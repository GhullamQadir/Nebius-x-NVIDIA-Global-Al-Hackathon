from packages.contracts.models import DecisionType, RiskLevel
from packages.policy_engine.network import evaluate_network_request


def test_approved_destination():
    dec = evaluate_network_request("github.com")
    assert dec.decision == DecisionType.ALLOW
    assert dec.risk == RiskLevel.LOW


def test_unapproved_destination_denied():
    dec = evaluate_network_request("malicious-exfiltration-server.com")
    assert dec.decision == DecisionType.DENY
    assert dec.risk == RiskLevel.HIGH


def test_direct_socket_denied():
    dec = evaluate_network_request("github.com", direct_socket=True)
    assert dec.decision == DecisionType.DENY
    assert dec.risk == RiskLevel.CRITICAL
