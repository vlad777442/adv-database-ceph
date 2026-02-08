#!/usr/bin/env python3
"""Run evaluation across multiple LLM models for paper comparison."""

import subprocess
import yaml
import json
import shutil
from pathlib import Path
from datetime import datetime

MODELS_TO_TEST = [
    "llama3.2",        # 3B  - your baseline
    "llama3.1:8b",     # 8B  - same family, larger
    "qwen2.5:7b",      # 7B  - best function calling
    "mistral:7b",      # 7B  - different architecture
    "qwen2.5:14b",     # 14B - quality ceiling
]

NUM_RUNS = 5  # Run each model 5 times for error bars!

CONFIG_PATH = "config.yaml"
RESULTS_DIR = Path("evaluation_results/model_comparison")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def update_config(model_name: str):
    """Update config.yaml with the target model."""
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    config['llm']['model'] = model_name
    config['embedding']['device'] = 'cuda'  # Use GPU!
    
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def pull_model(model_name: str):
    """Ensure model is pulled."""
    print(f"Pulling {model_name}...")
    subprocess.run(["ollama", "pull", model_name], check=True)

def run_evaluation(model_name: str, run_id: int):
    """Run the evaluation framework."""
    print(f"Running evaluation: {model_name} (run {run_id}/{NUM_RUNS})")
    result = subprocess.run(
        ["sudo", "venv/bin/python", "cli.py", "evaluate"],
        capture_output=True, text=True
    )
    return result

def main():
    for model in MODELS_TO_TEST:
        pull_model(model)
        update_config(model)
        
        for run in range(1, NUM_RUNS + 1):
            print(f"\n{'='*60}")
            print(f"Model: {model} | Run: {run}/{NUM_RUNS}")
            print(f"{'='*60}")
            
            run_evaluation(model, run)
            
            # Copy results with model and run info
            latest = sorted(Path("evaluation_results").glob("evaluation_*.json"))[-1]
            dest = RESULTS_DIR / f"{model.replace(':', '_')}_run{run}.json"
            shutil.copy(latest, dest)
            print(f"Saved: {dest}")
    
    print("\nAll evaluations complete!")
    print(f"Results in: {RESULTS_DIR}")

if __name__ == "__main__":
    main()