"""
Anomaly Detection for Ceph Cluster Management.

Provides rule-based and LLM-assisted anomaly detection that
analyzes cluster state and proactively identifies issues
before they become critical.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class AnomalySeverity(str, Enum):
    """Severity levels for detected anomalies."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnomalyCategory(str, Enum):
    """Categories of cluster anomalies."""
    HEALTH = "health"
    CAPACITY = "capacity"
    PERFORMANCE = "performance"
    OSD = "osd"
    PG = "pg"
    BALANCE = "balance"
    CONFIGURATION = "configuration"


@dataclass
class Anomaly:
    """A detected cluster anomaly."""
    anomaly_id: str
    category: AnomalyCategory
    severity: AnomalySeverity
    title: str
    description: str
    affected_components: List[str] = field(default_factory=list)
    suggested_action: str = ""
    suggested_runbook: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    detected_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "affected_components": self.affected_components,
            "suggested_action": self.suggested_action,
            "suggested_runbook": self.suggested_runbook,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class AnomalyReport:
    """Report from anomaly detection scan."""
    scan_time: datetime = field(default_factory=datetime.now)
    anomalies: List[Anomaly] = field(default_factory=list)
    cluster_score: float = 100.0  # 0-100, where 100 is perfectly healthy
    scan_duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_time": self.scan_time.isoformat(),
            "anomalies": [a.to_dict() for a in self.anomalies],
            "cluster_score": self.cluster_score,
            "scan_duration_ms": self.scan_duration_ms,
            "summary": self.get_summary(),
        }
    
    def get_summary(self) -> Dict[str, int]:
        counts = {"info": 0, "warning": 0, "critical": 0}
        for a in self.anomalies:
            counts[a.severity.value] = counts.get(a.severity.value, 0) + 1
        return counts


