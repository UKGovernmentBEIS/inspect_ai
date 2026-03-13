"""Tests for the MLflow tracking hook."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inspect_ai.hooks._hooks import (
    ModelUsageData,
    RunEnd,
    RunStart,
    SampleEnd,
    SampleEvent,
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


def _make_eval_spec(
    task: str = "test_task",
    model: str = "openai/gpt-4",
    eval_id: str = "eval-001",
    run_id: str = "run-001",
) -> EvalSpec:
    return EvalSpec(
        eval_id=eval_id,
        run_id=run_id,
        created="2026-03-06T00:00:00Z",
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
def mlflow_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "test-experiment")


def test_enabled_requires_tracking_uri(monkeypatch: pytest.MonkeyPatch):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    assert hook.enabled() is False

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    assert hook.enabled() is True


@pytest.mark.anyio
async def test_run_lifecycle(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    mock_run = MagicMock()
    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = mock_run

        await hook.on_run_start(
            RunStart(
                eval_set_id=None,
                run_id="run-abc123",
                task_names=["task_a", "task_b"],
            )
        )

        mock_mlflow.set_experiment.assert_called_once_with("test-experiment")
        mock_mlflow.start_run.assert_called_once()
        start_kwargs = mock_mlflow.start_run.call_args
        assert "inspect-run-abc1" in start_kwargs.kwargs["run_name"]
        assert start_kwargs.kwargs["tags"]["inspect.run_id"] == "run-abc123"

        await hook.on_run_end(
            RunEnd(
                eval_set_id=None,
                run_id="run-abc123",
                exception=None,
                logs=[],
            )
        )

        mock_mlflow.end_run.assert_called_with(status="FINISHED")


@pytest.mark.anyio
async def test_run_end_with_exception(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-fail", task_names=["task_a"])
        )

        await hook.on_run_end(
            RunEnd(
                eval_set_id=None,
                run_id="run-fail",
                exception=RuntimeError("boom"),
                logs=[],
            )
        )

        mock_mlflow.end_run.assert_called_with(status="FAILED")


@pytest.mark.anyio
async def test_task_lifecycle(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )

        await hook.on_task_start(
            TaskStart(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                spec=spec,
            )
        )

        assert mock_mlflow.start_run.call_count == 2
        nested_call = mock_mlflow.start_run.call_args_list[1]
        assert nested_call.kwargs["nested"] is True
        assert nested_call.kwargs["run_name"] == "test_task"

        mock_mlflow.log_param.assert_any_call("task", "test_task")
        mock_mlflow.log_param.assert_any_call("model", "openai/gpt-4")

        results = EvalResults(
            total_samples=10,
            completed_samples=10,
            scores=[
                EvalScore(
                    name="accuracy",
                    scorer="accuracy",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.85)},
                )
            ],
        )
        log = EvalLog(
            eval=spec,
            status="success",
            results=results,
            stats=EvalStats(
                started_at="2026-03-06T00:00:00Z",
                completed_at="2026-03-06T00:01:00Z",
                model_usage={
                    "openai/gpt-4": ModelUsage(
                        input_tokens=5000, output_tokens=1000, total_tokens=6000
                    )
                },
            ),
        )
        await hook.on_task_end(
            TaskEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                log=log,
            )
        )

        mock_mlflow.log_metric.assert_any_call("accuracy/accuracy", 0.85)
        mock_mlflow.log_metric.assert_any_call("total_samples", 10)
        mock_mlflow.log_metric.assert_any_call("completed_samples", 10)
        mock_mlflow.log_metric.assert_any_call(
            "usage/openai/gpt-4/input_tokens", 5000
        )
        mock_mlflow.log_metric.assert_any_call(
            "usage/openai/gpt-4/output_tokens", 1000
        )
        mock_mlflow.end_run.assert_called_with(status="FINISHED")


@pytest.mark.anyio
async def test_sample_scores_logged_as_step_metrics(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        sample_0 = _make_sample(
            sample_id=1,
            scores={"accuracy": Score(value=1.0)},
            total_time=2.0,
        )
        await hook.on_sample_end(
            SampleEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-0",
                sample=sample_0,
            )
        )

        mock_mlflow.log_metric.assert_any_call("sample/accuracy", 1.0, step=0)
        mock_mlflow.log_metric.assert_any_call("sample/total_time", 2.0, step=0)

        sample_1 = _make_sample(
            sample_id=2,
            scores={"accuracy": Score(value=0.0)},
            total_time=1.0,
        )
        await hook.on_sample_end(
            SampleEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-1",
                sample=sample_1,
            )
        )

        mock_mlflow.log_metric.assert_any_call("sample/accuracy", 0.0, step=1)
        mock_mlflow.log_metric.assert_any_call("sample/total_time", 1.0, step=1)


def test_score_to_numeric_conversion():
    from examples.hooks.mlflow_tracking import _score_to_numeric

    assert _score_to_numeric(0.85) == 0.85
    assert _score_to_numeric(1) == 1.0
    assert _score_to_numeric("C") == 1.0
    assert _score_to_numeric("I") == 0.0
    assert _score_to_numeric("correct") == 1.0
    assert _score_to_numeric("incorrect") == 0.0
    assert _score_to_numeric("unknown_value") is None
    assert _score_to_numeric(None) is None


@pytest.mark.anyio
async def test_model_usage_accumulation():
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    await hook.on_model_usage(
        ModelUsageData(
            model_name="gpt-4",
            usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            call_duration=0.5,
        )
    )
    await hook.on_model_usage(
        ModelUsageData(
            model_name="gpt-4",
            usage=ModelUsage(input_tokens=200, output_tokens=100, total_tokens=300),
            call_duration=1.0,
        )
    )

    assert hook._model_usage["gpt-4"]["calls"] == 2
    assert hook._model_usage["gpt-4"]["input_tokens"] == 300
    assert hook._model_usage["gpt-4"]["output_tokens"] == 150
    assert hook._model_usage["gpt-4"]["total_tokens"] == 450
    assert hook._model_usage["gpt-4"]["total_duration"] == 1.5


@pytest.mark.anyio
async def test_sample_without_active_task_is_ignored():
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    sample = _make_sample(scores={"accuracy": Score(value=1.0)})

    await hook.on_sample_end(
        SampleEnd(
            eval_set_id=None,
            run_id="run-001",
            eval_id="eval-999",
            sample_id="sample-0",
            sample=sample,
        )
    )


@pytest.mark.anyio
async def test_sample_event_model_call(mlflow_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput, ModelUsage

    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        model_event = ModelEvent(
            model="openai/gpt-4",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(
                usage=ModelUsage(
                    input_tokens=150, output_tokens=50, total_tokens=200
                )
            ),
            working_time=0.8,
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-0",
                event=model_event,
            )
        )

        mock_mlflow.log_metric.assert_any_call("event/model_call", 0, step=0)
        mock_mlflow.log_metric.assert_any_call("event/input_tokens", 150, step=0)
        mock_mlflow.log_metric.assert_any_call("event/output_tokens", 50, step=0)
        mock_mlflow.log_metric.assert_any_call("event/model_time", 0.8, step=0)

        assert hook._event_counts["eval-001"]["model_calls"] == 1


@pytest.mark.anyio
async def test_sample_event_tool_call(mlflow_env):
    from inspect_ai.event._tool import ToolEvent

    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        tool_event = ToolEvent(
            id="call-001",
            function="web_search",
            arguments={"query": "test"},
            working_time=1.2,
        )

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-0",
                event=tool_event,
            )
        )

        mock_mlflow.log_metric.assert_any_call("event/tool_call", 0, step=0)
        mock_mlflow.log_param.assert_any_call("tool_call.0.function", "web_search")
        mock_mlflow.log_metric.assert_any_call("event/tool_time", 1.2, step=0)

        assert hook._event_counts["eval-001"]["tool_calls"] == 1


@pytest.mark.anyio
async def test_sample_event_without_active_task_is_ignored():
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()

    model_event = ModelEvent(
        model="openai/gpt-4",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(),
    )

    # Should not raise even with no active task
    await hook.on_sample_event(
        SampleEvent(
            eval_set_id=None,
            run_id="run-001",
            eval_id="eval-999",
            sample_id="sample-0",
            event=model_event,
        )
    )

    assert "eval-999" not in hook._event_counts


@pytest.mark.anyio
async def test_event_counts_logged_on_task_end(mlflow_env):
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        # Send 2 model events and 1 tool event
        for _ in range(2):
            await hook.on_sample_event(
                SampleEvent(
                    eval_set_id=None,
                    run_id="run-001",
                    eval_id="eval-001",
                    sample_id="sample-0",
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

        await hook.on_sample_event(
            SampleEvent(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                sample_id="sample-0",
                event=ToolEvent(
                    id="call-001",
                    function="bash",
                    arguments={"cmd": "ls"},
                ),
            )
        )

        log = EvalLog(
            eval=spec,
            status="success",
            results=EvalResults(total_samples=1, completed_samples=1),
            stats=EvalStats(
                started_at="2026-03-06T00:00:00Z",
                completed_at="2026-03-06T00:01:00Z",
            ),
        )

        await hook.on_task_end(
            TaskEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                log=log,
            )
        )

        mock_mlflow.log_metric.assert_any_call("total_model_calls", 2)
        mock_mlflow.log_metric.assert_any_call("total_tool_calls", 1)

        # Event counts cleaned up after task end
        assert "eval-001" not in hook._event_counts


@pytest.mark.anyio
async def test_artifact_logging_sample_table(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        samples = [
            _make_sample(
                sample_id=1,
                scores={"accuracy": Score(value=1.0, explanation="Correct")},
                total_time=1.5,
            ),
            _make_sample(
                sample_id=2,
                scores={"accuracy": Score(value=0.0, explanation="Wrong")},
                total_time=2.0,
            ),
        ]
        results = EvalResults(
            total_samples=2,
            completed_samples=2,
            scores=[
                EvalScore(
                    name="accuracy",
                    scorer="accuracy",
                    metrics={"accuracy": EvalMetric(name="accuracy", value=0.5)},
                )
            ],
        )
        log = EvalLog(
            eval=spec,
            status="success",
            results=results,
            stats=EvalStats(
                started_at="2026-03-06T00:00:00Z",
                completed_at="2026-03-06T00:01:00Z",
            ),
            samples=samples,
        )

        await hook.on_task_end(
            TaskEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                log=log,
            )
        )

        # Should have 2 log_artifact calls: sample_results + eval_logs
        artifact_calls = mock_mlflow.log_artifact.call_args_list
        assert len(artifact_calls) == 2

        artifact_paths = [call.kwargs.get("artifact_path") or call.args[1] for call in artifact_calls]
        assert "sample_results" in artifact_paths
        assert "eval_logs" in artifact_paths


@pytest.mark.anyio
async def test_artifact_logging_disabled(mlflow_env, monkeypatch: pytest.MonkeyPatch):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    monkeypatch.setenv("MLFLOW_INSPECT_LOG_ARTIFACTS", "false")

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        log = EvalLog(
            eval=spec,
            status="success",
            results=EvalResults(total_samples=1, completed_samples=1),
            stats=EvalStats(
                started_at="2026-03-06T00:00:00Z",
                completed_at="2026-03-06T00:01:00Z",
            ),
            samples=[_make_sample(scores={"accuracy": Score(value=1.0)})],
        )

        await hook.on_task_end(
            TaskEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                log=log,
            )
        )

        # log_artifact should NOT be called when disabled
        mock_mlflow.log_artifact.assert_not_called()


@pytest.mark.anyio
async def test_artifact_logging_no_samples(mlflow_env):
    from examples.hooks.mlflow_tracking import MlflowTrackingHooks

    hook = MlflowTrackingHooks()
    spec = _make_eval_spec()

    with patch("examples.hooks.mlflow_tracking.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value = MagicMock()

        await hook.on_run_start(
            RunStart(eval_set_id=None, run_id="run-001", task_names=["test_task"])
        )
        await hook.on_task_start(
            TaskStart(
                eval_set_id=None, run_id="run-001", eval_id="eval-001", spec=spec
            )
        )

        log = EvalLog(
            eval=spec,
            status="success",
            results=EvalResults(total_samples=0, completed_samples=0),
            stats=EvalStats(
                started_at="2026-03-06T00:00:00Z",
                completed_at="2026-03-06T00:01:00Z",
            ),
        )

        await hook.on_task_end(
            TaskEnd(
                eval_set_id=None,
                run_id="run-001",
                eval_id="eval-001",
                log=log,
            )
        )

        # Only eval_logs artifact (no sample_results since no samples)
        artifact_calls = mock_mlflow.log_artifact.call_args_list
        assert len(artifact_calls) == 1
        artifact_path = artifact_calls[0].kwargs.get("artifact_path") or artifact_calls[0].args[1]
        assert artifact_path == "eval_logs"
