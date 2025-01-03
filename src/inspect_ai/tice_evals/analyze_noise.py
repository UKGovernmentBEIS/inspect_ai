import os
import csv
from inspect_ai.log import list_eval_logs, read_eval_log


def analyze_logs(log_dir: str):
    # Create output filename based on log directory name
    # Strip any leading ./ and trailing / from the directory name
    dir_name = log_dir.strip("./").rstrip("/")
    output_file = f"{dir_name}_results.csv"

    # Get all logs from the directory
    logs = list_eval_logs(log_dir)

    # Prepare CSV file
    with open(output_file, "w", newline="") as csvfile:
        fieldnames = [
            "noise_std",
            "noise_percentage",
            "noise_mean",
            "seed",
            "task",
            "accuracy",
            "accuracy_pass_at_1",
            "accuracy_pass_at_2",
            "accuracy_pass_at_5",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        # Process each log
        for log_path in logs:
            # Read the log header only since we don't need sample data
            log = read_eval_log(log_path, header_only=True)

            # Extract required information
            model_args = log.eval.model_args
            row = {
                "noise_std": model_args.get("noise_std", 0.0),
                "noise_percentage": model_args.get("noise_percentage", 1.0),
                "noise_mean": model_args.get("noise_mean", 0.0),
                "seed": model_args.get("seed", None),
                "task": log.eval.task,
                "accuracy": None,  # Will be updated if we find the accuracy metric
                "accuracy_pass_at_1": None,
                "accuracy_pass_at_2": None,
                "accuracy_pass_at_5": None,
            }

            # Extract accuracy from results
            if log.results and log.results.scores:
                if log.eval.task == "mbpp":
                    # For MBPP tasks, extract all accuracy metrics
                    for score in log.results.scores:
                        if "accuracy" in score.metrics:
                            reducer = score.reducer
                            accuracy = score.metrics["accuracy"].value
                            if reducer == "mean":
                                row["accuracy"] = (
                                    accuracy  # Keep backward compatibility
                                )
                            elif reducer == "pass_at_1":
                                row["accuracy_pass_at_1"] = accuracy
                            elif reducer == "pass_at_2":
                                row["accuracy_pass_at_2"] = accuracy
                            elif reducer == "pass_at_5":
                                row["accuracy_pass_at_5"] = accuracy
                else:
                    # For non-MBPP tasks, just get the regular accuracy
                    for score in log.results.scores:
                        if "accuracy" in score.metrics:
                            row["accuracy"] = score.metrics["accuracy"].value
                            break

            # Write the row
            writer.writerow(row)

    return output_file


def main():
    # Use the same log directory as defined in run_sandbag.py
    log_dir = "./sandbag_experiment_logs"
    output_file = analyze_logs(log_dir)
    print(f"Analysis complete. Results written to {output_file}")


if __name__ == "__main__":
    main()
