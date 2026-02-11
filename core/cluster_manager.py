"""
Ceph Cluster Management Module.

Provides both read-only monitoring and write/management operations
for cluster administration, health monitoring, troubleshooting,
and automated remediation.
"""

import logging
import subprocess
import json
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ClusterHealth:
    """Represents cluster health status."""
    status: str  # HEALTH_OK, HEALTH_WARN, HEALTH_ERR
    checks: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    details: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OSDStatus:
    """Represents OSD status."""
    osd_id: int
    host: str
    status: str  # up, down
    in_cluster: bool
    weight: float
    utilization: float = 0.0
    pgs: int = 0
    
    
@dataclass 
class PGStatus:
    """Represents PG status summary."""
    total: int = 0
    active_clean: int = 0
    degraded: int = 0
    recovering: int = 0
    undersized: int = 0
    stale: int = 0
    other_states: Dict[str, int] = field(default_factory=dict)


class CephClusterManager:
    """
    Manager for Ceph cluster operations.
    
    Provides high-level interfaces for:
    - Cluster health monitoring
    - OSD management
    - PG analysis
    - Performance insights
    - Capacity planning
    """
    
    def __init__(self, ceph_config: str = "/etc/ceph/ceph.conf"):
        """
        Initialize cluster manager.
        
        Args:
            ceph_config: Path to ceph.conf
        """
        self.ceph_config = ceph_config
        self._cache = {}
        self._cache_timeout = 30  # seconds
        logger.info("Initialized CephClusterManager")
    
    def _run_ceph_command(self, cmd: List[str], use_json: bool = True) -> Tuple[bool, Any]:
        """
        Execute a ceph command.
        
        Args:
            cmd: Command parts (e.g., ['health', 'detail'])
            use_json: Whether to request JSON output
            
        Returns:
            Tuple of (success, result_or_error)
        """
        full_cmd = ["sudo", "ceph", "-c", self.ceph_config]
        if use_json:
            full_cmd.extend(["-f", "json"])
        full_cmd.extend(cmd)
        
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, result.stderr.strip()
            
            if use_json:
                return True, json.loads(result.stdout)
            return True, result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except json.JSONDecodeError as e:
            return False, f"Failed to parse JSON: {e}"
        except Exception as e:
            return False, str(e)
    
    def get_cluster_health(self, detail: bool = True) -> ClusterHealth:
        """
        Get comprehensive cluster health status.
        
        Args:
            detail: Include detailed health checks
            
        Returns:
            ClusterHealth object
        """
        cmd = ["health", "detail"] if detail else ["health"]
        success, result = self._run_ceph_command(cmd)
        
        if not success:
            logger.error(f"Failed to get health: {result}")
            return ClusterHealth(
                status="UNKNOWN",
                summary=f"Failed to get health: {result}"
            )
        
        status = result.get("status", "UNKNOWN")
        checks = result.get("checks", {})
        
        # Build summary
        details = []
        for check_name, check_info in checks.items():
            severity = check_info.get("severity", "UNKNOWN")
            summary = check_info.get("summary", {}).get("message", "")
            details.append(f"[{severity}] {check_name}: {summary}")
        
        summary = f"Cluster is {status}"
        if checks:
            summary += f" with {len(checks)} health check(s)"
        
        return ClusterHealth(
            status=status,
            checks=checks,
            summary=summary,
            details=details
        )
    
    def get_cluster_status(self) -> Dict[str, Any]:
        """
        Get overall cluster status including health, OSDs, PGs, etc.
        
        Returns:
            Dictionary with comprehensive cluster status
        """
        success, result = self._run_ceph_command(["status"])
        
        if not success:
            return {"error": result}
        
        return result
    
    def get_osd_status(self) -> List[OSDStatus]:
        """
        Get status of all OSDs.
        
        Returns:
            List of OSDStatus objects
        """
        # Get OSD tree
        success, tree = self._run_ceph_command(["osd", "tree"])
        if not success:
            logger.error(f"Failed to get OSD tree: {tree}")
            return []
        
        # Get OSD df for utilization
        success, df = self._run_ceph_command(["osd", "df"])
        utilization = {}
        if success:
            for node in df.get("nodes", []):
                utilization[node.get("id")] = node.get("utilization", 0)
        
        osds = []
        nodes = tree.get("nodes", [])
        
        # Build host mapping
        host_map = {}
        for node in nodes:
            if node.get("type") == "host":
                for child_id in node.get("children", []):
                    host_map[child_id] = node.get("name", "unknown")
        
        # Process OSDs
        for node in nodes:
            if node.get("type") == "osd":
                osd_id = node.get("id", -1)
                osds.append(OSDStatus(
                    osd_id=osd_id,
                    host=host_map.get(osd_id, "unknown"),
                    status=node.get("status", "unknown"),
                    in_cluster=node.get("reweight", 0) > 0,
                    weight=node.get("crush_weight", 0),
                    utilization=utilization.get(osd_id, 0),
                    pgs=node.get("pgs", 0)
                ))
        
        return osds
    
    def get_osd_df(self) -> Dict[str, Any]:
        """
        Get OSD disk usage.
        
        Returns:
            Dictionary with OSD disk usage information
        """
        success, result = self._run_ceph_command(["osd", "df", "tree"])
        if not success:
            return {"error": result}
        return result
    
    def get_pg_status(self) -> PGStatus:
        """
        Get PG status summary.
        
        Returns:
            PGStatus object
        """
        success, result = self._run_ceph_command(["pg", "stat"])
        
        if not success:
            logger.error(f"Failed to get PG status: {result}")
            return PGStatus()
        
        pg_status = PGStatus()
        
        # Parse pg summary
        pgs_by_state = result.get("pg_summary", {}).get("num_pg_by_state", [])
        
        for state_info in pgs_by_state:
            state = state_info.get("name", "")
            count = state_info.get("num", 0)
            pg_status.total += count
            
            if "active+clean" in state:
                pg_status.active_clean += count
            elif "degraded" in state:
                pg_status.degraded += count
            elif "recovering" in state:
                pg_status.recovering += count
            elif "undersized" in state:
                pg_status.undersized += count
            elif "stale" in state:
                pg_status.stale += count
            else:
                pg_status.other_states[state] = count
        
        return pg_status
    
    def get_pool_stats(self) -> List[Dict[str, Any]]:
        """
        Get statistics for all pools.
        
        Returns:
            List of pool statistics
        """
        success, result = self._run_ceph_command(["df", "detail"])
        if not success:
            return []
        
        pools = []
        for pool in result.get("pools", []):
            pools.append({
                "name": pool.get("name"),
                "id": pool.get("id"),
                "used_bytes": pool.get("stats", {}).get("stored", 0),
                "objects": pool.get("stats", {}).get("objects", 0),
                "percent_used": pool.get("stats", {}).get("percent_used", 0),
                "max_avail": pool.get("stats", {}).get("max_avail", 0)
            })
        
        return pools
    
    def get_slow_requests(self) -> List[Dict[str, Any]]:
        """
        Get information about slow requests.
        
        Returns:
            List of slow request information
        """
        success, result = self._run_ceph_command(["daemon", "osd.0", "dump_blocked_ops"], use_json=False)
        # This might not work on all setups, provide fallback
        if not success:
            # Try to get from health detail
            health = self.get_cluster_health(detail=True)
            slow_requests = []
            for check_name, check_info in health.checks.items():
                if "slow" in check_name.lower() or "blocked" in check_name.lower():
                    slow_requests.append({
                        "check": check_name,
                        "message": check_info.get("summary", {}).get("message", ""),
                        "count": check_info.get("summary", {}).get("count", 0)
                    })
            return slow_requests
        
        return []
    
    def predict_capacity(self, days: int = 30) -> Dict[str, Any]:
        """
        Predict storage capacity based on current usage trends.
        
        Args:
            days: Number of days to project
            
        Returns:
            Capacity prediction information
        """
        success, result = self._run_ceph_command(["df"])
        
        if not success:
            return {"error": result}
        
        stats = result.get("stats", {})
        total_bytes = stats.get("total_bytes", 0)
        used_bytes = stats.get("total_used_raw_bytes", 0)
        avail_bytes = stats.get("total_avail_bytes", 0)
        
        # Calculate utilization
        utilization = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0
        
        # Simple linear projection (in production, use historical data)
        # Assuming 2% growth per month as baseline
        daily_growth_rate = 0.02 / 30  # 2% per month
        projected_used = used_bytes * (1 + daily_growth_rate * days)
        
        days_until_80 = None
        days_until_full = None
        
        if daily_growth_rate > 0:
            # Days until 80% capacity
            target_80 = total_bytes * 0.8
            if used_bytes < target_80:
                days_until_80 = int((target_80 - used_bytes) / (used_bytes * daily_growth_rate))
            
            # Days until full
            days_until_full = int((total_bytes - used_bytes) / (used_bytes * daily_growth_rate))
        
        return {
            "current": {
                "total_gb": round(total_bytes / (1024**3), 2),
                "used_gb": round(used_bytes / (1024**3), 2),
                "available_gb": round(avail_bytes / (1024**3), 2),
                "utilization_percent": round(utilization, 2)
            },
            "projection": {
                "days": days,
                "projected_used_gb": round(projected_used / (1024**3), 2),
                "projected_utilization": round(projected_used / total_bytes * 100, 2),
                "days_until_80_percent": days_until_80,
                "days_until_full": days_until_full,
                "growth_rate_monthly": "2%"  # Placeholder
            },
            "recommendation": self._capacity_recommendation(utilization, days_until_80)
        }
    
    def _capacity_recommendation(self, utilization: float, days_until_80: Optional[int]) -> str:
        """Generate capacity recommendation based on metrics."""
        if utilization > 85:
            return "CRITICAL: Cluster is above 85% capacity. Add storage immediately."
        elif utilization > 80:
            return "WARNING: Cluster is above 80% capacity. Plan storage expansion."
        elif days_until_80 and days_until_80 < 30:
            return f"ATTENTION: Projected to reach 80% capacity in {days_until_80} days."
        elif utilization > 60:
            return "OK: Cluster has adequate capacity. Monitor growth trends."
        else:
            return "HEALTHY: Cluster has ample capacity."
    
    def diagnose_cluster(self) -> Dict[str, Any]:
        """
        Perform comprehensive cluster diagnosis.
        
        Returns:
            Diagnostic report
        """
        diagnosis = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "OK",
            "issues": [],
            "warnings": [],
            "recommendations": []
        }
        
        # Check health
        health = self.get_cluster_health()
        if health.status != "HEALTH_OK":
            diagnosis["overall_status"] = health.status
            for detail in health.details:
                if "HEALTH_ERR" in detail:
                    diagnosis["issues"].append(detail)
                else:
                    diagnosis["warnings"].append(detail)
        
        # Check OSDs
        osds = self.get_osd_status()
        down_osds = [o for o in osds if o.status != "up"]
        if down_osds:
            diagnosis["issues"].append(f"{len(down_osds)} OSD(s) are down: {[o.osd_id for o in down_osds]}")
            diagnosis["recommendations"].append("Investigate down OSDs and bring them back online")
        
        # Check OSD utilization
        high_util_osds = [o for o in osds if o.utilization > 85]
        if high_util_osds:
            diagnosis["warnings"].append(f"{len(high_util_osds)} OSD(s) have high utilization (>85%)")
            diagnosis["recommendations"].append("Consider rebalancing or adding storage")
        
        # Check PGs
        pg_status = self.get_pg_status()
        if pg_status.degraded > 0:
            diagnosis["issues"].append(f"{pg_status.degraded} PGs are degraded")
        if pg_status.undersized > 0:
            diagnosis["warnings"].append(f"{pg_status.undersized} PGs are undersized")
        if pg_status.recovering > 0:
            diagnosis["warnings"].append(f"{pg_status.recovering} PGs are recovering")
        
        # Check capacity
        capacity = self.predict_capacity()
        if "error" not in capacity:
            util = capacity["current"]["utilization_percent"]
            if util > 80:
                diagnosis["issues"].append(f"Cluster utilization is at {util}%")
                diagnosis["recommendations"].append(capacity["recommendation"])
        
        # Set overall status
        if diagnosis["issues"]:
            diagnosis["overall_status"] = "CRITICAL" if len(diagnosis["issues"]) > 2 else "WARNING"
        
        return diagnosis
    
    def explain_pg_state(self, pg_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Explain PG states and any issues.
        
        Args:
            pg_id: Optional specific PG to explain
            
        Returns:
            Explanation of PG states
        """
        if pg_id:
            success, result = self._run_ceph_command(["pg", pg_id, "query"])
            if success:
                return {
                    "pg_id": pg_id,
                    "state": result.get("state", "unknown"),
                    "up": result.get("up", []),
                    "acting": result.get("acting", []),
                    "info": result.get("info", {})
                }
            return {"error": result}
        
        # Get summary of PG states
        pg_status = self.get_pg_status()
        
        explanations = {
            "active+clean": {
                "count": pg_status.active_clean,
                "meaning": "PG is healthy, data is available and replicated correctly"
            },
            "degraded": {
                "count": pg_status.degraded,
                "meaning": "PG has fewer copies than configured, needs recovery"
            },
            "recovering": {
                "count": pg_status.recovering,
                "meaning": "PG is actively recovering/replicating data"
            },
            "undersized": {
                "count": pg_status.undersized,
                "meaning": "PG has fewer OSDs than desired replication level"
            },
            "stale": {
                "count": pg_status.stale,
                "meaning": "PG status is unknown, OSDs haven't reported"
            }
        }
        
        for state, count in pg_status.other_states.items():
            explanations[state] = {
                "count": count,
                "meaning": "Custom state - check Ceph documentation"
            }
        
        return {
            "total_pgs": pg_status.total,
            "healthy_pgs": pg_status.active_clean,
            "problematic_pgs": pg_status.total - pg_status.active_clean,
            "states": explanations
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get cluster performance statistics.
        
        Returns:
            Performance metrics
        """
        success, result = self._run_ceph_command(["status"])
        
        if not success:
            return {"error": result}
        
        pgmap = result.get("pgmap", {})
        
        return {
            "io": {
                "read_bytes_sec": pgmap.get("read_bytes_sec", 0),
                "write_bytes_sec": pgmap.get("write_bytes_sec", 0),
                "read_op_per_sec": pgmap.get("read_op_per_sec", 0),
                "write_op_per_sec": pgmap.get("write_op_per_sec", 0)
            },
            "recovery": {
                "recovering_objects_per_sec": pgmap.get("recovering_objects_per_sec", 0),
                "recovering_bytes_per_sec": pgmap.get("recovering_bytes_per_sec", 0)
            },
            "objects": {
                "total": pgmap.get("num_objects", 0)
            }
        }
    
    def format_health_report(self) -> str:
        """
        Generate a human-readable health report.
        
        Returns:
            Formatted health report string
        """
        health = self.get_cluster_health()
        osds = self.get_osd_status()
        pg_status = self.get_pg_status()
        capacity = self.predict_capacity()
        
        up_osds = len([o for o in osds if o.status == "up"])
        total_osds = len(osds)
        
        report = []
        report.append(f"=== Ceph Cluster Health Report ===")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        report.append(f"Overall Status: {health.status}")
        report.append("")
        report.append(f"OSDs: {up_osds}/{total_osds} up")
        report.append(f"PGs: {pg_status.active_clean}/{pg_status.total} active+clean")
        
        if pg_status.degraded:
            report.append(f"  - {pg_status.degraded} degraded")
        if pg_status.recovering:
            report.append(f"  - {pg_status.recovering} recovering")
        
        report.append("")
        if "error" not in capacity:
            report.append(f"Capacity: {capacity['current']['utilization_percent']}% used")
            report.append(f"  - Used: {capacity['current']['used_gb']} GB")
            report.append(f"  - Available: {capacity['current']['available_gb']} GB")
            report.append(f"  - {capacity['recommendation']}")
        
        if health.details:
            report.append("")
            report.append("Health Checks:")
            for detail in health.details[:5]:  # Limit to 5
                report.append(f"  • {detail}")
        
        return "\n".join(report)

    # ============ Cluster Management Actions (Write Operations) ============
    
    def set_cluster_flag(self, flag: str) -> Dict[str, Any]:
        """
        Set a cluster-wide flag.
        
        Args:
            flag: Flag name (noout, noin, norebalance, nobackfill, 
                  norecover, noscrub, nodeep-scrub, pause)
                  
        Returns:
            Result dict
        """
        valid_flags = [
            "noout", "noin", "norebalance", "nobackfill",
            "norecover", "noscrub", "nodeep-scrub", "pause",
            "noup", "nodown"
        ]
        
        if flag not in valid_flags:
            return {"error": f"Invalid flag: {flag}. Valid flags: {valid_flags}"}
        
        success, result = self._run_ceph_command(["osd", "set", flag], use_json=False)
        
        if success:
            logger.info(f"Set cluster flag: {flag}")
            return {"success": True, "flag": flag, "message": f"Flag '{flag}' set successfully"}
        return {"error": result}
    
    def unset_cluster_flag(self, flag: str) -> Dict[str, Any]:
        """
        Unset a cluster-wide flag.
        
        Args:
            flag: Flag name to unset
            
        Returns:
            Result dict
        """
        valid_flags = [
            "noout", "noin", "norebalance", "nobackfill",
            "norecover", "noscrub", "nodeep-scrub", "pause",
            "noup", "nodown"
        ]
        
        if flag not in valid_flags:
            return {"error": f"Invalid flag: {flag}. Valid flags: {valid_flags}"}
        
        success, result = self._run_ceph_command(["osd", "unset", flag], use_json=False)
        
        if success:
            logger.info(f"Unset cluster flag: {flag}")
            return {"success": True, "flag": flag, "message": f"Flag '{flag}' unset successfully"}
        return {"error": result}
    
    def set_osd_out(self, osd_id: int) -> Dict[str, Any]:
        """
        Mark an OSD as 'out' of the cluster.
        
        Args:
            osd_id: OSD ID to mark out
            
        Returns:
            Result dict
        """
        success, result = self._run_ceph_command(
            ["osd", "out", str(osd_id)], use_json=False
        )
        
        if success:
            logger.info(f"Marked OSD.{osd_id} as out")
            return {"success": True, "osd_id": osd_id, "message": f"OSD.{osd_id} marked out"}
        return {"error": result}
    
    def set_osd_in(self, osd_id: int) -> Dict[str, Any]:
        """
        Mark an OSD as 'in' the cluster.
        
        Args:
            osd_id: OSD ID to mark in
            
        Returns:
            Result dict
        """
        success, result = self._run_ceph_command(
            ["osd", "in", str(osd_id)], use_json=False
        )
        
        if success:
            logger.info(f"Marked OSD.{osd_id} as in")
            return {"success": True, "osd_id": osd_id, "message": f"OSD.{osd_id} marked in"}
        return {"error": result}
    
    def reweight_osd(self, osd_id: int, weight: float) -> Dict[str, Any]:
        """
        Reweight an OSD to control data distribution.
        
        Args:
            osd_id: OSD ID
            weight: New reweight value (0.0 to 1.0)
            
        Returns:
            Result dict
        """
        if not 0.0 <= weight <= 1.0:
            return {"error": f"Weight must be between 0.0 and 1.0, got {weight}"}
        
        success, result = self._run_ceph_command(
            ["osd", "reweight", str(osd_id), str(weight)], use_json=False
        )
        
        if success:
            logger.info(f"Reweighted OSD.{osd_id} to {weight}")
            return {"success": True, "osd_id": osd_id, "weight": weight,
                    "message": f"OSD.{osd_id} reweighted to {weight}"}
        return {"error": result}
    
    def create_pool(
        self, pool_name: str, pg_num: int = 32,
        pool_type: str = "replicated", size: int = 3
    ) -> Dict[str, Any]:
        """
        Create a new RADOS pool.
        
        Args:
            pool_name: Name for the new pool
            pg_num: Number of placement groups
            pool_type: "replicated" or "erasure"
            size: Replication factor
            
        Returns:
            Result dict
        """
        cmd = ["osd", "pool", "create", pool_name, str(pg_num)]
        if pool_type == "erasure":
            cmd.append("erasure")
        
        success, result = self._run_ceph_command(cmd, use_json=False)
        
        if success:
            # Set replication size for replicated pools
            if pool_type == "replicated":
                self._run_ceph_command(
                    ["osd", "pool", "set", pool_name, "size", str(size)], use_json=False
                )
            logger.info(f"Created pool '{pool_name}' ({pool_type}, pg={pg_num}, size={size})")
            return {
                "success": True, "pool_name": pool_name,
                "message": f"Created pool '{pool_name}' ({pool_type}, {pg_num} PGs, {size}x replication)"
            }
        return {"error": result}
    
    def delete_pool(self, pool_name: str) -> Dict[str, Any]:
        """
        Delete a RADOS pool. This is a destructive operation.
        
        Args:
            pool_name: Name of the pool to delete
            
        Returns:
            Result dict
        """
        # Must enable pool deletion first
        self._run_ceph_command(
            ["tell", "mon.*", "config", "set", "mon_allow_pool_delete", "true"],
            use_json=False
        )
        
        success, result = self._run_ceph_command(
            ["osd", "pool", "delete", pool_name, pool_name, "--yes-i-really-really-mean-it"],
            use_json=False
        )
        
        if success:
            logger.warning(f"Deleted pool '{pool_name}'")
            return {"success": True, "pool_name": pool_name,
                    "message": f"Pool '{pool_name}' deleted"}
        return {"error": result}
    
    def set_pool_param(self, pool_name: str, param: str, value: str) -> Dict[str, Any]:
        """
        Set a pool parameter.
        
        Args:
            pool_name: Pool name
            param: Parameter name
            value: Parameter value
            
        Returns:
            Result dict
        """
        valid_params = [
            "size", "min_size", "pg_num", "pgp_num",
            "target_max_bytes", "target_max_objects",
            "pg_autoscale_mode"
        ]
        
        if param not in valid_params:
            return {"error": f"Invalid parameter: {param}. Valid: {valid_params}"}
        
        success, result = self._run_ceph_command(
            ["osd", "pool", "set", pool_name, param, value], use_json=False
        )
        
        if success:
            logger.info(f"Set pool '{pool_name}' {param}={value}")
            return {"success": True, "pool_name": pool_name, "param": param, "value": value,
                    "message": f"Set {pool_name}.{param} = {value}"}
        return {"error": result}
    
    def restart_osd(self, osd_id: int) -> Dict[str, Any]:
        """
        Restart an OSD daemon via systemctl.
        
        Args:
            osd_id: OSD ID to restart
            
        Returns:
            Result dict
        """
        try:
            result = subprocess.run(
                ["sudo", "systemctl", "restart", f"ceph-osd@{osd_id}"],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"Restarted OSD.{osd_id}")
                return {"success": True, "osd_id": osd_id,
                        "message": f"OSD.{osd_id} restart initiated"}
            return {"error": result.stderr.strip()}
            
        except Exception as e:
            return {"error": str(e)}
    
    def repair_pg(self, pg_id: str) -> Dict[str, Any]:
        """
        Initiate repair on a placement group.
        
        Args:
            pg_id: PG ID (e.g., '1.2a')
            
        Returns:
            Result dict
        """
        success, result = self._run_ceph_command(
            ["pg", "repair", pg_id], use_json=False
        )
        
        if success:
            logger.info(f"Initiated repair on PG {pg_id}")
            return {"success": True, "pg_id": pg_id,
                    "message": f"Repair initiated on PG {pg_id}"}
        return {"error": result}
    
    def deep_scrub_pg(self, pg_id: str) -> Dict[str, Any]:
        """
        Initiate deep scrub on a placement group.
        
        Args:
            pg_id: PG ID
            
        Returns:
            Result dict
        """
        success, result = self._run_ceph_command(
            ["pg", "deep-scrub", pg_id], use_json=False
        )
        
        if success:
            logger.info(f"Initiated deep scrub on PG {pg_id}")
            return {"success": True, "pg_id": pg_id,
                    "message": f"Deep scrub initiated on PG {pg_id}"}
        return {"error": result}
    
    def initiate_rebalance(self, method: str = "upmap") -> Dict[str, Any]:
        """
        Initiate data rebalancing.
        
        Args:
            method: Balancing method (upmap, crush-compat, weight)
            
        Returns:
            Result dict
        """
        if method == "upmap":
            # Enable upmap balancer
            success, result = self._run_ceph_command(
                ["balancer", "mode", "upmap"], use_json=False
            )
            if success:
                success2, result2 = self._run_ceph_command(
                    ["balancer", "on"], use_json=False
                )
                if success2:
                    return {"success": True, "method": method,
                            "message": "Upmap balancer enabled"}
                return {"error": result2}
            return {"error": result}
        
        elif method == "crush-compat":
            success, result = self._run_ceph_command(
                ["balancer", "mode", "crush-compat"], use_json=False
            )
            if success:
                self._run_ceph_command(["balancer", "on"], use_json=False)
                return {"success": True, "method": method,
                        "message": "CRUSH-compat balancer enabled"}
            return {"error": result}
        
        else:
            return {"error": f"Unknown balancing method: {method}"}
    
    def get_config(self, key: str, daemon: str = "mon") -> Dict[str, Any]:
        """
        Get a Ceph configuration value.
        
        Args:
            key: Config key
            daemon: Daemon type
            
        Returns:
            Config value
        """
        success, result = self._run_ceph_command(
            ["config", "get", daemon, key], use_json=False
        )
        
        if success:
            return {"key": key, "value": result.strip(), "daemon": daemon}
        return {"error": result}
    
    def set_config(self, key: str, value: str, daemon: str = "global") -> Dict[str, Any]:
        """
        Set a Ceph configuration value at runtime.
        
        Args:
            key: Config key
            value: Config value
            daemon: Target daemon type (global, mon, osd, mds, mgr)
            
        Returns:
            Result dict
        """
        success, result = self._run_ceph_command(
            ["config", "set", daemon, key, value], use_json=False
        )
        
        if success:
            logger.info(f"Set config {daemon}/{key}={value}")
            return {"success": True, "key": key, "value": value, "daemon": daemon,
                    "message": f"Set {daemon}/{key} = {value}"}
        return {"error": result}
    
    def get_cluster_state_snapshot(self) -> Dict[str, Any]:
        """
        Get a comprehensive snapshot of cluster state for anomaly detection.
        
        Returns:
            Dictionary with health, OSDs, PGs, capacity, and performance data
        """
        state = {}
        
        # Health
        health = self.get_cluster_health()
        state["health"] = {
            "status": health.status,
            "checks": health.checks,
            "summary": health.summary,
        }
        
        # OSDs
        osds = self.get_osd_status()
        state["osds"] = [
            {
                "osd_id": o.osd_id,
                "host": o.host,
                "status": o.status,
                "in_cluster": o.in_cluster,
                "weight": o.weight,
                "utilization": o.utilization,
                "pgs": o.pgs,
            }
            for o in osds
        ]
        
        # PGs
        pg = self.get_pg_status()
        state["pgs"] = {
            "total": pg.total,
            "active_clean": pg.active_clean,
            "degraded": pg.degraded,
            "recovering": pg.recovering,
            "undersized": pg.undersized,
            "stale": pg.stale,
        }
        
        # Capacity
        state["capacity"] = self.predict_capacity()
        
        # Performance
        state["performance"] = self.get_performance_stats()
        
        return state
