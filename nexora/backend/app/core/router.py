"""
Nexora Model Router and Provider Adapter
Routes to appropriate model and handles provider communication
"""
import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from nexora.backend.app.models import ModelRegistry
from nexora.backend.app.schemas import RoutingMode
from nexora.backend.config.settings import get_settings

settings = get_settings()

# Provider response bodies are untrusted (they are produced by an external
# service). Error text derived from them is bounded and credential-redacted
# before it can reach a log line, an exception message, or an API response.
_MAX_PROVIDER_ERROR_CHARS = 400


def _sanitize_provider_error(text: Any, secret: Optional[str] = None) -> str:
    """Bound and redact provider-controlled error text (fail-closed).

    Every C0 control character (including CR/LF/TAB and ANSI escapes) is
    replaced with a space so a hostile provider body cannot forge log lines or
    smuggle terminal escapes into whatever sink eventually renders the message.
    """
    value = str(text) if text is not None else ""
    if secret:
        value = value.replace(secret, "[REDACTED]")
    value = "".join(ch if ord(ch) >= 32 else " " for ch in value)
    return value[:_MAX_PROVIDER_ERROR_CHARS]


class RoutingReason(str, Enum):
    """Reasons for model selection"""
    EXPLICIT_FIXED = "explicit_fixed"
    AUTO_SIMPLE_TASK = "auto_simple_task"
    AUTO_MODERATE_TASK = "auto_moderate_task"
    AUTO_COMPLEX_TASK = "auto_complex_task"
    MAX_ANALYSIS = "max_analysis"
    FALLBACK_AFTER_FAILURE = "fallback_after_failure"
    ONLY_MODEL_AVAILABLE = "only_model_available"


@dataclass
class RoutingDecision:
    """Model routing decision"""
    model: ModelRegistry
    reason: RoutingReason
    attempt_number: int
    alternatives_considered: List[str]


@dataclass
class InferenceRequest:
    """Normalized inference request"""
    model_id: str
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = 120
    idempotency_key: str = ""


@dataclass
class InferenceResponse:
    """Normalized inference response"""
    content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_id: str = ""
    finish_reason: str = ""
    raw_response: Dict[str, Any] = None
    cached_tokens: int = 0


