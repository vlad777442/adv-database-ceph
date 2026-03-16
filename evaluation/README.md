# Evaluation Suite

## Quick start

```bash
# Full suite (all 5 evaluations, default 5 runs):
sudo venv/bin/python -m evaluation.runner --all

# Quick smoke test (intent only, 1 run):
sudo venv/bin/python -m evaluation.runner --intent --runs 1

# Individual evaluations:
sudo venv/bin/python -m evaluation.runner --react
sudo venv/bin/python -m evaluation.runner --safety --anomaly
sudo venv/bin/python -m evaluation.runner --latency --iterations 3

# Skip Ceph-dependent tests or CLI baseline:
sudo venv/bin/python -m evaluation.runner --all --no-ceph
sudo venv/bin/python -m evaluation.runner --latency --no-cli
```

## Package layout

```
evaluation/
├── runner.py            ← main CLI entry point
├── test_cases.py        ← all test cases (intent, react, safety, anomaly)
├── intent_eval.py       ← §1 intent classification (mean ± std, confusion matrix)
├── react_eval.py        ← §2 ReAct vs Simple mode comparison
├── safety_eval.py       ← §3 action-engine risk classification
├── anomaly_eval.py      ← §4 anomaly detection precision/recall
├── latency_profiler.py  ← §5 end-to-end latency + CLI baseline
├── report_generator.py  ← LaTeX tables + matplotlib figures
└── _base.py             ← base dataclasses (TestCase, EvaluationReport, …)
```

## Outputs

All artifacts land in `evaluation_results/`:
- `eval_<timestamp>.json`    — full data bundle
- `tables_<timestamp>.tex`   — ACM/EuroSys LaTeX tables
- `summary_<timestamp>.txt`  — human-readable summary
- `fig_*.pdf`                — matplotlib figures (requires matplotlib)