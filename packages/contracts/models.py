from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionType(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"
    QUARANTINE = "QUARANTINE"
    ALLOW_WITH_MONITORING = "ALLOW_WITH_MONITORING"


@dataclass(frozen=True)
class PolicyDecision:
    decision: DecisionType
    risk: RiskLevel
    reason: str
    policy_version: str
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    constraints: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolRequest:
    run_id: str
    request_id: str
    tool: str
    capability: str
    arguments: Dict[str, Any]
    target: Optional[str] = None
    reason: str = ""
    expected_impact: Optional[str] = None


@dataclass
class RuntimeState:
    repo_root: str
    temp_root: str
    active_profile: str = "sandboxed"
    environment_vars: Dict[str, str] = field(default_factory=dict)


@dataclass
class ApprovalState:
    approved_requests: Dict[str, bool] = field(default_factory=dict)
    human_in_loop: bool = True
