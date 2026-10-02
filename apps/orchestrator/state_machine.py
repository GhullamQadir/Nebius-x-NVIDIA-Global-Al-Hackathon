import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, List, Set, Any
import threading

from packages.contracts.run import (
    RunState,
    CreateRunRequest,
    RunResponse,
    RepositoryTarget,
    TaskBudgets,
)
from packages.task_analyzer.analyzer import TaskAnalyzer


class InvalidStateTransitionError(Exception):
    def __init__(self, current_state: RunState, target_state: RunState):
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(f"Cannot transition from {current_state.value} to {target_state.value}")


class RunStateMachine:
    """
    Enforces the 11-stage autonomous agent execution lifecycle.
    Terminal states cannot be transitioned out of.
    """

    ALLOWED_TRANSITIONS: Dict[RunState, Set[RunState]] = {
        RunState.QUEUED: {RunState.ANALYZING, RunState.CANCELLED},
        RunState.ANALYZING: {RunState.SECURITY_REVIEW, RunState.BLOCKED, RunState.CANCELLED},
        RunState.SECURITY_REVIEW: {
            RunState.PLANNING,
            RunState.AWAITING_APPROVAL,
            RunState.BLOCKED,
            RunState.CANCELLED,
        },
        RunState.AWAITING_APPROVAL: {RunState.PLANNING, RunState.BLOCKED, RunState.CANCELLED},
        RunState.PLANNING: {RunState.CONTEXT_BUILD, RunState.FAILED, RunState.CANCELLED},
        RunState.CONTEXT_BUILD: {RunState.MODEL_STEP, RunState.FAILED, RunState.CANCELLED},
        RunState.MODEL_STEP: {RunState.POLICY_CHECK, RunState.FAILED, RunState.CANCELLED},
        RunState.POLICY_CHECK: {
            RunState.EXECUTING,
            RunState.AWAITING_APPROVAL,
            RunState.BLOCKED,
            RunState.CANCELLED,
            RunState.FAILED,
        },
        RunState.EXECUTING: {RunState.VALIDATING, RunState.FAILED, RunState.CANCELLED},
        RunState.VALIDATING: {
            RunState.COMPLETED,
            RunState.REPLANNING,
            RunState.FAILED,
            RunState.CANCELLED,
        },
        RunState.REPLANNING: {RunState.PLANNING, RunState.CONTEXT_BUILD, RunState.FAILED, RunState.CANCELLED},
        # Terminal states have no transitions out
        RunState.COMPLETED: set(),
        RunState.FAILED: set(),
        RunState.BLOCKED: set(),
        RunState.CANCELLED: set(),
    }

    @classmethod
    def can_transition(cls, current: RunState, target: RunState) -> bool:
        return target in cls.ALLOWED_TRANSITIONS.get(current, set())

    @classmethod
    def validate_transition(cls, current: RunState, target: RunState) -> None:
        if not cls.can_transition(current, target):
            raise InvalidStateTransitionError(current, target)


