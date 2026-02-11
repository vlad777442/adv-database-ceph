"""
High-level agent service for natural language interface.

Provides the main integration point for the LLM-powered
autonomous Ceph cluster management agent.
"""

import logging
from typing import Optional

from core.llm_agent import LLMAgent
from core.llm_provider import create_llm_provider
from core.rados_client import RadosClient
from core.embedding_generator import EmbeddingGenerator
from core.content_processor import ContentProcessor
from core.vector_store import VectorStore
from core.rag_system import CephDocRAG
from services.indexer import Indexer
from services.searcher import Searcher

logger = logging.getLogger(__name__)


class AgentService:
    """
    High-level service for the Ceph AI management agent.
    
    Provides a simplified interface for creating and using the agent
    with all its capabilities: ReAct reasoning, runbook automation,
    anomaly detection, and cluster management.
    """
    
    def __init__(
        self,
        llm_config: dict,
        rados_client: Optional[RadosClient],
        embedding_generator: EmbeddingGenerator,
        content_processor: ContentProcessor,
        vector_store: VectorStore,
        enable_rag: bool = True,
        agent_config: Optional[dict] = None,
    ):
        """
        Initialize agent service.
        
        Args:
            llm_config: LLM configuration dictionary
            rados_client: RADOS client instance (optional)
            embedding_generator: Embedding generator instance
            content_processor: Content processor instance
            vector_store: Vector store instance
            enable_rag: Whether to enable RAG documentation system
            agent_config: Agent behavior config (react loop, safety, etc.)
        """
        # Create LLM provider
        self.llm_provider = create_llm_provider(llm_config)
        
        # Create service dependencies
        self.indexer = Indexer(
            rados_client=rados_client,
            embedding_generator=embedding_generator,
            content_processor=content_processor,
            vector_store=vector_store
        )
        
        self.searcher = Searcher(
            rados_client=rados_client,
            embedding_generator=embedding_generator,
            vector_store=vector_store
        )
        
        # Build agent config from llm_config and explicit agent_config
        effective_agent_config = {
            "use_react_loop": llm_config.get("agent_react_loop", True),
            "max_iterations": llm_config.get("agent_max_iterations", 10),
            "dry_run": llm_config.get("agent_dry_run", False),
            "max_actions_per_session": llm_config.get("agent_max_actions", 20),
            "require_confirmation": llm_config.get("agent_require_confirmation", True),
        }
        if agent_config:
            effective_agent_config.update(agent_config)
        
        # Create agent
        self.agent = LLMAgent(
            llm_provider=self.llm_provider,
            rados_client=rados_client,
            indexer=self.indexer,
            searcher=self.searcher,
            vector_store=vector_store,
            agent_config=effective_agent_config,
        )
        
        # Initialize RAG system
        if enable_rag:
            try:
                self.rag_system = CephDocRAG(
                    embedding_generator=embedding_generator,
                    docs_directory="./ceph_docs",
                    persist_directory="./rag_data"
                )
                self.agent.set_rag_system(self.rag_system)
                logger.info("RAG documentation system enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize RAG system: {e}")
                self.rag_system = None
        else:
            self.rag_system = None
        
        logger.info("Initialized Agent Service (autonomous mode)")
    
    def execute(self, prompt: str, auto_confirm: bool = False):
        """
        Execute a natural language command.
        
        Args:
            prompt: User's natural language input
            auto_confirm: Auto-confirm destructive operations
            
        Returns:
            OperationResult
        """
        return self.agent.process_query(prompt, auto_confirm=auto_confirm)
    
    def chat(self, prompt: str):
        """
        Chat with the agent (maintains conversation context).
        
        Args:
            prompt: User's message
            
        Returns:
            OperationResult
        """
        return self.agent.process_query(prompt, auto_confirm=False)
    
    def scan_anomalies(self):
        """Run proactive anomaly detection on the cluster."""
        return self.agent.scan_anomalies()
    
    def get_action_log(self):
        """Get the audit log of actions taken."""
        return self.agent.action_engine.get_audit_log()
    
    def get_session_summary(self):
        """Get a summary of the current session."""
        return self.agent.action_engine.get_session_summary()
    
    def clear_history(self):
        """Clear conversation history."""
        self.agent.clear_conversation()
    
    def get_rag_stats(self) -> dict:
        """Get RAG system statistics."""
        if self.rag_system:
            return self.rag_system.get_stats()
        return {"enabled": False}
