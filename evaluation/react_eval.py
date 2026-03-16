"""
ReAct vs Simple-mode comparison (Eval §2).

For each ReactTestCase, runs the query in BOTH modes and compares:
  • mode routing accuracy — did the agent pick the correct mode?
  • task completion — did it produce a relevant, non-error answer?
  • tool coverage — did it use the expected tools?
  • step count — how many ReAct iterations were needed?
  • latency — wall-clock time per mode
"""

from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from evaluation.test_cases import ExpectedMode, ReactTestCase, get_react_test_cases

logger = logging.getLogger(__name__)


@dataclass
class ModeTrial:
    """Outcome of running a single query in one mode."""
    mode: str                 # "simple" | "react"
    latency_ms: float
    success: bool             # non-error response produced
    response_snippet: str     # first 300 chars
    tools_used: List[str] = field(default_factory=list)
    num_steps: int = 0
    error: Optional[str] = None


@dataclass
class ReactResult:
    test_id: str
    query: str
    expected_mode: str
    description: str
    routing_correct: bool     # did agent choose the expected mode?
    simple_trial: Optional[ModeTrial] = None
    react_trial: Optional[ModeTrial] = None
    tool_coverage: float = 0.0     # fraction of expected tools used


@dataclass
class ReactEvalReport:
    num_tests: int
    routing_accuracy: float          # % queries routed to correct mode
    # simple-mode aggregates
    simple_success_rate: float
    simple_avg_latency_ms: float
    # react-mode aggregates
    react_success_rate: float
    react_avg_latency_ms: float
    react_avg_steps: float
    react_tool_coverage: float       # avg fraction of expected tools found
    # per-test details
    results: List[ReactResult] = field(default_factory=list)
    # summary: tasks where ReAct helped vs hurt
    react_wins: int = 0
    simple_wins: int = 0
    ties: int = 0


