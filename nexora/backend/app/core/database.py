"""
Nexora Database Core
Async SQLAlchemy setup with connection pooling
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from nexora.backend.config.settings import get_settings
from nexora.backend.app.models import Base, BudgetProfile, ModelRegistry

settings = get_settings()

NEMOTRON_MODELS = (
    ("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "NVIDIA Nemotron 3 Nano 30B A3B", "nano"),
    ("nvidia/Nemotron-3_5-Lightning", "NVIDIA Nemotron 3.5 Lightning", "nano"),
    ("nvidia/nemotron-3-super-120b-a12b", "NVIDIA Nemotron 3 Super 120B A12B", "super"),
    ("nvidia/Nemotron-3-Ultra-550b-a55b", "NVIDIA Nemotron 3 Ultra 550B A55B", "ultra"),
)
NEMOTRON_MODEL_IDS = tuple(model_id for model_id, _, _ in NEMOTRON_MODELS)

# Create async engine — pool_size/max_overflow are PostgreSQL-only
_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
    "poolclass": NullPool if settings.ENVIRONMENT == "test" else None,
}
if _db_url.startswith("postgresql"):
    _engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW
elif "sqlite" in _db_url:
    _engine_kwargs["connect_args"] = {"timeout": 60}

engine: AsyncEngine = create_async_engine(_db_url, **_engine_kwargs)

if "sqlite" in _db_url:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=60000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside FastAPI"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create missing tables and seed Nemotron models in registry."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # Ensure a default budget profile exists
        profile = await session.scalar(
            select(BudgetProfile).where(BudgetProfile.is_default.is_(True)).limit(1)
        )
        if profile is None:
            session.add(BudgetProfile(
                name="default",
                description="Default budget profile",
                max_steps=10,
                max_tool_calls=20,
                max_retries=1,
                timeout_seconds=300,
                max_input_tokens=16000,
                max_output_tokens=8192,
                is_default=True,
            ))
        else:
            profile.max_output_tokens = 8192
            profile.max_input_tokens = max(profile.max_input_tokens or 0, 16000)

        # Seed Nemotron models from Nebius
        for model_id, display_name, tier in NEMOTRON_MODELS:
            model = await session.scalar(
                select(ModelRegistry).where(ModelRegistry.model_id == model_id).limit(1)
            )
            if model is None:
                model = ModelRegistry(
                    model_id=model_id,
                    display_name=display_name,
                    provider="nebius",
                    tier=tier,
                    context_capacity=131072,
                    max_output_tokens=8192,
                    supports_tools=True,
                    supports_reasoning=True,
                    is_enabled=True,
                    terms_reviewed=True,
                )
                session.add(model)
            else:
                model.display_name = display_name
                model.provider = "nebius"
                model.tier = tier
                model.context_capacity = 131072
                model.max_output_tokens = 4096
                model.supports_tools = True
                model.supports_reasoning = True
                model.is_enabled = True
                model.terms_reviewed = True

        await session.execute(update(ModelRegistry).values(is_enabled=False))
        await session.execute(
            update(ModelRegistry)
            .where(
                ModelRegistry.model_id.in_(NEMOTRON_MODEL_IDS),
                ModelRegistry.provider == "nebius",
            )
            .values(is_enabled=True, terms_reviewed=True)
        )

        await session.commit()


async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()
