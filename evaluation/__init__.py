"""
Evaluation suite for the Ceph-SRE LLM Agent.

Entry point:
  sudo venv/bin/python -m evaluation.runner --all

Individual evaluations:
  sudo venv/bin/python -m evaluation.runner --intent --runs 5
  sudo venv/bin/python -m evaluation.runner --react
  sudo venv/bin/python -m evaluation.runner --safety
  sudo venv/bin/python -m evaluation.runner --anomaly
  sudo venv/bin/python -m evaluation.runner --latency --iterations 5
"""

from evaluation._base import (
    EvaluationFramework,
    TestCase,
    TestResult,
    EvaluationReport,
    MetricType,
    create_test_case,
)

__all__ = [
    "EvaluationFramework",
    "TestCase",
    "TestResult",
    "EvaluationReport",
    "MetricType",
    "create_test_case",
]
