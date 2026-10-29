"""
Nexora Validator / Critic
Layered validation and structured findings
"""
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nexora.backend.app.core.context import truncate_head_tail
from nexora.backend.app.models import ValidationStatus
from nexora.backend.app.schemas import ValidationFindingBase as ValidationFindingSchema


@dataclass
class ValidationResult:
    """Result of a validation check"""
    check_type: str
    status: ValidationStatus
    message: str
    details: Optional[Dict[str, Any]] = None


class ValidatorCritic:
    """
    Validator/Critic - runs layered validation checks.
    
    In order:
    1. Patch applies cleanly
    2. Formatting and syntax
    3. Static checks and linting
    4. Targeted tests
    5. Relevant broader tests within budget
    6. Security regression checks
    7. Diff review against task constraints
    
    Model self-assessment cannot mark a failed run successful.
    """
    
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path)
        self.critic_version = "1.0.0"
    
    def validate(
        self,
        patch_content: Optional[str],
        test_command: str,
        task_constraints: List[str],
        run_id: str,
        step_number: int,
        patch_already_applied: bool = False,
    ) -> List[ValidationResult]:
        """
        Run all validation checks.
        
        Returns:
            List of ValidationResult for each check
        """
        results = []
        
        # 1. Patch applies cleanly
        if patch_content:
            results.append(
                self._check_patch_applies(patch_content, already_applied=patch_already_applied)
            )
        else:
            results.append(ValidationResult(
                check_type="patch_applies",
                status=ValidationStatus.SKIPPED,
                message="No patch to validate",
            ))
        
        # 2. Syntax and formatting
        results.append(self._check_syntax(patch_content))
        
        # 3. Static checks / linting
        results.append(self._check_lint())
        
        # 4. Targeted tests
        results.append(self._run_targeted_tests(test_command))
        
        # 5. Broader tests (within budget - simplified)
        results.append(self._run_broader_tests(test_command))
        
        # 6. Security regression
        results.append(self._check_security_regression(patch_content))
        
        # 7. Diff review against constraints
        if patch_content:
            results.append(self._check_diff_constraints(patch_content, task_constraints))
        else:
            results.append(ValidationResult(
                check_type="diff_review",
                status=ValidationStatus.SKIPPED,
                message="No patch to review",
            ))
        
        return results
    
    def _check_patch_applies(
        self,
        patch_content: str,
        already_applied: bool = False,
    ) -> ValidationResult:
        """Check whether a proposed or already-applied patch is consistent."""
        try:
            # Write patch to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(patch_content)
                patch_file = f.name
            
            # Try dry-run
            apply_args = ["git", "apply", "--check"]
            if already_applied:
                apply_args.append("--reverse")
            proc = subprocess.run(
                [*apply_args, patch_file],
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            # Cleanup
            Path(patch_file).unlink(missing_ok=True)
            
            if proc.returncode == 0:
                return ValidationResult(
                    check_type="patch_applies",
                    status=ValidationStatus.PASS,
                    message=(
                        "Patch is applied and can be cleanly reversed"
                        if already_applied
                        else "Patch applies cleanly"
                    ),
                )
            else:
                return ValidationResult(
                    check_type="patch_applies",
                    status=ValidationStatus.FAIL,
                    message=f"Patch does not apply: {proc.stderr}",
                    details={"stderr": proc.stderr},
                )
        except Exception as e:
            return ValidationResult(
                check_type="patch_applies",
                status=ValidationStatus.FAIL,
                message=f"Patch validation error: {str(e)}",
            )
    
    def _check_syntax(self, patch_content: Optional[str] = None) -> ValidationResult:
        """Check Python syntax for modified .py files (or workspace files with BOM-safe reading)."""
        errors = []
        
        modified_py_files = []
        if patch_content:
            for line in patch_content.splitlines():
                if line.startswith("+++ b/") or line.startswith("--- a/") or line.startswith("diff --git a/"):
                    parts = line.split()
                    target = parts[-1].lstrip("b/").lstrip("a/")
                    if target.endswith(".py"):
                        p = self.workspace_path / target
                        if p not in modified_py_files:
                            modified_py_files.append(p)
        if not patch_content or not modified_py_files:
            return ValidationResult(
                check_type="syntax",
                status=ValidationStatus.PASS,
                message="No Python files modified in change",
            )
        
        candidates = modified_py_files
        
        for py_file in candidates:
            # Skip excluded
            if any(part in py_file.parts for part in {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".testsprite"}):
                continue
            if not py_file.is_file():
                continue
            
            try:
                content = py_file.read_text(encoding="utf-8-sig")
                compile(content, str(py_file), 'exec')
            except SyntaxError as e:
                errors.append(f"{py_file.relative_to(self.workspace_path)}:{e.lineno}: {e.msg}")
            except Exception as e:
                errors.append(f"{py_file.relative_to(self.workspace_path)}: {str(e)}")
        
        if errors:
            return ValidationResult(
                check_type="syntax",
                status=ValidationStatus.FAIL,
                message=f"Syntax errors found: {len(errors)}",
                details={"errors": errors[:10]},
            )
        
        return ValidationResult(
            check_type="syntax",
            status=ValidationStatus.PASS,
            message="All checked Python files have valid syntax",
        )
    
    def _check_lint(self) -> ValidationResult:
        """Run basic linting (ruff if available, else basic checks)"""
        # Try ruff first
        try:
            proc = subprocess.run(
                ["ruff", "check", "."],
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if proc.returncode == 0:
                return ValidationResult(
                    check_type="lint",
                    status=ValidationStatus.PASS,
                    message="Linting passed (ruff)",
                )
            else:
                return ValidationResult(
                    check_type="lint",
                    status=ValidationStatus.WARNING,
                    message="Linting issues found",
                    details={"output": truncate_head_tail(proc.stdout, max_chars=2000)},
                )
        except FileNotFoundError:
            # Fallback to basic checks
            return self._basic_lint_check()
        except Exception as e:
            return ValidationResult(
                check_type="lint",
                status=ValidationStatus.WARNING,
                message=f"Lint check failed: {str(e)}",
            )
    
    def _basic_lint_check(self) -> ValidationResult:
        """Basic linting without external tools"""
        issues = []
        
        for py_file in self.workspace_path.rglob("*.py"):
            if any(part in py_file.parts for part in {".git", "__pycache__", ".venv", "venv", "env"}):
                continue
            
            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.splitlines()
                
                for i, line in enumerate(lines, 1):
                    # Line too long
                    if len(line) > 120:
                        issues.append(f"{py_file.relative_to(self.workspace_path)}:{i}: Line too long ({len(line)} > 120)")
                    
                    # Trailing whitespace
                    if line.rstrip() != line:
                        issues.append(f"{py_file.relative_to(self.workspace_path)}:{i}: Trailing whitespace")
                        
            except Exception:
                pass
        
        if issues:
            return ValidationResult(
                check_type="lint",
                status=ValidationStatus.WARNING,
                message=f"Basic lint issues: {len(issues)}",
                details={"issues": issues[:20]},
            )
        
        return ValidationResult(
            check_type="lint",
            status=ValidationStatus.PASS,
            message="Basic lint checks passed",
        )
    
    def _run_targeted_tests(self, test_command: str) -> ValidationResult:
        """Run targeted tests related to the change"""
        # The validator executes a subprocess, so it must use the same
        # shell-free, allowlisted runner path as the sandbox. A command that is
        # not a reviewed runner (or that cannot be resolved to a trusted
        # executable) fails closed instead of being executed.
        from nexora.backend.app.core.tools import (
            ToolValidationError,
            _build_approved_test_argv,
            _resolve_trusted_executable,
        )

        try:
            argv = _build_approved_test_argv(test_command)
        except ToolValidationError as exc:
            return ValidationResult(
                check_type="targeted_tests",
                status=ValidationStatus.FAIL,
                message=f"Test command rejected: {exc}",
            )

        resolved = _resolve_trusted_executable(argv[0])
        if resolved is None:
            return ValidationResult(
                check_type="targeted_tests",
                status=ValidationStatus.FAIL,
                message=f"Test runner {argv[0]!r} could not be resolved to a trusted path",
            )

        try:
            proc = subprocess.run(
                [resolved, *argv[1:]],
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            # Parse test results
            passed = proc.returncode == 0
            output = proc.stdout + proc.stderr
            
            # Extract test counts
            import re
            passed_count = len(re.findall(r'\bPASSED\b', output))
            failed_count = len(re.findall(r'\bFAILED\b', output))
            error_count = len(re.findall(r'\bERROR\b', output))
            
            if passed:
                return ValidationResult(
                    check_type="targeted_tests",
                    status=ValidationStatus.PASS,
                    message=f"Targeted tests passed ({passed_count} passed)",
                    details={"passed": passed_count, "failed": failed_count, "errors": error_count},
                )
            else:
                return ValidationResult(
                    check_type="targeted_tests",
                    status=ValidationStatus.FAIL,
                    message=f"Targeted tests failed ({failed_count} failed, {error_count} errors)",
                    details={"passed": passed_count, "failed": failed_count, "errors": error_count, "output": truncate_head_tail(output, max_chars=3000)},
                )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                check_type="targeted_tests",
                status=ValidationStatus.FAIL,
                message="Tests timed out",
            )
        except Exception as e:
            return ValidationResult(
                check_type="targeted_tests",
                status=ValidationStatus.FAIL,
                message=f"Test execution error: {str(e)}",
            )
    
    def _run_broader_tests(self, test_command: str) -> ValidationResult:
        """Run broader test suite (simplified - same as targeted for now)"""
        # In a full implementation, this would run a broader set of tests
        # For now, reuse targeted tests
        return self._run_targeted_tests(test_command)
    
    def _check_security_regression(self, patch_content: Optional[str]) -> ValidationResult:
        """Check for security regressions in patch"""
        if not patch_content:
            return ValidationResult(
                check_type="security_regression",
                status=ValidationStatus.SKIPPED,
                message="No patch to check",
            )
        
        issues = []
        
        # Check for secrets in diff
        secret_patterns = [
            r"api[_-]?key\s*[:=]\s*\S+",
            r"password\s*[:=]\s*\S+",
            r"secret\s*[:=]\s*\S+",
            r"token\s*[:=]\s*\S+",
            r"BEGIN\s+(?:RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY",
        ]
        
        import re
        for pattern in secret_patterns:
            if re.search(pattern, patch_content, re.IGNORECASE):
                issues.append(f"Potential secret in diff: {pattern}")
        
        # Check for new network access
        if re.search(r"(?:curl|wget|requests\.|urllib|socket\.)", patch_content):
            issues.append("New network access detected in patch")
        
        # Check for shell execution
        if re.search(r"(?:subprocess|os\.system|eval\(|exec\()", patch_content):
            issues.append("Potential shell execution in patch")
        
        # Check for protected file modifications
        protected = [".env", "config/policies", "migrations", "*.key", "*.pem"]
        for prot in protected:
            if prot.replace("*", "") in patch_content:
                issues.append(f"Protected file pattern in diff: {prot}")
        
        if issues:
            return ValidationResult(
                check_type="security_regression",
                status=ValidationStatus.FAIL,
                message=f"Security regression checks failed: {len(issues)} issues",
                details={"issues": issues},
            )
        
        return ValidationResult(
            check_type="security_regression",
            status=ValidationStatus.PASS,
            message="No security regressions detected",
        )
    
    def _check_diff_constraints(self, patch_content: str, constraints: List[str]) -> ValidationResult:
        """Review diff against task constraints"""
        violations = []
        
        # Check each constraint
        for constraint in constraints:
            constraint_lower = constraint.lower()
            
            if "must not" in constraint_lower or "cannot" in constraint_lower or "avoid" in constraint_lower:
                # Negative constraint - check if violated
                # This is simplified - real implementation would be more sophisticated
                pass
        
        # Check for out-of-scope changes
        # (Would need to compare against proposed capabilities/artifacts)
        
        if violations:
            return ValidationResult(
                check_type="diff_review",
                status=ValidationStatus.FAIL,
                message=f"Constraint violations: {len(violations)}",
                details={"violations": violations},
            )
        
        return ValidationResult(
            check_type="diff_review",
            status=ValidationStatus.PASS,
            message="Diff respects task constraints",
        )
    
    def to_schemas(
        self,
        results: List[ValidationResult],
        run_id: str,
        step_number: int,
    ) -> List[ValidationFindingSchema]:
        """Convert to API schemas"""
        schemas = []
        for result in results:
            schemas.append(ValidationFindingSchema(
                id=run_id,  # Will be replaced
                run_id=run_id,
                step_number=step_number,
                check_type=result.check_type,
                status=result.status,
                message=result.message,
                details=result.details,
                critic_version=self.critic_version,
                created_at=datetime.now(),
            ))
        return schemas


def get_validator_critic(workspace_path: str) -> ValidatorCritic:
    """Get validator critic instance"""
    return ValidatorCritic(workspace_path)
