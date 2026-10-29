#!/usr/bin/env python3
"""
Nexora Database Migration Script - SQLite Version
Runs the schema against SQLite
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set working directory to project root
import os
os.chdir(project_root)

from sqlalchemy.ext.asyncio import create_async_engine
from nexora.backend.config.settings import get_settings

settings = get_settings()


async def run_migration():
    """Run the database schema migration"""
    # Read schema
    schema_path = project_root / "Nexora" / "database" / "schema_sqlite.sql"
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    # Split into statements
    statements = [s.strip() for s in schema_sql.split(';') if s.strip()]

    # Create engine - use SQLite directly
    engine = create_async_engine(
        "sqlite+aiosqlite:///./nexora.db",
        echo=True,
    )

    async with engine.begin() as conn:
        for i, statement in enumerate(statements):
            if statement:
                try:
                    await conn.exec_driver_sql(statement)
                    print(f"[OK] Statement {i+1}/{len(statements)} executed")
                except Exception as e:
                    print(f"[FAIL] Statement {i+1} failed: {e}")
                    print(f"  SQL: {statement[:100]}...")

    await engine.dispose()
    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(run_migration())

