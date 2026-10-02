from packages.policy_engine.secret_protection import redact_secrets

def test_secret_redaction():
    raw_log = "Error connecting with api_key: 'sk-1234567890abcdef1234567890abcdef'"
    clean_log = redact_secrets(raw_log)
    assert "sk-1234567890abcdef" not in clean_log
    assert "[REDACTED]" in clean_log