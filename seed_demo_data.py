"""Seed the demo data the Nexora backend needs to create runs.

The backend's ``RunOrchestrator.create_run`` requires two things that a fresh
migration does not populate:

1. at least one enabled row in ``model_registry`` (``ValueError: No enabled
   models in registry`` otherwise).
2. at least one default budget profile.

This script is idempotent: re-running it updates the existing rows instead of
duplicating them. It only writes seed data -- no backend code is touched.

    python seed_demo_data.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "nexora.db"

NEBIUS_MODELS = [
    {
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "display_name": "Meta Llama 3.1 8B Instruct",
        "tier": "nano",
        "context_capacity": 32_000,
        "max_output_tokens": 2_048,
        "supports_reasoning": 0,
    },
    {
        "model_id": "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "display_name": "Meta Llama 3.1 70B Instruct",
        "tier": "super",
        "context_capacity": 64_000,
        "max_output_tokens": 4_096,
        "supports_reasoning": 1,
    },
    {
        "model_id": "deepseek-ai/DeepSeek-R1-0528",
        "display_name": "DeepSeek R1 0528",
        "tier": "ultra",
        "context_capacity": 128_000,
        "max_output_tokens": 4_096,
        "supports_reasoning": 1,
    },
]

NEMOTRON_MODELS = [
    {
        "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "display_name": "NVIDIA Nemotron 3 Nano 30B A3B",
        "tier": "nano",
        "context_capacity": 131_072,
        "max_output_tokens": 4_096,
    },
    {
        "model_id": "nvidia/Nemotron-3_5-Lightning",
        "display_name": "NVIDIA Nemotron 3.5 Lightning",
        "tier": "nano",
        "context_capacity": 131_072,
        "max_output_tokens": 4_096,
    },
    {
        "model_id": "nvidia/nemotron-3-super-120b-a12b",
        "display_name": "NVIDIA Nemotron 3 Super 120B A12B",
        "tier": "super",
        "context_capacity": 131_072,
        "max_output_tokens": 4_096,
    },
    {
        "model_id": "nvidia/Nemotron-3-Ultra-550b-a55b",
        "display_name": "NVIDIA Nemotron 3 Ultra 550B A55B",
        "tier": "ultra",
        "context_capacity": 131_072,
        "max_output_tokens": 4_096,
    },
]

# Secondary provider. Nebius rows already exist from the migration; these Gemini
# rows are appended AFTER them on purpose -- ``ModelRouter.route`` picks the
# first row of the matching tier bucket in registry order, so appending keeps
# auto-routing on the primary provider. Gemini is reachable only through
# ``RoutingMode.FIXED`` + ``requested_model_id``.
GEMINI_MODELS = [
    {
        "model_id": "gemini-3.8-flash",
        "display_name": "Gemini 3.8 Flash",
        "tier": "super",
        "context_capacity": 1_048_576,
        "max_output_tokens": 8_192,
        "is_enabled": 1,
    },
    {
        "model_id": "gemini-3.5-flash-lite",
        "display_name": "Gemini 3.5 Flash Lite",
        "tier": "nano",
        "context_capacity": 1_048_576,
        "max_output_tokens": 4_096,
        "is_enabled": 1,
    },
    {
        # Registered but off: this key's quota tier rejects it with HTTP 429,
        # so it stays opt-in rather than breaking a run mid-flight.
        "model_id": "gemini-3.1-pro-preview",
        "display_name": "Gemini 3.1 Pro (preview)",
        "tier": "ultra",
        "context_capacity": 1_048_576,
        "max_output_tokens": 8_192,
        "is_enabled": 0,
    },
]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def seed_gemini_models(con: sqlite3.Connection) -> int:
    """Register Gemini rows as the secondary provider.

    Appended after the primary provider's rows so registry order -- and with it
    ``ModelRouter``'s auto tier pick -- stays on Nebius.
    """
    inserted = 0
    for spec in GEMINI_MODELS:
        row = con.execute(
            "SELECT id FROM model_registry WHERE model_id = ?", (spec["model_id"],)
        ).fetchone()
        if row:
            con.execute(
                "UPDATE model_registry SET display_name = ?, provider = 'gemini',"
                " tier = ?, context_capacity = ?, max_output_tokens = ?,"
                " supports_tools = 1, supports_reasoning = 1, terms_reviewed = 1"
                " WHERE id = ?",
                (
                    spec["display_name"],
                    spec["tier"],
                    spec["context_capacity"],
                    spec["max_output_tokens"],
                    row["id"],
                ),
            )
            continue

        con.execute(
            "INSERT INTO model_registry"
            " (id, model_id, display_name, provider, tier, context_capacity,"
            "  max_output_tokens, supports_tools, supports_reasoning, is_enabled,"
            "  terms_reviewed, created_at)"
            " VALUES (?, ?, ?, 'gemini', ?, ?, ?, 1, 1, ?, 1, ?)",
            (
                str(uuid.uuid4()),
                spec["model_id"],
                spec["display_name"],
                spec["tier"],
                spec["context_capacity"],
                spec["max_output_tokens"],
                spec["is_enabled"],
                utcnow(),
            ),
        )
        inserted += 1
    return inserted


def seed_nebius_models(con: sqlite3.Connection) -> int:
    """Sync primary registry IDs with the NVIDIA API's advertised model IDs."""
    updated = 0
    for spec in NEBIUS_MODELS:
        row = con.execute(
            "SELECT id FROM model_registry WHERE provider = 'nebius' AND tier = ?",
            (spec["tier"],),
        ).fetchone()
        if row:
            con.execute(
                "UPDATE model_registry SET model_id = ?, display_name = ?,"
                " context_capacity = ?, max_output_tokens = ?,"
                " supports_tools = 1, supports_reasoning = ?, is_enabled = 1,"
                " terms_reviewed = 1 WHERE id = ?",
                (
                    spec["model_id"],
                    spec["display_name"],
                    spec["context_capacity"],
                    spec["max_output_tokens"],
                    spec["supports_reasoning"],
                    row["id"],
                ),
            )
        else:
            con.execute(
                "INSERT INTO model_registry"
                " (id, model_id, display_name, provider, tier, context_capacity,"
                "  max_output_tokens, supports_tools, supports_reasoning,"
                "  is_enabled, terms_reviewed, created_at)"
                " VALUES (?, ?, ?, 'nebius', ?, ?, ?, 1, ?, 1, 1, ?)",
                (
                    str(uuid.uuid4()),
                    spec["model_id"],
                    spec["display_name"],
                    spec["tier"],
                    spec["context_capacity"],
                    spec["max_output_tokens"],
                    spec["supports_reasoning"],
                    utcnow(),
                ),
            )
        updated += 1
    return updated


