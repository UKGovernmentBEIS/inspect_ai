"""MLflow Tracking hook for Inspect AI.

Logs evaluation runs, task configurations, sample scores, and model usage
to an MLflow tracking server. Creates a parent run per eval run with nested
child runs per task.

To enable, set MLFLOW_TRACKING_URI (and optionally MLFLOW_EXPERIMENT_NAME):

    export MLFLOW_TRACKING_URI="http://localhost:5000"
    export MLFLOW_EXPERIMENT_NAME="inspect-evals"  # defaults to "inspect_ai"

Then import this module before running evals:

    from examples.hooks.mlflow_tracking import MlflowTrackingHooks  # noqa: F401

    inspect eval my_task.py
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

import mlflow

from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.hooks import (
    Hooks,
    ModelUsageData,
    RunEnd,
    RunStart,
    SampleEnd,
    SampleEvent,
    TaskEnd,
    TaskStart,
    hooks,
)
from inspect_ai.log import EvalSpec

logger = logging.getLogger(__name__)


def _safe_log_params(params: dict[str, Any]) -> None:
    """Log params, truncating values that exceed MLflow's 500-char limit."""
    for key, value in params.items():
        str_val = str(value)
        if len(str_val) > 500:
            str_val = str_val[:497] + "..."
        try:
            mlflow.log_param(key, str_val)
        except Exception:
            pass


