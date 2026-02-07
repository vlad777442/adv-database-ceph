"""
Evaluation Framework for Ceph LLM Agent.

Provides comprehensive evaluation capabilities for:
- Intent classification accuracy
- Response quality metrics
- Latency benchmarking
- Comparison with manual CLI operations
"""

import logging
import time
import json
import statistics
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of evaluation metrics."""
    ACCURACY = "accuracy"
    LATENCY = "latency"
    QUALITY = "quality"
    EFFICIENCY = "efficiency"


@dataclass
class TestCase:
    """A single test case for evaluation."""
    id: str
    query: str
    expected_intent: str
    expected_parameters: Dict[str, Any] = field(default_factory=dict)
    expected_response_contains: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "easy"  # easy, medium, hard
    requires_ceph: bool = False  # Whether test needs live Ceph cluster


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_id: str
    success: bool
    predicted_intent: str
    expected_intent: str
    intent_correct: bool
    parameters_correct: bool
    response_contains_expected: bool
    latency_ms: float
    response: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    """Complete evaluation report."""
    timestamp: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    
    # Accuracy metrics
    intent_accuracy: float
    parameter_accuracy: float
    response_quality: float
    
    # Latency metrics
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    
    # Category breakdown
    category_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Individual results
    results: List[TestResult] = field(default_factory=list)
    
    # Comparison metrics
    cli_comparison: Optional[Dict[str, Any]] = None


class EvaluationFramework:
    """
    Framework for evaluating Ceph LLM Agent performance.
    
    Capabilities:
    - Run test suites
    - Measure intent classification accuracy
    - Benchmark response latency
    - Compare with CLI operations
    - Generate reports
    """
    
    # Built-in test cases
    DEFAULT_TEST_CASES = [
        # Search operations
        TestCase(
            id="search_001",
            query="find files about kubernetes",
            expected_intent="semantic_search",
            expected_parameters={"query": "kubernetes"},
            expected_response_contains=["search", "object"],
            category="search",
            difficulty="easy"
        ),
        TestCase(
            id="search_002",
            query="look for documents mentioning configuration",
            expected_intent="semantic_search",
            expected_parameters={"query": "configuration"},
            category="search",
            difficulty="easy"
        ),
        TestCase(
            id="search_003",
            query="show me all files similar to config.yaml",
            expected_intent="find_similar",
            expected_parameters={"object_name": "config.yaml"},
            category="search",
            difficulty="medium"
        ),
        
        # Read operations
        TestCase(
            id="read_001",
            query="show me the content of test.txt",
            expected_intent="read_object",
            expected_parameters={"object_name": "test.txt"},
            category="read",
            difficulty="easy"
        ),
        TestCase(
            id="read_002",
            query="what's in the file called readme.md",
            expected_intent="read_object",
            expected_parameters={"object_name": "readme.md"},
            category="read",
            difficulty="easy"
        ),
        TestCase(
            id="read_003",
            query="list all objects in the pool",
            expected_intent="list_objects",
            category="read",
            difficulty="easy"
        ),
        TestCase(
            id="read_004",
            query="show me files starting with config",
            expected_intent="list_objects",
            expected_parameters={"prefix": "config"},
            category="read",
            difficulty="medium"
        ),
        
        # Write operations
        TestCase(
            id="write_001",
            query="create a new file called hello.txt with content Hello World",
            expected_intent="create_object",
            expected_parameters={"object_name": "hello.txt", "content": "Hello World"},
            category="write",
            difficulty="easy"
        ),
        TestCase(
            id="write_002",
            query="update the file test.txt with new content: This is updated",
            expected_intent="update_object",
            expected_parameters={"object_name": "test.txt"},
            category="write",
            difficulty="medium"
        ),
        
        # Delete operations
        TestCase(
            id="delete_001",
            query="delete the file old_file.txt",
            expected_intent="delete_object",
            expected_parameters={"object_name": "old_file.txt"},
            category="delete",
            difficulty="easy"
        ),
        TestCase(
            id="delete_002",
            query="remove test.txt from storage",
            expected_intent="delete_object",
            expected_parameters={"object_name": "test.txt"},
            category="delete",
            difficulty="easy"
        ),
        
        # Stats operations
        TestCase(
            id="stats_001",
            query="show me storage statistics",
            expected_intent="get_stats",
            category="stats",
            difficulty="easy"
        ),
        TestCase(
            id="stats_002",
            query="how much space is being used",
            expected_intent="get_stats",
            category="stats",
            difficulty="easy"
        ),
        
        # Cluster management
        TestCase(
            id="cluster_001",
            query="is the cluster healthy?",
            expected_intent="cluster_health",
            expected_response_contains=["health", "status"],
            category="cluster",
            difficulty="easy",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_002",
            query="what's the status of the cluster?",
            expected_intent="cluster_health",
            category="cluster",
            difficulty="easy",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_003",
            query="diagnose any problems with my ceph cluster",
            expected_intent="diagnose_cluster",
            category="cluster",
            difficulty="medium",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_004",
            query="show me OSD status",
            expected_intent="osd_status",
            category="cluster",
            difficulty="easy",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_005",
            query="are there any degraded PGs?",
            expected_intent="pg_status",
            category="cluster",
            difficulty="medium",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_006",
            query="when will the storage be full?",
            expected_intent="capacity_prediction",
            category="cluster",
            difficulty="medium",
            requires_ceph=True
        ),
        TestCase(
            id="cluster_007",
            query="what's the current throughput?",
            expected_intent="performance_stats",
            category="cluster",
            difficulty="medium",
            requires_ceph=True
        ),
        
        # Documentation/Help
        TestCase(
            id="docs_001",
            query="how do I configure erasure coding?",
            expected_intent="search_docs",
            expected_parameters={"query": "erasure coding"},
            category="documentation",
            difficulty="medium"
        ),
        TestCase(
            id="docs_002",
            query="what is a placement group?",
            expected_intent="search_docs",
            expected_response_contains=["PG", "placement"],
            category="documentation",
            difficulty="easy"
        ),
        TestCase(
            id="docs_003",
            query="explain why my OSDs are down",
            expected_intent="explain_issue",
            expected_parameters={"topic": "OSD"},
            category="documentation",
            difficulty="medium"
        ),
        
        # Complex queries
        TestCase(
            id="complex_001",
            query="find all python files and show me the first one",
            expected_intent="semantic_search",
            expected_parameters={"query": "python"},
            category="complex",
            difficulty="hard"
        ),
        TestCase(
            id="complex_002",
            query="check cluster health and tell me if any OSDs are down",
            expected_intent="cluster_health",
            category="complex",
            difficulty="hard",
            requires_ceph=True
        ),
        
        # Ambiguous queries
        TestCase(
            id="ambig_001",
            query="show me everything",
            expected_intent="list_objects",
            category="ambiguous",
            difficulty="hard"
        ),
        TestCase(
            id="ambig_002",
            query="help",
            expected_intent="help",
            category="ambiguous",
            difficulty="easy"
        ),
        TestCase(
            id="ambig_003",
            query="status",
            expected_intent="cluster_health",
            category="ambiguous",
            difficulty="medium",
            requires_ceph=True
        ),
    ]
    
    def __init__(
        self,
        agent=None,
        output_directory: str = "./evaluation_results",
        test_cases: Optional[List[TestCase]] = None
    ):
        """
        Initialize evaluation framework.
        
        Args:
            agent: LLM Agent instance to evaluate
            output_directory: Directory for saving reports
            test_cases: Custom test cases (uses defaults if None)
        """
        self.agent = agent
        self.output_directory = Path(output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)
        
        self.test_cases = test_cases or self.DEFAULT_TEST_CASES
        self.results: List[TestResult] = []
        
        logger.info(f"Initialized EvaluationFramework with {len(self.test_cases)} test cases")
    
    def run_evaluation(
        self,
        include_ceph_tests: bool = True,
        categories: Optional[List[str]] = None,
        save_report: bool = True,
        quick_mode: bool = False,
        progress_callback: Optional[callable] = None
    ) -> EvaluationReport:
        """
        Run complete evaluation suite.
        
        Args:
            include_ceph_tests: Whether to run tests requiring Ceph
            categories: Filter to specific categories
            save_report: Whether to save report to file
            quick_mode: Run a subset of tests for quick validation
            progress_callback: Callback function for progress updates (0.0 to 1.0)
            
        Returns:
            EvaluationReport with results
        """
        logger.info("Starting evaluation run")
        self.results = []
        
        # Filter test cases
        test_cases = self.test_cases
        if not include_ceph_tests:
            test_cases = [t for t in test_cases if not t.requires_ceph]
        if categories:
            test_cases = [t for t in test_cases if t.category in categories]
        if quick_mode:
            # In quick mode, take at most 2 tests per category
            seen_categories = {}
            quick_tests = []
            for t in test_cases:
                count = seen_categories.get(t.category, 0)
                if count < 2:
                    quick_tests.append(t)
                    seen_categories[t.category] = count + 1
            test_cases = quick_tests
        
        logger.info(f"Running {len(test_cases)} test cases")
        
        # Run tests
        for i, test_case in enumerate(test_cases):
            result = self._run_single_test(test_case)
            self.results.append(result)
            if progress_callback:
                progress_callback((i + 1) / len(test_cases))
        
        # Generate report
        report = self._generate_report()
        
        if save_report:
            self._save_report(report)
        
        return report
    
    def _run_single_test(self, test_case: TestCase) -> TestResult:
        """Run a single test case."""
        logger.debug(f"Running test: {test_case.id}")
        
        start_time = time.time()
        
        try:
            if self.agent is None:
                return TestResult(
                    test_id=test_case.id,
                    success=False,
                    predicted_intent="",
                    expected_intent=test_case.expected_intent,
                    intent_correct=False,
                    parameters_correct=False,
                    response_contains_expected=False,
                    latency_ms=0,
                    error="Agent not initialized"
                )
            
            # Execute query
            result = self.agent.process_query(test_case.query, auto_confirm=True)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Extract predicted intent
            predicted_intent = result.operation.value if hasattr(result.operation, 'value') else str(result.operation)
            
            # Check intent correctness
            intent_correct = self._intent_matches(predicted_intent, test_case.expected_intent)
            
            # Check parameters
            parameters_correct = self._parameters_match(
                result.metadata.get('intent', {}).get('parameters', {}),
                test_case.expected_parameters
            )
            
            # Check response content
            response_contains = self._response_contains_expected(
                result.message,
                test_case.expected_response_contains
            )
            
            success = intent_correct and (not test_case.expected_parameters or parameters_correct)
            
            return TestResult(
                test_id=test_case.id,
                success=success,
                predicted_intent=predicted_intent,
                expected_intent=test_case.expected_intent,
                intent_correct=intent_correct,
                parameters_correct=parameters_correct,
                response_contains_expected=response_contains,
                latency_ms=latency_ms,
                response=result.message,
                metadata={
                    "category": test_case.category,
                    "difficulty": test_case.difficulty
                }
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return TestResult(
                test_id=test_case.id,
                success=False,
                predicted_intent="error",
                expected_intent=test_case.expected_intent,
                intent_correct=False,
                parameters_correct=False,
                response_contains_expected=False,
                latency_ms=latency_ms,
                error=str(e),
                metadata={
                    "category": test_case.category,
                    "difficulty": test_case.difficulty
                }
            )
    
    def _intent_matches(self, predicted: str, expected: str) -> bool:
        """Check if predicted intent matches expected."""
        # Normalize intents for comparison
        predicted = predicted.lower().replace("_", "").replace("-", "")
        expected = expected.lower().replace("_", "").replace("-", "")
        
        # Direct match
        if predicted == expected:
            return True
        
        # Partial match (handle variations)
        intent_aliases = {
            "semanticsearch": ["search", "searchobjects", "findfiles"],
            "readobject": ["read", "showobject", "getobject"],
            "listobjects": ["list", "ls", "showobjects"],
            "createobject": ["create", "write", "makeobject"],
            "deleteobject": ["delete", "remove", "rm"],
            "clusterhealth": ["health", "clusterstatus", "status"],
            "searchdocs": ["documentation", "help", "explain"],
            "getstats": ["poolstats", "statistics", "stats"],
            "explainissue": ["explain", "troubleshoot"],
            "pgstatus": ["placementgroups", "pginfo"],
        }
        
        for canonical, aliases in intent_aliases.items():
            if expected == canonical or expected in aliases:
                if predicted == canonical or predicted in aliases:
                    return True
        
        return False
    
    def _parameters_match(self, predicted: Dict, expected: Dict) -> bool:
        """Check if predicted parameters match expected."""
        if not expected:
            return True
        
        for key, value in expected.items():
            if key not in predicted:
                return False
            
            # Flexible string matching
            if isinstance(value, str) and isinstance(predicted[key], str):
                if value.lower() not in predicted[key].lower():
                    # Check if query/object_name is reasonably close
                    if key in ['query', 'object_name']:
                        if value.lower() != predicted[key].lower():
                            return False
                    else:
                        return False
        
        return True
    
    def _response_contains_expected(self, response: str, expected: List[str]) -> bool:
        """Check if response contains expected strings."""
        if not expected:
            return True
        
        response_lower = response.lower()
        return all(term.lower() in response_lower for term in expected)
    
    def _generate_report(self) -> EvaluationReport:
        """Generate evaluation report from results."""
        if not self.results:
            return EvaluationReport(
                timestamp=datetime.now().isoformat(),
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                intent_accuracy=0.0,
                parameter_accuracy=0.0,
                response_quality=0.0,
                avg_latency_ms=0.0,
                p50_latency_ms=0.0,
                p95_latency_ms=0.0,
                p99_latency_ms=0.0
            )
        
        # Calculate metrics
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success)
        failed = total - passed
        
        intent_correct = sum(1 for r in self.results if r.intent_correct)
        params_correct = sum(1 for r in self.results if r.parameters_correct)
        response_quality = sum(1 for r in self.results if r.response_contains_expected)
        
        latencies = [r.latency_ms for r in self.results]
        latencies.sort()
        
        # Category breakdown
        category_results = {}
        for result in self.results:
            cat = result.metadata.get('category', 'unknown')
            if cat not in category_results:
                category_results[cat] = {
                    'total': 0,
                    'passed': 0,
                    'intent_correct': 0,
                    'avg_latency_ms': 0.0,
                    'latencies': []
                }
            category_results[cat]['total'] += 1
            if result.success:
                category_results[cat]['passed'] += 1
            if result.intent_correct:
                category_results[cat]['intent_correct'] += 1
            category_results[cat]['latencies'].append(result.latency_ms)
        
        # Calculate category averages
        for cat, data in category_results.items():
            if data['latencies']:
                data['avg_latency_ms'] = statistics.mean(data['latencies'])
                data['accuracy'] = data['passed'] / data['total'] * 100 if data['total'] > 0 else 0
            del data['latencies']
        
        return EvaluationReport(
            timestamp=datetime.now().isoformat(),
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            intent_accuracy=intent_correct / total * 100 if total > 0 else 0,
            parameter_accuracy=params_correct / total * 100 if total > 0 else 0,
            response_quality=response_quality / total * 100 if total > 0 else 0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0,
            p50_latency_ms=self._percentile(latencies, 50),
            p95_latency_ms=self._percentile(latencies, 95),
            p99_latency_ms=self._percentile(latencies, 99),
            category_results=category_results,
            results=self.results
        )
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0.0
        k = (len(data) - 1) * percentile / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        return data[f] + (k - f) * (data[c] - data[f])
    
    def _save_report(self, report: EvaluationReport):
        """Save report to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save JSON report
        json_path = self.output_directory / f"evaluation_{timestamp}.json"
        report_dict = asdict(report)
        # Convert TestResult objects to dicts
        report_dict['results'] = [asdict(r) for r in report.results]
        
        with open(json_path, 'w') as f:
            json.dump(report_dict, f, indent=2)
        
        # Save summary text report
        txt_path = self.output_directory / f"evaluation_{timestamp}.txt"
        with open(txt_path, 'w') as f:
            f.write(self._format_text_report(report))
        
        logger.info(f"Saved reports to {json_path} and {txt_path}")
    
    def _format_text_report(self, report: EvaluationReport) -> str:
        """Format report as readable text."""
        lines = [
            "=" * 60,
            "CEPH LLM AGENT EVALUATION REPORT",
            "=" * 60,
            f"Timestamp: {report.timestamp}",
            "",
            "SUMMARY",
            "-" * 40,
            f"Total Tests:    {report.total_tests}",
            f"Passed:         {report.passed_tests}",
            f"Failed:         {report.failed_tests}",
            f"Pass Rate:      {report.passed_tests / report.total_tests * 100:.1f}%" if report.total_tests > 0 else "N/A",
            "",
            "ACCURACY METRICS",
            "-" * 40,
            f"Intent Accuracy:     {report.intent_accuracy:.1f}%",
            f"Parameter Accuracy:  {report.parameter_accuracy:.1f}%",
            f"Response Quality:    {report.response_quality:.1f}%",
            "",
            "LATENCY METRICS",
            "-" * 40,
            f"Average:  {report.avg_latency_ms:.2f} ms",
            f"P50:      {report.p50_latency_ms:.2f} ms",
            f"P95:      {report.p95_latency_ms:.2f} ms",
            f"P99:      {report.p99_latency_ms:.2f} ms",
            "",
            "CATEGORY BREAKDOWN",
            "-" * 40,
        ]
        
        for category, data in report.category_results.items():
            lines.append(f"{category}:")
            lines.append(f"  Tests: {data['total']}, Passed: {data['passed']}, Accuracy: {data.get('accuracy', 0):.1f}%")
            lines.append(f"  Avg Latency: {data['avg_latency_ms']:.2f} ms")
        
        lines.extend([
            "",
            "FAILED TESTS",
            "-" * 40,
        ])
        
        failed = [r for r in report.results if not r.success]
        if failed:
            for r in failed:
                lines.append(f"  {r.test_id}: expected '{r.expected_intent}', got '{r.predicted_intent}'")
                if r.error:
                    lines.append(f"    Error: {r.error}")
        else:
            lines.append("  None")
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def add_test_case(self, test_case: TestCase):
        """Add a custom test case."""
        self.test_cases.append(test_case)
        logger.info(f"Added test case: {test_case.id}")
    
    def benchmark_latency(self, query: str, iterations: int = 10) -> Dict[str, float]:
        """
        Benchmark latency for a specific query.
        
        Args:
            query: Query to benchmark
            iterations: Number of iterations
            
        Returns:
            Dictionary with latency statistics
        """
        if self.agent is None:
            return {"error": "Agent not initialized"}
        
        latencies = []
        
        for _ in range(iterations):
            start = time.time()
            self.agent.process_query(query, auto_confirm=True)
            latencies.append((time.time() - start) * 1000)
        
        latencies.sort()
        
        return {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            "p95": self._percentile(latencies, 95),
            "p99": self._percentile(latencies, 99),
            "iterations": iterations
        }
    
    def compare_with_cli(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare agent performance with direct CLI operations.
        
        Args:
            operations: List of operations to compare
                Each dict should have 'query' (natural language) and 'cli_command'
                
        Returns:
            Comparison results
        """
        import subprocess
        
        results = {
            "operations": [],
            "summary": {
                "agent_avg_ms": 0,
                "cli_avg_ms": 0,
                "overhead_ms": 0,
                "overhead_percent": 0
            }
        }
        
        agent_times = []
        cli_times = []
        
        for op in operations:
            query = op.get('query', '')
            cli_cmd = op.get('cli_command', '')
            
            # Time agent
            if self.agent:
                start = time.time()
                self.agent.process_query(query, auto_confirm=True)
                agent_time = (time.time() - start) * 1000
            else:
                agent_time = 0
            
            # Time CLI
            if cli_cmd:
                start = time.time()
                try:
                    subprocess.run(cli_cmd, shell=True, capture_output=True, timeout=30)
                    cli_time = (time.time() - start) * 1000
                except:
                    cli_time = 0
            else:
                cli_time = 0
            
            results['operations'].append({
                'query': query,
                'cli_command': cli_cmd,
                'agent_ms': agent_time,
                'cli_ms': cli_time,
                'overhead_ms': agent_time - cli_time if cli_time > 0 else agent_time
            })
            
            agent_times.append(agent_time)
            if cli_time > 0:
                cli_times.append(cli_time)
        
        if agent_times:
            results['summary']['agent_avg_ms'] = statistics.mean(agent_times)
        if cli_times:
            results['summary']['cli_avg_ms'] = statistics.mean(cli_times)
            results['summary']['overhead_ms'] = results['summary']['agent_avg_ms'] - results['summary']['cli_avg_ms']
            results['summary']['overhead_percent'] = (
                results['summary']['overhead_ms'] / results['summary']['cli_avg_ms'] * 100
                if results['summary']['cli_avg_ms'] > 0 else 0
            )
        
        return results
    
    def get_summary(self) -> str:
        """Get a brief summary of the last evaluation."""
        if not self.results:
            return "No evaluation results available. Run run_evaluation() first."
        
        report = self._generate_report()
        
        return (
            f"Evaluation Summary:\n"
            f"  Tests: {report.total_tests} ({report.passed_tests} passed, {report.failed_tests} failed)\n"
            f"  Intent Accuracy: {report.intent_accuracy:.1f}%\n"
            f"  Avg Latency: {report.avg_latency_ms:.2f} ms\n"
        )


def create_test_case(
    id: str,
    query: str,
    expected_intent: str,
    **kwargs
) -> TestCase:
    """Helper function to create test cases."""
    return TestCase(
        id=id,
        query=query,
        expected_intent=expected_intent,
        **kwargs
    )