class ModelRouter:
    """
    Model Router - selects appropriate model based on task, budget, and history.
    
    In Auto mode: uses task complexity, budget, context size, observed reliability.
    In Fixed mode: respects chosen model, stops with evidence if inadequate.
    """
    
    def __init__(self, enabled_models: List[ModelRegistry]):
        self.enabled_models = {m.model_id: m for m in enabled_models if m.is_enabled}
        self._verify_models()
    
    def _verify_models(self) -> None:
        """Verify at least one model is available"""
        if not self.enabled_models:
            raise ValueError("No enabled models in registry")
    
    def route(
        self,
        routing_mode: RoutingMode,
        requested_model_id: Optional[str],
        task_complexity: str = "moderate",
        context_size: int = 0,
        previous_failures: int = 0,
        attempt_number: int = 1,
        task_text: str = "",
        requires_tools: bool = False,
        requires_reasoning: bool = False,
    ) -> RoutingDecision:
        """
        Select model for inference.
        
        Args:
            routing_mode: Auto, Fixed, or Max
            requested_model_id: Model ID if fixed mode
            task_complexity: simple, moderate, complex
            context_size: Estimated context tokens
            previous_failures: Number of previous failed attempts
            attempt_number: Current attempt number
            task_text: The user's task description (for MAX mode analysis)
            requires_tools: Whether the task likely needs tool calling
            requires_reasoning: Whether the task likely needs reasoning capability
            
        Returns:
            RoutingDecision with selected model and reason
        """
        if routing_mode == RoutingMode.FIXED or routing_mode == "fixed":
            if requested_model_id:
                # 1. Exact key match
                if requested_model_id in self.enabled_models:
                    model = self.enabled_models[requested_model_id]
                    return RoutingDecision(
                        model=model,
                        reason=RoutingReason.EXPLICIT_FIXED,
                        attempt_number=attempt_number,
                        alternatives_considered=[m.model_id for m in self.enabled_models.values() if m.model_id != requested_model_id],
                    )
                # 2. Match by UUID string or case-insensitive model_id
                req_lower = str(requested_model_id).lower().strip()
                for m in self.enabled_models.values():
                    if str(getattr(m, "id", "")).lower() == req_lower or m.model_id.lower() == req_lower:
                        return RoutingDecision(
                            model=m,
                            reason=RoutingReason.EXPLICIT_FIXED,
                            attempt_number=attempt_number,
                            alternatives_considered=[x.model_id for x in self.enabled_models.values() if x.model_id != m.model_id],
                        )
                # 3. Match by tier or model name keyword (nano, super, ultra, lightning, gemini)
                for m in self.enabled_models.values():
                    if req_lower in m.model_id.lower() or req_lower in (m.display_name or "").lower() or req_lower == (m.tier or "").lower():
                        return RoutingDecision(
                            model=m,
                            reason=RoutingReason.EXPLICIT_FIXED,
                            attempt_number=attempt_number,
                            alternatives_considered=[x.model_id for x in self.enabled_models.values() if x.model_id != m.model_id],
                        )
                # Fall back with evidence if requested model cannot be found
                available = list(self.enabled_models.values())
                if available:
                    return RoutingDecision(
                        model=available[0],
                        reason=RoutingReason.ONLY_MODEL_AVAILABLE,
                        attempt_number=attempt_number,
                        alternatives_considered=[],
                    )
                raise ValueError("No models available")
        
        # MAX mode - intelligent task-aware model selection
        if routing_mode == RoutingMode.MAX or routing_mode == "max":
            return self._route_max_mode(
                task_text=task_text,
                task_complexity=task_complexity,
                context_size=context_size,
                requires_tools=requires_tools,
                requires_reasoning=requires_reasoning,
                attempt_number=attempt_number,
                previous_failures=previous_failures,
            )
        
        # Auto mode - rule-based routing
        # Simple tasks -> Nano
        # Moderate -> Super
        # Complex -> Ultra (if available and quality verified)
        
        # For now, use first available model with appropriate tier
        models_by_tier = {
            "nano": [m for m in self.enabled_models.values() if m.tier == "nano"],
            "super": [m for m in self.enabled_models.values() if m.tier == "super"],
            "ultra": [m for m in self.enabled_models.values() if m.tier == "ultra"],
        }
        
        alternatives = [m.model_id for m in self.enabled_models.values()]
        
        if task_complexity == "simple" and models_by_tier["nano"]:
            model = models_by_tier["nano"][0]
            reason = RoutingReason.AUTO_SIMPLE_TASK
        elif task_complexity == "moderate" and models_by_tier["super"]:
            model = models_by_tier["super"][0]
            reason = RoutingReason.AUTO_MODERATE_TASK
        elif task_complexity == "complex" and models_by_tier["ultra"]:
            model = models_by_tier["ultra"][0]
            reason = RoutingReason.AUTO_COMPLEX_TASK
        else:
            # Fallback to any available model
            available = list(self.enabled_models.values())
            model = available[0]
            reason = RoutingReason.ONLY_MODEL_AVAILABLE
        
        # If previous failure, consider fallback
        if previous_failures > 0 and attempt_number > 1:
            reason = RoutingReason.FALLBACK_AFTER_FAILURE
        
        return RoutingDecision(
            model=model,
            reason=reason,
            attempt_number=attempt_number,
            alternatives_considered=alternatives,
        )
    
    def _route_max_mode(
        self,
        task_text: str,
        task_complexity: str,
        context_size: int,
        requires_tools: bool,
        requires_reasoning: bool,
        attempt_number: int,
        previous_failures: int,
    ) -> RoutingDecision:
        """
        MAX mode: Intelligently select the best model based on task analysis.
        
        Selection criteria (in priority order):
        1. Task requirements (tools, reasoning, context)
        2. Model capabilities (tool calling, reasoning, context window)
        3. Tier appropriateness for task complexity
        4. Provider reliability (prefer primary/Nebius)
        5. Fallback handling for failures
        """
        # Categorize models by capability
        models_with_tools = [m for m in self.enabled_models.values() if m.supports_tools]
        models_with_reasoning = [m for m in self.enabled_models.values() if m.supports_reasoning]
        models_large_context = [m for m in self.enabled_models.values() if m.context_capacity >= 64000]
        primary_models = [m for m in self.enabled_models.values() if m.provider == "nebius"]
        
        # Group by tier
        models_by_tier = {
            "nano": [m for m in self.enabled_models.values() if m.tier == "nano"],
            "super": [m for m in self.enabled_models.values() if m.tier == "super"],
            "ultra": [m for m in self.enabled_models.values() if m.tier == "ultra"],
        }
        
        alternatives = [m.model_id for m in self.enabled_models.values()]
        reason = RoutingReason.MAX_ANALYSIS
        
        # Determine minimum tier needed based on task complexity
        if task_complexity == "simple":
            preferred_tiers = ["nano", "super", "ultra"]
        elif task_complexity == "moderate":
            preferred_tiers = ["super", "ultra", "nano"]
        else:  # complex
            preferred_tiers = ["ultra", "super", "nano"]
        
        # Score each model based on capability match
        scored_models = []
        for model in self.enabled_models.values():
            score = 0
            
            # Tier preference
            try:
                tier_idx = preferred_tiers.index(model.tier)
                score += (3 - tier_idx) * 10  # 30, 20, 10
            except ValueError:
                score += 5
            
            # Tool calling capability
            if requires_tools and model.supports_tools:
                score += 15
            elif requires_tools and not model.supports_tools:
                score -= 20
            
            # Reasoning capability
            if requires_reasoning and model.supports_reasoning:
                score += 15
            elif requires_reasoning and not model.supports_reasoning:
                score -= 10
            
            # Context window adequacy
            if context_size > 0:
                if model.context_capacity >= context_size * 1.5:
                    score += 10
                elif model.context_capacity >= context_size:
                    score += 5
                else:
                    score -= 15
            
            # Prefer primary provider (Nebius)
            if model.provider == "nebius":
                score += 10
            
            # Penalize if previous failures with this model
            # (In a more advanced implementation, we'd track per-model failures)
            if previous_failures > 0:
                score -= 5
            
            scored_models.append((score, model))
        
        # Sort by score descending
        scored_models.sort(key=lambda x: x[0], reverse=True)
        
        if scored_models:
            best_model = scored_models[0][1]
            
            # If we had previous failures, note it as fallback
            if previous_failures > 0 and attempt_number > 1:
                reason = RoutingReason.FALLBACK_AFTER_FAILURE
            
            return RoutingDecision(
                model=best_model,
                reason=reason,
                attempt_number=attempt_number,
                alternatives_considered=alternatives,
            )
        
        # Ultimate fallback
        available = list(self.enabled_models.values())
        return RoutingDecision(
            model=available[0],
            reason=RoutingReason.ONLY_MODEL_AVAILABLE,
            attempt_number=attempt_number,
            alternatives_considered=alternatives,
        )
    
    def get_model(self, model_id: str) -> Optional[ModelRegistry]:
        """Get model by ID"""
        return self.enabled_models.get(model_id)
    
    def list_enabled(self) -> List[ModelRegistry]:
        """List all enabled models"""
        return list(self.enabled_models.values())


