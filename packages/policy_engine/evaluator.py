from packages.contracts.models import (
    ToolRequest,
    RuntimeState,
    ApprovalState,
    PolicyDecision,
    DecisionType,
    RiskLevel,
)
from .filesystem import evaluate_path
from .commands import evaluate_command
from .git import evaluate_git_action
from .network import evaluate_network_request
from .secrets import evaluate_secret_access

KNOWN_CAPABILITIES = {
    "repo.read",
    "repo.write",
    "repo.list",
    "file.read",
    "file.write",
    "file.delete",
    "shell.run",
    "git.status",
    "git.diff",
    "git.branch",
    "git.log",
    "git.commit",
    "git.push",
    "network.fetch",
}


def evaluate_request(
    request: ToolRequest,
    runtime_state: RuntimeState = None,
    approval_state: ApprovalState = None,
    policy_version: str = "security-v0.1",
) -> PolicyDecision:
    """
    Main Policy Evaluator algorithm enforcing Default Deny security architecture:
    Model -> Tool Request -> Policy Engine -> Decision (ALLOW, REQUIRE_APPROVAL, DENY, QUARANTINE).
    """
    if not request or not request.tool or not request.capability:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason="Malformed or empty tool request rejected before policy evaluation",
            policy_version=policy_version,
            reason_codes=("MALFORMED_REQUEST", "DEFAULT_DENY"),
        )

    capability = request.capability.lower()

    # Rule 1: Unknown capability -> DENY
    if capability not in KNOWN_CAPABILITIES:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.HIGH,
            reason=f"Unknown or unregistered capability '{request.capability}' is prohibited",
            policy_version=policy_version,
            reason_codes=("UNKNOWN_CAPABILITY_DENIED", "DEFAULT_DENY"),
        )

    # Extract target and roots from runtime state
    repo_root = runtime_state.repo_root if runtime_state else ""
    temp_root = runtime_state.temp_root if runtime_state else ""
    target_path = request.target or request.arguments.get("path") or request.arguments.get("target") or ""

    # Rule 2: Filesystem / Repo Capabilities
    if capability in {"repo.read", "repo.write", "repo.list", "file.read", "file.write", "file.delete"}:
        return evaluate_path(
            path=target_path,
            repo_root=repo_root,
            temp_root=temp_root,
            policy_version=policy_version,
        )

    # Rule 3: Shell Execution Capability
    if capability == "shell.run":
        cmd = request.arguments.get("command") or target_path
        return evaluate_command(
            command=cmd,
            approval_state=approval_state,
            policy_version=policy_version,
        )

    # Rule 4: Git Capabilities
    if capability.startswith("git."):
        return evaluate_git_action(
            action=capability,
            approval_state=approval_state,
            policy_version=policy_version,
        )

    # Rule 5: Network Egress Capability
    if capability == "network.fetch":
        dest = request.arguments.get("url") or request.arguments.get("destination") or target_path
        return evaluate_network_request(
            destination=dest,
            direct_socket=request.arguments.get("direct_socket", False),
            alternate_dns=request.arguments.get("alternate_dns", False),
            policy_version=policy_version,
        )

    # Fallback Default Deny
    return PolicyDecision(
        decision=DecisionType.DENY,
        risk=RiskLevel.HIGH,
        reason="No matching explicit allow policy found (Default Deny)",
        policy_version=policy_version,
        reason_codes=("DEFAULT_DENY",),
    )
