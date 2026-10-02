import os
from packages.contracts.models import ToolRequest, RuntimeState, DecisionType, RiskLevel
from packages.policy_engine.engine import PolicyEngine


def test_ssh_credentials_access_denied(tmp_path):
    engine = PolicyEngine()
    ssh_path = os.path.join(os.path.expanduser("~"), ".ssh", "id_rsa")

    req = ToolRequest(
        run_id="r1",
        request_id="req2",
        tool="file_reader",
        capability="file.read",
        arguments={"path": ssh_path},
        target=ssh_path,
        reason="Access SSH private key",
    )
    runtime = RuntimeState(repo_root=str(tmp_path / "repo"), temp_root=str(tmp_path / "temp"))

    dec = engine.evaluate(req, runtime_state=runtime)
    assert dec.decision == DecisionType.DENY
    assert dec.risk == RiskLevel.CRITICAL
    assert "CREDENTIAL_ACCESS" in dec.reason_codes
