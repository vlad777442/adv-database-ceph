"""
Expanded test suite for Ceph LLM Agent evaluation.

Generates 100+ systematic test cases across all operation categories,
with controlled difficulty levels and edge cases.

Categories:
- search (semantic search, find similar)
- read (read_object, list_objects)
- write (create, update)
- delete (delete objects)
- stats (pool stats, cluster stats)
- cluster (health, OSD, PG, capacity, performance, diagnose)
- documentation (search docs, explain issues)
- complex (multi-step, compound queries)
- ambiguous (underspecified, vague queries)
- edge_cases (error handling, unusual input)
"""

from evaluation.evaluation_framework import TestCase


def generate_expanded_test_suite() -> list:
    """Generate 100+ test cases for comprehensive evaluation."""
    
    tests = []
    
    # ========== SEARCH OPERATIONS (15 tests) ==========
    
    tests.extend([
        # Easy: direct search queries
        TestCase(
            id="search_001", query="find files about kubernetes",
            expected_intent="semantic_search",
            expected_parameters={"query": "kubernetes"},
            expected_response_contains=["search", "object"],
            category="search", difficulty="easy"
        ),
        TestCase(
            id="search_002", query="look for documents mentioning configuration",
            expected_intent="semantic_search",
            expected_parameters={"query": "configuration"},
            category="search", difficulty="easy"
        ),
        TestCase(
            id="search_003", query="search for backup related files",
            expected_intent="semantic_search",
            expected_parameters={"query": "backup"},
            category="search", difficulty="easy"
        ),
        TestCase(
            id="search_004", query="find all yaml files",
            expected_intent="semantic_search",
            expected_parameters={"query": "yaml"},
            category="search", difficulty="easy"
        ),
        TestCase(
            id="search_005", query="look for anything about monitoring",
            expected_intent="semantic_search",
            expected_parameters={"query": "monitoring"},
            category="search", difficulty="easy"
        ),
        
        # Medium: indirect/implicit search queries
        TestCase(
            id="search_006", query="which objects talk about performance tuning?",
            expected_intent="semantic_search",
            expected_parameters={"query": "performance tuning"},
            category="search", difficulty="medium"
        ),
        TestCase(
            id="search_007", query="I need to find my network configuration files",
            expected_intent="semantic_search",
            expected_parameters={"query": "network configuration"},
            category="search", difficulty="medium"
        ),
        TestCase(
            id="search_008", query="are there any documents about ceph replication?",
            expected_intent="semantic_search",
            expected_parameters={"query": "ceph replication"},
            category="search", difficulty="medium"
        ),
        TestCase(
            id="search_009", query="what files contain references to storage quotas?",
            expected_intent="semantic_search",
            expected_parameters={"query": "storage quotas"},
            category="search", difficulty="medium"
        ),
        
        # Hard: similarity and complex search
        TestCase(
            id="search_010", query="show me all files similar to config.yaml",
            expected_intent="find_similar",
            expected_parameters={"object_name": "config.yaml"},
            category="search", difficulty="hard"
        ),
        TestCase(
            id="search_011", query="find documents that are similar in content to test.txt",
            expected_intent="find_similar",
            expected_parameters={"object_name": "test.txt"},
            category="search", difficulty="hard"
        ),
        TestCase(
            id="search_012", query="which files resemble readme.md?",
            expected_intent="find_similar",
            expected_parameters={"object_name": "readme.md"},
            category="search", difficulty="hard"
        ),
        TestCase(
            id="search_013", query="search for Python scripts related to data processing",
            expected_intent="semantic_search",
            expected_parameters={"query": "Python data processing"},
            category="search", difficulty="medium"
        ),
        TestCase(
            id="search_014", query="find anything mentioning SSL or TLS certificates",
            expected_intent="semantic_search",
            expected_parameters={"query": "SSL TLS certificates"},
            category="search", difficulty="medium"
        ),
        TestCase(
            id="search_015", query="do we have any deployment manifests?",
            expected_intent="semantic_search",
            expected_parameters={"query": "deployment manifests"},
            category="search", difficulty="medium"
        ),
    ])
    
    # ========== READ OPERATIONS (15 tests) ==========
    
    tests.extend([
        # Easy: direct read
        TestCase(
            id="read_001", query="show me the content of test.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "test.txt"},
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_002", query="what's in the file called readme.md",
            expected_intent="read_object",
            expected_parameters={"object_name": "readme.md"},
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_003", query="read hello.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "hello.txt"},
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_004", query="display the file test_config.yaml",
            expected_intent="read_object",
            expected_parameters={"object_name": "test_config.yaml"},
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_005", query="cat test.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "test.txt"},
            category="read", difficulty="easy"
        ),
        
        # Easy: list operations
        TestCase(
            id="read_006", query="list all objects in the pool",
            expected_intent="list_objects",
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_007", query="show me all files",
            expected_intent="list_objects",
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_008", query="what objects are stored?",
            expected_intent="list_objects",
            category="read", difficulty="easy"
        ),
        TestCase(
            id="read_009", query="ls",
            expected_intent="list_objects",
            category="read", difficulty="easy"
        ),
        
        # Medium: filtered list
        TestCase(
            id="read_010", query="show me files starting with config",
            expected_intent="list_objects",
            expected_parameters={"prefix": "config"},
            category="read", difficulty="medium"
        ),
        TestCase(
            id="read_011", query="list all objects that begin with test",
            expected_intent="list_objects",
            expected_parameters={"prefix": "test"},
            category="read", difficulty="medium"
        ),
        TestCase(
            id="read_012", query="what .txt files do we have?",
            expected_intent="list_objects",
            category="read", difficulty="medium"
        ),
        
        # Hard: read with context
        TestCase(
            id="read_013", query="open the readme and tell me what it says",
            expected_intent="read_object",
            expected_parameters={"object_name": "readme.md"},
            category="read", difficulty="hard"
        ),
        TestCase(
            id="read_014", query="I want to see the contents of that yaml file",
            expected_intent="read_object",
            category="read", difficulty="hard"
        ),
        TestCase(
            id="read_015", query="print out everything in test.txt for me",
            expected_intent="read_object",
            expected_parameters={"object_name": "test.txt"},
            category="read", difficulty="hard"
        ),
    ])
    
    # ========== WRITE OPERATIONS (12 tests) ==========
    
    tests.extend([
        # Easy: explicit create
        TestCase(
            id="write_001", query="create a new file called hello.txt with content Hello World",
            expected_intent="create_object",
            expected_parameters={"object_name": "hello.txt", "content": "Hello World"},
            category="write", difficulty="easy"
        ),
        TestCase(
            id="write_002", query="store a new object named data.json with content {}",
            expected_intent="create_object",
            expected_parameters={"object_name": "data.json"},
            category="write", difficulty="easy"
        ),
        TestCase(
            id="write_003", query="make a file notes.txt containing meeting notes for today",
            expected_intent="create_object",
            expected_parameters={"object_name": "notes.txt"},
            category="write", difficulty="easy"
        ),
        TestCase(
            id="write_004", query="write a file called config.ini with content [default]",
            expected_intent="create_object",
            expected_parameters={"object_name": "config.ini"},
            category="write", difficulty="easy"
        ),
        
        # Medium: update existing
        TestCase(
            id="write_005", query="update the file test.txt with new content: This is updated",
            expected_intent="update_object",
            expected_parameters={"object_name": "test.txt"},
            category="write", difficulty="medium"
        ),
        TestCase(
            id="write_006", query="modify hello.txt to say Goodbye World",
            expected_intent="update_object",
            expected_parameters={"object_name": "hello.txt"},
            category="write", difficulty="medium"
        ),
        TestCase(
            id="write_007", query="replace the content of readme.md with new documentation",
            expected_intent="update_object",
            expected_parameters={"object_name": "readme.md"},
            category="write", difficulty="medium"
        ),
        TestCase(
            id="write_008", query="overwrite data.json with {\"version\": 2}",
            expected_intent="update_object",
            expected_parameters={"object_name": "data.json"},
            category="write", difficulty="medium"
        ),
        
        # Hard: implicit write
        TestCase(
            id="write_009", query="save these meeting notes to a file: Sprint planning discussion",
            expected_intent="create_object",
            category="write", difficulty="hard"
        ),
        TestCase(
            id="write_010", query="put the string 'server: ceph01' into cluster_config.txt",
            expected_intent="create_object",
            expected_parameters={"object_name": "cluster_config.txt"},
            category="write", difficulty="hard"
        ),
        TestCase(
            id="write_011", query="I need to upload a configuration snippet: pool_size=3",
            expected_intent="create_object",
            category="write", difficulty="hard"
        ),
        TestCase(
            id="write_012", query="append error log entry to debug.log",
            expected_intent="update_object",
            expected_parameters={"object_name": "debug.log"},
            category="write", difficulty="hard"
        ),
    ])
    
    # ========== DELETE OPERATIONS (8 tests) ==========
    
    tests.extend([
        TestCase(
            id="delete_001", query="delete the file old_file.txt",
            expected_intent="delete_object",
            expected_parameters={"object_name": "old_file.txt"},
            category="delete", difficulty="easy"
        ),
        TestCase(
            id="delete_002", query="remove test.txt from storage",
            expected_intent="delete_object",
            expected_parameters={"object_name": "test.txt"},
            category="delete", difficulty="easy"
        ),
        TestCase(
            id="delete_003", query="rm temp_file.dat",
            expected_intent="delete_object",
            expected_parameters={"object_name": "temp_file.dat"},
            category="delete", difficulty="easy"
        ),
        TestCase(
            id="delete_004", query="erase the backup_old.tar.gz file",
            expected_intent="delete_object",
            expected_parameters={"object_name": "backup_old.tar.gz"},
            category="delete", difficulty="easy"
        ),
        TestCase(
            id="delete_005", query="I don't need old_config.yaml anymore, get rid of it",
            expected_intent="delete_object",
            expected_parameters={"object_name": "old_config.yaml"},
            category="delete", difficulty="medium"
        ),
        TestCase(
            id="delete_006", query="purge the log file access.log",
            expected_intent="delete_object",
            expected_parameters={"object_name": "access.log"},
            category="delete", difficulty="medium"
        ),
        TestCase(
            id="delete_007", query="clean up the temporary file /tmp_data.bin",
            expected_intent="delete_object",
            category="delete", difficulty="hard"
        ),
        TestCase(
            id="delete_008", query="destroy scratch.txt",
            expected_intent="delete_object",
            expected_parameters={"object_name": "scratch.txt"},
            category="delete", difficulty="medium"
        ),
    ])
    
    # ========== STATS OPERATIONS (8 tests) ==========
    
    tests.extend([
        TestCase(
            id="stats_001", query="show me storage statistics",
            expected_intent="get_stats",
            category="stats", difficulty="easy"
        ),
        TestCase(
            id="stats_002", query="how much space is being used",
            expected_intent="get_stats",
            category="stats", difficulty="easy"
        ),
        TestCase(
            id="stats_003", query="what's the pool utilization?",
            expected_intent="get_stats",
            category="stats", difficulty="easy"
        ),
        TestCase(
            id="stats_004", query="show me disk usage",
            expected_intent="get_stats",
            category="stats", difficulty="easy"
        ),
        TestCase(
            id="stats_005", query="how many objects are in the pool?",
            expected_intent="get_stats",
            category="stats", difficulty="medium"
        ),
        TestCase(
            id="stats_006", query="give me pool statistics including IOPS",
            expected_intent="get_stats",
            category="stats", difficulty="medium"
        ),
        TestCase(
            id="stats_007", query="what's the storage efficiency ratio?",
            expected_intent="get_stats",
            category="stats", difficulty="hard"
        ),
        TestCase(
            id="stats_008", query="df",
            expected_intent="get_stats",
            category="stats", difficulty="medium"
        ),
    ])
    
    # ========== CLUSTER OPERATIONS (20 tests) ==========
    
    tests.extend([
        # Health checks
        TestCase(
            id="cluster_001", query="is the cluster healthy?",
            expected_intent="cluster_health",
            expected_response_contains=["health", "status"],
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_002", query="what's the status of the cluster?",
            expected_intent="cluster_health",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_003", query="check ceph cluster health",
            expected_intent="cluster_health",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_004", query="any warnings or errors in the cluster?",
            expected_intent="cluster_health",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_005", query="is everything OK with ceph?",
            expected_intent="cluster_health",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        
        # OSD operations
        TestCase(
            id="cluster_006", query="show me OSD status",
            expected_intent="osd_status",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_007", query="how many OSDs are up?",
            expected_intent="osd_status",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_008", query="are all OSDs running?",
            expected_intent="osd_status",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_009", query="which OSDs are down?",
            expected_intent="osd_status",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_010", query="OSD tree",
            expected_intent="osd_status",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        
        # PG operations
        TestCase(
            id="cluster_011", query="are there any degraded PGs?",
            expected_intent="pg_status",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_012", query="show me placement group status",
            expected_intent="pg_status",
            category="cluster", difficulty="easy", requires_ceph=True
        ),
        TestCase(
            id="cluster_013", query="any PGs stuck peering?",
            expected_intent="pg_status",
            category="cluster", difficulty="hard", requires_ceph=True
        ),
        
        # Capacity and performance
        TestCase(
            id="cluster_014", query="when will the storage be full?",
            expected_intent="capacity_prediction",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_015", query="predict storage capacity usage",
            expected_intent="capacity_prediction",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_016", query="what's the current throughput?",
            expected_intent="performance_stats",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="cluster_017", query="show me IOPS and bandwidth",
            expected_intent="performance_stats",
            category="cluster", difficulty="medium", requires_ceph=True
        ),
        
        # Diagnostics
        TestCase(
            id="cluster_018", query="diagnose any problems with my ceph cluster",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="cluster_019", query="troubleshoot slow operations",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="cluster_020", query="why is my cluster reporting HEALTH_WARN?",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="hard", requires_ceph=True
        ),
    ])
    
    # ========== DOCUMENTATION OPERATIONS (10 tests) ==========
    
    tests.extend([
        TestCase(
            id="docs_001", query="how do I configure erasure coding?",
            expected_intent="search_docs",
            expected_parameters={"query": "erasure coding"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_002", query="what is a placement group?",
            expected_intent="search_docs",
            expected_response_contains=["PG", "placement"],
            category="documentation", difficulty="easy"
        ),
        TestCase(
            id="docs_003", query="explain why my OSDs are down",
            expected_intent="explain_issue",
            expected_parameters={"topic": "OSD"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_004", query="how to set up CRUSH map?",
            expected_intent="search_docs",
            expected_parameters={"query": "CRUSH map"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_005", query="what is BlueStore?",
            expected_intent="search_docs",
            expected_parameters={"query": "BlueStore"},
            category="documentation", difficulty="easy"
        ),
        TestCase(
            id="docs_006", query="how does Ceph replication work?",
            expected_intent="search_docs",
            expected_parameters={"query": "replication"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_007", query="explain the OSD recovery process",
            expected_intent="explain_issue",
            expected_parameters={"topic": "OSD recovery"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_008", query="what happens when a node fails?",
            expected_intent="search_docs",
            expected_parameters={"query": "node failure"},
            category="documentation", difficulty="medium"
        ),
        TestCase(
            id="docs_009", query="tell me about ceph authentication",
            expected_intent="search_docs",
            expected_parameters={"query": "authentication"},
            category="documentation", difficulty="easy"
        ),
        TestCase(
            id="docs_010", query="how to tune ceph performance?",
            expected_intent="search_docs",
            expected_parameters={"query": "performance tuning"},
            category="documentation", difficulty="hard"
        ),
    ])
    
    # ========== COMPLEX / MULTI-STEP QUERIES (10 tests) ==========
    
    tests.extend([
        TestCase(
            id="complex_001", query="find all python files and show me the first one",
            expected_intent="semantic_search",
            expected_parameters={"query": "python"},
            category="complex", difficulty="hard"
        ),
        TestCase(
            id="complex_002", query="check cluster health and tell me if any OSDs are down",
            expected_intent="cluster_health",
            category="complex", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="complex_003", query="list all objects then read the first .txt file",
            expected_intent="list_objects",
            category="complex", difficulty="hard"
        ),
        TestCase(
            id="complex_004", query="search for config files and show me their contents",
            expected_intent="semantic_search",
            expected_parameters={"query": "config"},
            category="complex", difficulty="hard"
        ),
        TestCase(
            id="complex_005", query="check health and if there are issues, diagnose them",
            expected_intent="cluster_health",
            category="complex", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="complex_006", query="how much storage is free and when will it fill up?",
            expected_intent="get_stats",
            category="complex", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="complex_007", query="back up test.txt by creating test.txt.bak with same content",
            expected_intent="create_object",
            expected_parameters={"object_name": "test.txt.bak"},
            category="complex", difficulty="hard"
        ),
        TestCase(
            id="complex_008", query="show me storage stats then explain if anything is wrong",
            expected_intent="get_stats",
            category="complex", difficulty="hard", requires_ceph=True
        ),
        TestCase(
            id="complex_009", query="find all logs and delete any older than a week",
            expected_intent="semantic_search",
            expected_parameters={"query": "logs"},
            category="complex", difficulty="hard"
        ),
        TestCase(
            id="complex_010", query="check how many objects exist and summarize the pool state",
            expected_intent="get_stats",
            category="complex", difficulty="hard"
        ),
    ])
    
    # ========== AMBIGUOUS QUERIES (10 tests) ==========
    
    tests.extend([
        TestCase(
            id="ambig_001", query="show me everything",
            expected_intent="list_objects",
            category="ambiguous", difficulty="hard"
        ),
        TestCase(
            id="ambig_002", query="help",
            expected_intent="help",
            category="ambiguous", difficulty="easy"
        ),
        TestCase(
            id="ambig_003", query="status",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="ambig_004", query="what can you do?",
            expected_intent="help",
            category="ambiguous", difficulty="easy"
        ),
        TestCase(
            id="ambig_005", query="show me stuff",
            expected_intent="list_objects",
            category="ambiguous", difficulty="hard"
        ),
        TestCase(
            id="ambig_006", query="info",
            expected_intent="get_stats",
            category="ambiguous", difficulty="hard"
        ),
        TestCase(
            id="ambig_007", query="what do we have?",
            expected_intent="list_objects",
            category="ambiguous", difficulty="hard"
        ),
        TestCase(
            id="ambig_008", query="tell me about this cluster",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="ambig_009", query="hello",
            expected_intent="help",
            category="ambiguous", difficulty="easy"
        ),
        TestCase(
            id="ambig_010", query="ceph",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="hard", requires_ceph=True
        ),
    ])
    
    # ========== EDGE CASES (12 tests) ==========
    
    tests.extend([
        # Empty/minimal input
        TestCase(
            id="edge_001", query="",
            expected_intent="help",
            category="edge_cases", difficulty="hard"
        ),
        TestCase(
            id="edge_002", query="???",
            expected_intent="help",
            category="edge_cases", difficulty="hard"
        ),
        
        # Typos and misspellings
        TestCase(
            id="edge_003", query="serch for config files",
            expected_intent="semantic_search",
            expected_parameters={"query": "config"},
            category="edge_cases", difficulty="hard"
        ),
        TestCase(
            id="edge_004", query="delet old_file.txt",
            expected_intent="delete_object",
            expected_parameters={"object_name": "old_file.txt"},
            category="edge_cases", difficulty="hard"
        ),
        
        # Special characters
        TestCase(
            id="edge_005", query="read file with spaces: my file.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "my file.txt"},
            category="edge_cases", difficulty="hard"
        ),
        TestCase(
            id="edge_006", query="find files matching *.yaml",
            expected_intent="semantic_search",
            expected_parameters={"query": "yaml"},
            category="edge_cases", difficulty="medium"
        ),
        
        # Non-existent objects
        TestCase(
            id="edge_007", query="read nonexistent_file_xyz.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "nonexistent_file_xyz.txt"},
            category="edge_cases", difficulty="easy"
        ),
        
        # Very long queries
        TestCase(
            id="edge_008",
            query="I have a very important question about the status of my ceph storage cluster and I want to know if all the OSDs are running properly and if there are any placement groups that might be degraded or stuck in peering state",
            expected_intent="cluster_health",
            category="edge_cases", difficulty="hard", requires_ceph=True
        ),
        
        # Conversational style
        TestCase(
            id="edge_009", query="hey, could you please show me what files we have stored?",
            expected_intent="list_objects",
            category="edge_cases", difficulty="medium"
        ),
        TestCase(
            id="edge_010", query="so I was wondering, is there a file called test.txt?",
            expected_intent="read_object",
            expected_parameters={"object_name": "test.txt"},
            category="edge_cases", difficulty="hard"
        ),
        
        # Technical shorthand
        TestCase(
            id="edge_011", query="ceph -s",
            expected_intent="cluster_health",
            category="edge_cases", difficulty="medium", requires_ceph=True
        ),
        TestCase(
            id="edge_012", query="rados ls",
            expected_intent="list_objects",
            category="edge_cases", difficulty="medium"
        ),
    ])
    
    return tests


def get_test_suite_stats(tests: list) -> dict:
    """Get statistics about the test suite."""
    from collections import Counter
    
    categories = Counter(t.category for t in tests)
    difficulties = Counter(t.difficulty for t in tests)
    requires_ceph = sum(1 for t in tests if t.requires_ceph)
    
    return {
        "total": len(tests),
        "categories": dict(categories),
        "difficulties": dict(difficulties),
        "requires_ceph": requires_ceph,
        "no_ceph": len(tests) - requires_ceph,
    }


# Make tests available as module-level constant
EXPANDED_TEST_CASES = generate_expanded_test_suite()
