from typing import Optional
from packages.contracts.models import ToolRequest, RuntimeState, ApprovalState, PolicyDecision
from .evaluator import evaluate_request
from .yaml_loader import load_profile_policy


class PolicyEngine:
    """
    Deterministic Policy Engine for the Secure Coding Agent.
    Enforces security boundaries, default-deny posture, credential protection, and human approval constraints.
    """

    def __init__(self, policy_dir: Optional[str] = None, profile_name: str = "sandboxed"):
        self.policy_dir = policy_dir
        self.profile_name = profile_name
        self.policy_version = "security-v0.1"
        self.loaded_policies = {}

        if policy_dir:
            self.loaded_policies = load_profile_policy(policy_dir, profile_name)

    def evaluate(
        self,
        request: ToolRequest,
        runtime_state: Optional[RuntimeState] = None,
        approval_state: Optional[ApprovalState] = None,
    ) -> PolicyDecision:
        """
        Evaluates incoming ToolRequest and returns a deterministic PolicyDecision.
        """
        return evaluate_request(
            request=request,
            runtime_state=runtime_state,
            approval_state=approval_state,
            policy_version=self.policy_version,
        )
