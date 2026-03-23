"""MLflow Tracing hook for Inspect AI.

Maps evaluation execution flow to MLflow trace spans, giving users the
MLflow trace UI for debugging why a particular sample scored the way it did.

Creates a span tree mirroring the eval hierarchy:

    eval_run (root)
      task: math_reasoning (CHAIN)
        sample: q1 (CHAIN)
          model_call: gpt-4o (LLM) - 847 tokens, 1.2s
          tool_call: calculator (TOOL) - args: {"expr": "2+2"}, result: 4
          score: accuracy (EVALUATOR) - value: C

To enable, set MLFLOW_TRACKING_URI and MLFLOW_INSPECT_TRACING:

    export MLFLOW_TRACKING_URI="http://localhost:5000"
    export MLFLOW_INSPECT_TRACING="true"

Then import this module before running evals:

    from examples.hooks.mlflow_tracing import MlflowTracingHooks  # noqa: F401

    inspect eval my_task.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

import mlflow  # type: ignore[import-not-found]

from inspect_ai.event._model import ModelEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.hooks import (
    Hooks,
    RunEnd,
    RunStart,
    SampleEnd,
    SampleEvent,
    SampleStart,
    TaskEnd,
    TaskStart,
    hooks,
)

logger = logging.getLogger(__name__)


def _truncate(text: Any, max_len: int = 200) -> str:
    s = str(text) if text is not None else ""
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


@hooks(name="mlflow_tracing", description="MLflow Tracing")
class MlflowTracingHooks(Hooks):
    """MLflow Tracing Hooks.

    Creates MLflow trace spans from Inspect AI evaluation events.
    Each eval run produces a trace with hierarchical spans for tasks,
    samples, model calls, tool calls, and scoring.
    """

    def __init__(self) -> None:
        self._run_spans: dict[str, Any] = {}  # run_id -> LiveSpan
        self._task_spans: dict[str, Any] = {}  # eval_id -> LiveSpan
        self._sample_spans: dict[str, Any] = {}  # sample_id -> LiveSpan
        self._inspect_spans: dict[str, Any] = {}  # inspect span_id -> LiveSpan

    def enabled(self) -> bool:
        return (
            os.getenv("MLFLOW_TRACKING_URI") is not None
            and os.getenv("MLFLOW_INSPECT_TRACING", "").lower() == "true"
        )

    async def on_run_start(self, data: RunStart) -> None:
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "inspect_ai")
        mlflow.set_experiment(experiment_name)

        try:
            span = mlflow.start_span_no_context(
                name=f"eval_run:{data.run_id[:8]}",
                span_type="CHAIN",
                inputs={"task_names": data.task_names},
                attributes={
                    "inspect.run_id": data.run_id,
                    "inspect.task_count": len(data.task_names),
                },
            )
            self._run_spans[data.run_id] = span
        except Exception:
            logger.debug("Failed to start run span", exc_info=True)

    async def on_run_end(self, data: RunEnd) -> None:
        span = self._run_spans.pop(data.run_id, None)
        if span is None:
            return

        try:
            status = "ERROR" if data.exception else "OK"
            outputs = {"status": status}
            if data.exception:
                span.record_exception(data.exception)
                outputs["error"] = str(data.exception)
            span.end(outputs=outputs, status=status)
        except Exception:
            logger.debug("Failed to end run span", exc_info=True)

        self._task_spans.clear()
        self._sample_spans.clear()
        self._inspect_spans.clear()

    async def on_task_start(self, data: TaskStart) -> None:
        parent = self._run_spans.get(data.run_id)
        if parent is None:
            return

        try:
            span = mlflow.start_span_no_context(
                name=f"task:{data.spec.task}",
                span_type="CHAIN",
                parent_span=parent,
                inputs={
                    "task": data.spec.task,
                    "model": data.spec.model,
                    "dataset": data.spec.dataset.name or "",
                },
                attributes={
                    "inspect.eval_id": data.eval_id,
                    "inspect.task": data.spec.task,
                    "inspect.model": data.spec.model,
                },
            )
            self._task_spans[data.eval_id] = span
        except Exception:
            logger.debug("Failed to start task span", exc_info=True)

    async def on_task_end(self, data: TaskEnd) -> None:
        span = self._task_spans.pop(data.eval_id, None)
        if span is None:
            return

        try:
            log = data.log
            outputs: dict[str, Any] = {"status": log.status}

            if log.results and log.results.scores:
                scores = {}
                for eval_score in log.results.scores:
                    for metric_name, metric in eval_score.metrics.items():
                        scores[f"{eval_score.name}/{metric_name}"] = metric.value
                outputs["scores"] = scores

            if log.results:
                outputs["total_samples"] = log.results.total_samples
                outputs["completed_samples"] = log.results.completed_samples

            status = "OK" if log.status == "success" else "ERROR"
            span.end(outputs=outputs, status=status)
        except Exception:
            logger.debug("Failed to end task span", exc_info=True)

    async def on_sample_start(self, data: SampleStart) -> None:
        parent = self._task_spans.get(data.eval_id)
        if parent is None:
            return

        try:
            span = mlflow.start_span_no_context(
                name=f"sample:{data.sample_id[:8]}",
                span_type="CHAIN",
                parent_span=parent,
                inputs={"sample_id": data.sample_id},
                attributes={
                    "inspect.sample_id": data.sample_id,
                    "inspect.eval_id": data.eval_id,
                },
            )
            self._sample_spans[data.sample_id] = span
        except Exception:
            logger.debug("Failed to start sample span", exc_info=True)

    async def on_sample_end(self, data: SampleEnd) -> None:
        span = self._sample_spans.pop(data.sample_id, None)
        if span is None:
            return

        try:
            sample = data.sample
            outputs: dict[str, Any] = {}

            if sample.scores:
                outputs["scores"] = {
                    name: score.value for name, score in sample.scores.items()
                }

            if sample.total_time is not None:
                outputs["total_time"] = sample.total_time

            if sample.output and sample.output.choices:
                first = sample.output.choices[0]
                outputs["output"] = _truncate(first.message.text, 500)

            has_error = getattr(sample, "error", None) is not None
            status = "ERROR" if has_error else "OK"
            if has_error:
                span.record_exception(str(sample.error))

            span.end(outputs=outputs, status=status)
        except Exception:
            logger.debug("Failed to end sample span", exc_info=True)

    async def on_sample_event(self, data: SampleEvent) -> None:
        sample_span = self._sample_spans.get(data.sample_id)
        if sample_span is None:
            return

        event = data.event

        try:
            if isinstance(event, SpanBeginEvent):
                self._handle_span_begin(event, sample_span)
            elif isinstance(event, SpanEndEvent):
                self._handle_span_end(event)
            elif isinstance(event, ModelEvent):
                self._handle_model_event(event, sample_span)
            elif isinstance(event, ToolEvent):
                self._handle_tool_event(event, sample_span)
            elif isinstance(event, ScoreEvent):
                self._handle_score_event(event, sample_span)
        except Exception:
            logger.debug("Failed to handle sample event", exc_info=True)

    def _handle_span_begin(self, event: SpanBeginEvent, sample_span: Any) -> None:
        parent = sample_span
        if event.parent_id and event.parent_id in self._inspect_spans:
            parent = self._inspect_spans[event.parent_id]

        span = mlflow.start_span_no_context(
            name=event.name,
            span_type=event.type or "UNKNOWN",
            parent_span=parent,
            attributes={"inspect.span_id": event.id},
        )
        self._inspect_spans[event.id] = span

    def _handle_span_end(self, event: SpanEndEvent) -> None:
        span = self._inspect_spans.pop(event.id, None)
        if span is not None:
            span.end(status="OK")

    def _handle_model_event(self, event: ModelEvent, sample_span: Any) -> None:
        parent = sample_span
        if event.span_id and event.span_id in self._inspect_spans:
            parent = self._inspect_spans[event.span_id]

        attrs: dict[str, Any] = {"inspect.model": event.model}
        inputs: dict[str, Any] = {"model": event.model}
        outputs: dict[str, Any] = {}

        if event.config:
            if event.config.temperature is not None:
                attrs["temperature"] = event.config.temperature
            if event.config.max_tokens is not None:
                attrs["max_tokens"] = event.config.max_tokens

        if event.output and event.output.usage:
            usage = event.output.usage
            attrs["input_tokens"] = usage.input_tokens
            attrs["output_tokens"] = usage.output_tokens
            attrs["total_tokens"] = usage.total_tokens
            outputs["tokens"] = {
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "total": usage.total_tokens,
            }

        if event.working_time is not None:
            attrs["working_time"] = event.working_time

        if event.cache:
            attrs["cache"] = event.cache

        if event.input:
            inputs["messages"] = len(event.input)

        if event.output and event.output.choices:
            first = event.output.choices[0]
            outputs["response"] = _truncate(first.message.text, 500)

        span = mlflow.start_span_no_context(
            name=f"model:{event.model}",
            span_type="LLM",
            parent_span=parent,
            inputs=inputs,
            attributes=attrs,
        )

        status = "ERROR" if event.error else "OK"
        if event.error:
            span.record_exception(event.error)
        span.end(outputs=outputs, status=status)

    def _handle_tool_event(self, event: ToolEvent, sample_span: Any) -> None:
        parent = sample_span
        if event.span_id and event.span_id in self._inspect_spans:
            parent = self._inspect_spans[event.span_id]

        inputs: dict[str, Any] = {
            "function": event.function,
            "arguments": event.arguments,
        }
        outputs: dict[str, Any] = {}
        attrs: dict[str, Any] = {"inspect.tool_id": event.id}

        if event.result is not None:
            outputs["result"] = _truncate(event.result, 500)

        if event.working_time is not None:
            attrs["working_time"] = event.working_time

        span = mlflow.start_span_no_context(
            name=f"tool:{event.function}",
            span_type="TOOL",
            parent_span=parent,
            inputs=inputs,
            attributes=attrs,
        )

        has_error = event.error is not None or event.failed
        status = "ERROR" if has_error else "OK"
        if event.error:
            span.record_exception(str(event.error))
        span.end(outputs=outputs, status=status)

    def _handle_score_event(self, event: ScoreEvent, sample_span: Any) -> None:
        parent = sample_span
        if event.span_id and event.span_id in self._inspect_spans:
            parent = self._inspect_spans[event.span_id]

        inputs: dict[str, Any] = {}
        if event.target:
            inputs["target"] = _truncate(event.target, 200)

        outputs: dict[str, Any] = {"value": event.score.value}
        if event.score.explanation:
            outputs["explanation"] = _truncate(event.score.explanation, 500)

        attrs: dict[str, Any] = {"intermediate": event.intermediate}

        span = mlflow.start_span_no_context(
            name="score",
            span_type="EVALUATOR",
            parent_span=parent,
            inputs=inputs,
            attributes=attrs,
        )
        span.end(outputs=outputs, status="OK")
