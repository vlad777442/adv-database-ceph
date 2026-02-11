"""
Task Planner for Ceph Cluster Management Agent.

Decomposes complex management requests into executable plans
with dependency tracking, parallel execution support, and
checkpointing.
"""

import logging
import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from core.llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Status of a planned task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step_id: int
    description: str
    tool_name: str
    tool_args: Dict[str, Any]
    depends_on: List[int] = field(default_factory=list)  # step_ids this depends on
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ExecutionPlan:
    """A structured execution plan for a complex task."""
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    estimated_risk: str = "low"
    requires_confirmation: bool = False
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "estimated_risk": self.estimated_risk,
            "requires_confirmation": self.requires_confirmation,
            "summary": self.summary,
        }
    
    def get_next_steps(self) -> List[PlanStep]:
        """Get steps that are ready to execute (dependencies met)."""
        completed_ids = {s.step_id for s in self.steps if s.status == TaskStatus.COMPLETED}
        ready = []
        for step in self.steps:
            if step.status == TaskStatus.PENDING:
                if all(dep in completed_ids for dep in step.depends_on):
                    ready.append(step)
        return ready
    
    def is_complete(self) -> bool:
        """Check if all steps are done (completed, failed, or skipped)."""
        return all(
            s.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)
            for s in self.steps
        )
    
    def get_progress(self) -> Dict[str, int]:
        """Get plan progress summary."""
        counts = {}
        for s in self.steps:
            counts[s.status.value] = counts.get(s.status.value, 0) + 1
        counts["total"] = len(self.steps)
        return counts


