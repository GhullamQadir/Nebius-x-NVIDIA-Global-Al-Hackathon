"""
Nexora Policy Engine
Deterministic policy evaluation with fail-closed behavior
"""
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from nexora.backend.app.models import PolicyDecision as PolicyDecisionEnum
from nexora.backend.app.schemas import PolicyDecisionBase as PolicyDecisionSchema
from nexora.backend.config.settings import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


class Capability(str, Enum):
    """Defined capabilities that tools can require"""
    REPO_LIST = "repo.list"
    REPO_READ = "repo.read"
    REPO_WRITE = "repo.write"
    TEST_RUN = "test.run"
    GIT_STATUS = "git.status"
    GIT_DIFF = "git.diff"
    GIT_BRANCH = "git.branch"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"
    SHELL_RUN = "shell.run"
    NETWORK_FETCH = "network.fetch"
    WEB_SCRAPE = "web.scrape"


# The complete set of decisions this engine is allowed to emit. Anything that
# resolves outside this set is treated as an UNKNOWN decision and fails closed
# to DENY. Keeping this in one place makes the contract explicit and testable.
SUPPORTED_DECISIONS: Set[PolicyDecisionEnum] = {
    PolicyDecisionEnum.ALLOW,
    PolicyDecisionEnum.ALLOW_WITH_MONITORING,
    PolicyDecisionEnum.REQUIRE_APPROVAL,
    PolicyDecisionEnum.DENY,
    PolicyDecisionEnum.QUARANTINE,
}

# Approval states the caller may present to the engine. An unrecognised state
# is an unknown policy state and must not be treated as approval (fail closed).
# ``consumed`` marks an approval that has already been spent on one execution
# and therefore must never authorise a second one (replay protection).
KNOWN_APPROVAL_STATES: Set[str] = {
    "approved",
    "pending",
    "rejected",
    "expired",
    "consumed",
}


# Protected paths that can never be written
PROTECTED_PATHS: Set[str] = {
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "authorized_keys",
    "config/policies.yaml",
    "config/policies/*.yaml",
    "*.sql",
    "migrations/*",
}

# Protected commands that are always denied
DENIED_COMMANDS: Set[str] = {
    "rm -rf",
    "rm -rf /",
    "dd",
    "mkfs",
    "fdisk",
    "shutdown",
    "reboot",
    "curl",
    "wget",
    "nc",
    "netcat",
    "ssh",
    "scp",
    "rsync",
    "git push",
    "git push --force",
    "git push -f",
}

# Allowed commands (for demo profile)
ALLOWED_COMMANDS_DEMO: Set[str] = {
    "python",
    "python3",
    "pytest",
    "pip",
    "pip3",
    "cat",
    "ls",
    "find",
    "grep",
    "head",
    "tail",
    "wc",
    "diff",
    "patch",
    "git status",
    "git diff",
    "git log",
    "git branch",
    "git show",
}


@dataclass
class PolicyRule:
    """A single policy rule"""
    capability: Capability
    decision: PolicyDecisionEnum
    reason_codes: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyConfig:
    """Loaded policy configuration"""
    version: str
    rules: List[PolicyRule] = field(default_factory=list)
    default_decision: PolicyDecisionEnum = PolicyDecisionEnum.DENY
    protected_paths: Set[str] = field(default_factory=set)
    denied_commands: Set[str] = field(default_factory=set)
    allowed_commands: Set[str] = field(default_factory=set)
    approval_required_capabilities: Set[Capability] = field(default_factory=set)
    monitoring_capabilities: Set[Capability] = field(default_factory=set)


@dataclass(frozen=True)
class MonitoringLimits:
    """Predefined resource limits attached to an ALLOW_WITH_MONITORING action.

    These are trusted constants: they are never derived from model output or
    tool arguments. The orchestrator applies them to every monitored action.
    """
    max_timeout_seconds: int = 600
    max_output_bytes: int = 262144  # 256 KiB of captured stdout/stderr
    require_audit: bool = True


# Per-capability monitoring limits. Capabilities not listed fall back to
# ``DEFAULT_MONITORING_LIMITS``; monitoring never silently disables limits.
DEFAULT_MONITORING_LIMITS = MonitoringLimits()

MONITORING_LIMITS: Dict[Capability, MonitoringLimits] = {
    Capability.REPO_WRITE: MonitoringLimits(max_timeout_seconds=120, max_output_bytes=65536),
    Capability.TEST_RUN: MonitoringLimits(max_timeout_seconds=600, max_output_bytes=262144),
    Capability.WEB_SCRAPE: MonitoringLimits(max_timeout_seconds=30, max_output_bytes=65536),
}


