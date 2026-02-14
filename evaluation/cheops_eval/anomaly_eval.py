"""
Anomaly-detection evaluation (Eval §4).

Feeds synthetic cluster states into AnomalyDetector.analyze() and
measures:
  • detection precision/recall per anomaly category
  • cluster-score accuracy (within expected bounds)
  • suggested-runbook relevance
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .test_cases import AnomalyScenario, get_anomaly_scenarios

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    scenario_id: str
    description: str
    # score
    cluster_score: float
    score_in_range: bool
    expected_min_score: int
    expected_max_score: int
    # detection
    detected_categories: List[str]
    expected_categories: List[str]
    num_anomalies: int
    expected_min_anomalies: int
    # precision / recall for this scenario
    category_precision: float
    category_recall: float
    # suggested runbooks
    suggested_runbooks: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AnomalyEvalReport:
    num_scenarios: int
    score_accuracy: float             # % scenarios where score is in range
    macro_precision: float            # avg precision across scenarios
    macro_recall: float               # avg recall across scenarios
    f1_score: float
    per_category_detection: Dict[str, Dict[str, int]] = field(
        default_factory=dict)         # cat → {tp, fp, fn}
    results: List[AnomalyResult] = field(default_factory=list)


class AnomalyEvaluator:
    """
    Evaluate AnomalyDetector against synthetic cluster states.

    Does NOT require a live Ceph cluster — states are injected directly.
    """

    def __init__(
        self,
        anomaly_detector,
        scenarios: Optional[List[AnomalyScenario]] = None,
    ):
        self.detector = anomaly_detector
        self.scenarios = scenarios or get_anomaly_scenarios()

    def evaluate(self, progress_callback=None) -> AnomalyEvalReport:
        logger.info("Anomaly evaluation: %d scenarios", len(self.scenarios))
        results: List[AnomalyResult] = []

        for idx, sc in enumerate(self.scenarios):
            if progress_callback:
                progress_callback(idx + 1, len(self.scenarios), "anomaly")
            try:
                result = self._evaluate_scenario(sc)
            except Exception as exc:
                result = AnomalyResult(
                    scenario_id=sc.id, description=sc.description,
                    cluster_score=0, score_in_range=False,
                    expected_min_score=sc.expected_min_score,
                    expected_max_score=sc.expected_max_score,
                    detected_categories=[], expected_categories=sc.expected_anomaly_categories,
                    num_anomalies=0, expected_min_anomalies=sc.expected_min_anomalies,
                    category_precision=0, category_recall=0,
                    error=str(exc),
                )
            results.append(result)

        return self._aggregate(results)

    # ── internals ────────────────────────────────────────────────────

    def _evaluate_scenario(self, sc: AnomalyScenario) -> AnomalyResult:
        report = self.detector.analyze(sc.cluster_state)

        score = getattr(report, "cluster_score", 0)
        score_ok = sc.expected_min_score <= score <= sc.expected_max_score

        # detected categories (normalise to upper case for comparison)
        detected = set()
        anomalies = getattr(report, "anomalies", [])
        for a in anomalies:
            cat = getattr(a, "category", None)
            if cat:
                cat_str = cat.value if hasattr(cat, "value") else str(cat)
                detected.add(cat_str.upper())

        expected = {c.upper() for c in sc.expected_anomaly_categories}

        # precision / recall
        tp = len(detected & expected)
        fp = len(detected - expected)
        fn = len(expected - detected)
        prec = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if not expected else 0.0)
        rec = tp / (tp + fn) if (tp + fn) > 0 else (1.0 if not expected else 0.0)

        # suggested runbooks
        runbooks = []
        for a in anomalies:
            rb = getattr(a, "suggested_runbook", None)
            if rb:
                runbooks.append(rb)

        return AnomalyResult(
            scenario_id=sc.id, description=sc.description,
            cluster_score=score, score_in_range=score_ok,
            expected_min_score=sc.expected_min_score,
            expected_max_score=sc.expected_max_score,
            detected_categories=sorted(detected),
            expected_categories=sorted(expected),
            num_anomalies=len(anomalies),
            expected_min_anomalies=sc.expected_min_anomalies,
            category_precision=round(prec, 3),
            category_recall=round(rec, 3),
            suggested_runbooks=runbooks,
        )

    def _aggregate(self, results: List[AnomalyResult]) -> AnomalyEvalReport:
        n = len(results)
        score_acc = sum(r.score_in_range for r in results) / n * 100 if n else 0
        precs = [r.category_precision for r in results]
        recs = [r.category_recall for r in results]
        macro_p = sum(precs) / n if n else 0
        macro_r = sum(recs) / n if n else 0
        f1 = (2 * macro_p * macro_r / (macro_p + macro_r)
               if (macro_p + macro_r) > 0 else 0)

        # per-category detection counts
        per_cat: Dict[str, Dict[str, int]] = {}
        all_cats = set()
        for r in results:
            all_cats.update(r.detected_categories)
            all_cats.update(r.expected_categories)

        for cat in sorted(all_cats):
            tp = fp = fn = 0
            for r in results:
                detected = cat in r.detected_categories
                expected = cat in r.expected_categories
                if detected and expected:
                    tp += 1
                elif detected and not expected:
                    fp += 1
                elif not detected and expected:
                    fn += 1
            per_cat[cat] = {"tp": tp, "fp": fp, "fn": fn}

        return AnomalyEvalReport(
            num_scenarios=n,
            score_accuracy=round(score_acc, 1),
            macro_precision=round(macro_p, 3),
            macro_recall=round(macro_r, 3),
            f1_score=round(f1, 3),
            per_category_detection=per_cat,
            results=results,
        )
