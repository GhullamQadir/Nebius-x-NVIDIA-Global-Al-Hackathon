from packages.contracts.models import PolicyDecision, DecisionType, RiskLevel, ApprovalState

ALLOWED_GIT_ACTIONS = {"status", "diff", "branch", "log", "show"}
APPROVAL_REQUIRED_GIT_ACTIONS = {"commit", "push"}


def evaluate_git_action(
    action: str,
    approval_state: ApprovalState = None,
    policy_version: str = "security-v0.1",
) -> PolicyDecision:
    """
    Evaluates requested Git operation against security policies.
    Enforces strict rule that 'git.push' is NEVER automatic and requires explicit human approval.
    """
    if not action:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.HIGH,
            reason="Missing Git action parameter",
            policy_version=policy_version,
            reason_codes=("MISSING_GIT_ACTION",),
        )

    clean_action = action.lower().replace("git.", "").strip()

    if clean_action in ALLOWED_GIT_ACTIONS:
        return PolicyDecision(
            decision=DecisionType.ALLOW,
            risk=RiskLevel.LOW,
            reason=f"Git inspection action '{clean_action}' is permitted",
            policy_version=policy_version,
            reason_codes=("GIT_INSPECTION_ALLOWED",),
        )

    if clean_action == "commit":
        return PolicyDecision(
            decision=DecisionType.REQUIRE_APPROVAL,
            risk=RiskLevel.MEDIUM,
            reason="Git commit changes state and requires policy review or approval",
            policy_version=policy_version,
            reason_codes=("GIT_COMMIT_REVIEW_REQUIRED",),
        )

    if clean_action == "push":
        # Check human approval state
        if approval_state and approval_state.approved_requests.get("git.push", False):
            return PolicyDecision(
                decision=DecisionType.ALLOW,
                risk=RiskLevel.HIGH,
                reason="Git push explicitly approved by human reviewer",
                policy_version=policy_version,
                reason_codes=("GIT_PUSH_APPROVED",),
            )

        return PolicyDecision(
            decision=DecisionType.REQUIRE_APPROVAL,
            risk=RiskLevel.HIGH,
            reason="Git push is NEVER automatic and requires explicit human approval",
            policy_version=policy_version,
            reason_codes=("GIT_PUSH_NEVER_AUTOMATIC", "HUMAN_APPROVAL_REQUIRED"),
            constraints=("HUMAN_IN_THE_LOOP_REQUIRED",),
        )

    if clean_action in ["remote_add", "remote_remove", "remote_change", "config_override"]:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason=f"Git operation '{clean_action}' modifies remote governance and is prohibited",
            policy_version=policy_version,
            reason_codes=("GIT_GOVERNANCE_VIOLATION",),
        )

    # Unknown git action default deny
    return PolicyDecision(
        decision=DecisionType.DENY,
        risk=RiskLevel.HIGH,
        reason=f"Unknown or unapproved Git action '{clean_action}'",
        policy_version=policy_version,
        reason_codes=("UNKNOWN_GIT_ACTION", "DEFAULT_DENY"),
    )
