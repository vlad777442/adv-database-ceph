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
        "explain_issue": ActionRisk.LOW,
        "search_docs": ActionRisk.LOW,
        "get_crush_rule": ActionRisk.LOW,
        "list_pools": ActionRisk.LOW,
        "get_config": ActionRisk.LOW,
        "check_osd_perf": ActionRisk.LOW,
        "scan_anomalies": ActionRisk.LOW,
        "help": ActionRisk.LOW,
        "list_runbooks": ActionRisk.LOW,
        "suggest_runbook": ActionRisk.LOW,
        "create_plan": ActionRisk.LOW,
        "get_action_log": ActionRisk.LOW,
        
        # CRUSH read-only (LOW risk)
        "crush_dump": ActionRisk.LOW,
        "crush_tree": ActionRisk.LOW,
        "crush_rule_ls": ActionRisk.LOW,
        "crush_rule_dump": ActionRisk.LOW,
        
        # OSD lifecycle read-only (LOW risk)
        "osd_safe_to_destroy": ActionRisk.LOW,
        "osd_ok_to_stop": ActionRisk.LOW,
        "osd_df": ActionRisk.LOW,
        
        # Auth read-only (LOW risk)
        "auth_list": ActionRisk.LOW,
        "auth_get_key": ActionRisk.LOW,
        
        # Monitor read-only (LOW risk)
        "mon_stat": ActionRisk.LOW,
        "mon_dump": ActionRisk.LOW,
        "quorum_status": ActionRisk.LOW,
        
        # MGR read-only (LOW risk)
        "mgr_module_ls": ActionRisk.LOW,
        "mgr_dump": ActionRisk.LOW,
        
        # Erasure code read-only (LOW risk)
        "ec_profile_ls": ActionRisk.LOW,
        "ec_profile_get": ActionRisk.LOW,
        
        # Pool read-only (LOW risk)
        "pool_get": ActionRisk.LOW,
        "pool_get_quota": ActionRisk.LOW,
        
        # PG read-only (LOW risk)
        "pg_dump_stuck": ActionRisk.LOW,
        "pg_ls": ActionRisk.LOW,
        
        # OSD blocklist read-only (LOW risk)
        "osd_blocklist_ls": ActionRisk.LOW,
        
        # RBD read-only (LOW risk)
        "rbd_ls": ActionRisk.LOW,
        "rbd_info": ActionRisk.LOW,
        "rbd_snap_ls": ActionRisk.LOW,
        "rbd_du": ActionRisk.LOW,
        
        # CephFS read-only (LOW risk)
        "fs_ls": ActionRisk.LOW,
        "fs_status": ActionRisk.LOW,
        "mds_stat": ActionRisk.LOW,
        
        # Device health read-only (LOW risk)
        "device_ls": ActionRisk.LOW,
        "device_info": ActionRisk.LOW,
        "device_predict_life_expectancy": ActionRisk.LOW,
        
        # Crash read-only (LOW risk)
        "crash_ls": ActionRisk.LOW,
        "crash_info": ActionRisk.LOW,
        
        # OSD extended read-only (LOW risk)
        "osd_dump": ActionRisk.LOW,
        "osd_find": ActionRisk.LOW,
        "osd_metadata": ActionRisk.LOW,
        "osd_perf": ActionRisk.LOW,
        "osd_pool_autoscale_status": ActionRisk.LOW,
        
        # Config DB read-only (LOW risk)
        "config_dump": ActionRisk.LOW,
        "config_get": ActionRisk.LOW,
        "config_show": ActionRisk.LOW,
        "config_log": ActionRisk.LOW,
        
        # Balancer read-only (LOW risk)
        "balancer_status": ActionRisk.LOW,
        "balancer_eval": ActionRisk.LOW,
        
        # Reversible/low-impact write operations (MEDIUM risk)
        "repair_pg": ActionRisk.MEDIUM,
        "deep_scrub_pg": ActionRisk.MEDIUM,
        "set_cluster_flag": ActionRisk.MEDIUM,
        "unset_cluster_flag": ActionRisk.MEDIUM,
        "set_pool_param": ActionRisk.MEDIUM,
        "set_config": ActionRisk.MEDIUM,
        "pg_scrub": ActionRisk.MEDIUM,
        "mgr_module_enable": ActionRisk.MEDIUM,
        "mgr_module_disable": ActionRisk.MEDIUM,
        "pool_application_enable": ActionRisk.MEDIUM,
        "pool_set_quota": ActionRisk.MEDIUM,
        "pool_mksnap": ActionRisk.MEDIUM,
        "pool_rmsnap": ActionRisk.MEDIUM,
        "ec_profile_set": ActionRisk.MEDIUM,
        "osd_blocklist_add": ActionRisk.MEDIUM,
        "auth_caps": ActionRisk.MEDIUM,
        "crash_archive": ActionRisk.MEDIUM,
        "crash_archive_all": ActionRisk.MEDIUM,
        "device_light": ActionRisk.MEDIUM,
        "rbd_snap_create": ActionRisk.MEDIUM,
        "rbd_snap_rm": ActionRisk.MEDIUM,
        "config_set": ActionRisk.MEDIUM,
        "fs_set": ActionRisk.MEDIUM,
        
        # Significant changes (HIGH risk)
        "reweight_osd": ActionRisk.HIGH,
        "create_pool": ActionRisk.HIGH,
        "set_osd_out": ActionRisk.HIGH,
        "set_osd_in": ActionRisk.HIGH,
        "execute_runbook": ActionRisk.HIGH,
        "initiate_rebalance": ActionRisk.HIGH,
        "restart_osd": ActionRisk.HIGH,
        "crush_add_bucket": ActionRisk.HIGH,
        "crush_move": ActionRisk.HIGH,
        "crush_reweight": ActionRisk.HIGH,
        "crush_rule_create_simple": ActionRisk.HIGH,
        "crush_rule_rm": ActionRisk.HIGH,
        "osd_down": ActionRisk.HIGH,
        "osd_reweight_by_utilization": ActionRisk.HIGH,
        "auth_add": ActionRisk.HIGH,
        "pool_rename": ActionRisk.HIGH,
        "pool_get": ActionRisk.LOW,
        "mgr_fail": ActionRisk.HIGH,
        "rbd_create": ActionRisk.HIGH,
        "balancer_optimize": ActionRisk.HIGH,
        "fs_new": ActionRisk.HIGH,
        
        # Destructive operations (CRITICAL risk)
        "delete_pool": ActionRisk.CRITICAL,
        "remove_osd": ActionRisk.CRITICAL,
        "purge_osd": ActionRisk.CRITICAL,
        "osd_destroy": ActionRisk.CRITICAL,
        "osd_purge": ActionRisk.CRITICAL,
        "crush_remove": ActionRisk.CRITICAL,
        "auth_del": ActionRisk.CRITICAL,
        "mon_add": ActionRisk.CRITICAL,
        "mon_remove": ActionRisk.CRITICAL,
        "ec_profile_rm": ActionRisk.CRITICAL,
        "rbd_rm": ActionRisk.CRITICAL,
        "fs_rm": ActionRisk.CRITICAL,
    }
    
    # Rollback templates for reversible actions
    ROLLBACK_TEMPLATES = {
        "set_cluster_flag": "unset_cluster_flag with flag={flag}",
        "unset_cluster_flag": "set_cluster_flag with flag={flag}",
        "set_osd_out": "set_osd_in with osd_id={osd_id}",
        "set_osd_in": "set_osd_out with osd_id={osd_id}",
        "reweight_osd": "reweight_osd with osd_id={osd_id}, weight={original_weight}",
        "create_pool": "delete_pool with pool_name={pool_name}",
        "crush_add_bucket": "crush_remove with name={name}",
        "mgr_module_enable": "mgr_module_disable with module={module}",
        "mgr_module_disable": "mgr_module_enable with module={module}",
        "osd_down": "Manually bring OSD back up (systemctl start ceph-osd@{osd_id})",
        "pool_set_quota": "pool_set_quota with pool_name={pool_name}, quota_type={quota_type}, value=0",
        "osd_blocklist_add": "osd_blocklist_rm with addr={addr}",
        "rbd_create": "rbd_rm with image_name={image_name}, pool_name={pool_name}",
        "rbd_snap_create": "rbd_snap_rm with image_name={image_name}, snap_name={snap_name}, pool_name={pool_name}",
        "fs_new": "fs_rm with fs_name={fs_name}",
        "config_set": "config_set with who={who}, key={key}, value={original_value}",
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
