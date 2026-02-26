"""
Action Engine for Ceph Cluster Management.

Provides a safety-checked execution engine for cluster management actions.
Separates read-only observation tools from write/mutating actions,
with confirmation gates, dry-run support, and rollback tracking.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ActionRisk(str, Enum):
    """Risk level for cluster management actions."""
    LOW = "low"          # Read-only, no cluster impact
    MEDIUM = "medium"    # Reversible changes, minor impact
    HIGH = "high"        # Significant changes, may affect availability
    CRITICAL = "critical"  # Potentially destructive, data loss possible


class ActionStatus(str, Enum):
    """Status of an executed action."""
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DENIED = "denied"


@dataclass
class ActionRecord:
    """Record of a management action execution."""
    action_id: str
    action_name: str
    parameters: Dict[str, Any]
    risk_level: ActionRisk
    status: ActionStatus
    reason: str  # Why the agent chose this action
    result: Optional[Any] = None
    error: Optional[str] = None
    rollback_command: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    approved_by: str = "auto"  # "auto" or "user"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_name": self.action_name,
            "parameters": self.parameters,
            "risk_level": self.risk_level.value,
            "status": self.status.value,
            "reason": self.reason,
            "result": str(self.result)[:500] if self.result else None,
            "error": self.error,
            "rollback_command": self.rollback_command,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "approved_by": self.approved_by,
        }


@dataclass
class ActionPolicy:
    """Policy governing what actions the agent can take autonomously."""
    # Actions the agent can perform without confirmation
    auto_approve_risk_levels: List[ActionRisk] = field(
        default_factory=lambda: [ActionRisk.LOW]
    )
    # Maximum number of actions per session
    max_actions_per_session: int = 20
    # Whether dry-run mode is enabled (log but don't execute)
    dry_run: bool = False
    # Require user confirmation for all write actions
    require_confirmation_for_writes: bool = True
    # Allowed action names (empty = all allowed)
    allowed_actions: List[str] = field(default_factory=list)
    # Blocked action names
    blocked_actions: List[str] = field(default_factory=list)


class ActionEngine:
    """
    Safety-checked execution engine for cluster management actions.
    
    Features:
    - Risk classification for every action
    - Confirmation gates for destructive operations
    - Dry-run mode for safe testing
    - Action audit log with rollback commands
    - Rate limiting to prevent runaway automation
    """
    
    # Action risk classifications
    ACTION_RISK_MAP = {
        # Read-only operations (LOW risk)
        "cluster_health": ActionRisk.LOW,
        "osd_status": ActionRisk.LOW,
        "pg_status": ActionRisk.LOW,
        "pool_stats": ActionRisk.LOW,
        "performance_stats": ActionRisk.LOW,
        "capacity_prediction": ActionRisk.LOW,
        "diagnose_cluster": ActionRisk.LOW,
        "get_stats": ActionRisk.LOW,
        "search_objects": ActionRisk.LOW,
        "list_objects": ActionRisk.LOW,
        "read_object": ActionRisk.LOW,
        "get_metadata": ActionRisk.LOW,
        "find_similar": ActionRisk.LOW,
        "explain_issue": ActionRisk.LOW,
        "search_docs": ActionRisk.LOW,
        "get_crush_rule": ActionRisk.LOW,
        "list_pools": ActionRisk.LOW,
        "get_config": ActionRisk.LOW,
        "check_osd_perf": ActionRisk.LOW,
        "scan_anomalies": ActionRisk.LOW,
        
        # Reversible/low-impact write operations (MEDIUM risk)
        "index_object": ActionRisk.MEDIUM,
        "batch_index": ActionRisk.MEDIUM,
        "repair_pg": ActionRisk.MEDIUM,
        "deep_scrub_pg": ActionRisk.MEDIUM,
        "set_cluster_flag": ActionRisk.MEDIUM,
        "unset_cluster_flag": ActionRisk.MEDIUM,
        "set_pool_param": ActionRisk.MEDIUM,
        
        # Significant changes (HIGH risk)
        "reweight_osd": ActionRisk.HIGH,
        "create_pool": ActionRisk.HIGH,
        "set_osd_out": ActionRisk.HIGH,
        "set_osd_in": ActionRisk.HIGH,
        "execute_runbook": ActionRisk.HIGH,
        "initiate_rebalance": ActionRisk.HIGH,
        "restart_osd": ActionRisk.HIGH,
        
        # Destructive operations (CRITICAL risk)
        "delete_pool": ActionRisk.CRITICAL,
        "remove_osd": ActionRisk.CRITICAL,
        "purge_osd": ActionRisk.CRITICAL,
    }
    
    # Rollback templates for reversible actions
    ROLLBACK_TEMPLATES = {
        "set_cluster_flag": "unset_cluster_flag with flag={flag}",
        "unset_cluster_flag": "set_cluster_flag with flag={flag}",
        "set_osd_out": "set_osd_in with osd_id={osd_id}",
        "set_osd_in": "set_osd_out with osd_id={osd_id}",
        "reweight_osd": "reweight_osd with osd_id={osd_id}, weight={original_weight}",
        "create_pool": "delete_pool with pool_name={pool_name}",
    }

    def __init__(self, policy: Optional[ActionPolicy] = None):
        """
        Initialize action engine.
        
        Args:
            policy: Action execution policy
        """
        self.policy = policy or ActionPolicy()
        self.action_log: List[ActionRecord] = []
        self.session_action_count = 0
        
        logger.info(f"Initialized ActionEngine (dry_run={self.policy.dry_run})")
    
    def check_action(self, action_name: str, parameters: Dict[str, Any], reason: str) -> Tuple[bool, str]:
        """
        Pre-flight check for an action.
        
        Args:
            action_name: Name of the action to execute
            parameters: Action parameters
            reason: Why the agent wants to perform this action
            
        Returns:
            Tuple of (can_execute, message)
        """
        # Check if action is blocked
        if action_name in self.policy.blocked_actions:
            return False, f"Action '{action_name}' is blocked by policy"
        
        # Check if action is in allowed list (if specified)
        if self.policy.allowed_actions and action_name not in self.policy.allowed_actions:
            return False, f"Action '{action_name}' is not in the allowed actions list"
        
        # Check session action limit
        if self.session_action_count >= self.policy.max_actions_per_session:
            return False, f"Session action limit reached ({self.policy.max_actions_per_session})"
        
        # Check risk level
        risk = self.get_risk_level(action_name)
        
        if risk not in self.policy.auto_approve_risk_levels:
            if self.policy.require_confirmation_for_writes:
                return False, (
                    f"Action '{action_name}' has risk level '{risk.value}' and requires confirmation.\n"
                    f"Reason: {reason}\n"
                    f"Parameters: {json.dumps(parameters, indent=2)}"
                )
        
        # Dry-run mode
        if self.policy.dry_run and risk != ActionRisk.LOW:
            return False, f"[DRY RUN] Would execute: {action_name}({json.dumps(parameters)})"
        
        return True, "Action approved"
    
    def execute_action(
        self,
        action_name: str,
        parameters: Dict[str, Any],
        executor: Callable,
        reason: str = "",
        force: bool = False,
    ) -> ActionRecord:
        """
        Execute a management action with safety checks.
        
        Args:
            action_name: Name of the action
            parameters: Action parameters
            executor: Callable to execute the action
            reason: Why the agent is performing this action
            force: Skip safety checks (for confirmed actions)
            
        Returns:
            ActionRecord with execution details
        """
        action_id = f"{action_name}_{int(time.time() * 1000)}"
        risk = self.get_risk_level(action_name)
        
        record = ActionRecord(
            action_id=action_id,
            action_name=action_name,
            parameters=parameters,
            risk_level=risk,
            status=ActionStatus.PENDING,
            reason=reason,
        )
        
        # Pre-flight check (unless forced)
        if not force:
            can_execute, message = self.check_action(action_name, parameters, reason)
            if not can_execute:
                record.status = ActionStatus.DENIED
                record.error = message
                self.action_log.append(record)
                return record
        
        # Generate rollback command
        record.rollback_command = self._generate_rollback(action_name, parameters)
        record.status = ActionStatus.EXECUTING
        
        # Execute
        t_start = time.time()
        try:
            result = executor(**parameters)
            record.result = result
            record.status = ActionStatus.COMPLETED
            self.session_action_count += 1
            logger.info(f"Action completed: {action_name} (risk={risk.value})")
        except Exception as e:
            record.error = str(e)
            record.status = ActionStatus.FAILED
            logger.error(f"Action failed: {action_name} - {e}")
        
        record.duration_ms = (time.time() - t_start) * 1000
        self.action_log.append(record)
        
        return record
    
    def get_risk_level(self, action_name: str) -> ActionRisk:
        """Get the risk level for an action."""
        return self.ACTION_RISK_MAP.get(action_name, ActionRisk.HIGH)
    
    def _generate_rollback(self, action_name: str, parameters: Dict[str, Any]) -> Optional[str]:
        """Generate a rollback command for an action."""
        template = self.ROLLBACK_TEMPLATES.get(action_name)
        if template:
            try:
                return template.format(**parameters)
            except KeyError:
                return f"Manual rollback needed for {action_name}"
        return None
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get the action audit log."""
        return [r.to_dict() for r in self.action_log]
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the current session."""
        risk_counts = {}
        status_counts = {}
        
        for record in self.action_log:
            risk_counts[record.risk_level.value] = risk_counts.get(record.risk_level.value, 0) + 1
            status_counts[record.status.value] = status_counts.get(record.status.value, 0) + 1
        
        return {
            "total_actions": len(self.action_log),
            "session_actions_executed": self.session_action_count,
            "risk_distribution": risk_counts,
            "status_distribution": status_counts,
            "policy": {
                "dry_run": self.policy.dry_run,
                "max_per_session": self.policy.max_actions_per_session,
                "auto_approve": [r.value for r in self.policy.auto_approve_risk_levels],
            },
        }
    
    def reset_session(self):
        """Reset the session counter (keeps audit log)."""
        self.session_action_count = 0
