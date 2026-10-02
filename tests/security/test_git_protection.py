from packages.contracts.models import ToolRequest, DecisionType, RiskLevel
from packages.policy_engine.engine import PolicyEngine


def test_git_push_is_never_automatic():
    engine = PolicyEngine()
    req = ToolRequest(
        run_id="r-git",
        request_id="req-push",
        tool="git_tool",
        capability="git.push",
        arguments={},
        reason="Push changes to remote",
    )

    dec = engine.evaluate(req)
    assert dec.decision == DecisionType.REQUIRE_APPROVAL
    assert dec.risk == RiskLevel.HIGH
    assert "GIT_PUSH_NEVER_AUTOMATIC" in dec.reason_codes