class PolicyEngine:
    """
    Deterministic Policy Engine
    
    Evaluates tool requests against versioned policy rules.
    Fail-closed: unknown capabilities, malformed arguments, policy errors -> DENY
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self._engine_version = "1.0.0"
    
    def _load_config(self, config_path: Optional[str]) -> PolicyConfig:
        """Load policy configuration from YAML file"""
        if config_path is None:
            # policy.py lives in backend/app/core, policies.yaml in
            # backend/config -- two levels up, not one. The wrong depth
            # resolved to backend/app/config/policies.yaml, which does not
            # exist, so the FileNotFoundError fallback silently dropped every
            # rule and failed every capability closed on DEFAULT_DENY.
            config_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "config",
                "policies.yaml"
            )
        
        config = PolicyConfig(version="1.0.0")
        
        try:
            with open(config_path, "r", encoding="utf-8-sig") as f:
                data = yaml.safe_load(f) or {}
            
            config.version = data.get("version", "1.0.0")
            config.default_decision = PolicyDecisionEnum(data.get("default_decision", "DENY"))
            
            # Load protected paths
            config.protected_paths = set(PROTECTED_PATHS)
            config.protected_paths.update(data.get("protected_paths", []))
            
            # Load denied commands
            config.denied_commands = set(DENIED_COMMANDS)
            config.denied_commands.update(data.get("denied_commands", []))
            
            # Load allowed commands
            config.allowed_commands = set(ALLOWED_COMMANDS_DEMO)
            config.allowed_commands.update(data.get("allowed_commands", []))
            
            # Load approval-required capabilities
            config.approval_required_capabilities = {
                Capability(c) for c in data.get("approval_required_capabilities", [
                    "git.commit",
                    "git.push",
                    "shell.run",
                    "network.fetch",
                ])
            }
            
            # Load monitoring capabilities
            config.monitoring_capabilities = {
                Capability(c) for c in data.get("monitoring_capabilities", [
                    "repo.write",
                    "test.run",
                    "web.scrape",
                ])
            }
            
            # Load rules
            for rule_data in data.get("rules", []):
                try:
                    capability = Capability(rule_data["capability"])
                    decision = PolicyDecisionEnum(rule_data["decision"])
                    config.rules.append(PolicyRule(
                        capability=capability,
                        decision=decision,
                        reason_codes=rule_data.get("reason_codes", []),
                        conditions=rule_data.get("conditions", {}),
                    ))
                except (KeyError, ValueError) as e:
                    # Skip invalid rules but log in production
                    continue
                    
        except FileNotFoundError:
            # Use defaults if config file doesn't exist
            config.approval_required_capabilities = {
                Capability.GIT_COMMIT,
                Capability.GIT_PUSH,
                Capability.SHELL_RUN,
                Capability.NETWORK_FETCH,
            }
            config.monitoring_capabilities = {
                Capability.REPO_WRITE,
                Capability.TEST_RUN,
            }
        
        return config
    
    def evaluate(
        self,
        capability: Capability,
        normalized_arguments: Dict[str, Any],
        target_path: Optional[str] = None,
        risk_level: str = "medium",
        runtime_state: Optional[Dict[str, Any]] = None,
        approval_state: Optional[str] = None,
    ) -> PolicyDecisionSchema:
        """
        Evaluate a tool request against policy.

        This is the core security boundary - every tool request passes here.

        The method is fail-closed: any internal error, malformed input, or a
        decision outside :data:`SUPPORTED_DECISIONS` results in a DENY carrying
        an explicit reason code rather than an exception or a default allow.
        Callers therefore never need to wrap this in their own try/except and
        can treat the return value as the authoritative decision.
        """
        try:
            decision = self._evaluate(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                risk_level=risk_level,
                runtime_state=runtime_state,
                approval_state=approval_state,
            )
        except Exception as exc:  # noqa: BLE001 - the security boundary must not raise
            logger.warning("Policy engine evaluation failed; failing closed: %s", exc)
            return self._fail_closed(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                reason_codes=["POLICY_ENGINE_ERROR"],
            )

        # Defence in depth: never execute on a decision this engine did not
        # author. A malformed or unknown decision is treated as DENY.
        if not self._is_trusted_decision(decision):
            logger.warning("Policy engine produced an untrusted decision; failing closed")
            return self._fail_closed(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                reason_codes=["UNKNOWN_DECISION"],
            )

        return decision

    def _evaluate(
        self,
        capability: Capability,
        normalized_arguments: Dict[str, Any],
        target_path: Optional[str] = None,
        risk_level: str = "medium",
        runtime_state: Optional[Dict[str, Any]] = None,
        approval_state: Optional[str] = None,
    ) -> PolicyDecisionSchema:
        """Internal, unguarded evaluation. Only :meth:`evaluate` may call this."""
        # 0. Validate inputs before any rule is consulted.
        if normalized_arguments is None:
            normalized_arguments = {}
        if not isinstance(normalized_arguments, dict):
            return self._deny_by_contract(
                capability=capability,
                normalized_arguments=None,
                target_path=target_path,
                reason_codes=["MALFORMED_ARGUMENTS"],
            )
        if runtime_state is not None and not isinstance(runtime_state, dict):
            return self._deny_by_contract(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                reason_codes=["MALFORMED_RUNTIME_STATE"],
            )

        # Unknown approval state is an unknown policy state and must never be
        # interpreted as approval.
        if approval_state is not None and approval_state not in KNOWN_APPROVAL_STATES:
            return self._deny_by_contract(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                reason_codes=["UNKNOWN_APPROVAL_STATE"],
            )

        # 1. Validate capability is known
        try:
            capability_enum = Capability(capability) if isinstance(capability, str) else capability
        except ValueError:
            capability_enum = None
        if not isinstance(capability_enum, Capability):
            return self._deny_by_contract(
                capability=capability,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                reason_codes=["UNKNOWN_CAPABILITY"],
            )
        
        # 2. Check for protected path access
        if target_path and self._is_protected_path(target_path):
            return PolicyDecisionSchema(
                capability=capability_enum.value,
                decision=PolicyDecisionEnum.DENY,
                reason_codes=["PROTECTED_PATH_ACCESS"],
                risk_level="critical",
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                policy_version=self.config.version,
                engine_version=self._engine_version,
            )
        
        # 3. Check for denied commands
        if capability_enum == Capability.SHELL_RUN:
            command = normalized_arguments.get("command", "")
            if self._is_denied_command(command):
                return PolicyDecisionSchema(
                    capability=capability_enum.value,
                    decision=PolicyDecisionEnum.DENY,
                    reason_codes=["DENIED_COMMAND"],
                    risk_level="critical",
                    normalized_arguments=normalized_arguments,
                    target_path=target_path,
                    policy_version=self.config.version,
                    engine_version=self._engine_version,
                )
        
        # 4. Check explicit rules
        for rule in self.config.rules:
            if rule.capability == capability_enum:
                if self._match_conditions(rule.conditions, normalized_arguments, runtime_state, risk_level):
                    rule_decision = rule.decision
                    rule_reasons = list(rule.reason_codes or ["RULE_MATCH"])
                    # A verified "approved" state satisfies an explicit
                    # REQUIRE_APPROVAL rule. Every other state (pending,
                    # rejected, expired, consumed, or absent) keeps the action
                    # paused at REQUIRE_APPROVAL. DENY and QUARANTINE are
                    # terminal: an approval can never override them.
                    if (
                        rule_decision == PolicyDecisionEnum.REQUIRE_APPROVAL
                        and approval_state == "approved"
                    ):
                        rule_decision = PolicyDecisionEnum.ALLOW
                        rule_reasons = ["APPROVED"]
                    return PolicyDecisionSchema(
                        capability=capability_enum.value,
                        decision=rule_decision,
                        reason_codes=rule_reasons,
                        risk_level=risk_level,
                        normalized_arguments=normalized_arguments,
                        target_path=target_path,
                        policy_version=self.config.version,
                        engine_version=self._engine_version,
                    )
        
        # 5. Check if approval required. Only an explicit "approved" state (a
        # trusted value validated above) unlocks the action; every other state
        # remains REQUIRE_APPROVAL.
        if capability_enum in self.config.approval_required_capabilities:
            if approval_state == "approved":
                return PolicyDecisionSchema(
                    capability=capability_enum.value,
                    decision=PolicyDecisionEnum.ALLOW,
                    reason_codes=["APPROVED"],
                    risk_level=risk_level,
                    normalized_arguments=normalized_arguments,
                    target_path=target_path,
                    policy_version=self.config.version,
                    engine_version=self._engine_version,
                )
            return PolicyDecisionSchema(
                capability=capability_enum.value,
                decision=PolicyDecisionEnum.REQUIRE_APPROVAL,
                reason_codes=["REQUIRES_APPROVAL"],
                risk_level=risk_level,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                policy_version=self.config.version,
                engine_version=self._engine_version,
            )
        
        # 6. Check if monitoring required
        if capability_enum in self.config.monitoring_capabilities:
            return PolicyDecisionSchema(
                capability=capability_enum.value,
                decision=PolicyDecisionEnum.ALLOW_WITH_MONITORING,
                reason_codes=["MONITORED"],
                risk_level=risk_level,
                normalized_arguments=normalized_arguments,
                target_path=target_path,
                policy_version=self.config.version,
                engine_version=self._engine_version,
            )
        
        # 7. Default decision (fail closed). An unrecognised configured default
        # is coerced to DENY rather than emitted as-is.
        default_decision = self.config.default_decision
        if default_decision not in SUPPORTED_DECISIONS:
            default_decision = PolicyDecisionEnum.DENY
        return PolicyDecisionSchema(
            capability=capability_enum.value,
            decision=default_decision,
            reason_codes=["DEFAULT_DENY"],
            risk_level=risk_level,
            normalized_arguments=normalized_arguments,
            target_path=target_path,
            policy_version=self.config.version,
            engine_version=self._engine_version,
        )

    # ------------------------------------------------------------------
    # Fail-closed helpers and the monitoring contract
    # ------------------------------------------------------------------

    def _deny_by_contract(
        self,
        capability: Any,
        normalized_arguments: Optional[Dict[str, Any]],
        target_path: Any,
        reason_codes: List[str],
        risk_level: str = "critical",
    ) -> PolicyDecisionSchema:
        """Build a DENY decision using the shared policy-decision contract."""
        if isinstance(capability, Capability):
            capability_str = capability.value
        else:
            capability_str = str(capability)

        safe_arguments = normalized_arguments if isinstance(normalized_arguments, dict) else None
        safe_target = target_path if isinstance(target_path, str) else None

        return PolicyDecisionSchema(
            capability=capability_str,
            decision=PolicyDecisionEnum.DENY,
            reason_codes=list(reason_codes),
            risk_level=risk_level,
            normalized_arguments=safe_arguments,
            target_path=safe_target,
            policy_version=self.config.version,
            engine_version=self._engine_version,
        )

    def _fail_closed(
        self,
        capability: Any,
        normalized_arguments: Any,
        target_path: Any,
        reason_codes: List[str],
    ) -> PolicyDecisionSchema:
        """Convenience wrapper for the default fail-closed DENY."""
        return self._deny_by_contract(
            capability=capability,
            normalized_arguments=normalized_arguments,
            target_path=target_path,
            reason_codes=reason_codes,
        )

    @staticmethod
    def _is_trusted_decision(decision: Any) -> bool:
        """Return True only for a well-formed decision in SUPPORTED_DECISIONS."""
        if not isinstance(decision, PolicyDecisionSchema):
            return False
        raw = decision.decision
        try:
            if isinstance(raw, PolicyDecisionEnum):
                resolved = raw
            else:
                resolved = PolicyDecisionEnum(raw.value if isinstance(raw, Enum) else raw)
        except (ValueError, TypeError):
            return False
        return resolved in SUPPORTED_DECISIONS

    def monitoring_limits(self, capability: Any) -> MonitoringLimits:
        """Return the predefined monitoring limits for a capability.

        Unknown capabilities receive the conservative defaults rather than no
        limits at all, so ALLOW_WITH_MONITORING can never disable enforcement.
        """
        try:
            cap = Capability(capability) if isinstance(capability, str) else capability
        except ValueError:
            cap = None
        return MONITORING_LIMITS.get(cap, DEFAULT_MONITORING_LIMITS)

    def _is_protected_path(self, path: str) -> bool:
        """Check if path matches protected patterns"""
        path_obj = Path(path)
        for pattern in self.config.protected_paths:
            if path_obj.match(pattern) or path == pattern:
                return True
            # Check parent directories
            for parent in path_obj.parents:
                if parent.match(pattern) or str(parent) == pattern:
                    return True
        return False
    
    def _is_denied_command(self, command: str) -> bool:
        """Check if command matches denied patterns"""
        command_lower = command.lower().strip()
        for denied in self.config.denied_commands:
            if denied.lower() in command_lower:
                return True
        return False
    
    def _match_conditions(
        self,
        conditions: Dict[str, Any],
        arguments: Dict[str, Any],
        runtime_state: Optional[Dict[str, Any]],
        risk_level: str = "medium",
    ) -> bool:
        """Check whether a rule's conditions match.

        Only trusted values participate. ``risk_level`` is supplied by the
        caller (never read from model-controlled arguments), ``runtime_state``
        is populated by the orchestrator, and ``path_prefix`` is the tool's
        declared target. A condition key this engine does not understand never
        matches, so an unverifiable rule can never silently allow an action.
        """
        if not conditions:
            return True

        for key, expected in conditions.items():
            if key == "risk_level":
                # Trusted value: model output cannot set or override risk.
                if risk_level != expected:
                    return False
            elif key == "path_prefix":
                target = arguments.get("path", "")
                if not isinstance(target, str) or not target.startswith(str(expected)):
                    return False
            elif runtime_state is not None and key in runtime_state:
                if runtime_state[key] != expected:
                    return False
            else:
                # Unknown/underspecified condition -> cannot verify -> no match.
                return False
        return True


# Global policy engine instance
_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """Get or create the global policy engine instance"""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine
