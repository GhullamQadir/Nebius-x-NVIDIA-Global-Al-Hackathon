import os
import pathlib
from packages.contracts.models import PolicyDecision, DecisionType, RiskLevel
from .normalization import normalize_path, is_within
from .secrets import evaluate_secret_access, is_sensitive_path


def evaluate_path(
    path: str,
    repo_root: str,
    temp_root: str,
    policy_version: str = "security-v0.1",
) -> PolicyDecision:
    """
    Evaluates requested target path against default-deny filesystem policy boundaries:
    - Secret & credential access -> DENY (CRITICAL)
    - Path outside allowed roots -> DENY
    - Target repository -> ALLOW
    - Task temp directory -> ALLOW
    """
    if not path:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.HIGH,
            reason="Filesystem target path is empty or missing",
            policy_version=policy_version,
            reason_codes=("MISSING_TARGET",),
        )

    # Secret check first
    secret_decision = evaluate_secret_access(path, policy_version=policy_version)
    if secret_decision.decision == DecisionType.DENY:
        return secret_decision

    canonical_target = normalize_path(path)
    canonical_repo = normalize_path(repo_root) if repo_root else ""
    canonical_temp = normalize_path(temp_root) if temp_root else ""
    canonical_home = normalize_path(os.path.expanduser("~"))

    # System directory check (/etc, /proc, /sys, /dev, C:\Windows)
    lower_target = canonical_target.lower()
    system_prefixes = ["/etc", "/proc", "/sys", "/dev", "c:\\windows", "c:\\program files"]
    for sys_pref in system_prefixes:
        if lower_target.startswith(sys_pref):
            return PolicyDecision(
                decision=DecisionType.DENY,
                risk=RiskLevel.CRITICAL,
                reason="Access to host system directories is prohibited",
                policy_version=policy_version,
                reason_codes=("SYSTEM_ACCESS",),
            )

    # Target Repository Check
    if canonical_repo and is_within(canonical_target, canonical_repo):
        return PolicyDecision(
            decision=DecisionType.ALLOW,
            risk=RiskLevel.LOW,
            reason="Target path is inside approved repository boundary",
            policy_version=policy_version,
            reason_codes=("TARGET_REPOSITORY_ALLOWED",),
        )

    # Task Temp Directory Check
    if canonical_temp and is_within(canonical_target, canonical_temp):
        return PolicyDecision(
            decision=DecisionType.ALLOW,
            risk=RiskLevel.LOW,
            reason="Target path is inside approved temporary workspace boundary",
            policy_version=policy_version,
            reason_codes=("TASK_TEMP_ALLOWED",),
        )

    # Check if target is inside user home directory outside allowed workspace
    if is_within(canonical_target, canonical_home):
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.HIGH,
            reason="Access to host home directory outside workspace is prohibited",
            policy_version=policy_version,
            reason_codes=("HOST_HOME_ACCESS",),
        )

    # Default Deny for any unapproved path
    return PolicyDecision(
        decision=DecisionType.DENY,
        risk=RiskLevel.HIGH,
        reason="Target path is outside allowed workspace boundaries (Default Deny)",
        policy_version=policy_version,
        reason_codes=("UNAPPROVED_FILESYSTEM_TARGET", "DEFAULT_DENY"),
    )
