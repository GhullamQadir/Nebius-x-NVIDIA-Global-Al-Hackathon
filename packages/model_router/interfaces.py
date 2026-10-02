"""Interface contracts for the Model Router package."""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.context_optimizer.interfaces import ContextProvenance

__all__ = ["ModelRequest", "ModelResponse", "ModelProvider", "ModelRouter"]


class ModelRequest(BaseModel):
    """A generation request targeted at a specific model."""

    model_config = ConfigDict(frozen=True)

    prompt: str
    model_name: str
    max_tokens: int = Field(gt=0)


class ModelResponse(BaseModel):
    """The result of a generation request, with token accounting and provenance."""

    model_config = ConfigDict(frozen=True)

    text: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    model_used: str
    provenance: Optional[ContextProvenance] = None


class ModelProvider(ABC):
    """Any backend capable of fulfilling a `ModelRequest`."""

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a completion for `request`."""
        ...


class ModelRouter(ABC):
    """Chooses which model should service a task of a given complexity."""

    @abstractmethod
    def select_model(self, task_complexity: str) -> str:
        """Return the model name for `task_complexity` (e.g. 'simple' -> 'nemotron-nano')."""
        ...
