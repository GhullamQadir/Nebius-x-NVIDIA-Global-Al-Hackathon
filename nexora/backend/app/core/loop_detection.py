"""
Nexora Loop Detection
Detects and prevents repeated failed actions
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from nexora.backend.app.models import LoopDetection as LoopDetectionModel
from nexora.backend.app.schemas import LoopDetectionBase as LoopDetectionSchema


@dataclass
class LoopRecord:
    """Record of an action for loop detection"""
    action_hash: str
    action_type: str
    normalized_command: str
    target_path: Optional[str]
    result_class: str
    attempt_count: int
    last_attempt_at: datetime


class LoopDetector:
    """
    Loop Detector - tracks repeated actions and stops infinite loops.
    
    Persists record per action: action_hash, action_type, normalized_command,
    target, result_class, timestamp, attempt.
    
    When same unsuccessful action reaches threshold (default 2 in demo, 3 in standard),
    stop, change strategy, or request approval.
    """
    
    def __init__(self, threshold: int = 2):
        self.threshold = threshold
        self._records: Dict[str, LoopRecord] = {}
    
    def record_action(
        self,
        action_type: str,
        normalized_command: str,
        target_path: Optional[str],
        result_class: str,
    ) -> LoopRecord:
        """
        Record an action attempt.
        
        Args:
            action_type: Type of action (tool name)
            normalized_command: Normalized command/arguments
            target_path: Target file/path if applicable
            result_class: Result classification (success, same_failure, different_failure, etc.)
            
        Returns:
            Updated loop record
        """
        # Create action hash
        action_data = {
            "action_type": action_type,
            "normalized_command": normalized_command,
            "target_path": target_path,
        }
        action_hash = hashlib.sha256(
            json.dumps(action_data, sort_keys=True).encode()
        ).hexdigest()[:16]
        
        if action_hash in self._records:
            record = self._records[action_hash]
            record.attempt_count += 1
            record.last_attempt_at = datetime.now()
            record.result_class = result_class
        else:
            record = LoopRecord(
                action_hash=action_hash,
                action_type=action_type,
                normalized_command=normalized_command,
                target_path=target_path,
                result_class=result_class,
                attempt_count=1,
                last_attempt_at=datetime.now(),
            )
            self._records[action_hash] = record
        
        return record
    
    def check_loop(self, action_hash: str) -> Optional[LoopRecord]:
        """Check if action has exceeded threshold"""
        record = self._records.get(action_hash)
        if record and record.attempt_count >= self.threshold:
            return record
        return None
    
    def get_action_hash(
        self,
        action_type: str,
        normalized_command: str,
        target_path: Optional[str],
    ) -> str:
        """Compute action hash for lookup"""
        action_data = {
            "action_type": action_type,
            "normalized_command": normalized_command,
            "target_path": target_path,
        }
        return hashlib.sha256(
            json.dumps(action_data, sort_keys=True).encode()
        ).hexdigest()[:16]
    
    def should_stop(self, action_hash: str) -> bool:
        """Check if loop threshold reached for action"""
        record = self._records.get(action_hash)
        if record and record.attempt_count >= self.threshold:
            # Only stop if result is failure
            return record.result_class in ("same_failure", "failure", "error")
        return False
    
    def get_recommendation(self, action_hash: str) -> str:
        """Get recommendation for looped action"""
        record = self._records.get(action_hash)
        if not record:
            return "continue"
        
        if record.attempt_count >= self.threshold:
            if record.result_class == "same_failure":
                return "change_strategy"  # Rebuild context, try different approach
            elif record.result_class in ("failure", "error"):
                return "request_approval"  # Escalate to human
        
        return "continue"
    
    def get_all_records(self) -> List[LoopRecord]:
        """Get all loop records"""
        return list(self._records.values())
    
    def to_schema(self, record: LoopRecord, run_id: str) -> LoopDetectionSchema:
        """Convert to API schema"""
        return LoopDetectionSchema(
            id=run_id,
            run_id=run_id,
            action_hash=record.action_hash,
            action_type=record.action_type,
            normalized_command=record.normalized_command,
            target_path=record.target_path,
            result_class=record.result_class,
            attempt_count=record.attempt_count,
            last_attempt_at=record.last_attempt_at,
            created_at=record.last_attempt_at,
        )


def get_loop_detector(threshold: int = 2) -> LoopDetector:
    """Create loop detector with threshold"""
    return LoopDetector(threshold)
