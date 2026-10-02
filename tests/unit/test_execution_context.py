"""Tests for ExecutionContext typed contract."""
import pytest
from pydantic import ValidationError
from packages.contracts.execution_context import ExecutionContext


def test_execution_context_valid_creation():
    """A valid ExecutionContext can be created with all fields."""
    ctx = ExecutionContext(
        run_id="run_abc123",
        repository_root="workspace://my-repo",
        capabilities=frozenset(["repo.read", "repo.write", "test.run"]),
        timeout_seconds=600,
    )
    assert ctx.run_id == "run_abc123"
    assert ctx.repository_root == "workspace://my-repo"
    assert "repo.read" in ctx.capabilities
    assert ctx.timeout_seconds == 600


def test_execution_context_run_id_present():
    """run_id field is required and accessible."""
    ctx = ExecutionContext(run_id="run_xyz", repository_root="workspace://repo")
    assert ctx.run_id == "run_xyz"


def test_execution_context_repository_root_present():
    """repository_root field is required and accessible."""
    ctx = ExecutionContext(run_id="run_xyz", repository_root="workspace://my-repo")
    assert ctx.repository_root == "workspace://my-repo"


def test_execution_context_capabilities_present():
    """capabilities field is present and is a frozenset of strings."""
    ctx = ExecutionContext(
        run_id="run_xyz",
        repository_root="workspace://repo",
        capabilities=frozenset(["repo.read"]),
    )
    assert isinstance(ctx.capabilities, frozenset)
    assert "repo.read" in ctx.capabilities


def test_execution_context_timeout_present():
    """timeout_seconds field is present and accessible."""
    ctx = ExecutionContext(
        run_id="run_xyz",
        repository_root="workspace://repo",
        timeout_seconds=300,
    )
    assert ctx.timeout_seconds == 300


def test_execution_context_defaults():
    """Default capabilities is empty frozenset; default timeout is 900."""
    ctx = ExecutionContext(run_id="run_xyz", repository_root="workspace://repo")
    assert ctx.capabilities == frozenset()
    assert ctx.timeout_seconds == 900


def test_execution_context_missing_run_id_fails():
    """Missing run_id raises ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionContext(repository_root="workspace://repo")  # type: ignore[call-arg]


def test_execution_context_missing_repository_root_fails():
    """Missing repository_root raises ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionContext(run_id="run_xyz")  # type: ignore[call-arg]


def test_execution_context_timeout_below_minimum_fails():
    """timeout_seconds < 1 is rejected."""
    with pytest.raises(ValidationError):
        ExecutionContext(run_id="run_xyz", repository_root="workspace://repo", timeout_seconds=0)


def test_execution_context_timeout_above_maximum_fails():
    """timeout_seconds > 3600 is rejected."""
    with pytest.raises(ValidationError):
        ExecutionContext(run_id="run_xyz", repository_root="workspace://repo", timeout_seconds=9999)


def test_execution_context_is_immutable():
    """ExecutionContext is frozen — mutations raise an error."""
    ctx = ExecutionContext(run_id="run_xyz", repository_root="workspace://repo")
    with pytest.raises(Exception):
        ctx.run_id = "run_changed"  # type: ignore[misc]


def test_execution_context_no_secrets():
    """ExecutionContext has no secret-like fields (api_key, password, token)."""
    fields = ExecutionContext.model_fields.keys()
    forbidden = {"api_key", "password", "token", "secret", "credential"}
    for field in fields:
        assert field not in forbidden, f"ExecutionContext must not contain secret field: {field}"
