"""
Tool registry defining available functions for LLM agent.

Tools are organized into categories:
- Object Storage: Read-only RADOS object access and semantic search
- Semantic Search: Embedding-based search and similarity
- Cluster Monitoring: Read-only cluster status tools
- Cluster Management: Write operations for cluster administration
- Automated Remediation: Runbook-based automated procedures
- Documentation: RAG-powered Ceph documentation search
"""

from typing import List, Dict, Any


# Tool definitions for function calling
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # ============ Object Storage Tools ============
    {
        "name": "search_objects",
        "description": "Search for objects in Ceph storage using semantic/natural language query. Use this when user wants to find or search for files/objects.",
        "parameters": {
            "query": {
                "type": "string",
                "description": "Natural language search query",
                "required": True
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return",
                "default": 10
            },
            "min_score": {
                "type": "number",
                "description": "Minimum relevance score (0-1)",
                "default": 0.0
            }
        }
    },
    {
        "name": "read_object",
        "description": "Read the content of a specific object from Ceph storage. Use this when user wants to see, show, or read file content.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Exact name of the object to read (e.g., 'test.txt', 'config.yaml', 'README.md'). Extract the exact filename from the query. For 'readme', use 'readme.md'. For 'README', use 'README.md'.",
                "required": True
            }
        }
    },
    {
        "name": "list_objects",
        "description": "List all objects/files within a single Ceph pool, optionally filtered by prefix. Use when user wants to see what files/objects exist inside a pool. Do NOT use for listing pools themselves.",
        "parameters": {
            "prefix": {
                "type": "string",
                "description": "Optional prefix to filter objects",
                "default": None
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of objects to list",
                "default": 100
            }
        }
    },
    {
        "name": "get_stats",
        "description": "Get statistics about the Ceph pool and indexed objects. Use this when user asks about storage usage, counts, or statistics.",
        "parameters": {}
    },
    {
        "name": "index_object",
        "description": "Index a specific object for semantic search. Use this when user wants to make an object searchable.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Name of the object to index",
                "required": True
            },
            "force": {
                "type": "boolean",
                "description": "Force reindex if already indexed",
                "default": False
            }
        }
    },
    {
        "name": "batch_index",
        "description": "Index multiple objects in the pool. Use this when user wants to index all or many files.",
        "parameters": {
            "prefix": {
                "type": "string",
                "description": "Only index objects with this prefix",
                "default": None
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of objects to index",
                "default": None
            },
            "force": {
                "type": "boolean",
                "description": "Force reindex existing objects",
                "default": False
            }
        }
    },
    {
        "name": "find_similar",
        "description": "Find objects similar to a given object. Use this when user wants to find related or similar files.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Exact name of the reference object (e.g., 'config.yaml', 'test.txt', 'readme.md'). Extract the precise filename mentioned in the query without modification.",
                "required": True
            },
            "top_k": {
                "type": "integer",
                "description": "Number of similar objects to find",
                "default": 10
            }
        }
    },
    {
        "name": "get_metadata",
        "description": "Get metadata about a specific object. Use this when user wants to see file details, info, or properties.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Name of the object",
                "required": True
            }
        }
    },
    # ============ Cluster Management Tools ============
    {
        "name": "cluster_health",
        "description": "Get cluster health status. Use when user asks 'is the cluster healthy?', 'cluster status', 'any problems?', or health-related questions.",
        "parameters": {
            "detail": {
                "type": "boolean",
                "description": "Include detailed health checks",
                "default": True
            }
        }
    },
    {
        "name": "diagnose_cluster",
        "description": "Perform comprehensive cluster diagnosis. Use when user asks 'diagnose', 'what's wrong', 'troubleshoot', or wants a full analysis.",
        "parameters": {}
    },
    {
        "name": "osd_status",
        "description": "Get OSD status and information. Use when user asks about OSDs, disks, or storage devices.",
        "parameters": {}
    },
    {
        "name": "pg_status",
        "description": "Get placement group (PG) status. Use when user asks about PGs, placement groups, or data distribution.",
        "parameters": {
            "pg_id": {
                "type": "string",
                "description": "Specific PG ID to query (optional)",
                "default": None
            }
        }
    },
    {
        "name": "capacity_prediction",
        "description": "Predict storage capacity and when cluster will be full. Use when user asks about capacity planning, disk space, or 'when will we run out'.",
        "parameters": {
            "days": {
                "type": "integer",
                "description": "Number of days to project",
                "default": 30
            }
        }
    },
    {
        "name": "pool_stats",
        "description": "List all pools and get their statistics (usage, size, object count). Use when user asks 'what pools do I have', 'list pools', 'show pools', pool usage, or pool information.",
        "parameters": {}
    },
    {
        "name": "performance_stats",
        "description": "Get cluster performance statistics including IOPS and throughput. Use when user asks about performance, speed, throughput, or IOPS.",
        "parameters": {}
    },
    {
        "name": "explain_issue",
        "description": "Explain a Ceph issue or concept. Use when user asks 'why is X happening', 'what does Y mean', or needs explanation.",
        "parameters": {
            "topic": {
                "type": "string",
                "description": "The issue or concept to explain",
                "required": True
            }
        }
    },
    # ============ RAG Documentation Tools ============
    {
        "name": "search_docs",
        "description": "Search Ceph documentation using RAG. Use when user asks 'how do I...', 'what is...', or needs help with Ceph concepts.",
        "parameters": {
            "query": {
                "type": "string",
                "description": "Documentation search query",
                "required": True
            },
            "top_k": {
                "type": "integer",
                "description": "Number of relevant documents to retrieve",
                "default": 3
            }
        }
    },
    {
        "name": "help",
        "description": "Get help about available commands and capabilities. Use when user asks for help or what the agent can do.",
        "parameters": {}
    },
    # ============ Cluster Management Actions ============
    {
        "name": "set_cluster_flag",
        "description": "Set a cluster-wide flag (e.g., norebalance, noout, noin, nobackfill, norecover, noscrub, nodeep-scrub). Use when user wants to pause rebalancing, prevent OSD removals, or control cluster behavior.",
        "parameters": {
            "flag": {
                "type": "string",
                "description": "Flag to set: norebalance, noout, noin, nobackfill, norecover, noscrub, nodeep-scrub, pause",
                "required": True
            }
        }
    },
    {
        "name": "unset_cluster_flag",
        "description": "Unset/remove a cluster-wide flag. Use when user wants to resume rebalancing, allow OSD changes, etc.",
        "parameters": {
            "flag": {
                "type": "string",
                "description": "Flag to unset: norebalance, noout, noin, nobackfill, norecover, noscrub, nodeep-scrub, pause",
                "required": True
            }
        }
    },
    {
        "name": "set_osd_out",
        "description": "Mark an OSD as 'out' of the cluster. Data will be migrated away from this OSD. Use for planned OSD removal or maintenance.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to mark out",
                "required": True
            }
        }
    },
    {
        "name": "set_osd_in",
        "description": "Mark an OSD as 'in' the cluster. The OSD will start receiving data again. Use to bring an OSD back after maintenance.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to mark in",
                "required": True
            }
        }
    },
    {
        "name": "reweight_osd",
        "description": "Adjust the CRUSH weight of an OSD to control data distribution. Lower weight = less data. Use for balancing utilization across OSDs.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to reweight",
                "required": True
            },
            "weight": {
                "type": "number",
                "description": "New weight (0.0-1.0, where 1.0 is default)",
                "required": True
            }
        }
    },
    {
        "name": "create_pool",
        "description": "Create a new RADOS pool. Use when user wants to create a new storage pool.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Name of the pool to create",
                "required": True
            },
            "pg_num": {
                "type": "integer",
                "description": "Number of placement groups",
                "default": 32
            },
            "pool_type": {
                "type": "string",
                "description": "Pool type: replicated or erasure",
                "default": "replicated"
            },
            "size": {
                "type": "integer",
                "description": "Replication size (number of copies)",
                "default": 3
            }
        }
    },
    {
        "name": "delete_pool",
        "description": "Delete a RADOS pool. WARNING: This permanently destroys all data in the pool. Use only when explicitly requested.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Name of the pool to delete",
                "required": True
            }
        }
    },
    {
        "name": "set_pool_param",
        "description": "Set a pool parameter (e.g., size, min_size, pg_num, target_max_bytes). Use for pool tuning.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Name of the pool",
                "required": True
            },
            "param": {
                "type": "string",
                "description": "Parameter name (size, min_size, pg_num, pgp_num, target_max_bytes, target_max_objects)",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "Parameter value",
                "required": True
            }
        }
    },
    {
        "name": "restart_osd",
        "description": "Restart an OSD daemon. Use for recovering a stuck or unresponsive OSD.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to restart",
                "required": True
            }
        }
    },
    {
        "name": "initiate_rebalance",
        "description": "Initiate data rebalancing across OSDs using upmap balancer or CRUSH weight adjustments. Use when OSDs have uneven utilization.",
        "parameters": {
            "method": {
                "type": "string",
                "description": "Balancing method: upmap, crush-compat, or weight",
                "default": "upmap"
            }
        }
    },
    {
        "name": "repair_pg",
        "description": "Initiate repair on an inconsistent placement group. Use after scrub errors.",
        "parameters": {
            "pg_id": {
                "type": "string",
                "description": "Placement group ID (e.g., '1.2a')",
                "required": True
            }
        }
    },
    {
        "name": "deep_scrub_pg",
        "description": "Initiate a deep scrub on a placement group to check data integrity.",
        "parameters": {
            "pg_id": {
                "type": "string",
                "description": "Placement group ID to deep scrub",
                "required": True
            }
        }
    },
    {
        "name": "get_config",
        "description": "Get a Ceph configuration value. Use to inspect cluster configuration.",
        "parameters": {
            "key": {
                "type": "string",
                "description": "Configuration key (e.g., 'osd_recovery_max_active', 'mon_allow_pool_delete')",
                "required": True
            },
            "daemon": {
                "type": "string",
                "description": "Daemon type to query (mon, osd, mds, mgr)",
                "default": "mon"
            }
        }
    },
    {
        "name": "set_config",
        "description": "Set a Ceph configuration value at runtime. Use for tuning cluster behavior.",
        "parameters": {
            "key": {
                "type": "string",
                "description": "Configuration key",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "Configuration value",
                "required": True
            },
            "daemon": {
                "type": "string",
                "description": "Daemon type to configure (global, mon, osd, mds, mgr)",
                "default": "global"
            }
        }
    },
    # ============ Automated Remediation Tools ============
    {
        "name": "list_runbooks",
        "description": "List available automated runbooks for cluster management. Use when user asks what automated procedures are available.",
        "parameters": {}
    },
    {
        "name": "execute_runbook",
        "description": "Execute an automated runbook for a specific cluster management task. Runbooks are pre-defined multi-step procedures for common operations.",
        "parameters": {
            "runbook_name": {
                "type": "string",
                "description": "Name of the runbook (e.g., 'recover_down_osd', 'fix_degraded_pgs', 'rebalance_cluster', 'performance_investigation')",
                "required": True
            },
            "params": {
                "type": "object",
                "description": "Parameters for the runbook (e.g., {'osd_id': 5})",
                "default": {}
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, show what would be done without executing",
                "default": False
            }
        }
    },
    {
        "name": "suggest_runbook",
        "description": "Suggest a runbook based on the current cluster issue. Use when user describes a problem and wants an automated fix.",
        "parameters": {
            "issue_description": {
                "type": "string",
                "description": "Description of the cluster issue",
                "required": True
            }
        }
    },
    # ============ Agent Planning Tools ============
    {
        "name": "create_plan",
        "description": "Create a multi-step execution plan for a complex cluster management task. Use for tasks that require multiple coordinated operations.",
        "parameters": {
            "goal": {
                "type": "string",
                "description": "Description of the goal to achieve",
                "required": True
            }
        }
    },
    {
        "name": "get_action_log",
        "description": "Get the audit log of actions taken during this session. Use to review what has been done.",
        "parameters": {}
    }
]


def get_tool_by_name(name: str) -> Dict[str, Any]:
    """Get tool definition by name."""
    for tool in TOOL_DEFINITIONS:
        if tool['name'] == name:
            return tool
    raise ValueError(f"Tool '{name}' not found")


def get_all_tools() -> List[Dict[str, Any]]:
    """Get all tool definitions."""
    return TOOL_DEFINITIONS


def get_tool_names() -> List[str]:
    """Get list of all tool names."""
    return [tool['name'] for tool in TOOL_DEFINITIONS]
