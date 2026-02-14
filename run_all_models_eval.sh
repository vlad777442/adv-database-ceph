#!/bin/bash
# Run CHEOPS evaluation for multiple models with 5 runs each
# This script will continue running even if the laptop goes to sleep

MODELS=(
    "llama3.1:8b"
    "qwen2.5:7b"
    "qwen2.5:14b"
    "llama3.1:8b-instruct-fp16"
    "phi3.5:latest"
)

echo "========================================"
echo "Starting CHEOPS Multi-Model Evaluation"
echo "========================================"
echo "Models: ${MODELS[@]}"
echo "Runs per model: 5"
echo "Start time: $(date)"
echo ""

for MODEL in "${MODELS[@]}"; do
    # Replace special characters in model name for log file
    MODEL_SAFE=$(echo "$MODEL" | tr ':' '_' | tr '.' '_')
    LOG_FILE="eval_${MODEL_SAFE}_runs5.log"
    
    echo "----------------------------------------"
    echo "Running evaluation for model: $MODEL"
    echo "Log file: $LOG_FILE"
    echo "Started at: $(date)"
    echo "----------------------------------------"
    
    # Update config.yaml to use the current model (only the llm.model field)
    sed -i "/^llm:/,/^[^ ]/ s/  model: .*/  model: $MODEL/" config.yaml
    
    # Run the evaluation
    sudo venv/bin/python -m evaluation.cheops_eval.runner --all --runs 5 > "$LOG_FILE" 2>&1
    
    EXIT_CODE=$?
    echo ""
    echo "Model $MODEL completed with exit code: $EXIT_CODE"
    echo "Finished at: $(date)"
    echo ""
    
    # Small delay between models to let system stabilize
    sleep 10
done

echo "========================================"
echo "All evaluations complete!"
echo "End time: $(date)"
echo "========================================"