class TaskPlanner:
    """
    LLM-powered task planner for Ceph cluster management.
    
    Decomposes complex natural language requests into structured
    execution plans with:
    - Dependency tracking between steps
    - Risk estimation
    - Parallel execution when possible
    - Checkpoint and resume capability
    """
    
    # Pre-defined plan templates for common operations
    PLAN_TEMPLATES = {
        "add_osd": {
            "description": "Add a new OSD to the cluster",
            "steps": [
                {"description": "Check cluster health", "tool": "cluster_health", "args": {}},
                {"description": "Check current OSD count and distribution", "tool": "osd_status", "args": {}},
                {"description": "Check capacity before adding", "tool": "capacity_prediction", "args": {}},
                {"description": "Prepare the new OSD device", "tool": "prepare_osd", "args": {"device": "{device}"}},
                {"description": "Activate the OSD", "tool": "activate_osd", "args": {"osd_id": "{osd_id}"}},
                {"description": "Verify OSD is up and in", "tool": "osd_status", "args": {}},
                {"description": "Monitor rebalancing progress", "tool": "cluster_health", "args": {"detail": True}},
            ],
            "risk": "high",
        },
        "replace_osd": {
            "description": "Replace a failed OSD",
            "steps": [
                {"description": "Check cluster health and identify issues", "tool": "diagnose_cluster", "args": {}},
                {"description": "Get OSD details", "tool": "osd_status", "args": {}},
                {"description": "Mark OSD out", "tool": "set_osd_out", "args": {"osd_id": "{osd_id}"}},
                {"description": "Wait for rebalancing", "tool": "cluster_health", "args": {"detail": True}},
                {"description": "Remove old OSD", "tool": "remove_osd", "args": {"osd_id": "{osd_id}"}},
                {"description": "Add replacement OSD", "tool": "prepare_osd", "args": {"device": "{device}"}},
                {"description": "Verify cluster health", "tool": "diagnose_cluster", "args": {}},
            ],
            "risk": "critical",
        },
        "troubleshoot_slow": {
            "description": "Troubleshoot slow cluster performance",
            "steps": [
                {"description": "Check cluster health", "tool": "cluster_health", "args": {"detail": True}},
                {"description": "Check OSD status and utilization", "tool": "osd_status", "args": {}},
                {"description": "Check performance stats (IOPS, throughput)", "tool": "performance_stats", "args": {}},
                {"description": "Check PG status for recovering/degraded", "tool": "pg_status", "args": {}},
                {"description": "Check pool statistics", "tool": "pool_stats", "args": {}},
                {"description": "Analyze and provide recommendations", "tool": "explain_issue", "args": {"topic": "slow performance diagnosis"}},
            ],
            "risk": "low",
        },
        "capacity_planning": {
            "description": "Perform capacity planning analysis",
            "steps": [
                {"description": "Get current capacity", "tool": "capacity_prediction", "args": {"days": 90}},
                {"description": "Get per-pool statistics", "tool": "pool_stats", "args": {}},
                {"description": "Check OSD utilization distribution", "tool": "osd_status", "args": {}},
                {"description": "Generate long-term projection", "tool": "capacity_prediction", "args": {"days": 365}},
            ],
            "risk": "low",
        },
    }
    
    def __init__(self, llm: BaseLLMProvider, available_tools: List[str]):
        """
        Initialize task planner.
        
        Args:
            llm: LLM provider for plan generation
            available_tools: List of available tool names
        """
        self.llm = llm
        self.available_tools = available_tools
        logger.info(f"Initialized TaskPlanner with {len(available_tools)} tools")
    
    def create_plan(self, goal: str, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """
        Create an execution plan for a goal.
        
        First checks templates, then uses LLM for novel requests.
        
        Args:
            goal: Natural language description of the goal
            context: Additional context (cluster state, etc.)
            
        Returns:
            ExecutionPlan
        """
        # Check for template match
        template = self._match_template(goal)
        if template:
            logger.info(f"Using plan template: {template['description']}")
            return self._instantiate_template(template, goal, context)
        
        # Use LLM to generate a plan
        return self._generate_plan_with_llm(goal, context)
    
    def _match_template(self, goal: str) -> Optional[Dict]:
        """Check if a goal matches a pre-defined template."""
        goal_lower = goal.lower()
        
        keywords = {
            "add_osd": ["add osd", "add disk", "add storage", "new osd"],
            "replace_osd": ["replace osd", "swap osd", "failed osd", "replace disk"],
            "troubleshoot_slow": ["slow", "performance issue", "latency", "throughput problem"],
            "capacity_planning": ["capacity plan", "disk space", "when will", "storage forecast"],
        }
        
        for template_name, kws in keywords.items():
            if any(kw in goal_lower for kw in kws):
                return self.PLAN_TEMPLATES[template_name]
        
        return None
    
    def _instantiate_template(
        self, template: Dict, goal: str, context: Optional[Dict] = None
    ) -> ExecutionPlan:
        """Create a plan from a template."""
        plan = ExecutionPlan(
            goal=goal,
            estimated_risk=template.get("risk", "medium"),
            requires_confirmation=template.get("risk", "low") in ("high", "critical"),
            summary=template["description"],
        )
        
        for i, step_def in enumerate(template["steps"]):
            plan.steps.append(PlanStep(
                step_id=i + 1,
                description=step_def["description"],
                tool_name=step_def["tool"],
                tool_args=step_def.get("args", {}),
                depends_on=[i] if i > 0 else [],  # Sequential by default
            ))
        
        return plan
    
    def _generate_plan_with_llm(
        self, goal: str, context: Optional[Dict] = None
    ) -> ExecutionPlan:
        """Use LLM to generate a plan for a novel request."""
        tools_list = ", ".join(self.available_tools)
        
        context_text = ""
        if context:
            context_text = f"\nCurrent context: {json.dumps(context, default=str)[:1000]}"
        
        prompt = f"""You are a Ceph cluster management planner. Create a step-by-step execution plan.

Available tools: {tools_list}

Goal: {goal}
{context_text}

Create a plan as a JSON array of steps. Each step has:
- "description": what the step does
- "tool": which tool to use (from the available tools list)
- "args": parameters for the tool (JSON object)
- "depends_on": list of step numbers this depends on (empty for first steps)

Also include:
- "risk": "low", "medium", "high", or "critical"
- "summary": one-sentence summary of the plan

Respond with JSON only:
{{
    "summary": "...",
    "risk": "...",
    "steps": [
        {{"description": "...", "tool": "...", "args": {{}}, "depends_on": []}},
        ...
    ]
}}"""
        
        try:
            response = self.llm.complete(
                prompt,
                system="You are a Ceph cluster management expert. Generate precise, actionable plans."
            )
            
            # Parse JSON response
            plan_data = json.loads(response)
            
            plan = ExecutionPlan(
                goal=goal,
                estimated_risk=plan_data.get("risk", "medium"),
                requires_confirmation=plan_data.get("risk", "medium") in ("high", "critical"),
                summary=plan_data.get("summary", goal),
            )
            
            for i, step_data in enumerate(plan_data.get("steps", [])):
                tool_name = step_data.get("tool", "")
                # Validate tool exists
                if tool_name not in self.available_tools:
                    logger.warning(f"LLM suggested unknown tool: {tool_name}")
                    continue
                
                plan.steps.append(PlanStep(
                    step_id=i + 1,
                    description=step_data.get("description", ""),
                    tool_name=tool_name,
                    tool_args=step_data.get("args", {}),
                    depends_on=step_data.get("depends_on", []),
                ))
            
            return plan
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM plan: {e}")
            # Fallback: single diagnostic step
            plan = ExecutionPlan(
                goal=goal,
                summary=f"Fallback plan for: {goal}",
            )
            plan.steps.append(PlanStep(
                step_id=1,
                description="Diagnose cluster to understand current state",
                tool_name="diagnose_cluster",
                tool_args={},
            ))
            return plan
    
    def format_plan(self, plan: ExecutionPlan) -> str:
        """Format a plan for display."""
        lines = [
            f"📋 **Execution Plan**: {plan.summary}",
            f"   Risk Level: {plan.estimated_risk.upper()}",
            f"   Steps: {len(plan.steps)}",
            "",
        ]
        
        for step in plan.steps:
            status_icon = {
                TaskStatus.PENDING: "⬜",
                TaskStatus.IN_PROGRESS: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.SKIPPED: "⏭️",
                TaskStatus.BLOCKED: "🚫",
            }.get(step.status, "⬜")
            
            deps = f" (after step {step.depends_on})" if step.depends_on else ""
            lines.append(f"  {status_icon} Step {step.step_id}: {step.description}{deps}")
            lines.append(f"     Tool: {step.tool_name}")
        
        if plan.requires_confirmation:
            lines.append("")
            lines.append("⚠️ This plan contains high-risk operations and requires confirmation.")
        
        return "\n".join(lines)
