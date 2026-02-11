"""
Automated Runbooks for Ceph Cluster Management.

Pre-defined, safety-checked remediation procedures that the agent
can execute to resolve common cluster issues. Each runbook defines:
- Trigger conditions (when to suggest this runbook)
- Pre-flight checks
- Sequential remediation steps  
- Verification steps
- Rollback procedure
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RunbookStatus(str, Enum):
    """Execution status of a runbook."""
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PAUSED = "paused"  # Waiting for confirmation


@dataclass
class RunbookStep:
    """A step in a runbook."""
    name: str
    description: str
    action: str  # Tool name to execute
    args: Dict[str, Any] = field(default_factory=dict)
    check_condition: Optional[str] = None  # Condition to check before proceeding
    on_failure: str = "abort"  # "abort", "skip", "retry"
    max_retries: int = 1
    result: Optional[Any] = None
    status: str = "pending"


@dataclass
class RunbookResult:
    """Result of a runbook execution."""
    runbook_name: str
    status: RunbookStatus
    steps_completed: int
    total_steps: int
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0
    rollback_performed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "runbook_name": self.runbook_name,
            "status": self.status.value,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "results": self.results,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "rollback_performed": self.rollback_performed,
        }


class RunbookEngine:
    """
    Engine for executing automated runbooks.
    
    Provides pre-defined remediation procedures for common
    Ceph cluster management scenarios:
    - OSD recovery
    - PG repair
    - Rebalancing
    - Capacity management
    - Performance tuning
    """
    
    def __init__(self, tool_executor: Callable):
        """
        Initialize runbook engine.
        
        Args:
            tool_executor: Function that executes a tool by name and args
        """
        self.tool_executor = tool_executor
        self.runbooks = self._register_runbooks()
        self.execution_history: List[RunbookResult] = []
        logger.info(f"Initialized RunbookEngine with {len(self.runbooks)} runbooks")
    
    def _register_runbooks(self) -> Dict[str, Dict[str, Any]]:
        """Register all available runbooks."""
        return {
            "recover_down_osd": {
                "name": "Recover Down OSD",
                "description": "Investigate and recover a down OSD",
                "triggers": ["osd down", "osd not responding", "osd failed"],
                "risk": "medium",
                "requires_params": ["osd_id"],
                "steps": [
                    RunbookStep(
                        name="check_health",
                        description="Check cluster health to assess impact",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                    RunbookStep(
                        name="check_osd_status",
                        description="Get detailed OSD status",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="check_pg_impact",
                        description="Check PG impact from the down OSD",
                        action="pg_status",
                        args={},
                    ),
                    RunbookStep(
                        name="attempt_restart",
                        description="Attempt to restart the OSD service",
                        action="restart_osd",
                        args={"osd_id": "{osd_id}"},
                        on_failure="skip",
                    ),
                    RunbookStep(
                        name="verify_recovery",
                        description="Verify OSD came back up",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="check_final_health",
                        description="Final health check after recovery",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                ],
                "rollback": [
                    RunbookStep(
                        name="mark_osd_out",
                        description="Mark OSD out if restart failed",
                        action="set_osd_out",
                        args={"osd_id": "{osd_id}"},
                    ),
                ],
            },
            "fix_degraded_pgs": {
                "name": "Fix Degraded Placement Groups",
                "description": "Investigate and repair degraded PGs",
                "triggers": ["degraded pg", "pg not clean", "recovery needed"],
                "risk": "low",
                "requires_params": [],
                "steps": [
                    RunbookStep(
                        name="check_health",
                        description="Check cluster health",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                    RunbookStep(
                        name="get_pg_details",
                        description="Get detailed PG status",
                        action="pg_status",
                        args={},
                    ),
                    RunbookStep(
                        name="check_osds",
                        description="Verify all OSDs are up",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="check_recovery_progress",
                        description="Monitor recovery progress",
                        action="performance_stats",
                        args={},
                    ),
                    RunbookStep(
                        name="final_check",
                        description="Verify PGs are recovering",
                        action="pg_status",
                        args={},
                    ),
                ],
                "rollback": [],
            },
            "rebalance_cluster": {
                "name": "Rebalance Cluster Data",
                "description": "Rebalance data across OSDs for even distribution",
                "triggers": ["unbalanced", "skewed", "rebalance", "uneven distribution"],
                "risk": "high",
                "requires_params": [],
                "steps": [
                    RunbookStep(
                        name="check_health",
                        description="Pre-flight health check",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                    RunbookStep(
                        name="check_osd_utilization",
                        description="Check OSD utilization distribution",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="set_norebalance",
                        description="Set norebalance flag for controlled operation",
                        action="set_cluster_flag",
                        args={"flag": "norebalance"},
                        on_failure="abort",
                    ),
                    RunbookStep(
                        name="adjust_weights",
                        description="Adjust CRUSH weights for better distribution",
                        action="initiate_rebalance",
                        args={},
                    ),
                    RunbookStep(
                        name="unset_norebalance",
                        description="Remove norebalance flag to start migration",
                        action="unset_cluster_flag",
                        args={"flag": "norebalance"},
                    ),
                    RunbookStep(
                        name="monitor_progress",
                        description="Monitor rebalancing progress",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                ],
                "rollback": [
                    RunbookStep(
                        name="pause_rebalance",
                        description="Pause rebalancing if issues detected",
                        action="set_cluster_flag",
                        args={"flag": "norebalance"},
                    ),
                ],
            },
            "capacity_expansion_prep": {
                "name": "Prepare for Capacity Expansion",
                "description": "Assess cluster and prepare for adding storage",
                "triggers": ["running out of space", "capacity warning", "need more storage"],
                "risk": "low",
                "requires_params": [],
                "steps": [
                    RunbookStep(
                        name="current_capacity",
                        description="Check current capacity utilization",
                        action="capacity_prediction",
                        args={"days": 90},
                    ),
                    RunbookStep(
                        name="pool_breakdown",
                        description="Get per-pool usage breakdown",
                        action="pool_stats",
                        args={},
                    ),
                    RunbookStep(
                        name="osd_distribution",
                        description="Check OSD distribution and utilization",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="performance_baseline",
                        description="Capture performance baseline before expansion",
                        action="performance_stats",
                        args={},
                    ),
                    RunbookStep(
                        name="health_check",
                        description="Verify cluster is healthy before expansion",
                        action="diagnose_cluster",
                        args={},
                    ),
                ],
                "rollback": [],
            },
            "performance_investigation": {
                "name": "Investigate Performance Issues",
                "description": "Comprehensive performance investigation",
                "triggers": ["slow", "latency", "performance", "throughput"],
                "risk": "low",
                "requires_params": [],
                "steps": [
                    RunbookStep(
                        name="health_check",
                        description="Check cluster health for alerts",
                        action="cluster_health",
                        args={"detail": True},
                    ),
                    RunbookStep(
                        name="performance_metrics",
                        description="Gather current performance metrics",
                        action="performance_stats",
                        args={},
                    ),
                    RunbookStep(
                        name="osd_check",
                        description="Check OSD status and utilization",
                        action="osd_status",
                        args={},
                    ),
                    RunbookStep(
                        name="pg_check",
                        description="Check for recovering/degraded PGs",
                        action="pg_status",
                        args={},
                    ),
                    RunbookStep(
                        name="pool_check",
                        description="Check pool statistics",
                        action="pool_stats",
                        args={},
                    ),
                ],
                "rollback": [],
            },
        }
    
    def get_available_runbooks(self) -> List[Dict[str, str]]:
        """Get list of available runbooks with descriptions."""
        return [
            {
                "name": rb_id,
                "title": rb["name"],
                "description": rb["description"],
                "risk": rb["risk"],
                "steps": len(rb["steps"]),
            }
            for rb_id, rb in self.runbooks.items()
        ]
    
    def suggest_runbook(self, issue_description: str) -> Optional[str]:
        """
        Suggest a runbook based on an issue description.
        
        Args:
            issue_description: Description of the issue
            
        Returns:
            Runbook name or None
        """
        desc_lower = issue_description.lower()
        
        for rb_id, rb in self.runbooks.items():
            for trigger in rb.get("triggers", []):
                if trigger in desc_lower:
                    return rb_id
        
        return None
    
    def execute_runbook(
        self,
        runbook_name: str,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> RunbookResult:
        """
        Execute a runbook.
        
        Args:
            runbook_name: Name of the runbook to execute
            params: Parameters to fill into step arguments
            dry_run: If True, log steps but don't execute
            
        Returns:
            RunbookResult
        """
        if runbook_name not in self.runbooks:
            return RunbookResult(
                runbook_name=runbook_name,
                status=RunbookStatus.FAILED,
                steps_completed=0,
                total_steps=0,
                error=f"Unknown runbook: {runbook_name}",
            )
        
        rb = self.runbooks[runbook_name]
        steps = rb["steps"]
        params = params or {}
        
        result = RunbookResult(
            runbook_name=runbook_name,
            status=RunbookStatus.RUNNING,
            steps_completed=0,
            total_steps=len(steps),
        )
        
        start_time = time.time()
        logger.info(f"Starting runbook: {runbook_name} ({len(steps)} steps)")
        
        for i, step in enumerate(steps):
            step_name = step.name
            logger.info(f"  Step {i+1}/{len(steps)}: {step.description}")
            
            # Substitute parameters in args
            step_args = self._substitute_params(step.args, params)
            
            if dry_run:
                result.results.append({
                    "step": step_name,
                    "description": step.description,
                    "action": step.action,
                    "args": step_args,
                    "status": "dry_run",
                })
                result.steps_completed += 1
                continue
            
            # Execute step
            retries = 0
            step_success = False
            
            while retries <= step.max_retries:
                try:
                    step_result = self.tool_executor(step.action, step_args)
                    
                    result.results.append({
                        "step": step_name,
                        "description": step.description,
                        "action": step.action,
                        "result": str(step_result)[:500] if step_result else None,
                        "status": "completed",
                    })
                    result.steps_completed += 1
                    step_success = True
                    break
                    
                except Exception as e:
                    retries += 1
                    if retries > step.max_retries:
                        logger.error(f"  Step {step_name} failed after {retries} attempts: {e}")
                        
                        result.results.append({
                            "step": step_name,
                            "description": step.description,
                            "error": str(e),
                            "status": "failed",
                        })
                        
                        if step.on_failure == "abort":
                            result.status = RunbookStatus.FAILED
                            result.error = f"Step '{step_name}' failed: {e}"
                            break
                        elif step.on_failure == "skip":
                            result.steps_completed += 1
                            step_success = True
                            break
            
            if result.status == RunbookStatus.FAILED:
                break
        
        if result.status != RunbookStatus.FAILED:
            result.status = RunbookStatus.COMPLETED
        
        result.duration_ms = (time.time() - start_time) * 1000
        self.execution_history.append(result)
        
        logger.info(f"Runbook {runbook_name} {result.status.value}: "
                     f"{result.steps_completed}/{result.total_steps} steps")
        
        return result
    
    def _substitute_params(self, args: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """Substitute template parameters in arguments."""
        result = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                param_name = value[1:-1]
                result[key] = params.get(param_name, value)
            else:
                result[key] = value
        return result
    
    def format_runbook_result(self, result: RunbookResult) -> str:
        """Format runbook result for display."""
        status_icon = {
            RunbookStatus.COMPLETED: "✅",
            RunbookStatus.FAILED: "❌",
            RunbookStatus.RUNNING: "🔄",
            RunbookStatus.ROLLED_BACK: "↩️",
            RunbookStatus.PAUSED: "⏸️",
        }.get(result.status, "❓")
        
        lines = [
            f"{status_icon} Runbook: {result.runbook_name}",
            f"   Status: {result.status.value}",
            f"   Progress: {result.steps_completed}/{result.total_steps} steps",
            f"   Duration: {result.duration_ms:.0f}ms",
            "",
        ]
        
        for step_result in result.results:
            icon = "✅" if step_result.get("status") == "completed" else "❌"
            lines.append(f"  {icon} {step_result.get('description', step_result.get('step', ''))}")
            if step_result.get("error"):
                lines.append(f"     Error: {step_result['error']}")
        
        if result.error:
            lines.append(f"\n❌ Error: {result.error}")
        
        return "\n".join(lines)