class AnomalyDetector:
    """
    Rule-based anomaly detector for Ceph clusters.
    
    Analyzes cluster state data and applies a set of rules
    to detect potential issues. Each rule checks a specific
    condition and generates an Anomaly if triggered.
    
    The agent uses this to proactively identify issues and
    suggest remediation actions.
    """
    
    # Configurable thresholds
    DEFAULT_THRESHOLDS = {
        "osd_utilization_warning": 75.0,   # % 
        "osd_utilization_critical": 85.0,   # %
        "cluster_utilization_warning": 70.0, # %
        "cluster_utilization_critical": 80.0, # %
        "osd_variance_threshold": 20.0,      # % difference between min/max OSD utilization
        "pg_degraded_warning": 1,             # any degraded PGs
        "pg_undersized_warning": 1,           # any undersized PGs
        "min_osd_count": 3,                   # minimum OSDs for production
        "days_until_full_warning": 90,        # days
        "days_until_full_critical": 30,       # days
    }
    
    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize anomaly detector.
        
        Args:
            thresholds: Custom thresholds (merged with defaults)
        """
        self.thresholds = {**self.DEFAULT_THRESHOLDS}
        if thresholds:
            self.thresholds.update(thresholds)
        
        self._anomaly_counter = 0
        logger.info("Initialized AnomalyDetector")
    
    def _next_id(self) -> str:
        self._anomaly_counter += 1
        return f"anomaly_{self._anomaly_counter}"
    
    def analyze(self, cluster_state: Dict[str, Any]) -> AnomalyReport:
        """
        Analyze cluster state and detect anomalies.
        
        Args:
            cluster_state: Dictionary with cluster state data from various tools:
                - health: cluster health data
                - osds: list of OSD status dicts
                - pgs: PG status data
                - capacity: capacity prediction data
                - performance: performance statistics
                
        Returns:
            AnomalyReport with detected anomalies
        """
        start_time = time.time()
        report = AnomalyReport()
        
        # Run all detection rules
        self._check_health(cluster_state.get("health", {}), report)
        self._check_osds(cluster_state.get("osds", []), report)
        self._check_pgs(cluster_state.get("pgs", {}), report)
        self._check_capacity(cluster_state.get("capacity", {}), report)
        self._check_balance(cluster_state.get("osds", []), report)
        self._check_performance(cluster_state.get("performance", {}), report)
        
        # Calculate cluster health score
        report.cluster_score = self._calculate_score(report.anomalies)
        report.scan_duration_ms = (time.time() - start_time) * 1000
        
        logger.info(f"Anomaly scan complete: {len(report.anomalies)} anomalies, "
                     f"score={report.cluster_score:.0f}/100")
        
        return report
    
    def _check_health(self, health_data: Dict, report: AnomalyReport):
        """Check cluster health status."""
        status = health_data.get("status", "UNKNOWN")
        
        if status == "HEALTH_ERR":
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.HEALTH,
                severity=AnomalySeverity.CRITICAL,
                title="Cluster Health Error",
                description=f"Cluster is in HEALTH_ERR state: {health_data.get('summary', '')}",
                suggested_action="Run cluster diagnosis and address critical issues immediately",
                suggested_runbook="fix_degraded_pgs",
            ))
        elif status == "HEALTH_WARN":
            checks = health_data.get("checks", {})
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.HEALTH,
                severity=AnomalySeverity.WARNING,
                title="Cluster Health Warning",
                description=f"Cluster has {len(checks)} health warning(s)",
                affected_components=list(checks.keys()),
                suggested_action="Review health warnings and address non-critical issues",
            ))
    
    def _check_osds(self, osds: List[Dict], report: AnomalyReport):
        """Check OSD status and utilization."""
        if not osds:
            return
        
        # Check for down OSDs
        down_osds = [o for o in osds if o.get("status") != "up"]
        if down_osds:
            osd_ids = [o.get("osd_id", "?") for o in down_osds]
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.OSD,
                severity=AnomalySeverity.CRITICAL,
                title=f"{len(down_osds)} OSD(s) Down",
                description=f"OSDs {osd_ids} are not running",
                affected_components=[f"osd.{oid}" for oid in osd_ids],
                suggested_action="Investigate and restart down OSDs",
                suggested_runbook="recover_down_osd",
            ))
        
        # Check OSD count
        total_osds = len(osds)
        if total_osds < self.thresholds["min_osd_count"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.OSD,
                severity=AnomalySeverity.WARNING,
                title="Low OSD Count",
                description=f"Only {total_osds} OSDs, recommended minimum is {self.thresholds['min_osd_count']}",
                metric_value=total_osds,
                threshold=self.thresholds["min_osd_count"],
                suggested_action="Add more OSDs for better reliability",
            ))
        
        # Check individual OSD utilization
        for osd in osds:
            utilization = osd.get("utilization", 0)
            osd_id = osd.get("osd_id", "?")
            
            if utilization > self.thresholds["osd_utilization_critical"]:
                report.anomalies.append(Anomaly(
                    anomaly_id=self._next_id(),
                    category=AnomalyCategory.OSD,
                    severity=AnomalySeverity.CRITICAL,
                    title=f"OSD.{osd_id} Critical Utilization",
                    description=f"OSD.{osd_id} is at {utilization:.1f}% capacity",
                    affected_components=[f"osd.{osd_id}"],
                    metric_value=utilization,
                    threshold=self.thresholds["osd_utilization_critical"],
                    suggested_action=f"Reweight OSD.{osd_id} or add storage capacity",
                    suggested_runbook="rebalance_cluster",
                ))
            elif utilization > self.thresholds["osd_utilization_warning"]:
                report.anomalies.append(Anomaly(
                    anomaly_id=self._next_id(),
                    category=AnomalyCategory.OSD,
                    severity=AnomalySeverity.WARNING,
                    title=f"OSD.{osd_id} High Utilization",
                    description=f"OSD.{osd_id} is at {utilization:.1f}% capacity",
                    affected_components=[f"osd.{osd_id}"],
                    metric_value=utilization,
                    threshold=self.thresholds["osd_utilization_warning"],
                    suggested_action=f"Monitor OSD.{osd_id} and consider rebalancing",
                ))
    
    def _check_pgs(self, pg_data: Dict, report: AnomalyReport):
        """Check placement group status."""
        degraded = pg_data.get("degraded", 0)
        undersized = pg_data.get("undersized", 0)
        stale = pg_data.get("stale", 0)
        recovering = pg_data.get("recovering", 0)
        
        if degraded > self.thresholds["pg_degraded_warning"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.PG,
                severity=AnomalySeverity.CRITICAL if degraded > 10 else AnomalySeverity.WARNING,
                title=f"{degraded} Degraded Placement Groups",
                description=f"{degraded} PGs have fewer copies than configured replication level",
                metric_value=degraded,
                suggested_action="Check OSD status and wait for recovery, or investigate stuck PGs",
                suggested_runbook="fix_degraded_pgs",
            ))
        
        if undersized > self.thresholds["pg_undersized_warning"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.PG,
                severity=AnomalySeverity.WARNING,
                title=f"{undersized} Undersized Placement Groups",
                description=f"{undersized} PGs have fewer OSDs than desired replication level",
                metric_value=undersized,
                suggested_action="Ensure sufficient OSDs are available",
            ))
        
        if stale > 0:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.PG,
                severity=AnomalySeverity.CRITICAL,
                title=f"{stale} Stale Placement Groups",
                description=f"{stale} PGs have not been reported by their primary OSD",
                metric_value=stale,
                suggested_action="Check if OSDs are running and reachable",
            ))
        
        if recovering > 50:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.PG,
                severity=AnomalySeverity.INFO,
                title=f"Active Recovery: {recovering} PGs",
                description=f"{recovering} PGs are actively recovering data",
                metric_value=recovering,
                suggested_action="Monitor recovery progress; performance may be impacted",
            ))
    
    def _check_capacity(self, capacity_data: Dict, report: AnomalyReport):
        """Check capacity thresholds."""
        if not capacity_data or "error" in capacity_data:
            return
        
        current = capacity_data.get("current", {})
        projection = capacity_data.get("projection", {})
        
        utilization = current.get("utilization_percent", 0)
        
        if utilization > self.thresholds["cluster_utilization_critical"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.CAPACITY,
                severity=AnomalySeverity.CRITICAL,
                title="Critical Cluster Capacity",
                description=f"Cluster is at {utilization:.1f}% capacity",
                metric_value=utilization,
                threshold=self.thresholds["cluster_utilization_critical"],
                suggested_action="Add storage capacity immediately or delete unnecessary data",
                suggested_runbook="capacity_expansion_prep",
            ))
        elif utilization > self.thresholds["cluster_utilization_warning"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.CAPACITY,
                severity=AnomalySeverity.WARNING,
                title="High Cluster Capacity",
                description=f"Cluster is at {utilization:.1f}% capacity",
                metric_value=utilization,
                threshold=self.thresholds["cluster_utilization_warning"],
                suggested_action="Plan storage expansion",
                suggested_runbook="capacity_expansion_prep",
            ))
        
        # Check days until full
        days_until_full = projection.get("days_until_full")
        if days_until_full is not None:
            if days_until_full < self.thresholds["days_until_full_critical"]:
                report.anomalies.append(Anomaly(
                    anomaly_id=self._next_id(),
                    category=AnomalyCategory.CAPACITY,
                    severity=AnomalySeverity.CRITICAL,
                    title=f"Cluster Full in {days_until_full} Days",
                    description=f"At current growth rate, cluster will be full in {days_until_full} days",
                    metric_value=days_until_full,
                    threshold=self.thresholds["days_until_full_critical"],
                    suggested_action="Urgent: Add storage capacity or reduce data growth",
                    suggested_runbook="capacity_expansion_prep",
                ))
            elif days_until_full < self.thresholds["days_until_full_warning"]:
                report.anomalies.append(Anomaly(
                    anomaly_id=self._next_id(),
                    category=AnomalyCategory.CAPACITY,
                    severity=AnomalySeverity.WARNING,
                    title=f"Cluster Full in {days_until_full} Days",
                    description=f"At current growth rate, cluster will be full in {days_until_full} days",
                    metric_value=days_until_full,
                    threshold=self.thresholds["days_until_full_warning"],
                    suggested_action="Plan storage expansion within the next month",
                    suggested_runbook="capacity_expansion_prep",
                ))
    
    def _check_balance(self, osds: List[Dict], report: AnomalyReport):
        """Check data balance across OSDs."""
        if not osds:
            return
        
        utilizations = [o.get("utilization", 0) for o in osds if o.get("status") == "up"]
        if len(utilizations) < 2:
            return
        
        min_util = min(utilizations)
        max_util = max(utilizations)
        variance = max_util - min_util
        
        if variance > self.thresholds["osd_variance_threshold"]:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.BALANCE,
                severity=AnomalySeverity.WARNING,
                title="Unbalanced OSD Utilization",
                description=(
                    f"OSD utilization varies by {variance:.1f}% "
                    f"(min: {min_util:.1f}%, max: {max_util:.1f}%)"
                ),
                metric_value=variance,
                threshold=self.thresholds["osd_variance_threshold"],
                suggested_action="Consider rebalancing data with CRUSH weight adjustments",
                suggested_runbook="rebalance_cluster",
            ))
    
    def _check_performance(self, perf_data: Dict, report: AnomalyReport):
        """Check performance indicators."""
        if not perf_data or "error" in perf_data:
            return
        
        recovery = perf_data.get("recovery", {})
        recovering_objs = recovery.get("recovering_objects_per_sec", 0)
        
        if recovering_objs > 0:
            report.anomalies.append(Anomaly(
                anomaly_id=self._next_id(),
                category=AnomalyCategory.PERFORMANCE,
                severity=AnomalySeverity.INFO,
                title="Active Data Recovery",
                description=f"Recovering {recovering_objs:.0f} objects/sec",
                metric_value=recovering_objs,
                suggested_action="Performance may be impacted during recovery",
            ))
    
    def _calculate_score(self, anomalies: List[Anomaly]) -> float:
        """Calculate an overall cluster health score (0-100)."""
        score = 100.0
        
        for anomaly in anomalies:
            if anomaly.severity == AnomalySeverity.CRITICAL:
                score -= 25.0
            elif anomaly.severity == AnomalySeverity.WARNING:
                score -= 10.0
            elif anomaly.severity == AnomalySeverity.INFO:
                score -= 2.0
        
        return max(0.0, score)
    
    def format_report(self, report: AnomalyReport) -> str:
        """Format anomaly report for display."""
        # Score emoji
        if report.cluster_score >= 90:
            score_icon = "🟢"
        elif report.cluster_score >= 70:
            score_icon = "🟡"
        elif report.cluster_score >= 50:
            score_icon = "🟠"
        else:
            score_icon = "🔴"
        
        lines = [
            f"{score_icon} **Cluster Health Score: {report.cluster_score:.0f}/100**",
            "",
        ]
        
        if not report.anomalies:
            lines.append("✅ No anomalies detected. Cluster is healthy!")
            return "\n".join(lines)
        
        summary = report.get_summary()
        lines.append(f"Detected: {summary.get('critical', 0)} critical, "
                     f"{summary.get('warning', 0)} warnings, "
                     f"{summary.get('info', 0)} info")
        lines.append("")
        
        # Group by severity
        for severity in [AnomalySeverity.CRITICAL, AnomalySeverity.WARNING, AnomalySeverity.INFO]:
            severity_anomalies = [a for a in report.anomalies if a.severity == severity]
            if not severity_anomalies:
                continue
            
            icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}[severity.value]
            lines.append(f"**{severity.value.upper()}:**")
            
            for a in severity_anomalies:
                lines.append(f"  {icon} **{a.title}**")
                lines.append(f"     {a.description}")
                if a.suggested_action:
                    lines.append(f"     → {a.suggested_action}")
                if a.suggested_runbook:
                    lines.append(f"     📋 Runbook: {a.suggested_runbook}")
            lines.append("")
        
        return "\n".join(lines)