class ReactEvaluator:
    """
    Compare ReAct and Simple execution paths.

    Strategy:
      1. Run query in SIMPLE mode (force _should_use_react → False).
      2. Run query in REACT mode (force _should_use_react → True).
      3. Record which mode the agent would *naturally* choose.
      4. Compare quality, latency, and tool usage.
    """

    def __init__(
        self,
        agent,
        test_cases: Optional[List[ReactTestCase]] = None,
        include_ceph: bool = True,
    ):
        self.agent = agent
        all_cases = test_cases or get_react_test_cases()
        if not include_ceph:
            all_cases = [t for t in all_cases if not t.requires_ceph]
        self.test_cases = all_cases

    # ── helpers ──────────────────────────────────────────────────────

    def _force_simple(self, query: str) -> ModeTrial:
        """Run in simple intent→execute mode by temporarily disabling ReAct."""
        # Save original method
        original = getattr(self.agent, "_should_use_react", None)
        try:
            self.agent._should_use_react = lambda q: False
            t0 = time.time()
            res = self.agent.process_query(query, auto_confirm=True)
            lat = (time.time() - t0) * 1000

            tools = self._extract_tools_from_result(res)
            return ModeTrial(
                mode="simple", latency_ms=lat, success=res.success,
                response_snippet=res.message[:300],
                tools_used=tools, num_steps=1,
            )
        except Exception as exc:
            return ModeTrial(
                mode="simple", latency_ms=0, success=False,
                response_snippet="", error=str(exc),
            )
        finally:
            if original is not None:
                self.agent._should_use_react = original
            else:
                # Remove the lambda if the method didn't exist before
                if hasattr(self.agent, "_should_use_react"):
                    delattr(self.agent, "_should_use_react")

    def _force_react(self, query: str) -> ModeTrial:
        """Run in ReAct mode by forcing the router."""
        original = getattr(self.agent, "_should_use_react", None)
        try:
            self.agent._should_use_react = lambda q: True
            t0 = time.time()
            res = self.agent.process_query(query, auto_confirm=True)
            lat = (time.time() - t0) * 1000

            tools = self._extract_tools_from_result(res)
            steps = self._extract_step_count(res)
            return ModeTrial(
                mode="react", latency_ms=lat, success=res.success,
                response_snippet=res.message[:300],
                tools_used=tools, num_steps=steps,
            )
        except Exception as exc:
            return ModeTrial(
                mode="react", latency_ms=0, success=False,
                response_snippet="", error=str(exc),
            )
        finally:
            if original is not None:
                self.agent._should_use_react = original
            else:
                if hasattr(self.agent, "_should_use_react"):
                    delattr(self.agent, "_should_use_react")

    def _natural_mode(self, query: str) -> str:
        """Which mode would the agent naturally choose (via LLM router)?"""
        try:
            use_react = self.agent.__class__._should_use_react(self.agent, query)
            return "react" if use_react else "simple"
        except Exception:
            logger.warning("Failed to call LLM router for natural mode; defaulting to simple")
            return "simple"

    @staticmethod
    def _extract_tools_from_result(res) -> List[str]:
        """Best-effort extraction of tools used from result metadata/data."""
        tools = []
        # ReAct mode stores trace in res.data
        data = getattr(res, "data", {}) or {}
        if "agent_trace" in data:
            trace = data["agent_trace"]
            if isinstance(trace, dict):
                tools = trace.get("tools_used", [])
            elif hasattr(trace, "tools_used"):
                tools = list(trace.tools_used)
        if not tools and "tools_used" in data:
            t = data["tools_used"]
            tools = list(t) if t else []
        # Also check metadata (simple mode stores intent there)
        if not tools:
            meta = getattr(res, "metadata", {}) or {}
            if "agent_trace" in meta:
                trace = meta["agent_trace"]
                if isinstance(trace, dict):
                    tools = trace.get("tools_used", [])
                elif hasattr(trace, "tools_used"):
                    tools = list(trace.tools_used)
        # fallback: the classified operation itself counts as a tool
        if not tools:
            op = res.operation
            op_name = op.value if hasattr(op, "value") else str(op)
            tools = [op_name]
        return tools

    @staticmethod
    def _extract_step_count(res) -> int:
        # Check res.data first (ReAct mode)
        data = getattr(res, "data", {}) or {}
        if "iterations" in data:
            return data["iterations"]
        if "agent_trace" in data:
            trace = data["agent_trace"]
            if isinstance(trace, dict):
                return trace.get("iterations", 1)
            elif hasattr(trace, "iterations"):
                return trace.iterations
        # Fallback to metadata
        meta = getattr(res, "metadata", {}) or {}
        if "agent_trace" in meta:
            trace = meta["agent_trace"]
            if isinstance(trace, dict):
                return trace.get("iterations", 1)
            elif hasattr(trace, "iterations"):
                return trace.iterations
        return 1

    @staticmethod
    def _tool_coverage(used: List[str], expected: List[str]) -> float:
        if not expected:
            return 1.0
        # normalise tool names
        used_norm = {t.lower().replace("_", "") for t in used}
        hits = sum(
            1 for e in expected
            if e.lower().replace("_", "") in used_norm
        )
        return hits / len(expected)

    # ── main ─────────────────────────────────────────────────────────

    def evaluate(self, progress_callback=None) -> ReactEvalReport:
        logger.info("ReAct evaluation: %d scenarios", len(self.test_cases))
        results: List[ReactResult] = []

        for idx, tc in enumerate(self.test_cases):
            logger.info("  [%d/%d] %s — %s",
                        idx + 1, len(self.test_cases), tc.id, tc.description)
            if progress_callback:
                progress_callback(idx + 1, len(self.test_cases), "react")

            nat_mode = self._natural_mode(tc.query)
            routing_ok = (nat_mode == tc.expected_mode.value)

            # run both modes
            simple = self._force_simple(tc.query)
            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

            react = self._force_react(tc.query)
            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

            # tool coverage for react
            tc_cov = self._tool_coverage(react.tools_used, tc.expected_tools)

            results.append(ReactResult(
                test_id=tc.id, query=tc.query,
                expected_mode=tc.expected_mode.value,
                description=tc.description,
                routing_correct=routing_ok,
                simple_trial=simple, react_trial=react,
                tool_coverage=tc_cov,
            ))

        # ── aggregate ────────────────────────────────────────────────

        routing_acc = (
            sum(r.routing_correct for r in results) / len(results) * 100
            if results else 0
        )
        s_successes = [r.simple_trial for r in results
                       if r.simple_trial and r.simple_trial.success]
        r_successes = [r.react_trial for r in results
                       if r.react_trial and r.react_trial.success]

        s_rate = len(s_successes) / len(results) * 100 if results else 0
        r_rate = len(r_successes) / len(results) * 100 if results else 0

        s_lats = [r.simple_trial.latency_ms for r in results
                  if r.simple_trial]
        r_lats = [r.react_trial.latency_ms for r in results
                  if r.react_trial]
        r_steps = [r.react_trial.num_steps for r in results
                   if r.react_trial]
        r_covs = [r.tool_coverage for r in results]

        # wins / losses
        react_wins = simple_wins = ties = 0
        for r in results:
            s_ok = r.simple_trial and r.simple_trial.success
            r_ok = r.react_trial and r.react_trial.success
            if r_ok and not s_ok:
                react_wins += 1
            elif s_ok and not r_ok:
                simple_wins += 1
            else:
                ties += 1

        return ReactEvalReport(
            num_tests=len(results),
            routing_accuracy=round(routing_acc, 1),
            simple_success_rate=round(s_rate, 1),
            simple_avg_latency_ms=round(
                statistics.mean(s_lats), 1) if s_lats else 0,
            react_success_rate=round(r_rate, 1),
            react_avg_latency_ms=round(
                statistics.mean(r_lats), 1) if r_lats else 0,
            react_avg_steps=round(
                statistics.mean(r_steps), 1) if r_steps else 0,
            react_tool_coverage=round(
                statistics.mean(r_covs), 2) if r_covs else 0,
            results=results,
            react_wins=react_wins, simple_wins=simple_wins, ties=ties,
        )
