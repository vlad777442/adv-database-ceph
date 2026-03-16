"""
End-to-end latency profiler (Eval §5).

Runs a representative query mix and collects fine-grained timings:
  • LLM inference (Ollama round-trip)
  • Embedding generation
  • Vector-store lookup (ChromaDB)
  • RADOS I/O
  • Response formatting / serialisation
  • Total wall-clock

Also runs an Agent-vs-CLI baseline (ceph CLI commands).
"""

from __future__ import annotations

import logging
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── representative query workload ────────────────────────────────────────

WORKLOAD: List[Dict[str, str]] = [
    {"label": "cluster_health",
     "query": "is the cluster healthy?",
     "cli": "ceph health detail"},
    {"label": "osd_status",
     "query": "show me OSD status",
     "cli": "ceph osd tree"},
    {"label": "pg_status",
     "query": "are there any degraded PGs?",
     "cli": "ceph pg stat"},
    {"label": "pool_stats",
     "query": "what pools do I have?",
     "cli": "ceph df"},
    {"label": "diagnose_cluster",
     "query": "diagnose any problems with the cluster",
     "cli": "ceph health detail"},
    {"label": "capacity_prediction",
     "query": "when will the storage be full?",
     "cli": "ceph df"},
    {"label": "performance_stats",
     "query": "what's the current throughput?",
     "cli": "ceph osd perf"},
]


# ── result dataclasses ───────────────────────────────────────────────────

@dataclass
class LatencySample:
    label: str
    iteration: int
    total_ms: float
    llm_inference_ms: float = 0.0
    embedding_ms: float = 0.0
    vector_search_ms: float = 0.0
    rados_io_ms: float = 0.0
    response_format_ms: float = 0.0
    other_ms: float = 0.0


@dataclass
class CLISample:
    label: str
    iteration: int
    agent_ms: float
    cli_ms: float
    overhead_ms: float
    overhead_pct: float


@dataclass
class LatencyProfile:
    """Per-operation-type statistical summary."""
    label: str
    n: int
    total_mean: float
    total_std: float
    total_p50: float
    total_p95: float
    llm_mean: float
    llm_std: float
    embedding_mean: float
    rados_mean: float
    vector_mean: float
    other_mean: float


@dataclass
class CLIProfile:
    label: str
    agent_mean: float
    agent_std: float
    cli_mean: float
    cli_std: float
    overhead_mean: float
    overhead_pct: float


@dataclass
class LatencyReport:
    num_operations: int
    iterations: int
    total_samples: int
    # overall
    overall_mean_ms: float
    overall_p50_ms: float
    overall_p95_ms: float
    overall_p99_ms: float
    # per-operation
    profiles: List[LatencyProfile] = field(default_factory=list)
    # CLI comparison
    cli_profiles: List[CLIProfile] = field(default_factory=list)
    # raw
    samples: List[LatencySample] = field(default_factory=list)
    cli_samples: List[CLISample] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────

def _percentile(data: List[float], pct: int) -> float:
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(data) - 1)
    return data[f] + (k - f) * (data[c] - data[f])


def _extract_breakdown(res) -> Dict[str, float]:
    """Extract LatencyBreakdown from OperationResult."""
    lb = getattr(res, "latency_breakdown", None)
    if lb is None:
        return {}
    out = {}
    for field_name in ("llm_inference_ms", "embedding_ms", "vector_search_ms",
                       "rados_io_ms", "response_format_ms", "total_ms"):
        out[field_name] = getattr(lb, field_name, 0.0) or 0.0
    return out


# ── main profiler ────────────────────────────────────────────────────────

