#!/usr/bin/env python3
"""
Nexora Database Migration Script
Runs the schema against PostgreSQL
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path (parent of nexora/)
project_root = Path(__file__).parent.parent
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
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    # Split into statements
    statements = [s.strip() for s in schema_sql.split(';') if s.strip()]

    # Create engine
    engine = create_async_engine(
        settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
        echo=True,
    )

    async with engine.begin() as conn:
        for i, statement in enumerate(statements):
            if statement:
                try:
                    await conn.exec_driver_sql(statement)
                    print(f"✓ Statement {i+1}/{len(statements)} executed")
                except Exception as e:
                    print(f"✗ Statement {i+1} failed: {e}")
                    print(f"  SQL: {statement[:100]}...")

    await engine.dispose()
    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(run_migration())
