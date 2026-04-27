#!/usr/bin/env python3
"""
Main runner for the Ceph-SRE evaluation suite.

Usage (from project root, as root for Ceph access):

  # Full suite (all evaluations):
  sudo venv/bin/python -m evaluation.runner --all

  # Individual evaluations:
  sudo venv/bin/python -m evaluation.runner --intent --runs 5
  sudo venv/bin/python -m evaluation.runner --react
  sudo venv/bin/python -m evaluation.runner --safety
  sudo venv/bin/python -m evaluation.runner --anomaly
  sudo venv/bin/python -m evaluation.runner --latency --iterations 5
  sudo venv/bin/python -m evaluation.runner --latency --no-cli

Hardware target: CloudLab node, NVIDIA P100 12 GB VRAM,
                 Ollama llama3.1:8b-instruct-fp16.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── ensure project root is on sys.path ───────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()
logger = logging.getLogger("evaluation")

# ── configuration ────────────────────────────────────────────────────────
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
OUTPUT_DIR = PROJECT_ROOT / "evaluation_results"


# ── bootstrap helpers ────────────────────────────────────────────────────

def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    fmt = log_cfg.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.basicConfig(level=level, format=fmt,
                        handlers=[logging.StreamHandler()])


def create_agent(config: dict):
    """
    Bootstrap the full LLMAgent with all dependencies, mirroring
    the cli.py → AgentService initialisation path.
    """
    from services.agent_service import AgentService
    from core.embedding_generator import EmbeddingGenerator
    from core.content_processor import ContentProcessor
    from core.rados_vector_store import RadosVectorStore

    try:
        from core.rados_client import RadosClient
        HAS_RADOS = True
    except (ImportError, ModuleNotFoundError):
        HAS_RADOS = False
        RadosClient = None

    # RADOS
    rados_client = None
    if HAS_RADOS:
        try:
            rados_client = RadosClient(**config["ceph"])
            rados_client.connect()
            console.print(
                f"[green]Connected to pool: {config['ceph']['pool_name']}[/green]")
        except Exception as e:
            console.print(f"[yellow]Ceph unavailable: {e}[/yellow]")

    # Embedding
    emb = config["embedding"]
    embedding_gen = EmbeddingGenerator(
        model_name=emb.get("model", "all-MiniLM-L6-v2"),
        device=emb.get("device", "cpu"),
        normalize_embeddings=emb.get("normalize_embeddings", True),
        batch_size=emb.get("batch_size", 32),
    )

    # Content processor
    idx = config["indexing"]
    content_proc = ContentProcessor(
        max_file_size_mb=idx.get("max_file_size_mb", 100),
        encoding_detection=idx.get("encoding_detection", True),
        fallback_encoding=idx.get("fallback_encoding", "utf-8"),
        supported_extensions=idx.get("supported_extensions", []),
    )

    # Vector store
    vec = config["vectordb"]
    vector_store = RadosVectorStore(
        rados_client=rados_client,
        embedding_dim=vec.get("embedding_dim", 384),
    )

    # Agent service
    llm_config = config.get("llm", {})
    agent_config = config.get("agent", {})
    svc = AgentService(
        llm_config=llm_config,
        rados_client=rados_client,
        embedding_generator=embedding_gen,
        content_processor=content_proc,
        vector_store=vector_store,
        agent_config=agent_config,
    )

    # Seed test objects in RADOS for evaluation benchmarks
    if rados_client:
        try:
            from evaluation.test_data_setup import setup_test_data
            created, indexed, errs = setup_test_data(
                rados_client, svc.indexer, force_recreate=False)
            if created or indexed:
                console.print(
                    f"[dim]Seeded test data: {created} created, "
                    f"{indexed} indexed[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Test-data seed skipped: {exc}[/yellow]")

    return svc.agent, rados_client


# ── progress callback ────────────────────────────────────────────────────

class ProgressTracker:
    def __init__(self):
        self.progress = None
        self.task_ids = {}

    def __call__(self, current, total, label=""):
        key = label or "eval"
        if self.progress is None:
            return
        if key not in self.task_ids:
            self.task_ids[key] = self.progress.add_task(
                f"[cyan]{key}", total=total)
        self.progress.update(self.task_ids[key], completed=current)


# ── individual evaluation runners ────────────────────────────────────────

def run_intent(agent, num_runs: int, include_ceph: bool, tracker):
    from evaluation.intent_eval import IntentEvaluator
    console.print("\n[bold]§1  Intent Classification[/bold]")
    ev = IntentEvaluator(agent, include_ceph=include_ceph)
    console.print(f"    {len(ev.test_cases)} test cases × {num_runs} runs")
    report = ev.evaluate(num_runs=num_runs, progress_callback=tracker)
    console.print(
        f"    [green]Intent accuracy: {report.intent_accuracy_mean:.1f}% "
        f"± {report.intent_accuracy_std:.1f}%[/green]")
    return report


def run_react(agent, include_ceph: bool, tracker):
    from evaluation.react_eval import ReactEvaluator
    console.print("\n[bold]§2  ReAct vs Simple Mode[/bold]")
    ev = ReactEvaluator(agent, include_ceph=include_ceph)
    console.print(f"    {len(ev.test_cases)} scenarios")
    report = ev.evaluate(progress_callback=tracker)
    console.print(
        f"    [green]Routing acc: {report.routing_accuracy:.1f}%, "
        f"React wins: {report.react_wins}, "
        f"Simple wins: {report.simple_wins}[/green]")
    return report


def run_safety(agent, tracker):
    from evaluation.safety_eval import SafetyEvaluator
    console.print("\n[bold]§3  Safety Framework[/bold]")
    ev = SafetyEvaluator(agent.action_engine)
    console.print(f"    {len(ev.test_cases)} test cases")
    report = ev.evaluate(progress_callback=tracker)
    console.print(
        f"    [green]Risk accuracy: {report.risk_accuracy:.1f}%, "
        f"Confirm accuracy: {report.confirmation_accuracy:.1f}%[/green]")
    return report


def run_anomaly(agent, tracker):
    from evaluation.anomaly_eval import AnomalyEvaluator
    console.print("\n[bold]§4  Anomaly Detection[/bold]")
    ev = AnomalyEvaluator(agent.anomaly_detector)
    console.print(f"    {len(ev.scenarios)} synthetic scenarios")
    report = ev.evaluate(progress_callback=tracker)
    console.print(
        f"    [green]Score acc: {report.score_accuracy:.1f}%, "
        f"F1: {report.f1_score:.3f}[/green]")
    return report


def run_latency(agent, iterations: int, include_cli: bool, tracker):
    from evaluation.latency_profiler import LatencyProfiler
    console.print("\n[bold]§5  Latency Profile[/bold]")
    prof = LatencyProfiler(agent)
    console.print(
        f"    {len(prof.workload)} operations × {iterations} iterations"
        f"{' + CLI' if include_cli else ''}")
    report = prof.profile(
        iterations=iterations, include_cli=include_cli,
        warmup=1, progress_callback=tracker,
    )
    console.print(
        f"    [green]Mean: {report.overall_mean_ms:.0f} ms, "
        f"P95: {report.overall_p95_ms:.0f} ms[/green]")
    return report


def run_integration(agent, tracker):
    from evaluation.integration_eval import IntegrationEvaluator
    console.print("\n[bold]§6  Integration Tests (live cluster)[/bold]")
    ev = IntegrationEvaluator(agent)
    console.print(f"    {len(ev.scenarios)} end-to-end scenarios")
    report = ev.evaluate(progress_callback=tracker)
    if report.skipped == report.num_scenarios:
        console.print(
            "    [yellow]Skipped: Ceph cluster not available[/yellow]")
    else:
        console.print(
            f"    [green]Passed: {report.passed}/{report.num_scenarios}, "
            f"Failed: {report.failed}[/green]")
    return report


def run_fault_injection(agent, osd_id: int, tracker):
    from evaluation.integration_eval import (
        IntegrationEvaluator, get_fault_injection_scenarios,
    )
    console.print(
        f"\n[bold]§7  Fault Injection (OSD {osd_id})[/bold]"
        "\n    [yellow]⚠  Stops a live OSD daemon — ensure cluster has ≥3 OSDs[/yellow]"
    )
    scenarios = get_fault_injection_scenarios(osd_id=osd_id)
    ev = IntegrationEvaluator(agent, scenarios=scenarios)
    report = ev.evaluate(progress_callback=tracker)
    if report.skipped == report.num_scenarios:
        console.print(
            "    [yellow]Skipped: Ceph cluster not available[/yellow]")
    else:
        status = "[green]PASSED[/green]" if report.passed else "[red]FAILED[/red]"
        console.print(f"    {status} ({report.passed}/{report.num_scenarios})")
        for r in report.results:
            for step in r.steps:
                icon = "✓" if step.success else "✗"
                console.print(
                    f"      [{icon}] {step.step:<18} "
                    f"{step.detail or step.error or ''}"
                )
    return report


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ceph-SRE CHEOPS 2026 evaluation suite")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Path to config.yaml")
    parser.add_argument("--output", default=str(OUTPUT_DIR),
                        help="Output directory")

    # evaluation selectors
    parser.add_argument("--all", action="store_true",
                        help="Run all evaluations")
    parser.add_argument("--intent", action="store_true",
                        help="Run intent classification eval")
    parser.add_argument("--react", action="store_true",
                        help="Run ReAct vs Simple eval")
    parser.add_argument("--safety", action="store_true",
                        help="Run safety framework eval")
    parser.add_argument("--anomaly", action="store_true",
                        help="Run anomaly detection eval")
    parser.add_argument("--latency", action="store_true",
                        help="Run latency profiler")
    parser.add_argument("--integration", action="store_true",
                        help="Run live integration tests (requires Ceph cluster)")
    parser.add_argument("--integration-fault-injection", action="store_true",
                        dest="fault_injection",
                        help="Run OSD fault injection test (requires root + systemd)")
    parser.add_argument("--osd-id", type=int, default=0, dest="osd_id",
                        help="OSD number to use for fault injection (default: 0)")

    # parameters
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of intent-eval runs (default: 5)")
    parser.add_argument("--iterations", type=int, default=5,
                        help="Latency profiler iterations (default: 5)")
    parser.add_argument("--no-cli", action="store_true",
                        help="Skip CLI baseline in latency profiler")
    parser.add_argument("--no-ceph", action="store_true",
                        help="Exclude tests requiring live Ceph cluster")

    args = parser.parse_args()

    # If nothing selected, default to --all
    run_all = args.all or not any([
        args.intent, args.react, args.safety, args.anomaly, args.latency,
        args.integration, args.fault_injection,
    ])

    # ── setup ────────────────────────────────────────────────────────
    config = load_config(Path(args.config))
    setup_logging(config)

    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print("[bold cyan]  Ceph-SRE  —  CHEOPS 2026 Evaluation Suite[/bold cyan]")
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print(f"  Model:  {config.get('llm', {}).get('model', '?')}")
    console.print(f"  Output: {args.output}")
    console.print()

    t_start = time.time()
    agent, rados_client = create_agent(config)
    include_ceph = not args.no_ceph

    # ── run evaluations ──────────────────────────────────────────────
    tracker = ProgressTracker()
    intent_report = react_report = safety_report = None
    anomaly_report = latency_report = integration_report = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        tracker.progress = progress

        if run_all or args.intent:
            intent_report = run_intent(
                agent, args.runs, include_ceph, tracker)

        if run_all or args.react:
            react_report = run_react(agent, include_ceph, tracker)

        if run_all or args.safety:
            safety_report = run_safety(agent, tracker)

        if run_all or args.anomaly:
            anomaly_report = run_anomaly(agent, tracker)

        if run_all or args.latency:
            latency_report = run_latency(
                agent, args.iterations, not args.no_cli, tracker)

        if args.integration:  # never included in --all by default
            integration_report = run_integration(agent, tracker)

        if args.fault_injection:  # opt-in only, never in --all
            run_fault_injection(agent, args.osd_id, tracker)

    # ── generate reports ─────────────────────────────────────────────
    from evaluation.report_generator import ReportGenerator

    model_name = config.get('llm', {}).get('model', 'unknown_model').replace(':', '_').replace('.', '_')
    model_output_dir = Path(args.output) / model_name

    gen = ReportGenerator(output_dir=str(model_output_dir))
    paths = gen.generate(
        intent_report=intent_report,
        react_report=react_report,
        safety_report=safety_report,
        anomaly_report=anomaly_report,
        latency_report=latency_report,
    )

    elapsed = time.time() - t_start
    console.print()
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print(f"[bold green]  Evaluation complete in {elapsed:.0f}s[/bold green]")
    for label, path in paths.items():
        console.print(f"    {label:6s}  →  {path}")
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")

    # ── cleanup ──────────────────────────────────────────────────────
    if rados_client:
        try:
            rados_client.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
