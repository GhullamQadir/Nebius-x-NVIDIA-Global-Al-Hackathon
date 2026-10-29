"""
Nexora Cross-Run Agent Memory (lightweight, file-based).

Stores per-run outcomes, success/failure patterns, and tool effectiveness
so that subsequent runs can learn from past experience. No database schema
changes required — data lives in a JSON file under the workspace.

Designed to be non-invasive: import and call record_run_outcome() from the
orchestrator at run completion; everything else is optional.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_MEMORY_FILE = Path(os.environ.get("NEXORA_MEMORY_FILE", ".nexora_agent_memory.json"))


def _load() -> Dict[str, Any]:
    if not _MEMORY_FILE.exists():
        return {"runs": [], "tool_success": {}, "patterns": {}, "created_at": _now()}
    try:
        with open(_MEMORY_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"runs": [], "tool_success": {}, "patterns": {}, "created_at": _now()}


def _save(data: Dict[str, Any]) -> None:
    try:
        _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_MEMORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    except OSError:
        pass  # memory is best-effort; never fail a run because of it


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_run_outcome(
    run_id: str,
    objective: str,
    status: str,
    tools_used: Optional[List[str]] = None,
    output_tokens: int = 0,
    truncated: bool = False,
    error: Optional[str] = None,
) -> None:
    """Record the outcome of a completed run for cross-run learning."""
    data = _load()
    entry = {
        "run_id": run_id,
        "objective": objective,
        "status": status,
        "tools_used": tools_used or [],
        "output_tokens": output_tokens,
        "truncated": truncated,
        "error": error,
        "timestamp": _now(),
    }
    data.setdefault("runs", []).append(entry)
    # Keep only last 500 runs to bound file size
    if len(data["runs"]) > 500:
        data["runs"] = data["runs"][-500:]

    # Track per-tool success/failure
    for tool in (tools_used or []):
        ts = data.setdefault("tool_success", {}).setdefault(tool, {"success": 0, "failure": 0, "total": 0})
        ts["total"] += 1
        if status in ("COMPLETED", "completed"):
            ts["success"] += 1
        else:
            ts["failure"] += 1

    # Track simple failure patterns by objective keyword
    if status not in ("COMPLETED", "completed") and error:
        key = objective.lower().split()[0] if objective.split() else "unknown"
        pat = data.setdefault("patterns", {}).setdefault(key, {"failures": 0, "examples": []})
        pat["failures"] += 1
        if len(pat["examples"]) < 5:
            pat["examples"].append({"objective": objective, "error": str(error)[:200], "timestamp": _now()})

    _save(data)


def get_tool_reliability(tool_name: str) -> Dict[str, Any]:
    """Return success/failure stats for a tool (best-effort, empty if none)."""
    data = _load()
    return data.get("tool_success", {}).get(tool_name, {"success": 0, "failure": 0, "total": 0})


def get_recent_failures(limit: int = 10) -> List[Dict[str, Any]]:
    """Return most recent failed runs."""
    data = _load()
    failed = [r for r in data.get("runs", []) if r.get("status") not in ("COMPLETED", "completed")]
    return failed[-limit:]
