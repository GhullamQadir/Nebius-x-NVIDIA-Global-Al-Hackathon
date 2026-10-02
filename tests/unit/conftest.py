"""Tool fixtures: tests ke liye ready-made inputs (Aamir)."""

import pytest


@pytest.fixture
def valid_tool_call():
    return {"tool_name": "read_file", "args": {"path": "src/main.py"}}


@pytest.fixture
def unknown_tool_call():
    return {"tool_name": "hack_the_planet", "args": {}}


@pytest.fixture
def missing_args_call():
    # write_file ko path aur content dono chahiye, content missing hai
    return {"tool_name": "write_file", "args": {"path": "src/main.py"}}


@pytest.fixture
def timeout_call():
    return {"tool_name": "run_shell",
            "args": {"command": "echo hi", "_simulate": "timeout"}}


@pytest.fixture
def failure_call():
    return {"tool_name": "run_tests",
            "args": {"path": "tests/", "_simulate": "failure"}}
