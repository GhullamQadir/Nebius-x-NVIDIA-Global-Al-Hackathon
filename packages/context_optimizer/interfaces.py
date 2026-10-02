"""Interface contracts for the Context Optimizer package."""

from abc import ABC, abstractmethod
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ContextProvenance",
    "ContextBudget",
    "RepoFileIndex",
    "RepositoryIndexer",
    "ContextRanker",
    "ContextCompressor",
    "ContextCache",
]


class ContextProvenance(BaseModel):
    """Origin and trust classification of a piece of context."""

    model_config = ConfigDict(frozen=True)

    source_type: str
    file_path: str
    trust_level: Literal["trusted", "untrusted"]


class ContextBudget(BaseModel):
    """Token limits for a single context request."""

    model_config = ConfigDict(frozen=True)

    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)

    @property
    def max_total_tokens(self) -> int:
        return self.max_input_tokens + self.max_output_tokens


class RepoFileIndex(BaseModel):
    """Per-file metadata produced by a repository indexer."""

    model_config = ConfigDict(frozen=True)

    path: str
    language: str
    size: int = Field(ge=0)
    hash: str
    imports: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)


class RepositoryIndexer(ABC):
    """Indexes a repository and retrieves budget-aware relevant context."""

    @abstractmethod
    def build_index(self, repo_path: str) -> dict:
        """Build an index for `repo_path` and return a summary of the result."""
        ...

    @abstractmethod
    def get_relevant_context(self, query: str, budget: ContextBudget) -> dict:
        """Return context snippets for `query` that fit within `budget`."""
        ...


class ContextRanker(ABC):
    """Orders index entries by relevance to a query."""

    @abstractmethod
    def rank(self, index_entries: list[RepoFileIndex], query: str) -> list[RepoFileIndex]:
        """Return `index_entries` ordered most-relevant first."""
        ...


class ContextCompressor(ABC):
    """Renders index entries into a context string that fits a budget."""

    @abstractmethod
    def compress(self, index_entries: list[RepoFileIndex], budget: ContextBudget) -> str:
        """Return a serialized context block within `budget`'s token limits."""
        ...


class ContextCache(ABC):
    """Stores retrieved context keyed by query signature."""

    @abstractmethod
    def get(self, key: str) -> Optional[dict]:
        """Return the cached value for `key`, or None if absent."""
        ...

    @abstractmethod
    def set(self, key: str, value: dict) -> None:
        """Store `value` under `key`, overwriting any prior entry."""
        ...
