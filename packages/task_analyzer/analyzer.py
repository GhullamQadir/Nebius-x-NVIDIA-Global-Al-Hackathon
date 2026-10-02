"""
Task Analyzer interface and concrete implementation.

The Protocol defines the contract a future LLM-backed analyzer must fulfil.
The current TaskAnalyzer is a rule-based implementation suitable for Day 2.
"""
from __future__ import annotations

import re
from typing import List, Optional
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class TaskAnalysisResult(BaseModel):
    """Structured output of task analysis.  Never authorizes capabilities."""

    objective: str = Field(..., description="Normalized objective statement")
    constraints: List[str] = Field(default_factory=list, description="Preservation constraints")
    acceptance_tests: List[str] = Field(default_factory=list, description="Identified or suggested test targets")
    risk_class: str = Field("medium", description="Risk assessment: low | medium | high | critical")
    likely_artifacts: List[str] = Field(default_factory=list, description="Anticipated code/config targets")
    required_capabilities: List[str] = Field(
        default_factory=list,
        description="Capabilities proposed for policy review — NOT authorization",
    )


@runtime_checkable
class TaskAnalyzerProtocol(Protocol):
    """
    Contract that any TaskAnalyzer implementation must satisfy.

    An implementation receives a raw task string and optional acceptance
    criteria and returns a structured TaskAnalysisResult.

    Rules:
    - Must NOT call any LLM or external service.
    - Must NOT grant capabilities — it only proposes them.
    - Output is untrusted proposal data; the Policy Engine decides.
    """

    def analyze(
        self,
        raw_task: str,
        custom_acceptance: Optional[List[str]] = None,
    ) -> TaskAnalysisResult:
        """Analyse *raw_task* and return a structured result."""
        ...


class TaskAnalyzer:
    """
    Rule-based Task Analyzer.

    Implements TaskAnalyzerProtocol without any LLM or external calls.
    Heuristics derive capabilities, risk class, and acceptance targets
    from keyword inspection.  The results are proposals only.
    """

    def analyze(
        self,
        raw_task: str,
        custom_acceptance: Optional[List[str]] = None,
    ) -> TaskAnalysisResult:
        task_lower = raw_task.lower()

        capabilities = ["repo.list", "repo.read"]
        if any(w in task_lower for w in ["fix", "add", "update", "modify", "refactor", "create", "implement", "write"]):
            capabilities.append("repo.write")
        if any(w in task_lower for w in ["test", "pytest", "verify", "run", "check", "assert"]):
            capabilities.append("test.run")

        risk = "medium"
        if any(w in task_lower for w in ["push", "deploy", "secret", "token", "password", "key", "root", "rm -rf"]):
            risk = "high"
        elif all(w not in task_lower for w in ["write", "modify", "delete", "push", "update"]):
            risk = "low"

        artifacts = ["application code"]
        if "test" in task_lower or "spec" in task_lower:
            artifacts.append("tests")
        if any(w in task_lower for w in ["config", "yaml", "toml", "env", "requirement"]):
            artifacts.append("configuration")

        constraints = ["preserve existing API contract", "isolate execution inside sandbox"]
        if "regression" in task_lower or "test" in task_lower:
            constraints.append("add regression test")

        acceptance_tests: List[str] = list(custom_acceptance or [])
        if not acceptance_tests:
            matches = re.findall(r"(?:pytest\s+)?([a-zA-Z0-9_\-/]+\.py)", raw_task)
            if matches:
                acceptance_tests.extend([f"pytest {m}" for m in matches])
            else:
                acceptance_tests.append("pytest tests/")

        return TaskAnalysisResult(
            objective=raw_task.strip(),
            constraints=constraints,
            acceptance_tests=acceptance_tests,
            risk_class=risk,
            likely_artifacts=artifacts,
            required_capabilities=capabilities,
        )
