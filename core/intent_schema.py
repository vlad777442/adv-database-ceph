"""
Intent classification and operation schemas for LLM agent.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class OperationType(str, Enum):
    """Types of operations the agent can perform."""
    
    # Cluster monitoring operations (read-only)
    CLUSTER_HEALTH = "cluster_health"
    DIAGNOSE_CLUSTER = "diagnose_cluster"
    OSD_STATUS = "osd_status"
    PG_STATUS = "pg_status"
    CAPACITY_PREDICTION = "capacity_prediction"
    POOL_STATS = "pool_stats"
    PERFORMANCE_STATS = "performance_stats"
    EXPLAIN_ISSUE = "explain_issue"
    
    # Cluster management actions (write operations)
    SET_CLUSTER_FLAG = "set_cluster_flag"
    UNSET_CLUSTER_FLAG = "unset_cluster_flag"
    SET_OSD_OUT = "set_osd_out"
    SET_OSD_IN = "set_osd_in"
    REWEIGHT_OSD = "reweight_osd"
    CREATE_POOL = "create_pool"
    DELETE_POOL = "delete_pool"
    SET_POOL_PARAM = "set_pool_param"
    RESTART_OSD = "restart_osd"
    INITIATE_REBALANCE = "initiate_rebalance"
    REPAIR_PG = "repair_pg"
    DEEP_SCRUB_PG = "deep_scrub_pg"
    GET_CONFIG = "get_config"
    SET_CONFIG = "set_config"
    
    # CRUSH map operations
    CRUSH_DUMP = "crush_dump"
    CRUSH_TREE = "crush_tree"
    CRUSH_ADD_BUCKET = "crush_add_bucket"
    CRUSH_MOVE = "crush_move"
    CRUSH_REMOVE = "crush_remove"
    CRUSH_REWEIGHT = "crush_reweight"
    CRUSH_RULE_LS = "crush_rule_ls"
    CRUSH_RULE_DUMP = "crush_rule_dump"
    CRUSH_RULE_CREATE_SIMPLE = "crush_rule_create_simple"
    CRUSH_RULE_RM = "crush_rule_rm"
    
    # OSD lifecycle operations
    OSD_SAFE_TO_DESTROY = "osd_safe_to_destroy"
    OSD_OK_TO_STOP = "osd_ok_to_stop"
    OSD_DESTROY = "osd_destroy"
    OSD_PURGE = "osd_purge"
    OSD_DOWN = "osd_down"
    
    # Auth management
    AUTH_LIST = "auth_list"
    AUTH_ADD = "auth_add"
    AUTH_DEL = "auth_del"
    AUTH_CAPS = "auth_caps"
    AUTH_GET_KEY = "auth_get_key"
    
    # Monitor management
    MON_STAT = "mon_stat"
    MON_DUMP = "mon_dump"
    MON_ADD = "mon_add"
    MON_REMOVE = "mon_remove"
    QUORUM_STATUS = "quorum_status"
    
    # MGR module management
    MGR_MODULE_LS = "mgr_module_ls"
    MGR_MODULE_ENABLE = "mgr_module_enable"
    MGR_MODULE_DISABLE = "mgr_module_disable"
    MGR_DUMP = "mgr_dump"
    MGR_FAIL = "mgr_fail"
    
    # Erasure code profiles
    EC_PROFILE_LS = "ec_profile_ls"
    EC_PROFILE_GET = "ec_profile_get"
    EC_PROFILE_SET = "ec_profile_set"
    EC_PROFILE_RM = "ec_profile_rm"
    
    # Pool extended operations
    POOL_GET = "pool_get"
    POOL_RENAME = "pool_rename"
    POOL_GET_QUOTA = "pool_get_quota"
    POOL_SET_QUOTA = "pool_set_quota"
    POOL_MKSNAP = "pool_mksnap"
    POOL_RMSNAP = "pool_rmsnap"
    POOL_APPLICATION_ENABLE = "pool_application_enable"
    
    # PG extended operations
    PG_SCRUB = "pg_scrub"
    PG_DUMP_STUCK = "pg_dump_stuck"
    PG_LS = "pg_ls"
    
    # OSD utilization operations
    OSD_DF = "osd_df"
    OSD_REWEIGHT_BY_UTILIZATION = "osd_reweight_by_utilization"
    OSD_BLOCKLIST_LS = "osd_blocklist_ls"
    OSD_BLOCKLIST_ADD = "osd_blocklist_add"
    
    # RBD (block device) operations
    RBD_LS = "rbd_ls"
    RBD_INFO = "rbd_info"
    RBD_CREATE = "rbd_create"
    RBD_RM = "rbd_rm"
    RBD_SNAP_LS = "rbd_snap_ls"
    RBD_SNAP_CREATE = "rbd_snap_create"
    RBD_SNAP_RM = "rbd_snap_rm"
    RBD_DU = "rbd_du"
    
    # CephFS (file system) operations
    FS_LS = "fs_ls"
    FS_STATUS = "fs_status"
    FS_NEW = "fs_new"
    FS_RM = "fs_rm"
    MDS_STAT = "mds_stat"
    FS_SET = "fs_set"
    
    # Device health operations
    DEVICE_LS = "device_ls"
    DEVICE_INFO = "device_info"
    DEVICE_PREDICT_LIFE_EXPECTANCY = "device_predict_life_expectancy"
    DEVICE_LIGHT = "device_light"
    
    # Crash management operations
    CRASH_LS = "crash_ls"
    CRASH_INFO = "crash_info"
    CRASH_ARCHIVE = "crash_archive"
    CRASH_ARCHIVE_ALL = "crash_archive_all"
    
    # OSD extended operations
    OSD_DUMP = "osd_dump"
    OSD_FIND = "osd_find"
    OSD_METADATA = "osd_metadata"
    OSD_PERF = "osd_perf"
    OSD_POOL_AUTOSCALE_STATUS = "osd_pool_autoscale_status"
    
    # Config DB operations
    CONFIG_DUMP = "config_dump"
    CONFIG_GET = "config_get"
    CONFIG_SET = "config_set"
    CONFIG_SHOW = "config_show"
    CONFIG_LOG = "config_log"
    
    # Balancer operations
    BALANCER_STATUS = "balancer_status"
    BALANCER_EVAL = "balancer_eval"
    BALANCER_OPTIMIZE = "balancer_optimize"
    
    # Automated remediation
    LIST_RUNBOOKS = "list_runbooks"
    EXECUTE_RUNBOOK = "execute_runbook"
    SUGGEST_RUNBOOK = "suggest_runbook"
    
    # Agent planning
    CREATE_PLAN = "create_plan"
    GET_ACTION_LOG = "get_action_log"
    
    # Anomaly detection
    SCAN_ANOMALIES = "scan_anomalies"
    
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


class LatencyBreakdown(BaseModel):
    """Detailed latency breakdown for performance analysis."""
    llm_inference_ms: float = Field(default=0.0, description="LLM intent classification time")
    embedding_ms: float = Field(default=0.0, description="Embedding generation time")
    vector_search_ms: float = Field(default=0.0, description="Vector store query time")
    rados_io_ms: float = Field(default=0.0, description="RADOS read/write/list time")
    response_format_ms: float = Field(default=0.0, description="Response formatting time")
    total_ms: float = Field(default=0.0, description="Total end-to-end time")

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
    latency_breakdown: Optional[LatencyBreakdown] = Field(default=None, description="Detailed latency breakdown")
    
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
