from packages.contracts.models import DecisionType, RiskLevel, ApprovalState
from packages.policy_engine.git import evaluate_git_action


def test_git_inspection_actions_allowed():
    for act in ["git.status", "git.diff", "git.branch", "git.log"]:
        dec = evaluate_git_action(act)
        assert dec.decision == DecisionType.ALLOW


def test_git_commit_requires_approval():
    dec = evaluate_git_action("git.commit")
    assert dec.decision == DecisionType.REQUIRE_APPROVAL


def test_git_push_never_automatic():
    dec = evaluate_git_action("git.push")
    assert dec.decision == DecisionType.REQUIRE_APPROVAL
    assert dec.risk == RiskLevel.HIGH
    assert "GIT_PUSH_NEVER_AUTOMATIC" in dec.reason_codes


def test_git_push_with_explicit_approval():
    app = ApprovalState(approved_requests={"git.push": True})
    dec = evaluate_git_action("git.push", approval_state=app)
    assert dec.decision == DecisionType.ALLOW
