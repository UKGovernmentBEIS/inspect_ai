"""Tests for the MLflow tracing hook."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inspect_ai.hooks._hooks import (
    RunEnd,
    RunStart,
    SampleEnd,
    SampleEvent,
    SampleStart,
    TaskEnd,
    TaskStart,
)
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalMetric,
    EvalResults,
    EvalSample,
    EvalScore,
    EvalSpec,
    EvalStats,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.scorer._metric import Score

_mlflow_was_mocked = "mlflow" not in sys.modules
if _mlflow_was_mocked:
    _mock = MagicMock()
    _mock.__spec__ = None
    sys.modules["mlflow"] = _mock


def _load_mlflow_tracing():
    module_path = Path(__file__).parents[2] / "examples" / "hooks" / "mlflow_tracing.py"
    spec = importlib.util.spec_from_file_location("mlflow_tracing", module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tracing_mod = _load_mlflow_tracing()
MlflowTracingHooks = _tracing_mod.MlflowTracingHooks

if _mlflow_was_mocked:
    del sys.modules["mlflow"]


@pytest.fixture(autouse=True)
def _mock_mlflow_in_sys_modules():
    installed = "mlflow" not in sys.modules
    if installed:
        sys.modules["mlflow"] = MagicMock()
    yield
    if installed:
        sys.modules.pop("mlflow", None)


def _make_eval_spec(
    task: str = "test_task",
    model: str = "openai/gpt-4",
    eval_id: str = "eval-001",
    run_id: str = "run-001",
) -> EvalSpec:
    return EvalSpec(
        eval_id=eval_id,
        run_id=run_id,
        created="2026-03-20T00:00:00Z",
        task=task,
        model=model,
        dataset=EvalDataset(name="test_dataset", location="test.jsonl"),
        config=EvalConfig(),
    )


def _make_sample(
    sample_id: int = 1,
    scores: dict[str, Score] | None = None,
    total_time: float = 1.5,
) -> EvalSample:
    return EvalSample(
        id=sample_id,
        epoch=1,
        input="What is 2+2?",
        target="4",
        output=ModelOutput(),
        scores=scores,
        total_time=total_time,
    )


@pytest.fixture
def tracing_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setenv("MLFLOW_INSPECT_TRACING", "true")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "test-experiment")


def test_enabled_requires_both_env_vars(monkeypatch: pytest.MonkeyPatch):
    hook = MlflowTracingHooks()

    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_INSPECT_TRACING", raising=False)
    assert hook.enabled() is False

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    assert hook.enabled() is False

    monkeypatch.setenv("MLFLOW_INSPECT_TRACING", "true")
    assert hook.enabled() is True


def test_enabled_case_insensitive(monkeypatch: pytest.MonkeyPatch):
    hook = MlflowTracingHooks()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")

    monkeypatch.setenv("MLFLOW_INSPECT_TRACING", "TRUE")
    assert hook.enabled() is True

    monkeypatch.setenv("MLFLOW_INSPECT_TRACING", "True")
    assert hook.enabled() is True

    monkeypatch.setenv("MLFLOW_INSPECT_TRACING", "false")
    assert hook.enabled() is False


@pytest.mark.anyio
async def test_run_lifecycle_creates_and_ends_span(tracing_env):
    hook = MlflowTracingHooks()
    mock_span = MagicMock()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.return_value = mock_span

        await hook.on_run_start(
            RunStart(
                eval_set_id=None,
                run_id="run-abc123",
                task_names=["task_a", "task_b"],
            )
        )

        mock_mlflow.set_experiment.assert_called_once_with("test-experiment")
        mock_mlflow.start_span_no_context.assert_called_once()
        span_kwargs = mock_mlflow.start_span_no_context.call_args
        assert "eval_run:" in span_kwargs.kwargs["name"]
        assert span_kwargs.kwargs["span_type"] == "CHAIN"
        assert span_kwargs.kwargs["inputs"]["task_names"] == ["task_a", "task_b"]

        await hook.on_run_end(
            RunEnd(
                eval_set_id=None,
                run_id="run-abc123",
                exception=None,
                logs=[],
            )
        )

        mock_span.end.assert_called_once()
        end_kwargs = mock_span.end.call_args.kwargs
        assert end_kwargs["status"] == "OK"
        assert end_kwargs["outputs"]["status"] == "OK"


@pytest.mark.anyio
async def test_run_end_with_exception_records_error(tracing_env):
    hook = MlflowTracingHooks()
    mock_span = MagicMock()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.return_value = mock_span

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-fail", task_names=["t"])
        )
        await hook.on_run_end(
            RunEnd(
                eval_set_id=None,
                run_id="run-fail",
                exception=RuntimeError("boom"),
                logs=[],
            )
        )

        mock_span.record_exception.assert_called_once()
        mock_span.end.assert_called_once()
        assert mock_span.end.call_args.kwargs["status"] == "ERROR"


@pytest.mark.anyio
async def test_task_span_nested_under_run(tracing_env):
    hook = MlflowTracingHooks()
    run_span = MagicMock(name="run_span")
    task_span = MagicMock(name="task_span")
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [run_span, task_span]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )

        assert mock_mlflow.start_span_no_context.call_count == 2
        task_call = mock_mlflow.start_span_no_context.call_args_list[1]
        assert task_call.kwargs["parent_span"] is run_span
        assert task_call.kwargs["span_type"] == "CHAIN"
        assert "task:test_task" in task_call.kwargs["name"]


@pytest.mark.anyio
async def test_task_end_logs_scores_and_closes_span(tracing_env):
    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [run_span, task_span]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )

        log = EvalLog(
            eval=spec,
            status="success",
            results=EvalResults(
                total_samples=5,
                completed_samples=5,
                scores=[
                    EvalScore(
                        name="accuracy",
                        scorer="accuracy",
                        metrics={"accuracy": EvalMetric(name="accuracy", value=0.8)},
                    )
                ],
            ),
            stats=EvalStats(
                started_at="2026-03-20T00:00:00Z",
                completed_at="2026-03-20T00:01:00Z",
            ),
        )

        await hook.on_task_end(
            TaskEnd(eval_set_id=None, run_id="run-001", eval_id="eval-001", log=log)
        )

        task_span.end.assert_called_once()
        end_kwargs = task_span.end.call_args.kwargs
        assert end_kwargs["status"] == "OK"
        assert end_kwargs["outputs"]["scores"]["accuracy/accuracy"] == 0.8
        assert end_kwargs["outputs"]["total_samples"] == 5


@pytest.mark.anyio
async def test_sample_span_nested_under_task(tracing_env):
    hook = MlflowTracingHooks()
    run_span = MagicMock(name="run_span")
    task_span = MagicMock(name="task_span")
    sample_span = MagicMock(name="sample_span")
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-abc12345",
                summary=MagicMock(),
            )
        )

        assert mock_mlflow.start_span_no_context.call_count == 3
        sample_call = mock_mlflow.start_span_no_context.call_args_list[2]
        assert sample_call.kwargs["parent_span"] is task_span
        assert sample_call.kwargs["span_type"] == "CHAIN"


@pytest.mark.anyio
async def test_sample_end_logs_scores_and_output(tracing_env):
    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-001",
                summary=MagicMock(),
            )
        )

        sample = _make_sample(scores={"accuracy": Score(value=1.0)}, total_time=2.5)
        await hook.on_sample_end(
            SampleEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-001",
                sample=sample,
            )
        )

        sample_span.end.assert_called_once()
        end_kwargs = sample_span.end.call_args.kwargs
        assert end_kwargs["status"] == "OK"
        assert end_kwargs["outputs"]["scores"]["accuracy"] == 1.0
        assert end_kwargs["outputs"]["total_time"] == 2.5


@pytest.mark.anyio
async def test_model_event_creates_llm_span(tracing_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    model_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            model_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        model_event = ModelEvent(
            model="openai/gpt-4o",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(temperature=0.7),
            output=ModelOutput(
                usage=ModelUsage(input_tokens=150, output_tokens=50, total_tokens=200)
            ),
            working_time=0.8,
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=model_event,
            )
        )

        assert mock_mlflow.start_span_no_context.call_count == 4
        model_call = mock_mlflow.start_span_no_context.call_args_list[3]
        assert model_call.kwargs["span_type"] == "LLM"
        assert model_call.kwargs["parent_span"] is sample_span
        assert model_call.kwargs["attributes"]["input_tokens"] == 150
        assert model_call.kwargs["attributes"]["output_tokens"] == 50
        assert model_call.kwargs["attributes"]["working_time"] == 0.8
        assert model_call.kwargs["attributes"]["temperature"] == 0.7

        model_span.end.assert_called_once()
        assert model_span.end.call_args.kwargs["status"] == "OK"


@pytest.mark.anyio
async def test_tool_event_creates_tool_span(tracing_env):
    from inspect_ai.event._tool import ToolEvent

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    tool_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            tool_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        tool_event = ToolEvent(
            id="call-001",
            function="web_search",
            arguments={"query": "capital of France"},
            result="Paris is the capital of France.",
            working_time=1.2,
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=tool_event,
            )
        )

        assert mock_mlflow.start_span_no_context.call_count == 4
        tool_call = mock_mlflow.start_span_no_context.call_args_list[3]
        assert tool_call.kwargs["span_type"] == "TOOL"
        assert tool_call.kwargs["parent_span"] is sample_span
        assert tool_call.kwargs["inputs"]["function"] == "web_search"
        assert tool_call.kwargs["inputs"]["arguments"] == {"query": "capital of France"}

        tool_span.end.assert_called_once()
        end_kwargs = tool_span.end.call_args.kwargs
        assert end_kwargs["status"] == "OK"
        assert "Paris" in end_kwargs["outputs"]["result"]


@pytest.mark.anyio
async def test_tool_event_with_error(tracing_env):
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.tool._tool_call import ToolCallError

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    tool_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            tool_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        tool_event = ToolEvent(
            id="call-err",
            function="bash",
            arguments={"command": "rm -rf /"},
            error=ToolCallError(message="Permission denied", type="PermissionError"),
            failed=True,
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=tool_event,
            )
        )

        tool_span.record_exception.assert_called_once()
        tool_span.end.assert_called_once()
        assert tool_span.end.call_args.kwargs["status"] == "ERROR"


@pytest.mark.anyio
async def test_score_event_creates_evaluator_span(tracing_env):
    from inspect_ai.event._score import ScoreEvent
    from inspect_ai.scorer._metric import Score

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    score_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            score_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        score_event = ScoreEvent(
            score=Score(value="C", explanation="Correct answer"),
            target="4",
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=score_event,
            )
        )

        assert mock_mlflow.start_span_no_context.call_count == 4
        score_call = mock_mlflow.start_span_no_context.call_args_list[3]
        assert score_call.kwargs["span_type"] == "EVALUATOR"
        assert score_call.kwargs["name"] == "score"

        score_span.end.assert_called_once()
        assert score_span.end.call_args.kwargs["outputs"]["value"] == "C"
        assert "Correct" in score_span.end.call_args.kwargs["outputs"]["explanation"]


@pytest.mark.anyio
async def test_span_begin_end_events_create_hierarchy(tracing_env):
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent

    hook = MlflowTracingHooks()
    run_span = MagicMock(name="run")
    task_span = MagicMock(name="task")
    sample_span = MagicMock(name="sample")
    solver_span = MagicMock(name="solver")
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            solver_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        # SpanBeginEvent with no parent -> parent is sample
        begin_event = SpanBeginEvent(
            id="span-solver-1",
            name="chain_of_thought",
            type="solver",
        )
        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=begin_event,
            )
        )

        solver_call = mock_mlflow.start_span_no_context.call_args_list[3]
        assert solver_call.kwargs["parent_span"] is sample_span
        assert solver_call.kwargs["name"] == "chain_of_thought"

        # SpanEndEvent closes the span
        end_event = SpanEndEvent(id="span-solver-1")
        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=end_event,
            )
        )

        solver_span.end.assert_called_once_with(status="OK")


@pytest.mark.anyio
async def test_nested_inspect_spans_preserve_hierarchy(tracing_env):
    from inspect_ai.event._span import SpanBeginEvent

    hook = MlflowTracingHooks()
    run_span = MagicMock(name="run")
    task_span = MagicMock(name="task")
    sample_span = MagicMock(name="sample")
    outer_span = MagicMock(name="outer")
    inner_span = MagicMock(name="inner")
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            outer_span,
            inner_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        # Outer span
        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=SpanBeginEvent(id="span-outer", name="solver"),
            )
        )

        # Inner span with parent_id pointing to outer
        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=SpanBeginEvent(
                    id="span-inner", name="generate", parent_id="span-outer"
                ),
            )
        )

        inner_call = mock_mlflow.start_span_no_context.call_args_list[4]
        assert inner_call.kwargs["parent_span"] is outer_span


@pytest.mark.anyio
async def test_event_without_active_sample_is_ignored(tracing_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    hook = MlflowTracingHooks()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-999",
                sample_id="s-999",
                event=ModelEvent(
                    model="openai/gpt-4",
                    input=[],
                    tools=[],
                    tool_choice="auto",
                    config=GenerateConfig(),
                    output=ModelOutput(),
                ),
            )
        )

        mock_mlflow.start_span_no_context.assert_not_called()


@pytest.mark.anyio
async def test_sample_without_active_task_is_ignored(tracing_env):
    hook = MlflowTracingHooks()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-999",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        mock_mlflow.start_span_no_context.assert_not_called()


@pytest.mark.anyio
async def test_model_event_with_error(tracing_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    model_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            model_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        model_event = ModelEvent(
            model="openai/gpt-4",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
            error="Rate limit exceeded",
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=model_event,
            )
        )

        model_span.record_exception.assert_called_once_with("Rate limit exceeded")
        assert model_span.end.call_args.kwargs["status"] == "ERROR"


@pytest.mark.anyio
async def test_model_event_with_cache_hit(tracing_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    hook = MlflowTracingHooks()
    run_span = MagicMock()
    task_span = MagicMock()
    sample_span = MagicMock()
    model_span = MagicMock()
    spec = _make_eval_spec()

    with patch.object(_tracing_mod, "mlflow") as mock_mlflow:
        mock_mlflow.start_span_no_context.side_effect = [
            run_span,
            task_span,
            sample_span,
            model_span,
        ]

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["t"])
        )
        await hook.on_task_start(
            TaskStart(eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec)
        )
        await hook.on_sample_start(
            SampleStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                summary=MagicMock(),
            )
        )

        model_event = ModelEvent(
            model="openai/gpt-4",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
            cache="read",
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="s-001",
                event=model_event,
            )
        )

        model_call = mock_mlflow.start_span_no_context.call_args_list[3]
        assert model_call.kwargs["attributes"]["cache"] == "read"