def seed_nemotron_models(con: sqlite3.Connection) -> int:
    """Add Nemotron variants without replacing the existing tier defaults."""
    added = 0
    for spec in NEMOTRON_MODELS:
        row = con.execute(
            "SELECT id FROM model_registry WHERE model_id = ?",
            (spec["model_id"],),
        ).fetchone()
        if row:
            con.execute(
                "UPDATE model_registry SET display_name = ?, provider = 'nebius',"
                " tier = ?, context_capacity = ?, max_output_tokens = ?,"
                " supports_tools = 1, supports_reasoning = 1, is_enabled = 1,"
                " terms_reviewed = 1 WHERE id = ?",
                (
                    spec["display_name"],
                    spec["tier"],
                    spec["context_capacity"],
                    spec["max_output_tokens"],
                    row["id"],
                ),
            )
            continue

        con.execute(
            "INSERT INTO model_registry"
            " (id, model_id, display_name, provider, tier, context_capacity,"
            "  max_output_tokens, supports_tools, supports_reasoning, is_enabled,"
            "  terms_reviewed, created_at)"
            " VALUES (?, ?, ?, 'nebius', ?, ?, ?, 1, 1, 1, 1, ?)",
            (
                str(uuid.uuid4()),
                spec["model_id"],
                spec["display_name"],
                spec["tier"],
                spec["context_capacity"],
                spec["max_output_tokens"],
                utcnow(),
            ),
        )
        added += 1
    return added


def seed_models(con: sqlite3.Connection) -> int:
    """Seed model metadata, enabling only the requested Nemotron tiers."""
    primary_synced = seed_nebius_models(con)
    nemotron_added = seed_nemotron_models(con)
    added = seed_gemini_models(con)
    con.execute("UPDATE model_registry SET is_enabled = 0")
    enabled = 0
    for spec in NEMOTRON_MODELS:
        enabled += con.execute(
            "UPDATE model_registry SET is_enabled = 1, terms_reviewed = 1"
            " WHERE model_id = ? AND provider = 'nebius'",
            (spec["model_id"],),
        ).rowcount

    print(
        f"  {primary_synced} Nebius row(s) synced, "
        f"{nemotron_added} Nemotron row(s) added, {added} Gemini row(s) inserted"
    )
    for row in con.execute(
        "SELECT model_id, display_name, provider, tier, is_enabled"
        " FROM model_registry ORDER BY rowid"
    ):
        flag = "on " if row["is_enabled"] else "off"
        print(
            f"  model     {row['model_id']:<24} {row['display_name']:<24}"
            f" {row['provider']:<7} tier={row['tier']:<6} {flag}"
        )
    return enabled or 0


