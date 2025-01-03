import os
import argparse
from inspect_ai import eval


def main(std_value):
    # Set up log directory for this experiment
    log_dir = "./sandbag_experiment_logs"
    os.environ["INSPECT_LOG_DIR"] = log_dir
    os.makedirs(log_dir, exist_ok=True)

    # Set PyTorch memory allocation settings
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    # Define the model name
    model_name = "noise_hf/meta-llama/Meta-Llama-3.1-8B-Instruct"

    try:
        # Run eval with current configuration
        eval(
            tasks="src/inspect_ai/tice_evals/sandbag_MBPP.py",
            model=[model_name],
            max_tokens=200,
            model_args={
                "noise_percentage": 1.0,
                "noise_mean": 0.0,
                "noise_std": std_value,
                "seed": 999,
            },
        )
    except Exception as e:
        print(f"Error during evaluation with std={std_value}: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run sandbag evaluation with noise std"
    )
    parser.add_argument(
        "--std", type=float, required=True, help="Standard deviation value for noise"
    )

    args = parser.parse_args()
    main(args.std)
