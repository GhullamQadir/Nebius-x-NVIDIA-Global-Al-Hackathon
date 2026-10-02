"""Mock tools: nakli tools. Koi real file/command/test touch nahi hota."""

from dataclasses import dataclass
from typing import Optional

from packages.tool_router.schemas import get_schema

# Error codes (result.error_code mein yehi milenge)
UNKNOWN_TOOL = "UNKNOWN_TOOL"
MISSING_ARGUMENT = "MISSING_ARGUMENT"
TIMEOUT = "TIMEOUT"
TOOL_FAILURE = "TOOL_FAILURE"


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str = ""
    error_code: Optional[str] = None
    error_message: str = ""


def _maybe_simulate(args):
    """Test ke liye: args mein _simulate ho to nakli timeout/failure banao."""
    mode = args.get("_simulate")
    if mode == "timeout":
        raise TimeoutError("mock tool timed out")
    if mode == "failure":
        raise RuntimeError("mock tool crashed")


def mock_list_files(args):
    _maybe_simulate(args)
    return "[mock] files in %s: a.py, b.py" % args["path"]


def mock_read_file(args):
    _maybe_simulate(args)
    return "[mock] content of %s" % args["path"]


def mock_write_file(args):
    _maybe_simulate(args)
    return "[mock] wrote %d chars to %s" % (len(args["content"]), args["path"])


def mock_run_shell(args):
    _maybe_simulate(args)
    # Command kabhi run nahi hoti, sirf text return hota hai
    return "[mock] would run: %s" % args["command"]


def mock_run_tests(args):
    _maybe_simulate(args)
    return "[mock] 3 passed in %s" % args["path"]


MOCK_TOOLS = {
    "list_files": mock_list_files,
    "read_file": mock_read_file,
    "write_file": mock_write_file,
    "run_shell": mock_run_shell,
    "run_tests": mock_run_tests,
}


def execute_tool(tool_name, args):
    """Tool chalao. Hamesha ToolResult return karta hai, crash nahi karta."""
    schema = get_schema(tool_name)
    if schema is None or tool_name not in MOCK_TOOLS:
        return ToolResult(tool_name, False, error_code=UNKNOWN_TOOL,
                          error_message="Unknown tool: %s" % tool_name)

    missing = [a for a in schema["required_args"] if a not in args]
    if missing:
        return ToolResult(tool_name, False, error_code=MISSING_ARGUMENT,
                          error_message="Missing arguments: %s" % ", ".join(missing))

    try:
        output = MOCK_TOOLS[tool_name](args)
    except TimeoutError as e:
        return ToolResult(tool_name, False, error_code=TIMEOUT, error_message=str(e))
    except Exception as e:
        return ToolResult(tool_name, False, error_code=TOOL_FAILURE, error_message=str(e))

    return ToolResult(tool_name, True, output=output)
