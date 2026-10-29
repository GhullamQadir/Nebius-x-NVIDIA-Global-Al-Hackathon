"""
Nexora API Routes
FastAPI routes for the backend
"""
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexora.backend.app.core.file_extractor import process_file_content, MAX_FILE_SIZE_BYTES

from nexora.backend.app.core.approval import ApprovalError, get_approval_manager
from nexora.backend.app.core.database import get_db
from nexora.backend.app.models import (
    Workspace,
    BudgetProfile,
    ModelRegistry,
    Run,
    RunEvent,
    RunStatus,
    RoutingMode,
    Approval,
    ApprovalStatus,
    RepositorySnapshot,
)
from nexora.backend.app.schemas import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceListResponse,
    BudgetProfileCreate,
    BudgetProfileUpdate,
    BudgetProfileResponse,
    ModelRegistryCreate,
    ModelRegistryUpdate,
    ModelRegistryResponse,
    RunCreate,
    RunUpdate,
    RunResponse,
    RunListResponse,
    RunDetailResponse,
    StartRunRequest,
    ApproveActionRequest,
    ApprovalResponse,
)
from nexora.backend.app.worker.orchestrator import run_orchestrator_task
from nexora.backend.config.settings import get_settings

router = APIRouter()

# Active in-memory execution tasks keyed by run_id string
_active_run_tasks: Dict[str, asyncio.Task] = {}


def pk(value: uuid.UUID | str) -> str:
    """Primary-key helper: id columns are ``String(36)``, not native UUIDs.

    Path/query parameters arrive as ``uuid.UUID`` after FastAPI validation.
    Passing one straight into ``db.get()`` makes the driver raise
    ``sqlite3.ProgrammingError: Error binding parameter 1: type 'UUID' is not
    supported`` (and on PostgreSQL it would mismatch the ``varchar`` column).
    Converting here also keeps the session identity map keyed consistently --
    mixing ``uuid.UUID`` and ``str`` keys for one row yields two distinct
    instances of the same entity.

    See ``UUID = String(36)`` in ``nexora.backend.app.models``.
    """
    return str(value)


# ============================================================
# Workspace Routes
# ============================================================

@router.post("/workspaces", response_model=WorkspaceResponse, status_code=status.HTTP_200_OK)
async def create_workspace(
    workspace: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new workspace"""
    db_workspace = Workspace(**workspace.model_dump())
    db.add(db_workspace)
    await db.flush()
    
    snapshot = RepositorySnapshot(
        workspace_id=db_workspace.id,
        snapshot_path=f"/tmp/workspaces/{db_workspace.id}",
        branch_name="main",
        commit_hash="initial_commit"
    )
    db.add(snapshot)
    
    await db.commit()
    await db.refresh(db_workspace)
    return db_workspace


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List workspaces with pagination"""
    query = select(Workspace)
    if active_only:
        query = query.where(Workspace.is_active == True)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Get paginated results
    query = query.order_by(Workspace.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    workspaces = result.scalars().all()
    
    return WorkspaceListResponse(
        workspaces=workspaces,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a workspace by ID"""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: uuid.UUID,
    workspace_update: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a workspace"""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    update_data = workspace_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)
    
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a workspace (soft delete)"""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    workspace.is_active = False
    await db.commit()


@router.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List directory tree of workspace files for the file explorer."""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    snap_query = await db.execute(
        select(RepositorySnapshot)
        .where(RepositorySnapshot.workspace_id == pk(workspace_id))
        .order_by(RepositorySnapshot.created_at.desc())
    )
    snapshot = snap_query.scalars().first()
    if not snapshot or not snapshot.snapshot_path:
        return {"files": [], "root": "", "workspace_name": workspace.name}

    root = Path(snapshot.snapshot_path).resolve()
    if not root.is_dir():
        fallback = (Path.cwd() / "nexora" / "fixtures" / workspace.name).resolve()
        if fallback.is_dir():
            root = fallback
        else:
            return {"files": [], "root": str(root), "workspace_name": workspace.name}

    files = []
    ignored = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".idea"}
    try:
        for p in sorted(root.rglob("*")):
            if any(part in ignored for part in p.parts):
                continue
            rel = p.relative_to(root).as_posix()
            files.append({
                "path": rel,
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
                "size": p.stat().st_size if p.is_file() else None,
            })
    except Exception as exc:
        pass

    return {"files": files, "root": str(root), "workspace_name": workspace.name}


@router.get("/workspaces/{workspace_id}/files/content")
async def read_workspace_file_content(
    workspace_id: uuid.UUID,
    path: str = Query(..., description="Relative file path within workspace"),
    db: AsyncSession = Depends(get_db),
):
    """Read a specific file from the workspace sandbox."""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    snap_query = await db.execute(
        select(RepositorySnapshot)
        .where(RepositorySnapshot.workspace_id == pk(workspace_id))
        .order_by(RepositorySnapshot.created_at.desc())
    )
    snapshot = snap_query.scalars().first()
    if not snapshot or not snapshot.snapshot_path:
        raise HTTPException(status_code=404, detail="No snapshot found for workspace")

    root = Path(snapshot.snapshot_path).resolve()
    if not root.is_dir():
        fallback = (Path.cwd() / "nexora" / "fixtures" / workspace.name).resolve()
        if fallback.is_dir():
            root = fallback

    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=403, detail="Access denied: outside workspace boundary")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content, "size": len(content)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read file: {exc}")