def _score_to_numeric(value: Any) -> float | None:
    """Convert a Score value to a numeric value for MLflow metrics."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Common patterns: "C" for correct, "I" for incorrect, "P" for partial
        mapping = {"C": 1.0, "I": 0.0, "P": 0.5, "correct": 1.0, "incorrect": 0.0}
        return mapping.get(value)
    return None


def _truncate(text: Any, max_len: int = 500) -> str:
    """Truncate text to max_len characters, adding ellipsis if truncated."""
    s = str(text) if text is not None else ""
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


@hooks(name="mlflow_tracking", description="MLflow Tracking")
class MlflowTrackingHooks(Hooks):
    """MLflow Tracking Hooks.

    Tracks Inspect AI evaluations in MLflow with a hierarchical structure:
    one parent run per eval invocation, with nested child runs per task.

    Logs task configuration as parameters, per-sample scores as metrics,
    and model token usage.

    To enable, set MLFLOW_TRACKING_URI and optionally MLFLOW_EXPERIMENT_NAME.
    """

    def __init__(self) -> None:
        self._parent_run: mlflow.ActiveRun | None = None
        self._task_runs: dict[str, mlflow.ActiveRun] = {}
        self._tasks: dict[str, EvalSpec] = {}
        self._sample_counts: dict[str, int] = {}
        self._model_usage: dict[str, dict[str, float]] = {}
        self._event_counts: dict[str, dict[str, int]] = {}

    def enabled(self) -> bool:
        return os.getenv("MLFLOW_TRACKING_URI") is not None

    async def on_run_start(self, data: RunStart) -> None:
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "inspect_ai")
        mlflow.set_experiment(experiment_name)

        self._parent_run = mlflow.start_run(
            run_name=f"inspect-{data.run_id[:8]}",
            tags={
                "inspect.run_id": data.run_id,
                "inspect.task_count": str(len(data.task_names)),
                "inspect.tasks": ", ".join(data.task_names),
            },
        )

    async def on_run_end(self, data: RunEnd) -> None:
        # End any remaining task runs (shouldn't happen normally)
        for eval_id in list(self._task_runs.keys()):
            mlflow.end_run()
            self._task_runs.pop(eval_id, None)

        # Log run-level summary on parent
        if self._parent_run:
            status = "FAILED" if data.exception else "FINISHED"
            mlflow.end_run(status=status)
            self._parent_run = None

        self._tasks.clear()
        self._sample_counts.clear()
        self._model_usage.clear()
        self._event_counts.clear()

    async def on_task_start(self, data: TaskStart) -> None:
        self._tasks[data.eval_id] = data.spec
        self._sample_counts[data.eval_id] = 0

        if not self._parent_run:
            return

        # Start a nested child run for this task
        task_run = mlflow.start_run(
            run_name=data.spec.task,
            nested=True,
            tags={
                "inspect.eval_id": data.eval_id,
                "inspect.run_id": data.run_id,
                "inspect.task": data.spec.task,
                "inspect.model": data.spec.model,
            },
        )
        self._task_runs[data.eval_id] = task_run

        # Log task configuration as parameters
        _safe_log_params(
            {
                "task": data.spec.task,
                "model": data.spec.model,
                "task_version": str(data.spec.task_version),
                "dataset.name": data.spec.dataset.name or "",
                "dataset.samples": str(data.spec.dataset.samples or ""),
                "solver": data.spec.solver or "",
            }
        )

        # Log task args (user-provided)
        if data.spec.task_args_passed:
            _safe_log_params(
                {f"task_arg.{k}": v for k, v in data.spec.task_args_passed.items()}
            )

        # Log generate config
        config = data.spec.model_generate_config
        gen_params: dict[str, Any] = {}
        if config.temperature is not None:
            gen_params["temperature"] = config.temperature
        if config.top_p is not None:
            gen_params["top_p"] = config.top_p
        if config.max_tokens is not None:
            gen_params["max_tokens"] = config.max_tokens
        if gen_params:
            _safe_log_params(gen_params)

        # Log tags if present
        if data.spec.tags:
            _safe_log_params({"tags": ", ".join(data.spec.tags)})

    async def on_task_end(self, data: TaskEnd) -> None:
        eval_id = data.eval_id
        task_run = self._task_runs.get(eval_id)
        if not task_run:
            return

        log = data.log

        # Log aggregate results
        if log.results and log.results.scores:
            for eval_score in log.results.scores:
                scorer_name = eval_score.name
                for metric_name, metric in eval_score.metrics.items():
                    metric_key = f"{scorer_name}/{metric_name}"
                    if isinstance(metric.value, (int, float)):
                        try:
                            mlflow.log_metric(metric_key, float(metric.value))
                        except Exception:
                            pass

        # Log completion stats
        if log.results:
            try:
                mlflow.log_metric("total_samples", log.results.total_samples)
                mlflow.log_metric("completed_samples", log.results.completed_samples)
            except Exception:
                pass

        # Log aggregate model usage from stats
        if log.stats and log.stats.model_usage:
            for model_name, usage in log.stats.model_usage.items():
                prefix = f"usage/{model_name}"
                try:
                    mlflow.log_metric(f"{prefix}/input_tokens", usage.input_tokens)
                    mlflow.log_metric(f"{prefix}/output_tokens", usage.output_tokens)
                    mlflow.log_metric(f"{prefix}/total_tokens", usage.total_tokens)
                except Exception:
                    pass

        # Log event counts
        event_counts = self._event_counts.get(eval_id, {})
        if event_counts:
            try:
                mlflow.log_metric(
                    "total_model_calls", event_counts.get("model_calls", 0)
                )
                mlflow.log_metric(
                    "total_tool_calls", event_counts.get("tool_calls", 0)
                )
            except Exception:
                pass

        # Log eval artifacts (sample results table + eval log JSON)
        if os.getenv("MLFLOW_INSPECT_LOG_ARTIFACTS", "true").lower() != "false":
            self._log_eval_artifacts(log)

        # Log eval status
        status = "FINISHED" if log.status == "success" else "FAILED"
        mlflow.end_run(status=status)
        self._task_runs.pop(eval_id, None)
        self._tasks.pop(eval_id, None)
        self._event_counts.pop(eval_id, None)

    def _log_eval_artifacts(self, log: Any) -> None:
        """Log eval artifacts: per-sample results table and eval log JSON."""
        try:
            self._log_sample_table(log)
        except Exception:
            logger.debug("Failed to log sample results artifact", exc_info=True)
        try:
            self._log_eval_json(log)
        except Exception:
            logger.debug("Failed to log eval log artifact", exc_info=True)

    def _log_sample_table(self, log: Any) -> None:
        """Write per-sample results as a JSON artifact under sample_results/."""
        if not log.samples:
            return

        rows = []
        for sample in log.samples:
            row: dict[str, Any] = {
                "id": sample.id,
                "epoch": sample.epoch,
                "input": _truncate(sample.input, 500),
                "target": _truncate(sample.target, 300),
                "total_time": sample.total_time,
                "error": getattr(sample, "error", None),
            }
            if sample.output and sample.output.choices:
                first_choice = sample.output.choices[0]
                row["output"] = _truncate(first_choice.message.text, 500)
            else:
                row["output"] = ""
            if sample.scores:
                for scorer_name, score in sample.scores.items():
                    row[f"score/{scorer_name}"] = score.value
                    if score.explanation:
                        row[f"explanation/{scorer_name}"] = _truncate(
                            score.explanation, 300
                        )
            rows.append(row)

        eval_id = log.eval.eval_id if log.eval else "unknown"
        fd, path = tempfile.mkstemp(
            prefix=f"sample_results_{eval_id}_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(rows, f, indent=2, default=str)
            mlflow.log_artifact(path, artifact_path="sample_results")
        finally:
            os.unlink(path)

    def _log_eval_json(self, log: Any) -> None:
        """Write EvalLog (minus samples) as JSON under eval_logs/."""
        eval_id = log.eval.eval_id if log.eval else "unknown"
        log_data = log.model_dump(mode="json", exclude={"samples"})

        fd, path = tempfile.mkstemp(
            prefix=f"eval_log_{eval_id}_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(log_data, f, indent=2, default=str)
            mlflow.log_artifact(path, artifact_path="eval_logs")
        finally:
            os.unlink(path)

    async def on_sample_end(self, data: SampleEnd) -> None:
        eval_id = data.eval_id
        if eval_id not in self._task_runs:
            return

        # Increment sample counter
        sample_idx = self._sample_counts.get(eval_id, 0)
        self._sample_counts[eval_id] = sample_idx + 1

        sample = data.sample

        # Log per-sample scores as step metrics
        if sample.scores:
            for scorer_name, score in sample.scores.items():
                numeric = _score_to_numeric(score.value)
                if numeric is not None:
                    try:
                        mlflow.log_metric(
                            f"sample/{scorer_name}",
                            numeric,
                            step=sample_idx,
                        )
                    except Exception:
                        pass

        # Log sample timing
        if sample.total_time is not None:
            try:
                mlflow.log_metric(
                    "sample/total_time", sample.total_time, step=sample_idx
                )
            except Exception:
                pass

    async def on_sample_event(self, data: SampleEvent) -> None:
        eval_id = data.eval_id
        if eval_id not in self._task_runs:
            return

        # Initialize per-task event counters
        if eval_id not in self._event_counts:
            self._event_counts[eval_id] = {"model_calls": 0, "tool_calls": 0}

        event = data.event
        counters = self._event_counts[eval_id]

        if isinstance(event, ModelEvent):
            step = counters["model_calls"]
            counters["model_calls"] += 1
            try:
                mlflow.log_metric("event/model_call", step, step=step)
                if event.output and event.output.usage:
                    usage = event.output.usage
                    mlflow.log_metric(
                        "event/input_tokens", usage.input_tokens, step=step
                    )
                    mlflow.log_metric(
                        "event/output_tokens", usage.output_tokens, step=step
                    )
                if event.working_time is not None:
                    mlflow.log_metric(
                        "event/model_time", event.working_time, step=step
                    )
            except Exception:
                pass

        elif isinstance(event, ToolEvent):
            step = counters["tool_calls"]
            counters["tool_calls"] += 1
            try:
                mlflow.log_metric("event/tool_call", step, step=step)
                mlflow.log_param(
                    f"tool_call.{step}.function", event.function[:500]
                )
                if event.error:
                    mlflow.log_metric("event/tool_error", 1, step=step)
                if event.working_time is not None:
                    mlflow.log_metric(
                        "event/tool_time", event.working_time, step=step
                    )
            except Exception:
                pass

    async def on_model_usage(self, data: ModelUsageData) -> None:
        # Accumulate model usage for the current context
        model = data.model_name
        if model not in self._model_usage:
            self._model_usage[model] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_duration": 0.0,
            }

        stats = self._model_usage[model]
        stats["calls"] += 1
        stats["input_tokens"] += data.usage.input_tokens
        stats["output_tokens"] += data.usage.output_tokens
        stats["total_tokens"] += data.usage.total_tokens
        stats["total_duration"] += data.call_duration
