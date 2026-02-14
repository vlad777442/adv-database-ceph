"""
Safety-framework evaluation (Eval §3).

Tests the ActionEngine's risk-classification accuracy:
  • Does each action get the correct risk level?
  • Are HIGH / CRITICAL actions gated on confirmation?
  • Does rate-limiting trigger at the expected threshold?
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .test_cases import ExpectedRisk, SafetyTestCase, get_safety_test_cases

logger = logging.getLogger(__name__)


@dataclass
class SafetyResult:
    test_id: str
    action_name: str
    expected_risk: str
    predicted_risk: str
    risk_correct: bool
    confirmation_required: bool
    confirmation_expected: bool
    confirmation_correct: bool
    description: str
    error: Optional[str] = None


@dataclass
class SafetyEvalReport:
    num_tests: int
    risk_accuracy: float           # % correct risk level
    confirmation_accuracy: float   # % correct confirmation requirement
    per_level_accuracy: Dict[str, float] = field(default_factory=dict)
    results: List[SafetyResult] = field(default_factory=list)
    rate_limit_tested: bool = False
    rate_limit_correct: bool = False


class SafetyEvaluator:
    """
    Evaluate the ActionEngine risk classification against ground truth.

    Does NOT actually execute destructive actions — it only calls
    ``action_engine.check_action()`` which classifies risk and returns
    whether confirmation is needed.
    """

    def __init__(
        self,
        action_engine,
        test_cases: Optional[List[SafetyTestCase]] = None,
    ):
        self.engine = action_engine
        self.test_cases = test_cases or get_safety_test_cases()

    # ── main ─────────────────────────────────────────────────────────

    def evaluate(self, progress_callback=None) -> SafetyEvalReport:
        logger.info("Safety evaluation: %d test cases", len(self.test_cases))
        results: List[SafetyResult] = []

        for idx, tc in enumerate(self.test_cases):
            if progress_callback:
                progress_callback(idx + 1, len(self.test_cases), "safety")
            try:
                result = self._evaluate_one(tc)
            except Exception as exc:
                result = SafetyResult(
                    test_id=tc.id, action_name=tc.action_name,
                    expected_risk=tc.expected_risk.value,
                    predicted_risk="ERROR",
                    risk_correct=False,
                    confirmation_required=False,
                    confirmation_expected=tc.should_require_confirmation,
                    confirmation_correct=False,
                    description=tc.description,
                    error=str(exc),
                )
            results.append(result)

        # ── aggregate ────────────────────────────────────────────────

        risk_correct = sum(r.risk_correct for r in results)
        conf_correct = sum(r.confirmation_correct for r in results)
        n = len(results)
        risk_acc = risk_correct / n * 100 if n else 0
        conf_acc = conf_correct / n * 100 if n else 0

        per_level: Dict[str, List[bool]] = {}
        for r in results:
            per_level.setdefault(r.expected_risk, []).append(r.risk_correct)
        per_level_acc = {
            lv: sum(bs) / len(bs) * 100
            for lv, bs in per_level.items()
        }

        # ── rate-limit test ──────────────────────────────────────────
        rl_tested, rl_ok = self._test_rate_limit()

        return SafetyEvalReport(
            num_tests=n,
            risk_accuracy=round(risk_acc, 1),
            confirmation_accuracy=round(conf_acc, 1),
            per_level_accuracy=per_level_acc,
            results=results,
            rate_limit_tested=rl_tested,
            rate_limit_correct=rl_ok,
        )

    # ── internals ────────────────────────────────────────────────────

    def _evaluate_one(self, tc: SafetyTestCase) -> SafetyResult:
        # Try the engine's check_action API
        allowed, msg = self.engine.check_action(
            tc.action_name, tc.action_params, reason="eval_test"
        )

        # Determine predicted risk from the engine's internal mapping
        pred_risk = self._get_predicted_risk(tc.action_name)
        # Normalise to upper-case for comparison (ActionRisk uses lower)
        pred_upper = pred_risk.upper()
        expected_upper = tc.expected_risk.value.upper()
        risk_ok = (pred_upper == expected_upper)

        # Confirmation: HIGH and CRITICAL should require it
        conf_required = not allowed  # if check_action blocks, it needs confirm
        # Alternatively, check the policy
        if hasattr(self.engine, "policy"):
            policy = self.engine.policy
            auto_level = getattr(policy, "auto_approve_level", "LOW").upper()
            # actions above auto_approve_level need confirmation
            risk_order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            auto_idx = risk_order.index(auto_level) if auto_level in risk_order else 0
            pred_idx = risk_order.index(pred_upper) if pred_upper in risk_order else 0
            conf_required = pred_idx > auto_idx

        conf_ok = (conf_required == tc.should_require_confirmation)

        return SafetyResult(
            test_id=tc.id, action_name=tc.action_name,
            expected_risk=tc.expected_risk.value,
            predicted_risk=pred_risk,
            risk_correct=risk_ok,
            confirmation_required=conf_required,
            confirmation_expected=tc.should_require_confirmation,
            confirmation_correct=conf_ok,
            description=tc.description,
        )

    def _get_predicted_risk(self, action_name: str) -> str:
        """Extract the risk level the engine assigns to this action."""
        # Try the ACTION_RISK_MAP
        if hasattr(self.engine, "ACTION_RISK_MAP"):
            risk = self.engine.ACTION_RISK_MAP.get(action_name)
            if risk:
                return risk.value if hasattr(risk, "value") else str(risk)

        # Try action_risk_map as attribute
        if hasattr(self.engine, "action_risk_map"):
            risk = self.engine.action_risk_map.get(action_name)
            if risk:
                return risk.value if hasattr(risk, "value") else str(risk)

        # Try classify_risk method
        if hasattr(self.engine, "classify_risk"):
            risk = self.engine.classify_risk(action_name)
            return risk.value if hasattr(risk, "value") else str(risk)

        # Fallback: look in the class
        cls = type(self.engine)
        if hasattr(cls, "ACTION_RISK_MAP"):
            risk = cls.ACTION_RISK_MAP.get(action_name)
            if risk:
                return risk.value if hasattr(risk, "value") else str(risk)

        return "UNKNOWN"

    def _test_rate_limit(self) -> tuple:
        """Verify rate limiting by attempting many LOW-risk actions."""
        if not hasattr(self.engine, "policy"):
            return False, False

        policy = self.engine.policy
        limit = getattr(policy, "max_actions_per_session", 20)

        # Reset action count
        if hasattr(self.engine, "action_count"):
            old_count = self.engine.action_count
            self.engine.action_count = limit - 1  # one below limit

        try:
            # This should succeed (at the limit)
            ok1, _ = self.engine.check_action(
                "list_objects", {}, reason="rate_limit_test")
            # Push over the limit
            if hasattr(self.engine, "action_count"):
                self.engine.action_count = limit + 1
            ok2, _ = self.engine.check_action(
                "list_objects", {}, reason="rate_limit_test")
            # ok2 should be False (rate limited)
            return True, (ok1 and not ok2)
        except Exception:
            return True, False
        finally:
            if hasattr(self.engine, "action_count"):
                self.engine.action_count = old_count if 'old_count' in dir() else 0
