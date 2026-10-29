"""
Google Gemini Provider Adapter -- SECONDARY provider for Nexora.

Design contract (deliberately identical to the primary adapter's):

* Implements the same duck-typed interface as :class:`ProviderAdapter`, namely
  ``async infer(InferenceRequest) -> InferenceResponse`` plus ``async close()``,
  so it is a drop-in for the primary adapter behind the provider registry.
* Reuses :class:`InferenceRequest`, :class:`InferenceResponse` and
  :class:`ProviderError` imported read-only from ``core.router``. Nothing in
  ``core.router`` is modified by this module.
* Never silently switches models or hides provider failures. A Gemini failure
  surfaces as a :class:`ProviderError` like any other provider failure; the
  registry does not retry a Gemini failure on Nebius or vice versa.

The wire format is different (Gemini's ``generateContent`` is not
OpenAI-compatible), so this module owns a full request/response translation
layer:

    OpenAI-ish                          Gemini
    ------------------------------      --------------------------------------
    messages[].role/content             systemInstruction + contents[].parts
    tools[]                             tools[].functionDeclarations
    tool_choice "auto"                  toolConfig.functionCallingConfig.mode
    choices[0].message.tool_calls[]     candidates[0].content.parts[].functionCall
    usage.prompt_tokens                 usageMetadata.promptTokenCount
    usage.completion_tokens             usageMetadata.candidatesTokenCount

Three Gemini-specific quirks are handled explicitly, because each one is a
silent failure mode otherwise:

1. ``generateContent`` rejects any JSON-Schema keyword it does not know with a
   400 ``Unknown name "additionalProperties"``. Nexora's ``TOOL_SCHEMAS`` are
   JSON Schema, not Gemini ``Schema``, so they are sanitised by
   :func:`sanitize_json_schema` before being sent.
2. ``thinkingBudget: 0`` is rejected with a 400 by models that do not support
   thinking (``gemini-3.5-flash-lite``), and the same config intermittently
   answers 503 on models that do. ``thinkingConfig`` is therefore only sent
   for an explicitly positive budget.
3. ``maxOutputTokens`` is a budget for thinking *and* output together. Leaving
   it alone can silently truncate a tool call on complex steps, so
   :func:`resolve_max_output_tokens` keeps a reserve for the visible answer.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from nexora.backend.app.core.router import (
    InferenceRequest,
    InferenceResponse,
    ProviderError,
)
from nexora.backend.config.settings import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

#: Value stored in ``ModelRegistry.provider`` for every Gemini-served model.
GEMINI_PROVIDER_NAME = "gemini"

#: HTTP statuses worth another attempt (quota, transient upstream, overload).
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: JSON-Schema keywords Gemini's ``Schema`` accepts. Everything else is dropped
#: during translation; see the module docstring for why that matters.
GEMINI_SCHEMA_KEYS = frozenset({
    "type", "format", "title", "description", "nullable", "enum",
    "maxItems", "minItems", "properties", "required", "anyOf",
    "propertyOrdering", "default", "example", "items",
})

#: Gemini's ``FunctionCallingConfig`` mode names.
FUNCTION_CALLING_MODES = {
    "auto": "AUTO",
    "none": "NONE",
    "required": "ANY",
    "any": "ANY",
}

#: Visible output tokens always left free of the thinking budget so a tool call
#: can never be truncated by the model's internal reasoning.
OUTPUT_TOKEN_RESERVE = 1024


def sanitize_json_schema(schema: Any) -> Any:
    """Reduce a JSON Schema to the subset Gemini's ``Schema`` accepts.

    Recursive, so nested ``properties``/``items`` are cleaned too. Unknown
    keywords are dropped rather than rejected, which is what makes Nexora's
    existing ``TOOL_SCHEMAS`` reusable without being edited.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: Dict[str, Any] = {}
    for key, value in schema.items():
        if key not in GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                name: sanitize_json_schema(sub) for name, sub in value.items()
            }
        elif key == "items":
            cleaned[key] = sanitize_json_schema(value)
        elif key == "anyOf" and isinstance(value, list):
            cleaned[key] = [sanitize_json_schema(option) for option in value]
        elif key == "enum" and isinstance(value, list):
            # Gemini enum members must be strings.
            cleaned[key] = [str(option) for option in value]
        elif key in ("required", "propertyOrdering") and isinstance(value, list):
            cleaned[key] = [str(option) for option in value]
        else:
            cleaned[key] = value

    # Gemini rejects an "object" schema that declares properties without a type.
    if cleaned.get("type") == "object" and "properties" not in cleaned:
        cleaned.setdefault("properties", {})
    if cleaned.get("type") == "array" and "items" not in cleaned:
        cleaned.setdefault("items", {"type": "string"})

    return cleaned


