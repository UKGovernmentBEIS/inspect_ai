import os
import gc
import torch
from inspect_ai import eval
import time


def cleanup_gpu():
    """Force cleanup of GPU memory between model runs."""
    # Clear any cached tensors
    torch.cuda.empty_cache()

    # Force garbage collection
    gc.collect()

    # Additional memory cleanup steps
    if torch.cuda.is_available():
        # Explicitly clear CUDA memory
        with torch.cuda.device("cuda:0"):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    # Second GC pass after CUDA cleanup
    gc.collect()


def main():
    # Define the standard deviations to test
    std_values = [0.0, 0.001, 0.002, 0.003, 0.004, 0.005]

    # Set up log directory for this experiment
    log_dir = "./sandbag_experiment_logs"
    os.environ["INSPECT_LOG_DIR"] = log_dir
    os.makedirs(log_dir, exist_ok=True)

    # Set PyTorch memory allocation settings
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    # Define the model name
    model_name = "noise_hf/microsoft/Phi-3-mini-4k-instruct"

    # Run eval for each standard deviation
    for std in std_values:
        try:
            # Run eval with current configuration
            eval(
                tasks="examples/sandbag_arc.py",
                model=[model_name],
                model_args={
                    "noise_percentage": 1.0,
                    "noise_mean": 0.0,
                    "noise_std": std,
                    "low_cpu_mem_usage": True,
                },
            )
        except Exception as e:
            print(f"Error during evaluation with std={std}: {str(e)}")
            # Continue with next iteration even if current one fails
        finally:
            # Ensure cleanup happens even if eval fails
            cleanup_gpu()
            # Add a small delay to allow memory to settle
            time.sleep(2)


if __name__ == "__main__":
    main()
