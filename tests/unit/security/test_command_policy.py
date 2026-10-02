from packages.contracts.models import DecisionType, RiskLevel, ApprovalState
from packages.policy_engine.commands import classify_command, evaluate_command


def test_classify_safe_command():
    assert classify_command("pytest") == RiskLevel.LOW
    assert classify_command("git status") == RiskLevel.LOW


def test_classify_medium_command():
    assert classify_command("pip install requests") == RiskLevel.MEDIUM


def test_classify_high_command():
    assert classify_command("git push origin main") == RiskLevel.HIGH


def test_classify_critical_command():
    assert classify_command("rm -rf /") == RiskLevel.CRITICAL
    assert classify_command("cat ~/.ssh/id_rsa") == RiskLevel.CRITICAL


def test_evaluate_safe_command():
    decision = evaluate_command("pytest")
    assert decision.decision == DecisionType.ALLOW


def test_evaluate_unapproved_git_push():
    decision = evaluate_command("git push origin main")
    assert decision.decision == DecisionType.REQUIRE_APPROVAL
    assert decision.risk == RiskLevel.HIGH


def test_evaluate_approved_git_push():
    approval = ApprovalState(approved_requests={"git push origin main": True})
    decision = evaluate_command("git push origin main", approval_state=approval)
    assert decision.decision == DecisionType.ALLOW
