from typing import List
from fastapi import APIRouter, HTTPException, status
from packages.contracts.run import (
    CreateRunRequest,
    RunResponse,
    CancelRunResponse,
)
from apps.orchestrator.state_machine import (
    run_store,
    InvalidStateTransitionError,
)

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED, summary="Create a new task run")
async def create_run(req: CreateRunRequest):
    """
    Submits a new coding task against a target repository.
    Initializes state machine to QUEUED, computes initial task analysis,
    and allocates execution budgets.
    """
    try:
        run = run_store.create_run(req)
        return run
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[RunResponse], summary="List all runs")
async def list_runs():
    """
    Returns all in-memory runs and their current lifecycle states.
    """
    return run_store.list_runs()


@router.get("/{run_id}", response_model=RunResponse, summary="Get details for a specific run")
async def get_run(run_id: str):
    """
    Retrieves full execution details, current stage, security decisions,
    and generated artifacts for a run.
    """
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with ID '{run_id}' not found."
        )
    return run


@router.post("/{run_id}/cancel", response_model=CancelRunResponse, summary="Cancel an in-flight run")
async def cancel_run(run_id: str):
    """
    Safely transitions an active run to CANCELLED state.
    """
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with ID '{run_id}' not found."
        )
    try:
        cancelled_run = run_store.cancel_run(run_id)
        return CancelRunResponse(
            run_id=run_id,
            status=cancelled_run.state.value,
            message=f"Run {run_id} transitioned to {cancelled_run.state.value}."
        )
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )


@router.post("/{run_id}/advance", response_model=RunResponse, summary="Advance run to next pipeline stage (Mock/Demo)")
async def advance_run(run_id: str):
    """
    Advances the run through the 11-stage pipeline for testing and live demonstration.
    """
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run with ID '{run_id}' not found."
        )
    try:
        return run_store.advance_mock_pipeline(run_id)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
