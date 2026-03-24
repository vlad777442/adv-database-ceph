"""
ReAct (Reasoning + Acting) Agent Loop for Ceph Cluster Management.

Implements a multi-step agent loop where the LLM:
1. Observes the current cluster state
2. Reasons about what to do next
3. Selects and executes a tool
4. Reflects on the result
5. Decides whether to continue or return a final answer

This is the core agentic behavior that distinguishes a true AI agent
from a simple intent-classification wrapper.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from core.llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


# Maximum iterations to prevent runaway loops
MAX_ITERATIONS = 10
# Maximum time for a single agent session (seconds)
MAX_SESSION_TIME = 120


class AgentStepType(str, Enum):
    """Types of steps in the agent loop."""
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class AgentStep:
    """A single step in the agent's reasoning trace."""
    step_type: AgentStepType
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type.value,
            "content": self.content,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": str(self.tool_result)[:500] if self.tool_result else None,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentTrace:
    """Complete reasoning trace for an agent session."""
    query: str
    steps: List[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    success: bool = False
    total_time_ms: float = 0.0
    iterations: int = 0
    tools_used: List[str] = field(default_factory=list)
    rollback_suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "steps": [s.to_dict() for s in self.steps],
            "final_answer": self.final_answer,
            "success": self.success,
            "total_time_ms": self.total_time_ms,
            "iterations": self.iterations,
            "tools_used": self.tools_used,
            "rollback_suggestions": self.rollback_suggestions,
        }


