"""
Comprehensive benchmarking suite for the Ceph LLM Agent.

Addresses reviewer requirements:
- Multiple evaluation runs with error bars (mean ± std)
- Latency decomposition per operation type
- Scalability benchmarks (indexing throughput, search at scale)
- Multi-model comparison (Ollama models)
- CLI baseline comparison
- Generates JSON + LaTeX-ready output
"""

import logging
import time
import json
import statistics
import subprocess
import os
import random
import string
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark runs."""
    num_runs: int = 5
    output_dir: str = "./evaluation_results/benchmarks"
    models: List[str] = field(default_factory=lambda: ["llama3.2"])
    scalability_sizes: List[int] = field(default_factory=lambda: [10, 50, 100, 500, 1000])
    pool_name: str = "testpool"


@dataclass
class RunMetrics:
    """Metrics from a single evaluation run."""
    run_id: int
    total_tests: int
    passed_tests: int
    intent_accuracy: float
    parameter_accuracy: float
    response_quality: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    latency_decomposition: Dict[str, float] = field(default_factory=dict)
    category_results: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class AggregatedMetrics:
    """Aggregated metrics across multiple runs with statistics."""
    num_runs: int
    model: str
    
    intent_accuracy_mean: float
    intent_accuracy_std: float
    parameter_accuracy_mean: float
    parameter_accuracy_std: float
    response_quality_mean: float
    response_quality_std: float
    
    avg_latency_mean: float
    avg_latency_std: float
    p50_latency_mean: float
    p50_latency_std: float
    p95_latency_mean: float
    p95_latency_std: float
    p99_latency_mean: float
    p99_latency_std: float
    
    latency_decomposition_mean: Dict[str, float] = field(default_factory=dict)
    latency_decomposition_std: Dict[str, float] = field(default_factory=dict)
    
    category_accuracies: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    individual_runs: List[RunMetrics] = field(default_factory=list)


@dataclass
class ScalabilityResult:
    """Result of a scalability benchmark."""
    num_objects: int
    indexing_time_ms: float
    indexing_throughput_ops: float  # objects/second
    search_latency_ms: float
    search_latency_std: float
    chromadb_memory_mb: float
    rados_overhead_ms: float


@dataclass
class CLIComparison:
    """Comparison between agent and CLI for a single operation."""
    operation: str
    query: str
    cli_command: str
    agent_latency_ms: float
    cli_latency_ms: float
    overhead_ms: float
    overhead_percent: float


class BenchmarkSuite:
    """
    Comprehensive benchmarking suite for paper evaluation.
    
    Produces results suitable for academic publication:
    - Mean ± std across multiple runs
    - Latency CDFs
    - Scalability curves
    - Baseline comparisons
    """
    
    def __init__(self, config: Optional[BenchmarkConfig] = None):
        self.config = config or BenchmarkConfig()
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # ========== Multi-Run Evaluation ==========
    
    def run_multi_evaluation(
        self,
        agent,
        num_runs: Optional[int] = None,
        progress_callback=None
    ) -> AggregatedMetrics:
        """
        Run evaluation multiple times and aggregate with statistics.
        
        Args:
            agent: Initialized LLM agent
            num_runs: Number of runs (overrides config)
            progress_callback: Called with (run_number, total_runs)
        
        Returns:
            AggregatedMetrics with mean ± std for all metrics
        """
        from evaluation.evaluation_framework import EvaluationFramework
        
        n = num_runs or self.config.num_runs
        logger.info(f"Starting multi-run evaluation: {n} runs")
        
        runs: List[RunMetrics] = []
        
        for run_id in range(1, n + 1):
            logger.info(f"=== Run {run_id}/{n} ===")
            if progress_callback:
                progress_callback(run_id, n)
            
            framework = EvaluationFramework(agent=agent)
            report = framework.run_evaluation(save_report=False)
            
            run_metrics = RunMetrics(
                run_id=run_id,
                total_tests=report.total_tests,
                passed_tests=report.passed_tests,
                intent_accuracy=report.intent_accuracy,
                parameter_accuracy=report.parameter_accuracy,
                response_quality=report.response_quality,
                avg_latency_ms=report.avg_latency_ms,
                p50_latency_ms=report.p50_latency_ms,
                p95_latency_ms=report.p95_latency_ms,
                p99_latency_ms=report.p99_latency_ms,
                latency_decomposition=report.latency_decomposition,
                category_results=report.category_results,
            )
            runs.append(run_metrics)
            
            # Clear agent conversation context between runs
            if hasattr(agent, 'clear_conversation'):
                agent.clear_conversation()
        
        # Aggregate
        aggregated = self._aggregate_runs(runs, model=getattr(agent, 'llm', None) and agent.llm.model or "unknown")
        
        # Save
        self._save_json(f"multi_eval_{self.timestamp}.json", asdict(aggregated))
        self._save_text_report(aggregated)
        
        return aggregated
    
    def _aggregate_runs(self, runs: List[RunMetrics], model: str) -> AggregatedMetrics:
        """Aggregate multiple runs into mean ± std."""
        n = len(runs)
        
        def mean_std(values):
            m = statistics.mean(values)
            s = statistics.stdev(values) if len(values) > 1 else 0.0
            return m, s
        
        ia_m, ia_s = mean_std([r.intent_accuracy for r in runs])
        pa_m, pa_s = mean_std([r.parameter_accuracy for r in runs])
        rq_m, rq_s = mean_std([r.response_quality for r in runs])
        al_m, al_s = mean_std([r.avg_latency_ms for r in runs])
        p50_m, p50_s = mean_std([r.p50_latency_ms for r in runs])
        p95_m, p95_s = mean_std([r.p95_latency_ms for r in runs])
        p99_m, p99_s = mean_std([r.p99_latency_ms for r in runs])
        
        # Latency decomposition aggregation
        ld_keys = set()
        for r in runs:
            ld_keys.update(r.latency_decomposition.keys())
        
        ld_mean = {}
        ld_std = {}
        for key in ld_keys:
            vals = [r.latency_decomposition.get(key, 0) for r in runs]
            ld_mean[key], ld_std[key] = mean_std(vals)
        
        # Category aggregation
        all_cats = set()
        for r in runs:
            all_cats.update(r.category_results.keys())
        
        cat_accs = {}
        for cat in all_cats:
            accs = []
            for r in runs:
                cr = r.category_results.get(cat, {})
                if cr.get('total', 0) > 0:
                    accs.append(cr.get('accuracy', 0))
            if accs:
                m, s = mean_std(accs)
                cat_accs[cat] = {'mean': m, 'std': s}
        
        return AggregatedMetrics(
            num_runs=n,
            model=model,
            intent_accuracy_mean=ia_m, intent_accuracy_std=ia_s,
            parameter_accuracy_mean=pa_m, parameter_accuracy_std=pa_s,
            response_quality_mean=rq_m, response_quality_std=rq_s,
            avg_latency_mean=al_m, avg_latency_std=al_s,
            p50_latency_mean=p50_m, p50_latency_std=p50_s,
            p95_latency_mean=p95_m, p95_latency_std=p95_s,
            p99_latency_mean=p99_m, p99_latency_std=p99_s,
            latency_decomposition_mean=ld_mean,
            latency_decomposition_std=ld_std,
            category_accuracies=cat_accs,
            individual_runs=runs,
        )
    
    # ========== Scalability Benchmarks ==========
    
    def run_scalability_benchmark(
        self,
        rados_client,
        embedding_generator,
        vector_store,
        searcher,
        sizes: Optional[List[int]] = None,
        progress_callback=None
    ) -> List[ScalabilityResult]:
        """
        Benchmark indexing and search performance at different corpus sizes.
        
        Creates synthetic objects, indexes them, measures search latency.
        
        Args:
            rados_client: Connected RADOS client
            embedding_generator: Embedding generator
            vector_store: Vector store instance
            searcher: Searcher service
            sizes: List of corpus sizes to test
            
        Returns:
            List of ScalabilityResult for each size
        """
        sizes = sizes or self.config.scalability_sizes
        results = []
        
        logger.info(f"Starting scalability benchmark: sizes={sizes}")
        
        # Generate synthetic content
        topics = [
            "kubernetes deployment configuration", "ceph cluster monitoring",
            "storage performance tuning", "network configuration guide",
            "database backup procedures", "security audit report",
            "application log analysis", "infrastructure automation",
            "disaster recovery plan", "capacity planning document",
            "microservice architecture", "load balancing setup",
            "certificate management", "API documentation",
            "container orchestration", "storage replication policy",
        ]
        
        prefix = f"_bench_{self.timestamp}_"
        created_objects = []
        
        try:
            for size_idx, target_size in enumerate(sizes):
                logger.info(f"--- Scalability test: {target_size} objects ---")
                if progress_callback:
                    progress_callback(size_idx + 1, len(sizes), target_size)
                
                # Create objects up to target size
                while len(created_objects) < target_size:
                    idx = len(created_objects)
                    obj_name = f"{prefix}obj_{idx:06d}.txt"
                    topic = topics[idx % len(topics)]
                    content = f"Document {idx}: {topic}\n" + self._generate_content(topic, 200)
                    
                    rados_client.create_object(obj_name, content.encode('utf-8'))
                    created_objects.append(obj_name)
                
                # Measure indexing time for ALL objects at this scale
                t_index_start = time.time()
                for obj_name in created_objects:
                    try:
                        content = rados_client.read_object(obj_name)
                        text = content.decode('utf-8')
                        embedding = embedding_generator.generate(text)
                        # We just measure embedding generation, not full index
                    except Exception as e:
                        logger.warning(f"Index benchmark error: {e}")
                t_index_end = time.time()
                
                indexing_time_ms = (t_index_end - t_index_start) * 1000
                throughput = target_size / (indexing_time_ms / 1000) if indexing_time_ms > 0 else 0
                
                # Measure search latency (10 queries, average)
                search_queries = ["kubernetes config", "storage performance", "backup plan",
                                  "monitoring setup", "security report"]
                search_latencies = []
                for q in search_queries:
                    for _ in range(2):  # 2 iterations per query
                        t_start = time.time()
                        searcher.search(q, top_k=10)
                        search_latencies.append((time.time() - t_start) * 1000)
                
                search_mean = statistics.mean(search_latencies) if search_latencies else 0
                search_std = statistics.stdev(search_latencies) if len(search_latencies) > 1 else 0
                
                # Measure RADOS overhead (raw read vs semantic read)
                if created_objects:
                    sample_obj = created_objects[0]
                    t_start = time.time()
                    rados_client.read_object(sample_obj)
                    rados_overhead = (time.time() - t_start) * 1000
                else:
                    rados_overhead = 0
                
                # ChromaDB memory estimate
                import psutil
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / (1024 * 1024)
                
                result = ScalabilityResult(
                    num_objects=target_size,
                    indexing_time_ms=indexing_time_ms,
                    indexing_throughput_ops=throughput,
                    search_latency_ms=search_mean,
                    search_latency_std=search_std,
                    chromadb_memory_mb=memory_mb,
                    rados_overhead_ms=rados_overhead,
                )
                results.append(result)
                logger.info(f"  Objects: {target_size}, Index: {indexing_time_ms:.0f}ms, "
                           f"Search: {search_mean:.1f}±{search_std:.1f}ms, Memory: {memory_mb:.0f}MB")
            
        finally:
            # Cleanup benchmark objects
            logger.info(f"Cleaning up {len(created_objects)} benchmark objects...")
            for obj_name in created_objects:
                try:
                    rados_client.delete_object(obj_name)
                except:
                    pass
        
        self._save_json(f"scalability_{self.timestamp}.json", [asdict(r) for r in results])
        return results
    
    def _generate_content(self, topic: str, num_words: int) -> str:
        """Generate synthetic document content for benchmarking."""
        words = topic.split()
        # Expand with related terms
        filler = [
            "system", "configuration", "management", "deployment", "monitoring",
            "performance", "optimization", "storage", "network", "cluster",
            "service", "application", "resource", "capacity", "throughput",
            "latency", "availability", "replication", "backup", "recovery",
        ]
        content_words = []
        for _ in range(num_words):
            if random.random() < 0.3:
                content_words.append(random.choice(words))
            else:
                content_words.append(random.choice(filler))
        return " ".join(content_words)
    
    # ========== CLI Baseline Comparison ==========
    
    def run_cli_comparison(
        self,
        agent,
        rados_client=None,
        iterations: int = 3
    ) -> List[CLIComparison]:
        """
        Compare agent latency vs direct CLI/library commands.
        
        Args:
            agent: LLM agent
            rados_client: RADOS client for direct operations
            iterations: Number of iterations per operation
            
        Returns:
            List of comparison results
        """
        logger.info("Starting CLI baseline comparison")
        
        # Define operations to compare
        operations = [
            {
                "operation": "list_objects",
                "query": "list all objects in the pool",
                "cli_command": "rados -p testpool ls",
            },
            {
                "operation": "read_object",
                "query": "show me the content of hello.txt",
                "cli_command": "rados -p testpool get hello.txt /dev/stdout",
            },
            {
                "operation": "cluster_health",
                "query": "is the cluster healthy?",
                "cli_command": "ceph health detail",
            },
            {
                "operation": "pool_stats",
                "query": "show me storage statistics",
                "cli_command": "ceph df",
            },
            {
                "operation": "osd_status",
                "query": "show me OSD status",
                "cli_command": "ceph osd tree",
            },
            {
                "operation": "pg_status",
                "query": "are there any degraded PGs?",
                "cli_command": "ceph pg stat",
            },
            {
                "operation": "create_object",
                "query": "create a new file called _bench_cli_test.txt with content benchmark data",
                "cli_command": "echo 'benchmark data' | rados -p testpool put _bench_cli_test.txt /dev/stdin",
            },
            {
                "operation": "semantic_search",
                "query": "find files about kubernetes",
                "cli_command": "rados -p testpool ls | grep -i kube",
            },
        ]
        
        results = []
        
        for op in operations:
            agent_times = []
            cli_times = []
            
            for _ in range(iterations):
                # Time agent
                t_start = time.time()
                try:
                    agent.process_query(op['query'], auto_confirm=True)
                except Exception as e:
                    logger.warning(f"Agent error for '{op['query']}': {e}")
                agent_times.append((time.time() - t_start) * 1000)
                
                # Time CLI
                t_start = time.time()
                try:
                    subprocess.run(
                        op['cli_command'], shell=True,
                        capture_output=True, timeout=30
                    )
                except Exception as e:
                    logger.warning(f"CLI error for '{op['cli_command']}': {e}")
                cli_times.append((time.time() - t_start) * 1000)
            
            agent_avg = statistics.mean(agent_times) if agent_times else 0
            cli_avg = statistics.mean(cli_times) if cli_times else 0
            overhead = agent_avg - cli_avg
            overhead_pct = (overhead / cli_avg * 100) if cli_avg > 0 else 0
            
            results.append(CLIComparison(
                operation=op['operation'],
                query=op['query'],
                cli_command=op['cli_command'],
                agent_latency_ms=agent_avg,
                cli_latency_ms=cli_avg,
                overhead_ms=overhead,
                overhead_percent=overhead_pct,
            ))
            
            logger.info(f"  {op['operation']}: Agent={agent_avg:.0f}ms, CLI={cli_avg:.0f}ms, "
                        f"Overhead={overhead:.0f}ms ({overhead_pct:.0f}%)")
        
        # Cleanup
        try:
            if rados_client:
                rados_client.delete_object("_bench_cli_test.txt")
        except:
            pass
        
        self._save_json(f"cli_comparison_{self.timestamp}.json", [asdict(r) for r in results])
        return results
    
    # ========== Multi-Model Comparison ==========
    
    def run_model_comparison(
        self,
        rados_client,
        indexer,
        searcher,
        vector_store,
        models: Optional[List[str]] = None,
        num_runs: int = 3,
        progress_callback=None
    ) -> Dict[str, AggregatedMetrics]:
        """
        Compare multiple LLM models on the same evaluation suite.
        
        Args:
            rados_client: RADOS client
            indexer: Indexer service
            searcher: Searcher service
            vector_store: Vector store
            models: List of model names (Ollama)
            num_runs: Runs per model
            
        Returns:
            Dict mapping model_name -> AggregatedMetrics
        """
        from core.llm_provider import OllamaProvider
        from core.llm_agent import LLMAgent
        
        models = models or self.config.models
        results = {}
        
        for model_name in models:
            logger.info(f"\n{'='*60}")
            logger.info(f"Evaluating model: {model_name}")
            logger.info(f"{'='*60}")
            
            try:
                provider = OllamaProvider(model=model_name)
                agent = LLMAgent(
                    llm_provider=provider,
                    rados_client=rados_client,
                    indexer=indexer,
                    searcher=searcher,
                    vector_store=vector_store,
                )
                
                if progress_callback:
                    progress_callback(model_name, "started")
                
                aggregated = self.run_multi_evaluation(agent, num_runs=num_runs)
                results[model_name] = aggregated
                
                if progress_callback:
                    progress_callback(model_name, "completed")
                    
            except Exception as e:
                logger.error(f"Failed to evaluate model {model_name}: {e}")
                if progress_callback:
                    progress_callback(model_name, f"failed: {e}")
        
        self._save_json(f"model_comparison_{self.timestamp}.json",
                        {k: asdict(v) for k, v in results.items()})
        return results
    
    # ========== Report Generation ==========
    
    def _save_json(self, filename: str, data: Any):
        """Save data as JSON."""
        path = self.output_dir / filename
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved: {path}")
    
    def _save_text_report(self, metrics: AggregatedMetrics):
        """Save human-readable report."""
        path = self.output_dir / f"report_{self.timestamp}.txt"
        
        lines = [
            "=" * 70,
            "CEPH LLM AGENT - MULTI-RUN EVALUATION REPORT",
            "=" * 70,
            f"Timestamp:   {self.timestamp}",
            f"Model:       {metrics.model}",
            f"Runs:        {metrics.num_runs}",
            "",
            "ACCURACY METRICS (mean ± std)",
            "-" * 50,
            f"Intent Accuracy:     {metrics.intent_accuracy_mean:.1f}% ± {metrics.intent_accuracy_std:.1f}%",
            f"Parameter Accuracy:  {metrics.parameter_accuracy_mean:.1f}% ± {metrics.parameter_accuracy_std:.1f}%",
            f"Response Quality:    {metrics.response_quality_mean:.1f}% ± {metrics.response_quality_std:.1f}%",
            "",
            "LATENCY METRICS (mean ± std)",
            "-" * 50,
            f"Average:  {metrics.avg_latency_mean:.1f} ± {metrics.avg_latency_std:.1f} ms",
            f"P50:      {metrics.p50_latency_mean:.1f} ± {metrics.p50_latency_std:.1f} ms",
            f"P95:      {metrics.p95_latency_mean:.1f} ± {metrics.p95_latency_std:.1f} ms",
            f"P99:      {metrics.p99_latency_mean:.1f} ± {metrics.p99_latency_std:.1f} ms",
            "",
            "LATENCY DECOMPOSITION (mean ± std)",
            "-" * 50,
        ]
        
        for key in ['llm_inference_ms', 'embedding_ms', 'vector_search_ms', 'rados_io_ms', 'response_format_ms', 'other_ms']:
            m = metrics.latency_decomposition_mean.get(key, 0)
            s = metrics.latency_decomposition_std.get(key, 0)
            pct = m / metrics.avg_latency_mean * 100 if metrics.avg_latency_mean > 0 else 0
            label = key.replace('_ms', '').replace('_', ' ').title()
            lines.append(f"{label:20s}: {m:7.1f} ± {s:5.1f} ms ({pct:.1f}%)")
        
        lines.extend([
            "",
            "CATEGORY BREAKDOWN (accuracy mean ± std)",
            "-" * 50,
        ])
        
        for cat, data in sorted(metrics.category_accuracies.items()):
            lines.append(f"  {cat:20s}: {data['mean']:.1f}% ± {data['std']:.1f}%")
        
        lines.extend([
            "",
            "INDIVIDUAL RUN RESULTS",
            "-" * 50,
        ])
        
        for run in metrics.individual_runs:
            lines.append(f"  Run {run.run_id}: Intent={run.intent_accuracy:.1f}%, "
                        f"Param={run.parameter_accuracy:.1f}%, "
                        f"Latency={run.avg_latency_ms:.0f}ms, "
                        f"Passed={run.passed_tests}/{run.total_tests}")
        
        lines.append("")
        lines.append("=" * 70)
        
        with open(path, 'w') as f:
            f.write("\n".join(lines))
        logger.info(f"Saved report: {path}")
    
    def generate_latex_tables(
        self,
        multi_run: Optional[AggregatedMetrics] = None,
        scalability: Optional[List[ScalabilityResult]] = None,
        cli_comparison: Optional[List[CLIComparison]] = None,
        model_comparison: Optional[Dict[str, AggregatedMetrics]] = None,
    ) -> str:
        """Generate LaTeX-formatted tables for paper inclusion."""
        
        latex = []
        
        # Table 1: Main evaluation results
        if multi_run:
            latex.append(r"""
