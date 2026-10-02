from packages.contracts.models import ToolRequest, DecisionType
from packages.policy_engine.engine import PolicyEngine


def test_unregistered_capability_is_denied():
    engine = PolicyEngine()
    req = ToolRequest(
        run_id="r1",
        request_id="req1",
        tool="custom_tool",
        capability="arbitrary.capability.exec",
        arguments={},
        reason="Run unexpected capability",
    )
    dec = engine.evaluate(req)
    assert dec.decision == DecisionType.DENY
    assert "UNKNOWN_CAPABILITY_DENIED" in dec.reason_codes
