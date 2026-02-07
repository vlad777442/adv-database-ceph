"""
LLM-powered agent for natural language Ceph operations.
"""

import logging
import time
from typing import Dict, Any, Optional, List
import json

from core.intent_schema import (
    OperationType, Intent, OperationResult, ConversationHistory
)
from core.llm_provider import BaseLLMProvider
from core.tool_registry import get_all_tools, get_tool_by_name
from core.rados_client import RadosClient
from services.indexer import Indexer
from services.searcher import Searcher
from core.vector_store import VectorStore

logger = logging.getLogger(__name__)


class LLMAgent:
    """
    LLM-powered agent for natural language Ceph storage operations.
    
    Capabilities:
    - Intent classification from natural language
    - Parameter extraction
    - Command execution with validation
    - Natural language response generation
    - Conversational context
    """
    
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        rados_client: RadosClient,
        indexer: Indexer,
        searcher: Searcher,
        vector_store: VectorStore
    ):
        """
        Initialize LLM agent.
        
        Args:
            llm_provider: LLM provider instance
            rados_client: RADOS client for storage operations
            indexer: Indexer service
            searcher: Searcher service
            vector_store: Vector store
        """
        self.llm = llm_provider
        self.rados_client = rados_client
        self.indexer = indexer
        self.searcher = searcher
        self.vector_store = vector_store
        
        self.conversation = ConversationHistory()
        self.tools = get_all_tools()
        
        logger.info("Initialized LLM Agent")
    
    def process_query(self, user_prompt: str, auto_confirm: bool = False) -> OperationResult:
        """
        Main entry point for processing natural language queries.
        Supports multi-step queries (e.g., "create X and then search for Y").
        
        Args:
            user_prompt: User's natural language input
            auto_confirm: Auto-confirm destructive operations (for non-interactive mode)
            
        Returns:
            OperationResult with execution outcome
        """
        logger.info(f"Processing query: '{user_prompt}'")
        start_time = time.time()
        
        try:
            # Check if this is a multi-step query
            sub_queries = self._split_multi_step_query(user_prompt)
            
            if len(sub_queries) > 1:
                logger.info(f"Detected multi-step query with {len(sub_queries)} steps")
                return self._execute_multi_step(sub_queries, auto_confirm, start_time)
            
            # Single-step query
            # Step 1: Classify intent and extract parameters
            intent = self.classify_intent(user_prompt)
            logger.debug(f"Classified intent: {intent.operation} (confidence: {intent.confidence})")
            
            # Step 2: Validate and confirm if needed
            if intent.requires_confirmation and not auto_confirm:
                return OperationResult(
                    success=False,
                    operation=intent.operation,
                    message="Operation requires confirmation",
                    metadata={"intent": intent.to_dict(), "requires_user_confirmation": True}
                )
            
            # Step 3: Execute operation
            result = self.execute_operation(intent)
            result.execution_time = time.time() - start_time
            
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
                OperationType.DELETE_OBJECT,
                OperationType.BULK_DELETE,
                OperationType.UPDATE_OBJECT
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
            if operation == OperationType.SEMANTIC_SEARCH:
                result = self._handle_search(params)
            
            elif operation == OperationType.READ_OBJECT:
                result = self._handle_read(params)
            
            elif operation == OperationType.LIST_OBJECTS:
                result = self._handle_list(params)
            
            elif operation == OperationType.CREATE_OBJECT:
                result = self._handle_create(params)
            
            elif operation == OperationType.UPDATE_OBJECT:
                result = self._handle_update(params)
            
            elif operation == OperationType.DELETE_OBJECT:
                result = self._handle_delete(params)
            
            elif operation == OperationType.GET_STATS:
                result = self._handle_stats(params)
            
            elif operation == OperationType.INDEX_OBJECT:
                result = self._handle_index_object(params)
            
            elif operation == OperationType.BATCH_INDEX:
                result = self._handle_batch_index(params)
            
            elif operation == OperationType.FIND_SIMILAR:
                result = self._handle_find_similar(params)
            
            elif operation == OperationType.GET_METADATA:
                result = self._handle_get_metadata(params)
            
            # Cluster management operations
            elif operation == OperationType.CLUSTER_HEALTH:
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
            "search_objects": OperationType.SEMANTIC_SEARCH,
            "read_object": OperationType.READ_OBJECT,
            "list_objects": OperationType.LIST_OBJECTS,
            "create_object": OperationType.CREATE_OBJECT,
            "update_object": OperationType.UPDATE_OBJECT,
            "delete_object": OperationType.DELETE_OBJECT,
            "get_stats": OperationType.GET_STATS,
            "index_object": OperationType.INDEX_OBJECT,
            "batch_index": OperationType.BATCH_INDEX,
            "find_similar": OperationType.FIND_SIMILAR,
            "get_metadata": OperationType.GET_METADATA,
            # Cluster management
            "cluster_health": OperationType.CLUSTER_HEALTH,
            "diagnose_cluster": OperationType.DIAGNOSE_CLUSTER,
            "osd_status": OperationType.OSD_STATUS,
            "pg_status": OperationType.PG_STATUS,
            "capacity_prediction": OperationType.CAPACITY_PREDICTION,
            "pool_stats": OperationType.POOL_STATS,
            "performance_stats": OperationType.PERFORMANCE_STATS,
            "explain_issue": OperationType.EXPLAIN_ISSUE,
            # Documentation
            "search_docs": OperationType.SEARCH_DOCS,
            "help": OperationType.HELP,
        }
        return mapping.get(function_name, OperationType.UNKNOWN)
    
    # Operation handlers
    
    def _handle_search(self, params: Dict[str, Any]) -> OperationResult:
        """Handle semantic search operation."""
        query = params.get('query', '')
        top_k = params.get('top_k') or 10  # Default to 10 if None or 0
        min_score = params.get('min_score') or 0.0
        
        results = self.searcher.search(query, top_k=top_k, min_score=min_score)
        
        if results:
            summary = f"Found {len(results)} objects matching '{query}':\n"
            for i, r in enumerate(results[:5], 1):
                summary += f"{i}. {r.object_name} (score: {r.relevance_score:.2f})\n"
            if len(results) > 5:
                summary += f"... and {len(results) - 5} more"
        else:
            summary = f"No objects found matching '{query}'"
        
        return OperationResult(
            success=True,
            operation=OperationType.SEMANTIC_SEARCH,
            data=[r.to_dict() for r in results],
            message=summary
        )
    
    def _handle_read(self, params: Dict[str, Any]) -> OperationResult:
        """Handle read object operation."""
        object_name = params.get('object_name', '')
        
        if self.rados_client is None:
            return OperationResult(
                success=False,
                operation=OperationType.READ_OBJECT,
                error="Ceph RADOS not connected",
                message="Cannot read objects: Ceph RADOS is not available. Run with sudo for Ceph access."
            )
        
        content = self.rados_client.read_object(object_name)
        
        if content:
            try:
                text = content.decode('utf-8')
                return OperationResult(
                    success=True,
                    operation=OperationType.READ_OBJECT,
                    data={"object_name": object_name, "content": text, "size": len(content)},
                    message=f"Content of '{object_name}':\n{text}"
                )
            except:
                return OperationResult(
                    success=True,
                    operation=OperationType.READ_OBJECT,
                    data={"object_name": object_name, "size": len(content), "binary": True},
                    message=f"Object '{object_name}' contains binary data ({len(content)} bytes)"
                )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.READ_OBJECT,
                error="Object not found or empty",
                message=f"Object '{object_name}' not found"
            )
    
    def _handle_list(self, params: Dict[str, Any]) -> OperationResult:
        """Handle list objects operation."""
        prefix = params.get('prefix')
        limit = params.get('limit', 100)
        
        if self.rados_client is None:
            return OperationResult(
                success=False,
                operation=OperationType.LIST_OBJECTS,
                error="Ceph RADOS not connected",
                message="Cannot list objects: Ceph RADOS is not available. Run with sudo for Ceph access."
            )
        
        objects = list(self.rados_client.list_objects(prefix=prefix, limit=limit))
        
        summary = f"Found {len(objects)} objects"
        if prefix:
            summary += f" with prefix '{prefix}'"
        summary += ":\n" + "\n".join(f"- {obj}" for obj in objects[:20])
        if len(objects) > 20:
            summary += f"\n... and {len(objects) - 20} more"
        
        return OperationResult(
            success=True,
            operation=OperationType.LIST_OBJECTS,
            data={"objects": objects, "count": len(objects)},
            message=summary
        )
    
    def _handle_create(self, params: Dict[str, Any]) -> OperationResult:
        """Handle create object operation."""
        object_name = params.get('object_name', '')
        content = params.get('content', '')
        auto_index = params.get('auto_index', True)
        
        if self.rados_client is None:
            return OperationResult(
                success=False,
                operation=OperationType.CREATE_OBJECT,
                error="Ceph RADOS not connected",
                message="Cannot create objects: Ceph RADOS is not available. Run with sudo for Ceph access."
            )
        
        data = content.encode('utf-8')
        success = self.rados_client.create_object(object_name, data)
        
        if success:
            message = f"Created object '{object_name}' ({len(data)} bytes)"
            
            # Auto-index if requested
            if auto_index:
                self.indexer.index_object(object_name)
                message += " and indexed for search"
            
            return OperationResult(
                success=True,
                operation=OperationType.CREATE_OBJECT,
                data={"object_name": object_name, "size": len(data)},
                message=message
            )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.CREATE_OBJECT,
                error="Failed to create object",
                message=f"Failed to create object '{object_name}'"
            )
    
    def _handle_update(self, params: Dict[str, Any]) -> OperationResult:
        """Handle update object operation."""
        object_name = params.get('object_name', '')
        content = params.get('content', '')
        append = params.get('append', False)
        
        if self.rados_client is None:
            return OperationResult(
                success=False,
                operation=OperationType.UPDATE_OBJECT,
                error="Ceph RADOS not connected",
                message="Cannot update objects: Ceph RADOS is not available. Run with sudo for Ceph access."
            )
        
        data = content.encode('utf-8')
        success = self.rados_client.update_object(object_name, data, append=append)
        
        if success:
            action = "Appended to" if append else "Updated"
            return OperationResult(
                success=True,
                operation=OperationType.UPDATE_OBJECT,
                data={"object_name": object_name, "size": len(data)},
                message=f"{action} object '{object_name}'"
            )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.UPDATE_OBJECT,
                error="Failed to update object",
                message=f"Failed to update object '{object_name}'"
            )
    
    def _handle_delete(self, params: Dict[str, Any]) -> OperationResult:
        """Handle delete object operation."""
        object_name = params.get('object_name', '')
        
        if self.rados_client is None:
            return OperationResult(
                success=False,
                operation=OperationType.DELETE_OBJECT,
                error="Ceph RADOS not connected",
                message="Cannot delete objects: Ceph RADOS is not available. Run with sudo for Ceph access."
            )
        
        success = self.rados_client.delete_object(object_name)
        
        if success:
            return OperationResult(
                success=True,
                operation=OperationType.DELETE_OBJECT,
                data={"object_name": object_name},
                message=f"Deleted object '{object_name}'"
            )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.DELETE_OBJECT,
                error="Failed to delete object",
                message=f"Failed to delete object '{object_name}'"
            )
    
    def _handle_stats(self, params: Dict[str, Any]) -> OperationResult:
        """Handle get stats operation."""
        if self.rados_client is not None:
            try:
                pool_stats = self.rados_client.get_pool_stats()
            except Exception as e:
                logger.warning(f"Failed to get pool stats: {e}")
                pool_stats = {"error": str(e)}
        else:
            pool_stats = {"status": "Ceph RADOS not connected"}
        
        indexer_stats = self.indexer.get_indexing_status()
        vector_stats = self.vector_store.get_stats()
        
        stats = {
            "pool": pool_stats,
            "indexer": indexer_stats,
            "vector_store": vector_stats
        }
        
        if "error" in pool_stats or "status" in pool_stats:
            pool_info = pool_stats.get('status', pool_stats.get('error', 'N/A'))
            message = f"""Storage Statistics:
Pool: {pool_info}
Indexed: {vector_stats.get('count', 0)} objects
Collection: {vector_stats.get('collection_name', 'unknown')}"""
        else:
            message = f"""Storage Statistics:
Pool: {pool_stats.get('num_objects', 0)} objects, {pool_stats.get('size_kb', 0) / 1024:.2f} MB
Indexed: {vector_stats.get('count', 0)} objects
Collection: {vector_stats.get('collection_name', 'unknown')}"""
        
        return OperationResult(
            success=True,
            operation=OperationType.GET_STATS,
            data=stats,
            message=message
        )
    
    def _handle_index_object(self, params: Dict[str, Any]) -> OperationResult:
        """Handle index object operation."""
        object_name = params.get('object_name', '')
        force = params.get('force', False)
        
        metadata = self.indexer.index_object(object_name, force_reindex=force)
        
        if metadata:
            return OperationResult(
                success=True,
                operation=OperationType.INDEX_OBJECT,
                data=metadata.to_dict(),
                message=f"Indexed object '{object_name}'"
            )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.INDEX_OBJECT,
                error="Failed to index object",
                message=f"Failed to index object '{object_name}'"
            )
    
    def _handle_batch_index(self, params: Dict[str, Any]) -> OperationResult:
        """Handle batch index operation."""
        prefix = params.get('prefix')
        limit = params.get('limit')
        force = params.get('force', False)
        
        stats = self.indexer.index_pool(prefix=prefix, limit=limit, force_reindex=force)
        
        message = f"Indexed {stats.indexed_count} objects"
        if stats.skipped_count > 0:
            message += f", skipped {stats.skipped_count}"
        if stats.failed_count > 0:
            message += f", failed {stats.failed_count}"
        
        return OperationResult(
            success=True,
            operation=OperationType.BATCH_INDEX,
            data=stats.to_dict(),
            message=message
        )
    
    def _handle_find_similar(self, params: Dict[str, Any]) -> OperationResult:
        """Handle find similar operation."""
        object_name = params.get('object_name', '')
        top_k = params.get('top_k', 10)
        
        results = self.searcher.find_similar(object_name, top_k=top_k)
        
        if results:
            summary = f"Found {len(results)} objects similar to '{object_name}':\n"
            for i, r in enumerate(results[:5], 1):
                summary += f"{i}. {r.object_name} (similarity: {r.score:.2f})\n"
            if len(results) > 5:
                summary += f"... and {len(results) - 5} more"
        else:
            summary = f"No similar objects found for '{object_name}'"
        
        return OperationResult(
            success=True,
            operation=OperationType.FIND_SIMILAR,
            data=[r.to_dict() for r in results],
            message=summary
        )
    
    def _handle_get_metadata(self, params: Dict[str, Any]) -> OperationResult:
        """Handle get metadata operation."""
        object_name = params.get('object_name', '')
        
        details = self.searcher.get_object_details(object_name)
        
        if details:
            message = f"Metadata for '{object_name}':\n"
            message += f"- Size: {details.get('size_bytes', 0)} bytes\n"
            message += f"- Type: {details.get('content_type', 'unknown')}\n"
            message += f"- Modified: {details.get('modified_at', 'unknown')}"
            
            return OperationResult(
                success=True,
                operation=OperationType.GET_METADATA,
                data=details,
                message=message
            )
        else:
            return OperationResult(
                success=False,
                operation=OperationType.GET_METADATA,
                error="Object not found",
                message=f"Object '{object_name}' not found or not indexed"
            )
    
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
        help_text = """🤖 **Ceph AI Assistant - Available Commands**

**Object Operations:**
• Search for files: "find files about kubernetes" or "search for config files"
• Read objects: "show me the content of test.txt"
• List objects: "list all files" or "show files starting with config"
• Create objects: "create a file called hello.txt with content Hello World"
• Delete objects: "delete old_file.txt"

**Cluster Management:**
• Health check: "is the cluster healthy?" or "check cluster status"
• Diagnose issues: "diagnose cluster problems" or "what's wrong?"
• OSD status: "show OSD status" or "are any OSDs down?"
• PG status: "show placement group status" or "any degraded PGs?"
• Capacity: "when will storage be full?" or "capacity prediction"
• Performance: "what's the current throughput?" or "show IOPS"

**Documentation:**
• Ask questions: "how do I configure erasure coding?"
• Get explanations: "what is a placement group?"
• Troubleshooting: "why might OSDs be slow?"

**Tips:**
• Use natural language - I understand context
• Ask follow-up questions
• Type 'exit' to quit
"""
        
        return OperationResult(
            success=True,
            operation=OperationType.HELP,
            data={"commands": ["search", "read", "create", "delete", "health", "diagnose", "help"]},
            message=help_text
        )
    
    def set_rag_system(self, rag_system):
        """Set the RAG system for documentation queries."""
        self.rag_system = rag_system
        logger.info("RAG system configured for agent")
    
    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation.clear()
