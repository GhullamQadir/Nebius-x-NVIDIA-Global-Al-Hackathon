"""
Package layer API -- exposes the standalone ``packages/*`` router & adapters.

These routes are additive: they do not touch the documented run/workspace
surface served by ``api.routes``. They exist so the Odysseus UI can show what
``packages/model_router`` and ``packages/nebius_adapter`` decided, and so a
single completion can be driven through a package adapter end to end.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexora.backend.app.core.database import get_db
from nexora.backend.app.core.package_bridge import (
    NotConfigured,
    get_package_bridge,
)
from nexora.backend.app.models import ModelRegistry

router = APIRouter()


class PackageCompleteRequest(BaseModel):
    """Provider-neutral completion request forwarded to a package adapter."""

    prompt: str = Field(..., description="Prompt to complete")
    provider: str = Field(default="mock", description="mock | nebius")
    task_complexity: str = Field(default="low", description="low | moderate | high")
    tools: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Tool definitions the model may call"
    )
    token_budget: int = Field(default=1000, ge=1, le=32768)
    preferred_model: Optional[str] = Field(default=None, description="Pin a model id")


async def _registry_models(db: AsyncSession) -> List[ModelRegistry]:
    result = await db.execute(
        select(ModelRegistry).order_by(ModelRegistry.tier, ModelRegistry.display_name)
    )
    return list(result.scalars().all())


@router.get("/packages/routing")
async def package_routing(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Tier decisions from ``packages/model_router`` translated to registry rows."""
    bridge = get_package_bridge()
    models = await _registry_models(db)
    return await run_in_threadpool(bridge.routing_overview, models)


@router.post("/packages/complete")
async def package_complete(
    payload: PackageCompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Run one completion through a package adapter (mock by default)."""
    bridge = get_package_bridge()
    models = await _registry_models(db)
    decision = await run_in_threadpool(
        bridge.select, payload.task_complexity, payload.preferred_model, models
    )
    try:
        response = await run_in_threadpool(
            bridge.complete,
            payload.prompt,
            payload.provider,
            payload.task_complexity,
            payload.tools,
            payload.token_budget,
            payload.preferred_model,
        )
    except NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response["routing_decision"] = decision
    return response
