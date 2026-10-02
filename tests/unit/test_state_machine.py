import pytest
from packages.contracts.run import RunState, CreateRunRequest, RepositoryTarget
from apps.orchestrator.state_machine import (
    RunStateMachine,
    InMemoryRunStore,
    InvalidStateTransitionError,
)


def test_valid_state_transitions():
    assert RunStateMachine.can_transition(RunState.QUEUED, RunState.ANALYZING)
    assert RunStateMachine.can_transition(RunState.ANALYZING, RunState.SECURITY_REVIEW)
    assert RunStateMachine.can_transition(RunState.SECURITY_REVIEW, RunState.PLANNING)
    assert RunStateMachine.can_transition(RunState.SECURITY_REVIEW, RunState.AWAITING_APPROVAL)
    assert RunStateMachine.can_transition(RunState.POLICY_CHECK, RunState.EXECUTING)
    assert RunStateMachine.can_transition(RunState.POLICY_CHECK, RunState.BLOCKED)
    assert RunStateMachine.can_transition(RunState.VALIDATING, RunState.COMPLETED)


def test_invalid_state_transitions():
    # Cannot jump directly from QUEUED to COMPLETED
    assert not RunStateMachine.can_transition(RunState.QUEUED, RunState.COMPLETED)
    # Cannot transition backwards from COMPLETED
    assert not RunStateMachine.can_transition(RunState.COMPLETED, RunState.PLANNING)
    
    with pytest.raises(InvalidStateTransitionError):
        RunStateMachine.validate_transition(RunState.QUEUED, RunState.EXECUTING)


def test_terminal_states_cannot_transition():
    terminal_states = [RunState.COMPLETED, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED]
    for term in terminal_states:
        for any_state in RunState:
            assert not RunStateMachine.can_transition(term, any_state)


def test_run_store_lifecycle_and_policy_denial():
    store = InMemoryRunStore()
    req = CreateRunRequest(
        repository=RepositoryTarget(source="workspace://repo"),
        task="Test run lifecycle",
    )
    run = store.create_run(req)
    assert run.state == RunState.QUEUED

    # Move to analyzing
    run = store.transition(run.run_id, RunState.ANALYZING)
    assert run.state == RunState.ANALYZING

    # Move to security review
    run = store.transition(run.run_id, RunState.SECURITY_REVIEW)
    assert run.state == RunState.SECURITY_REVIEW

    # Simulate security policy denial -> state moves to BLOCKED
    run = store.transition(run.run_id, RunState.BLOCKED, {"error": "Access denied: Unauthorized credential access detected"})
    assert run.state == RunState.BLOCKED
    assert "Access denied" in run.error
