from packages.task_analyzer.analyzer import TaskAnalyzer


def test_task_analyzer_code_modification():
    analyzer = TaskAnalyzer()
    task = "Fix failing authentication check in src/auth.py and run pytest tests/test_auth.py"
    res = analyzer.analyze(task)

    assert res.objective == task
    assert "repo.read" in res.required_capabilities
    assert "repo.write" in res.required_capabilities
    assert "test.run" in res.required_capabilities
    assert any("test_auth.py" in t for t in res.acceptance_tests)


def test_task_analyzer_high_risk_flagging():
    analyzer = TaskAnalyzer()
    task = "Extract deploy token and password then push to remote git"
    res = analyzer.analyze(task)

    assert res.risk_class == "high"


def test_task_analyzer_read_only_low_risk():
    analyzer = TaskAnalyzer()
    task = "Inspect and describe repository directory layout"
    res = analyzer.analyze(task)

    assert res.risk_class == "low"
    assert "repo.write" not in res.required_capabilities
