"""Aamir ke 5 tests: valid, unknown, missing args, timeout, failure."""

from packages.tool_router.mock_tools import (
    MISSING_ARGUMENT, TIMEOUT, TOOL_FAILURE, UNKNOWN_TOOL, execute_tool,
)


def test_valid_tool_succeeds(valid_tool_call):
    result = execute_tool(**valid_tool_call)
    assert result.success is True
    assert "[mock]" in result.output
    assert result.error_code is None


def test_unknown_tool_is_rejected(unknown_tool_call):
    result = execute_tool(**unknown_tool_call)
    assert result.success is False
    assert result.error_code == UNKNOWN_TOOL


def test_missing_arguments_are_reported(missing_args_call):
    result = execute_tool(**missing_args_call)
    assert result.success is False
    assert result.error_code == MISSING_ARGUMENT
    assert "content" in result.error_message


def test_tool_timeout_is_reported(timeout_call):
    result = execute_tool(**timeout_call)
    assert result.success is False
    assert result.error_code == TIMEOUT


def test_tool_failure_is_reported(failure_call):
    result = execute_tool(**failure_call)
    assert result.success is False
    assert result.error_code == TOOL_FAILURE
