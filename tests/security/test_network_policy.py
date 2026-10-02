from packages.contracts.models import ToolRequest, DecisionType, RiskLevel
from packages.policy_engine.engine import PolicyEngine


def test_network_fetch_unapproved_host_denied():
    engine = PolicyEngine()
    req = ToolRequest(
        run_id="r-net",
        request_id="req-net1",
        tool="network_tool",
        capability="network.fetch",
        arguments={"url": "https://unapproved-exfiltration-server.org/leak"},
        reason="Fetch external data",
    )

    dec = engine.evaluate(req)
    assert dec.decision == DecisionType.DENY
    assert dec.risk == RiskLevel.HIGH
