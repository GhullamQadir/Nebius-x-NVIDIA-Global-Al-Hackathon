"""
Bridge between the standalone ``packages/*`` layer and the Nexora backend.

The isolated packages built during the hackathon --

- ``packages/contracts``       provider-neutral ``ModelRequest`` / ``ModelResponse``
- ``packages/model_router``    tiered model selection with fallback rules
- ``packages/nebius_adapter``  ``ModelProvider`` ABC + Nebius and mock adapters

-- are standalone packages with their own unit tests and import nothing from
``nexora.*``. This module is the single place where the backend imports them,
so the packages keep their zero-coupling guarantee while the API can still
expose their routing decisions and adapter responses.

Nothing on the existing inference path changes: ``RunOrchestrator`` keeps
using ``core.router`` / ``core.provider_registry`` exactly as before. The
bridge only *translates* a package tier decision (low / moderate / high) into
a ``ModelRegistry`` row (nano / super / ultra) so both routers agree on one
answer, and it pushes backend settings into the package adapters' env-backed
configuration.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from packages.contracts.schemas import ModelRequest, ModelResponse
from packages.model_router import ModelRouter
from packages.nebius_adapter import MockModelProvider, NebiusAdapter
from packages.nebius_adapter.base import ModelProvider

from nexora.backend.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

#: Package tier key -> backend ``ModelRegistry.tier`` for the primary provider.
TIER_MAP: Dict[str, str] = {"low": "nano", "moderate": "super", "high": "ultra"}

#: Reverse of :data:`TIER_MAP`, used to label a backend decision.
TIER_LABEL: Dict[str, str] = {v: k for k, v in TIER_MAP.items()}
NEBIUS_MODELS_CACHE_TTL_SECONDS = 30


def sync_provider_config() -> bool:
    """Copy backend settings into the package adapter configuration.

    ``ModelProvider`` reads ``NEBIUS_BASE_URL`` / ``NEBIUS_API_KEY`` /
    ``NEBIUS_TIMEOUT`` from the environment at import time, which means the
    packages know nothing about ``nexora.backend.config.settings``. Writing the
    resolved settings onto the abstract base makes every subclass (the Nebius
    adapter included) inherit them without the packages importing the backend.

    Returns ``True`` when a usable API key was handed to the adapter.
    """
    if settings.NEBIUS_BASE_URL:
        ModelProvider.base_url = settings.NEBIUS_BASE_URL
    if settings.NEBIUS_TIMEOUT:
        ModelProvider.timeout = float(settings.NEBIUS_TIMEOUT)
    if settings.NEBIUS_API_KEY:
        ModelProvider.api_key = settings.NEBIUS_API_KEY
    return bool(ModelProvider.api_key)


class PackageBridge:
    """Facade the API layer uses to talk to ``packages/*``."""

    def __init__(self) -> None:
        sync_provider_config()
        self.router = ModelRouter()
        self._mock: Optional[MockModelProvider] = None
        self._nebius: Optional[NebiusAdapter] = None
        self._nebius_models: Optional[List[str]] = None
        self._nebius_models_fetched_at = 0.0
        self._nebius_models_lock = threading.Lock()
        self._nebius_models_refresh: Optional[threading.Event] = None

    # ------------------------------------------------------------------
    # adapters
    # ------------------------------------------------------------------
    @property
    def mock(self) -> MockModelProvider:
        if self._mock is None:
            self._mock = MockModelProvider()
        return self._mock

    @property
    def nebius(self) -> NebiusAdapter:
        if self._nebius is None:
            self._nebius = NebiusAdapter()
        return self._nebius

    @property
    def nebius_configured(self) -> bool:
        return bool(ModelProvider.api_key and ModelProvider.base_url)

    def providers(self) -> List[Dict[str, Any]]:
        """Status of every ``ModelProvider`` implementation the packages ship."""
        available_models: List[str] = []
        if self.nebius_configured:
            refresh_event: Optional[threading.Event] = None
            should_refresh = False
            with self._nebius_models_lock:
                now = time.monotonic()
                has_cached_models = self._nebius_models is not None
                cache_is_fresh = (
                    has_cached_models
                    and now - self._nebius_models_fetched_at
                    < NEBIUS_MODELS_CACHE_TTL_SECONDS
                )
                if cache_is_fresh:
                    available_models = list(self._nebius_models or [])
                elif self._nebius_models_refresh is not None:
                    refresh_event = self._nebius_models_refresh
                    if self._nebius_models is not None:
                        available_models = list(self._nebius_models)
                else:
                    refresh_event = threading.Event()
                    self._nebius_models_refresh = refresh_event
                    should_refresh = True

            if should_refresh:
                assert refresh_event is not None
                try:
                    refreshed_models = self.nebius.fetch_available_models()
                except Exception:
                    with self._nebius_models_lock:
                        self._nebius_models = []
                        self._nebius_models_fetched_at = time.monotonic()
                        self._nebius_models_refresh = None
                        refresh_event.set()
                    raise
                with self._nebius_models_lock:
                    self._nebius_models = refreshed_models
                    self._nebius_models_fetched_at = time.monotonic()
                    self._nebius_models_refresh = None
                    available_models = list(refreshed_models)
                    refresh_event.set()
            elif refresh_event is not None and not has_cached_models:
                refresh_event.wait()
                with self._nebius_models_lock:
                    available_models = list(self._nebius_models or [])

        return [
            {
                "name": "nebius",
                "adapter": f"{NebiusAdapter.__module__}.{NebiusAdapter.__name__}",
                "kind": "live",
                "configured": self.nebius_configured,
                "base_url": ModelProvider.base_url or None,
                "timeout_ms": ModelProvider.timeout * 1000,
                "available_models": available_models,
                "note": None
                if self.nebius_configured
                else "NEBIUS_API_KEY is empty in backend settings",
            },
            {
                "name": "mock",
                "adapter": f"{MockModelProvider.__module__}.{MockModelProvider.__name__}",
                "kind": "offline",
                "configured": True,
                "base_url": None,
                "timeout_ms": None,
                "available_models": list(MockModelProvider().fetch_available_models()),
                "note": "no network calls — used by tests and the demo path",
            },
        ]

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------
    def select(
        self,
        task_complexity: str = "low",
        preferred_model: Optional[str] = None,
        registry_models: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        """Run the package router, then translate its answer for the backend.

        The package router only knows provider-native ids
        (``nvidia/...``) and the low/moderate/high complexity keys; the
        backend registry knows ``nemotron-3-*`` rows and the nano/super/ultra
        tiers. ``decide`` bridges the two vocabularies so the UI and the
        orchestrator read one consistent routing decision.
        """
        request = ModelRequest(
            prompt="routing probe",
            task_complexity=task_complexity,
            preferred_model=preferred_model,
        )
        # An empty availability list makes the package router answer purely
        # from its tier table -- the availability-aware fallback is exercised
        # separately by passing registry ids in ``available_models``.
        package_model, reason = self.router.select_model(request, [])

        tier = next(
            (key for key, model in self.router.MODEL_TIERS.items() if model == package_model),
            None,
        )

        models = list(registry_models or [])
        provider_models = [
            m for m in models if (getattr(m, "provider", None) or "nebius") == "nebius"
        ]
        by_tier = {
            getattr(m, "tier", None): m for m in provider_models if getattr(m, "is_enabled", True)
        }
        by_id = {getattr(m, "model_id", None): m for m in models}

        registry_row = None
        if preferred_model:
            registry_row = by_id.get(preferred_model)
        elif tier:
            registry_row = by_tier.get(TIER_MAP[tier])

        alternatives = [
            getattr(m, "model_id", "")
            for m in provider_models
            if m is not registry_row
        ]

        return {
            "task_complexity": task_complexity,
            "preferred_model": preferred_model,
            "package_model_id": package_model,
            "routing_reason": reason,
            "package_tier": tier,
            "registry_tier": getattr(registry_row, "tier", None)
            or (TIER_MAP.get(tier) if tier else None),
            "registry_model_id": getattr(registry_row, "model_id", None),
            "registry_display_name": getattr(registry_row, "display_name", None),
            "provider": getattr(registry_row, "provider", None) or "nebius",
            "alternatives_considered": alternatives,
        }

    def routing_overview(self, registry_models: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
        """Everything ``GET /packages/routing`` reports."""
        models = list(registry_models or [])
        return {
            "packages": ["packages.contracts", "packages.model_router", "packages.nebius_adapter"],
            "router": {
                "class": f"{ModelRouter.__module__}.{ModelRouter.__name__}",
                "tiers": dict(self.router.MODEL_TIERS),
                "tier_map": dict(TIER_MAP),
            },
            "providers": self.providers(),
            "config_synced": self.nebius_configured,
            "decisions": [
                self.select(complexity, None, models)
                for complexity in ("low", "moderate", "high")
            ],
        }

    # ------------------------------------------------------------------
    # completion
    # ------------------------------------------------------------------
    def build_request(
        self,
        prompt: str,
        task_complexity: str = "low",
        tools: Optional[List[Dict[str, Any]]] = None,
        token_budget: int = 1000,
        preferred_model: Optional[str] = None,
    ) -> ModelRequest:
        return ModelRequest(
            prompt=prompt,
            tools=tools,
            task_complexity=task_complexity,
            token_budget=token_budget,
            preferred_model=preferred_model,
        )

    def complete(
        self,
        prompt: str,
        provider: str = "mock",
        task_complexity: str = "low",
        tools: Optional[List[Dict[str, Any]]] = None,
        token_budget: int = 1000,
        preferred_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one completion through a package adapter and normalise the result."""
        request = self.build_request(
            prompt,
            task_complexity=task_complexity,
            tools=tools,
            token_budget=token_budget,
            preferred_model=preferred_model,
        )

        if provider == "nebius":
            if not self.nebius_configured:
                raise NotConfigured(
                    "The Nebius adapter has no NEBIUS_API_KEY in backend settings. "
                    "Set it (or use provider='mock') to run a live completion."
                )
            response: ModelResponse = self.nebius.complete(request)
        else:
            response = self.mock.complete(request)

        payload = response.model_dump()
        payload["provider"] = provider
        return payload


class NotConfigured(RuntimeError):
    """Raised when a live provider is requested without credentials."""


_bridge: Optional[PackageBridge] = None


def get_package_bridge() -> PackageBridge:
    """Process-wide bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = PackageBridge()
    return _bridge
