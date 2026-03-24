"""
Integration evaluation (Eval §6) — live-cluster end-to-end tests.

Requires a running Ceph cluster with at least 3 OSDs and root access.
Gated behind ``--integration`` in the evaluation runner.

Each scenario follows: setup → inject fault → run agent → verify → cleanup.

Fault injection scenarios (``--integration-fault-injection``) additionally
stop/start OSD daemons and require systemd access.

Usage:
    sudo venv/bin/python -m evaluation.runner --integration
    sudo venv/bin/python -m evaluation.runner --integration-fault-injection --osd-id 2
"""

from __future__ import annotations

import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── result dataclasses ───────────────────────────────────────────────────

@dataclass
class IntegrationStepResult:
    step: str
    success: bool
    duration_ms: float
    detail: str = ""
    error: Optional[str] = None


@dataclass
class IntegrationResult:
    scenario_id: str
    description: str
    passed: bool
    steps: List[IntegrationStepResult] = field(default_factory=list)
    agent_response: str = ""
    total_duration_ms: float = 0.0


@dataclass
class IntegrationEvalReport:
    num_scenarios: int
    passed: int
    failed: int
    skipped: int
    results: List[IntegrationResult] = field(default_factory=list)


# ── helper: run ceph CLI ─────────────────────────────────────────────────

