"""
Intent classification and operation schemas for LLM agent.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class OperationType(str, Enum):
    """Types of operations the agent can perform."""
    
    # Search operations
    SEMANTIC_SEARCH = "semantic_search"
    FIND_SIMILAR = "find_similar"
    
    # Read operations
    READ_OBJECT = "read_object"
    LIST_OBJECTS = "list_objects"
    GET_METADATA = "get_metadata"
    GET_STATS = "get_stats"
    
    # Write operations
    CREATE_OBJECT = "create_object"
    UPDATE_OBJECT = "update_object"
    APPEND_OBJECT = "append_object"
    
    # Delete operations
    DELETE_OBJECT = "delete_object"
    BULK_DELETE = "bulk_delete"
    
    # Index operations
    INDEX_OBJECT = "index_object"
    BATCH_INDEX = "batch_index"
    REINDEX_ALL = "reindex_all"
    
    # Analysis operations
    SUMMARIZE = "summarize_content"
    COMPARE = "compare_objects"
    ANALYZE_POOL = "analyze_pool"
    
    # Cluster management operations
    CLUSTER_HEALTH = "cluster_health"
    DIAGNOSE_CLUSTER = "diagnose_cluster"
    OSD_STATUS = "osd_status"
    PG_STATUS = "pg_status"
    CAPACITY_PREDICTION = "capacity_prediction"
    POOL_STATS = "pool_stats"
    PERFORMANCE_STATS = "performance_stats"
    EXPLAIN_ISSUE = "explain_issue"
    
    # Documentation/RAG operations
    SEARCH_DOCS = "search_docs"
    
    # System operations
    HELP = "help"
    UNKNOWN = "unknown"


class Intent(BaseModel):
    """
    Represents the classified intent from user's natural language input.
    """
    operation: OperationType = Field(..., description="The operation to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Extracted parameters")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    reasoning: Optional[str] = Field(None, description="LLM's reasoning")
    requires_confirmation: bool = Field(default=False, description="Whether operation needs user confirmation")
    original_prompt: str = Field(..., description="Original user input")
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class OperationResult(BaseModel):
    """Result of an operation execution."""
    
    success: bool = Field(..., description="Whether operation succeeded")
    operation: OperationType = Field(..., description="Operation that was executed")
    data: Optional[Any] = Field(None, description="Result data")
    message: str = Field(default="", description="Human-readable message")
    error: Optional[str] = Field(None, description="Error message if failed")
    execution_time: float = Field(default=0.0, description="Execution time in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class ConversationMessage(BaseModel):
    """A message in the conversation history."""
    
    role: str = Field(..., description="Message role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationHistory(BaseModel):
    """Manages conversation history for context."""
    
    messages: List[ConversationMessage] = Field(default_factory=list)
    max_history: int = Field(default=10, description="Maximum messages to keep")
    
    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """Add a message to history."""
        msg = ConversationMessage(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(msg)
        
        # Keep only last max_history messages
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def get_context(self) -> List[Dict[str, str]]:
        """Get conversation context for LLM."""
        return [{"role": msg.role, "content": msg.content} for msg in self.messages]
    
    def clear(self):
        """Clear conversation history."""
        self.messages = []
