from urllib.parse import urlparse
from packages.contracts.models import PolicyDecision, DecisionType, RiskLevel

APPROVED_DESTINATIONS = {
    "github.com",
    "api.github.com",
    "pypi.org",
    "files.pythonhosted.org",
    "npmjs.org",
    "registry.npmjs.org",
    "nebius.ai",
    "api.nebius.ai",
    "nvidia.com",
    "api.nvidia.com",
}


def evaluate_network_request(
    destination: str,
    method: str = "GET",
    direct_socket: bool = False,
    alternate_dns: bool = False,
    policy_version: str = "security-v0.1",
) -> PolicyDecision:
    """
    Evaluates egress network connection requests against default-deny network security rules.
    """
    if direct_socket:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason="Direct raw socket access is strictly prohibited",
            policy_version=policy_version,
            reason_codes=("DIRECT_SOCKET_DENIED",),
        )

    if alternate_dns:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.CRITICAL,
            reason="Alternate DNS resolution attempts are prohibited",
            policy_version=policy_version,
            reason_codes=("ALTERNATE_DNS_DENIED",),
        )

    if not destination:
        return PolicyDecision(
            decision=DecisionType.DENY,
            risk=RiskLevel.HIGH,
            reason="Network destination host is missing",
            policy_version=policy_version,
            reason_codes=("MISSING_DESTINATION",),
        )

    # Extract hostname
    host = destination.lower()
    if "://" in host:
        parsed = urlparse(host)
        host = parsed.hostname or host

    # Strip port if present
    if ":" in host:
        host = host.split(":")[0]

    # Check approved destination list
    if host in APPROVED_DESTINATIONS or any(host.endswith("." + app) for app in APPROVED_DESTINATIONS):
        return PolicyDecision(
            decision=DecisionType.ALLOW,
            risk=RiskLevel.LOW,
            reason=f"Network destination '{host}' is in approved egress allowlist",
            policy_version=policy_version,
            reason_codes=("APPROVED_NETWORK_DESTINATION",),
        )

    # Default Deny for unknown destination
    return PolicyDecision(
        decision=DecisionType.DENY,
        risk=RiskLevel.HIGH,
        reason=f"Network destination '{host}' is not in approved egress allowlist (Default Deny)",
        policy_version=policy_version,
        reason_codes=("UNAPPROVED_NETWORK_DESTINATION", "DEFAULT_DENY"),
    )
