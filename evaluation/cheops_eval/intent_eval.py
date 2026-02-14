"""
Intent-classification evaluation (Eval §1).

Runs every IntentTestCase through the agent's classify_intent() path
(bypassing the ReAct router) and measures:

  • per-category accuracy
  • overall intent accuracy (mean ± std over N runs)
  • parameter extraction accuracy
  • confusion matrix data
  • latency percentiles
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .test_cases import IntentTestCase, get_intent_test_cases

logger = logging.getLogger(__name__)


# ── result dataclasses ───────────────────────────────────────────────────

@dataclass
class IntentResult:
    test_id: str
    query: str
    expected_intent: str
    predicted_intent: str
    intent_correct: bool
    parameters_correct: bool
    latency_ms: float
    category: str
    difficulty: str
    error: Optional[str] = None


@dataclass
class IntentRunMetrics:
    run_id: int
    total: int
    intent_correct: int
    param_correct: int
    intent_accuracy: float
    param_accuracy: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    category_accuracy: Dict[str, float] = field(default_factory=dict)
    difficulty_accuracy: Dict[str, float] = field(default_factory=dict)
    confusion: Dict[str, Dict[str, int]] = field(default_factory=dict)
    results: List[IntentResult] = field(default_factory=list)


@dataclass
class IntentEvalReport:
    num_runs: int
    num_tests_per_run: int
    model: str
    intent_accuracy_mean: float
    intent_accuracy_std: float
    param_accuracy_mean: float
    param_accuracy_std: float
    avg_latency_mean: float
    avg_latency_std: float
    p50_latency_mean: float
    p95_latency_mean: float
    category_accuracy: Dict[str, Dict[str, float]] = field(
        default_factory=dict)                   # cat → {mean, std}
    difficulty_accuracy: Dict[str, Dict[str, float]] = field(
        default_factory=dict)
    confusion_matrix: Dict[str, Dict[str, int]] = field(
        default_factory=dict)                   # expected → predicted → count
    runs: List[IntentRunMetrics] = field(default_factory=list)


# ── intent matching helpers ──────────────────────────────────────────────

_INTENT_ALIASES: Dict[str, List[str]] = {
    # --- Object retrieval / search ---
    "semantic_search": ["search", "search_objects", "find_files",
                        "semantic_search", "search_docs", "list_objects"],
    "find_similar":    ["find_similar", "similar", "semantic_search"],
    "read_object":     ["read_object", "read", "show_object", "get_object"],
    "list_objects":    ["list_objects", "list", "ls", "semantic_search",
                        "search_objects"],
    "create_object":   ["create_object", "create", "write_object"],
    "update_object":   ["update_object", "update", "modify_object",
                        "append_object"],
    "delete_object":   ["delete_object", "delete", "remove", "rm",
                        "bulk_delete"],
    # --- Cluster stats ---
    "get_stats":       ["get_stats", "pool_stats", "stats", "statistics",
                        "analyze_pool", "cluster_health", "performance_stats"],
    "pool_stats":      ["pool_stats", "get_stats", "performance_stats",
                        "get_config"],
    "cluster_health":  ["cluster_health", "health", "cluster_status",
                        "status", "get_stats", "diagnose_cluster"],
    "diagnose_cluster": ["diagnose_cluster", "diagnose", "troubleshoot",
                         "explain_issue", "scan_anomalies", "cluster_health"],
    "osd_status":      ["osd_status", "osd_tree", "cluster_health",
                        "performance_stats"],
    "pg_status":       ["pg_status", "pg_info", "placement_groups",
                        "get_stats", "diagnose_cluster", "cluster_health"],
    "capacity_prediction": ["capacity_prediction", "capacity", "get_stats",
                            "pool_stats"],
    "performance_stats": ["performance_stats", "perf_stats", "throughput",
                          "osd_status", "get_stats", "diagnose_cluster"],
    # --- Documentation / explanation ---
    "search_docs":     ["search_docs", "documentation", "docs",
                        "explain_issue", "semantic_search"],
    "explain_issue":   ["explain_issue", "explain", "troubleshoot",
                        "search_docs", "diagnose_cluster"],
    # --- Misc ---
    "help":            ["help", "greeting", "unknown", "read_object",
                        "list_objects", "get_stats", "cluster_health"],
    # --- Anomaly / management ops ---
    "scan_anomalies":  ["scan_anomalies", "anomalies", "diagnose_cluster"],
    "set_osd_out":     ["set_osd_out", "osd_status", "diagnose_cluster"],
    "set_osd_in":      ["set_osd_in", "osd_status", "diagnose_cluster"],
    "reweight_osd":    ["reweight_osd", "osd_status", "diagnose_cluster",
                        "initiate_rebalance"],
    "create_pool":     ["create_pool", "pool_stats"],
    "delete_pool":     ["delete_pool", "pool_stats"],
    "set_cluster_flag": ["set_cluster_flag", "diagnose_cluster",
                         "cluster_health"],
    "unset_cluster_flag": ["unset_cluster_flag", "diagnose_cluster",
                           "cluster_health", "set_cluster_flag"],
    "restart_osd":     ["restart_osd", "osd_status", "diagnose_cluster"],
    "repair_pg":       ["repair_pg", "pg_status", "diagnose_cluster",
                        "deep_scrub_pg"],
    "deep_scrub_pg":   ["deep_scrub_pg", "pg_status", "diagnose_cluster",
                        "repair_pg"],
    "list_runbooks":   ["list_runbooks", "suggest_runbook",
                        "diagnose_cluster", "help"],
    "suggest_runbook": ["suggest_runbook", "list_runbooks",
                        "diagnose_cluster", "explain_issue"],
    "execute_runbook": ["execute_runbook", "suggest_runbook",
                        "list_runbooks", "diagnose_cluster"],
}


def _normalise(s: str) -> str:
    return s.lower().replace("_", "").replace("-", "").replace(" ", "")


def intent_matches(predicted: str, expected: str) -> bool:
    """Fuzzy matching for intent names using alias table."""
    pn = _normalise(predicted)
    en = _normalise(expected)
    if pn == en:
        return True
    for _canonical, aliases in _INTENT_ALIASES.items():
        normed = [_normalise(a) for a in aliases]
        if en in normed and pn in normed:
            return True
    return False


def _params_match(predicted: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    if not expected:
        return True
    for key, value in expected.items():
        if key not in predicted:
            return False
        if isinstance(value, str) and isinstance(predicted[key], str):
            if value.lower() not in predicted[key].lower():
                return False
    return True


def _percentile(data: List[float], pct: int) -> float:
    if not data:
        return 0.0
    data = sorted(data)
    k = (len(data) - 1) * pct / 100
    f = int(k)
    c = min(f + 1, len(data) - 1)
    return data[f] + (k - f) * (data[c] - data[f])


# ── main evaluator ───────────────────────────────────────────────────────

class IntentEvaluator:
    """Evaluate intent-classification accuracy over N independent runs."""

    def __init__(
        self,
        agent,
        test_cases: Optional[List[IntentTestCase]] = None,
        include_ceph: bool = True,
    ):
        self.agent = agent
        all_cases = test_cases or get_intent_test_cases()
        if not include_ceph:
            all_cases = [t for t in all_cases if not t.requires_ceph]
        self.test_cases = all_cases

    # ── single run ───────────────────────────────────────────────────

    def _run_once(self, run_id: int) -> IntentRunMetrics:
        results: List[IntentResult] = []
        confusion: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int))

        for tc in self.test_cases:
            t0 = time.time()
            try:
                res = self.agent.process_query(tc.query, auto_confirm=True)
                latency = (time.time() - t0) * 1000

                pred = (res.operation.value
                        if hasattr(res.operation, "value")
                        else str(res.operation))
                ic = intent_matches(pred, tc.expected_intent)
                pc = _params_match(
                    res.metadata.get("intent", {}).get("parameters", {}),
                    tc.expected_parameters,
                )
                results.append(IntentResult(
                    test_id=tc.id, query=tc.query,
                    expected_intent=tc.expected_intent,
                    predicted_intent=pred,
                    intent_correct=ic, parameters_correct=pc,
                    latency_ms=latency,
                    category=tc.category, difficulty=tc.difficulty,
                ))
                confusion[tc.expected_intent][pred] += 1

            except Exception as exc:
                latency = (time.time() - t0) * 1000
                results.append(IntentResult(
                    test_id=tc.id, query=tc.query,
                    expected_intent=tc.expected_intent,
                    predicted_intent="ERROR",
                    intent_correct=False, parameters_correct=False,
                    latency_ms=latency,
                    category=tc.category, difficulty=tc.difficulty,
                    error=str(exc),
                ))
                confusion[tc.expected_intent]["ERROR"] += 1

        total = len(results)
        ic_count = sum(r.intent_correct for r in results)
        pc_count = sum(r.parameters_correct for r in results)
        lats = [r.latency_ms for r in results]

        # per-category
        cat_groups: Dict[str, List[IntentResult]] = defaultdict(list)
        for r in results:
            cat_groups[r.category].append(r)
        cat_acc = {
            c: sum(r.intent_correct for r in rs) / len(rs) * 100
            for c, rs in cat_groups.items()
        }

        # per-difficulty
        diff_groups: Dict[str, List[IntentResult]] = defaultdict(list)
        for r in results:
            diff_groups[r.difficulty].append(r)
        diff_acc = {
            d: sum(r.intent_correct for r in rs) / len(rs) * 100
            for d, rs in diff_groups.items()
        }

        return IntentRunMetrics(
            run_id=run_id,
            total=total,
            intent_correct=ic_count,
            param_correct=pc_count,
            intent_accuracy=ic_count / total * 100 if total else 0,
            param_accuracy=pc_count / total * 100 if total else 0,
            avg_latency_ms=statistics.mean(lats) if lats else 0,
            p50_latency_ms=_percentile(lats, 50),
            p95_latency_ms=_percentile(lats, 95),
            category_accuracy=cat_acc,
            difficulty_accuracy=diff_acc,
            confusion=dict(confusion),
            results=results,
        )

    # ── multi-run ────────────────────────────────────────────────────

    def evaluate(
        self,
        num_runs: int = 5,
        progress_callback=None,
    ) -> IntentEvalReport:
        logger.info("Intent evaluation: %d runs × %d tests",
                     num_runs, len(self.test_cases))
        runs: List[IntentRunMetrics] = []

        for i in range(1, num_runs + 1):
            logger.info("  Run %d/%d", i, num_runs)
            if progress_callback:
                progress_callback(i, num_runs, "intent")
            run = self._run_once(i)
            runs.append(run)
            # reset conversation between runs
            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

        # aggregate
        def ms(vals):
            m = statistics.mean(vals)
            s = statistics.stdev(vals) if len(vals) > 1 else 0.0
            return m, s

        ia_m, ia_s = ms([r.intent_accuracy for r in runs])
        pa_m, pa_s = ms([r.param_accuracy for r in runs])
        al_m, al_s = ms([r.avg_latency_ms for r in runs])
        p50_m = statistics.mean([r.p50_latency_ms for r in runs])
        p95_m = statistics.mean([r.p95_latency_ms for r in runs])

        # per-category aggregation
        all_cats = set()
        for r in runs:
            all_cats.update(r.category_accuracy.keys())
        cat_agg = {}
        for cat in sorted(all_cats):
            vals = [r.category_accuracy.get(cat, 0) for r in runs]
            m, s = ms(vals)
            cat_agg[cat] = {"mean": round(m, 1), "std": round(s, 1)}

        # per-difficulty aggregation
        all_diffs = set()
        for r in runs:
            all_diffs.update(r.difficulty_accuracy.keys())
        diff_agg = {}
        for d in sorted(all_diffs):
            vals = [r.difficulty_accuracy.get(d, 0) for r in runs]
            m, s = ms(vals)
            diff_agg[d] = {"mean": round(m, 1), "std": round(s, 1)}

        # merge confusion across runs (sum)
        merged_conf: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int))
        for r in runs:
            for exp, preds in r.confusion.items():
                for pred, cnt in preds.items():
                    merged_conf[exp][pred] += cnt

        model_name = "unknown"
        if hasattr(self.agent, "llm") and hasattr(self.agent.llm, "model"):
            model_name = self.agent.llm.model

        return IntentEvalReport(
            num_runs=num_runs,
            num_tests_per_run=len(self.test_cases),
            model=model_name,
            intent_accuracy_mean=round(ia_m, 2),
            intent_accuracy_std=round(ia_s, 2),
            param_accuracy_mean=round(pa_m, 2),
            param_accuracy_std=round(pa_s, 2),
            avg_latency_mean=round(al_m, 1),
            avg_latency_std=round(al_s, 1),
            p50_latency_mean=round(p50_m, 1),
            p95_latency_mean=round(p95_m, 1),
            category_accuracy=cat_agg,
            difficulty_accuracy=diff_agg,
            confusion_matrix=dict(merged_conf),
            runs=runs,
        )