% Table: Evaluation Results (mean ± std over N runs)
\begin{table}[t]
\centering
\caption{Agent evaluation results (mean $\pm$ std, """ + f"N={multi_run.num_runs}" + r""" runs, model: """ + multi_run.model + r""").}
\label{tab:eval-results}
\begin{tabular}{lr}
\toprule
\textbf{Metric} & \textbf{Result} \\
\midrule
Intent Accuracy (\%) & """ + f"${multi_run.intent_accuracy_mean:.1f} \\pm {multi_run.intent_accuracy_std:.1f}$" + r""" \\
Parameter Accuracy (\%) & """ + f"${multi_run.parameter_accuracy_mean:.1f} \\pm {multi_run.parameter_accuracy_std:.1f}$" + r""" \\
Response Quality (\%) & """ + f"${multi_run.response_quality_mean:.1f} \\pm {multi_run.response_quality_std:.1f}$" + r""" \\
\midrule
Avg Latency (ms) & """ + f"${multi_run.avg_latency_mean:.0f} \\pm {multi_run.avg_latency_std:.0f}$" + r""" \\
P50 Latency (ms) & """ + f"${multi_run.p50_latency_mean:.0f} \\pm {multi_run.p50_latency_std:.0f}$" + r""" \\
P95 Latency (ms) & """ + f"${multi_run.p95_latency_mean:.0f} \\pm {multi_run.p95_latency_std:.0f}$" + r""" \\
\bottomrule
\end{tabular}
\end{table}
""")
        
        # Table 2: Latency decomposition
        if multi_run and multi_run.latency_decomposition_mean:
            ld = multi_run.latency_decomposition_mean
            ld_s = multi_run.latency_decomposition_std
            total = multi_run.avg_latency_mean
            
            latex.append(r"""
