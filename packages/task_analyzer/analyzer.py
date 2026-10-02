import re
from typing import List
from pydantic import BaseModel, Field


class TaskAnalysisResult(BaseModel):
    objective: str = Field(..., description="Normalized objective statement")
    constraints: List[str] = Field(default_factory=list, description="Preservation constraints")
    acceptance_tests: List[str] = Field(default_factory=list, description="Identified or suggested test targets")
    risk_class: str = Field("medium", description="Risk assessment: low, medium, high, critical")
    likely_artifacts: List[str] = Field(default_factory=list, description="Anticipated code/config targets")
    required_capabilities: List[str] = Field(default_factory=list, description="Capabilities requested for policy review")


class TaskAnalyzer:
    """
    Task Analyzer extracts structured objectives, identifies tests,
    and proposes capabilities from a raw task description.
    Note: It NEVER grants permissions—it only proposes them for the Policy Engine.
    """

    def analyze(self, raw_task: str, custom_acceptance: List[str] = None) -> TaskAnalysisResult:
        task_lower = raw_task.lower()
        
        # Determine likely capabilities needed
        capabilities = ["repo.list", "repo.read"]
        if any(w in task_lower for w in ["fix", "add", "update", "modify", "refactor", "create", "implement", "write"]):
            capabilities.append("repo.write")
        if any(w in task_lower for w in ["test", "pytest", "verify", "run", "check", "assert"]):
            capabilities.append("test.run")
            
        # Determine risk level
        risk = "medium"
        if any(w in task_lower for w in ["push", "deploy", "secret", "token", "password", "key", "root", "rm -rf"]):
            risk = "high"
        elif all(w not in task_lower for w in ["write", "modify", "delete", "push", "update"]):
            risk = "low"

        # Determine artifacts
        artifacts = ["application code"]
        if "test" in task_lower or "spec" in task_lower:
            artifacts.append("tests")
        if any(w in task_lower for w in ["config", "yaml", "toml", "env", "requirement"]):
            artifacts.append("configuration")

        # Constraints
        constraints = ["preserve existing API contract", "isolate execution inside sandbox"]
        if "regression" in task_lower or "test" in task_lower:
            constraints.append("add regression test")

        # Acceptance tests
        acceptance_tests = list(custom_acceptance or [])
        if not acceptance_tests:
            # Extract mentions like pytest tests/...
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
