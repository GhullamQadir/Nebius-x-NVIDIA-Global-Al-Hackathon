"""
Provider Registry - multi-provider dispatch for Nexora.

``core.router`` holds the primary (Nebius) adapter and stays the single source
of truth for the primary provider. This module adds dispatch on top so a second
provider can be plugged in without editing ``core.router``.

Routing rules, in priority order:

1. **Explicit model wins.** The provider is whatever ``ModelRegistry.provider``
   says for the routed ``model_id``. A Gemini-served model always goes to
   Gemini, a Nebius-served model always goes to Nebius.
2. **Unknown model falls back to the primary provider**, so a registry row with
   a blank or unrecognised ``provider`` keeps working exactly as before.
3. **No cross-provider failover.** A provider failure propagates to the caller
   as :class:`ProviderError`. The registry never retries a Gemini call on
   Nebius (or the reverse), mirroring the primary adapter's own "never silently
   switches models or hides provider failures" contract.

Because ``infer()`` has the same signature as ``ProviderAdapter.infer()``, the
registry is a drop-in replacement in ``RunOrchestrator`` and the inference call
site needs no change.
"""
import logging
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

from nexora.backend.app.core.gemini_provider import (
    GEMINI_PROVIDER_NAME,
    GeminiProviderAdapter,
)
from nexora.backend.app.core.router import (
    InferenceRequest,
    InferenceResponse,
    ProviderError,
    get_provider_adapter,
)
from nexora.backend.config.settings import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

#: Value in ``ModelRegistry.provider`` for the primary provider.
PRIMARY_PROVIDER = "nebius"


class ProviderRegistry:
    """
    Resolves and dispatches to the adapter that owns a routed model.

    Args:
        models: Optional ``ModelRegistry`` rows (or any objects exposing
            ``model_id`` / ``provider``) used to build the provider map.
    """

    #: Providers this build knows how to serve. A model naming one of these is
    #: never handed to a different provider -- if its adapter is unavailable the
    #: call fails loudly instead.
    SUPPORTED_PROVIDERS = frozenset({PRIMARY_PROVIDER, GEMINI_PROVIDER_NAME})

    def __init__(self, models: Optional[Iterable[Any]] = None) -> None:
        self._adapters: Dict[str, Any] = {}
        self._model_provider: Dict[str, str] = {}
        self.primary_provider = PRIMARY_PROVIDER

        self._register(self.primary_provider, get_provider_adapter())

        if settings.GEMINI_ENABLED:
            gemini = GeminiProviderAdapter()
            self._register(gemini.provider_name, gemini)
        else:
            logger.info("gemini secondary provider disabled by GEMINI_ENABLED")

        if models is not None:
            self.sync_models(models)

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def _register(self, name: str, adapter: Any) -> None:
        self._adapters[name] = adapter
        logger.debug("registered provider adapter: %s", name)

    def register_adapter(self, name: str, adapter: Any) -> None:
        """Register an extra adapter (used by tests and future providers)."""
        self._register(name, adapter)

    def sync_models(self, models: Iterable[Any]) -> None:
        """Rebuild the ``model_id -> provider`` map from registry rows."""
        mapping: Dict[str, str] = {}
        for model in models or []:
            model_id = getattr(model, "model_id", None)
            if not model_id:
                continue
            mapping[str(model_id)] = str(
                getattr(model, "provider", None) or self.primary_provider
            )
        self._model_provider = mapping

    def register_model(self, model_id: str, provider: str) -> None:
        """Bind a single ``model_id`` to a provider."""
        self._model_provider[str(model_id)] = str(provider or self.primary_provider)

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    @property
    def registered_providers(self) -> List[str]:
        """Names of every adapter currently registered."""
        return sorted(self._adapters)

    def provider_for(self, model_id: str) -> str:
        """Provider that owns ``model_id``, defaulting to the primary."""
        return self._model_provider.get(str(model_id), self.primary_provider)

    def adapter_for(self, model_id: str) -> Any:
        """Adapter that owns ``model_id``.

        A model whose provider is one this build supports but has no adapter
        for (Gemini disabled, say) is an error, not a reason to send its
        model_id to a different endpoint. An unrecognised provider *label* --
            a typo, or a legacy row -- does fall back to the primary provider
            so existing rows keep working.
        """
        provider = self.provider_for(model_id)
        adapter = self._adapters.get(provider)
        if adapter is None:
            if provider in self.SUPPORTED_PROVIDERS:
                raise ProviderError(
                    f"Provider {provider!r} is not available for model "
                    f"{model_id!r}: no adapter is registered "
                    f"(registered: {', '.join(self.registered_providers) or 'none'})",
                    status_code=503,
                )
            logger.warning(
                "unknown provider %r on model %s - using %s",
                provider, model_id, self.primary_provider,
            )
            return self._adapters[self.primary_provider]
        return adapter

    def is_model_servable(self, model_id: str) -> bool:
        """True when the owning adapter is usable (key present, enabled)."""
        try:
            adapter = self.adapter_for(model_id)
        except ProviderError:
            return False
        return bool(getattr(adapter, "is_configured", True))

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Dispatch an inference request to the owning provider.

        Same contract as ``ProviderAdapter.infer`` so call sites are unchanged.
        """
        provider = self.provider_for(request.model_id)
        adapter = self.adapter_for(request.model_id)

        if not getattr(adapter, "is_configured", True):
            raise ProviderError(
                f"Provider {provider!r} is not configured for model "
                f"{request.model_id!r}",
                status_code=503,
            )

        return await adapter.infer(request)

    async def infer_stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """
        Dispatch a streaming inference request to the owning provider.
        """
        provider = self.provider_for(request.model_id)
        adapter = self.adapter_for(request.model_id)

        if not getattr(adapter, "is_configured", True):
            raise ProviderError(
                f"Provider {provider!r} is not configured for model "
                f"{request.model_id!r}",
                status_code=503,
            )

        if hasattr(adapter, "infer_stream"):
            async for chunk in adapter.infer_stream(request):
                yield chunk
        else:
            resp = await adapter.infer(request)
            if resp.content:
                yield resp.content

    async def close(self) -> None:
        """Close every adapter that owns an HTTP client."""
        for name, adapter in self._adapters.items():
            close = getattr(adapter, "close", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:  # pragma: no cover - best effort teardown
                logger.warning("failed to close provider %s: %s", name, exc)


# Global instance
_provider_registry: Optional[ProviderRegistry] = None


def get_provider_registry(
    models: Optional[Iterable[Any]] = None,
) -> ProviderRegistry:
    """Get or create the process-wide provider registry."""
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = ProviderRegistry(models)
    elif models is not None:
        _provider_registry.sync_models(models)
    return _provider_registry