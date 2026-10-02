from packages.contracts.models import ToolRequest, RuntimeState, DecisionType
from packages.policy_engine.engine import PolicyEngine


def test_path_traversal_attack_denied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    engine = PolicyEngine()
    traversal_path = str(repo) + "/../../../../etc/passwd"

    req = ToolRequest(
        run_id="r1",
        request_id="req3",
        tool="file_reader",
        capability="file.read",
        arguments={"path": traversal_path},
        target=traversal_path,
        reason="Path traversal attack",
    )
    runtime = RuntimeState(repo_root=str(repo), temp_root=str(tmp_path / "temp"))

    dec = engine.evaluate(req, runtime_state=runtime)
    assert dec.decision == DecisionType.DENY