class ReActAgentLoop:
    """
    ReAct-style agent loop for autonomous Ceph cluster management.
    
    The agent follows the Observe-Think-Act pattern:
    - Observe: Gather information from the cluster
    - Think: Reason about the current state and what to do
    - Act: Execute a tool or provide a final answer
    
    Key features:
    - Multi-step reasoning: Can chain multiple tool calls
    - Self-correction: Can detect and recover from errors
    - Safety checks: Validates destructive actions before execution  
    - Scratchpad: Maintains intermediate results for context
    """

    def __init__(
        self,
        llm: BaseLLMProvider,
        tools: Dict[str, Callable],
        tool_descriptions: List[Dict[str, Any]],
        max_iterations: int = MAX_ITERATIONS,
        max_time: float = MAX_SESSION_TIME,
        require_confirmation: bool = True,
    ):
        """
        Initialize ReAct agent loop.
        
        Args:
            llm: LLM provider for reasoning
            tools: Dictionary mapping tool names to callable functions
            tool_descriptions: Tool schema definitions for the LLM prompt
            max_iterations: Maximum reasoning iterations
            max_time: Maximum session time in seconds
            require_confirmation: Whether destructive actions need confirmation
        """
        self.llm = llm
        self.tools = tools
        self.tool_descriptions = tool_descriptions
        self.max_iterations = max_iterations
        self.max_time = max_time
        self.require_confirmation = require_confirmation
        
        # Destructive actions that need confirmation
        self.destructive_actions = {
            "remove_osd", "set_osd_out", "delete_pool",
            "set_cluster_flag", "execute_runbook", "reweight_osd",
        }
        
        logger.info(f"Initialized ReAct Agent Loop (max_iter={max_iterations}, tools={len(tools)})")

    def run(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        auto_confirm: bool = False,
    ) -> AgentTrace:
        """
        Execute the ReAct loop for a user query.
        
        Args:
            query: User's natural language query
            context: Optional additional context (e.g., conversation history)
            auto_confirm: Auto-confirm destructive operations
            
        Returns:
            AgentTrace with full reasoning trace and final answer
        """
        trace = AgentTrace(query=query)
        start_time = time.time()
        scratchpad = []  # Running list of Thought/Action/Observation tuples
        completed_actions = []  # Track (action_name, action_input) for rollback
        
        logger.info(f"Starting ReAct loop for: '{query}'")
        
        for iteration in range(self.max_iterations):
            trace.iterations = iteration + 1
            elapsed = time.time() - start_time
            
            # Time guard
            if elapsed > self.max_time:
                trace.steps.append(AgentStep(
                    step_type=AgentStepType.ERROR,
                    content=f"Agent timed out after {elapsed:.1f}s",
                ))
                trace.final_answer = "I ran out of time processing your request. Here's what I found so far:\n"
                trace.final_answer += self._summarize_scratchpad(scratchpad)
                break
            
            # === THINK: Ask LLM to reason about next step ===
            t_think_start = time.time()
            think_result = self._think(query, scratchpad, context)
            t_think_end = time.time()
            
            thought = think_result.get("thought", "")
            action = think_result.get("action")
            action_input = think_result.get("action_input", {})
            final_answer = think_result.get("final_answer")
            
            # Record thought
            trace.steps.append(AgentStep(
                step_type=AgentStepType.THOUGHT,
                content=thought,
                duration_ms=(t_think_end - t_think_start) * 1000,
            ))
            scratchpad.append(("Thought", thought))
            
            # === FINAL ANSWER: LLM decided it has enough info ===
            if final_answer:
                trace.steps.append(AgentStep(
                    step_type=AgentStepType.FINAL_ANSWER,
                    content=final_answer,
                ))
                trace.final_answer = final_answer
                trace.success = True
                break
            
            # === ACT: Execute the chosen tool ===
            if action and action in self.tools:
                # Safety check for destructive actions
                if action in self.destructive_actions and not auto_confirm:
                    if self.require_confirmation:
                        trace.steps.append(AgentStep(
                            step_type=AgentStepType.ACTION,
                            content=f"REQUIRES CONFIRMATION: {action}({json.dumps(action_input)})",
                            tool_name=action,
                            tool_args=action_input,
                        ))
                        trace.final_answer = (
                            f"I want to execute **{action}** with parameters: "
                            f"{json.dumps(action_input, indent=2)}\n\n"
                            f"Reason: {thought}\n\n"
                            f"This is a potentially destructive action. Please confirm to proceed."
                        )
                        trace.success = False
                        break
                
                # Execute the tool
                t_act_start = time.time()
                try:
                    tool_result = self.tools[action](**action_input)
                    t_act_end = time.time()
                    
                    observation = self._format_tool_result(tool_result)
                    
                    trace.steps.append(AgentStep(
                        step_type=AgentStepType.ACTION,
                        content=f"Calling {action}",
                        tool_name=action,
                        tool_args=action_input,
                        tool_result=observation,
                        duration_ms=(t_act_end - t_act_start) * 1000,
                    ))
                    trace.tools_used.append(action)
                    completed_actions.append((action, action_input))
                    
                    scratchpad.append(("Action", f"{action}({json.dumps(action_input)})"))
                    scratchpad.append(("Observation", observation))
                    
                except Exception as e:
                    t_act_end = time.time()
                    error_msg = f"Tool {action} failed: {str(e)}"
                    logger.error(error_msg)
                    
                    trace.steps.append(AgentStep(
                        step_type=AgentStepType.ERROR,
                        content=error_msg,
                        tool_name=action,
                        tool_args=action_input,
                        duration_ms=(t_act_end - t_act_start) * 1000,
                    ))
                    # Generate rollback suggestions for completed actions
                    if completed_actions:
                        trace.rollback_suggestions = self._suggest_rollbacks(
                            completed_actions
                        )
                        logger.warning(
                            f"Tool {action} failed after {len(completed_actions)} "
                            f"prior actions; rollback suggestions generated"
                        )
                    scratchpad.append(("Action", f"{action}({json.dumps(action_input)})"))
                    scratchpad.append(("Observation", f"ERROR: {error_msg}"))
            
            elif action:
                # Unknown tool
                error_msg = f"Unknown tool: {action}"
                trace.steps.append(AgentStep(
                    step_type=AgentStepType.ERROR,
                    content=error_msg,
                ))
                scratchpad.append(("Action", f"{action}({json.dumps(action_input)})"))
                scratchpad.append(("Observation", f"ERROR: {error_msg}. Available tools: {list(self.tools.keys())}"))
        
        else:
            # Hit max iterations
            trace.final_answer = "I reached the maximum number of reasoning steps. Here's what I found:\n"
            trace.final_answer += self._summarize_scratchpad(scratchpad)
        
        trace.total_time_ms = (time.time() - start_time) * 1000
        logger.info(f"ReAct loop completed: {trace.iterations} iterations, "
                     f"{len(trace.tools_used)} tools used, {trace.total_time_ms:.0f}ms")
        return trace

    def _think(
        self,
        query: str,
        scratchpad: List[tuple],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ask the LLM to reason about the next step.
        
        Returns dict with keys: thought, action, action_input, final_answer
        """
        tools_desc = self._format_tool_descriptions()
        
        scratchpad_text = ""
        for label, content in scratchpad:
            scratchpad_text += f"{label}: {content}\n"
        
        context_text = ""
        if context:
            if "conversation_history" in context:
                context_text = "Previous conversation:\n"
                for msg in context["conversation_history"][-5:]:
                    context_text += f"  {msg['role']}: {msg['content']}\n"
        
        prompt = f"""You are an autonomous AI agent for Ceph distributed storage cluster management.
Your job is to help administrators manage, monitor, troubleshoot, and optimize their Ceph cluster.

You have access to these tools:
{tools_desc}

When responding, use EXACTLY this format:

Thought: <your reasoning about what to do next>
Action: <tool_name>
Action Input: <JSON parameters for the tool>

OR if you have enough information to answer:

Thought: <your final reasoning>
Final Answer: <your comprehensive answer to the user>

IMPORTANT RULES:
1. Always start with a Thought explaining your reasoning
2. Use tools to gather information before making conclusions
3. For cluster management tasks, always check cluster health first
4. For troubleshooting, gather multiple data points before diagnosing
5. For destructive operations, explain what you plan to do and why
6. Chain multiple tool calls when needed - don't guess when you can look up
7. If a tool fails, try an alternative approach
8. Provide actionable recommendations, not just raw data

{context_text}

User Query: {query}

{f"Scratchpad (previous steps):{chr(10)}{scratchpad_text}" if scratchpad_text else "This is the first step."}
"""
        
        system = (
            "You are an expert Ceph storage cluster management agent. "
            "You think step-by-step, use tools to gather information, "
            "and provide actionable recommendations. You handle complex "
            "multi-step tasks autonomously."
        )
        
        try:
            response = self.llm.complete(prompt, system=system)
            return self._parse_react_response(response)
        except Exception as e:
            logger.error(f"LLM reasoning failed: {e}")
            return {
                "thought": f"Reasoning failed: {e}",
                "final_answer": f"I encountered an error while reasoning: {e}",
            }

    def _parse_react_response(self, response: str) -> Dict[str, Any]:
        """Parse the LLM's ReAct-format response."""
        result = {
            "thought": "",
            "action": None,
            "action_input": {},
            "final_answer": None,
        }
        
        lines = response.strip().split("\n")
        current_section = None
        current_content = []
        
        for line in lines:
            stripped = line.strip()
            
            if stripped.lower().startswith("thought:"):
                if current_section and current_content:
                    self._store_section(result, current_section, "\n".join(current_content))
                current_section = "thought"
                current_content = [stripped[len("thought:"):].strip()]
            elif stripped.lower().startswith("action:") and not stripped.lower().startswith("action input:"):
                if current_section and current_content:
                    self._store_section(result, current_section, "\n".join(current_content))
                current_section = "action"
                current_content = [stripped[len("action:"):].strip()]
            elif stripped.lower().startswith("action input:"):
                if current_section and current_content:
                    self._store_section(result, current_section, "\n".join(current_content))
                current_section = "action_input"
                current_content = [stripped[len("action input:"):].strip()]
            elif stripped.lower().startswith("final answer:"):
                if current_section and current_content:
                    self._store_section(result, current_section, "\n".join(current_content))
                current_section = "final_answer"
                current_content = [stripped[len("final answer:"):].strip()]
            else:
                current_content.append(stripped)
        
        # Store last section
        if current_section and current_content:
            self._store_section(result, current_section, "\n".join(current_content))
        
        # If we couldn't parse properly, treat the whole response as a final answer
        if not result["thought"] and not result["action"] and not result["final_answer"]:
            result["final_answer"] = response.strip()
        
        return result

    def _store_section(self, result: Dict, section: str, content: str):
        """Store parsed section content."""
        content = content.strip()
        if section == "thought":
            result["thought"] = content
        elif section == "action":
            result["action"] = content.strip().lower()
        elif section == "action_input":
            try:
                result["action_input"] = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from the content
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    try:
                        result["action_input"] = json.loads(match.group())
                    except json.JSONDecodeError:
                        result["action_input"] = {"raw_input": content}
                else:
                    result["action_input"] = {"raw_input": content}
        elif section == "final_answer":
            result["final_answer"] = content

    def _format_tool_descriptions(self) -> str:
        """Format tool descriptions for the LLM prompt."""
        lines = []
        for tool in self.tool_descriptions:
            name = tool["name"]
            desc = tool["description"]
            params = tool.get("parameters", {})
            
            param_strs = []
            for pname, pinfo in params.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                required = pinfo.get("required", False)
                req_tag = " (REQUIRED)" if required else ""
                param_strs.append(f"    - {pname} ({ptype}{req_tag}): {pdesc}")
            
            params_text = "\n".join(param_strs) if param_strs else "    (no parameters)"
            lines.append(f"  {name}: {desc}\n  Parameters:\n{params_text}")
        
        return "\n\n".join(lines)

    def _format_tool_result(self, result: Any) -> str:
        """Format tool result for the scratchpad."""
        if isinstance(result, dict):
            # For OperationResult-like objects
            if "message" in result:
                return result["message"]
            return json.dumps(result, indent=2, default=str)[:2000]
        elif isinstance(result, str):
            return result[:2000]
        elif isinstance(result, list):
            return json.dumps(result, indent=2, default=str)[:2000]
        elif hasattr(result, 'message'):
            return result.message
        elif hasattr(result, 'to_dict'):
            return json.dumps(result.to_dict(), indent=2, default=str)[:2000]
        return str(result)[:2000]

    def _summarize_scratchpad(self, scratchpad: List[tuple]) -> str:
        """Summarize scratchpad contents for a partial answer."""
        observations = [content for label, content in scratchpad if label == "Observation"]
        if observations:
            return "\n".join(f"- {obs[:300]}" for obs in observations)
        thoughts = [content for label, content in scratchpad if label == "Thought"]
        if thoughts:
            return thoughts[-1]
        return "No information gathered yet."

    def _suggest_rollbacks(
        self, completed_actions: List[tuple]
    ) -> List[str]:
        """
        Generate rollback suggestions for previously completed actions.

        Uses ActionEngine.ROLLBACK_TEMPLATES when available, falling back
        to a generic "manual rollback needed" message.
        """
        from core.action_engine import ActionEngine

        suggestions = []
        # Process in reverse order (most recent action first)
        for action_name, action_input in reversed(completed_actions):
            template = ActionEngine.ROLLBACK_TEMPLATES.get(action_name)
            if template:
                try:
                    rollback = template.format(**action_input)
                    suggestions.append(
                        f"Undo '{action_name}': {rollback}"
                    )
                except KeyError:
                    suggestions.append(
                        f"Undo '{action_name}': manual rollback needed "
                        f"(params: {json.dumps(action_input)})"
                    )
            else:
                suggestions.append(
                    f"Undo '{action_name}': no automatic rollback available "
                    f"(params: {json.dumps(action_input)})"
                )

        if suggestions:
            logger.warning(
                "Rollback suggestions for %d completed actions:\n  %s",
                len(completed_actions),
                "\n  ".join(suggestions),
            )
        return suggestions

