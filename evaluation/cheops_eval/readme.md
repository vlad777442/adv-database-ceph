# Full suite (all 5 evaluations):
sudo venv/bin/python -m evaluation.cheops_eval.runner --all

# Quick smoke test (intent only, 1 run):
sudo venv/bin/python -m evaluation.cheops_eval.runner --intent --runs 1

# Individual evals:
sudo venv/bin/python -m evaluation.cheops_eval.runner --react
sudo venv/bin/python -m evaluation.cheops_eval.runner --safety --anomaly
sudo venv/bin/python -m evaluation.cheops_eval.runner --latency --iterations 3

# Skip Ceph-dependent tests or CLI baseline:
sudo venv/bin/python -m evaluation.cheops_eval.runner --all --no-ceph
sudo venv/bin/python -m evaluation.cheops_eval.runner --latency --no-cli