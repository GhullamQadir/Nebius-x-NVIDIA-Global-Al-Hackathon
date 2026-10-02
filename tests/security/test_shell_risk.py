from packages.contracts.models import ToolRequest, DecisionType, RiskLevel
from packages.policy_engine.engine import PolicyEngine


def test_destructive_shell_command_blocked():
    engine = PolicyEngine()
    req = ToolRequest(
        run_id="r-sh",
        request_id="req-sh1",
        tool="shell_tool",
        capability="shell.run",
        arguments={"command": "rm -rf /"},
        reason="Run destructive payload",
    )

    dec = engine.evaluate(req)
    assert dec.decision == DecisionType.DENY
    assert dec.risk == RiskLevel.CRITICAL
