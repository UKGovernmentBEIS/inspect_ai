import os
from inspect_ai import eval


def main():
    # Define the standard deviations to test
    std_values = [0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.1]

    # Set up log directory for this experiment
    log_dir = "./sandbag_experiment_logs"
    os.environ["INSPECT_LOG_DIR"] = log_dir
    os.makedirs(log_dir, exist_ok=True)

    # Define the base model configuration
    model_name = "noise_hf/microsoft/Phi-3-mini-4k-instruct"
    base_model_args = {
        "noise_percentage": 1.0,
        "noise_mean": 0.0,  # Adding this as a default
    }

    # Run eval for each standard deviation
    for std in std_values:
        # Update model args with current std
        model_args = base_model_args.copy()
        model_args["noise_std"] = std

        # Run eval with current configuration
        eval(
            tasks="examples/sandbag_arc.py",
            model=[model_name],
            model_args=model_args,
        )


if __name__ == "__main__":
    main()