def parse_thinking_budgets(raw: str) -> Dict[str, int]:
    """Parse ``"model:tokens,model2:tokens"`` into ``{model: tokens}``."""
    budgets: Dict[str, int] = {}
    for chunk in (raw or "").split(","):
        model, _, value = chunk.partition(":")
        model = model.strip()
        if not model or not value.strip().lstrip("-").isdigit():
            continue
        budgets[model] = int(value.strip())
    return budgets


def resolve_max_output_tokens(model_id: str, requested: int, thinking_budget: int) -> int:
    """Split the requested output budget into thinking reserve + visible output.

    ``requested`` comes from ``ModelRegistry.max_output_tokens``. Gemini counts
    thinking tokens against ``maxOutputTokens``, so the visible allowance is
    whatever is left after the thinking reserve, floored at
    :data:`OUTPUT_TOKEN_RESERVE`.
    """
    hard_cap = settings.GEMINI_MAX_OUTPUT_TOKENS or requested
    budget = min(int(requested or 0), hard_cap)
    visible = budget - max(thinking_budget, 0)
    if visible < OUTPUT_TOKEN_RESERVE:
        visible = OUTPUT_TOKEN_RESERVE
        budget = visible + max(thinking_budget, 0)
    return budget


class GeminiProviderAdapter:
    """
    Gemini adapter - normalizes ``generateContent`` calls onto Nexora's
    ``InferenceRequest`` / ``InferenceResponse`` contract.

    Registered as a secondary provider: it only ever serves models whose
    ``ModelRegistry.provider`` is ``"gemini"``. It is never consulted for a
    Nebius model and never used as a fallback when Nebius fails.
    """

    provider_name = GEMINI_PROVIDER_NAME

    def __init__(self) -> None:
        self.base_url = settings.GEMINI_BASE_URL.rstrip("/")
        self.api_key = settings.GEMINI_API_KEY
        self.timeout = settings.GEMINI_TIMEOUT
        self.max_retries = max(1, settings.GEMINI_MAX_RETRIES)
        self.retry_base_delay = max(0.1, settings.GEMINI_RETRY_BASE_DELAY)
        self.rate_limit_base_delay = max(
            self.retry_base_delay, settings.GEMINI_RATE_LIMIT_BASE_DELAY
        )
        self._thinking_budgets = parse_thinking_budgets(settings.GEMINI_THINKING_BUDGETS)
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """True when a key is present and the provider is switched on."""
        return bool(self.api_key) and bool(settings.GEMINI_ENABLED)

    def thinking_budget_for(self, model_id: str) -> int:
        """Per-model thinking budget, falling back to the global setting."""
        if model_id in self._thinking_budgets:
            return self._thinking_budgets[model_id]
        return max(settings.GEMINI_THINKING_BUDGET, 0)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # request translation
    # ------------------------------------------------------------------

    @staticmethod
    def _content_to_parts(content: Any) -> List[Dict[str, Any]]:
        """Normalize an OpenAI-ish ``content`` value into Gemini ``parts``."""
        if content is None:
            return []
        if isinstance(content, str):
            return [{"text": content}] if content else []
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        parts: List[Dict[str, Any]] = []
        for block in content:
            if isinstance(block, str):
                if block:
                    parts.append({"text": block})
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append({"text": text})
        return parts

    def _split_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Split OpenAI messages into ``(systemInstruction, contents)``."""
        system_parts: List[Dict[str, Any]] = []
        contents: List[Dict[str, Any]] = []

        for message in messages or []:
            if not isinstance(message, dict):
                continue
            role = (message.get("role") or "user").lower()
            parts = self._content_to_parts(message.get("content"))
            if not parts:
                continue

            if role in ("system", "developer"):
                system_parts.extend(parts)
            elif role in ("assistant", "model"):
                contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                # Gemini expects tool output folded back into a user turn.
                contents.append({"role": "user", "parts": parts})
            else:
                contents.append({"role": "user", "parts": parts})

        # Gemini requires the conversation to start with a user turn. Fold any
        # leading model turns into the first user turn rather than dropping
        # them, so a resumed conversation keeps its context.
        leading: List[Dict[str, Any]] = []
        while contents and contents[0]["role"] != "user":
            leading.extend(contents.pop(0).get("parts") or [])
        if leading:
            if contents:
                contents[0]["parts"] = leading + contents[0]["parts"]
            else:
                contents.append({"role": "user", "parts": leading})

        system_instruction = (
            {"parts": system_parts} if system_parts else None
        )
        return system_instruction, contents

    @staticmethod
    def _to_function_declarations(
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Translate Nexora/OpenAI tool schemas into Gemini declarations.

        Accepts both the bare ``{name, description, parameters}`` shape that
        :meth:`ToolRouter.get_all_schemas` returns and the OpenAI
        ``{type: "function", function: {...}}`` envelope.
        """
        declarations: List[Dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            body = tool.get("function") if tool.get("type") == "function" else tool
            if not isinstance(body, dict):
                continue
            name = body.get("name")
            if not name:
                continue

            parameters = body.get("parameters") or body.get("input_schema")
            declaration: Dict[str, Any] = {
                "name": str(name),
                "description": str(body.get("description") or f"Tool: {name}"),
            }
            if isinstance(parameters, dict) and parameters:
                declaration["parameters"] = sanitize_json_schema(parameters)
            else:
                declaration["parameters"] = {"type": "object", "properties": {}}
            declarations.append(declaration)
        return declarations

    @staticmethod
    def _to_tool_config(tool_choice: Optional[str]) -> Optional[Dict[str, Any]]:
        """Translate Nexora's ``tool_choice`` into ``toolConfig``."""
        if not tool_choice:
            return None
        choice = str(tool_choice).strip()
        mode = FUNCTION_CALLING_MODES.get(choice.lower())
        if mode is None:
            # A bare function name means "must call exactly this".
            return {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [choice],
                }
            }
        if mode == "NONE":
            return {"functionCallingConfig": {"mode": "NONE"}}
        return {"functionCallingConfig": {"mode": mode}}

    def build_payload(self, request: InferenceRequest) -> Dict[str, Any]:
        """Build the ``generateContent`` request body."""
        model_id = self._model_name(request.model_id)
        thinking_budget = self.thinking_budget_for(model_id)

        system_instruction, contents = self._split_messages(request.messages)
        if not contents:
            raise ProviderError(
                "Gemini request has no user content to send",
                status_code=400,
            )

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": resolve_max_output_tokens(
                    model_id, request.max_tokens, thinking_budget
                ),
            },
        }

        # ``thinkingConfig`` is only sent for an explicitly positive budget.
        # ``thinkingBudget: 0`` is rejected with HTTP 400 by models that do not
        # support thinking (verified against gemini-3.5-flash-lite), and
        # omitting the block leaves the model on its own default, which is what
        # a zero budget means anyway.
        if thinking_budget > 0:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": thinking_budget
            }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        if request.tools:
            declarations = self._to_function_declarations(request.tools)
            if declarations:
                payload["tools"] = [{"functionDeclarations": declarations}]
                tool_config = self._to_tool_config(request.tool_choice)
                if tool_config:
                    payload["toolConfig"] = tool_config

        return payload

    @staticmethod
    def _model_name(model_id: str) -> str:
        """Strip the ``models/`` prefix; Gemini accepts it but we normalize."""
        name = (model_id or "").strip()
        return name[len("models/"):] if name.startswith("models/") else name

    # ------------------------------------------------------------------
    # inference
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int, status_code: Optional[int] = None) -> float:
        """Exponential backoff, capped so a run cannot stall indefinitely.

        Rate limits get a longer base than server errors: a 429 does not clear
        in two seconds, so retrying quickly just burns the remaining quota.
        """
        base = (
            self.rate_limit_base_delay
            if status_code == 429
            else self.retry_base_delay
        )
        return min(base * (2 ** attempt), 60.0)

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute a ``generateContent`` call with retries and error handling.

        Args:
            request: Normalized inference request

        Returns:
            InferenceResponse with normalized output

        Raises:
            ProviderError: On provider failures (not hidden)
        """
        if not self.is_configured:
            raise ProviderError(
                "Gemini provider is not configured "
                "(set GEMINI_API_KEY and GEMINI_ENABLED=true)"
            )

        client = await self._get_client()
        model_id = self._model_name(request.model_id)
        payload = self.build_payload(request)
        url = f"/models/{model_id}:generateContent"

        headers: Dict[str, str] = {}
        if request.idempotency_key:
            headers["X-Idempotency-Key"] = request.idempotency_key

        last_error: Optional[str] = None
        last_status: Optional[int] = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    return self._normalize_response(
                        response.json(), request.model_id
                    )

                if response.status_code in RETRYABLE_STATUS:
                    last_status = response.status_code
                    last_error = self._error_text(response)
                    if attempt == self.max_retries - 1:
                        break
                    delay = self._backoff_delay(attempt, response.status_code)
                    logger.warning(
                        "gemini retryable error %s (attempt %s/%s, retrying in %.1fs): %s",
                        response.status_code, attempt + 1, self.max_retries,
                        delay, last_error,
                    )
                    await asyncio.sleep(delay)
                    continue

                # 4xx other than throttling is a request bug -- never retried.
                raise ProviderError(
                    f"Gemini error {response.status_code}: {self._error_text(response)}",
                    status_code=response.status_code,
                )

            except httpx.TimeoutException:
                last_status = None
                last_error = f"timed out after {self.timeout}s"
                if attempt == self.max_retries - 1:
                    break
                await asyncio.sleep(self._backoff_delay(attempt))

            except httpx.RequestError as exc:
                last_status = None
                last_error = str(exc)
                if attempt == self.max_retries - 1:
                    break
                await asyncio.sleep(self._backoff_delay(attempt))

        suffix = f" (HTTP {last_status})" if last_status else ""
        raise ProviderError(
            f"Gemini request failed after {self.max_retries} attempt(s){suffix}: "
            f"{last_error}"
        )

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """Extract Gemini's error message without dumping the whole body."""
        try:
            body = response.json()
        except Exception:
            return response.text[:400]
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])[:400]
        return response.text[:400]

    # ------------------------------------------------------------------
    # response translation
    # ------------------------------------------------------------------

    def _normalize_response(
        self,
        data: Dict[str, Any],
        model_id: str,
    ) -> InferenceResponse:
        """Normalize a ``generateContent`` response onto ``InferenceResponse``."""
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            blocked = feedback.get("blockReason")
            detail = f"Gemini returned no candidates (prompt blocked: {blocked})" if blocked \
                else "Gemini returned no candidates"
            message = feedback.get("blockReasonMessage")
            if message:
                detail = f"{detail}: {message}"
            raise ProviderError(detail, status_code=400)

        candidate = candidates[0] or {}
        parts = ((candidate.get("content") or {}).get("parts")) or []

        text_chunks: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue

            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                name = function_call.get("name")
                if not name:
                    continue
                arguments = function_call.get("args")
                tool_calls.append({
                    # ``_process_tool_call`` expects a dict, not a JSON string.
                    "id": function_call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    "name": str(name),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                })
                continue

            if part.get("thought") is True:
                # Reasoning trace, not part of the model's answer.
                continue

            text = part.get("text")
            if isinstance(text, str) and text:
                text_chunks.append(text)

        usage = data.get("usageMetadata") or {}
        candidates_tokens = int(usage.get("candidatesTokenCount") or 0)
        thoughts_tokens = int(usage.get("thoughtsTokenCount") or 0)

        finish_reason = candidate.get("finishReason") or ""
        if not text_chunks and not tool_calls and finish_reason:
            detail = f"Gemini produced no usable output (finishReason={finish_reason}"
            detail += f", {candidate['finishMessage']}" if candidate.get("finishMessage") else ")"
            raise ProviderError(detail, status_code=400)

        return InferenceResponse(
            content="".join(text_chunks) if text_chunks else None,
            tool_calls=tool_calls,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            # Thinking tokens are billed by Google, so they are reported as
            # output rather than silently dropped from the run's budget.
            output_tokens=candidates_tokens + thoughts_tokens,
            total_tokens=int(usage.get("totalTokenCount") or 0),
            model_id=data.get("modelVersion") or model_id,
            finish_reason=finish_reason,
            raw_response=data,
            cached_tokens=int(usage.get("cachedContentTokenCount") or 0),
        )