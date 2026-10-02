"""Tests for RunStateMachine invariants and InMemoryRunStore lifecycle."""
import pytest
from packages.contracts.run import RunState, CreateRunRequest, RepositoryTarget
from apps.orchestrator.state_machine import (
    RunStateMachine,
    InMemoryRunStore,
    InvalidStateTransitionError,
)


# ---------------------------------------------------------------------------
# RunStateMachine — valid transitions
# ---------------------------------------------------------------------------

def test_valid_state_transitions():
    """All expected forward transitions are allowed."""
    assert RunStateMachine.can_transition(RunState.QUEUED, RunState.ANALYZING)
    assert RunStateMachine.can_transition(RunState.ANALYZING, RunState.SECURITY_REVIEW)
    assert RunStateMachine.can_transition(RunState.SECURITY_REVIEW, RunState.PLANNING)
    assert RunStateMachine.can_transition(RunState.SECURITY_REVIEW, RunState.AWAITING_APPROVAL)
    assert RunStateMachine.can_transition(RunState.AWAITING_APPROVAL, RunState.PLANNING)
    assert RunStateMachine.can_transition(RunState.PLANNING, RunState.CONTEXT_BUILD)
    assert RunStateMachine.can_transition(RunState.CONTEXT_BUILD, RunState.MODEL_STEP)
    assert RunStateMachine.can_transition(RunState.MODEL_STEP, RunState.POLICY_CHECK)
    assert RunStateMachine.can_transition(RunState.POLICY_CHECK, RunState.EXECUTING)
    assert RunStateMachine.can_transition(RunState.EXECUTING, RunState.VALIDATING)
    assert RunStateMachine.can_transition(RunState.VALIDATING, RunState.COMPLETED)
    assert RunStateMachine.can_transition(RunState.VALIDATING, RunState.REPLANNING)
    assert RunStateMachine.can_transition(RunState.POLICY_CHECK, RunState.BLOCKED)


# ---------------------------------------------------------------------------
# RunStateMachine — invalid transitions
# ---------------------------------------------------------------------------

def test_invalid_state_transitions():
    """Illegal transitions return False from can_transition."""
    assert not RunStateMachine.can_transition(RunState.QUEUED, RunState.COMPLETED)
    assert not RunStateMachine.can_transition(RunState.QUEUED, RunState.EXECUTING)
    assert not RunStateMachine.can_transition(RunState.ANALYZING, RunState.EXECUTING)
    assert not RunStateMachine.can_transition(RunState.COMPLETED, RunState.PLANNING)
    assert not RunStateMachine.can_transition(RunState.FAILED, RunState.QUEUED)


def test_validate_transition_raises_on_invalid():
    """validate_transition raises InvalidStateTransitionError for illegal moves."""
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        RunStateMachine.validate_transition(RunState.QUEUED, RunState.EXECUTING)
    assert "QUEUED" in str(exc_info.value)
    assert "EXECUTING" in str(exc_info.value)


def test_unexpected_state_transition_rejected():
    """Arbitrary state combinations that are not in the transition table are rejected."""
    with pytest.raises(InvalidStateTransitionError):
        RunStateMachine.validate_transition(RunState.VALIDATING, RunState.QUEUED)


# ---------------------------------------------------------------------------
# Terminal state protection
# ---------------------------------------------------------------------------

def test_terminal_states_cannot_transition():
    """No transition is allowed out of any terminal state."""
    terminal_states = [RunState.COMPLETED, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED]
    for term in terminal_states:
        for target in RunState:
            assert not RunStateMachine.can_transition(term, target), (
                f"Terminal state {term} must not transition to {target}"
            )


# ---------------------------------------------------------------------------
# Cancellation rules
# ---------------------------------------------------------------------------

def test_cancellation_allowed_from_active_states():
    """CANCELLED is reachable from non-terminal active states."""
    cancellable = [
        RunState.QUEUED,
        RunState.ANALYZING,
        RunState.SECURITY_REVIEW,
        RunState.AWAITING_APPROVAL,
        RunState.PLANNING,
        RunState.CONTEXT_BUILD,
        RunState.MODEL_STEP,
        RunState.POLICY_CHECK,
        RunState.EXECUTING,
        RunState.VALIDATING,
    ]
    for state in cancellable:
        assert RunStateMachine.can_transition(state, RunState.CANCELLED), (
            f"CANCELLED must be reachable from {state}"
        )


def test_cancellation_blocked_from_terminal_states():
    """Terminal states cannot be cancelled."""
    terminal = [RunState.COMPLETED, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED]
    for state in terminal:
        assert not RunStateMachine.can_transition(state, RunState.CANCELLED)


# ---------------------------------------------------------------------------
# InMemoryRunStore lifecycle
# ---------------------------------------------------------------------------

def _make_req(task: str = "Fix something meaningful") -> CreateRunRequest:
    return CreateRunRequest(
        repository=RepositoryTarget(source="workspace://test-repo"),
        task=task,
    )


def test_run_store_create_initial_state():
    """Created run starts in QUEUED."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    assert run.state == RunState.QUEUED


def test_run_store_valid_transition_sequence():
    """Full forward sequence of transitions succeeds."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    run = store.transition(run.run_id, RunState.ANALYZING)
    assert run.state == RunState.ANALYZING
    run = store.transition(run.run_id, RunState.SECURITY_REVIEW)
    assert run.state == RunState.SECURITY_REVIEW


def test_run_store_invalid_transition_raises():
    """Illegal transition raises InvalidStateTransitionError."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    with pytest.raises(InvalidStateTransitionError):
        store.transition(run.run_id, RunState.EXECUTING)


def test_run_store_policy_denial_blocked():
    """Security policy denial correctly transitions to BLOCKED."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    run = store.transition(run.run_id, RunState.ANALYZING)
    run = store.transition(run.run_id, RunState.SECURITY_REVIEW)
    run = store.transition(
        run.run_id,
        RunState.BLOCKED,
        {"error": "Access denied: Unauthorized credential access detected"},
    )
    assert run.state == RunState.BLOCKED
    assert "Access denied" in run.error


def test_run_store_cancel_from_queued():
    """A QUEUED run can be cancelled."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    run = store.cancel_run(run.run_id)
    assert run.state == RunState.CANCELLED


def test_run_store_cancel_terminal_raises():
    """Cancelling a terminal run raises InvalidStateTransitionError."""
    store = InMemoryRunStore()
    run = store.create_run(_make_req())
    run = store.transition(run.run_id, RunState.ANALYZING)
    run = store.transition(run.run_id, RunState.SECURITY_REVIEW)
    run = store.transition(run.run_id, RunState.BLOCKED)
    with pytest.raises(InvalidStateTransitionError):
        store.cancel_run(run.run_id)
