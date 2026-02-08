"""
Tool registry defining available functions for LLM agent.
"""

from typing import List, Dict, Any


# Tool definitions for function calling
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
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
        "description": "List all objects in the Ceph pool, optionally filtered by prefix. Use this when user wants to see what files exist.",
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
        "name": "create_object",
        "description": "Create a new object in Ceph storage with specified content. Use this when user wants to create, write, or save a new file.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Name for the new object",
                "required": True
            },
            "content": {
                "type": "string",
                "description": "Content to write to the object",
                "required": True
            },
            "auto_index": {
                "type": "boolean",
                "description": "Whether to automatically index the object for search",
                "default": True
            }
        }
    },
    {
        "name": "update_object",
        "description": "Update an existing object with new content. Use this when user wants to modify or update a file.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Name of the object to update",
                "required": True
            },
            "content": {
                "type": "string",
                "description": "New content for the object",
                "required": True
            },
            "append": {
                "type": "boolean",
                "description": "Whether to append instead of replace",
                "default": False
            }
        }
    },
    {
        "name": "delete_object",
        "description": "Delete an object from Ceph storage. Use this when user wants to remove or delete a file. REQUIRES CONFIRMATION.",
        "parameters": {
            "object_name": {
                "type": "string",
                "description": "Name of the object to delete",
                "required": True
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
        "description": "Get statistics for all pools in the cluster. Use when user asks about pool usage, pool sizes, or pool information.",
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
