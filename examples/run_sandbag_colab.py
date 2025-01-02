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
    model_name = "noise_hf/microsoft/Phi-3-mini-4k-instruct"

    try:
        # Run eval with current configuration
        eval(
            tasks="examples/sandbag_arc.py",
            max_tokens=8,
            # temperature=0.0,
            do_sample=False,
            model=[model_name],
            model_args={
                "noise_percentage": 1.0,
                "noise_mean": 0.0,
                "noise_std": std_value,
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
