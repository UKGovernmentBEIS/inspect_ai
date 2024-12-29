# run_hellaswag.py
from inspect_ai import eval


def main():
    # Define the model name and corresponding arguments
    model_name = "noise_hf/microsoft/Phi-3-mini-4k-instruct"  # Custom identifier for your NoiseHuggingFaceAPI
    model_args = {
        "noise_std": 0.00,
        "noise_percentage": 1.0,
    }

    # Run eval_async with model name and model_args
    eval(
        tasks="examples/sandbag_hellaswag.py",  # Path to your task file
        model=[model_name],  # Pass the registered model name as a list of strings
        model_args=[model_args],  # Pass model arguments corresponding to each model
    )


if __name__ == "__main__":
    main()
