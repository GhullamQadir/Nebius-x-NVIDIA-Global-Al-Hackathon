import re
from packages.contracts.models import PolicyDecision, DecisionType, RiskLevel, ApprovalState
from .secrets import is_sensitive_path

SAFE_EXECTUABLES = {
    "ls": RiskLevel.LOW,
    "dir": RiskLevel.LOW,
    "cat": RiskLevel.LOW,
    "type": RiskLevel.LOW,
    "pwd": RiskLevel.LOW,
    "echo": RiskLevel.LOW,
    "pytest": RiskLevel.LOW,
    "python": RiskLevel.LOW,
    "node": RiskLevel.LOW,
    "git": RiskLevel.LOW,
}

MEDIUM_COMMANDS = [
    "pip install",
    "npm install",
    "yarn install",
    "docker build",
    "python -m pip",
]

CRITICAL_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"mkfs",
    r"dd\s+if=",
    r">\s*/dev/sd",
    r":\(\)\s*\{\s*:\|\:&\s*\};:",  # fork bomb
    r"chmod\s+-R\s+777\s+/",
    r"curl.*\|.*sh",
    r"wget.*\|.*sh",
]


def classify_command(command: str) -> RiskLevel:
    """
    Classifies command risk into LOW, MEDIUM, HIGH, or CRITICAL based on command structure and payload.
    """
    if not command:
        return RiskLevel.CRITICAL

    cmd_str = command.strip().lower()

    # Check Critical Patterns
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, cmd_str):
            return RiskLevel.CRITICAL

    # Check for secret path access inside command string
    if is_sensitive_path(cmd_str):
        return RiskLevel.CRITICAL

    # Check git push explicitly -> HIGH
    if "git push" in cmd_str:
        return RiskLevel.HIGH

    # Check medium risk commands
    for med in MEDIUM_COMMANDS:
        if cmd_str.startswith(med) or f" {med}" in cmd_str:
            return RiskLevel.MEDIUM

    # Check executable token
    tokens = cmd_str.split()
    first_token = tokens[0] if tokens else ""

    if first_token in SAFE_EXECTUABLES:
        # If shell command contains command chaining (; && || |), raise to HIGH/CRITICAL if suspicious
        if any(chain in cmd_str for chain in [";", "&&", "||", "|"]):
            # analyze chained parts
            subcommands = re.split(r";|&&|\|\||\|", cmd_str)
            sub_risks = [classify_command(sub.strip()) for sub in subcommands if sub.strip()]
            return max(sub_risks, key=lambda r: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(r.value))

        return SAFE_EXECTUABLES[first_token]

    return RiskLevel.HIGH


def evaluate_command(
    command: str,
    approval_state: ApprovalState = None,
    policy_version: str = "security-v0.1",
) -> PolicyDecision:
    """
    Evaluates shell command execution request against safety policies and approval requirements.
    """
    risk = classify_command(command)

    if risk == RiskLevel.CRITICAL:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason="Command exhibits critical security risk, credential harvesting, or destructive payload",
            policy_version=policy_version,
            reason_codes=("CRITICAL_COMMAND_DENIED",),
        )

    if risk == RiskLevel.HIGH:
        # High risk requires explicit approval
        if approval_state and approval_state.approved_requests.get(command, False):
            return PolicyDecision(
                decision=DecisionType.ALLOW,
                risk=RiskLevel.HIGH,
                reason="High-risk command explicitly approved by human reviewer",
                policy_version=policy_version,
                reason_codes=("HIGH_RISK_APPROVED",),
            )
        return PolicyDecision(
            decision=DecisionType.REQUIRE_APPROVAL,
            risk=RiskLevel.HIGH,
            reason="Command risk is HIGH; explicit human approval is required prior to execution",
            policy_version=policy_version,
            reason_codes=("HUMAN_APPROVAL_REQUIRED",),
        )

    if risk == RiskLevel.MEDIUM:
        return PolicyDecision(
            decision=DecisionType.ALLOW_WITH_MONITORING,
            risk=RiskLevel.MEDIUM,
            reason="Medium-risk package/build command allowed with execution monitoring",
            policy_version=policy_version,
            reason_codes=("MEDIUM_RISK_MONITORED",),
        )

    return PolicyDecision(
        decision=DecisionType.ALLOW,
        risk=RiskLevel.LOW,
        reason="Command is classified as safe/low-risk",
        policy_version=policy_version,
        reason_codes=("SAFE_COMMAND_ALLOWED",),
    )