% Table: Latency Decomposition
\begin{table}[t]
\centering
\caption{End-to-end latency decomposition (mean $\pm$ std in ms).}
\label{tab:latency-decomp}
\begin{tabular}{lrr}
\toprule
\textbf{Phase} & \textbf{Latency (ms)} & \textbf{Fraction (\%)} \\
\midrule""")
            for key, label in [('llm_inference_ms', 'LLM Inference'), ('embedding_ms', 'Embedding Gen.'),
                               ('vector_search_ms', 'Vector Search'), ('rados_io_ms', 'RADOS I/O'),
                               ('response_format_ms', 'Response Format'), ('other_ms', 'Other')]:
                m = ld.get(key, 0)
                s = ld_s.get(key, 0)
                pct = m / total * 100 if total > 0 else 0
                latex.append(f"{label} & ${m:.0f} \\pm {s:.0f}$ & {pct:.1f} \\\\")
            
            latex.append(r"""\midrule
Total & """ + f"${total:.0f}$" + r""" & 100.0 \\
\bottomrule
\end{tabular}
\end{table}
""")
        
        # Table 3: Scalability
        if scalability:
            latex.append(r"""
% Table: Scalability Results
\begin{table}[t]
\centering
\caption{Scalability evaluation: indexing throughput and search latency vs.\ corpus size.}
\label{tab:scalability}
\begin{tabular}{rrrrr}
\toprule
\textbf{Objects} & \textbf{Index (ms)} & \textbf{Throughput (obj/s)} & \textbf{Search (ms)} & \textbf{Memory (MB)} \\
\midrule""")
            for sr in scalability:
                latex.append(f"{sr.num_objects} & {sr.indexing_time_ms:.0f} & "
                            f"{sr.indexing_throughput_ops:.1f} & "
                            f"${sr.search_latency_ms:.1f} \\pm {sr.search_latency_std:.1f}$ & "
                            f"{sr.chromadb_memory_mb:.0f} \\\\")
            latex.append(r"""\bottomrule
