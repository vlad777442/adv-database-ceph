"""
Ceph-SRE CHEOPS 2026 Evaluation Suite.

Comprehensive evaluation for publication-ready data:
  - Intent classification accuracy (40+ operation types)
  - ReAct vs Simple mode comparison
  - Safety framework evaluation (risk classification)
  - Anomaly detection precision/recall
  - End-to-end latency profiling
  - Agent vs CLI baseline comparison
  - LaTeX tables + matplotlib figures

Hardware target: CloudLab node, NVIDIA P100 (12 GB VRAM),
  Ollama llama3.1:8b-instruct-fp16.

Usage:
  sudo venv/bin/python -m evaluation.cheops_eval.runner --all
"""

__version__ = "1.0.0"
