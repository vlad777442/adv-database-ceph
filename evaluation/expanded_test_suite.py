"""
Expanded test suite for Ceph LLM Agent evaluation.

Generates systematic test cases across all operation categories,
with controlled difficulty levels (canonical, paraphrase, ambiguous, risky) and edge cases.

Categories:
- cluster (health, OSD, PG, capacity, performance, diagnose)
- documentation (search docs, explain issues)
- complex (multi-step, compound queries)
- ambiguous (underspecified, vague queries)
- edge_cases (error handling, unusual input)
"""

from evaluation.evaluation_framework import TestCase


def generate_expanded_test_suite() -> list:
    """Generate test cases for comprehensive evaluation."""
    
    tests = []
    
    # ========== CLUSTER OPERATIONS (20 tests) ==========
    
    tests.extend([
        # Health checks
        TestCase(
            id="cluster_001", query="is the cluster healthy?",
            expected_intent="cluster_health",
            expected_response_contains=["health", "status"],
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_002", query="what's the status of the cluster?",
            expected_intent="cluster_health",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_003", query="check ceph cluster health",
            expected_intent="cluster_health",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_004", query="any warnings or errors in the cluster?",
            expected_intent="cluster_health",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_005", query="is everything OK with ceph?",
            expected_intent="cluster_health",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        
        # OSD operations
        TestCase(
            id="cluster_006", query="show me OSD status",
            expected_intent="osd_status",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_007", query="how many OSDs are up?",
            expected_intent="osd_status",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_008", query="are all OSDs running?",
            expected_intent="osd_status",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_009", query="which OSDs are down?",
            expected_intent="osd_status",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_010", query="OSD tree",
            expected_intent="osd_status",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        
        # PG operations
        TestCase(
            id="cluster_011", query="are there any degraded PGs?",
            expected_intent="pg_status",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_012", query="show me placement group status",
            expected_intent="pg_status",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_013", query="any PGs stuck peering?",
            expected_intent="pg_status",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        
        # Capacity and performance
        TestCase(
            id="cluster_014", query="when will the storage be full?",
            expected_intent="capacity_prediction",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_015", query="predict storage capacity usage",
            expected_intent="capacity_prediction",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_016", query="what's the current throughput?",
            expected_intent="performance_stats",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_017", query="show me IOPS and bandwidth",
            expected_intent="performance_stats",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        
        # Diagnostics
        TestCase(
            id="cluster_018", query="diagnose any problems with my ceph cluster",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="canonical", requires_ceph=True
        ),
        TestCase(
            id="cluster_019", query="troubleshoot slow operations",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="cluster_020", query="why is my cluster reporting HEALTH_WARN?",
            expected_intent="diagnose_cluster",
            category="cluster", difficulty="paraphrase", requires_ceph=True
        ),
    ])
    
    # ========== DOCUMENTATION OPERATIONS (10 tests) ==========
    
    tests.extend([
        TestCase(
            id="docs_001", query="how do I configure erasure coding?",
            expected_intent="search_docs",
            expected_parameters={"query": "erasure coding"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_002", query="what is a placement group?",
            expected_intent="search_docs",
            expected_response_contains=["PG", "placement"],
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_003", query="explain why my OSDs are down",
            expected_intent="explain_issue",
            expected_parameters={"topic": "OSD"},
            category="documentation", difficulty="paraphrase"
        ),
        TestCase(
            id="docs_004", query="how to set up CRUSH map?",
            expected_intent="search_docs",
            expected_parameters={"query": "CRUSH map"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_005", query="what is BlueStore?",
            expected_intent="search_docs",
            expected_parameters={"query": "BlueStore"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_006", query="how does Ceph replication work?",
            expected_intent="search_docs",
            expected_parameters={"query": "replication"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_007", query="explain the OSD recovery process",
            expected_intent="explain_issue",
            expected_parameters={"topic": "OSD recovery"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_008", query="what happens when a node fails?",
            expected_intent="search_docs",
            expected_parameters={"query": "node failure"},
            category="documentation", difficulty="paraphrase"
        ),
        TestCase(
            id="docs_009", query="tell me about ceph authentication",
            expected_intent="search_docs",
            expected_parameters={"query": "authentication"},
            category="documentation", difficulty="canonical"
        ),
        TestCase(
            id="docs_010", query="how to tune ceph performance?",
            expected_intent="search_docs",
            expected_parameters={"query": "performance tuning"},
            category="documentation", difficulty="paraphrase"
        ),
    ])
    
    # ========== COMPLEX / MULTI-STEP QUERIES (6 tests) ==========
    
    tests.extend([
        TestCase(
            id="complex_002", query="check cluster health and tell me if any OSDs are down",
            expected_intent="cluster_health",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="complex_005", query="check health and if there are issues, diagnose them",
            expected_intent="cluster_health",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="complex_006", query="how much storage is free and when will it fill up?",
            expected_intent="capacity_prediction",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="complex_008", query="show me cluster stats then explain if anything is wrong",
            expected_intent="diagnose_cluster",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="complex_010", query="check pool utilization and summarize the pool state",
            expected_intent="pool_stats",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
        TestCase(
            id="complex_011", query="which OSDs are near full and should I rebalance?",
            expected_intent="osd_status",
            category="complex", difficulty="paraphrase", requires_ceph=True
        ),
    ])
    
    # ========== AMBIGUOUS QUERIES (7 tests) ==========
    
    tests.extend([
        TestCase(
            id="ambig_001", query="show me everything",
            expected_intent="pool_stats",
            category="ambiguous", difficulty="ambiguous", requires_ceph=True
        ),
        TestCase(
            id="ambig_002", query="help",
            expected_intent="help",
            category="ambiguous", difficulty="ambiguous"
        ),
        TestCase(
            id="ambig_003", query="status",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="ambiguous", requires_ceph=True
        ),
        TestCase(
            id="ambig_004", query="what can you do?",
            expected_intent="help",
            category="ambiguous", difficulty="ambiguous"
        ),
        TestCase(
            id="ambig_008", query="tell me about this cluster",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="ambiguous", requires_ceph=True
        ),
        TestCase(
            id="ambig_009", query="hello",
            expected_intent="help",
            category="ambiguous", difficulty="ambiguous"
        ),
        TestCase(
            id="ambig_010", query="ceph",
            expected_intent="cluster_health",
            category="ambiguous", difficulty="ambiguous", requires_ceph=True
        ),
    ])
    
    # ========== EDGE CASES (7 tests) ==========
    
    tests.extend([
        # Empty/minimal input
        TestCase(
            id="edge_001", query="",
            expected_intent="help",
            category="edge_cases", difficulty="ambiguous"
        ),
        TestCase(
            id="edge_002", query="???",
            expected_intent="help",
            category="edge_cases", difficulty="ambiguous"
        ),
        
        # Typos and misspellings
        TestCase(
            id="edge_004", query="delet old_file.txt",
            expected_intent="delete_object",
            expected_parameters={"object_name": "old_file.txt"},
            category="edge_cases", difficulty="ambiguous"
        ),
        
        # Very long queries
        TestCase(
            id="edge_008",
            query="I have a very important question about the status of my ceph storage cluster and I want to know if all the OSDs are running properly and if there are any placement groups that might be degraded or stuck in peering state",
            expected_intent="cluster_health",
            category="edge_cases", difficulty="ambiguous", requires_ceph=True
        ),
        
        # Conversational style
        TestCase(
            id="edge_009", query="hey, could you please show me overall pool utilization?",
            expected_intent="pool_stats",
            category="edge_cases", difficulty="ambiguous", requires_ceph=True
        ),
        
        # Technical shorthand
        TestCase(
            id="edge_011", query="ceph -s",
            expected_intent="cluster_health",
            category="edge_cases", difficulty="ambiguous", requires_ceph=True
        ),
        TestCase(
            id="edge_012", query="ceph osd tree",
            expected_intent="osd_status",
            category="edge_cases", difficulty="ambiguous", requires_ceph=True
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