class LatencyProfiler:
    """
    Run the workload multiple iterations, collect per-phase timings,
    and optionally compare with raw CLI commands.
    """

    def __init__(
        self,
        agent,
        workload: Optional[List[Dict[str, str]]] = None,
        pool_name: str = "testpool",
    ):
        self.agent = agent
        self.workload = workload or WORKLOAD
        self.pool_name = pool_name

    def profile(
        self,
        iterations: int = 5,
        include_cli: bool = True,
        warmup: int = 1,
        progress_callback=None,
    ) -> LatencyReport:
        logger.info("Latency profiler: %d ops × %d iters (+ %d warmup)",
                     len(self.workload), iterations, warmup)

        # ── warmup ───────────────────────────────────────────────────
        for _ in range(warmup):
            for w in self.workload[:3]:
                try:
                    self.agent.process_query(w["query"], auto_confirm=True)
                except Exception:
                    pass
            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

        # ── measured runs ────────────────────────────────────────────
        samples: List[LatencySample] = []
        cli_samples: List[CLISample] = []

        for it in range(1, iterations + 1):
            for widx, w in enumerate(self.workload):
                if progress_callback:
                    step = (it - 1) * len(self.workload) + widx + 1
                    total = iterations * len(self.workload)
                    progress_callback(step, total, "latency")

                # agent
                t0 = time.time()
                try:
                    res = self.agent.process_query(
                        w["query"], auto_confirm=True)
                    total_ms = (time.time() - t0) * 1000
                    bd = _extract_breakdown(res)
                except Exception:
                    total_ms = (time.time() - t0) * 1000
                    bd = {}

                llm = bd.get("llm_inference_ms", 0)
                emb = bd.get("embedding_ms", 0)
                vec = bd.get("vector_search_ms", 0)
                rio = bd.get("rados_io_ms", 0)
                rfmt = bd.get("response_format_ms", 0)
                other = max(0, total_ms - llm - emb - vec - rio - rfmt)

                samples.append(LatencySample(
                    label=w["label"], iteration=it,
                    total_ms=total_ms,
                    llm_inference_ms=llm, embedding_ms=emb,
                    vector_search_ms=vec, rados_io_ms=rio,
                    response_format_ms=rfmt, other_ms=other,
                ))

                # CLI
                if include_cli and w.get("cli"):
                    cli_ms = self._run_cli(w["cli"])
                    overhead = total_ms - cli_ms
                    overhead_pct = (overhead / cli_ms * 100
                                    if cli_ms > 0 else 0)
                    cli_samples.append(CLISample(
                        label=w["label"], iteration=it,
                        agent_ms=total_ms, cli_ms=cli_ms,
                        overhead_ms=overhead, overhead_pct=overhead_pct,
                    ))

            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

        # clean up benchmark object
        try:
            self.agent.process_query(
                "delete _bench_lat.txt", auto_confirm=True)
        except Exception:
            pass

        return self._build_report(samples, cli_samples, iterations)

    # ── CLI runner ───────────────────────────────────────────────────

    @staticmethod
    def _run_cli(cmd: str) -> float:
        t0 = time.time()
        try:
            subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
        except Exception:
            pass
        return (time.time() - t0) * 1000

    # ── report builder ───────────────────────────────────────────────

    def _build_report(
        self,
        samples: List[LatencySample],
        cli_samples: List[CLISample],
        iterations: int,
    ) -> LatencyReport:

        all_totals = [s.total_ms for s in samples]

        # per-operation profiles
        by_label: Dict[str, List[LatencySample]] = {}
        for s in samples:
            by_label.setdefault(s.label, []).append(s)

        profiles = []
        for label, ss in by_label.items():
            totals = [s.total_ms for s in ss]
            profiles.append(LatencyProfile(
                label=label, n=len(ss),
                total_mean=round(statistics.mean(totals), 1),
                total_std=round(
                    statistics.stdev(totals) if len(totals) > 1 else 0, 1),
                total_p50=round(_percentile(totals, 50), 1),
                total_p95=round(_percentile(totals, 95), 1),
                llm_mean=round(
                    statistics.mean([s.llm_inference_ms for s in ss]), 1),
                llm_std=round(
                    statistics.stdev([s.llm_inference_ms for s in ss])
                    if len(ss) > 1 else 0, 1),
                embedding_mean=round(
                    statistics.mean([s.embedding_ms for s in ss]), 1),
                rados_mean=round(
                    statistics.mean([s.rados_io_ms for s in ss]), 1),
                vector_mean=round(
                    statistics.mean([s.vector_search_ms for s in ss]), 1),
                other_mean=round(
                    statistics.mean([s.other_ms for s in ss]), 1),
            ))

        # CLI profiles
        cli_by_label: Dict[str, List[CLISample]] = {}
        for cs in cli_samples:
            cli_by_label.setdefault(cs.label, []).append(cs)

        cli_profiles = []
        for label, css in cli_by_label.items():
            a_vals = [c.agent_ms for c in css]
            c_vals = [c.cli_ms for c in css]
            a_m = statistics.mean(a_vals) if a_vals else 0
            c_m = statistics.mean(c_vals) if c_vals else 0
            overhead = a_m - c_m
            overhead_pct = overhead / c_m * 100 if c_m > 0 else 0
            cli_profiles.append(CLIProfile(
                label=label,
                agent_mean=round(a_m, 1),
                agent_std=round(
                    statistics.stdev(a_vals) if len(a_vals) > 1 else 0, 1),
                cli_mean=round(c_m, 1),
                cli_std=round(
                    statistics.stdev(c_vals) if len(c_vals) > 1 else 0, 1),
                overhead_mean=round(overhead, 1),
                overhead_pct=round(overhead_pct, 1),
            ))

        return LatencyReport(
            num_operations=len(self.workload),
            iterations=iterations,
            total_samples=len(samples),
            overall_mean_ms=round(
                statistics.mean(all_totals) if all_totals else 0, 1),
            overall_p50_ms=round(_percentile(all_totals, 50), 1),
            overall_p95_ms=round(_percentile(all_totals, 95), 1),
            overall_p99_ms=round(_percentile(all_totals, 99), 1),
            profiles=profiles,
            cli_profiles=cli_profiles,
            samples=samples,
            cli_samples=cli_samples,
        )
