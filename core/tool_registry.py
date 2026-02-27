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
    # ============ CRUSH Map Tools ============
    {
        "name": "crush_dump",
        "description": "Dump the full CRUSH map showing the cluster topology (hosts, racks, OSDs, rules). Use when user asks about CRUSH map, cluster topology, or data placement.",
        "parameters": {}
    },
    {
        "name": "crush_tree",
        "description": "Show the CRUSH hierarchy as a tree view. Use when user asks to see the OSD tree, cluster layout, or bucket structure.",
        "parameters": {}
    },
    {
        "name": "crush_add_bucket",
        "description": "Add a new CRUSH bucket (host, rack, datacenter, etc.) to the CRUSH map. Use when user wants to add a new host, rack, or location.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the bucket to add (e.g., 'rack01', 'host-new')",
                "required": True
            },
            "bucket_type": {
                "type": "string",
                "description": "CRUSH bucket type: host, rack, row, room, datacenter, region, root",
                "required": True
            }
        }
    },
    {
        "name": "crush_move",
        "description": "Move a CRUSH bucket to a new location in the hierarchy. Use when user wants to move a host to a different rack, or reorganize topology.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the bucket to move",
                "required": True
            },
            "location": {
                "type": "object",
                "description": "Target location as key-value pairs (e.g., {'rack': 'rack01', 'root': 'default'})",
                "required": True
            }
        }
    },
    {
        "name": "crush_remove",
        "description": "Remove a bucket or OSD from the CRUSH map. Use when decommissioning a host or removing topology entries.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the bucket or OSD to remove (e.g., 'osd.5', 'host-old')",
                "required": True
            }
        }
    },
    {
        "name": "crush_reweight",
        "description": "Change the CRUSH weight of a bucket or OSD. Use to control how much data a host or OSD receives.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the OSD or bucket (e.g., 'osd.5')",
                "required": True
            },
            "weight": {
                "type": "number",
                "description": "New CRUSH weight (typically in TB, e.g., 3.63 for a 4TB disk)",
                "required": True
            }
        }
    },
    {
        "name": "crush_rule_ls",
        "description": "List all CRUSH rules. Use when user asks about data placement rules or CRUSH rules.",
        "parameters": {}
    },
    {
        "name": "crush_rule_dump",
        "description": "Dump details of a specific CRUSH rule. Use when user wants to inspect rule configuration.",
        "parameters": {
            "rule_name": {
                "type": "string",
                "description": "Name of the CRUSH rule to dump (optional, dumps all if omitted)",
                "default": None
            }
        }
    },
    {
        "name": "crush_rule_create_simple",
        "description": "Create a simple CRUSH replication rule. Use when user wants to create a new data placement rule.",
        "parameters": {
            "rule_name": {
                "type": "string",
                "description": "Name for the new rule",
                "required": True
            },
            "root": {
                "type": "string",
                "description": "Root bucket to start from (e.g., 'default')",
                "default": "default"
            },
            "failure_domain": {
                "type": "string",
                "description": "Failure domain for replica placement (e.g., 'host', 'rack')",
                "default": "host"
            }
        }
    },
    {
        "name": "crush_rule_rm",
        "description": "Remove a CRUSH rule. Use when user wants to delete a data placement rule.",
        "parameters": {
            "rule_name": {
                "type": "string",
                "description": "Name of the CRUSH rule to remove",
                "required": True
            }
        }
    },
    # ============ OSD Lifecycle Tools ============
    {
        "name": "osd_safe_to_destroy",
        "description": "Check whether it is safe to destroy an OSD without losing data. Use before decommissioning an OSD.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to check",
                "required": True
            }
        }
    },
    {
        "name": "osd_ok_to_stop",
        "description": "Check whether an OSD can be stopped without making data unavailable. Use before maintenance on an OSD.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to check",
                "required": True
            }
        }
    },
    {
        "name": "osd_destroy",
        "description": "Destroy an OSD, removing its cephx keys and dm-crypt keys. The OSD must be marked as 'lost' first. Use for permanent decommissioning.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to destroy",
                "required": True
            }
        }
    },
    {
        "name": "osd_purge",
        "description": "Purge an OSD: combines osd destroy, osd rm, and osd crush remove. Use for complete OSD removal.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to purge",
                "required": True
            }
        }
    },
    {
        "name": "osd_down",
        "description": "Mark an OSD as down. Use when an OSD needs to be flagged as down manually.",
        "parameters": {
            "osd_id": {
                "type": "integer",
                "description": "ID of the OSD to mark down",
                "required": True
            }
        }
    },
    # ============ Auth Management Tools ============
    {
        "name": "auth_list",
        "description": "List all authentication entities and their capabilities. Use when user asks about auth keys, users, or permissions.",
        "parameters": {}
    },
    {
        "name": "auth_add",
        "description": "Add a new authentication entity with specified capabilities. Use when creating a new client key or service account.",
        "parameters": {
            "entity": {
                "type": "string",
                "description": "Entity name (e.g., 'client.myapp', 'client.admin')",
                "required": True
            },
            "caps": {
                "type": "object",
                "description": "Capability map (e.g., {'mon': 'allow r', 'osd': 'allow rw pool=mypool'})",
                "required": True
            }
        }
    },
    {
        "name": "auth_del",
        "description": "Delete an authentication entity and revoke its keys. Use when removing a client or revoking access.",
        "parameters": {
            "entity": {
                "type": "string",
                "description": "Entity name to delete (e.g., 'client.myapp')",
                "required": True
            }
        }
    },
    {
        "name": "auth_caps",
        "description": "Update capabilities for an existing authentication entity. Use when changing permissions for a client.",
        "parameters": {
            "entity": {
                "type": "string",
                "description": "Entity name (e.g., 'client.myapp')",
                "required": True
            },
            "caps": {
                "type": "object",
                "description": "New capability map (e.g., {'mon': 'allow r', 'osd': 'allow rw'})",
                "required": True
            }
        }
    },
    {
        "name": "auth_get_key",
        "description": "Get the authentication key for an entity. Use when user needs to retrieve a client key.",
        "parameters": {
            "entity": {
                "type": "string",
                "description": "Entity name (e.g., 'client.admin')",
                "required": True
            }
        }
    },
    # ============ Monitor Management Tools ============
    {
        "name": "mon_stat",
        "description": "Get monitor quorum status summary. Use when user asks about monitors, quorum, or mon health.",
        "parameters": {}
    },
    {
        "name": "mon_dump",
        "description": "Dump the monitor map showing all monitors, their addresses, and epochs. Use when user wants detailed monitor information.",
        "parameters": {}
    },
    {
        "name": "mon_add",
        "description": "Add a new monitor to the cluster. Use when expanding monitor quorum.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name for the new monitor",
                "required": True
            },
            "addr": {
                "type": "string",
                "description": "IP address and port (e.g., '10.0.0.5:6789')",
                "required": True
            }
        }
    },
    {
        "name": "mon_remove",
        "description": "Remove a monitor from the cluster. WARNING: removing a monitor from a small quorum can cause data unavailability.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the monitor to remove",
                "required": True
            }
        }
    },
    {
        "name": "quorum_status",
        "description": "Get detailed quorum status including which monitors are in/out of quorum. Use when investigating monitor issues.",
        "parameters": {}
    },
    # ============ MGR Module Tools ============
    {
        "name": "mgr_module_ls",
        "description": "List all manager modules and their enabled/disabled status. Use when user asks about mgr modules, dashboard, balancer, etc.",
        "parameters": {}
    },
    {
        "name": "mgr_module_enable",
        "description": "Enable a manager module (e.g., dashboard, balancer, prometheus, telemetry). Use when activating a mgr feature.",
        "parameters": {
            "module": {
                "type": "string",
                "description": "Module name to enable (e.g., 'dashboard', 'balancer', 'prometheus')",
                "required": True
            }
        }
    },
    {
        "name": "mgr_module_disable",
        "description": "Disable a manager module. Use when deactivating a mgr feature.",
        "parameters": {
            "module": {
                "type": "string",
                "description": "Module name to disable",
                "required": True
            }
        }
    },
    {
        "name": "mgr_dump",
        "description": "Dump the MgrMap showing active and standby manager daemons. Use when user asks about manager daemon status.",
        "parameters": {}
    },
    {
        "name": "mgr_fail",
        "description": "Fail a manager daemon, causing a standby to take over. Use when the active mgr is unresponsive.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Name of the manager daemon to fail",
                "required": True
            }
        }
    },
    # ============ Erasure Code Profile Tools ============
    {
        "name": "ec_profile_ls",
        "description": "List all erasure code profiles. Use when user asks about erasure coding configurations.",
        "parameters": {}
    },
    {
        "name": "ec_profile_get",
        "description": "Get details of a specific erasure code profile. Use when user wants to inspect an EC profile.",
        "parameters": {
            "profile_name": {
                "type": "string",
                "description": "Name of the erasure code profile",
                "required": True
            }
        }
    },
    {
        "name": "ec_profile_set",
        "description": "Create or update an erasure code profile. Use when user wants to create a new EC profile for erasure-coded pools.",
        "parameters": {
            "profile_name": {
                "type": "string",
                "description": "Name for the profile",
                "required": True
            },
            "k": {
                "type": "integer",
                "description": "Number of data chunks",
                "required": True
            },
            "m": {
                "type": "integer",
                "description": "Number of coding (parity) chunks",
                "required": True
            },
            "plugin": {
                "type": "string",
                "description": "Erasure code plugin (e.g., 'jerasure', 'isa', 'lrc')",
                "default": "jerasure"
            }
        }
    },
    {
        "name": "ec_profile_rm",
        "description": "Remove an erasure code profile. Use when user wants to delete an unused EC profile.",
        "parameters": {
            "profile_name": {
                "type": "string",
                "description": "Name of the profile to remove",
                "required": True
            }
        }
    },
    # ============ Pool Extended Tools ============
    {
        "name": "pool_get",
        "description": "Get a specific parameter value from a pool. Use when user wants to check pool settings like size, min_size, pg_num, crush_rule.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            },
            "param": {
                "type": "string",
                "description": "Parameter to get (size, min_size, pg_num, pgp_num, crush_rule, all)",
                "required": True
            }
        }
    },
    {
        "name": "pool_rename",
        "description": "Rename a pool. Use when user wants to change a pool's name.",
        "parameters": {
            "old_name": {
                "type": "string",
                "description": "Current pool name",
                "required": True
            },
            "new_name": {
                "type": "string",
                "description": "New pool name",
                "required": True
            }
        }
    },
    {
        "name": "pool_get_quota",
        "description": "Get the object or byte quota for a pool. Use when user asks about pool limits or quotas.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            }
        }
    },
    {
        "name": "pool_set_quota",
        "description": "Set a quota (max objects or max bytes) on a pool. Use when user wants to limit pool usage.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            },
            "quota_type": {
                "type": "string",
                "description": "Quota type: 'max_objects' or 'max_bytes'",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "Quota value (e.g., '1000000' for max_objects, '10737418240' for max_bytes, '0' to remove quota)",
                "required": True
            }
        }
    },
    {
        "name": "pool_mksnap",
        "description": "Create a snapshot of a pool. Use when user wants to snapshot a pool.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            },
            "snap_name": {
                "type": "string",
                "description": "Snapshot name",
                "required": True
            }
        }
    },
    {
        "name": "pool_rmsnap",
        "description": "Remove a pool snapshot. Use when user wants to delete a pool snapshot.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            },
            "snap_name": {
                "type": "string",
                "description": "Snapshot name to remove",
                "required": True
            }
        }
    },
    {
        "name": "pool_application_enable",
        "description": "Enable an application tag on a pool (rgw, rbd, cephfs). Use when user creates a pool for a specific Ceph subsystem.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool name",
                "required": True
            },
            "app": {
                "type": "string",
                "description": "Application name: 'rgw', 'rbd', or 'cephfs'",
                "required": True
            }
        }
    },
    # ============ PG Extended Tools ============
    {
        "name": "pg_scrub",
        "description": "Initiate a (normal) scrub on a placement group to check metadata consistency. Use for routine integrity checks.",
        "parameters": {
            "pg_id": {
                "type": "string",
                "description": "Placement group ID (e.g., '1.2a')",
                "required": True
            }
        }
    },
    {
        "name": "pg_dump_stuck",
        "description": "Show placement groups stuck in a given state (inactive, unclean, stale, undersized, degraded). Use to find problematic PGs.",
        "parameters": {
            "state": {
                "type": "string",
                "description": "Stuck state to query: 'inactive', 'unclean', 'stale', 'undersized', 'degraded'",
                "default": "unclean"
            },
            "threshold_seconds": {
                "type": "integer",
                "description": "How long a PG must be stuck (seconds) to be reported",
                "default": 300
            }
        }
    },
    {
        "name": "pg_ls",
        "description": "List placement groups, optionally filtered by pool or OSD. Use when user wants to see PGs for a specific pool or OSD.",
        "parameters": {
            "pool_id": {
                "type": "integer",
                "description": "Optional pool ID to filter by",
                "default": None
            },
            "osd_id": {
                "type": "integer",
                "description": "Optional OSD ID to list PGs by OSD",
                "default": None
            },
            "state": {
                "type": "string",
                "description": "Optional PG state filter (e.g., 'active+clean', 'degraded')",
                "default": None
            }
        }
    },
    # ============ OSD Utilization Tools ============
    {
        "name": "osd_df",
        "description": "Show OSD utilization (disk usage per OSD). Use when user asks about OSD disk space, utilization, or imbalance.",
        "parameters": {
            "format": {
                "type": "string",
                "description": "Output format: 'plain' or 'tree' (tree shows CRUSH bucket hierarchy)",
                "default": "tree"
            }
        }
    },
    {
        "name": "osd_reweight_by_utilization",
        "description": "Automatically reweight outlier OSDs based on utilization. Only reweights OSDs whose utilization exceeds the threshold over average.",
        "parameters": {
            "threshold": {
                "type": "integer",
                "description": "Overload threshold percentage (default 120 means OSDs >20% above average)",
                "default": 120
            }
        }
    },
    {
        "name": "osd_blocklist_ls",
        "description": "List all blocklisted client addresses. Use when investigating client connectivity issues.",
        "parameters": {}
    },
    {
        "name": "osd_blocklist_add",
        "description": "Add a client address to the blocklist. Use when a misbehaving client needs to be blocked.",
        "parameters": {
            "addr": {
                "type": "string",
                "description": "Client address to blocklist (e.g., '10.0.0.100:0/123456')",
                "required": True
            },
            "expire_seconds": {
                "type": "number",
                "description": "Seconds until the blocklist entry expires",
                "default": 3600
            }
        }
    },
    # ============ RBD (Block Device) Tools ============
    {
        "name": "rbd_ls",
        "description": "List all RBD images in a pool. Use when user asks to list block images, volumes, or RBD devices.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool containing the RBD images (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_info",
        "description": "Show detailed information about an RBD image including size, features, snapshots, and data pool.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name of the RBD image",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool containing the image (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_create",
        "description": "Create a new RBD image with the specified size and optional features.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name for the new RBD image",
                "required": True
            },
            "size": {
                "type": "string",
                "description": "Image size (e.g., '10G', '500M', '1T')",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool in which to create the image (default: rbd)",
                "default": "rbd"
            },
            "image_feature": {
                "type": "string",
                "description": "Comma-separated image features (e.g., 'layering,exclusive-lock')",
                "default": "layering"
            }
        }
    },
    {
        "name": "rbd_rm",
        "description": "Remove (delete) an RBD image. This is destructive and cannot be undone.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name of the RBD image to remove",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool containing the image (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_snap_ls",
        "description": "List all snapshots of an RBD image.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name of the RBD image",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool containing the image (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_snap_create",
        "description": "Create a snapshot of an RBD image.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name of the RBD image",
                "required": True
            },
            "snap_name": {
                "type": "string",
                "description": "Name for the snapshot",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool containing the image (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_snap_rm",
        "description": "Remove a snapshot from an RBD image.",
        "parameters": {
            "image_name": {
                "type": "string",
                "description": "Name of the RBD image",
                "required": True
            },
            "snap_name": {
                "type": "string",
                "description": "Name of the snapshot to remove",
                "required": True
            },
            "pool_name": {
                "type": "string",
                "description": "Pool containing the image (default: rbd)",
                "default": "rbd"
            }
        }
    },
    {
        "name": "rbd_du",
        "description": "Show disk usage of RBD images in a pool, including provisioned and actual used space.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Pool to check (default: rbd)",
                "default": "rbd"
            },
            "image_name": {
                "type": "string",
                "description": "Specific image to check (optional, omit for all images)"
            }
        }
    },
    # ============ CephFS (File System) Tools ============
    {
        "name": "fs_ls",
        "description": "List all CephFS file systems in the cluster.",
        "parameters": {}
    },
    {
        "name": "fs_status",
        "description": "Show the status of a CephFS file system including MDS daemons, ranks, and client sessions.",
        "parameters": {
            "fs_name": {
                "type": "string",
                "description": "File system name (optional, shows all if omitted)"
            }
        }
    },
    {
        "name": "fs_new",
        "description": "Create a new CephFS file system with specified metadata and data pools.",
        "parameters": {
            "fs_name": {
                "type": "string",
                "description": "Name for the new file system",
                "required": True
            },
            "metadata_pool": {
                "type": "string",
                "description": "Name of the metadata pool",
                "required": True
            },
            "data_pool": {
                "type": "string",
                "description": "Name of the data pool",
                "required": True
            }
        }
    },
    {
        "name": "fs_rm",
        "description": "Remove a CephFS file system. Destructive operation that removes the filesystem metadata.",
        "parameters": {
            "fs_name": {
                "type": "string",
                "description": "Name of the file system to remove",
                "required": True
            },
            "confirm": {
                "type": "boolean",
                "description": "Must be true to confirm deletion",
                "required": True
            }
        }
    },
    {
        "name": "mds_stat",
        "description": "Show MDS (Metadata Server) status including active/standby ranks and health.",
        "parameters": {}
    },
    {
        "name": "fs_set",
        "description": "Set a CephFS file system parameter (e.g., max_mds, allow_standby_replay).",
        "parameters": {
            "fs_name": {
                "type": "string",
                "description": "Name of the file system",
                "required": True
            },
            "param": {
                "type": "string",
                "description": "Parameter name (e.g., 'max_mds', 'allow_standby_replay', 'standby_count_wanted')",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "Parameter value",
                "required": True
            }
        }
    },
    # ============ Device Health Tools ============
    {
        "name": "device_ls",
        "description": "List all storage devices known to the Ceph cluster with their daemon associations.",
        "parameters": {}
    },
    {
        "name": "device_info",
        "description": "Show detailed information about a specific storage device including SMART data and wear metrics.",
        "parameters": {
            "device_id": {
                "type": "string",
                "description": "Device ID (e.g., 'SAMSUNG_MZQLB960HAJR-00007_S3HKNX0M800154')",
                "required": True
            }
        }
    },
    {
        "name": "device_predict_life_expectancy",
        "description": "Query predicted life expectancy of a device based on SMART telemetry. Requires the diskprediction module.",
        "parameters": {
            "device_id": {
                "type": "string",
                "description": "Device ID to query prediction for",
                "required": True
            }
        }
    },
    {
        "name": "device_light",
        "description": "Control the identification/fault LED on a storage device for physical location.",
        "parameters": {
            "device_id": {
                "type": "string",
                "description": "Device ID",
                "required": True
            },
            "light_type": {
                "type": "string",
                "description": "LED type: 'ident' (identification) or 'fault'",
                "default": "ident"
            },
            "on": {
                "type": "boolean",
                "description": "True to turn on, False to turn off",
                "default": True
            }
        }
    },
    # ============ Crash Management Tools ============
    {
        "name": "crash_ls",
        "description": "List all daemon crash reports in the cluster, optionally showing only recent ones.",
        "parameters": {
            "recent": {
                "type": "number",
                "description": "Show crashes from the last N days (optional, omit for all)"
            }
        }
    },
    {
        "name": "crash_info",
        "description": "Show detailed information about a specific daemon crash including stack trace and metadata.",
        "parameters": {
            "crash_id": {
                "type": "string",
                "description": "Crash ID to inspect",
                "required": True
            }
        }
    },
    {
        "name": "crash_archive",
        "description": "Archive a specific crash report to silence the health warning.",
        "parameters": {
            "crash_id": {
                "type": "string",
                "description": "Crash ID to archive",
                "required": True
            }
        }
    },
    {
        "name": "crash_archive_all",
        "description": "Archive all unarchived crash reports to clear health warnings.",
        "parameters": {}
    },
    # ============ OSD Extended Tools ============
    {
        "name": "osd_dump",
        "description": "Dump the full OSD map including epoch, flags, pools, and all OSD entries with state and addresses.",
        "parameters": {}
    },
    {
        "name": "osd_find",
        "description": "Find the location (host, rack, root) and IP address of a specific OSD.",
        "parameters": {
            "osd_id": {
                "type": "number",
                "description": "OSD ID to locate",
                "required": True
            }
        }
    },
    {
        "name": "osd_metadata",
        "description": "Show full metadata for an OSD including device model, bluestore info, kernel version, and hardware details.",
        "parameters": {
            "osd_id": {
                "type": "number",
                "description": "OSD ID to query",
                "required": True
            }
        }
    },
    {
        "name": "osd_perf",
        "description": "Show OSD performance counters including commit and apply latency statistics.",
        "parameters": {}
    },
    {
        "name": "osd_pool_autoscale_status",
        "description": "Show the PG autoscaler status for all pools including target PG counts, actual counts, and scaling recommendations.",
        "parameters": {}
    },
    # ============ Config DB Tools ============
    {
        "name": "config_dump",
        "description": "Dump all configuration options set in the config database (mon configdb), showing who set what.",
        "parameters": {}
    },
    {
        "name": "config_get",
        "description": "Get the value of a specific configuration option for a given daemon type or daemon name.",
        "parameters": {
            "who": {
                "type": "string",
                "description": "Target daemon type or name (e.g., 'osd', 'mon', 'osd.0', 'global')",
                "required": True
            },
            "key": {
                "type": "string",
                "description": "Configuration key to query",
                "required": True
            }
        }
    },
    {
        "name": "config_set",
        "description": "Set a configuration value in the config database for a daemon type or specific daemon.",
        "parameters": {
            "who": {
                "type": "string",
                "description": "Target (e.g., 'osd', 'mon', 'osd.0', 'global')",
                "required": True
            },
            "key": {
                "type": "string",
                "description": "Configuration key to set",
                "required": True
            },
            "value": {
                "type": "string",
                "description": "Value to set",
                "required": True
            }
        }
    },
    {
        "name": "config_show",
        "description": "Show the running configuration of a specific daemon (requires the daemon to be running).",
        "parameters": {
            "who": {
                "type": "string",
                "description": "Daemon name (e.g., 'osd.0', 'mon.a', 'mgr.x')",
                "required": True
            }
        }
    },
    {
        "name": "config_log",
        "description": "Show recent configuration change log entries from the monitor config database.",
        "parameters": {
            "num_entries": {
                "type": "number",
                "description": "Number of recent entries to show",
                "default": 10
            }
        }
    },
    # ============ Balancer Tools ============
    {
        "name": "balancer_status",
        "description": "Show the current status of the PG balancer module including mode, active state, and last optimization.",
        "parameters": {}
    },
    {
        "name": "balancer_eval",
        "description": "Evaluate the current PG distribution score. Lower scores indicate better balance.",
        "parameters": {
            "pool_name": {
                "type": "string",
                "description": "Evaluate balance for a specific pool (optional, omit for cluster-wide)"
            }
        }
    },
    {
        "name": "balancer_optimize",
        "description": "Generate an optimization plan for PG distribution and optionally execute it.",
        "parameters": {
            "plan_name": {
                "type": "string",
                "description": "Name for the optimization plan",
                "required": True
            }
        }
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