class InMemoryRunStore:
    """
    Thread-safe in-memory store for agent runs during Day 2 development.
    """

    def __init__(self):
        self._runs: Dict[str, RunResponse] = {}
        self._lock = threading.Lock()
        self._analyzer = TaskAnalyzer()

    def create_run(self, req: CreateRunRequest) -> RunResponse:
        with self._lock:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc).isoformat()
            
            # Analyze task upfront
            analysis = self._analyzer.analyze(req.task, req.acceptance)
            
            run = RunResponse(
                run_id=run_id,
                state=RunState.QUEUED,
                repository=req.repository,
                task=req.task,
                acceptance=analysis.acceptance_tests,
                autonomy=req.autonomy or "sandboxed",
                budgets=req.budgets or TaskBudgets(),
                created_at=now,
                updated_at=now,
                active_stage="Task received and queued for execution",
                plan={
                    "task_analysis": analysis.model_dump(),
                    "steps": [
                        "1. Analyze repository and dependencies",
                        "2. Pin security policy and review requested capabilities",
                        "3. Retrieve relevant context symbols and budget tokens",
                        "4. Query NVIDIA model for solution patch",
                        "5. Policy-check tool requests",
                        "6. Execute and validate in Token Factory sandbox",
                    ]
                }
            )
            self._runs[run_id] = run
            return run

    def get_run(self, run_id: str) -> Optional[RunResponse]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> List[RunResponse]:
        with self._lock:
            return list(self._runs.values())

    def transition(self, run_id: str, new_state: RunState, metadata: Dict[str, Any] = None) -> RunResponse:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"Run {run_id} not found")
            
            current = self._runs[run_id]
            RunStateMachine.validate_transition(current.state, new_state)
            
            updated_dict = current.model_dump()
            updated_dict["state"] = new_state
            updated_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            if metadata:
                for k, v in metadata.items():
                    if k in updated_dict and isinstance(updated_dict[k], dict) and isinstance(v, dict):
                        updated_dict[k].update(v)
                    else:
                        updated_dict[k] = v
                        
            new_run = RunResponse(**updated_dict)
            self._runs[run_id] = new_run
            return new_run

    def cancel_run(self, run_id: str) -> RunResponse:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"Run {run_id} not found")
            current = self._runs[run_id]
            # Always validate — terminal states have no CANCELLED transition,
            # so this raises InvalidStateTransitionError -> HTTP 409.
            RunStateMachine.validate_transition(current.state, RunState.CANCELLED)
            updated_dict = current.model_dump()
            updated_dict["state"] = RunState.CANCELLED
            updated_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated_dict["active_stage"] = "Run cancelled by user request"
            new_run = RunResponse(**updated_dict)
            self._runs[run_id] = new_run
            return new_run


    def advance_mock_pipeline(self, run_id: str) -> RunResponse:
        """
        Simulate the next natural step in the pipeline for testing/demo purposes.
        """
        run = self.get_run(run_id)
        if not run:
            raise KeyError(f"Run {run_id} not found")

        transitions_map = {
            RunState.QUEUED: (RunState.ANALYZING, {"active_stage": "Analyzing repository workspace structure"}),
            RunState.ANALYZING: (RunState.SECURITY_REVIEW, {
                "active_stage": "Evaluating requested capabilities against security policies",
                "security_decision": {
                    "decision": "ALLOW",
                    "policy_version": "mvp-1.0",
                    "reason_codes": ["approved_tool_scopes", "workspace_contained"],
                }
            }),
            RunState.SECURITY_REVIEW: (RunState.PLANNING, {"active_stage": "Building bounded execution plan"}),
            RunState.PLANNING: (RunState.CONTEXT_BUILD, {"active_stage": "Retrieving and compressing repository AST context"}),
            RunState.CONTEXT_BUILD: (RunState.MODEL_STEP, {"active_stage": "Prompting NVIDIA Nemotron model via Nebius API"}),
            RunState.MODEL_STEP: (RunState.POLICY_CHECK, {
                "active_stage": "Validating model tool-call proposal against policy engine",
                "security_decision": {
                    "decision": "ALLOW_WITH_MONITORING",
                    "tool": "repo.write",
                    "path": "src/target.py"
                }
            }),
            RunState.POLICY_CHECK: (RunState.EXECUTING, {"active_stage": "Applying patch inside isolated Token Factory sandbox"}),
            RunState.EXECUTING: (RunState.VALIDATING, {
                "active_stage": "Executing pytest validation suite inside sandbox",
                "diff": "--- a/src/target.py\n+++ b/src/target.py\n@@ -10,3 +10,4 @@\n def handler(req):\n+    if not req.auth: raise AuthenticationError('Invalid credentials')\n     return process(req)"
            }),
            RunState.VALIDATING: (RunState.COMPLETED, {
                "active_stage": "Run completed successfully. All tests passed.",
                "validation_result": {
                    "status": "pass",
                    "tests_run": 14,
                    "tests_failed": 0,
                    "exit_code": 0
                }
            }),
        }

        if run.state in transitions_map:
            next_state, meta = transitions_map[run.state]
            return self.transition(run_id, next_state, meta)
        return run


# Global singleton instance for the API worker
run_store = InMemoryRunStore()
