from packages.contracts.models import ToolRequest, DecisionType
from packages.policy_engine.engine import PolicyEngine


def test_malformed_and_unknown_tools_rejected():
    engine = PolicyEngine()

    req_empty = ToolRequest(
        run_id="",
        request_id="",
        tool="",
        capability="",
        arguments={},
        reason="Malformed request",
    )
    assert engine.evaluate(req_empty).decision == DecisionType.DENY

    req_unknown = ToolRequest(
        run_id="r1",
        request_id="req-unk",
        tool="unsupported_tool",
        capability="unsupported.tool.action",
        arguments={},
        reason="Unknown tool test",
    )
    assert engine.evaluate(req_unknown).decision == DecisionType.DENY