def seed_budget_profile(con: sqlite3.Connection) -> int:
    """Ensure a default budget profile exists."""
    # Check if any budget profile exists
    existing = con.execute("SELECT id FROM budget_profiles LIMIT 1").fetchone()
    if existing:
        # Ensure one is default
        con.execute("UPDATE budget_profiles SET is_default = 0")
        con.execute("UPDATE budget_profiles SET is_default = 1 WHERE id = ?", (existing["id"],))
        print(f"  budget    using existing profile: {existing['id']}")
        return 0

    # Create a default budget profile
    profile_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO budget_profiles (id, name, description, max_input_tokens, max_output_tokens, max_total_tokens, max_steps, max_tool_calls, is_default, created_at)"
        " VALUES (?, 'default', 'Default budget profile', 100000, 8192, 200000, 50, 100, 1, ?)",
        (profile_id, utcnow()),
    )
    print(f"  budget    created default profile: {profile_id}")
    return 1


def ensure_workspace_exists(con: sqlite3.Connection) -> str:
    """Ensure at least one workspace exists. Returns workspace_id."""
    existing = con.execute("SELECT id FROM workspaces WHERE is_active = 1 LIMIT 1").fetchone()
    if existing:
        print(f"  workspace using existing: {existing['id']}")
        return existing["id"]

    # Create a default empty workspace
    ws_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO workspaces (id, name, description, repository_url, repository_type, is_active, created_at, updated_at)"
        " VALUES (?, 'default', 'Default workspace', '', 'python', 1, ?, ?)",
        (ws_id, utcnow(), utcnow()),
    )
    # Create a snapshot pointing to current directory (empty but valid)
    cwd = str(Path.cwd()).replace("\\", "/")
    con.execute(
        "INSERT INTO repository_snapshots (id, workspace_id, commit_hash, branch_name, snapshot_path, created_at)"
        " VALUES (?, ?, 'initial', 'main', ?, ?)",
        (snapshot_id, ws_id, cwd, utcnow()),
    )
    print(f"  workspace created default: {ws_id} -> {cwd}")
    return ws_id


def verify(con: sqlite3.Connection) -> None:
    problems: list[str] = []

    if not con.execute(
        "SELECT 1 FROM model_registry WHERE is_enabled = 1 LIMIT 1"
    ).fetchone():
        problems.append("no enabled models in model_registry")

    # Auto routing picks the first enabled row of the matching tier bucket in
    # registry order, so a secondary-provider row inserted ahead of the primary
    # one would silently take over auto mode. Fail loudly instead.
    expected_ids: dict[str, set[str]] = {}
    for model in NEMOTRON_MODELS:
        expected_ids.setdefault(model["tier"], set()).add(model["model_id"])
    for tier in ("nano", "super", "ultra"):
        head = con.execute(
            "SELECT provider, model_id FROM model_registry"
            " WHERE is_enabled = 1 AND tier = ? ORDER BY rowid LIMIT 1",
            (tier,),
        ).fetchone()
        if head and (
            head["provider"] != "nebius"
            or head["model_id"] not in expected_ids[tier]
        ):
            problems.append(
                f"auto-routing for tier {tier!r} resolves to "
                f"{head['provider']!r}/{head['model_id']!r}, expected "
                f"nebius/{expected_ids[tier]!r}"
            )

    if not con.execute(
        "SELECT 1 FROM budget_profiles WHERE is_default = 1 LIMIT 1"
    ).fetchone():
        problems.append("no default budget profile")

    if not con.execute(
        "SELECT 1 FROM workspaces WHERE is_active = 1 LIMIT 1"
    ).fetchone():
        problems.append("no active workspace")

    if problems:
        print("\nFAILED:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("\nOK: models enabled, budget profile set, workspace exists.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    args = parser.parse_args()

    print(f"Seeding {args.db}")
    con = connect(args.db)
    try:
        print("\nModel registry:")
        models = seed_models(con)
        print(f"  ({models} row(s) enabled)\n")

        print("Budget profile:")
        seed_budget_profile(con)
        print()

        print("Workspace:")
        ensure_workspace_exists(con)
        print()

        con.commit()
        verify(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())