from packages.policy_engine.evaluator import evaluate_policy
from packages.policy_engine.types import DecisionEnum

def test_sensitive_path_deny():
    res = evaluate_policy("repo.read", "~/.ssh/id_rsa")
    assert res.decision == DecisionEnum.DENY

def test_workspace_allow():
    res = evaluate_policy("repo.read", "/workspace/src/main.py")
    assert res.decision == DecisionEnum.ALLOW

def test_unknown_tool_deny():
    res = evaluate_policy("unknown.hack.tool", "/workspace")
    assert res.decision == DecisionEnum.DENY