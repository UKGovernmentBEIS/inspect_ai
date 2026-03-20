"""Example: run an Inspect AI eval with MLflow tracing enabled.

Prerequisites:
    pip install mlflow
    mlflow server --port 5556

Usage:
    export OPENAI_API_KEY="sk-..."
    python examples/hooks/mlflow_tracing_example.py

Then open http://127.0.0.1:5556 to see traces.
"""

import os
import sys

os.environ["MLFLOW_TRACKING_URI"] = "http://127.0.0.1:5556"
os.environ["MLFLOW_INSPECT_TRACING"] = "true"
os.environ["MLFLOW_EXPERIMENT_NAME"] = "inspect-tracing-test"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import mlflow  # noqa: E402
from examples.hooks.mlflow_tracing import MlflowTracingHooks  # noqa: E402, F401

from inspect_ai import Task, eval  # noqa: E402
from inspect_ai.dataset import Sample  # noqa: E402
from inspect_ai.scorer import match  # noqa: E402
from inspect_ai.solver import generate  # noqa: E402


def main():
    print("Setting up MLflow experiment...")
    mlflow.set_tracking_uri("http://127.0.0.1:5556")
    mlflow.set_experiment("inspect-tracing-test")

    # Simple math task with 5 samples
    dataset = [
        Sample(input="What is 2 + 2?", target="4"),
        Sample(input="What is 3 * 5?", target="15"),
        Sample(input="What is 10 - 7?", target="3"),
        Sample(input="What is 8 / 2?", target="4"),
        Sample(input="What is 6 + 9?", target="15"),
    ]

    task = Task(
        dataset=dataset,
        solver=generate(),
        scorer=match(),
    )

    print("Running Inspect AI eval with MLflow tracing enabled...")
    print("Model: openai/gpt-4o-mini")
    print(f"Samples: {len(dataset)}")
    print()

    logs = eval(
        task,
        model="openai/gpt-4o-mini",
        log_dir="/tmp/inspect-tracing-test-logs",
    )

    log = logs[0]
    print(f"\nEval status: {log.status}")

    if log.results and log.results.scores:
        for score in log.results.scores:
            for metric_name, metric in score.metrics.items():
                print(f"  {score.name}/{metric_name}: {metric.value}")

    if log.results:
        print(f"  Total samples: {log.results.total_samples}")
        print(f"  Completed: {log.results.completed_samples}")

    # Verify traces were created
    print("\nVerifying MLflow traces...")
    experiment = mlflow.get_experiment_by_name("inspect-tracing-test")
    if experiment:
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
        )
        print(f"  Traces found: {len(traces)}")
        if len(traces) > 0:
            print(f"  First trace ID: {traces.iloc[0]['trace_id']}")
            print(f"  Request ID: {traces.iloc[0].get('client_request_id', 'N/A')}")

            # Get the full trace to inspect spans
            trace_id = traces.iloc[0]["trace_id"]
            trace = mlflow.get_trace(trace_id)
            if trace and trace.data and trace.data.spans:
                print(f"  Spans in trace: {len(trace.data.spans)}")
                for span in trace.data.spans:
                    indent = "    " if span.parent_id else "  "
                    if span.parent_id:
                        indent = "      "
                    print(f"{indent}{span.name} ({span.span_type}) - {span.status}")
    else:
        print("  No experiment found!")

    print("\nDone. Open http://127.0.0.1:5556 to see traces.")


if __name__ == "__main__":
    main()