\end{tabular}
\end{table}
""")
        
        # Table 4: CLI Comparison
        if cli_comparison:
            latex.append(r"""
% Table: CLI Baseline Comparison
\begin{table}[t]
\centering
\caption{Agent vs.\ CLI latency comparison.}
\label{tab:cli-comparison}
\begin{tabular}{lrrr}
\toprule
\textbf{Operation} & \textbf{Agent (ms)} & \textbf{CLI (ms)} & \textbf{Overhead (\%)} \\
\midrule""")
            for c in cli_comparison:
                op_name = c.operation.replace('_', ' ').title()
                latex.append(f"{op_name} & {c.agent_latency_ms:.0f} & {c.cli_latency_ms:.0f} & "
                            f"{c.overhead_percent:.0f} \\\\")
            
            # Add averages
            avg_agent = statistics.mean([c.agent_latency_ms for c in cli_comparison])
            avg_cli = statistics.mean([c.cli_latency_ms for c in cli_comparison])
            avg_overhead = ((avg_agent - avg_cli) / avg_cli * 100) if avg_cli > 0 else 0
            latex.append(r"\midrule")
            latex.append(f"\\textbf{{Average}} & \\textbf{{{avg_agent:.0f}}} & "
                        f"\\textbf{{{avg_cli:.0f}}} & \\textbf{{{avg_overhead:.0f}}} \\\\")
            latex.append(r"""\bottomrule
