from packages.contracts.models import ToolRequest, RuntimeState, DecisionType
from packages.policy_engine.engine import PolicyEngine


def test_engine_evaluate_valid_repo_read(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    target = repo / "main.py"
    target.touch()

    engine = PolicyEngine()
    req = ToolRequest(
        run_id="run-1",
        request_id="req-1",
        tool="file_tool",
        capability="repo.read",
        arguments={"path": str(target)},
        target=str(target),
        reason="Read main entry file",
    )
    runtime = RuntimeState(repo_root=str(repo), temp_root=str(tmp_path / "temp"))

    decision = engine.evaluate(req, runtime_state=runtime)
    assert decision.decision == DecisionType.ALLOW
