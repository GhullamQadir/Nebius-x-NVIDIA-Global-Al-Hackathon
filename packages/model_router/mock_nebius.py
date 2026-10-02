"""Offline mock Nebius provider used for tests and local development.

Mimics the shape of an OpenAI-compatible `/chat/completions` response without
making any network calls.
"""

from packages.context_optimizer.interfaces import ContextProvenance

from .interfaces import ModelProvider, ModelRequest, ModelResponse

__all__ = ["MockNebiusProvider"]

MOCK_COMPLETION = "This is a mock completion used for local development only."
DEFAULT_MODEL = "nemotron-nano"


class MockNebiusProvider(ModelProvider):
    """Deterministic `ModelProvider` that makes no external API calls."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        prompt_tokens = max(1, len(request.prompt.split()))
        completion_tokens = min(len(MOCK_COMPLETION.split()), request.max_tokens)
        return ModelResponse(
            text=MOCK_COMPLETION,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model_used=request.model_name or DEFAULT_MODEL,
            provenance=ContextProvenance(
                source_type="tool_output",
                file_path="mock://mock_nebius",
                trust_level="untrusted",
            ),
        )

    def chat_completion(self, request: ModelRequest) -> dict:
        """Return the raw OpenAI-compatible response payload."""
        response = self.generate(request)
        return {
            "id": "chatcmpl-mock-000",
            "object": "chat.completion",
            "model": response.model_used,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response.text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
        }