@router.post("/workspaces/{workspace_id}/upload")
async def upload_workspace_files(
    workspace_id: uuid.UUID,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload and extract multi-format files (code, documents, archives) up to 10MB."""
    workspace = await db.get(Workspace, pk(workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Locate workspace upload sandbox directory
    snap_query = await db.execute(
        select(RepositorySnapshot)
        .where(RepositorySnapshot.workspace_id == pk(workspace_id))
        .order_by(RepositorySnapshot.created_at.desc())
    )
    snapshot = snap_query.scalars().first()
    sandbox_dir = None
    if snapshot and snapshot.snapshot_path:
        root_cand = Path(snapshot.snapshot_path).resolve()
        if root_cand.is_dir():
            sandbox_dir = root_cand / "uploads"
    if not sandbox_dir:
        sandbox_dir = (Path.cwd() / "nexora" / "workspaces" / pk(workspace_id) / "uploads").resolve()
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for file in files:
        file_bytes = await file.read()
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File '{file.filename}' exceeds maximum allowed limit of 10 MB ({len(file_bytes)} bytes).",
            )

        extracted = process_file_content(
            file_bytes=file_bytes,
            filename=file.filename or "uploaded_file",
            sandbox_workspace_dir=sandbox_dir,
        )
        results.append(extracted.to_dict())

    return {
        "success": True,
        "workspace_id": pk(workspace_id),
        "uploaded_count": len(results),
        "files": results,
    }


# ============================================================
# Budget Profile Routes
# ============================================================

@router.post("/budget-profiles", response_model=BudgetProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_budget_profile(
    profile: BudgetProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a budget profile"""
    # If this is default, unset others
    if profile.is_default:
        await db.execute(
            BudgetProfile.__table__.update().values(is_default=False)
        )
    
    db_profile = BudgetProfile(**profile.model_dump())
    db.add(db_profile)
    await db.commit()
    await db.refresh(db_profile)
    return db_profile


@router.get("/budget-profiles", response_model=List[BudgetProfileResponse])
async def list_budget_profiles(
    db: AsyncSession = Depends(get_db),
):
    """List all budget profiles"""
    result = await db.execute(select(BudgetProfile).order_by(BudgetProfile.name))
    return result.scalars().all()


@router.get("/budget-profiles/{profile_id}", response_model=BudgetProfileResponse)
async def get_budget_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a budget profile"""
    profile = await db.get(BudgetProfile, pk(profile_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Budget profile not found")
    return profile


@router.patch("/budget-profiles/{profile_id}", response_model=BudgetProfileResponse)
async def update_budget_profile(
    profile_id: uuid.UUID,
    profile_update: BudgetProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a budget profile"""
    profile = await db.get(BudgetProfile, pk(profile_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Budget profile not found")
    
    # Handle default flag
    if profile_update.is_default is True:
        await db.execute(
            BudgetProfile.__table__.update().values(is_default=False)
        )
    
    update_data = profile_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)
    
    await db.commit()
    await db.refresh(profile)
    return profile


# ============================================================
# Model Registry Routes
# ============================================================

@router.post("/models", response_model=ModelRegistryResponse, status_code=status.HTTP_201_CREATED)
async def create_model(
    model: ModelRegistryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new model"""
    db_model = ModelRegistry(**model.model_dump())
    db.add(db_model)
    await db.commit()
    await db.refresh(db_model)
    return db_model


@router.get("/models", response_model=List[ModelRegistryResponse])
async def list_models(
    enabled_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List registered models"""
    query = select(ModelRegistry)
    if enabled_only:
        query = query.where(ModelRegistry.is_enabled == True)
    query = query.order_by(ModelRegistry.tier, ModelRegistry.display_name)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/models/{model_id}", response_model=ModelRegistryResponse)
async def get_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a model by ID"""
    model = await db.get(ModelRegistry, pk(model_id))
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch("/models/{model_id}", response_model=ModelRegistryResponse)
async def update_model(
    model_id: uuid.UUID,
    model_update: ModelRegistryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a model"""
    model = await db.get(ModelRegistry, pk(model_id))
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    update_data = model_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model, field, value)
    
    await db.commit()
    await db.refresh(model)
    return model


# ============================================================
# Run Routes
# ============================================================

@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_200_OK)
async def create_run(
    run: RunCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new run, or continue an existing chat thread if parent_run_id is set."""
    # Import here to avoid circular dependency
    from nexora.backend.app.worker.orchestrator import RunOrchestrator
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            orchestrator = RunOrchestrator(db)
            created_run = await orchestrator.create_run(
                workspace_id=str(run.workspace_id),
                task_text=run.task_text,
                routing_mode=run.routing_mode,
                requested_model_id=str(run.requested_model_id) if run.requested_model_id else None,
                budget_profile_name=None,  # Will use default
                parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
                healing_mode=getattr(run, "healing_mode", "auto") or "auto",
                detail_level=getattr(run, "detail_level", "auto") or "auto",
            )
            await db.commit()
            return created_run
        except Exception as exc:
            if "locked" in str(exc).lower() and attempt < max_retries - 1:
                await db.rollback()
                await asyncio.sleep(0.3 * (attempt + 1))
                continue
            raise


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    workspace_id: Optional[uuid.UUID] = None,
    status: Optional[RunStatus] = None,
    q: Optional[str] = Query(None, min_length=1, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List runs with optional conversation-history search and pagination."""
    query = select(Run)
    
    if workspace_id:
        query = query.where(Run.workspace_id == pk(workspace_id))
    if status:
        query = query.where(Run.status == status)
    if q and (search_text := q.strip()):
        escaped_text = search_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{escaped_text}%"
        query = query.where(or_(
            Run.task_text.ilike(search_pattern, escape="\\"),
            cast(Run.conversation_history, String).ilike(search_pattern, escape="\\"),
        ))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Get paginated results
    query = query.order_by(Run.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    runs = result.scalars().all()
    
    return RunListResponse(
        runs=runs,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get complete run details"""
    run = await db.get(Run, pk(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Load all related data
    from sqlalchemy.orm import selectinload
    
    query = select(Run).where(Run.id == pk(run_id)).options(
        selectinload(Run.events),
        selectinload(Run.task_analysis),
        selectinload(Run.security_decision),
        selectinload(Run.plan),
        selectinload(Run.context_packages),
        selectinload(Run.tool_requests),
        selectinload(Run.policy_decisions),
        selectinload(Run.approvals),
        selectinload(Run.tool_executions),
        selectinload(Run.validation_findings),
        selectinload(Run.run_result),
        selectinload(Run.audit_events),
    )
    result = await db.execute(query)
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return RunDetailResponse(
        run=run,
        task_analysis=run.task_analysis,
        security_decision=run.security_decision,
        plan=run.plan,
        context_packages=run.context_packages,
        tool_requests=run.tool_requests,
        policy_decisions=run.policy_decisions,
        approvals=run.approvals,
        tool_executions=run.tool_executions,
        validation_findings=run.validation_findings,
        run_result=run.run_result,
        audit_events=run.audit_events,
        events=run.events,
    )


@router.post("/runs/{run_id}/start", response_model=RunResponse)
async def start_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Start/continue run execution.

    Two entry points, matching the orchestrator's documented flow:

    * ``QUEUED`` -- a freshly created run. Runs the local task analysis ->
      security review -> planning phases and leaves the run in
      ``AWAITING_START`` with a plan for review.
    * ``AWAITING_START`` -- plan acceptance. Hands off to the execution loop.
    """
    run = await db.get(Run, pk(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Import here to avoid circular dependency
    from nexora.backend.app.worker.orchestrator import RunOrchestrator
    
    if run.status == RunStatus.QUEUED:
        # First start: create_run() only records the run (step 1 of the
        # orchestrator flow). RunOrchestrator.start_run() drives the run
        # through analysis/security/planning to AWAITING_START.
        orchestrator = RunOrchestrator(db)
        run = await orchestrator.start_run(str(run_id))
        await db.commit()
        await db.refresh(run)
        return run
    
    if run.status != RunStatus.AWAITING_START:
        raise HTTPException(
            status_code=400,
            detail=f"Run cannot be started from status: {run.status.value}"
        )
    
    # accept_plan_and_execute() re-binds the run-scoped state it needs
    # (audit log, context optimizer, validator, model router).
    orchestrator = RunOrchestrator(db)
    orchestrator.run = run
    
    await orchestrator.accept_plan_and_execute()
    await db.commit()
    # ``Run.updated_at`` carries ``onupdate=func.now()``, so the flush expires it
    # and the next read would try to refresh it lazily -- which fails once the
    # response is serialized outside the greenlet that owns the connection.
    await db.refresh(run)
    
    return run


@router.post("/runs/{run_id}/approve", response_model=ApprovalResponse)
async def approve_action(
    run_id: uuid.UUID,
    request: ApproveActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a pending action.

    The approver identity is taken from server configuration; a client-supplied
    identity is never trusted. The approval must belong to this run and be
    pending and unexpired, otherwise the decision is refused.
    """
    run = await db.get(Run, pk(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    approval_manager = get_approval_manager()
    
    approval = approval_manager.get_approval(str(request.approval_id))
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    if approval.run_id != str(run_id):
        raise HTTPException(status_code=403, detail="Approval does not belong to this run")
    
    # Record decision under the server-owned operator identity.
    try:
        approval_record = approval_manager.decide(
            str(request.approval_id),
            request.approve,
            get_settings().OPERATOR_ID,
            expected_run_id=str(run_id),
        )
    except ApprovalError as exc:
        # Expired / already decided / invalid -> a safe, generic conflict.
        raise HTTPException(status_code=409, detail=str(exc))
    
    # Update database
    db_approval = await db.get(Approval, pk(request.approval_id))
    if db_approval:
        db_approval.status = approval_record.status
        db_approval.approver_id = approval_record.approver_id
        db_approval.decided_at = approval_record.decided_at

    # Auditable run event correlated with the run and approval identifiers.
    db.add(RunEvent(
        run_id=run.id,
        event_type="approval_granted" if request.approve else "approval_rejected",
        stage="awaiting_approval",
        message=f"Approval {approval_record.status.value}",
        event_metadata={
            "approval_id": str(request.approval_id),
            "approver_id": approval_record.approver_id,
        },
    ))
    
    await db.commit()
    
    # If approved, the run will continue via polling or websocket
    # For now, return the approval status
    return approval_record


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running run with instant stop authority."""
    run_str = pk(run_id)
    # 1. Immediately cancel the active asyncio.Task in memory if currently executing
    task = _active_run_tasks.get(run_str)
    if task and not task.done():
        task.cancel()

    run = await db.get(Run, run_str)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED):
        return run
    
    run.status = RunStatus.CANCELLED
    run.completed_at = datetime.now()
    if not run.result_summary or not isinstance(run.result_summary, dict) or not run.result_summary.get("content"):
        run.result_summary = {"type": "assistant_response", "content": "Run cancelled by user.", "cancelled": True}
    
    db.add(RunEvent(
        run_id=run.id,
        event_type="run_cancelled",
        stage="cancelled",
        message="Run cancelled immediately by user request",
    ))
    await db.commit()
    # See the note in start_run(): ``updated_at`` is expired by the flush and
    # must be refreshed before the ORM object is serialized into the response.
    await db.refresh(run)
    
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Stream real-time inference tokens and lifecycle events via Server-Sent Events (SSE)."""
    run = await db.get(Run, pk(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        # If run is already in a terminal state, stream stored output and exit immediately
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.CANCELLED):
            content = ""
            if run.result_summary and isinstance(run.result_summary, dict):
                content = run.result_summary.get("content", "")
            if content:
                yield f"event: delta\ndata: {json.dumps({'type': 'delta', 'content': content})}\n\n"
            yield f"event: done\ndata: {json.dumps({'type': 'done', 'status': run.status.value, 'run_id': str(run.id), 'result_summary': run.result_summary})}\n\n"
            return

        queue = asyncio.Queue()
        from nexora.backend.app.worker.orchestrator import RunOrchestrator
        from nexora.backend.app.core.database import get_db_context

        async def worker():
            try:
                async with get_db_context() as stream_db:
                    orch = RunOrchestrator(stream_db, event_queue=queue)
                    await orch.start_run(str(run_id))
            except asyncio.CancelledError:
                # Handle task cancellation gracefully
                await queue.put({
                    "type": "done",
                    "status": "cancelled",
                    "run_id": str(run_id),
                    "result_summary": {"content": "Run cancelled.", "cancelled": True},
                })
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        _active_run_tasks[str(run_id)] = task

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_name = item.get("type", "message")
                data_str = json.dumps(item)
                yield f"event: {event_name}\ndata: {data_str}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            if not task.done():
                task.cancel()
            raise
        finally:
            _active_run_tasks.pop(str(run_id), None)
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# Health Check
# ============================================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Nexora-backend"}
