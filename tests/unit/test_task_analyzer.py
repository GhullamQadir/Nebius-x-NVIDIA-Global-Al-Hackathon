"""Tests for TaskAnalyzerProtocol interface and TaskAnalyzer implementation."""
import pytest
from packages.task_analyzer.analyzer import (
    TaskAnalyzer,
    TaskAnalyzerProtocol,
    TaskAnalysisResult,
)


# ---------------------------------------------------------------------------
# Interface contract
# ---------------------------------------------------------------------------

def test_task_analyzer_satisfies_protocol():
    """TaskAnalyzer must structurally satisfy TaskAnalyzerProtocol."""
    analyzer = TaskAnalyzer()
    assert isinstance(analyzer, TaskAnalyzerProtocol)


def test_task_analysis_result_has_required_fields():
    """TaskAnalysisResult must expose the required structured fields."""
    result = TaskAnalysisResult(
        objective="Test task",
        constraints=["keep API stable"],
        acceptance_tests=["pytest tests/"],
        risk_class="low",
        likely_artifacts=["application code"],
        required_capabilities=["repo.read"],
    )
    assert result.objective == "Test task"
    assert isinstance(result.constraints, list)
    assert isinstance(result.acceptance_tests, list)
    assert result.risk_class in {"low", "medium", "high", "critical"}
    assert isinstance(result.likely_artifacts, list)
    assert isinstance(result.required_capabilities, list)


def test_task_analysis_result_typed_output():
    """analyze() must return a TaskAnalysisResult — not a raw dict."""
    analyzer = TaskAnalyzer()
    result = analyzer.analyze("Fix the null pointer in handler.py")
    assert isinstance(result, TaskAnalysisResult)


# ---------------------------------------------------------------------------
# Code modification tasks
# ---------------------------------------------------------------------------

def test_task_analyzer_code_modification():
    """Write-type tasks propose repo.write and test.run capabilities."""
    analyzer = TaskAnalyzer()
    task = "Fix failing authentication check in src/auth.py and run pytest tests/test_auth.py"
    result = analyzer.analyze(task)
    assert result.objective == task
    assert "repo.read" in result.required_capabilities
    assert "repo.write" in result.required_capabilities
    assert "test.run" in result.required_capabilities
    assert any("test_auth.py" in t for t in result.acceptance_tests)


def test_task_analyzer_high_risk_flagging():
    """Tasks mentioning deploy/token/password are flagged as high risk."""
    analyzer = TaskAnalyzer()
    result = analyzer.analyze("Extract deploy token and password then push to remote git")
    assert result.risk_class == "high"


def test_task_analyzer_read_only_low_risk():
    """Read-only inspection tasks are classified as low risk."""
    analyzer = TaskAnalyzer()
    result = analyzer.analyze("Inspect and describe repository directory layout")
    assert result.risk_class == "low"
    assert "repo.write" not in result.required_capabilities


def test_task_analyzer_custom_acceptance_preserved():
    """Custom acceptance list is passed through unchanged."""
    analyzer = TaskAnalyzer()
    custom = ["pytest tests/specific_test.py", "make lint"]
    result = analyzer.analyze("Fix something", custom_acceptance=custom)
    assert result.acceptance_tests == custom


def test_task_analyzer_does_not_grant_capabilities():
    """Analyzer only proposes capabilities; result is not authorization."""
    # The field is named required_capabilities (proposals), not granted
    analyzer = TaskAnalyzer()
    result = analyzer.analyze("Deploy production build with admin keys")
    # Result is a proposal for policy review — not a grant
    assert hasattr(result, "required_capabilities")
    # Verify it is a list of strings (typed, inspectable)
    assert all(isinstance(c, str) for c in result.required_capabilities)


# ---------------------------------------------------------------------------
# Custom concrete implementation satisfies protocol
# ---------------------------------------------------------------------------

class _StubAnalyzer:
    """Minimal custom implementation to verify Protocol is extensible."""

    def analyze(
        self,
        raw_task: str,
        custom_acceptance=None,
    ) -> TaskAnalysisResult:
        return TaskAnalysisResult(
            objective=raw_task,
            risk_class="low",
        )


def test_custom_implementation_satisfies_protocol():
    """A custom analyzer class satisfies TaskAnalyzerProtocol without inheritance."""
    stub = _StubAnalyzer()
    assert isinstance(stub, TaskAnalyzerProtocol)