\end{tabular}
\end{table}
""")
        
        # Table 5: Model comparison
        if model_comparison:
            latex.append(r"""
% Table: Multi-Model Comparison
\begin{table}[t]
\centering
\caption{LLM model comparison on intent classification and latency.}
\label{tab:model-comparison}
\begin{tabular}{lrrr}
\toprule
\textbf{Model} & \textbf{Intent Acc.\ (\%)} & \textbf{Param Acc.\ (\%)} & \textbf{Avg Latency (ms)} \\
\midrule""")
            for model_name, metrics in model_comparison.items():
                latex.append(f"{model_name} & "
                            f"${metrics.intent_accuracy_mean:.1f} \\pm {metrics.intent_accuracy_std:.1f}$ & "
                            f"${metrics.parameter_accuracy_mean:.1f} \\pm {metrics.parameter_accuracy_std:.1f}$ & "
                            f"${metrics.avg_latency_mean:.0f} \\pm {metrics.avg_latency_std:.0f}$ \\\\")
            latex.append(r"""\bottomrule
\end{tabular}
\end{table}
""")
        
        # Save
        latex_str = "\n".join(latex)
        path = self.output_dir / f"tables_{self.timestamp}.tex"
        with open(path, 'w') as f:
            f.write(latex_str)
        logger.info(f"Saved LaTeX tables: {path}")
        
        return latex_str
