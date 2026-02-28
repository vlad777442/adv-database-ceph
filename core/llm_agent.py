"""
LLM-powered agent for natural language Ceph cluster management.

Supports two modes:
1. Simple mode: Single intent classification → execute (fast, for simple queries)
2. Agent mode: ReAct loop with multi-step reasoning (for complex management tasks)
"""

import logging
import time
from typing import Dict, Any, Optional, List
import json

from core.intent_schema import (
    OperationType, Intent, OperationResult, ConversationHistory, LatencyBreakdown
)
from core.llm_provider import BaseLLMProvider
from core.tool_registry import get_all_tools, get_tool_by_name
from core.rados_client import RadosClient
from core.agent_loop import ReActAgentLoop, AgentTrace
from core.action_engine import ActionEngine, ActionPolicy, ActionRisk
from core.planner import TaskPlanner
from core.runbooks import RunbookEngine
from core.anomaly_detector import AnomalyDetector
from services.indexer import Indexer
from services.searcher import Searcher
from core.vector_store import VectorStore

logger = logging.getLogger(__name__)


class LLMAgent:
    """
    LLM-powered autonomous agent for Ceph cluster management.
    
    Core agent capabilities:
    - ReAct-style reasoning loop for complex multi-step tasks
    - Intent classification for simple queries (fast path)
    - Autonomous planning and task decomposition
    - Safety-checked cluster management actions
    - Automated runbook execution
    - Proactive anomaly detection
    - Conversational context
    """
    
    # System prompt for the LLM-based query router
    ROUTER_SYSTEM_PROMPT = (
        "You are a query router for a Ceph storage cluster management agent.\n"
        "Classify the user's query into exactly one mode:\n\n"
        "SIMPLE — The query can be answered with a single tool call.\n"
        "Examples: 'is the cluster healthy?', 'list all pools', 'show OSD status',\n"
        "'what is a CRUSH map?', 'show storage statistics'.\n\n"
        "REACT — The query requires multi-step reasoning, investigation,\n"
        "diagnosis, planning, or combining results from several tools.\n"
        "Examples: 'troubleshoot why the cluster is slow', 'diagnose degraded PGs\n"
        "and suggest fixes', 'plan a capacity expansion', 'create a maintenance report'.\n\n"
        "Respond with ONLY the single word: SIMPLE or REACT"
    )
    
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        rados_client: RadosClient,
        indexer: Indexer,
        searcher: Searcher,
        vector_store: VectorStore,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize LLM agent.
        
        Args:
            llm_provider: LLM provider instance
            rados_client: RADOS client for storage operations
            indexer: Indexer service
            searcher: Searcher service
            vector_store: Vector store
            agent_config: Agent behavior configuration
        """
        self.llm = llm_provider
        self.rados_client = rados_client
        self.indexer = indexer
        self.searcher = searcher
        self.vector_store = vector_store
        
        self.conversation = ConversationHistory()
        self.tools = get_all_tools()
        
        # Agent configuration
        config = agent_config or {}
        self.use_react_loop = config.get("use_react_loop", True)
        self.max_iterations = config.get("max_iterations", 10)
        self.dry_run = config.get("dry_run", False)
        
        # Initialize action engine with safety policy
        policy = ActionPolicy(
            auto_approve_risk_levels=[ActionRisk.LOW],
            max_actions_per_session=config.get("max_actions_per_session", 20),
            dry_run=self.dry_run,
            require_confirmation_for_writes=config.get("require_confirmation", True),
        )
        self.action_engine = ActionEngine(policy=policy)
        
        # Initialize cluster manager (lazy - loaded when needed)
        self._cluster_manager = None
        
        # Initialize task planner
        tool_names = [t["name"] for t in self.tools]
        self.planner = TaskPlanner(llm_provider, tool_names)
        
        # Initialize runbook engine
        self.runbook_engine = RunbookEngine(self._execute_tool_by_name)
        
        # Initialize anomaly detector
        self.anomaly_detector = AnomalyDetector(
            thresholds=config.get("anomaly_thresholds", {})
        )
        
        # Build the tool function registry for ReAct loop
        self._tool_functions = self._build_tool_functions()
        
        # Initialize ReAct agent loop
        self.react_loop = ReActAgentLoop(
            llm=llm_provider,
            tools=self._tool_functions,
            tool_descriptions=self.tools,
            max_iterations=self.max_iterations,
            require_confirmation=config.get("require_confirmation", True),
        )
        
        logger.info(f"Initialized LLM Agent (react={self.use_react_loop}, "
                     f"tools={len(self._tool_functions)}, dry_run={self.dry_run})")
    
    @property
    def cluster_manager(self):
        """Lazy-initialize cluster manager."""
        if self._cluster_manager is None:
            try:
                from core.cluster_manager import CephClusterManager
                self._cluster_manager = CephClusterManager()
            except Exception as e:
                logger.warning(f"Failed to initialize cluster manager: {e}")
        return self._cluster_manager
    
    def _build_tool_functions(self) -> Dict[str, Any]:
        """Build a dictionary mapping tool names to callable functions for the ReAct loop."""
        return {
            # Cluster monitoring (read-only)
            "cluster_health": lambda **kw: self._handle_cluster_health(kw),
            "diagnose_cluster": lambda **kw: self._handle_diagnose_cluster(kw),
            "osd_status": lambda **kw: self._handle_osd_status(kw),
            "pg_status": lambda **kw: self._handle_pg_status(kw),
            "capacity_prediction": lambda **kw: self._handle_capacity_prediction(kw),
            "pool_stats": lambda **kw: self._handle_pool_stats(kw),
            "performance_stats": lambda **kw: self._handle_performance_stats(kw),
            "explain_issue": lambda **kw: self._handle_explain_issue(kw),
            # Cluster management actions (write)
            "set_cluster_flag": lambda **kw: self._handle_cluster_action("set_cluster_flag", kw),
            "unset_cluster_flag": lambda **kw: self._handle_cluster_action("unset_cluster_flag", kw),
            "set_osd_out": lambda **kw: self._handle_cluster_action("set_osd_out", kw),
            "set_osd_in": lambda **kw: self._handle_cluster_action("set_osd_in", kw),
            "reweight_osd": lambda **kw: self._handle_cluster_action("reweight_osd", kw),
            "create_pool": lambda **kw: self._handle_cluster_action("create_pool", kw),
            "delete_pool": lambda **kw: self._handle_cluster_action("delete_pool", kw),
            "set_pool_param": lambda **kw: self._handle_cluster_action("set_pool_param", kw),
            "restart_osd": lambda **kw: self._handle_cluster_action("restart_osd", kw),
            "initiate_rebalance": lambda **kw: self._handle_cluster_action("initiate_rebalance", kw),
            "repair_pg": lambda **kw: self._handle_cluster_action("repair_pg", kw),
            "deep_scrub_pg": lambda **kw: self._handle_cluster_action("deep_scrub_pg", kw),
            "get_config": lambda **kw: self._handle_cluster_action("get_config", kw),
            "set_config": lambda **kw: self._handle_cluster_action("set_config", kw),
            # CRUSH map tools
            "crush_dump": lambda **kw: self._handle_cluster_action("crush_dump", kw),
            "crush_tree": lambda **kw: self._handle_cluster_action("crush_tree", kw),
            "crush_add_bucket": lambda **kw: self._handle_cluster_action("crush_add_bucket", kw),
            "crush_move": lambda **kw: self._handle_cluster_action("crush_move", kw),
            "crush_remove": lambda **kw: self._handle_cluster_action("crush_remove", kw),
            "crush_reweight": lambda **kw: self._handle_cluster_action("crush_reweight", kw),
            "crush_rule_ls": lambda **kw: self._handle_cluster_action("crush_rule_ls", kw),
            "crush_rule_dump": lambda **kw: self._handle_cluster_action("crush_rule_dump", kw),
            "crush_rule_create_simple": lambda **kw: self._handle_cluster_action("crush_rule_create_simple", kw),
            "crush_rule_rm": lambda **kw: self._handle_cluster_action("crush_rule_rm", kw),
            # OSD lifecycle tools
            "osd_safe_to_destroy": lambda **kw: self._handle_cluster_action("osd_safe_to_destroy", kw),
            "osd_ok_to_stop": lambda **kw: self._handle_cluster_action("osd_ok_to_stop", kw),
            "osd_destroy": lambda **kw: self._handle_cluster_action("osd_destroy", kw),
            "osd_purge": lambda **kw: self._handle_cluster_action("osd_purge", kw),
            "osd_down": lambda **kw: self._handle_cluster_action("osd_down", kw),
            # Auth management tools
            "auth_list": lambda **kw: self._handle_cluster_action("auth_list", kw),
            "auth_add": lambda **kw: self._handle_cluster_action("auth_add", kw),
            "auth_del": lambda **kw: self._handle_cluster_action("auth_del", kw),
            "auth_caps": lambda **kw: self._handle_cluster_action("auth_caps", kw),
            "auth_get_key": lambda **kw: self._handle_cluster_action("auth_get_key", kw),
            # Monitor management tools
            "mon_stat": lambda **kw: self._handle_cluster_action("mon_stat", kw),
            "mon_dump": lambda **kw: self._handle_cluster_action("mon_dump", kw),
            "mon_add": lambda **kw: self._handle_cluster_action("mon_add", kw),
            "mon_remove": lambda **kw: self._handle_cluster_action("mon_remove", kw),
            "quorum_status": lambda **kw: self._handle_cluster_action("quorum_status", kw),
            # MGR module tools
            "mgr_module_ls": lambda **kw: self._handle_cluster_action("mgr_module_ls", kw),
            "mgr_module_enable": lambda **kw: self._handle_cluster_action("mgr_module_enable", kw),
            "mgr_module_disable": lambda **kw: self._handle_cluster_action("mgr_module_disable", kw),
            "mgr_dump": lambda **kw: self._handle_cluster_action("mgr_dump", kw),
            "mgr_fail": lambda **kw: self._handle_cluster_action("mgr_fail", kw),
            # Erasure code profile tools
            "ec_profile_ls": lambda **kw: self._handle_cluster_action("ec_profile_ls", kw),
            "ec_profile_get": lambda **kw: self._handle_cluster_action("ec_profile_get", kw),
            "ec_profile_set": lambda **kw: self._handle_cluster_action("ec_profile_set", kw),
            "ec_profile_rm": lambda **kw: self._handle_cluster_action("ec_profile_rm", kw),
            # Pool extended tools
            "pool_get": lambda **kw: self._handle_cluster_action("pool_get", kw),
            "pool_rename": lambda **kw: self._handle_cluster_action("pool_rename", kw),
            "pool_get_quota": lambda **kw: self._handle_cluster_action("pool_get_quota", kw),
            "pool_set_quota": lambda **kw: self._handle_cluster_action("pool_set_quota", kw),
            "pool_mksnap": lambda **kw: self._handle_cluster_action("pool_mksnap", kw),
            "pool_rmsnap": lambda **kw: self._handle_cluster_action("pool_rmsnap", kw),
            "pool_application_enable": lambda **kw: self._handle_cluster_action("pool_application_enable", kw),
            # PG extended tools
            "pg_scrub": lambda **kw: self._handle_cluster_action("pg_scrub", kw),
            "pg_dump_stuck": lambda **kw: self._handle_cluster_action("pg_dump_stuck", kw),
            "pg_ls": lambda **kw: self._handle_cluster_action("pg_ls", kw),
            # OSD utilization tools
            "osd_df": lambda **kw: self._handle_cluster_action("osd_df", kw),
            "osd_reweight_by_utilization": lambda **kw: self._handle_cluster_action("osd_reweight_by_utilization", kw),
            "osd_blocklist_ls": lambda **kw: self._handle_cluster_action("osd_blocklist_ls", kw),
            "osd_blocklist_add": lambda **kw: self._handle_cluster_action("osd_blocklist_add", kw),
            # RBD (block device) tools
            "rbd_ls": lambda **kw: self._handle_cluster_action("rbd_ls", kw),
            "rbd_info": lambda **kw: self._handle_cluster_action("rbd_info", kw),
            "rbd_create": lambda **kw: self._handle_cluster_action("rbd_create", kw),
            "rbd_rm": lambda **kw: self._handle_cluster_action("rbd_rm", kw),
            "rbd_snap_ls": lambda **kw: self._handle_cluster_action("rbd_snap_ls", kw),
            "rbd_snap_create": lambda **kw: self._handle_cluster_action("rbd_snap_create", kw),
            "rbd_snap_rm": lambda **kw: self._handle_cluster_action("rbd_snap_rm", kw),
            "rbd_du": lambda **kw: self._handle_cluster_action("rbd_du", kw),
            # CephFS tools
            "fs_ls": lambda **kw: self._handle_cluster_action("fs_ls", kw),
            "fs_status": lambda **kw: self._handle_cluster_action("fs_status", kw),
            "fs_new": lambda **kw: self._handle_cluster_action("fs_new", kw),
            "fs_rm": lambda **kw: self._handle_cluster_action("fs_rm", kw),
            "mds_stat": lambda **kw: self._handle_cluster_action("mds_stat", kw),
            "fs_set": lambda **kw: self._handle_cluster_action("fs_set", kw),
            # Device health tools
            "device_ls": lambda **kw: self._handle_cluster_action("device_ls", kw),
            "device_info": lambda **kw: self._handle_cluster_action("device_info", kw),
            "device_predict_life_expectancy": lambda **kw: self._handle_cluster_action("device_predict_life_expectancy", kw),
            "device_light": lambda **kw: self._handle_cluster_action("device_light", kw),
            # Crash management tools
            "crash_ls": lambda **kw: self._handle_cluster_action("crash_ls", kw),
            "crash_info": lambda **kw: self._handle_cluster_action("crash_info", kw),
            "crash_archive": lambda **kw: self._handle_cluster_action("crash_archive", kw),
            "crash_archive_all": lambda **kw: self._handle_cluster_action("crash_archive_all", kw),
            # OSD extended tools
            "osd_dump": lambda **kw: self._handle_cluster_action("osd_dump", kw),
            "osd_find": lambda **kw: self._handle_cluster_action("osd_find", kw),
            "osd_metadata": lambda **kw: self._handle_cluster_action("osd_metadata", kw),
            "osd_perf": lambda **kw: self._handle_cluster_action("osd_perf", kw),
            "osd_pool_autoscale_status": lambda **kw: self._handle_cluster_action("osd_pool_autoscale_status", kw),
            # Config DB tools
            "config_dump": lambda **kw: self._handle_cluster_action("config_dump", kw),
            "config_get": lambda **kw: self._handle_cluster_action("config_get", kw),
            "config_set": lambda **kw: self._handle_cluster_action("config_set", kw),
            "config_show": lambda **kw: self._handle_cluster_action("config_show", kw),
            "config_log": lambda **kw: self._handle_cluster_action("config_log", kw),
            # Balancer tools
            "balancer_status": lambda **kw: self._handle_cluster_action("balancer_status", kw),
            "balancer_eval": lambda **kw: self._handle_cluster_action("balancer_eval", kw),
            "balancer_optimize": lambda **kw: self._handle_cluster_action("balancer_optimize", kw),
            # Runbooks
            "list_runbooks": lambda **kw: self._handle_list_runbooks(kw),
            "execute_runbook": lambda **kw: self._handle_execute_runbook(kw),
            "suggest_runbook": lambda **kw: self._handle_suggest_runbook(kw),
            # Planning
            "create_plan": lambda **kw: self._handle_create_plan(kw),
            "get_action_log": lambda **kw: self._handle_get_action_log(kw),
            # Documentation
            "search_docs": lambda **kw: self._handle_search_docs(kw),
            "help": lambda **kw: self._handle_help(kw),
        }
    
    def _execute_tool_by_name(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Execute a tool by name (used by runbook engine)."""
        func = self._tool_functions.get(tool_name)
        if func:
            return func(**args)
        raise ValueError(f"Unknown tool: {tool_name}")
    
    def _should_use_react(self, prompt: str) -> bool:
        """
        Use the LLM to classify whether a query needs the full ReAct
        agent loop or can be handled by a single intent→execute call.

        Returns True for complex/multi-step queries, False for simple ones.
        The classification adds one lightweight LLM round-trip (~0.3–1 s).
        """
        if not self.use_react_loop:
            return False

        try:
            response = self.llm.complete(
                prompt,
                system=self.ROUTER_SYSTEM_PROMPT,
            ).strip().upper()

            # Parse: accept "REACT" or "SIMPLE" (robust to minor noise)
            is_react = "REACT" in response and "SIMPLE" not in response
            logger.info(
                f"LLM router decision: {'REACT' if is_react else 'SIMPLE'} "
                f"(raw: {response!r})"
            )
            return is_react

        except Exception as exc:
            logger.warning(f"LLM router failed ({exc}); defaulting to SIMPLE")
            return False
    
    def process_query(self, user_prompt: str, auto_confirm: bool = False) -> OperationResult:
        """
        Main entry point for processing natural language queries.
        
        Routes between:
        - ReAct agent loop for complex management tasks
        - Simple intent→execute for straightforward queries
        
        Args:
            user_prompt: User's natural language input
            auto_confirm: Auto-confirm destructive operations (for non-interactive mode)
            
        Returns:
            OperationResult with execution outcome
        """
        logger.info(f"Processing query: '{user_prompt}'")
        start_time = time.time()
        
        try:
            # Step 0: LLM-based routing decision
            t_route_start = time.time()
            use_react = self._should_use_react(user_prompt)
            t_route_end = time.time()
            routing_ms = (t_route_end - t_route_start) * 1000

            # Route: complex queries → ReAct agent loop
            if use_react:
                logger.info(f"Routing to ReAct agent loop (router: {routing_ms:.0f} ms)")
                result = self._process_with_react(user_prompt, auto_confirm, start_time)
                if result.latency_breakdown:
                    result.latency_breakdown.routing_ms = routing_ms
                return result
            
            # Route: multi-step → sequential execution
            sub_queries = self._split_multi_step_query(user_prompt)
            if len(sub_queries) > 1:
                logger.info(f"Detected multi-step query with {len(sub_queries)} steps")
                return self._execute_multi_step(sub_queries, auto_confirm, start_time)
            
            # Route: simple → single intent classification + execute
            # Step 1: Classify intent and extract parameters
            t_llm_start = time.time()
            intent = self.classify_intent(user_prompt)
            t_llm_end = time.time()
            logger.debug(f"Classified intent: {intent.operation} (confidence: {intent.confidence})")
            
            # Step 2: Validate and confirm if needed
            if intent.requires_confirmation and not auto_confirm:
                return OperationResult(
                    success=False,
                    operation=intent.operation,
                    message="Operation requires confirmation",
                    metadata={"intent": intent.to_dict(), "requires_user_confirmation": True}
                )
            
            # Step 3: Execute operation (with internal timing)
            t_exec_start = time.time()
            result = self.execute_operation(intent)
            t_exec_end = time.time()
            
            total_ms = (t_exec_end - start_time) * 1000
            llm_ms = (t_llm_end - t_llm_start) * 1000
            exec_ms = (t_exec_end - t_exec_start) * 1000
            
            result.execution_time = total_ms / 1000.0
            
            # Build latency breakdown
            breakdown = LatencyBreakdown(
                routing_ms=routing_ms,
                llm_inference_ms=llm_ms,
                total_ms=total_ms,
            )
            if result.latency_breakdown:
                breakdown.embedding_ms = result.latency_breakdown.embedding_ms
                breakdown.vector_search_ms = result.latency_breakdown.vector_search_ms
                breakdown.rados_io_ms = result.latency_breakdown.rados_io_ms
                breakdown.response_format_ms = result.latency_breakdown.response_format_ms
            result.latency_breakdown = breakdown
            
            # Step 4: Add to conversation history
            self.conversation.add_message("user", user_prompt)
            self.conversation.add_message("assistant", result.message, {"success": result.success})
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to process query: {e}", exc_info=True)
            return OperationResult(
                success=False,
                operation=OperationType.UNKNOWN,
                error=str(e),
                message=f"Error: {str(e)}",
                execution_time=time.time() - start_time
            )
    
    def _process_with_react(self, prompt: str, auto_confirm: bool, start_time: float) -> OperationResult:
        """
        Process a complex query using the ReAct agent loop.
        
        The agent will autonomously:
        1. Reason about the query
        2. Select and execute tools
        3. Analyze results
        4. Chain additional tool calls if needed
        5. Provide a comprehensive answer
        """
        context = {}
        if self.conversation.messages:
            context["conversation_history"] = self.conversation.get_context()
        
        # Classify intent first so we can tag the result correctly
        try:
            pre_intent = self.classify_intent(prompt)
            classified_op = pre_intent.operation
        except Exception:
            classified_op = OperationType.DIAGNOSE_CLUSTER
        
        # Run the ReAct loop
        trace: AgentTrace = self.react_loop.run(
            query=prompt,
            context=context,
            auto_confirm=auto_confirm,
        )
        
        total_ms = (time.time() - start_time) * 1000
        
        # Convert trace to OperationResult
        result = OperationResult(
            success=trace.success,
            operation=classified_op,
            data={
                "agent_trace": trace.to_dict(),
                "tools_used": trace.tools_used,
                "iterations": trace.iterations,
            },
            message=trace.final_answer,
            execution_time=total_ms / 1000.0,
            latency_breakdown=LatencyBreakdown(total_ms=total_ms),
        )
        
        # Add to conversation
        self.conversation.add_message("user", prompt)
        self.conversation.add_message("assistant", trace.final_answer, {
            "success": trace.success,
            "mode": "react",
            "iterations": trace.iterations,
        })
        
        return result
    
    def _split_multi_step_query(self, prompt: str) -> List[str]:
        """
        Split a multi-step query into individual sub-queries.
        Detects connectors like 'and then', 'then', 'after that', 'also', 'and also'.
        """
        import re
        # Split on common multi-step connectors (case-insensitive)
        # Only split on connectors that indicate sequential operations
        parts = re.split(
            r'\s+(?:and\s+then|then|after\s+that|afterwards|and\s+also|also\s+(?=search|find|list|create|read|delete|show|get))\s+',
            prompt,
            flags=re.IGNORECASE
        )
        # Filter out empty strings and strip whitespace
        parts = [p.strip() for p in parts if p.strip()]
        return parts
    
    def _execute_multi_step(self, sub_queries: List[str], auto_confirm: bool, start_time: float) -> OperationResult:
        """Execute multiple sub-queries sequentially and combine results."""
        results = []
        all_success = True
        combined_messages = []
        
        for i, sub_query in enumerate(sub_queries, 1):
            logger.info(f"Executing step {i}/{len(sub_queries)}: '{sub_query}'")
            
            intent = self.classify_intent(sub_query)
            
            if intent.requires_confirmation and not auto_confirm:
                combined_messages.append(f"Step {i}: Skipped (requires confirmation) - {sub_query}")
                continue
            
            result = self.execute_operation(intent)
            results.append(result)
            
            if result.success:
                combined_messages.append(f"Step {i}: ✅ {result.message}")
            else:
                combined_messages.append(f"Step {i}: ❌ {result.error or result.message}")
                all_success = False
        
        combined_message = "\n\n".join(combined_messages)
        
        # Use the last operation type for the combined result
        last_operation = results[-1].operation if results else OperationType.UNKNOWN
        
        final_result = OperationResult(
            success=all_success,
            operation=last_operation,
            data={"steps": [r.to_dict() for r in results]},
            message=combined_message,
            execution_time=time.time() - start_time
        )
        
        # Add to conversation history
        full_prompt = " → ".join(sub_queries)
        self.conversation.add_message("user", full_prompt)
        self.conversation.add_message("assistant", combined_message, {"success": all_success})
        
        return final_result
    
    def classify_intent(self, prompt: str) -> Intent:
        """
        Classify user intent and extract parameters.
        
        Args:
            prompt: User's natural language input
            
        Returns:
            Intent object with operation and parameters
        """
        try:
            # Use LLM function calling to determine intent
            system_prompt = """You are a Ceph storage assistant. Analyze the user's request and determine which operation they want to perform."""
            
            result = self.llm.function_call(prompt, self.tools, system=system_prompt)
            
            function_name = result.get('function', 'unknown')
            parameters = result.get('parameters', {})
            reasoning = result.get('reasoning', '')
            
            # Map function name to operation type
            operation = self._map_function_to_operation(function_name)
            
            # Determine if confirmation is needed
            requires_confirmation = operation in [
                OperationType.DELETE_POOL,
                OperationType.OSD_DESTROY,
                OperationType.OSD_PURGE,
                OperationType.CRUSH_REMOVE,
                OperationType.MON_REMOVE,
            ]
            
            return Intent(
                operation=operation,
                parameters=parameters,
                confidence=0.9,
                reasoning=reasoning,
                requires_confirmation=requires_confirmation,
                original_prompt=prompt
            )
        
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return Intent(
                operation=OperationType.UNKNOWN,
                parameters={},
                confidence=0.0,
                reasoning=str(e),
                requires_confirmation=False,
                original_prompt=prompt
            )
    
    def execute_operation(self, intent: Intent) -> OperationResult:
        """
        Execute the operation specified in the intent.
        
        Args:
            intent: Intent object with operation and parameters
            
        Returns:
            OperationResult
        """
        try:
            operation = intent.operation
            params = intent.parameters
            
            logger.info(f"Executing operation: {operation}")
            
            result = None
            
            # Dispatch to appropriate handler
            # Cluster management operations
            if operation == OperationType.CLUSTER_HEALTH:
                result = self._handle_cluster_health(params)
            
            elif operation == OperationType.DIAGNOSE_CLUSTER:
                result = self._handle_diagnose_cluster(params)
            
            elif operation == OperationType.OSD_STATUS:
                result = self._handle_osd_status(params)
            
            elif operation == OperationType.PG_STATUS:
                result = self._handle_pg_status(params)
            
            elif operation == OperationType.CAPACITY_PREDICTION:
                result = self._handle_capacity_prediction(params)
            
            elif operation == OperationType.POOL_STATS:
                result = self._handle_pool_stats(params)
            
            elif operation == OperationType.PERFORMANCE_STATS:
                result = self._handle_performance_stats(params)
            
            elif operation == OperationType.EXPLAIN_ISSUE:
                result = self._handle_explain_issue(params)
            
            # Cluster management actions (write operations)
            elif operation in (
                OperationType.SET_CLUSTER_FLAG, OperationType.UNSET_CLUSTER_FLAG,
                OperationType.SET_OSD_OUT, OperationType.SET_OSD_IN,
                OperationType.REWEIGHT_OSD, OperationType.CREATE_POOL,
                OperationType.DELETE_POOL, OperationType.SET_POOL_PARAM,
                OperationType.RESTART_OSD, OperationType.INITIATE_REBALANCE,
                OperationType.REPAIR_PG, OperationType.DEEP_SCRUB_PG,
                OperationType.GET_CONFIG, OperationType.SET_CONFIG,
                # CRUSH map
                OperationType.CRUSH_DUMP, OperationType.CRUSH_TREE,
                OperationType.CRUSH_ADD_BUCKET, OperationType.CRUSH_MOVE,
                OperationType.CRUSH_REMOVE, OperationType.CRUSH_REWEIGHT,
                OperationType.CRUSH_RULE_LS, OperationType.CRUSH_RULE_DUMP,
                OperationType.CRUSH_RULE_CREATE_SIMPLE, OperationType.CRUSH_RULE_RM,
                # OSD lifecycle
                OperationType.OSD_SAFE_TO_DESTROY, OperationType.OSD_OK_TO_STOP,
                OperationType.OSD_DESTROY, OperationType.OSD_PURGE, OperationType.OSD_DOWN,
                # Auth
                OperationType.AUTH_LIST, OperationType.AUTH_ADD,
                OperationType.AUTH_DEL, OperationType.AUTH_CAPS, OperationType.AUTH_GET_KEY,
                # Monitor
                OperationType.MON_STAT, OperationType.MON_DUMP,
                OperationType.MON_ADD, OperationType.MON_REMOVE, OperationType.QUORUM_STATUS,
                # MGR
                OperationType.MGR_MODULE_LS, OperationType.MGR_MODULE_ENABLE,
                OperationType.MGR_MODULE_DISABLE, OperationType.MGR_DUMP, OperationType.MGR_FAIL,
                # Erasure code profiles
                OperationType.EC_PROFILE_LS, OperationType.EC_PROFILE_GET,
                OperationType.EC_PROFILE_SET, OperationType.EC_PROFILE_RM,
                # Pool extended
                OperationType.POOL_GET, OperationType.POOL_RENAME,
                OperationType.POOL_GET_QUOTA, OperationType.POOL_SET_QUOTA,
                OperationType.POOL_MKSNAP, OperationType.POOL_RMSNAP,
                OperationType.POOL_APPLICATION_ENABLE,
                # PG extended
                OperationType.PG_SCRUB, OperationType.PG_DUMP_STUCK, OperationType.PG_LS,
                # OSD utilization
                OperationType.OSD_DF, OperationType.OSD_REWEIGHT_BY_UTILIZATION,
                OperationType.OSD_BLOCKLIST_LS, OperationType.OSD_BLOCKLIST_ADD,
                # RBD
                OperationType.RBD_LS, OperationType.RBD_INFO, OperationType.RBD_CREATE,
                OperationType.RBD_RM, OperationType.RBD_SNAP_LS, OperationType.RBD_SNAP_CREATE,
                OperationType.RBD_SNAP_RM, OperationType.RBD_DU,
                # CephFS
                OperationType.FS_LS, OperationType.FS_STATUS, OperationType.FS_NEW,
                OperationType.FS_RM, OperationType.MDS_STAT, OperationType.FS_SET,
                # Device health
                OperationType.DEVICE_LS, OperationType.DEVICE_INFO,
                OperationType.DEVICE_PREDICT_LIFE_EXPECTANCY, OperationType.DEVICE_LIGHT,
                # Crash management
                OperationType.CRASH_LS, OperationType.CRASH_INFO,
                OperationType.CRASH_ARCHIVE, OperationType.CRASH_ARCHIVE_ALL,
                # OSD extended
                OperationType.OSD_DUMP, OperationType.OSD_FIND, OperationType.OSD_METADATA,
                OperationType.OSD_PERF, OperationType.OSD_POOL_AUTOSCALE_STATUS,
                # Config DB
                OperationType.CONFIG_DUMP, OperationType.CONFIG_GET, OperationType.CONFIG_SET,
                OperationType.CONFIG_SHOW, OperationType.CONFIG_LOG,
                # Balancer
                OperationType.BALANCER_STATUS, OperationType.BALANCER_EVAL,
                OperationType.BALANCER_OPTIMIZE,
            ):
                result = self._handle_cluster_action(operation.value, params)
            
            # Runbook operations
            elif operation == OperationType.LIST_RUNBOOKS:
                result = self._handle_list_runbooks(params)
            
            elif operation == OperationType.EXECUTE_RUNBOOK:
                result = self._handle_execute_runbook(params)
            
            elif operation == OperationType.SUGGEST_RUNBOOK:
                result = self._handle_suggest_runbook(params)
            
            # Planning operations
            elif operation == OperationType.CREATE_PLAN:
                result = self._handle_create_plan(params)
            
            elif operation == OperationType.GET_ACTION_LOG:
                result = self._handle_get_action_log(params)
            
            # Documentation operations
            elif operation == OperationType.SEARCH_DOCS:
                result = self._handle_search_docs(params)
            
            elif operation == OperationType.HELP:
                result = self._handle_help(params)
            
            else:
                result = OperationResult(
                    success=False,
                    operation=operation,
                    error="Unknown or unsupported operation",
                    message=f"Operation '{operation}' is not supported"
                )
            
            # Inject intent metadata for evaluation tracking
            if result is not None:
                if result.metadata is None:
                    result.metadata = {}
                result.metadata['intent'] = intent.to_dict()
            
            return result
        
        except Exception as e:
            logger.error(f"Operation execution failed: {e}", exc_info=True)
            return OperationResult(
                success=False,
                operation=intent.operation,
                error=str(e),
                message=f"Error executing {intent.operation}: {str(e)}",
                metadata={"intent": intent.to_dict()}
            )
    
    def generate_response(self, result: OperationResult) -> str:
        """
        Generate natural language response from operation result.
        
        Args:
            result: OperationResult
            
        Returns:
            Natural language response string
        """
        if result.message:
            return result.message
        
        # Use LLM to generate friendly response
        try:
            prompt = f"""Generate a friendly, concise response for this operation result:
Operation: {result.operation}
Success: {result.success}
Data: {json.dumps(result.data, indent=2) if result.data else 'None'}
Error: {result.error or 'None'}

Generate a 1-2 sentence natural language response."""
            
            response = self.llm.complete(prompt)
            return response
        
        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            return result.message or ("Operation completed successfully" if result.success else "Operation failed")
    
    def _map_function_to_operation(self, function_name: str) -> OperationType:
        """Map function name to OperationType."""
        mapping = {
            # Cluster monitoring
            "cluster_health": OperationType.CLUSTER_HEALTH,
            "diagnose_cluster": OperationType.DIAGNOSE_CLUSTER,
            "osd_status": OperationType.OSD_STATUS,
            "pg_status": OperationType.PG_STATUS,
            "capacity_prediction": OperationType.CAPACITY_PREDICTION,
            "pool_stats": OperationType.POOL_STATS,
            "performance_stats": OperationType.PERFORMANCE_STATS,
            "explain_issue": OperationType.EXPLAIN_ISSUE,
            # Cluster management actions
            "set_cluster_flag": OperationType.SET_CLUSTER_FLAG,
            "unset_cluster_flag": OperationType.UNSET_CLUSTER_FLAG,
            "set_osd_out": OperationType.SET_OSD_OUT,
            "set_osd_in": OperationType.SET_OSD_IN,
            "reweight_osd": OperationType.REWEIGHT_OSD,
            "create_pool": OperationType.CREATE_POOL,
            "delete_pool": OperationType.DELETE_POOL,
            "set_pool_param": OperationType.SET_POOL_PARAM,
            "restart_osd": OperationType.RESTART_OSD,
            "initiate_rebalance": OperationType.INITIATE_REBALANCE,
            "repair_pg": OperationType.REPAIR_PG,
            "deep_scrub_pg": OperationType.DEEP_SCRUB_PG,
            "get_config": OperationType.GET_CONFIG,
            "set_config": OperationType.SET_CONFIG,
            # CRUSH map
            "crush_dump": OperationType.CRUSH_DUMP,
            "crush_tree": OperationType.CRUSH_TREE,
            "crush_add_bucket": OperationType.CRUSH_ADD_BUCKET,
            "crush_move": OperationType.CRUSH_MOVE,
            "crush_remove": OperationType.CRUSH_REMOVE,
            "crush_reweight": OperationType.CRUSH_REWEIGHT,
            "crush_rule_ls": OperationType.CRUSH_RULE_LS,
            "crush_rule_dump": OperationType.CRUSH_RULE_DUMP,
            "crush_rule_create_simple": OperationType.CRUSH_RULE_CREATE_SIMPLE,
            "crush_rule_rm": OperationType.CRUSH_RULE_RM,
            # OSD lifecycle
            "osd_safe_to_destroy": OperationType.OSD_SAFE_TO_DESTROY,
            "osd_ok_to_stop": OperationType.OSD_OK_TO_STOP,
            "osd_destroy": OperationType.OSD_DESTROY,
            "osd_purge": OperationType.OSD_PURGE,
            "osd_down": OperationType.OSD_DOWN,
            # Auth management
            "auth_list": OperationType.AUTH_LIST,
            "auth_add": OperationType.AUTH_ADD,
            "auth_del": OperationType.AUTH_DEL,
            "auth_caps": OperationType.AUTH_CAPS,
            "auth_get_key": OperationType.AUTH_GET_KEY,
            # Monitor management
            "mon_stat": OperationType.MON_STAT,
            "mon_dump": OperationType.MON_DUMP,
            "mon_add": OperationType.MON_ADD,
            "mon_remove": OperationType.MON_REMOVE,
            "quorum_status": OperationType.QUORUM_STATUS,
            # MGR modules
            "mgr_module_ls": OperationType.MGR_MODULE_LS,
            "mgr_module_enable": OperationType.MGR_MODULE_ENABLE,
            "mgr_module_disable": OperationType.MGR_MODULE_DISABLE,
            "mgr_dump": OperationType.MGR_DUMP,
            "mgr_fail": OperationType.MGR_FAIL,
            # Erasure code profiles
            "ec_profile_ls": OperationType.EC_PROFILE_LS,
            "ec_profile_get": OperationType.EC_PROFILE_GET,
            "ec_profile_set": OperationType.EC_PROFILE_SET,
            "ec_profile_rm": OperationType.EC_PROFILE_RM,
            # Pool extended
            "pool_get": OperationType.POOL_GET,
            "pool_rename": OperationType.POOL_RENAME,
            "pool_get_quota": OperationType.POOL_GET_QUOTA,
            "pool_set_quota": OperationType.POOL_SET_QUOTA,
            "pool_mksnap": OperationType.POOL_MKSNAP,
            "pool_rmsnap": OperationType.POOL_RMSNAP,
            "pool_application_enable": OperationType.POOL_APPLICATION_ENABLE,
            # PG extended
            "pg_scrub": OperationType.PG_SCRUB,
            "pg_dump_stuck": OperationType.PG_DUMP_STUCK,
            "pg_ls": OperationType.PG_LS,
            # OSD utilization
            "osd_df": OperationType.OSD_DF,
            "osd_reweight_by_utilization": OperationType.OSD_REWEIGHT_BY_UTILIZATION,
            "osd_blocklist_ls": OperationType.OSD_BLOCKLIST_LS,
            "osd_blocklist_add": OperationType.OSD_BLOCKLIST_ADD,
            # RBD
            "rbd_ls": OperationType.RBD_LS,
            "rbd_info": OperationType.RBD_INFO,
            "rbd_create": OperationType.RBD_CREATE,
            "rbd_rm": OperationType.RBD_RM,
            "rbd_snap_ls": OperationType.RBD_SNAP_LS,
            "rbd_snap_create": OperationType.RBD_SNAP_CREATE,
            "rbd_snap_rm": OperationType.RBD_SNAP_RM,
            "rbd_du": OperationType.RBD_DU,
            # CephFS
            "fs_ls": OperationType.FS_LS,
            "fs_status": OperationType.FS_STATUS,
            "fs_new": OperationType.FS_NEW,
            "fs_rm": OperationType.FS_RM,
            "mds_stat": OperationType.MDS_STAT,
            "fs_set": OperationType.FS_SET,
            # Device health
            "device_ls": OperationType.DEVICE_LS,
            "device_info": OperationType.DEVICE_INFO,
            "device_predict_life_expectancy": OperationType.DEVICE_PREDICT_LIFE_EXPECTANCY,
            "device_light": OperationType.DEVICE_LIGHT,
            # Crash
            "crash_ls": OperationType.CRASH_LS,
            "crash_info": OperationType.CRASH_INFO,
            "crash_archive": OperationType.CRASH_ARCHIVE,
            "crash_archive_all": OperationType.CRASH_ARCHIVE_ALL,
            # OSD extended
            "osd_dump": OperationType.OSD_DUMP,
            "osd_find": OperationType.OSD_FIND,
            "osd_metadata": OperationType.OSD_METADATA,
            "osd_perf": OperationType.OSD_PERF,
            "osd_pool_autoscale_status": OperationType.OSD_POOL_AUTOSCALE_STATUS,
            # Config DB
            "config_dump": OperationType.CONFIG_DUMP,
            "config_get": OperationType.CONFIG_GET,
            "config_set": OperationType.CONFIG_SET,
            "config_show": OperationType.CONFIG_SHOW,
            "config_log": OperationType.CONFIG_LOG,
            # Balancer
            "balancer_status": OperationType.BALANCER_STATUS,
            "balancer_eval": OperationType.BALANCER_EVAL,
            "balancer_optimize": OperationType.BALANCER_OPTIMIZE,
            # Runbooks
            "list_runbooks": OperationType.LIST_RUNBOOKS,
            "execute_runbook": OperationType.EXECUTE_RUNBOOK,
            "suggest_runbook": OperationType.SUGGEST_RUNBOOK,
            # Planning
            "create_plan": OperationType.CREATE_PLAN,
            "get_action_log": OperationType.GET_ACTION_LOG,
            # Documentation
            "search_docs": OperationType.SEARCH_DOCS,
            "help": OperationType.HELP,
        }
        return mapping.get(function_name, OperationType.UNKNOWN)
    
    # ============ Cluster Management Handlers ============
    
    def _handle_cluster_health(self, params: Dict[str, Any]) -> OperationResult:
        """Handle cluster health check."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            detail = params.get('detail', True)
            health = manager.get_cluster_health(detail=detail)
            
            message = f"🏥 Cluster Health: {health.status}\n\n"
            message += health.summary + "\n"
            
            if health.details:
                message += "\nHealth Checks:\n"
                for detail in health.details[:5]:
                    message += f"  • {detail}\n"
            
            return OperationResult(
                success=True,
                operation=OperationType.CLUSTER_HEALTH,
                data={"status": health.status, "checks": health.checks},
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.CLUSTER_HEALTH,
                error=str(e),
                message=f"Failed to get cluster health: {e}"
            )
    
    def _handle_diagnose_cluster(self, params: Dict[str, Any]) -> OperationResult:
        """Handle cluster diagnosis."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            diagnosis = manager.diagnose_cluster()
            
            message = f"🔍 Cluster Diagnosis Report\n"
            message += f"Overall Status: {diagnosis['overall_status']}\n\n"
            
            if diagnosis['issues']:
                message += "❌ Issues:\n"
                for issue in diagnosis['issues']:
                    message += f"  • {issue}\n"
            
            if diagnosis['warnings']:
                message += "\n⚠️  Warnings:\n"
                for warning in diagnosis['warnings']:
                    message += f"  • {warning}\n"
            
            if diagnosis['recommendations']:
                message += "\n💡 Recommendations:\n"
                for rec in diagnosis['recommendations']:
                    message += f"  • {rec}\n"
            
            if not diagnosis['issues'] and not diagnosis['warnings']:
                message += "✅ No issues detected. Cluster is healthy.\n"
            
            return OperationResult(
                success=True,
                operation=OperationType.DIAGNOSE_CLUSTER,
                data=diagnosis,
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.DIAGNOSE_CLUSTER,
                error=str(e),
                message=f"Failed to diagnose cluster: {e}"
            )
    
    def _handle_osd_status(self, params: Dict[str, Any]) -> OperationResult:
        """Handle OSD status query."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            osds = manager.get_osd_status()
            
            up_count = len([o for o in osds if o.status == "up"])
            total_count = len(osds)
            
            message = f"💾 OSD Status: {up_count}/{total_count} up\n\n"
            
            for osd in osds[:10]:  # Limit display
                status_icon = "🟢" if osd.status == "up" else "🔴"
                message += f"{status_icon} OSD.{osd.osd_id} ({osd.host}): {osd.status}"
                if osd.utilization > 0:
                    message += f" | {osd.utilization:.1f}% used"
                message += "\n"
            
            if len(osds) > 10:
                message += f"... and {len(osds) - 10} more OSDs\n"
            
            return OperationResult(
                success=True,
                operation=OperationType.OSD_STATUS,
                data=[{"osd_id": o.osd_id, "host": o.host, "status": o.status, 
                       "utilization": o.utilization} for o in osds],
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.OSD_STATUS,
                error=str(e),
                message=f"Failed to get OSD status: {e}"
            )
    
    def _handle_pg_status(self, params: Dict[str, Any]) -> OperationResult:
        """Handle PG status query."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            pg_id = params.get('pg_id')
            result = manager.explain_pg_state(pg_id)
            
            if pg_id:
                message = f"📊 PG {pg_id} Status:\n"
                message += f"State: {result.get('state', 'unknown')}\n"
                message += f"Acting OSDs: {result.get('acting', [])}\n"
            else:
                message = f"📊 Placement Groups Summary\n"
                message += f"Total PGs: {result.get('total_pgs', 0)}\n"
                message += f"Healthy (active+clean): {result.get('healthy_pgs', 0)}\n"
                message += f"Problematic: {result.get('problematic_pgs', 0)}\n\n"
                
                states = result.get('states', {})
                for state, info in states.items():
                    if info.get('count', 0) > 0:
                        message += f"  {state}: {info['count']} - {info['meaning']}\n"
            
            return OperationResult(
                success=True,
                operation=OperationType.PG_STATUS,
                data=result,
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.PG_STATUS,
                error=str(e),
                message=f"Failed to get PG status: {e}"
            )
    
    def _handle_capacity_prediction(self, params: Dict[str, Any]) -> OperationResult:
        """Handle capacity prediction."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            days = params.get('days', 30)
            prediction = manager.predict_capacity(days=days)
            
            if "error" in prediction:
                return OperationResult(
                    success=False,
                    operation=OperationType.CAPACITY_PREDICTION,
                    error=prediction['error'],
                    message=f"Failed to predict capacity: {prediction['error']}"
                )
            
            current = prediction['current']
            proj = prediction['projection']
            
            message = f"📈 Capacity Analysis\n\n"
            message += f"Current Usage:\n"
            message += f"  • Used: {current['used_gb']:.1f} GB / {current['total_gb']:.1f} GB\n"
            message += f"  • Utilization: {current['utilization_percent']:.1f}%\n"
            message += f"  • Available: {current['available_gb']:.1f} GB\n\n"
            
            message += f"Projection ({days} days):\n"
            message += f"  • Projected Usage: {proj['projected_utilization']:.1f}%\n"
            if proj['days_until_80_percent']:
                message += f"  • Days until 80%: {proj['days_until_80_percent']}\n"
            if proj['days_until_full']:
                message += f"  • Days until full: {proj['days_until_full']}\n"
            
            message += f"\n💡 {prediction['recommendation']}"
            
            return OperationResult(
                success=True,
                operation=OperationType.CAPACITY_PREDICTION,
                data=prediction,
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.CAPACITY_PREDICTION,
                error=str(e),
                message=f"Failed to predict capacity: {e}"
            )
    
    def _handle_pool_stats(self, params: Dict[str, Any]) -> OperationResult:
        """Handle pool statistics query."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            pools = manager.get_pool_stats()
            
            message = "🏊 Pool Statistics\n\n"
            for pool in pools:
                used_mb = pool.get('used_bytes', 0) / (1024 * 1024)
                message += f"📁 {pool['name']}:\n"
                message += f"   Objects: {pool.get('objects', 0)}\n"
                message += f"   Used: {used_mb:.2f} MB\n"
                message += f"   Utilization: {pool.get('percent_used', 0):.2f}%\n\n"
            
            return OperationResult(
                success=True,
                operation=OperationType.POOL_STATS,
                data=pools,
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.POOL_STATS,
                error=str(e),
                message=f"Failed to get pool stats: {e}"
            )
    
    def _handle_performance_stats(self, params: Dict[str, Any]) -> OperationResult:
        """Handle performance statistics query."""
        try:
            from core.cluster_manager import CephClusterManager
            manager = CephClusterManager()
            
            stats = manager.get_performance_stats()
            
            if "error" in stats:
                return OperationResult(
                    success=False,
                    operation=OperationType.PERFORMANCE_STATS,
                    error=stats['error'],
                    message=f"Failed to get performance stats: {stats['error']}"
                )
            
            io = stats.get('io', {})
            
            message = "⚡ Performance Statistics\n\n"
            message += "I/O Operations:\n"
            message += f"  • Read:  {io.get('read_op_per_sec', 0):.0f} ops/sec "
            message += f"({io.get('read_bytes_sec', 0) / 1024 / 1024:.2f} MB/s)\n"
            message += f"  • Write: {io.get('write_op_per_sec', 0):.0f} ops/sec "
            message += f"({io.get('write_bytes_sec', 0) / 1024 / 1024:.2f} MB/s)\n\n"
            
            recovery = stats.get('recovery', {})
            if recovery.get('recovering_objects_per_sec', 0) > 0:
                message += "Recovery:\n"
                message += f"  • Objects: {recovery['recovering_objects_per_sec']:.0f}/sec\n"
                message += f"  • Throughput: {recovery['recovering_bytes_per_sec'] / 1024 / 1024:.2f} MB/s\n"
            
            message += f"\nTotal Objects: {stats.get('objects', {}).get('total', 0)}"
            
            return OperationResult(
                success=True,
                operation=OperationType.PERFORMANCE_STATS,
                data=stats,
                message=message
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.PERFORMANCE_STATS,
                error=str(e),
                message=f"Failed to get performance stats: {e}"
            )
    
    def _handle_explain_issue(self, params: Dict[str, Any]) -> OperationResult:
        """Handle issue explanation using RAG."""
        topic = params.get('topic', '')
        
        # Use RAG to find relevant documentation
        try:
            if hasattr(self, 'rag_system') and self.rag_system:
                result = self.rag_system.answer_question(topic, self.llm)
                message = result['answer']
                
                if result['sources']:
                    message += "\n\n📚 Sources:\n"
                    for src in result['sources'][:3]:
                        message += f"  • {src['title']} ({src['section']})\n"
                
                return OperationResult(
                    success=True,
                    operation=OperationType.EXPLAIN_ISSUE,
                    data=result,
                    message=message
                )
        except Exception as e:
            logger.warning(f"RAG lookup failed: {e}")
        
        # Fallback to LLM-only response
        prompt = f"""As a Ceph storage expert, explain: {topic}

Provide a clear, technical explanation that would help a storage administrator understand this issue or concept."""
        
        response = self.llm.complete(prompt, system="You are an expert Ceph storage consultant.")
        
        return OperationResult(
            success=True,
            operation=OperationType.EXPLAIN_ISSUE,
            data={"topic": topic},
            message=response
        )
    
    # ============ Cluster Management Action Handlers ============
    
    def _handle_cluster_action(self, action_name: str, params: Dict[str, Any]) -> OperationResult:
        """Handle cluster management write operations via the action engine."""
        # Resolve the correct OperationType for this action
        op_type = self._map_function_to_operation(action_name)

        try:
            if self.cluster_manager is None:
                return OperationResult(
                    success=False,
                    operation=op_type,
                    error="Cluster manager not available",
                    message="Cannot perform cluster management: cluster manager is not initialized"
                )
            
            # Get the method from cluster manager
            method = getattr(self.cluster_manager, action_name, None)
            if method is None:
                return OperationResult(
                    success=False,
                    operation=op_type,
                    error=f"Unknown action: {action_name}",
                    message=f"Action '{action_name}' is not supported"
                )
            
            # Execute through the action engine (with safety checks)
            record = self.action_engine.execute_action(
                action_name=action_name,
                parameters=params,
                executor=method,
                reason=f"User requested {action_name}",
            )
            
            if record.status.value == "denied":
                return OperationResult(
                    success=False,
                    operation=op_type,
                    error=record.error,
                    message=f"⚠️ Action denied: {record.error}",
                    metadata={"action_record": record.to_dict()}
                )
            
            if record.status.value == "completed":
                result_data = record.result
                message = result_data.get("message", f"Action {action_name} completed") if isinstance(result_data, dict) else str(result_data)
                
                rollback_info = ""
                if record.rollback_command:
                    rollback_info = f"\n↩️ Rollback: {record.rollback_command}"
                
                return OperationResult(
                    success=True,
                    operation=op_type,
                    data=record.to_dict(),
                    message=f"✅ {message}{rollback_info}",
                    metadata={"action_record": record.to_dict()}
                )
            else:
                return OperationResult(
                    success=False,
                    operation=op_type,
                    error=record.error,
                    message=f"❌ Action failed: {record.error}",
                    metadata={"action_record": record.to_dict()}
                )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=op_type,
                error=str(e),
                message=f"Failed to execute {action_name}: {e}"
            )
    
    # ============ Runbook Handlers ============
    
    def _handle_list_runbooks(self, params: Dict[str, Any]) -> OperationResult:
        """List available runbooks."""
        runbooks = self.runbook_engine.get_available_runbooks()
        
        message = "📋 **Available Runbooks:**\n\n"
        for rb in runbooks:
            risk_icon = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(rb["risk"], "⬜")
            message += f"  {risk_icon} **{rb['name']}** - {rb['title']}\n"
            message += f"     {rb['description']} ({rb['steps']} steps)\n\n"
        
        return OperationResult(
            success=True,
            operation=OperationType.LIST_RUNBOOKS,
            data=runbooks,
            message=message
        )
    
    def _handle_execute_runbook(self, params: Dict[str, Any]) -> OperationResult:
        """Execute an automated runbook."""
        runbook_name = params.get("runbook_name", "")
        rb_params = params.get("params", {})
        dry_run = params.get("dry_run", False)
        
        result = self.runbook_engine.execute_runbook(
            runbook_name=runbook_name,
            params=rb_params,
            dry_run=dry_run,
        )
        
        message = self.runbook_engine.format_runbook_result(result)
        
        return OperationResult(
            success=result.status.value == "completed",
            operation=OperationType.EXECUTE_RUNBOOK,
            data=result.to_dict(),
            message=message
        )
    
    def _handle_suggest_runbook(self, params: Dict[str, Any]) -> OperationResult:
        """Suggest a runbook for an issue."""
        issue = params.get("issue_description", "")
        
        suggested = self.runbook_engine.suggest_runbook(issue)
        
        if suggested:
            rb_info = self.runbook_engine.runbooks.get(suggested, {})
            message = (
                f"💡 Suggested runbook: **{rb_info.get('name', suggested)}**\n"
                f"   {rb_info.get('description', '')}\n"
                f"   Risk: {rb_info.get('risk', 'unknown')}\n\n"
                f"Run with: `execute_runbook {suggested}`"
            )
            return OperationResult(
                success=True,
                operation=OperationType.SUGGEST_RUNBOOK,
                data={"runbook": suggested, "info": rb_info.get("description", "")},
                message=message
            )
        
        return OperationResult(
            success=True,
            operation=OperationType.SUGGEST_RUNBOOK,
            message=f"No matching runbook found for: '{issue}'. Use 'list runbooks' to see available options."
        )
    
    # ============ Planning Handlers ============
    
    def _handle_create_plan(self, params: Dict[str, Any]) -> OperationResult:
        """Create an execution plan for a complex task."""
        goal = params.get("goal", "")
        
        plan = self.planner.create_plan(goal)
        message = self.planner.format_plan(plan)
        
        return OperationResult(
            success=True,
            operation=OperationType.CREATE_PLAN,
            data=plan.to_dict(),
            message=message
        )
    
    def _handle_get_action_log(self, params: Dict[str, Any]) -> OperationResult:
        """Get the action audit log."""
        summary = self.action_engine.get_session_summary()
        log = self.action_engine.get_audit_log()
        
        message = f"📝 **Session Action Log**\n\n"
        message += f"Total actions: {summary['total_actions']}\n"
        message += f"Executed: {summary['session_actions_executed']}\n"
        
        if log:
            message += "\nRecent actions:\n"
            for entry in log[-10:]:
                status_icon = "✅" if entry["status"] == "completed" else "❌"
                message += f"  {status_icon} {entry['action_name']} ({entry['risk_level']}) - {entry['status']}\n"
        
        return OperationResult(
            success=True,
            operation=OperationType.GET_ACTION_LOG,
            data={"summary": summary, "log": log},
            message=message
        )
    
    # ============ Anomaly Detection ============
    
    def scan_anomalies(self) -> OperationResult:
        """Run anomaly detection scan on the cluster."""
        try:
            if self.cluster_manager is None:
                return OperationResult(
                    success=False,
                    operation=OperationType.SCAN_ANOMALIES,
                    error="Cluster manager not available",
                    message="Cannot scan: cluster manager not initialized"
                )
            
            # Get cluster state snapshot
            state = self.cluster_manager.get_cluster_state_snapshot()
            
            # Run anomaly detection
            report = self.anomaly_detector.analyze(state)
            message = self.anomaly_detector.format_report(report)
            
            return OperationResult(
                success=True,
                operation=OperationType.SCAN_ANOMALIES,
                data=report.to_dict(),
                message=message,
            )
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.SCAN_ANOMALIES,
                error=str(e),
                message=f"Anomaly scan failed: {e}"
            )
    
    # ============ Documentation/RAG Handlers ============
    
    def _handle_search_docs(self, params: Dict[str, Any]) -> OperationResult:
        """Handle documentation search using RAG."""
        query = params.get('query', '')
        top_k = params.get('top_k', 3)
        
        try:
            if hasattr(self, 'rag_system') and self.rag_system:
                results = self.rag_system.search(query, top_k=top_k)
                
                if results:
                    message = f"📚 Found {len(results)} relevant documentation entries:\n\n"
                    for i, result in enumerate(results, 1):
                        doc = result.document
                        message += f"{i}. **{doc.title}** ({doc.section})\n"
                        message += f"   {doc.content[:200]}...\n\n"
                    
                    # Generate a summary answer
                    context = self.rag_system.get_context_for_query(query)
                    answer_prompt = f"""Based on this documentation context:
{context}

Answer this question concisely: {query}"""
                    
                    answer = self.llm.complete(answer_prompt, system="You are a Ceph documentation expert. Provide accurate, helpful answers based on the provided documentation.")
                    
                    message = f"💡 {answer}\n\n" + message
                    
                    return OperationResult(
                        success=True,
                        operation=OperationType.SEARCH_DOCS,
                        data=[{"title": r.document.title, "score": r.score} for r in results],
                        message=message
                    )
        except Exception as e:
            logger.warning(f"RAG search failed: {e}")
        
        # Fallback: use LLM knowledge
        prompt = f"""As a Ceph storage expert, answer this question about Ceph: {query}

Provide a helpful, accurate answer."""
        
        response = self.llm.complete(prompt, system="You are an expert Ceph documentation assistant.")
        
        return OperationResult(
            success=True,
            operation=OperationType.SEARCH_DOCS,
            data={"query": query, "source": "llm_knowledge"},
            message=f"💡 {response}"
        )
    
    def _handle_help(self, params: Dict[str, Any]) -> OperationResult:
        """Handle help request."""
        help_text = """🤖 **Ceph AI Agent - Autonomous Cluster Management**

**Object Operations:**
• Search: "find files about kubernetes" or "search for config files"
• Read/Write: "show test.txt", "create hello.txt with Hello World"
• Manage: "list all files", "delete old_file.txt"

**Cluster Monitoring:**
• Health: "is the cluster healthy?" or "check cluster status"
• Diagnostics: "diagnose cluster" or "what's wrong?"
• OSD/PG: "show OSD status", "any degraded PGs?"
• Capacity: "when will storage be full?", "capacity prediction"
• Performance: "show IOPS", "current throughput?"

**Cluster Management (Agent Actions):**
• Flags: "set noout flag", "pause rebalancing"
• OSD mgmt: "mark OSD 5 out", "reweight OSD 3 to 0.8"
• Pool mgmt: "create pool mydata", "set pool size to 2"
• Repair: "repair PG 1.2a", "deep scrub PG 3.1"
• Config: "get osd_recovery_max_active", "set config..."

**Automated Runbooks:**
• List: "show available runbooks"
• Execute: "run performance investigation runbook"
• Suggest: "suggest a fix for degraded PGs"

**AI Agent Features:**
• Troubleshooting: "troubleshoot slow performance" (multi-step analysis)
• Planning: "create a plan to add new storage"
• Root cause: "why are my PGs degraded?"
• Optimization: "how can I optimize my cluster?"
• Anomaly scan: "scan for anomalies"

**Tips:**
• Complex questions trigger the autonomous agent (multi-step reasoning)
• Simple questions use fast intent classification
• Destructive actions require confirmation
• Type 'exit' to quit
"""
        
        return OperationResult(
            success=True,
            operation=OperationType.HELP,
            data={"commands": ["search", "read", "create", "delete", "health", 
                               "diagnose", "troubleshoot", "runbook", "plan", "help"]},
            message=help_text
        )
    
    def set_rag_system(self, rag_system):
        """Set the RAG system for documentation queries."""
        self.rag_system = rag_system
        logger.info("RAG system configured for agent")
    
    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation.clear()
