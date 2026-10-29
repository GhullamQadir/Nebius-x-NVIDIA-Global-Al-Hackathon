"""
Nexora Task Analyzer
Normalizes natural language tasks into structured analysis
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from nexora.backend.app.models import RiskClass
from nexora.backend.app.schemas import TaskAnalysisBase as TaskAnalysisSchema
from nexora.backend.app.schemas import RiskClass
from nexora.backend.app.core.policy import Capability


class TaskType(str, Enum):
    """Types of coding tasks"""
    BUG_FIX = "bug_fix"
    ADD_FUNCTION = "add_function"
    ADD_TEST = "add_test"
    REFACTOR = "refactor"
    FIX_TEST = "fix_test"
    DEPENDENCY_UPDATE = "dependency_update"
    MODIFY_ENDPOINT = "modify_endpoint"
    DEBUG_RUNTIME = "debug_runtime"


@dataclass
class TaskAnalysisResult:
    """Structured task analysis output"""
    objective: str
    constraints: List[str]
    acceptance_tests: List[str]
    risk_class: RiskClass
    likely_artifacts: List[str]
    proposed_capabilities: List[Capability]
    task_type: TaskType
    analyzer_version: str = "1.0.0"


class TaskAnalyzer:
    """
    Task Analyzer - converts natural language task into structured analysis.
    
    Output has no authority - it only proposes capabilities and structure.
    Security Gateway and Policy Engine make actual decisions.
    """
    
    def __init__(self):
        self.analyzer_version = "1.0.0"
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for task classification"""
        self._task_type_patterns = {
            TaskType.BUG_FIX: [
                r"\b(fix|resolve|repair|correct)\b.*\b(bug|issue|error|problem|defect)\b",
                r"\b(bug|issue|error|problem)\b.*\b(fix|resolve|repair)\b",
            ],
            TaskType.ADD_FUNCTION: [
                r"\b(add|implement|create|write)\b.*\b(function|method|feature)\b",
                r"\bnew\b.*\b(function|method|feature)\b",
            ],
            TaskType.ADD_TEST: [
                r"\b(add|write|create)\b.*\b(test|unit test|integration test)\b",
                r"\btest\b.*\b(coverage|missing|add)\b",
            ],
            TaskType.REFACTOR: [
                r"\b(refactor|restructure|reorganize|clean up)\b",
                r"\b(improve|optimize)\b.*\b(code|structure|design)\b",
            ],
            TaskType.FIX_TEST: [
                r"\b(fix|resolve)\b.*\b(test|failing test|broken test)\b",
                r"\btest\b.*\b(fail|broken|error)\b",
            ],
            TaskType.DEPENDENCY_UPDATE: [
                r"\b(update|upgrade|bump)\b.*\b(dependenc|package|library)\b",
            ],
            TaskType.MODIFY_ENDPOINT: [
                r"\b(modify|change|update)\b.*\b(endpoint|api|route)\b",
            ],
            TaskType.DEBUG_RUNTIME: [
                r"\b(debug|investigate|trace)\b.*\b(runtime|error|crash|exception)\b",
            ],
        }
        
        self._capability_keywords = {
            Capability.REPO_LIST: ["list", "explore", "find files", "directory", "structure"],
            Capability.REPO_READ: ["read", "view", "examine", "look at", "see", "inspect"],
            Capability.REPO_WRITE: ["write", "create", "modify", "edit", "change", "update", "fix", "implement"],
            Capability.TEST_RUN: ["test", "run test", "pytest", "verify", "validate"],
            Capability.GIT_STATUS: ["git status", "changes", "modified"],
            Capability.GIT_DIFF: ["diff", "difference", "changes"],
            Capability.GIT_BRANCH: ["branch", "checkout"],
        }
        
        self._risk_keywords = {
            RiskClass.CRITICAL: ["delete", "remove", "drop", "destroy", "production", "database", "schema"],
            RiskClass.HIGH: ["security", "auth", "password", "secret", "key", "token", "credential", "permission"],
            RiskClass.MEDIUM: ["refactor", "restructure", "modify", "change", "update", "migration"],
            RiskClass.LOW: ["add", "create", "implement", "test", "read", "view", "list"],
        }
    
    def analyze(
        self,
        task_text: str,
        repository_structure: Optional[Dict[str, Any]] = None,
    ) -> TaskAnalysisResult:
        """
        Analyze a natural language task.
        
        Args:
            task_text: User's task description
            repository_structure: Optional repository file structure for context
            
        Returns:
            TaskAnalysisResult with structured analysis
        """
        # Normalize task text
        normalized = task_text.strip()
        
        # Extract objective (first sentence or first 200 chars)
        objective = self._extract_objective(normalized)
        
        # Classify task type
        task_type = self._classify_task_type(normalized)
        
        # Extract constraints
        constraints = self._extract_constraints(normalized)
        
        # Generate acceptance tests
        acceptance_tests = self._generate_acceptance_tests(normalized, task_type)
        
        # Assess risk class
        risk_class = self._assess_risk(normalized)
        
        # Determine likely artifacts
        likely_artifacts = self._determine_artifacts(normalized, task_type, repository_structure)
        
        # Propose capabilities (not granted!)
        proposed_capabilities = self._propose_capabilities(normalized, task_type)
        
        return TaskAnalysisResult(
            objective=objective,
            constraints=constraints,
            acceptance_tests=acceptance_tests,
            risk_class=risk_class,
            likely_artifacts=likely_artifacts,
            proposed_capabilities=proposed_capabilities,
            task_type=task_type,
            analyzer_version=self.analyzer_version,
        )
    
    def _extract_objective(self, text: str) -> str:
        """Extract the main objective from task text"""
        # Split into sentences
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if sentences:
            # Return first sentence, truncated if too long
            obj = sentences[0]
            return obj[:500] + ("..." if len(obj) > 500 else "")
        
        return text[:500] + ("..." if len(text) > 500 else "")
    
    def _classify_task_type(self, text: str) -> TaskType:
        """Classify the task type based on keywords"""
        text_lower = text.lower()
        
        scores: Dict[TaskType, int] = {t: 0 for t in TaskType}
        
        for task_type, patterns in self._task_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    scores[task_type] += 1
        
        # Return highest scoring type, default to BUG_FIX
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        
        return TaskType.BUG_FIX
    
    def _extract_constraints(self, text: str) -> List[str]:
        """Extract explicit constraints from task text"""
        constraints = []
        text_lower = text.lower()
        
        # Look for constraint patterns
        constraint_patterns = [
            (r"\b(must|must not|should|should not|cannot|can't)\b\s+(.+?)(?:\.|$)", "explicit"),
            (r"\b(without|avoid|don't|do not)\b\s+(.+?)(?:\.|$)", "negative"),
            (r"\b(only|exclusively|specifically)\b\s+(.+?)(?:\.|$)", "restrictive"),
            (r"\b(within|under|less than|at most)\b\s+(.+?)(?:\.|$)", "budget"),
        ]
        
        for pattern, ctype in constraint_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                constraint_text = match[1] if isinstance(match, tuple) else match
                constraints.append(f"[{ctype}] {constraint_text.strip()}")
        
        # Add implicit constraints based on task type
        if "test" in text_lower:
            constraints.append("[implicit] Must not break existing tests")
        if "fix" in text_lower or "bug" in text_lower:
            constraints.append("[implicit] Fix must address root cause")
        
        return constraints[:10]  # Limit to 10 constraints
    
    def _generate_acceptance_tests(
        self,
        text: str,
        task_type: TaskType,
    ) -> List[str]:
        """Generate acceptance test criteria"""
        tests = []
        text_lower = text.lower()
        
        # Base tests based on task type
        if task_type == TaskType.BUG_FIX:
            tests.extend([
                "Original bug is fixed (reproduction case passes)",
                "No regression in existing functionality",
                "Code passes existing test suite",
            ])
        elif task_type == TaskType.ADD_FUNCTION:
            tests.extend([
                "New function works as specified",
                "Function has appropriate tests",
                "Code follows project style",
            ])
        elif task_type == TaskType.ADD_TEST:
            tests.extend([
                "New test covers the specified behavior",
                "Test passes with correct implementation",
                "Test follows project test patterns",
            ])
        elif task_type == TaskType.FIX_TEST:
            tests.extend([
                "Previously failing test now passes",
                "Fix doesn't change test intent",
                "No other tests broken",
            ])
        elif task_type == TaskType.REFACTOR:
            tests.extend([
                "All existing tests pass",
                "Behavior unchanged (verified by tests)",
                "Code quality improved",
            ])
        else:
            tests.extend([
                "Task objective achieved",
                "Existing tests pass",
            ])
        
        # Add specific tests from text
        if "empty" in text_lower and "input" in text_lower:
            tests.append("Empty input handled gracefully")
        if "validation" in text_lower:
            tests.append("Input validation works correctly")
        if "error" in text_lower or "exception" in text_lower:
            tests.append("Error handling works as expected")
        
        return tests[:8]  # Limit to 8 acceptance tests
    
    def _assess_risk(self, text: str) -> RiskClass:
        """Assess risk class based on keywords"""
        text_lower = text.lower()
        
        for risk_class, keywords in self._risk_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return risk_class
        
        return RiskClass.LOW
    
    def _determine_artifacts(
        self,
        text: str,
        task_type: TaskType,
        repository_structure: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Determine likely files/symbols to modify"""
        artifacts = []
        text_lower = text.lower()
        
        # Extract file mentions
        file_pattern = r'[\w/]+\.py\b'
        files = re.findall(file_pattern, text)
        artifacts.extend(files[:5])
        
        # Extract function/class mentions
        func_pattern = r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\)'
        funcs = re.findall(func_pattern, text)
        artifacts.extend([f"{f}()" for f in funcs[:5]])
        
        class_pattern = r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)'
        classes = re.findall(class_pattern, text)
        artifacts.extend([f"class {c}" for c in classes[:3]])
        
        # Add type-based defaults
        if task_type == TaskType.BUG_FIX:
            artifacts.append("test file for the bug")
        elif task_type == TaskType.ADD_TEST:
            artifacts.append("test file")
        elif task_type == TaskType.REFACTOR:
            artifacts.append("source files in affected module")
        
        # Deduplicate and limit
        seen: Set[str] = set()
        unique = []
        for a in artifacts:
            if a not in seen:
                seen.add(a)
                unique.append(a)
        
        return unique[:10]
    
    def _propose_capabilities(
        self,
        text: str,
        task_type: TaskType,
    ) -> List[Capability]:
        """Propose capabilities needed (not granted!)"""
        proposed: Set[Capability] = set()
        text_lower = text.lower()
        
        # Always need to read repo
        proposed.add(Capability.REPO_READ)
        proposed.add(Capability.REPO_LIST)
        
        # Keyword-based capability detection
        for capability, keywords in self._capability_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    proposed.add(capability)
                    break
        
        # Task-type defaults
        if task_type in (TaskType.BUG_FIX, TaskType.ADD_FUNCTION, TaskType.REFACTOR, TaskType.FIX_TEST):
            proposed.add(Capability.REPO_WRITE)
            proposed.add(Capability.TEST_RUN)
        
        if task_type == TaskType.ADD_TEST:
            proposed.add(Capability.REPO_WRITE)
            proposed.add(Capability.TEST_RUN)
        
        # Git capabilities only if explicitly mentioned
        if any(kw in text_lower for kw in ["commit", "branch", "git"]):
            proposed.add(Capability.GIT_STATUS)
            proposed.add(Capability.GIT_DIFF)
            proposed.add(Capability.GIT_BRANCH)
        
        return list(proposed)
    
    def to_schema(self, result: TaskAnalysisResult, run_id: str) -> TaskAnalysisSchema:
        """Convert to API schema"""
        return TaskAnalysisSchema(
            id=run_id,  # Will be replaced with actual UUID
            run_id=run_id,
            objective=result.objective,
            constraints=result.constraints,
            acceptance_tests=result.acceptance_tests,
            risk_class=result.risk_class,
            likely_artifacts=result.likely_artifacts,
            proposed_capabilities=[c.value for c in result.proposed_capabilities],
            analyzer_version=result.analyzer_version,
            created_at=datetime.now(),
        )


# Global instance
_task_analyzer: Optional[TaskAnalyzer] = None


def get_task_analyzer() -> TaskAnalyzer:
    """Get or create the global task analyzer instance"""
    global _task_analyzer
    if _task_analyzer is None:
        _task_analyzer = TaskAnalyzer()
    return _task_analyzer
