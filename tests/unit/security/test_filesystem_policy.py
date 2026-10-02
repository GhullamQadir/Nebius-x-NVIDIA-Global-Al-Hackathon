import os
from packages.contracts.models import DecisionType, RiskLevel
from packages.policy_engine.filesystem import evaluate_path


def test_repository_read_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "app.py"
    target.touch()

    decision = evaluate_path(str(target), repo_root=str(repo), temp_root=str(tmp_path / "temp"))
    assert decision.decision == DecisionType.ALLOW
    assert decision.risk == RiskLevel.LOW


def test_temp_directory_allowed(tmp_path):
    repo = tmp_path / "repo"
    temp = tmp_path / "temp"
    repo.mkdir()
    temp.mkdir()

    target = temp / "output.txt"
    target.touch()

    decision = evaluate_path(str(target), repo_root=str(repo), temp_root=str(temp))
    assert decision.decision == DecisionType.ALLOW


def test_home_directory_denied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = os.path.expanduser("~")

    decision = evaluate_path(home, repo_root=str(repo), temp_root=str(tmp_path / "temp"))
    assert decision.decision == DecisionType.DENY


def test_ssh_credentials_denied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ssh_key = os.path.join(os.path.expanduser("~"), ".ssh", "id_rsa")

    decision = evaluate_path(ssh_key, repo_root=str(repo), temp_root=str(tmp_path / "temp"))
    assert decision.decision == DecisionType.DENY
    assert decision.risk == RiskLevel.CRITICAL
    assert "CREDENTIAL_ACCESS" in decision.reason_codes
