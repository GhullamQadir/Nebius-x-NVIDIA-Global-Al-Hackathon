from enum import Enum
from pydantic import BaseModel
from typing import List, Optional

class DecisionEnum(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    QUARANTINE = "QUARANTINE"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class PolicyDecision(BaseModel):
    decision: DecisionEnum
    policy_version: str = "v1-mvp"
    risk: RiskLevel
    reason_codes: List[str]
    message: str