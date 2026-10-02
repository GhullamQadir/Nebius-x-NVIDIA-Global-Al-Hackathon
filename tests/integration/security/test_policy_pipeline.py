from packages.contracts.models import ToolRequest, RuntimeState, DecisionType
from packages.policy_engine.engine import PolicyEngine


def simulate_execution_pipeline(request: ToolRequest, runtime: RuntimeState, engine: PolicyEngine):
    """
    Simulates Model -> Tool Request -> Tool Router -> Policy Engine -> Sandbox Execution Boundary.
    Returns True if execution proceeds, False if blocked/denied/approval required.
    """
    decision = engine.evaluate(request, runtime_state=runtime)
    if decision.decision in [DecisionType.ALLOW, DecisionType.ALLOW_WITH_MONITORING]:
        # Proceed to Sandbox Execution
        return True, decision
    else:
        # Stop / Block Execution
        return False, decision


def test_pipeline_allowed_repo_access(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target_file = repo / "main.py"
    target_file.touch()

    engine = PolicyEngine()
    runtime = RuntimeState(repo_root=str(repo), temp_root=str(tmp_path / "temp"))

    request = ToolRequest(
        run_id="run-pipeline-1",
        request_id="req-p1",
        tool="file_tool",
        capability="repo.read",
        arguments={"path": str(target_file)},
        target=str(target_file),
        reason="Read source code",
    )

    executed, decision = simulate_execution_pipeline(request, runtime, engine)
    assert executed is True
    assert decision.decision == DecisionType.ALLOW


def test_pipeline_denied_ssh_key_harvesting(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    engine = PolicyEngine()
    runtime = RuntimeState(repo_root=str(repo), temp_root=str(tmp_path / "temp"))

    request = ToolRequest(
        run_id="run-pipeline-2",
        request_id="req-p2",
        tool="shell_tool",
        capability="shell.run",
        arguments={"command": "cat ~/.ssh/id_rsa"},
        reason="Scrape SSH private key",
    )

    executed, decision = simulate_execution_pipeline(request, runtime, engine)
    assert executed is False
    assert decision.decision == DecisionType.DENY
    assert decision.risk.value == "CRITICAL"