class ProviderAdapter:
    """
    Provider Adapter - normalizes OpenAI-compatible API calls.
    
    Handles: timeouts, backoff, idempotency, token limits, redacted logs.
    Never silently switches models or hides provider failures.
    """
    
    def __init__(self):
        self.base_url = settings.NEBIUS_BASE_URL
        self.api_key = settings.NEBIUS_API_KEY
        self.timeout = settings.NEBIUS_TIMEOUT
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        """True when the Nebius API key is present."""
        return bool(self.api_key.strip())
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _error_text(self, response: httpx.Response) -> str:
        """Extract the provider error message without dumping the whole body.

        The body is untrusted: only the provider's own ``error.message`` (when
        present) is surfaced, and then bounded and credential-redacted.
        """
        try:
            body = response.json()
        except Exception:
            return _sanitize_provider_error(response.text, self.api_key)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("message"):
                return _sanitize_provider_error(error["message"], self.api_key)
            if isinstance(error, str):
                return _sanitize_provider_error(error, self.api_key)
        return _sanitize_provider_error(response.text, self.api_key)

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute inference request with retries and error handling.
        
        Args:
            request: Normalized inference request
            
        Returns:
            InferenceResponse with normalized output
            
        Raises:
            ProviderError: On provider failures (not hidden)
        """
        client = await self._get_client()
        
        # Prepare payload
        payload = {
            "model": request.model_id,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"
        
        # Idempotency key
        headers = {}
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        
        # Execute with exponential backoff
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                response = await client.post(
                    "chat/completions",
                    json=payload,
                    headers=headers,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return self._normalize_response(data, request.model_id)
                
                elif response.status_code == 429:
                    # Rate limited - back off
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                
                elif response.status_code >= 500:
                    # Server error - retry
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                
                else:
                    # Client error - don't retry
                    raise ProviderError(
                        f"Provider error {response.status_code}: {self._error_text(response)}",
                        status_code=response.status_code,
                    )
                    
            except httpx.TimeoutException:
                if attempt == max_retries - 1:
                    raise ProviderError("Provider request timed out")
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
                
            except httpx.RequestError as e:
                if attempt == max_retries - 1:
                    raise ProviderError(
                        "Provider request failed: "
                        + _sanitize_provider_error(str(e), self.api_key)
                    )
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
        
        raise ProviderError("Max retries exceeded")

    async def infer_stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """
        Execute streaming inference request yielding delta content chunks.
        
        Args:
            request: Normalized inference request
            
        Yields:
            str: Token delta chunks
            
        Raises:
            ProviderError: On provider failures
        """
        client = await self._get_client()
        
        payload = {
            "model": request.model_id,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"
        
        headers = {}
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
            
        try:
            async with client.stream(
                "POST",
                "chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    raw_bytes = await response.aread()
                    error_msg = _sanitize_provider_error(
                        raw_bytes.decode("utf-8", errors="replace"), self.api_key
                    )
                    raise ProviderError(
                        f"Provider error {response.status_code}: {error_msg}",
                        status_code=response.status_code,
                    )
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.TimeoutException:
            raise ProviderError("Provider stream request timed out")
        except httpx.RequestError as e:
            raise ProviderError(
                "Provider stream request failed: "
                + _sanitize_provider_error(str(e), self.api_key)
            )
    
    def _normalize_response(self, data: Dict[str, Any], model_id: str) -> InferenceResponse:
        """Normalize provider response"""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        
        tool_calls = message.get("tool_calls")
        if tool_calls:
            # Normalize tool calls
            normalized_calls = []
            for tc in tool_calls:
                args_raw = tc.get("function", {}).get("arguments", "{}")
                args_parse_error = None
                if isinstance(args_raw, str):
                    try:
                        args_parsed = json.loads(args_raw)
                    except json.JSONDecodeError as exc:
                        # Truncated/partial JSON (e.g. output token limit cut the
                        # arguments mid-string) must be surfaced, NOT silently
                        # coerced into {} — a silent {} made the orchestrator
                        # report missing-field errors (or worse, execute with
                        # empty content) and never told the model why.
                        args_parsed = {}
                        args_parse_error = (
                            f"Tool call arguments are not valid JSON "
                            f"(possibly truncated at the output token limit): {exc.msg} "
                            f"at char {exc.pos}"
                        )
                else:
                    args_parsed = args_raw or {}

                normalized_calls.append({
                    "id": tc.get("id"),
                    "name": tc.get("function", {}).get("name"),
                    "arguments": args_parsed,
                    "arguments_parse_error": args_parse_error,
                })
            tool_calls = normalized_calls
        
        usage = data.get("usage", {})
        prompt_details = usage.get("prompt_tokens_details", {}) or {}
        cached_tokens = int(prompt_details.get("cached_tokens", 0) or usage.get("cached_tokens", 0) or 0)
        
        return InferenceResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            model_id=data.get("model", model_id),
            finish_reason=choice.get("finish_reason", ""),
            raw_response=data,
            cached_tokens=cached_tokens,
        )


class ProviderError(Exception):
    """Provider-specific error that should not be hidden"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# Global instances
_model_router: Optional[ModelRouter] = None
_provider_adapter: Optional[ProviderAdapter] = None


def get_model_router(enabled_models: List[ModelRegistry]) -> ModelRouter:
    """Build a router from the current registry rows."""
    global _model_router
    _model_router = ModelRouter(enabled_models)
    return _model_router


def get_provider_adapter() -> ProviderAdapter:
    """Get or create provider adapter"""
    global _provider_adapter
    if _provider_adapter is None:
        _provider_adapter = ProviderAdapter()
    return _provider_adapter
