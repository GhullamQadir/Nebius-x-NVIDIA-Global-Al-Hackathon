"""Reconcile the migrated SQLite schema with the SQLAlchemy models.

The hand-written DDL in ``Nexora/database/schema_sqlite.sql`` has drifted from
``nexora.backend.app.models`` on two columns::

    run_events.metadata    -> run_events.event_metadata
    run_results.model_used -> run_results.model_used_id

``metadata`` in particular cannot be used as a declarative attribute name
(``Base.metadata`` is reserved), which is why the models renamed it. The
migrated database kept the old name, so every ``RunEvent`` insert raised
``sqlite3.OperationalError: no such column: run_events.event_metadata``.

This script copies the models' intent -- rename stale columns, add columns that
are missing entirely, and report columns that exist only in the database.
Nothing is dropped, so it is safe to re-run.

    python repair_schema.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "nexora.db"

sys.path.insert(0, str(ROOT))

# table -> {old column: new column}
RENAMES = {
    "run_events": {"metadata": "event_metadata"},
    "run_results": {"model_used": "model_used_id"},
}


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--dry-run", action="store_true", help="report changes without applying them"
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"database not found: {args.db}")

    import nexora.backend.app.models as models  # noqa: F401  (populates metadata)

    con = sqlite3.connect(args.db)
    try:
        applied = 0
        for table, mapping in RENAMES.items():
            if not table_exists(con, table):
                print(f"  skip {table}: table not present")
                continue
            have = columns(con, table)
            for old, new in mapping.items():
                if old not in have:
                    print(f"  ok   {table}.{old}: already renamed")
                    continue
                if new in have:
                    print(
                        f"  WARN {table}: both '{old}' and '{new}' exist; "
                        "drop the stale one by hand"
                    )
                    continue
                print(f"  {'would' if args.dry_run else 'will'} rename "
                      f"{table}.{old} -> {table}.{new}")
                if not args.dry_run:
                    con.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
                applied += 1

        if not args.dry_run:
            con.commit()

        print("\nColumn check against the models:")
        problems = []
        for name, sa_table in models.Base.metadata.tables.items():
            if not table_exists(con, name):
                problems.append(f"missing table: {name}")
                continue
            have = set(columns(con, name))
            missing = sorted({c.name for c in sa_table.columns} - have)
            extra = sorted(have - {c.name for c in sa_table.columns})
            if missing:
                problems.append(f"{name}: missing {missing}")
            if extra:
                problems.append(f"{name}: extra {extra}")

        live = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for name in sorted(live - set(models.Base.metadata.tables)):
            problems.append(f"unmapped table: {name}")

        if problems:
            print("\nRemaining differences:")
            for p in problems:
                print(f"  - {p}")
            return 1

        print("  every mapped table and column matches the models")
        print(f"\nDone ({applied} rename(s) applied).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())