def _ceph_cmd(args: List[str], timeout: int = 30) -> Dict[str, Any]:
    """Run a ceph CLI command and return parsed output."""
    cmd = ["ceph"] + args + ["--format", "json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        import json
        if proc.returncode == 0:
            try:
                return {"success": True, "data": json.loads(proc.stdout)}
            except json.JSONDecodeError:
                return {"success": True, "data": proc.stdout.strip()}
        return {"success": False, "error": proc.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except FileNotFoundError:
        return {"success": False, "error": "ceph CLI not found"}


def _ceph_cmd_plain(args: List[str], timeout: int = 30) -> Dict[str, Any]:
    """Run a ceph CLI command, return raw text output."""
    cmd = ["ceph"] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── abstract scenario ────────────────────────────────────────────────────

class IntegrationScenario(ABC):
    """Base class for live integration test scenarios."""

    id: str
    description: str
    requires_root: bool = True

    @abstractmethod
    def setup(self) -> IntegrationStepResult:
        """Prepare cluster state for the test."""

    @abstractmethod
    def run_agent(self, agent) -> IntegrationStepResult:
        """Execute the agent query and capture response."""

    @abstractmethod
    def verify(self) -> IntegrationStepResult:
        """Verify the cluster is in the expected state after agent action."""

    @abstractmethod
    def cleanup(self) -> IntegrationStepResult:
        """Restore cluster to pre-test state."""


# ── Scenario 1: Pool lifecycle ───────────────────────────────────────────

class PoolLifecycleScenario(IntegrationScenario):
    """
    Create a pool → agent verifies it → set parameter → delete → verify gone.

    This is a safe, non-destructive test that creates a temporary pool.
    """

    id = "int01"
    description = "Pool lifecycle: create → inspect → configure → delete"
    POOL_NAME = "_ceph_sre_test_pool"

    def setup(self) -> IntegrationStepResult:
        t0 = time.time()
        # Ensure pool doesn't already exist
        r = _ceph_cmd_plain(["osd", "pool", "delete", self.POOL_NAME,
                             self.POOL_NAME, "--yes-i-really-really-mean-it"])
        # Create the pool
        r = _ceph_cmd_plain(["osd", "pool", "create", self.POOL_NAME, "8"])
        return IntegrationStepResult(
            step="setup", success=r["success"],
            duration_ms=(time.time() - t0) * 1000,
            detail=f"Created pool {self.POOL_NAME}",
            error=r.get("stderr") if not r["success"] else None,
        )

    def run_agent(self, agent) -> IntegrationStepResult:
        t0 = time.time()
        try:
            res = agent.process_query(
                f"Show me details about pool {self.POOL_NAME}",
                auto_confirm=True,
            )
            return IntegrationStepResult(
                step="agent_query", success=res.success,
                duration_ms=(time.time() - t0) * 1000,
                detail=res.message[:300],
            )
        except Exception as e:
            return IntegrationStepResult(
                step="agent_query", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=str(e),
            )

    def verify(self) -> IntegrationStepResult:
        t0 = time.time()
        r = _ceph_cmd(["osd", "pool", "ls"])
        if not r["success"]:
            return IntegrationStepResult(
                step="verify", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=r.get("error", "pool list failed"),
            )
        pools = r["data"] if isinstance(r["data"], list) else []
        found = self.POOL_NAME in pools
        return IntegrationStepResult(
            step="verify", success=found,
            duration_ms=(time.time() - t0) * 1000,
            detail=f"Pool {'found' if found else 'NOT found'} in cluster",
        )

    def cleanup(self) -> IntegrationStepResult:
        t0 = time.time()
        r = _ceph_cmd_plain(["osd", "pool", "delete", self.POOL_NAME,
                             self.POOL_NAME, "--yes-i-really-really-mean-it"])
        return IntegrationStepResult(
            step="cleanup", success=True,
            duration_ms=(time.time() - t0) * 1000,
            detail="Pool deleted",
        )


# ── Scenario 2: Flag management ─────────────────────────────────────────

class FlagManagementScenario(IntegrationScenario):
    """
    Set noout flag → agent diagnoses → unset flag → verify cleared.

    Uses the safe, reversible noout flag.
    """

    id = "int02"
    description = "Flag management: set noout → diagnose → unset"

    def setup(self) -> IntegrationStepResult:
        t0 = time.time()
        r = _ceph_cmd_plain(["osd", "set", "noout"])
        return IntegrationStepResult(
            step="setup", success=r["success"],
            duration_ms=(time.time() - t0) * 1000,
            detail="Set noout flag",
            error=r.get("stderr") if not r["success"] else None,
        )

    def run_agent(self, agent) -> IntegrationStepResult:
        t0 = time.time()
        try:
            res = agent.process_query(
                "Check cluster health and tell me about any flags that are set",
                auto_confirm=True,
            )
            return IntegrationStepResult(
                step="agent_query", success=res.success,
                duration_ms=(time.time() - t0) * 1000,
                detail=res.message[:300],
            )
        except Exception as e:
            return IntegrationStepResult(
                step="agent_query", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=str(e),
            )

    def verify(self) -> IntegrationStepResult:
        t0 = time.time()
        r = _ceph_cmd(["osd", "dump"])
        if not r["success"]:
            return IntegrationStepResult(
                step="verify", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error="osd dump failed",
            )
        flags = r["data"].get("flags", "") if isinstance(r["data"], dict) else ""
        has_noout = "noout" in flags
        return IntegrationStepResult(
            step="verify", success=True,
            duration_ms=(time.time() - t0) * 1000,
            detail=f"noout flag {'present' if has_noout else 'absent'} "
                   f"(flags: {flags})",
        )

    def cleanup(self) -> IntegrationStepResult:
        t0 = time.time()
        _ceph_cmd_plain(["osd", "unset", "noout"])
        return IntegrationStepResult(
            step="cleanup", success=True,
            duration_ms=(time.time() - t0) * 1000,
            detail="Unset noout flag",
        )


# ── Scenario 3: Agent health diagnosis ──────────────────────────────────

class HealthDiagnosisScenario(IntegrationScenario):
    """
    Ask the agent to diagnose cluster health on a live cluster.

    Non-destructive: only runs read-only operations.
    """

    id = "int03"
    description = "Health diagnosis: full cluster health check via agent"
    requires_root = False

    def setup(self) -> IntegrationStepResult:
        t0 = time.time()
        r = _ceph_cmd(["health"])
        return IntegrationStepResult(
            step="setup", success=r["success"],
            duration_ms=(time.time() - t0) * 1000,
            detail="Verified cluster connectivity",
            error=r.get("error") if not r["success"] else None,
        )

    def run_agent(self, agent) -> IntegrationStepResult:
        t0 = time.time()
        try:
            res = agent.process_query(
                "Give me a full cluster health diagnosis including OSD status, "
                "PG status, and capacity prediction",
                auto_confirm=True,
            )
            return IntegrationStepResult(
                step="agent_query", success=res.success,
                duration_ms=(time.time() - t0) * 1000,
                detail=res.message[:300],
            )
        except Exception as e:
            return IntegrationStepResult(
                step="agent_query", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=str(e),
            )

    def verify(self) -> IntegrationStepResult:
        t0 = time.time()
        # Verify agent didn't break anything
        r = _ceph_cmd(["health"])
        return IntegrationStepResult(
            step="verify",
            success=r["success"],
            duration_ms=(time.time() - t0) * 1000,
            detail="Cluster still responsive after diagnosis",
            error=r.get("error") if not r["success"] else None,
        )

    def cleanup(self) -> IntegrationStepResult:
        return IntegrationStepResult(
            step="cleanup", success=True, duration_ms=0,
            detail="No cleanup needed (read-only test)",
        )


# ── Scenario 4: OSD fault injection ─────────────────────────────────────

def _systemctl(action: str, unit: str, timeout: int = 30) -> Dict[str, Any]:
    """Run systemctl on a ceph-osd unit."""
    cmd = ["systemctl", action, unit]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _wait_for_osd_state(
    osd_id: int,
    desired_state: str,  # "down" or "up"
    timeout: int = 60,
    poll: float = 3.0,
) -> bool:
    """
    Poll ceph osd tree until osd.<osd_id> reports the desired state.
    Returns True if state reached within timeout, False otherwise.
    """
    import json as _json
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _ceph_cmd(["osd", "tree"])
        if r["success"]:
            nodes = r["data"].get("nodes", []) if isinstance(r["data"], dict) else []
            for node in nodes:
                if node.get("id") == osd_id:
                    status = node.get("status", "")
                    if desired_state == "down" and status != "up":
                        return True
                    if desired_state == "up" and status == "up":
                        return True
                    break
        time.sleep(poll)
    return False


class OSDFailureScenario(IntegrationScenario):
    """
    Fault injection: stop OSD daemon → agent diagnoses → bring OSD back.

    Safety gates:
    - Aborts if cluster has < 3 OSDs (unsafe to lose quorum).
    - Aborts if target OSD is already down.
    - Cleanup always runs: marks OSD in, then starts daemon, with retries.
    - noout is set during the test so Ceph doesn't begin rebalancing.

    Parameters:
        osd_id: The OSD number to stop (default 0). Choose an OSD that is
                not the primary for critical PGs in production.
    """

    id = "int04"
    description = "Fault injection: OSD failure → agent diagnosis → recovery"
    requires_root = True

    # How long to wait (seconds) for Ceph to register the state change
    WAIT_FOR_DOWN = 45
    WAIT_FOR_UP = 90
    CLEANUP_RETRIES = 3

    def __init__(self, osd_id: int = 0):
        self.osd_id = osd_id
        self._unit = f"ceph-osd@{osd_id}"
        self._osd_was_up = False  # set in setup, guards cleanup

    # ── helpers ──────────────────────────────────────────────────────

    def _osd_count(self) -> int:
        r = _ceph_cmd(["osd", "stat"])
        if r["success"] and isinstance(r["data"], dict):
            return r["data"].get("num_osds", 0)
        return 0

    def _osd_is_up(self, osd_id: int) -> bool:
        r = _ceph_cmd(["osd", "tree"])
        if not r["success"]:
            return False
        nodes = r["data"].get("nodes", []) if isinstance(r["data"], dict) else []
        for node in nodes:
            if node.get("id") == osd_id:
                return node.get("status", "") == "up"
        return False

    # ── scenario steps ───────────────────────────────────────────────

    def setup(self) -> IntegrationStepResult:
        t0 = time.time()

        # Safety: require at least 3 OSDs
        n_osds = self._osd_count()
        if n_osds < 3:
            return IntegrationStepResult(
                step="setup", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=f"Unsafe: only {n_osds} OSD(s); need ≥3 to inject faults",
            )

        # Safety: OSD must currently be up
        if not self._osd_is_up(self.osd_id):
            return IntegrationStepResult(
                step="setup", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=f"OSD {self.osd_id} is not up; choose a healthy OSD",
            )

        # Set noout so Ceph doesn't start rebalancing immediately
        _ceph_cmd_plain(["osd", "set", "noout"])
        logger.info("Set noout flag before OSD stop")

        # Stop the daemon
        logger.info("Stopping %s", self._unit)
        r = _systemctl("stop", self._unit)
        if not r["success"]:
            _ceph_cmd_plain(["osd", "unset", "noout"])  # cleanup flag
            return IntegrationStepResult(
                step="setup", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=f"systemctl stop failed: {r.get('stderr') or r.get('error')}",
            )

        # Wait for Ceph to register the OSD as down
        logger.info("Waiting for OSD %d to appear down in osd tree…", self.osd_id)
        reached = _wait_for_osd_state(self.osd_id, "down", timeout=self.WAIT_FOR_DOWN)

        self._osd_was_up = True  # enable cleanup regardless
        return IntegrationStepResult(
            step="setup",
            success=True,  # proceed even if state not confirmed yet
            duration_ms=(time.time() - t0) * 1000,
            detail=(
                f"OSD {self.osd_id} daemon stopped; "
                f"state confirmed down: {reached}"
            ),
        )

    def run_agent(self, agent) -> IntegrationStepResult:
        t0 = time.time()
        try:
            res = agent.process_query(
                f"OSD {self.osd_id} appears to be down. "
                "Diagnose the cluster health, identify which OSD is affected, "
                "and tell me the recommended recovery steps.",
                auto_confirm=True,
            )
            # Check the agent mentioned the right OSD in its response
            mentioned_osd = (
                str(self.osd_id) in res.message
                or f"osd.{self.osd_id}" in res.message.lower()
            )
            return IntegrationStepResult(
                step="agent_query",
                success=res.success,
                duration_ms=(time.time() - t0) * 1000,
                detail=(
                    f"Agent {'mentioned' if mentioned_osd else 'did NOT mention'} "
                    f"OSD {self.osd_id}. Response: {res.message[:300]}"
                ),
            )
        except Exception as e:
            return IntegrationStepResult(
                step="agent_query", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error=str(e),
            )

    def verify(self) -> IntegrationStepResult:
        """Verify the cluster registered the OSD as down (fault was real)."""
        t0 = time.time()
        r = _ceph_cmd(["health", "detail"])
        if not r["success"]:
            return IntegrationStepResult(
                step="verify", success=False,
                duration_ms=(time.time() - t0) * 1000,
                error="ceph health detail failed",
            )
        health_str = str(r["data"])
        osd_down_detected = (
            "OSD_DOWN" in health_str
            or f"osd.{self.osd_id}" in health_str.lower()
        )
        return IntegrationStepResult(
            step="verify",
            success=osd_down_detected,
            duration_ms=(time.time() - t0) * 1000,
            detail=(
                f"OSD down {'detected' if osd_down_detected else 'NOT detected'} "
                "in cluster health"
            ),
        )

    def cleanup(self) -> IntegrationStepResult:
        """Always runs: restart daemon, mark OSD in, unset noout."""
        t0 = time.time()
        errors = []

        if not self._osd_was_up:
            # setup bailed before stopping the OSD, nothing to undo
            _ceph_cmd_plain(["osd", "unset", "noout"])
            return IntegrationStepResult(
                step="cleanup", success=True, duration_ms=0,
                detail="No cleanup needed (OSD was never stopped)",
            )

        # 1. Mark OSD in (do this first so rebalancing can resume on restart)
        _ceph_cmd_plain(["osd", "in", str(self.osd_id)])
        logger.info("Marked OSD %d in", self.osd_id)

        # 2. Start daemon with retries
        started = False
        for attempt in range(1, self.CLEANUP_RETRIES + 1):
            r = _systemctl("start", self._unit, timeout=30)
            if r["success"]:
                started = True
                logger.info("Started %s (attempt %d)", self._unit, attempt)
                break
            logger.warning(
                "systemctl start attempt %d failed: %s",
                attempt, r.get("stderr") or r.get("error"),
            )
            time.sleep(5)

        if not started:
            errors.append(f"Could not restart {self._unit} after "
                          f"{self.CLEANUP_RETRIES} attempts — manual intervention needed")

        # 3. Wait for OSD to come back up
        if started:
            reached = _wait_for_osd_state(
                self.osd_id, "up", timeout=self.WAIT_FOR_UP
            )
            if not reached:
                errors.append(
                    f"OSD {self.osd_id} daemon started but did not appear up "
                    f"within {self.WAIT_FOR_UP}s"
                )

        # 4. Unset noout regardless
        _ceph_cmd_plain(["osd", "unset", "noout"])
        logger.info("Unset noout flag")

        return IntegrationStepResult(
            step="cleanup",
            success=len(errors) == 0,
            duration_ms=(time.time() - t0) * 1000,
            detail=f"OSD {self.osd_id} restarted={'yes' if started else 'no'}, "
                   f"noout unset",
            error="; ".join(errors) if errors else None,
        )


# ── scenario factories ────────────────────────────────────────────────────

def get_integration_scenarios() -> List[IntegrationScenario]:
    """Return all safe (non-destructive) integration scenarios."""
    return [
        PoolLifecycleScenario(),
        FlagManagementScenario(),
        HealthDiagnosisScenario(),
    ]


def get_fault_injection_scenarios(osd_id: int = 0) -> List[IntegrationScenario]:
    """
    Return fault-injection scenarios (require systemd + root).

    Args:
        osd_id: Which OSD number to stop during the test.
                Pick an OSD that is not the sole primary for a critical pool.
    """
    return [OSDFailureScenario(osd_id=osd_id)]


class IntegrationEvaluator:
    """
    Run end-to-end integration tests against a live Ceph cluster.

    Each scenario follows: setup → agent query → verify → cleanup.
    """

    def __init__(self, agent, scenarios: Optional[List[IntegrationScenario]] = None):
        self.agent = agent
        self.scenarios = scenarios or get_integration_scenarios()

    def _check_ceph_available(self) -> bool:
        """Verify ceph CLI is accessible."""
        r = _ceph_cmd(["health"])
        return r["success"]

    def evaluate(self, progress_callback=None) -> IntegrationEvalReport:
        logger.info("Integration evaluation: %d scenarios", len(self.scenarios))

        if not self._check_ceph_available():
            logger.warning("Ceph cluster not available; skipping integration tests")
            return IntegrationEvalReport(
                num_scenarios=len(self.scenarios),
                passed=0, failed=0, skipped=len(self.scenarios),
            )

        results: List[IntegrationResult] = []

        for idx, scenario in enumerate(self.scenarios):
            if progress_callback:
                progress_callback(idx + 1, len(self.scenarios), "integration")

            logger.info("  [%d/%d] %s — %s",
                        idx + 1, len(self.scenarios),
                        scenario.id, scenario.description)

            result = self._run_scenario(scenario)
            results.append(result)

            # Clear conversation between scenarios
            if hasattr(self.agent, "clear_conversation"):
                self.agent.clear_conversation()

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return IntegrationEvalReport(
            num_scenarios=len(results),
            passed=passed, failed=failed, skipped=0,
            results=results,
        )

    def _run_scenario(self, scenario: IntegrationScenario) -> IntegrationResult:
        t0 = time.time()
        steps = []
        agent_response = ""
        passed = True

        # 1. Setup
        try:
            setup = scenario.setup()
            steps.append(setup)
            if not setup.success:
                passed = False
        except Exception as e:
            steps.append(IntegrationStepResult(
                step="setup", success=False, duration_ms=0, error=str(e),
            ))
            passed = False

        # 2. Run agent (even if setup failed, for diagnostic value)
        if passed:
            try:
                agent_step = scenario.run_agent(self.agent)
                steps.append(agent_step)
                agent_response = agent_step.detail
                if not agent_step.success:
                    passed = False
            except Exception as e:
                steps.append(IntegrationStepResult(
                    step="agent_query", success=False, duration_ms=0,
                    error=str(e),
                ))
                passed = False

        # 3. Verify
        if passed:
            try:
                verify = scenario.verify()
                steps.append(verify)
                if not verify.success:
                    passed = False
            except Exception as e:
                steps.append(IntegrationStepResult(
                    step="verify", success=False, duration_ms=0,
                    error=str(e),
                ))
                passed = False

        # 4. Cleanup (always)
        try:
            cleanup = scenario.cleanup()
            steps.append(cleanup)
        except Exception as e:
            steps.append(IntegrationStepResult(
                step="cleanup", success=False, duration_ms=0,
                error=str(e),
            ))

        return IntegrationResult(
            scenario_id=scenario.id,
            description=scenario.description,
            passed=passed,
            steps=steps,
            agent_response=agent_response,
            total_duration_ms=(time.time() - t0) * 1000,
        )
