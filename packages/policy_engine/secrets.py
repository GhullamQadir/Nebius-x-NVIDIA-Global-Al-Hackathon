import os
import pathlib
from packages.contracts.models import PolicyDecision, DecisionType, RiskLevel
from .normalization import normalize_path

SENSITIVE_PATTERNS = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".azure",
    ".gcp",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "credentials",
    "shadow",
    "passwd",
    "secret",
    "private.pem",
    "service_account.json",
]


def is_sensitive_path(path: str) -> bool:
    """
    Determines if a target path accesses sensitive system files, keys, or credentials.
    """
    if not path:
        return False

    norm_p = normalize_path(path).lower()
    path_obj = pathlib.Path(norm_p)

    # Check path parts
    for part in path_obj.parts:
        if part.lower() in SENSITIVE_PATTERNS:
            return True

    # Check filename string match
    filename = path_obj.name.lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in filename:
            return True

    # Check home directory secret locations
    home = pathlib.Path(os.path.expanduser("~")).resolve()
    try:
        rel = path_obj.relative_to(home)
        first_part = rel.parts[0].lower() if rel.parts else ""
        if first_part in [".ssh", ".aws", ".gnupg", ".azure", ".gcp"]:
            return True
    except ValueError:
        pass

    return False


def evaluate_secret_access(path: str, policy_version: str = "security-v0.1") -> PolicyDecision:
    """
    Evaluates secret access attempts and returns a CRITICAL DENY decision if target is sensitive.
    """
    if is_sensitive_path(path):
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason="Access to sensitive credentials or secrets is strictly prohibited",
            policy_version=policy_version,
            reason_codes=("CREDENTIAL_ACCESS", "SECRET_PROTECTION"),
        )

    return PolicyDecision(
        decision=DecisionType.ALLOW,
        risk=RiskLevel.LOW,
        reason="No secret path detected",
        policy_version=policy_version,
    )
