"""
Nexora Security Gateway
Content provenance labeling, injection detection, risk assessment
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from nexora.backend.app.models import SecurityDecision as SecurityDecisionEnum
from nexora.backend.app.models import RiskClass
from nexora.backend.app.schemas import SecurityDecision as SecurityDecisionSchema


class Provenance(str, Enum):
    """Content provenance labels"""
    TASK = "task"
    REPOSITORY = "repository"
    TOOL_OUTPUT = "tool_output"
    MODEL_OUTPUT = "model_output"
    SYSTEM = "system"


class TrustLevel(str, Enum):
    """Trust levels for content"""
    TRUSTED = "trusted"      # System-generated, policy config
    VERIFIED = "verified"    # Verified by deterministic checks
    UNTRUSTED = "untrusted"  # User input, repository content, model output


@dataclass
class ContentBlock:
    """A block of content with provenance and trust metadata"""
    content: str
    provenance: Provenance
    trust_level: TrustLevel
    source_ref: Optional[str] = None  # file path, tool name, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InjectionFinding:
    """Result of injection detection"""
    detector: str
    matched_pattern: str
    location: str  # e.g., "README.md:42"
    severity: str  # low, medium, high
    disposition: str = "flagged_as_data"  # flagged_as_data, blocked, quarantined


@dataclass
class SecurityDecisionResult:
    """Complete security decision"""
    decision: SecurityDecisionEnum
    reason_codes: List[str]
    provenance_summary: Dict[str, int]
    injection_findings: List[InjectionFinding]
    risk_level: RiskClass
    gateway_version: str = "1.0.0"


# Injection detection patterns (heuristic, advisory only)
INJECTION_PATTERNS = [
    # Direct instruction patterns
    (r"ignore\s+(?:previous|above|all)\s+instructions?", "instruction_override"),
    (r"disregard\s+(?:previous|above|all)\s+(?:instructions?|prompts?)", "instruction_override"),
    (r"forget\s+(?:previous|above|all)\s+(?:instructions?|prompts?)", "instruction_override"),
    (r"you\s+are\s+now\s+(?:a|an)\s+\w+", "role_injection"),
    (r"act\s+as\s+(?:a|an)\s+\w+", "role_injection"),
    (r"pretend\s+to\s+be\s+(?:a|an)\s+\w+", "role_injection"),
    (r"system\s*:\s*", "system_prompt_injection"),
    (r"user\s*:\s*", "user_prompt_injection"),
    (r"assistant\s*:\s*", "assistant_prompt_injection"),
    # Secret exfiltration attempts
    (r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*\S+", "secret_pattern"),
    (r"BEGIN\s+(?:RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY", "private_key"),
    # Command injection
    (r"\$\s*\(\s*\w+", "command_substitution"),
    (r"`\s*\w+\s*`", "backtick_substitution"),
    (r";\s*(?:rm|cat|wget|curl|nc|ssh)\b", "command_chaining"),
    # Data exfiltration
    (r"send\s+(?:to|data\s+to)\s+\S+", "exfiltration"),
    (r"upload\s+(?:to|data\s+to)\s+\S+", "exfiltration"),
    (r"post\s+(?:to|data\s+to)\s+\S+", "exfiltration"),
    # Policy bypass
    (r"safe\s*=\s*true", "policy_bypass"),
    (r"approved\s*=\s*true", "policy_bypass"),
    (r"bypass\s+(?:policy|security|check)", "policy_bypass"),
]


class SecurityGateway:
    """
    Security Gateway - analyzes content for risk before it enters the model context.
    
    Labels provenance, runs injection heuristics (advisory), assesses risk,
    and issues an explicit SecurityDecision with reasons.
    """
    
    def __init__(self):
        self.gateway_version = "1.0.0"
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance"""
        self._injection_regexes = [
            (re.compile(pattern, re.IGNORECASE | re.MULTILINE), name)
            for pattern, name in INJECTION_PATTERNS
        ]
    
    def analyze(
        self,
        task_text: str,
        repository_files: Dict[str, str],
        tool_outputs: Optional[List[Dict[str, Any]]] = None,
        model_outputs: Optional[List[str]] = None,
    ) -> SecurityDecisionResult:
        """
        Perform complete security analysis.
        
        Args:
            task_text: User-provided task description
            repository_files: Dict of file_path -> content
            tool_outputs: Previous tool execution outputs
            model_outputs: Previous model outputs
            
        Returns:
            SecurityDecisionResult with decision, reasons, and findings
        """
        # Collect all content blocks with provenance
        blocks: List[ContentBlock] = []
        
        # Task content (user input - untrusted)
        blocks.append(ContentBlock(
            content=task_text,
            provenance=Provenance.TASK,
            trust_level=TrustLevel.UNTRUSTED,
            source_ref="user_task",
        ))
        
        # Repository files (untrusted - may contain injection)
        for path, content in repository_files.items():
            blocks.append(ContentBlock(
                content=content,
                provenance=Provenance.REPOSITORY,
                trust_level=TrustLevel.UNTRUSTED,
                source_ref=path,
            ))
        
        # Tool outputs (untrusted - model could have influenced)
        if tool_outputs:
            for output in tool_outputs:
                blocks.append(ContentBlock(
                    content=str(output.get("content", "")),
                    provenance=Provenance.TOOL_OUTPUT,
                    trust_level=TrustLevel.UNTRUSTED,
                    source_ref=output.get("tool", "unknown"),
                ))
        
        # Model outputs (untrusted)
        if model_outputs:
            for i, output in enumerate(model_outputs):
                blocks.append(ContentBlock(
                    content=output,
                    provenance=Provenance.MODEL_OUTPUT,
                    trust_level=TrustLevel.UNTRUSTED,
                    source_ref=f"model_step_{i}",
                ))
        
        # Run injection detection
        injection_findings = self._detect_injections(blocks)
        
        # Build provenance summary
        provenance_summary = self._build_provenance_summary(blocks)
        
        # Assess risk level
        risk_level = self._assess_risk(blocks, injection_findings)
        
        # Make security decision
        decision, reason_codes = self._make_decision(
            blocks, injection_findings, risk_level
        )
        
        return SecurityDecisionResult(
            decision=decision,
            reason_codes=reason_codes,
            provenance_summary=provenance_summary,
            injection_findings=injection_findings,
            risk_level=risk_level,
            gateway_version=self.gateway_version,
        )
    
    def _detect_injections(self, blocks: List[ContentBlock]) -> List[InjectionFinding]:
        """Run injection detection heuristics on content blocks"""
        findings: List[InjectionFinding] = []
        
        for block in blocks:
            if block.trust_level == TrustLevel.TRUSTED:
                continue  # Skip trusted content
            
            for regex, detector_name in self._injection_regexes:
                for match in regex.finditer(block.content):
                    # Get line number for location
                    line_no = block.content[:match.start()].count('\n') + 1
                    location = f"{block.source_ref}:{line_no}" if block.source_ref else f"line_{line_no}"
                    
                    findings.append(InjectionFinding(
                        detector=detector_name,
                        matched_pattern=match.group()[:100],  # Truncate long matches
                        location=location,
                        severity=self._severity_for_detector(detector_name),
                        disposition="flagged_as_data",  # Always advisory
                    ))
        
        return findings
    
    def _severity_for_detector(self, detector: str) -> str:
        """Map detector to severity"""
        high_severity = {"private_key", "secret_pattern", "command_substitution", "backtick_substitution"}
        medium_severity = {"instruction_override", "role_injection", "system_prompt_injection", "policy_bypass"}
        
        if detector in high_severity:
            return "high"
        elif detector in medium_severity:
            return "medium"
        return "low"
    
    def _build_provenance_summary(self, blocks: List[ContentBlock]) -> Dict[str, int]:
        """Count blocks by provenance"""
        summary = {p.value: 0 for p in Provenance}
        for block in blocks:
            summary[block.provenance.value] += 1
        return summary
    
    def _assess_risk(
        self,
        blocks: List[ContentBlock],
        injection_findings: List[InjectionFinding],
    ) -> RiskClass:
        """Assess overall risk level"""
        # High severity injection findings -> high risk
        high_findings = [f for f in injection_findings if f.severity == "high"]
        if high_findings:
            return RiskClass.HIGH
        
        # Medium severity findings -> medium risk
        medium_findings = [f for f in injection_findings if f.severity == "medium"]
        if medium_findings:
            return RiskClass.MEDIUM
        
        # Check for suspicious repository content
        repo_blocks = [b for b in blocks if b.provenance == Provenance.REPOSITORY]
        for block in repo_blocks:
            # Large files with lots of text could hide injection
            if len(block.content) > 50000:
                return RiskClass.MEDIUM
            
            # Files with many injection-like patterns
            pattern_count = sum(
                1 for regex, _ in self._injection_regexes
                if regex.search(block.content)
            )
            if pattern_count > 5:
                return RiskClass.MEDIUM
        
        return RiskClass.LOW
    
    def _make_decision(
        self,
        blocks: List[ContentBlock],
        injection_findings: List[InjectionFinding],
        risk_level: RiskClass,
    ) -> tuple[SecurityDecisionEnum, List[str]]:
        """Make the final security decision"""
        reason_codes: List[str] = []
        
        # High risk -> block
        if risk_level == RiskClass.HIGH:
            reason_codes.append("HIGH_RISK_CONTENT")
            return SecurityDecisionEnum.BLOCKED, reason_codes
        
        # Medium risk with injection findings -> needs approval
        if risk_level == RiskClass.MEDIUM and injection_findings:
            reason_codes.append("INJECTION_DETECTED")
            reason_codes.append("MEDIUM_RISK")
            return SecurityDecisionEnum.NEEDS_APPROVAL, reason_codes
        
        # Low risk -> allowed
        reason_codes.append("LOW_RISK")
        return SecurityDecisionEnum.ALLOWED, reason_codes
    
    def to_schema(self, result: SecurityDecisionResult) -> SecurityDecisionSchema:
        """Convert internal result to API schema"""
        return SecurityDecisionSchema(
            decision=result.decision,
            reason_codes=result.reason_codes,
            provenance_summary=result.provenance_summary,
            injection_findings=[
                {
                    "detector": f.detector,
                    "matched_pattern": f.matched_pattern,
                    "location": f.location,
                    "severity": f.severity,
                    "disposition": f.disposition,
                }
                for f in result.injection_findings
            ],
            risk_level=result.risk_level.value,
            gateway_version=result.gateway_version,
        )


# Global instance
_security_gateway: Optional[SecurityGateway] = None


def get_security_gateway() -> SecurityGateway:
    """Get or create the global security gateway instance"""
    global _security_gateway
    if _security_gateway is None:
        _security_gateway = SecurityGateway()
    return _security_gateway
