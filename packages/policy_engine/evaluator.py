import os
from typing import Optional
from .types import PolicyDecision, DecisionEnum, RiskLevel

SENSITIVE_PATTERNS = ["~/.ssh", "~/.aws", ".env", "id_rsa", "/etc/passwd"]

def evaluate_policy(capability: str, target_path: str, command: Optional[str] = None) -> PolicyDecision:
    abs_path = os.path.abspath(target_path)
    
    # 1. Deny Sensitive Paths
    for sensitive in SENSITIVE_PATTERNS:
        if sensitive in target_path or sensitive in abs_path:
            return PolicyDecision(
                decision=DecisionEnum.DENY,
                risk=RiskLevel.CRITICAL,
                reason_codes=["SENSITIVE_PATH_DENIED"],
                message=f"Access to sensitive path '{target_path}' is strictly denied."
            )
            
    # 2. Command Checks
    if command:
        if "rm -rf /" in command or "shutdown" in command:
            return PolicyDecision(
                decision=DecisionEnum.QUARANTINE,
                risk=RiskLevel.CRITICAL,
                reason_codes=["DANGEROUS_COMMAND_BLOCKED"],
                message="Critical dangerous command detected."
            )
        if "git push" in command:
            return PolicyDecision(
                decision=DecisionEnum.REQUIRE_APPROVAL,
                risk=RiskLevel.HIGH,
                reason_codes=["GIT_PUSH_NEEDS_APPROVAL"],
                message="Git push requires explicit human approval."
            )

    # 3. Allowed Workspace Tools
    if capability in ["repo.read", "repo.write", "repo.list", "test.run"]:
        return PolicyDecision(
            decision=DecisionEnum.ALLOW,
            risk=RiskLevel.LOW,
            reason_codes=["APPROVED_WORKSPACE_TOOL"],
            message="Action allowed within workspace."
        )

    # 4. Fallback Default Deny
    return PolicyDecision(
        decision=DecisionEnum.DENY,
        risk=RiskLevel.MEDIUM,
        reason_codes=["DEFAULT_DENY"],
        message="Capability or action not explicitly allowed."
    )