"""
Nexora Tool Router and Sandbox Adapter
Typed tool schemas, validation, and sandboxed execution
"""
import json
import os
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type
from urllib.parse import urlparse

from nexora.backend.app.core.policy import Capability
from nexora.backend.app.models import ExecutionStatus
from nexora.backend.app.schemas import ToolExecutionBase as ToolExecutionSchema
from nexora.backend.config.settings import get_settings

settings = get_settings()


# ============================================================
# Tool Schemas (Typed)
# ============================================================

class ToolName(str, Enum):
    REPO_LIST = "repo.list"
    REPO_READ = "repo.read"
    REPO_WRITE = "repo.write"
    TEST_RUN = "test.run"
    GIT_STATUS = "git.status"
    GIT_DIFF = "git.diff"
    GIT_BRANCH = "git.branch"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"
    SHELL_RUN = "shell.run"
    NETWORK_FETCH = "network.fetch"
    WEB_SCRAPE = "web.scrape"


# Tool argument schemas (for validation)
TOOL_SCHEMAS: Dict[ToolName, Dict[str, Any]] = {
    ToolName.REPO_LIST: {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": ".", "description": "Subdirectory to list (defaults to '.')"},
            "pattern": {"type": "string", "default": "**/*", "description": "Glob pattern to filter files"},
        },
        "required": [],
        "additionalProperties": False,
    },
    ToolName.REPO_READ: {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file in repository (e.g. 'index.html', 'src/main.py')"},
            "start_line": {"type": "integer", "minimum": 1, "description": "Optional start line number (1-indexed)"},
            "end_line": {"type": "integer", "minimum": 1, "description": "Optional end line number (1-indexed)"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    ToolName.REPO_WRITE: {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to the file to create or write (e.g. 'index.html', 'solution.py')"},
            "content": {"type": "string", "description": "REQUIRED. The exact full text content or code to write into the file. Never omit this field. For very large files (>200 lines), write the file in chunks: first call with mode='overwrite', then subsequent calls with mode='append'."},
            "mode": {"type": "string", "enum": ["create", "overwrite", "append"], "default": "overwrite", "description": "Write mode: 'create' (fails if file exists), 'overwrite' (replaces file), or 'append' (adds content to the end of the file, use to build large files in multiple chunks)"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    ToolName.TEST_RUN: {
        "type": "object",
        "properties": {
            "command": {"type": "string", "default": "pytest -v", "description": "Test command to execute"},
            "timeout_seconds": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
        },
        "required": [],
        "additionalProperties": False,
    },
    ToolName.GIT_STATUS: {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    ToolName.GIT_DIFF: {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "default": False},
        },
        "required": [],
        "additionalProperties": False,
    },
    ToolName.GIT_BRANCH: {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create", "switch"], "default": "list"},
            "name": {"type": "string"},
        },
        "required": [],
        "additionalProperties": False,
    },
    ToolName.GIT_COMMIT: {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    ToolName.GIT_PUSH: {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "default": "origin"},
            "branch": {"type": "string"},
            "force": {"type": "boolean", "default": False},
        },
        "required": [],
        "additionalProperties": False,
    },
    ToolName.SHELL_RUN: {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 60},
            "working_dir": {"type": "string"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    ToolName.NETWORK_FETCH: {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "default": "GET"},
            "headers": {"type": "object"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    ToolName.WEB_SCRAPE: {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full HTTP/HTTPS URL of the web page or documentation to scrape"},
            "selector": {"type": "string", "default": "body", "description": "Optional HTML tag or selector to focus extraction on"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


# Capability mapping for each tool
TOOL_CAPABILITIES: Dict[ToolName, Capability] = {
    ToolName.REPO_LIST: Capability.REPO_LIST,
    ToolName.REPO_READ: Capability.REPO_READ,
    ToolName.REPO_WRITE: Capability.REPO_WRITE,
    ToolName.TEST_RUN: Capability.TEST_RUN,
    ToolName.GIT_STATUS: Capability.GIT_STATUS,
    ToolName.GIT_DIFF: Capability.GIT_DIFF,
    ToolName.GIT_BRANCH: Capability.GIT_BRANCH,
    ToolName.GIT_COMMIT: Capability.GIT_COMMIT,
    ToolName.GIT_PUSH: Capability.GIT_PUSH,
    ToolName.SHELL_RUN: Capability.SHELL_RUN,
    ToolName.NETWORK_FETCH: Capability.NETWORK_FETCH,
    ToolName.WEB_SCRAPE: Capability.WEB_SCRAPE,
}


# ============================================================
# Argument validation limits and redaction (fail-closed)
# ============================================================

# Predefined, trusted limits. Generous enough for ordinary coding-agent work
# but bound the damage a hostile model can cause through oversized or
# malformed tool arguments. These are never derived from model output.
MAX_STRING_ARG_LENGTH = 2_000_000   # 2 MB per string argument (e.g. file content)
MAX_ARRAY_ARG_LENGTH = 10_000       # items per array argument
MAX_ARGUMENTS_BYTES = 4_000_000     # 4 MB total serialized arguments
MAX_PATH_LENGTH = 4096

# Trusted domains for web scraping. Arbitrary URLs are never reachable;
# only these vetted hosts may be scraped. Never derived from model output.
WEB_SCRAPE_ALLOWED_DOMAINS = frozenset({
    "ghulam-qasim.vercel.app",
    "github.com",
    "raw.githubusercontent.com",
    "www.linkedin.com",
    "linkedin.com",
    "example.com",
    "www.example.com",
    "nonexistent-domain.xyz",
    "developer.mozilla.org",
    "docs.python.org",
    "pypi.org",
    "npmjs.com",
    # Add additional domains here as needed for your demo
})

# Argument keys whose values must never be written to logs. Substring match so
# "db_password", "API_KEY", "auth_token" etc. are all covered.
_SENSITIVE_ARG_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "access_key",
)

REDACTED_PLACEHOLDER = "[REDACTED]"


def redact_arguments(
    arguments: Optional[Dict[str, Any]],
    max_string_length: int = 256,
) -> Dict[str, Any]:
    """Return a log-safe deep copy of ``arguments``.

    Sensitive keys are replaced wholesale and every long string (including
    file ``content``) is truncated, so secrets and unbounded payloads never
    reach audit logs or other log sinks. The input mapping is not modified.
    """
    if not isinstance(arguments, dict):
        return {}

    def _scrub(key: str, value: Any) -> Any:
        key_lower = key.lower()
        if any(marker in key_lower for marker in _SENSITIVE_ARG_SUBSTRINGS):
            return REDACTED_PLACEHOLDER
        if isinstance(value, str):
            if len(value) > max_string_length:
                return (
                    value[:max_string_length]
                    + f"...[truncated {len(value) - max_string_length} chars]"
                )
            return value
        if isinstance(value, dict):
            return {k: _scrub(str(k), v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_scrub(key, item) for item in value]
        return value

    return {k: _scrub(str(k), v) for k, v in arguments.items()}


@dataclass
class ToolRequest:
    """Validated tool request"""
    tool_name: ToolName
    arguments: Dict[str, Any]
    request_id: str
    capability: Capability
    # Optional identity context. Trailing defaults keep every existing
    # positional construction of ToolRequest valid.
    run_id: Optional[str] = None
    repository_id: Optional[str] = None


class ToolRouter:
    """
    Tool Router - validates and routes typed tool requests.
    
    Only accepts typed tool schemas. Rejects malformed/unknown requests
    before policy evaluation. No arbitrary shell strings.
    """
    
    def __init__(self):
        self.schemas = TOOL_SCHEMAS
        self.capabilities = TOOL_CAPABILITIES

    def _normalize_arguments(
        self,
        tool_enum: ToolName,
        schema: Dict[str, Any],
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Normalize tool arguments: alias resolution, metadata stripping, and defaults."""
        args = dict(arguments)
        allowed_props = set(schema.get("properties", {}).keys())

        # 1. Content aliases for repo.write MUST be rescued BEFORE metadata
        # stripping: body-like keys (code, text, body, ...) must never be
        # discarded as "metadata", otherwise the write silently loses content.
        if tool_enum == ToolName.REPO_WRITE:
            if "content" not in args:
                # NOTE: Do NOT default missing content to "" here. A model that
                # omits (or had its arguments truncated and lost) the content
                # field must get an explicit validation error it can retry
                # from, instead of silently overwriting the file with an empty
                # one (this caused "Written 0 bytes" events for large files).
                for alias in ("code", "text", "body", "data", "file_content", "patch_content", "fileContent", "contents", "source"):
                    if alias in args:
                        args["content"] = str(args.pop(alias))
                        break
            # Legacy compat: 'patch' was never implemented (it silently acted
            # as overwrite). Treat it as 'append' so chunk-based large-file
            # writes do not hard-fail on the stricter enum.
            if args.get("mode") == "patch":
                args["mode"] = "append"

        # 2. Strip harmless metadata fields commonly output by LLMs
        harmless_metadata = {"explanation", "comment", "description", "thought", "reason", "summary", "notes", "_notes"}
        for k in harmless_metadata:
            if k not in allowed_props and k in args:
                args.pop(k, None)

        # 3. Path aliases for repo operations: file, filename, filepath, target, file_path, name -> path
        if "path" in allowed_props and "path" not in args:
            for alias in ("file", "filename", "filepath", "target", "file_path", "name"):
                if alias in args:
                    args["path"] = str(args.pop(alias))
                    break

        # 4. Command aliases for test.run / shell.run: cmd, script, exec -> command
        if "command" in allowed_props and "command" not in args:
            for alias in ("cmd", "script", "exec"):
                if alias in args:
                    args["command"] = str(args.pop(alias))
                    break

        return args
    
    def validate_and_route(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        request_id: str,
        *,
        run_id: Optional[str] = None,
        repository_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> ToolRequest:
        """
        Validate tool request against schema.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            request_id: Unique request identifier
            run_id: Optional run identity to validate and carry forward
            repository_id: Optional repository identity to validate
            workspace_path: Optional workspace root used to bind target paths

        Returns:
            Validated ToolRequest

        Raises:
            ToolValidationError: If validation fails
        """
        # Reject non-mapping arguments before touching them. JSON ``null`` or a
        # bare string from a malformed model tool call must fail closed.
        if not isinstance(arguments, dict):
            raise ToolValidationError(
                f"Arguments must be an object, got {type(arguments).__name__}"
            )

        # Normalize underscore tool names (e.g. repo_read -> repo.read)
        normalized_name = tool_name
        if "_" in tool_name and tool_name not in [t.value for t in ToolName]:
            normalized_name = tool_name.replace("_", ".")

        # Check tool exists
        try:
            tool_enum = ToolName(normalized_name)
        except ValueError:
            raise ToolValidationError(f"Unknown tool: {tool_name}")
        
        # Get schema
        schema = self.schemas.get(tool_enum)
        if not schema:
            raise ToolValidationError(f"No schema for tool: {tool_name}")

        # Normalize arguments (alias resolution, harmless metadata stripping, defaults)
        arguments = self._normalize_arguments(tool_enum, schema, arguments)
        
        # Validate required fields
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in arguments:
                raise ToolValidationError(f"Missing required field: {field_name}")
            if tool_enum == ToolName.REPO_WRITE and field_name == "content" and not str(arguments[field_name]).strip():
                raise ToolValidationError("Argument 'content' for repo_write cannot be empty. Please provide the code/content to write.")
        
        # Validate no additional properties
        allowed_props = set(schema.get("properties", {}).keys())
        for arg_name in arguments:
            if arg_name not in allowed_props:
                raise ToolValidationError(f"Unexpected argument: {arg_name}")
        
        # Type validation (basic)
        for arg_name, arg_value in arguments.items():
            prop_schema = schema["properties"].get(arg_name, {})
            expected_type = prop_schema.get("type")
            if expected_type and not self._check_type(arg_value, expected_type):
                raise ToolValidationError(
                    f"Argument '{arg_name}' must be {expected_type}, got {type(arg_value).__name__}"
                )
            
            # Enum validation
            enum_values = prop_schema.get("enum")
            if enum_values and arg_value not in enum_values:
                # Report the allowed set and the received *type* only: the raw
                # value could contain sensitive data that must not be logged.
                raise ToolValidationError(
                    f"Argument '{arg_name}' must be one of {enum_values}, "
                    f"got {type(arg_value).__name__}"
                )
        
        # Size validation (fail closed on oversized/unsafe payloads)
        self._validate_argument_sizes(arguments)

        # Target validation (paths, urls)
        self._validate_targets(arguments, workspace_path)

        # Identity validation (run / repository)
        self._validate_identity(run_id, repository_id, workspace_path)

        # Get capability
        capability = self.capabilities.get(tool_enum)
        if not capability:
            raise ToolValidationError(f"No capability mapping for tool: {tool_name}")
        
        return ToolRequest(
            tool_name=tool_enum,
            arguments=arguments,
            request_id=request_id,
            capability=capability,
            run_id=run_id,
            repository_id=repository_id,
        )

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Strict JSON type checking.

        ``bool`` is a subclass of ``int`` in Python, so integer/number checks
        must explicitly reject booleans (and the reverse) to prevent a model
        from smuggling the wrong type past schema validation.
        """
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type in ("integer", "number") and isinstance(value, bool):
            return False

        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        return isinstance(value, expected)

    def _value_size(self, value: Any) -> int:
        """Best-effort serialized size of an argument value."""
        if isinstance(value, str):
            return len(value)
        try:
            return len(json.dumps(value, default=str))
        except (TypeError, ValueError) as exc:
            raise ToolValidationError(f"Argument is not serializable: {exc}")

    def _validate_argument_sizes(self, arguments: Dict[str, Any]) -> None:
        """Enforce predefined string/array/total size limits (fail closed)."""
        total = 0
        for name, value in arguments.items():
            if isinstance(value, str):
                if "\x00" in value:
                    raise ToolValidationError(f"Argument '{name}' contains a NUL byte")
                if len(value) > MAX_STRING_ARG_LENGTH:
                    raise ToolValidationError(
                        f"Argument '{name}' exceeds {MAX_STRING_ARG_LENGTH} characters"
                    )
            elif isinstance(value, (list, tuple)):
                if len(value) > MAX_ARRAY_ARG_LENGTH:
                    raise ToolValidationError(
                        f"Argument '{name}' exceeds {MAX_ARRAY_ARG_LENGTH} items"
                    )
            total += self._value_size(value)
            if total > MAX_ARGUMENTS_BYTES:
                raise ToolValidationError(
                    f"Total tool arguments exceed {MAX_ARGUMENTS_BYTES} bytes"
                )

    def _validate_targets(
        self,
        arguments: Dict[str, Any],
        workspace_path: Optional[str],
    ) -> None:
        """Validate path-like and URL-like targets declared by the request."""
        for key in ("path", "working_dir", "pattern"):
            if key in arguments:
                self._validate_relative_path(key, arguments[key], workspace_path)
        if "url" in arguments:
            self._validate_url(arguments["url"])

    def _validate_relative_path(
        self,
        name: str,
        value: Any,
        workspace_path: Optional[str],
    ) -> None:
        """Require a workspace-relative path that cannot escape the root."""
        if not isinstance(value, str) or not value:
            raise ToolValidationError(f"Argument '{name}' must be a non-empty path string")
        if len(value) > MAX_PATH_LENGTH:
            raise ToolValidationError(f"Argument '{name}' exceeds {MAX_PATH_LENGTH} characters")
        if "\x00" in value:
            raise ToolValidationError(f"Argument '{name}' contains a NUL byte")
        # Reject absolute paths regardless of host OS: Windows/POSIX absolute
        # forms, UNC roots, and Windows drive-relative paths like "C:foo".
        if (
            os.path.isabs(value)
            or Path(value).is_absolute()
            or value.startswith(("/", "\\"))
            or (len(value) >= 2 and value[1] == ":")
        ):
            raise ToolValidationError(f"Argument '{name}' must be a relative path")

        # Normalise and reject anything that escapes the workspace root.
        normalized = os.path.normpath(value).replace("\\", "/")
        if normalized == ".." or normalized.startswith("../"):
            raise ToolValidationError(f"Argument '{name}' escapes the workspace root")

        if workspace_path:
            try:
                (Path(workspace_path) / value).resolve().relative_to(
                    Path(workspace_path).resolve()
                )
            except ValueError:
                raise ToolValidationError(f"Argument '{name}' escapes the workspace root")

    def _validate_url(self, value: Any) -> None:
        """Require an absolute http(s) URL."""
        if not isinstance(value, str) or not value:
            raise ToolValidationError("Argument 'url' must be a non-empty string")
        if len(value) > MAX_STRING_ARG_LENGTH:
            raise ToolValidationError("Argument 'url' is too long")
        try:
            parsed = urlparse(value)
        except ValueError:
            raise ToolValidationError("Argument 'url' is not a valid URL")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ToolValidationError("Argument 'url' must be an absolute http(s) URL")

    def _validate_identity(
        self,
        run_id: Optional[str],
        repository_id: Optional[str],
        workspace_path: Optional[str],
    ) -> None:
        """Validate run/repository identity when supplied."""
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise ToolValidationError("Invalid run identity")
        if repository_id is not None and (
            not isinstance(repository_id, str) or not repository_id.strip()
        ):
            raise ToolValidationError("Invalid repository identity")
        if workspace_path is not None and (
            not isinstance(workspace_path, str) or not workspace_path.strip()
        ):
            raise ToolValidationError("Invalid workspace identity")
    
    def get_schema(self, tool_name: ToolName) -> Dict[str, Any]:
        """Get JSON schema for a tool"""
        return self.schemas.get(tool_name, {})
    
    def get_all_schemas(self, underscore_safe: bool = False) -> List[Dict[str, Any]]:
        """Get all tool schemas for model, optionally using underscore-safe identifiers for standard OpenAI/LLM compliance."""
        descriptions = {
            ToolName.REPO_LIST: "List files and directories in the repository workspace.",
            ToolName.REPO_READ: "Read contents of a file in the workspace (supports optional start_line and end_line).",
            ToolName.REPO_WRITE: "Create or write content to a file in the workspace.",
            ToolName.TEST_RUN: "Run tests (e.g. pytest -v) in the workspace sandbox to verify behavior.",
            ToolName.SHELL_RUN: "Run an approved shell command safely in the workspace.",
            ToolName.GIT_STATUS: "Get current git status of modified or untracked files.",
            ToolName.GIT_DIFF: "Inspect git diff of modified files in the workspace.",
            ToolName.GIT_BRANCH: "List or manage git branches.",
            ToolName.GIT_COMMIT: "Commit staged file changes with a message.",
            ToolName.GIT_PUSH: "Push committed changes to remote repository.",
            ToolName.NETWORK_FETCH: "Raw network fetch (restricted in sandbox). For inspecting websites or documentation, use web_scrape.",
            ToolName.WEB_SCRAPE: "Scrape and extract clean, sanitized text/markdown and metadata from any web page, portfolio, documentation or GitHub URL.",

        }

        schemas = []
        # Sort deterministically by tool name to preserve byte-level prefix stability for KV-cache
        for tool_name in sorted(self.schemas.keys(), key=lambda t: t.value):
            schema = self.schemas[tool_name]
            func_name = tool_name.value.replace(".", "_") if underscore_safe else tool_name.value
            desc = descriptions.get(tool_name, f"Tool: {tool_name.value}")
            schemas.append({
                "type": "function",
                "function": {
                    "name": func_name,
                    "description": desc,
                    "parameters": schema,
                }
            })
        return schemas


class ToolValidationError(Exception):
    """Tool validation error"""
    pass


# ============================================================
# test.run command parsing (shell-free, fail-closed)
# ============================================================

# Human-readable names used in the rejection message. These mirror the
# previously supported command families so existing callers/UX are unchanged.
_ALLOWED_TEST_RUNNERS = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "npm test",
    "npm run test",
    "cargo test",
)

# Shell metacharacters that must never appear *unquoted* in a test command.
# They are the operators a shell uses to chain a second command, redirect a
# file, perform substitution, or escape/expand (the trailing trio is Windows
# cmd.exe specific). Rejecting them keeps the command a single bounded call.
_UNQUOTED_SHELL_METACHARACTERS = frozenset(";|&<>$`()^%")

# Defence in depth: also refuse these inside arguments, even when they were
# quoted, so a metacharacter can never reach the runner as a live operator.
_FORBIDDEN_ARG_CHARACTERS = frozenset(";&|<>$`")

# Control characters may never appear anywhere in a test command.
_TEST_COMMAND_CONTROL_CHARACTERS = frozenset("\x00\n\r")


def _exe_basename(token: str) -> Optional[str]:
    """Return the lower-cased bare executable name, or ``None`` for a path.

    Only bare command names are accepted (no directory components), so a model
    can never point the "test runner" at an arbitrary file/executable.
    """
    if "/" in token or "\\" in token:
        return None
    name = token.lower()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name


def _is_python_exe(name: str) -> bool:
    """True for ``py`` / ``python`` / ``python3`` / ``python3.14`` etc."""
    if name == "py":
        return True
    if not name.startswith("python"):
        return False
    suffix = name[len("python"):]
    return suffix == "" or all(char.isdigit() or char == "." for char in suffix)


def _tokenize_test_command(command: str) -> List[str]:
    """Split ``command`` into an argument vector without invoking a shell.

    Whitespace separates tokens; single and double quotes group tokens and are
    removed. Shell metacharacters are rejected when unquoted (they would be
    operators in a real shell), and control characters are rejected outright.
    This is deliberately platform independent: backslash is treated as an
    ordinary character rather than an escape, which avoids the Windows/POSIX
    parsing divergence of ``shlex`` while keeping tokenisation deterministic.
    """
    if not isinstance(command, str):
        raise ToolValidationError("Test command must be a string")

    tokens: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    has_content = False

    for char in command:
        if char in _TEST_COMMAND_CONTROL_CHARACTERS:
            raise ToolValidationError("Test command contains a control character")
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
            has_content = True
            continue
        if char.isspace():
            if has_content:
                tokens.append("".join(current))
                current = []
                has_content = False
            continue
        if char in _UNQUOTED_SHELL_METACHARACTERS:
            raise ToolValidationError(
                f"Test command contains a shell metacharacter {char!r}"
            )
        current.append(char)
        has_content = True

    if quote is not None:
        raise ToolValidationError("Test command has an unterminated quote")
    if has_content:
        tokens.append("".join(current))
    return tokens


# Options that only affect verbosity / reporting / test selection. They cannot
# load plugins, change configuration, alter discovery, or touch the filesystem.
_SAFE_TEST_FLAGS = frozenset({
    "-v", "--verbose",
    "-q", "--quiet",
    "-x", "--exitfirst",
    "-s",
    "-l", "--showlocals",
    "--version",
    "--collect-only",
    "--disable-warnings",
})

# Traceback styles accepted by ``--tb``.
_TB_STYLES = frozenset({"auto", "long", "short", "line", "native", "no"})


def _reject_unsafe_argument(argument: str) -> None:
    """Reject empty, control-character, shell-metacharacter and out-of-workspace
    arguments. Used for both positional selectors and option values."""
    if not argument:
        raise ToolValidationError("Test command contains an empty argument")
    for char in argument:
        if char in _TEST_COMMAND_CONTROL_CHARACTERS:
            raise ToolValidationError(
                "Test command argument contains a control character"
            )
        if char in _FORBIDDEN_ARG_CHARACTERS:
            raise ToolValidationError(
                f"Test command argument contains a shell metacharacter {char!r}"
            )
    if (
        argument.startswith(("/", "\\"))
        or (len(argument) >= 2 and argument[1] == ":")
        or os.path.isabs(argument)
    ):
        raise ToolValidationError("Test command argument must not be an absolute path")
    normalized = os.path.normpath(argument).replace("\\", "/")
    if normalized == ".." or normalized.startswith("../"):
        raise ToolValidationError("Test command argument escapes the workspace root")


def _validate_expression_value(name: str, value: str) -> None:
    """Validate a ``-k`` / ``-m`` selection expression."""
    _reject_unsafe_argument(value)


def _validate_maxfail_value(name: str, value: str) -> None:
    """``--maxfail`` takes a non-negative integer."""
    if not value.isdigit():
        raise ToolValidationError(f"Test option {name} requires a non-negative integer")


def _validate_tb_value(name: str, value: str) -> None:
    """``--tb`` takes one of a fixed set of styles."""
    if value not in _TB_STYLES:
        raise ToolValidationError(
            f"Test option {name} must be one of: " + ", ".join(sorted(_TB_STYLES))
        )


# Options that take a value, mapped to a validator for that value. Anything not
# listed here (or in ``_SAFE_TEST_FLAGS``) is rejected, so this is an allowlist.
_SAFE_TEST_VALUE_OPTIONS = {
    "-k": _validate_expression_value,       # keyword expression
    "-m": _validate_expression_value,       # marker expression
    "--maxfail": _validate_maxfail_value,   # integer
    "--tb": _validate_tb_value,             # traceback style
}

# Explicitly dangerous options, rejected with a precise reason. Everything not
# allowlisted is rejected anyway ("fail closed"); this set only improves the
# message for the obvious cases (plugins, config, discovery, filesystem output).
_UNSAFE_TEST_OPTIONS = frozenset({
    "-p", "--plugin",
    "-c", "--config-file",
    "-o", "--override-ini",
    "--rootdir", "--confcutdir",
    "--basetemp", "--junitxml", "--junit-prefix",
    "--log-file", "--log-file-level", "--log-file-format", "--log-file-date-format",
    "--cache-dir", "--cache-clear",
    "--result-log", "--report-log",
    "--html", "--self-contained-html",
    "--cov", "--cov-report", "--cov-config", "--cov-fail-under",
    "-n", "--numprocesses", "--dist",
})


def _next_option_value(name: str, arguments: List[str], index: int) -> str:
    """Return the separate value token for an option, failing closed when it is
    missing or ambiguous (looks like another option)."""
    if index + 1 >= len(arguments):
        raise ToolValidationError(f"Test option {name} requires a value")
    value = arguments[index + 1]
    if value.startswith("-"):
        raise ToolValidationError(f"Test option {name} has an ambiguous value {value!r}")
    return value


def _validate_long_test_option(token: str, arguments: List[str], index: int) -> int:
    name, sep, value = token.partition("=")
    if name in _SAFE_TEST_FLAGS:
        if sep:
            raise ToolValidationError(f"Test option {name} does not take a value")
        return index + 1
    if name in _SAFE_TEST_VALUE_OPTIONS:
        if sep:
            _SAFE_TEST_VALUE_OPTIONS[name](name, value)
            return index + 1
        _SAFE_TEST_VALUE_OPTIONS[name](name, _next_option_value(name, arguments, index))
        return index + 2
    if name in _UNSAFE_TEST_OPTIONS:
        raise ToolValidationError(f"Test option {name!r} is not permitted")
    raise ToolValidationError(f"Unknown test option {name!r}")


def _validate_short_test_option(token: str, arguments: List[str], index: int) -> int:
    body = token[1:]
    position = 0
    while position < len(body):
        option = "-" + body[position]
        if option in _SAFE_TEST_VALUE_OPTIONS:
            attached = body[position + 1:]
            if attached.startswith("="):
                raise ToolValidationError(
                    f"Test option {option!r} has an ambiguous value"
                )
            if attached:
                _SAFE_TEST_VALUE_OPTIONS[option](option, attached)
                return index + 1
            _SAFE_TEST_VALUE_OPTIONS[option](
                option, _next_option_value(option, arguments, index)
            )
            return index + 2
        if option in _SAFE_TEST_FLAGS:
            position += 1
            continue
        if option in _UNSAFE_TEST_OPTIONS:
            raise ToolValidationError(f"Test option {option!r} is not permitted")
        raise ToolValidationError(f"Unknown test option {option!r}")
    return index + 1


def _validate_test_arguments(arguments: List[str]) -> None:
    """Validate the argument vector of an approved test runner.

    Only a small allowlist of pytest options that cannot load plugins, change
    configuration, override settings, alter discovery, or write/clear files is
    accepted; anything else is rejected (fail closed). Positional arguments are
    treated as workspace-relative test selectors. Supported forms are
    ``--option=value``, ``--option value``, ``-k value`` and attached ``-kvalue``;
    ambiguous forms (e.g. ``-k=value``, or a value that looks like an option)
    are rejected.
    """
    index = 0
    total = len(arguments)
    while index < total:
        token = arguments[index]
        if token == "--":
            for selector in arguments[index + 1:]:
                _reject_unsafe_argument(selector)
            return
        if token.startswith("--"):
            index = _validate_long_test_option(token, arguments, index)
        elif token.startswith("-") and token != "-":
            index = _validate_short_test_option(token, arguments, index)
        else:
            _reject_unsafe_argument(token)
            index += 1


def _build_approved_test_argv(command: str) -> List[str]:
    """Validate ``command`` and return a safe argument vector for ``exec``.

    The executable is matched as an exact approved runner (not a string
    prefix) and the command shape is pinned, so a model cannot smuggle a second
    command through the interpreter.
    """
    tokens = _tokenize_test_command(command)
    if not tokens:
        raise ToolValidationError("Test command is empty")

    exe_name = _exe_basename(tokens[0])
    if exe_name is None:
        raise ToolValidationError("Test executable must be a bare command name")

    if exe_name == "pytest":
        arguments = tokens[1:]
    elif _is_python_exe(exe_name):
        if len(tokens) < 3 or tokens[1] != "-m" or tokens[2] != "pytest":
            raise ToolValidationError("Only 'python -m pytest' is supported")
        arguments = tokens[3:]
    elif exe_name == "npm":
        if tokens[1:3] == ["run", "test"]:
            arguments = tokens[3:]
        elif tokens[1:2] == ["test"]:
            arguments = tokens[2:]
        else:
            raise ToolValidationError("Only 'npm test' or 'npm run test' is supported")
    elif exe_name == "cargo":
        if tokens[1:2] != ["test"]:
            raise ToolValidationError("Only 'cargo test' is supported")
        arguments = tokens[2:]
    else:
        raise ToolValidationError(
            f"Test executable {tokens[0]!r} is not an approved test runner"
        )

    _validate_test_arguments(arguments)
    return tokens


def _resolve_trusted_executable(exe: str) -> Optional[str]:
    """Resolve an approved bare executable name to an absolute path using only
    the absolute entries of ``PATH``.

    The current/working directory and any relative ``PATH`` entry are ignored,
    so a binary planted in the workspace cannot shadow the trusted runner. On
    Windows the ``PATHEXT`` extensions are honoured. Returns ``None`` when the
    executable cannot be resolved; callers treat that as fail-closed.
    """
    raw_path = os.environ.get("PATH", "") or ""
    directories: List[str] = []
    seen = set()
    for entry in raw_path.split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        # Never search the current/working directory or a relative entry.
        if entry in (".", os.curdir, "..", os.pardir) or not os.path.isabs(entry):
            continue
        key = os.path.normcase(entry)
        if key in seen:
            continue
        seen.add(key)
        directories.append(entry)

    # If PATH already has an approved python environment, ensure the active Python user Scripts
    # directory is searched ahead of legacy cross-version shims (e.g. anaconda python 3.11).
    if any("python" in d.lower() for d in directories):
        import site
        import sys
        v_scripts = os.path.join(getattr(site, "USER_BASE", ""), f"Python{sys.version_info.major}{sys.version_info.minor}", "Scripts" if os.name == "nt" else "bin")
        if os.path.isdir(v_scripts) and v_scripts not in directories:
            directories.insert(0, v_scripts)

    if os.name == "nt":
        pathext = (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
        candidates = [exe + ext for ext in pathext if ext]
        if exe not in candidates:
            candidates.append(exe)
    else:
        candidates = [exe]

    for directory in directories:
        for candidate in candidates:
            full = os.path.join(directory, candidate)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                return full
    return None


# ============================================================
# Filesystem boundary and resource limits (fail-closed)
# ============================================================
#
# The sandbox adapter must confine every filesystem operation to the approved
# workspace root. Like the argument limits above, these are trusted constants
# that are never derived from model output.

MAX_FILE_READ_BYTES = 5_000_000                # 5 MB per read
MAX_FILE_WRITE_BYTES = MAX_STRING_ARG_LENGTH   # 2 MB per write
MAX_LIST_ENTRIES = 10_000                      # entries returned by repo.list
MAX_LIST_OUTPUT_BYTES = 2_000_000              # serialized repo.list payload

# Control characters are never valid in a path or glob pattern.
_PATH_CONTROL_CHARACTERS = frozenset("\x00\n\r\t\v\f")

# Path components that identify version-control internals, credential stores,
# or private/browser profiles. Any entry below one of these is refused by the
# sandbox regardless of the policy engine (defence in depth).
_SENSITIVE_PATH_COMPONENTS = frozenset({
    ".git",
    ".ssh", ".aws", ".gnupg", ".azure", ".gcloud", ".kube", ".docker",
    "cookies", "login data", "logins.json", "key4.db",
})

# File names that always hold secret material.
_SENSITIVE_FILE_NAMES = frozenset({
    ".netrc", ".npmrc", ".pgpass", ".git-credentials", ".htpasswd",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "authorized_keys",
    "known_hosts", "credentials",
})

# File-name suffixes that always hold secret material.
_SENSITIVE_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")


class PathBoundaryError(Exception):
    """A path or pattern is malformed or escapes the workspace root."""


def _has_control_character(value: str) -> bool:
    """True when ``value`` contains any C0 control character."""
    return any(char in _PATH_CONTROL_CHARACTERS or ord(char) < 0x20 for char in value)


def _is_absolute_like(value: str) -> bool:
    """True for POSIX/Windows absolute, UNC, and drive-relative forms.

    Rejecting all of these keeps a path from being reinterpreted as absolute on
    the host OS or on a different OS than the one the model assumed.
    """
    return (
        os.path.isabs(value)
        or Path(value).is_absolute()
        or value.startswith(("/", "\\"))
        or (len(value) >= 2 and value[1] == ":")
    )


def _resolve_within_workspace(workspace: str, relative: Optional[str]) -> Path:
    """Resolve ``relative`` to an absolute path inside ``workspace``.

    Fails closed (:class:`PathBoundaryError`) for a non-string/empty value,
    control characters, absolute/UNC/drive-relative forms, any ``..`` component
    that escapes the root, and any symlink or junction whose *final* target
    resolves outside the workspace. The returned path is fully resolved, so
    callers must operate on it directly and never on the raw input (this closes
    the resolve-then-use gap for a single bounded call).
    """
    if not isinstance(relative, str) or not relative:
        raise PathBoundaryError("path must be a non-empty string")
    if len(relative) > MAX_PATH_LENGTH:
        raise PathBoundaryError("path is too long")
    if _has_control_character(relative):
        raise PathBoundaryError("path contains a control character")
    if _is_absolute_like(relative):
        raise PathBoundaryError("path must be relative to the workspace")
    normalized = os.path.normpath(relative).replace("\\", "/")
    if normalized == ".." or normalized.startswith("../"):
        raise PathBoundaryError("path escapes the workspace root")

    root = Path(workspace).resolve()
    try:
        candidate = (Path(workspace) / relative).resolve()
    except (OSError, RuntimeError) as exc:  # malformed name, symlink loop, ...
        raise PathBoundaryError(f"path could not be resolved: {exc}") from exc
    if not candidate.is_relative_to(root):
        raise PathBoundaryError("path escapes the workspace root")
    return candidate


def _validate_glob_pattern(pattern: Optional[str]) -> str:
    """Validate a ``repo.list`` glob pattern (no traversal, no absolute form)."""
    if not isinstance(pattern, str) or not pattern:
        raise PathBoundaryError("pattern must be a non-empty string")
    if len(pattern) > MAX_PATH_LENGTH:
        raise PathBoundaryError("pattern is too long")
    if _has_control_character(pattern):
        raise PathBoundaryError("pattern contains a control character")
    if _is_absolute_like(pattern):
        raise PathBoundaryError("pattern must be relative to the workspace")
    for part in pattern.replace("\\", "/").split("/"):
        if part == "..":
            raise PathBoundaryError("pattern escapes the workspace root")
    return pattern


def _is_sensitive_path(path: Path) -> bool:
    """True when ``path`` names credential material or private/vcs internals.

    ``path`` is expected to be workspace-relative so that the workspace root's
    own name cannot accidentally match a sensitive component.
    """
    lowered_components = [part.lower() for part in path.parts]
    if any(component in _SENSITIVE_PATH_COMPONENTS for component in lowered_components):
        return True
    name = path.name.lower()
    if name in _SENSITIVE_FILE_NAMES:
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    return name.endswith(_SENSITIVE_FILE_SUFFIXES)


def _validate_command_path_argument(argument: str) -> None:
    """Reject an argument that is an absolute path or escapes the workspace.

    Applied to command arguments (shell.run and git tools) so a file argument
    cannot point outside the sandbox even though the command itself runs
    shell-free. Flags and ordinary tokens pass through unchanged.
    """
    if not isinstance(argument, str) or not argument:
        raise ToolValidationError("Command arguments must be non-empty strings")
    if _has_control_character(argument):
        raise ToolValidationError("Command argument contains a control character")
    if _is_absolute_like(argument):
        raise ToolValidationError("Command argument must not be an absolute path")
    normalized = os.path.normpath(argument).replace("\\", "/")
    if normalized == ".." or normalized.startswith("../"):
        raise ToolValidationError("Command argument escapes the workspace root")


def _is_safe_ref_name(name: Any) -> bool:
    """Validate a git branch/ref name (no option injection, no traversal)."""
    if not isinstance(name, str) or not name or len(name) > 255:
        return False
    if name.startswith("-") or name.startswith("/") or name.endswith("/"):
        return False
    if name.startswith(".") or name.endswith(".lock") or name.endswith("."):
        return False
    if _has_control_character(name) or any(char.isspace() for char in name):
        return False
    if ".." in name or "@{" in name:
        return False
    return not any(char in _UNSAFE_REF_CHARACTERS for char in name)


# ============================================================
# shell.run structured execution policy (shell-free, fail-closed)
# ============================================================
#
# shell.run must never hand raw model text to a shell. The command is split
# into a token vector (sharing the test.run tokeniser, which rejects unquoted
# shell operators and control characters) and each part is checked against the
# reviewed executable/argument policy below.

# Shells and re-dispatching launchers. Running one of these would let the
# caller execute an arbitrary second program, so they are always refused.
_SHELL_FORBIDDEN_EXECUTABLES = frozenset({
    "sh", "bash", "dash", "zsh", "ksh", "csh", "tcsh", "fish", "ash",
    "cmd", "powershell", "pwsh", "wsl", "env", "xargs", "nohup", "setsid",
    "eval", "exec", "source",
})

# Interpreters that can evaluate inline code or load an arbitrary module.
_INTERPRETER_EXECUTABLES = frozenset({
    "python", "python3", "py", "node", "nodejs", "perl", "ruby", "php", "lua",
    "tclsh", "wish", "rscript",
})

# The only reviewed interpreter invocation permitted through shell.run.
_ALLOWED_INTERPRETER_INVOCATION = ["-m", "pytest"]

# Git ref names may not contain these characters and may not start with "-".
_UNSAFE_REF_CHARACTERS = frozenset("~^:?*[\\")


def _policy_command_sets() -> Tuple[Set[str], Set[str]]:
    """Reviewed command sets from the trusted Policy Engine configuration.

    Read lazily (avoids an import cycle and always reflects the loaded policy
    file). An unavailable engine yields empty sets, which callers treat as "no
    command is allowed" (fail closed).
    """
    try:
        from nexora.backend.app.core.policy import get_policy_engine

        config = get_policy_engine().config
    except Exception:  # pragma: no cover - defensive
        return set(), set()
    allowed = {str(command) for command in (config.allowed_commands or set())}
    denied = {str(command) for command in (config.denied_commands or set())}
    return allowed, denied


def _is_structurally_denied(tokens: List[str], denied: Set[str]) -> bool:
    """Exact-token match (never substring) against the denied-command policy."""
    lowered = {entry.strip().lower() for entry in denied}
    if not tokens:
        return False
    if tokens[0].lower() in lowered:
        return True
    return " ".join(token.lower() for token in tokens[:2]) in lowered


def _allowed_executable_names(allowed: Set[str]) -> Set[str]:
    """Single-word executables implied by the reviewed command policy."""
    names = set()
    for entry in allowed:
        parts = entry.strip().lower().split()
        if parts:
            names.add(parts[0])
    return names


def _allowed_git_subcommands(allowed: Set[str]) -> Set[str]:
    """``git <subcommand>`` entries from the reviewed command policy."""
    subcommands = set()
    for entry in allowed:
        parts = entry.strip().lower().split()
        if len(parts) == 2 and parts[0] == "git":
            subcommands.add(parts[1])
    return subcommands


def _build_approved_shell_argv(command: str) -> List[str]:
    """Parse and validate a shell.run command into a shell-free argv.

    The command is tokenised *without* a shell, so unquoted operators (``;``,
    ``|``, ``&``, ``>``, ``<``, ``$(...)``, backticks and cmd.exe escapes) are
    rejected and can never chain a second command or redirect a file.

    The executable must be a bare, reviewed command name: path executables,
    shells and inline interpreters are refused, and the name is later resolved
    to a trusted absolute path on ``PATH``. File arguments may not be absolute
    or escape the workspace root. Anything unrecognised fails closed.
    """
    tokens = _tokenize_test_command(command)
    if not tokens:
        raise ToolValidationError("Shell command is empty")

    exe_name = _exe_basename(tokens[0])
    if exe_name is None:
        raise ToolValidationError("Shell executable must be a bare command name")

    allowed, denied = _policy_command_sets()

    if _is_structurally_denied(tokens, denied):
        raise ToolValidationError(f"Command {tokens[0]!r} is denied by policy")
    if exe_name in _SHELL_FORBIDDEN_EXECUTABLES:
        raise ToolValidationError(f"Shell executable {tokens[0]!r} is not permitted")

    if exe_name in _INTERPRETER_EXECUTABLES:
        if tokens[1:3] != _ALLOWED_INTERPRETER_INVOCATION:
            raise ToolValidationError(
                "Only 'python -m pytest' is permitted when running an interpreter"
            )
    else:
        allowed_names = _allowed_executable_names(allowed)
        if not allowed_names or exe_name not in allowed_names:
            raise ToolValidationError(
                f"Command {tokens[0]!r} is not in the reviewed command allowlist"
            )
        if exe_name == "git":
            subcommands = _allowed_git_subcommands(allowed)
            if len(tokens) < 2 or tokens[1].lower() not in subcommands:
                raise ToolValidationError(
                    "Only reviewed 'git' subcommands are permitted"
                )

    for argument in tokens[1:]:
        _validate_command_path_argument(argument)
    return tokens


# ============================================================
# Sandbox Adapter
# ============================================================

class SandboxAdapter(ABC):
    """Abstract sandbox adapter"""
    
    @abstractmethod
    async def execute(
        self,
        tool_request: ToolRequest,
        workspace_path: str,
        environment: Dict[str, str],
    ) -> ToolExecutionSchema:
        """Execute tool in sandbox"""
        pass
    
    @abstractmethod
    async def cleanup(self, sandbox_id: str) -> None:
        """Clean up sandbox"""
        pass


class LocalSandboxAdapter(SandboxAdapter):
    """
    Local sandbox adapter for development.
    
    In production, this would be replaced with Token Factory Sandboxes.
    This implementation uses subprocess with resource limits.
    """
    
    def __init__(self):
        self.sandboxes: Dict[str, Dict[str, Any]] = {}
    
    async def execute(
        self,
        tool_request: ToolRequest,
        workspace_path: str,
        environment: Dict[str, str],
    ) -> ToolExecutionSchema:
        """Execute tool in local sandbox"""
        sandbox_id = f"local-{uuid.uuid4().hex[:8]}"
        start_time = datetime.now()
        
        try:
            # Prepare environment
            env = os.environ.copy()
            env.update(environment)
            # Remove sensitive env vars
            for key in list(env.keys()):
                if any(s in key.lower() for s in ["key", "secret", "password", "token", "api"]):
                    if key not in ["PATH", "HOME", "USER"]:
                        env.pop(key, None)
            
            # Execute based on tool
            if tool_request.tool_name == ToolName.REPO_LIST:
                result = await self._repo_list(tool_request.arguments, workspace_path)
            elif tool_request.tool_name == ToolName.REPO_READ:
                result = await self._repo_read(tool_request.arguments, workspace_path)
            elif tool_request.tool_name == ToolName.REPO_WRITE:
                result = await self._repo_write(tool_request.arguments, workspace_path)
            elif tool_request.tool_name == ToolName.TEST_RUN:
                result = await self._test_run(tool_request.arguments, workspace_path, env)
            elif tool_request.tool_name == ToolName.GIT_STATUS:
                result = await self._git_status(workspace_path)
            elif tool_request.tool_name == ToolName.GIT_DIFF:
                result = await self._git_diff(tool_request.arguments, workspace_path)
            elif tool_request.tool_name == ToolName.GIT_BRANCH:
                result = await self._git_branch(tool_request.arguments, workspace_path)
            elif tool_request.tool_name == ToolName.GIT_COMMIT:
                result = await self._git_commit(tool_request.arguments, workspace_path, env)
            elif tool_request.tool_name == ToolName.GIT_PUSH:
                result = await self._git_push(tool_request.arguments, workspace_path, env)
            elif tool_request.tool_name == ToolName.SHELL_RUN:
                result = await self._shell_run(tool_request.arguments, workspace_path, env)
            elif tool_request.tool_name == ToolName.NETWORK_FETCH:
                result = await self._network_fetch(tool_request.arguments)
            elif tool_request.tool_name == ToolName.WEB_SCRAPE:
                result = await self._web_scrape(tool_request.arguments)
            else:
                raise ValueError(f"Unsupported tool: {tool_request.tool_name}")
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            return ToolExecutionSchema(
                id=sandbox_id,
                run_id="",  # Filled by caller
                tool_request_id=tool_request.request_id,
                tool_name=tool_request.tool_name.value,
                arguments=tool_request.arguments,
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                exit_code=result.get("exit_code", 0),
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
                execution_status=ExecutionStatus.SUCCESS if result.get("exit_code", 0) == 0 else ExecutionStatus.FAILURE,
                created_at=datetime.now(),
            )
            
        except subprocess.TimeoutExpired:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return ToolExecutionSchema(
                id=sandbox_id,
                run_id="",
                tool_request_id=tool_request.request_id,
                tool_name=tool_request.tool_name.value,
                arguments=tool_request.arguments,
                stdout="",
                stderr="Execution timed out",
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
                execution_status=ExecutionStatus.TIMEOUT,
                created_at=datetime.now(),
            )
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return ToolExecutionSchema(
                id=sandbox_id,
                run_id="",
                tool_request_id=tool_request.request_id,
                tool_name=tool_request.tool_name.value,
                arguments=tool_request.arguments,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                duration_ms=duration_ms,
                sandbox_id=sandbox_id,
                execution_status=ExecutionStatus.ERROR,
                created_at=datetime.now(),
            )
    
    async def cleanup(self, sandbox_id: str) -> None:
        """Clean up sandbox resources"""
        if sandbox_id in self.sandboxes:
            del self.sandboxes[sandbox_id]
    
    async def _repo_list(self, args: Dict, workspace: str) -> Dict[str, Any]:
        # Enforce the workspace boundary on both the base directory and the
        # glob pattern before any filesystem walk. Previously only ``path`` was
        # validated (at the router) and ``pattern`` was not validated at all,
        # so a pattern such as ``../../*`` was passed straight to ``rglob``.
        try:
            base = _resolve_within_workspace(workspace, args.get("path", "."))
            pattern = _validate_glob_pattern(args.get("pattern", "**/*"))
        except PathBoundaryError as exc:
            return {
                "stdout": "",
                "stderr": f"Path traversal attempt blocked: {exc}",
                "exit_code": 1,
            }

        root = Path(workspace).resolve()
        if _is_sensitive_path(base.relative_to(root)):
            return {"stdout": "", "stderr": "Access to sensitive path denied", "exit_code": 1}
        if not base.is_dir():
            return {"stdout": "", "stderr": f"Not a directory: {args.get('path', '.')}", "exit_code": 1}

        files: List[str] = []
        for found in base.rglob(pattern):
            # Defence in depth: a symlink/junction yielded by the walk must
            # still resolve inside the workspace before it is disclosed.
            try:
                resolved = found.resolve()
            except (OSError, RuntimeError):
                continue
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            try:
                rel = resolved.relative_to(root)
            except ValueError:
                continue
            if _is_sensitive_path(rel):
                continue
            files.append(rel.as_posix())
            if len(files) >= MAX_LIST_ENTRIES:
                break

        # Bound the serialized payload as well as the entry count.
        payload = json.dumps(files)
        if len(payload) > MAX_LIST_OUTPUT_BYTES:
            kept: List[str] = []
            used = 2  # enclosing brackets
            for name in files:
                used += len(name) + 3  # quotes + separator
                if used > MAX_LIST_OUTPUT_BYTES:
                    break
                kept.append(name)
            payload = json.dumps(kept)

        return {"stdout": payload, "stderr": "", "exit_code": 0}

    async def _repo_read(self, args: Dict, workspace: str) -> Dict[str, Any]:
        rel = args.get("path")
        # Resolve the final target (following symlinks) and confirm it is inside
        # the workspace before anything is read. Failure is fail-closed.
        try:
            target = _resolve_within_workspace(workspace, rel)
        except PathBoundaryError:
            return {"stdout": "", "stderr": "Path traversal attempt blocked", "exit_code": 1}

        root = Path(workspace).resolve()
        if _is_sensitive_path(target.relative_to(root)):
            return {"stdout": "", "stderr": "Access to sensitive path denied", "exit_code": 1}
        if not target.exists():
            return {"stdout": "", "stderr": f"File not found: {rel}", "exit_code": 1}
        if not target.is_file():
            return {"stdout": "", "stderr": f"Not a file: {rel}", "exit_code": 1}

        try:
            if target.stat().st_size > MAX_FILE_READ_BYTES:
                return {
                    "stdout": "",
                    "stderr": f"File exceeds the {MAX_FILE_READ_BYTES} byte read limit",
                    "exit_code": 1,
                }
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {"stdout": "", "stderr": f"Could not read file: {type(exc).__name__}", "exit_code": 1}

        lines = content.splitlines()

        start = args.get("start_line", 1) - 1
        end = args.get("end_line", len(lines))

        selected = lines[start:end]
        result = "\n".join(selected)

        return {"stdout": result, "stderr": "", "exit_code": 0}

    async def _repo_write(self, args: Dict, workspace: str) -> Dict[str, Any]:
        rel = args["path"]
        content = args["content"]
        mode = args.get("mode", "overwrite")

        if not isinstance(content, str):
            return {"stdout": "", "stderr": "Content must be a string", "exit_code": 1}
        # Fail closed on empty writes: an empty overwrite is almost always a
        # failed generation (missing/truncated content), not an intent. Report
        # a retryable error instead of recording a silent 0-byte "success".
        if len(content) == 0:
            return {
                "stdout": "",
                "stderr": (
                    "repo_write refused: content was empty. Re-issue the call "
                    "with the full file content; for large files, split the "
                    "write into a mode='overwrite' chunk followed by "
                    "mode='append' chunks."
                ),
                "exit_code": 1,
            }
        if len(content.encode("utf-8", errors="replace")) > MAX_FILE_WRITE_BYTES:
            return {
                "stdout": "",
                "stderr": f"Content exceeds the {MAX_FILE_WRITE_BYTES} byte write limit",
                "exit_code": 1,
            }

        # Resolve the final target (following symlinks) and confirm it is inside
        # the workspace before creating directories or writing.
        try:
            target = _resolve_within_workspace(workspace, rel)
        except PathBoundaryError:
            return {"stdout": "", "stderr": "Path traversal attempt blocked", "exit_code": 1}

        root = Path(workspace).resolve()
        if _is_sensitive_path(target.relative_to(root)):
            return {"stdout": "", "stderr": "Writing to a sensitive path is denied", "exit_code": 1}
        if target.is_dir():
            return {"stdout": "", "stderr": f"Target is a directory: {rel}", "exit_code": 1}
        if mode == "create" and target.exists():
            return {"stdout": "", "stderr": f"File already exists: {rel}", "exit_code": 1}

        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            # Append byte-exact content to the end of the file (creating it if
            # missing) so very large files can be built across multiple calls.
            with target.open("a", encoding="utf-8", newline="") as f:
                f.write(content)
        else:
            target.write_text(content, encoding="utf-8")

        return {"stdout": f"Written {len(content)} bytes to {rel}", "stderr": "", "exit_code": 0}
    
    async def _test_run(self, args: Dict, workspace: str, env: Dict[str, str]) -> Dict[str, Any]:
        command = args.get("command", "pytest -v")
        timeout = args.get("timeout_seconds", 120)

        # Security: validate the command against an EXACT allowlist of approved
        # test runners and build a plain argument vector. It is then executed
        # WITHOUT a shell (create_subprocess_exec), so shell operators such as
        # `;`, `|`, `&`, `>` and `$(...)` are inert and can no longer chain a
        # second command, redirect a file, or perform command substitution.
        try:
            argv = _build_approved_test_argv(command)
        except ToolValidationError as exc:
            return {
                "stdout": "",
                "stderr": (
                    f"Test command {command!r} is not in the allowed prefix list: "
                    f"{exc}. Allowed prefixes: " + ", ".join(_ALLOWED_TEST_RUNNERS)
                ),
                "exit_code": 1,
            }

        # Resolve the approved runner to a trusted absolute path using PATH only
        # (never the current/workspace directory), so a binary planted in the
        # workspace cannot shadow the real runner.
        resolved_executable = _resolve_trusted_executable(argv[0])
        if resolved_executable is None:
            return {
                "stdout": "",
                "stderr": (
                    f"Test runner {argv[0]!r} could not be resolved to a "
                    "trusted executable on PATH"
                ),
                "exit_code": 1,
            }

        # Run in workspace directory. Executing an argument vector means a
        # launch failure (e.g. a Windows ``.cmd`` shim such as ``npm.cmd``
        # cannot be started without a shell) is reported as a fail-closed
        # result instead of propagating, keeping the dict return contract.
        try:
            proc = await asyncio.create_subprocess_exec(
                resolved_executable,
                *argv[1:],
                cwd=workspace,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return {
                "stdout": "",
                "stderr": f"Failed to launch test command {command!r}: {exc}",
                "exit_code": 1,
            }
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise subprocess.TimeoutExpired(command, timeout)
    
    async def _git_status(self, workspace: str) -> Dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    
    async def _git_diff(self, args: Dict, workspace: str) -> Dict[str, Any]:
        cmd = ["git", "diff"]
        if args.get("staged"):
            cmd.append("--cached")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    
    async def _git_branch(self, args: Dict, workspace: str) -> Dict[str, Any]:
        action = args.get("action", "list")
        name = args.get("name")

        if action == "list":
            cmd = ["git", "branch"]
        elif action == "create":
            if not _is_safe_ref_name(name):
                return {"stdout": "", "stderr": "Invalid branch name", "exit_code": 1}
            cmd = ["git", "branch", name]
        elif action == "switch":
            if not _is_safe_ref_name(name):
                return {"stdout": "", "stderr": "Invalid branch name", "exit_code": 1}
            cmd = ["git", "checkout", name]
        else:
            return {"stdout": "", "stderr": f"Unknown action: {action}", "exit_code": 1}
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    
    async def _git_commit(self, args: Dict, workspace: str, env: Dict[str, str]) -> Dict[str, Any]:
        # Requires approval in policy - just stage and commit.
        files = args.get("files", ["."])
        message = args["message"]

        # Validate file arguments: no option injection (leading '-') and no
        # absolute/parent escape, so ``git add`` cannot be pointed outside the
        # workspace or tricked into changing behaviour with a flag.
        if not isinstance(files, list) or not files:
            return {"stdout": "", "stderr": "Invalid file list", "exit_code": 1}
        for path_arg in files:
            if not isinstance(path_arg, str) or not path_arg or path_arg.startswith("-"):
                return {"stdout": "", "stderr": "Invalid file argument for git add", "exit_code": 1}
            try:
                _validate_command_path_argument(path_arg)
            except ToolValidationError:
                return {"stdout": "", "stderr": "File argument escapes the workspace", "exit_code": 1}

        proc = await asyncio.create_subprocess_exec(
            "git", "add", *files,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            cwd=workspace,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    
    async def _git_push(self, args: Dict, workspace: str, env: Dict[str, str]) -> Dict[str, Any]:
        # Denied in MVP - return blocked
        return {
            "stdout": "",
            "stderr": "Git push is denied in MVP. Requires explicit human approval.",
            "exit_code": 1,
        }
    
    async def _shell_run(self, args: Dict, workspace: str, env: Dict[str, str]) -> Dict[str, Any]:
        command = args["command"]
        timeout = args.get("timeout_seconds", 60)

        # Structured, shell-free validation. Raw model text must never reach a
        # shell: the command is split into a token vector and each token is
        # checked against the reviewed executable/argument policy (see
        # ``_build_approved_shell_argv``).
        try:
            argv = _build_approved_shell_argv(command)
        except ToolValidationError as exc:
            return {
                "stdout": "",
                "stderr": f"Shell command rejected: {exc}",
                "exit_code": 1,
            }

        # Resolve the reviewed executable to a trusted absolute path using PATH
        # only (never the workspace/current directory), so a binary planted in
        # the workspace cannot shadow it.
        resolved_executable = _resolve_trusted_executable(argv[0])
        if resolved_executable is None:
            return {
                "stdout": "",
                "stderr": (
                    f"Executable {argv[0]!r} could not be resolved to a trusted "
                    "path on PATH"
                ),
                "exit_code": 1,
            }

        # Bind the working directory to the workspace with the same boundary
        # check used for every filesystem operation. A relative ``working_dir``
        # is resolved against the workspace, never the process cwd.
        raw_working_dir = args.get("working_dir")
        if raw_working_dir is None:
            working_dir = str(Path(workspace).resolve())
        else:
            try:
                working_dir = str(_resolve_within_workspace(workspace, raw_working_dir))
            except PathBoundaryError as exc:
                return {
                    "stdout": "",
                    "stderr": f"Shell working directory rejected: {exc}",
                    "exit_code": 1,
                }
        if not Path(working_dir).is_dir():
            return {
                "stdout": "",
                "stderr": "Shell working directory does not exist",
                "exit_code": 1,
            }

        try:
            proc = await asyncio.create_subprocess_exec(
                resolved_executable,
                *argv[1:],
                cwd=working_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return {
                "stdout": "",
                "stderr": f"Failed to launch shell command {command!r}: {exc}",
                "exit_code": 1,
            }

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise subprocess.TimeoutExpired(command, timeout)
    
    async def _network_fetch(self, args: Dict) -> Dict[str, Any]:
        # Denied in MVP - no network access for task sandboxes
        return {
            "stdout": "",
            "stderr": "Network access is denied in MVP. Task sandboxes have no internet access.",
            "exit_code": 1,
        }

    async def _web_scrape(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape web page or documentation URL and return clean sanitized markdown.
        Supports metadata extraction, SPA (Single Page Application) bundle inspection,
        realistic browser headers, 15s timeout, and safe exception fallback.
        """
        raw_url = str(args.get("url") or "").strip()
        if not raw_url:
            return {"stdout": "", "stderr": "Error: Missing required 'url' parameter.", "exit_code": 1}

        if not raw_url.startswith(("http://", "https://")):
            url = f"https://{raw_url}"
        else:
            url = raw_url

        # ---- Domain allowlist (security boundary) ----
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.netloc not in WEB_SCRAPE_ALLOWED_DOMAINS:
            return {
                "stdout": "",
                "stderr": (
                    f"Web scrape denied: domain '{parsed.netloc}' is not in the "
                    f"allowed list. Only trusted portfolio/GitHub/LinkedIn domains "
                    f"may be scraped."
                ),
                "exit_code": 1,
            }
        # ------------------------------------------------

        try:
            import urllib.request
            import urllib.error
            import urllib.parse
            import html as html_lib
            import re

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            req = urllib.request.Request(url, headers=headers)

            def _fetch_page():
                with urllib.request.urlopen(req, timeout=15) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.read().decode(charset, errors="replace")

            html_content = await asyncio.to_thread(_fetch_page)

            # 1. Extract metadata and OpenGraph information
            meta_sections = []
            title_m = re.search(r"(?i)<title[^>]*>(.*?)</title>", html_content)
            title = html_lib.unescape(title_m.group(1)).strip() if title_m else ""

            desc_m = re.search(r'(?i)<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']', html_content)
            if not desc_m:
                desc_m = re.search(r'(?i)<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:description|og:description)["\']', html_content)
            desc = html_lib.unescape(desc_m.group(1)).strip() if desc_m else ""

            img_m = re.search(r'(?i)<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_content)
            img = img_m.group(1).strip() if img_m else ""

            if title:
                meta_sections.append(f"# {title}")
            if desc:
                meta_sections.append(f"> **Description:** {desc}")
            if img:
                resolved_img = urllib.parse.urljoin(url, img)
                meta_sections.append(f"> **Preview Image:** {resolved_img}")

            # 2. Strip non-content and clutter tags (scripts, styles, nav, footer, ads)
            cleaned = re.sub(r"(?is)<(script|style|nav|header|footer|svg|noscript|iframe)[^>]*>.*?</\1>", " ", html_content)
            cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)

            # Convert standard HTML elements to Markdown
            cleaned = re.sub(r'(?i)<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'[\2](\1)', cleaned)
            cleaned = re.sub(r'(?i)<h[1-2][^>]*>(.*?)</h[1-2]>', r'\n\n# \1\n\n', cleaned)
            cleaned = re.sub(r'(?i)<h[3-4][^>]*>(.*?)</h[3-4]>', r'\n\n## \1\n\n', cleaned)
            cleaned = re.sub(r'(?i)<h[5-6][^>]*>(.*?)</h[5-6]>', r'\n\n### \1\n\n', cleaned)
            cleaned = re.sub(r'(?i)<li[^>]*>(.*?)</li>', r'\n- \1', cleaned)
            cleaned = re.sub(r'(?i)<(?:p|div|section|article)[^>]*>', r'\n\n', cleaned)
            cleaned = re.sub(r'(?i)</(?:p|div|section|article)>', r'\n', cleaned)
            cleaned = re.sub(r'<[^>]+>', ' ', cleaned)

            # Unescape entities and normalize spacing
            text = html_lib.unescape(cleaned)
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text).strip()

            # 3. Single Page Application (SPA / React / Vite / Vue) detection & bundle inspection
            spa_sections = []
            is_spa = len(text) < 300 and any(
                marker in html_content
                for marker in ('id="root"', "id='root'", 'id="app"', "id='app'", 'id="__next"', "id='__next'")
            )
            if is_spa:
                scripts = re.findall(r'(?i)<script[^>]+src=["\']([^"\']+\.(?:js|mjs))["\']', html_content)
                bundle_script = None
                for s in scripts:
                    if any(k in s.lower() for k in ("index", "main", "app", "bundle", "assets", "chunk")):
                        bundle_script = s
                        break
                if not bundle_script and scripts:
                    bundle_script = scripts[0]

                if bundle_script:
                    script_url = urllib.parse.urljoin(url, bundle_script)
                    try:
                        def _fetch_bundle():
                            sreq = urllib.request.Request(script_url, headers=headers)
                            with urllib.request.urlopen(sreq, timeout=10) as sresp:
                                return sresp.read().decode("utf-8", errors="replace")

                        js = await asyncio.to_thread(_fetch_bundle)

                        # Check for portfolio data definitions (e.g. fullName:, roles:, projects:, etc.)
                        pos = js.find("fullName:")
                        if pos != -1:
                            data_chunk = js[pos - 20 : pos + 3000].replace(chr(96), '"')
                            spa_sections.append(
                                f"### Extracted Client-Side Portfolio Data\n```javascript\n{data_chunk}\n```"
                            )
                        else:
                            bt = chr(96)
                            strings = re.findall(
                                r'[\x22\x27' + bt + r']([A-Za-z0-9][A-Za-z0-9 ,.!\?:;\'\-_/()&]{20,250})[\x22\x27' + bt + r']',
                                js,
                            )
                            clean_strings = []
                            seen = set()
                            for st in strings:
                                stc = st.strip()
                                if (
                                    stc not in seen
                                    and stc.count(" ") >= 2
                                    and not any(
                                        k in stc
                                        for k in ["function", "return", "var ", "const ", "let ", "=>", "{", "}", ";", "div", "class"]
                                    )
                                ):
                                    seen.add(stc)
                                    clean_strings.append(f"- {stc}")
                                if len(clean_strings) >= 20:
                                    break
                            if clean_strings:
                                spa_sections.append("### Client-Side Application Content Snippets\n" + "\n".join(clean_strings))
                    except Exception:
                        pass

            # Combine all extracted content parts
            parts = []
            if meta_sections:
                parts.append("\n".join(meta_sections))
            if text and text != title:
                parts.append(text)
            if spa_sections:
                parts.append("\n\n".join(spa_sections))

            combined_text = "\n\n".join(parts).strip()
            if not combined_text:
                combined_text = f"URL {url} responded, but contained no readable text after sanitization."

            if len(combined_text) > 9500:
                combined_text = combined_text[:9500] + f"\n\n... [Content truncated: {len(combined_text)} total characters extracted from {url}]"

            return {
                "stdout": combined_text,
                "stderr": "",
                "exit_code": 0,
            }
        except urllib.error.HTTPError as http_err:
            if http_err.code in (999, 403) and "linkedin.com" in url.lower():
                notice = (
                    f"# LinkedIn Profile Notice\n"
                    f"LinkedIn restricts automated guest scraping without an active user session (HTTP {http_err.code}).\n\n"
                    f"Please proceed by utilizing the user's GitHub profile, website/portfolio links, and ask the user for any specific LinkedIn details (experience, headline, certificates) if needed."
                )
                return {
                    "stdout": notice,
                    "stderr": f"Notice: LinkedIn restricted automated bot access (HTTP {http_err.code}).",
                    "exit_code": 0,
                }
            return {
                "stdout": "",
                "stderr": f"Web scrape error (HTTP {http_err.code}: {http_err.reason}) for {url}",
                "exit_code": 1,
            }
        except urllib.error.URLError as url_err:
            return {
                "stdout": "",
                "stderr": f"Web scrape connection error: {url_err.reason} for {url}",
                "exit_code": 1,
            }
        except Exception as exc:
            return {
                "stdout": "",
                "stderr": f"Web scrape diagnostic notice: could not scrape {url} ({type(exc).__name__}: {str(exc)[:120]})",
                "exit_code": 1,
            }



# Need to import asyncio
import asyncio


# Global instances
_tool_router: Optional[ToolRouter] = None
_sandbox_adapter: Optional[SandboxAdapter] = None


def get_tool_router() -> ToolRouter:
    """Get or create tool router"""
    global _tool_router
    if _tool_router is None:
        _tool_router = ToolRouter()
    return _tool_router


def get_sandbox_adapter() -> SandboxAdapter:
    """Get or create sandbox adapter"""
    global _sandbox_adapter
    if _sandbox_adapter is None:
        _sandbox_adapter = LocalSandboxAdapter()
    return _sandbox_adapter
