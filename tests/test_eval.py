import functools
import logging
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest import mock

import anyio
import pytest
from botocore.exceptions import ClientError

from inspect_ai import (
    Epochs,
    Task,
    TaskSource,
    eval,
    eval_async,
    eval_set,
    task,
    task_source,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._util._async import tg_collect
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


def test_eval_epochs_sample_count():
    task = Task(dataset=[Sample(input="s1"), Sample(input="s2")])
    log = eval(task, model="mockllm/model", epochs=3)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 6  # 2 samples * 3 epochs


def test_eval_sample_records_turn_count_and_token_limit_usage():
    from typing import Generator

    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util._limit import TokenLimit

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    @solver
    def generate_three_times():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            for _ in range(3):
                state.output = await model.generate("hi")
            return state

        return solve

    # an "output"-metered limit so token_limit_usage (metered output tokens)
    # is distinguishable from total tokens
    task = Task(
        dataset=[Sample(input="s1")],
        solver=generate_three_times(),
        token_limit=TokenLimit(tokens=1000, type="output"),
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # three top-level generate() calls -> three turns
    assert sample.turn_count == 3
    # output-metered usage is 3 turns * 5 output tokens (not the 45 total)
    assert sample.token_limit_usage == 15
    # the configured ceiling and metering type are persisted alongside
    assert sample.token_limit == 1000
    assert sample.token_limit_type == "output"
    # the summary carries the same values
    summary = sample.summary()
    assert summary.turn_count == 3
    assert summary.token_limit_usage == 15
    assert summary.token_limit == 1000
    assert summary.token_limit_type == "output"


def test_eval_sample_token_limit_fields_none_without_limit():
    task = Task(dataset=[Sample(input="s1")])
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # turns are counted regardless of configured limits
    assert sample.turn_count == 1
    # but token limit fields are None when no ceiling is configured
    assert sample.token_limit is None
    assert sample.token_limit_type is None
    assert sample.token_limit_usage is None
    # and so are the other per-sample limit ceilings
    assert sample.message_limit is None
    assert sample.time_limit is None


def test_eval_sample_records_message_and_time_limits():
    task = Task(
        dataset=[Sample(input="s1")],
        message_limit=10,
        time_limit=600,
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # the configured ceilings are persisted on the sample record
    assert sample.message_limit == 10
    assert sample.time_limit == 600
    # the summary carries the same values
    summary = sample.summary()
    assert summary.message_limit == 10
    assert summary.time_limit == 600


def test_dynamic_token_limit_updates_active_sample() -> None:
    from typing import Generator

    from inspect_ai.log._samples import sample_active
    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver

    observed: list[tuple[int | None, str | None, int | None]] = []

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    def observe() -> None:
        active = sample_active()
        assert active is not None
        observed.append(
            (active.token_limit, active.token_limit_type, active.token_limit_usage)
        )

    @solver
    def toggle_token_limit():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            state.output = await model.generate("hi")
            observe()  # unlimited: whole group is None
            state.token_limit = 1000
            observe()  # enabling pushes ceiling, type, and current metered usage
            state.token_limit = None
            observe()  # disabling clears the group again
            return state

        return solve

    task = Task(dataset=[Sample(input="s1")], solver=toggle_token_limit())
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"

    assert observed == [
        (None, None, None),
        (1000, "all", 15),
        (None, None, None),
    ]


def test_eval_sample_limit_values_reflect_final_retry_attempt() -> None:
    from typing import Generator

    from inspect_ai.model import get_model
    from inspect_ai.model._model_output import ModelOutput, ModelUsage
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util._limit import TokenLimit, token_limit_usage, turn_count

    attempts: list[int] = []
    live_values_attempt2: list[tuple[int | None, int | None]] = []

    def repeat_forever(
        output: ModelOutput,
    ) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    @solver
    def fail_then_succeed():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            output = ModelOutput.from_content("mockllm/model", "hello")
            output.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
            model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
            attempts.append(len(attempts) + 1)
            if attempts[-1] == 1:
                # attempt 1: 2 generates then error
                for _ in range(2):
                    state.output = await model.generate("hi")
                raise RuntimeError("boom")
            # attempt 2: 5 generates then succeed
            for _ in range(5):
                state.output = await model.generate("hi")
                live_values_attempt2.append((turn_count(), token_limit_usage()))
            return state

        return solve

    task = Task(
        dataset=[Sample(input="s1")],
        solver=fail_then_succeed(),
        token_limit=TokenLimit(tokens=100000, type="output"),
    )
    log = eval(task, model="mockllm/model", retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert attempts == [1, 2]

    # regression: attempt 1's limit snapshot must not leak into the retry --
    # live values advance during attempt 2 rather than freezing at (2, 10)
    assert live_values_attempt2 == [(1, 5), (2, 10), (3, 15), (4, 20), (5, 25)]
    # and the logged sample reflects the successful attempt, not attempt 1
    assert sample.turn_count == 5
    assert sample.token_limit_usage == 25


def _peak_model_concurrency(max_tasks: int | None) -> int:
    """Run one task against two models and return the peak concurrent models.

    A `record` solver brackets its work with enter/exit markers; the peak depth
    of overlapping enter/exit pairs is how many models ran at once.
    """
    from inspect_ai.solver import Generate, TaskState, solver

    events: list[str] = []

    @solver
    def record():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            events.append("enter")
            await anyio.sleep(0.2)
            events.append("exit")
            return state

        return solve

    task = Task(dataset=[Sample(input="x", target="y")], solver=[record()], name="t")
    eval(
        task,
        model=["mockllm/model", "mockllm/model2"],
        max_tasks=max_tasks,
        display="none",
    )

    depth = peak = 0
    for e in events:
        depth += 1 if e == "enter" else -1
        peak = max(peak, depth)
    return peak


def test_max_tasks_bounds_concurrent_models_single_task():
    # Regression for #4195: a single task definition fanned across models must
    # honor max_tasks. max_tasks=1 runs model-by-model; unset runs them all.
    assert _peak_model_concurrency(max_tasks=1) == 1
    assert _peak_model_concurrency(max_tasks=None) == 2


@pytest.mark.anyio
async def test_no_concurrent_eval_async():
    tasks = [
        Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
        for i in range(0, 2)
    ]

    with pytest.raises(RuntimeError):
        await tg_collect(
            [
                functools.partial(eval_async, task, model="mockllm/model")
                for task in tasks
            ]
        )


def test_eval_config_override():
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        message_limit=10,
        epochs=Epochs(2, "at_least_1"),
        fail_on_error=True,
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model")[0]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["at_least_1"]
    assert log.eval.config.fail_on_error is True

    log = eval(
        deepcopy(task),
        message_limit=5,
        epochs=Epochs(5, "at_least_3"),
        fail_on_error=0.5,
        model="mockllm/model",
    )[0]
    assert log.eval.config.message_limit == 5
    assert log.eval.config.epochs == 5
    assert log.eval.config.epochs_reducer == ["at_least_3"]
    assert log.eval.config.fail_on_error == 0.5


def test_eval_config_overrides_do_not_mutate_reused_task():
    from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
    from inspect_ai.model._model_info import clear_model_info_cache, set_model_info

    set_model_info(
        "mockllm/model",
        ModelInfo(
            cost=ModelCost(
                input=1.0,
                output=1.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    task = Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())

    try:
        log = eval(
            task,
            model="mockllm/model",
            epochs=Epochs(2, "mean"),
            message_limit=10,
            token_limit=500,
            turn_limit=3,
            time_limit=60,
            working_limit=60,
            cost_limit=5.0,
            fail_on_error=False,
            continue_on_fail=True,
            score_on_error=True,
        )[0]
    finally:
        clear_model_info_cache()

    assert log.eval.config.epochs == 2
    assert log.eval.config.epochs_reducer == ["mean"]
    assert log.eval.config.message_limit == 10
    assert log.eval.config.token_limit == 500
    assert log.eval.config.turn_limit == 3
    assert log.eval.config.time_limit == 60
    assert log.eval.config.working_limit == 60
    assert log.eval.config.cost_limit == 5.0
    assert log.eval.config.fail_on_error is False
    assert log.eval.config.continue_on_fail is True
    assert log.eval.config.score_on_error is True

    assert task.epochs is None
    assert task.epochs_reducer is None
    assert task.message_limit is None
    assert task.token_limit is None
    assert task.token_limit_type is None
    assert task.turn_limit is None
    assert task.time_limit is None
    assert task.working_limit is None
    assert task.cost_limit is None
    assert task.fail_on_error is None
    assert task.continue_on_fail is None
    assert task.score_on_error is None

    followup = eval(task, model="mockllm/model")[0]
    assert followup.eval.config.epochs == 1
    assert followup.eval.config.epochs_reducer is None
    assert followup.eval.config.message_limit is None
    assert followup.eval.config.token_limit is None
    assert followup.eval.config.token_limit_type is None
    assert followup.eval.config.turn_limit is None
    assert followup.eval.config.time_limit is None
    assert followup.eval.config.working_limit is None
    assert followup.eval.config.cost_limit is None
    assert followup.eval.config.fail_on_error is True
    assert followup.eval.config.continue_on_fail is False
    assert followup.eval.config.score_on_error is False


def test_eval_level_message_limit_not_reused_by_task_object():
    from inspect_ai.solver import Generate, TaskState, solver

    @solver
    def two_generates():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await generate(state)
            state.messages.append(state.user_prompt)
            return await generate(state)

        return solve

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[two_generates()],
        scorer=match(numeric=True),
    )

    limited = eval(task, model="mockllm/model", message_limit=1, fail_on_error=False)[0]
    assert limited.samples is not None
    assert limited.samples[0].limit is not None
    assert limited.samples[0].limit.type == "message"
    assert task.message_limit is None

    followup = eval(task, model="mockllm/model")[0]
    assert followup.eval.config.message_limit is None
    assert followup.samples is not None
    assert followup.samples[0].limit is None


def test_eval_approval_override():
    eval_approval = ApprovalPolicyConfig(
        approvers=[
            ApproverPolicyConfig(name="human", tools="human_tool"),
            ApproverPolicyConfig(name="auto", tools="auto_tool"),
        ]
    )
    task = Task(dataset=[Sample(input="Say Hello", target="Hello")], approval="auto")
    log = eval(
        deepcopy(task),
        model="mockllm/model",
        approval=eval_approval,
    )[0]
    assert log.eval.config.approval == eval_approval


def test_eval_sandbox_init_when_first_task_has_no_sandbox():
    """Check that Sandbox initialization runs when ANY task has a sandbox, not just the first.

    Startup is asserted via a spy rather than a docker task whose init
    crashes when skipped: a local sandbox keeps the regression coverage
    (the gating logic is sandbox-type agnostic) without docker's ~40s of
    container lifecycle in CI.
    """
    from inspect_ai._eval.run import SandboxManager

    with mock.patch.object(
        SandboxManager, "start", autospec=True, side_effect=SandboxManager.start
    ) as start_spy:
        results = eval(
            tasks=[
                Task(dataset=[Sample(input="x")], name="no_sandbox"),
                Task(
                    dataset=[Sample(input="x")], sandbox="local", name="local_sandbox"
                ),
            ],
            model="mockllm/model",
            max_tasks=2,
        )
    assert len(results) == 2
    for r in results:
        assert r.status == "success", f"{r.eval.task}: {r.error}"
    start_spy.assert_called_once()


# -- unconsumed task_args warning (#4194) ------------------------------------
# task_args only apply to tasks resolved by specification (name, file,
# TaskInfo, task function/class, or cwd auto-discovery). When every task is a
# Task instance passed directly, task_args are silently ignored — eval() and
# eval_set() should warn.

TASK_ARGS_WARNING_SNIPPET = "will not be applied"


@task
def task_args_warning_check(task_arg: str = "default") -> Task:
    return Task(dataset=[Sample(input=f"{task_arg}: test input")])


def _task_args_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if TASK_ARGS_WARNING_SNIPPET in r.message]


def test_task_instance_with_task_args_warns(caplog) -> None:
    log = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    records = _task_args_warnings(caplog)
    assert len(records) == 1, "expected exactly one unconsumed task_args warning"
    assert "task_arg" in records[0].message


def test_task_instance_multiple_models_warns_once(caplog) -> None:
    # resolve_tasks runs once per model; the warning is gated to the first
    # model so it fires exactly once regardless of the model count
    logs = eval(
        task_args_warning_check(),
        task_args={"task_arg": "custom"},
        model=["mockllm/model", "mockllm/model"],
    )
    assert all(log.status == "success" for log in logs)
    assert len(_task_args_warnings(caplog)) == 1


def test_string_task_with_task_args_no_warning(caplog) -> None:
    log = eval(
        "task_args_warning_check",
        task_args={"task_arg": "custom"},
        model="mockllm/model",
    )[0]
    assert log.status == "success"
    # args actually applied
    assert log.eval.task_args["task_arg"] == "custom"
    assert not _task_args_warnings(caplog)


def test_task_instance_without_task_args_no_warning(caplog) -> None:
    log = eval(task_args_warning_check(), model="mockllm/model")[0]
    assert log.status == "success"
    assert not _task_args_warnings(caplog)


def test_eval_set_task_instance_warns_once(caplog) -> None:
    # eval_set re-enters resolution internally with ResolvedTask objects;
    # the warning must fire exactly once, not per resolution pass
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=task_args_warning_check(),
            task_args={"task_arg": "custom"},
            model="mockllm/model",
            log_dir=log_dir,
        )
    assert success
    records = _task_args_warnings(caplog)
    assert len(records) == 1, (
        f"expected exactly one unconsumed task_args warning, got {len(records)}"
    )


class _SeedTasks(TaskSource):
    def __init__(self, count: int) -> None:
        self._count = count

    def initial_tasks(self) -> list[Task]:
        return [
            Task(dataset=[Sample(input=f"t{i}")], name=f"t{i}")
            for i in range(self._count)
        ]

    async def next_tasks(self) -> list[Task] | None:
        return None


@task_source(name="task_args_warning_source")
def task_args_warning_source(count: int = 1) -> TaskSource:
    return _SeedTasks(count)


def test_task_source_with_task_args_no_warning(caplog) -> None:
    # task_args are consumed by the source (resolve_task_source) to build its
    # seed; resolving the seed Task instances must not false-warn (#4194)
    logs = eval(
        "task_args_warning_source",
        task_args={"count": 2},
        model="mockllm/model",
        display="none",
    )
    assert all(log.status == "success" for log in logs)
    assert len(logs) == 2  # count applied by the source -> two seed tasks
    assert not _task_args_warnings(caplog)


# A failed log write must not tear down the whole run. Log writes at task
# start (the log_start() header flush) and the error-status log_finish() are
# the only exceptions that escape task_run(). If log storage (e.g. S3) is
# unreachable at that moment, the failure previously propagated out of
# _run_task() and crashed the entire eval — cancelling every sibling task. It
# should instead surface as an errored EvalLog so the task can be retried like
# any other task error.


@task
def log_write_failure_task() -> Task:
    return Task(
        dataset=[Sample(id=1, input="x", target="y")], name="log_write_failure_task"
    )


def _skew_error() -> ClientError:
    return ClientError(
        cast(
            Any,
            {
                "Error": {
                    "Code": "RequestTimeTooSkewed",
                    "Message": "The difference between the request time and the "
                    "current time is too large.",
                },
                "ResponseMetadata": {"RequestId": "request-1"},
            },
        ),
        "PutObject",
    )


def test_failed_log_start_returns_errored_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A permanently failing log_start yields an errored log, not a crash."""

    async def failing_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        raise _skew_error()

    monkeypatch.setattr(TaskLogger, "log_start", failing_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )

    assert len(logs) == 1
    assert logs[0].status == "error"
    assert logs[0].error is not None
    assert "RequestTimeTooSkewed" in logs[0].error.message
    assert logs[0].location  # the path the failed write was destined for


def test_failed_log_start_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient log_start failure is retried and the task completes."""
    calls = {"n": 0}
    original_log_start = TaskLogger.log_start

    async def flaky_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # push the retry's `created` (second resolution) past the failed
            # attempt's so the retry gets a different log location and must
            # cope with the failed attempt's log never having been written
            await anyio.sleep(1.1)
            raise _skew_error()
        return await original_log_start(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_start", flaky_log_start)

    logs = eval(
        log_write_failure_task(),
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert calls["n"] == 2


async def test_retry_sample_source_tolerates_missing_log_file(tmp_path: Path) -> None:
    """A retry whose prior log was never written yields no reusable samples.

    When a task fails in log_start() its log file never reaches disk, but the
    errored EvalLog still carries the destination path as its location. The
    retry's sample source must treat the missing file as "no prior sample"
    rather than propagating FileNotFoundError (which would error the retry).
    """
    from inspect_ai._eval.task.run import eval_log_sample_source
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset
    from inspect_ai.log import EvalConfig, EvalDataset, EvalLog, EvalSpec
    from inspect_ai.log._file import EvalLogInfo

    missing_log = str(tmp_path / "never-written.eval")
    eval_log = EvalLog(
        status="error",
        eval=EvalSpec(
            created="2026-07-10T00:00:00+00:00",
            task="log_write_failure_task",
            dataset=EvalDataset(samples=1),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        location=missing_log,
    )
    log_info = EvalLogInfo(
        name=missing_log,
        type="file",
        size=0,
        mtime=None,
        task="log_write_failure_task",
        task_id="task-id",
        suffix=None,
    )
    source = eval_log_sample_source(
        eval_log, log_info, MemoryDataset([Sample(id=1, input="x", target="y")])
    )

    async with AsyncFilesystem():
        assert await source.lookup(1, 1) is None


def _retry_source_log_info(location: str) -> Any:
    from inspect_ai.log._file import EvalLogInfo

    return EvalLogInfo(
        name=location,
        type="file",
        size=0,
        mtime=None,
        task="retry_probe_task",
        task_id="task-id",
        suffix=None,
    )


def _write_prior_eval_log(log_dir: Path) -> tuple[Any, bytes]:
    """Run a one-sample eval and return its log plus the .eval file bytes."""
    task = Task(
        dataset=[Sample(id=1, input="Say hello", target="hello")], scorer=match()
    )
    log = eval(task, model="mockllm/model", log_dir=str(log_dir))[0]
    assert log.status == "success" and log.location
    from inspect_ai._util.file import local_path

    return log, Path(local_path(log.location)).read_bytes()


def test_retry_presence_probe_retries_transient_failure(tmp_path: Path) -> None:
    """A failed central-directory fetch is retried on the next probe.

    A transient failure must not be cached as "no presence" — that would
    silently disable the reuse read throttle for the whole sweep.
    """
    from inspect_ai._eval.task.run import eval_log_sample_source
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset

    prior_log, real_bytes = _write_prior_eval_log(tmp_path / "logs")
    probe_path = tmp_path / "prior.eval"
    probe_path.write_bytes(b"not a zip")

    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(str(probe_path)),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )

    async def check() -> None:
        async with AsyncFilesystem():
            assert await source.prior_exists(1, 1) is False
            probe_path.write_bytes(real_bytes)
            assert await source.prior_exists(1, 1) is True
            assert await source.prior_exists(2, 1) is False

    anyio.run(check)


def test_retry_presence_probe_gives_up_after_max_failures(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Persistent fetch failures stop being retried after the cap, with a warning."""
    from inspect_ai._eval.task.run import (
        PRIOR_PROBE_MAX_FAILURES,
        eval_log_sample_source,
    )
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset

    prior_log, real_bytes = _write_prior_eval_log(tmp_path / "logs")
    probe_path = tmp_path / "prior.eval"
    probe_path.write_bytes(b"not a zip")

    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(str(probe_path)),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )

    async def check() -> None:
        async with AsyncFilesystem():
            for _ in range(PRIOR_PROBE_MAX_FAILURES + 2):
                assert await source.prior_exists(1, 1) is False
            # gave up: even a now-valid log is no longer probed
            probe_path.write_bytes(real_bytes)
            assert await source.prior_exists(1, 1) is False

    with caplog.at_level(logging.WARNING, logger="inspect_ai._eval.task.run"):
        anyio.run(check)

    warnings = [r for r in caplog.records if "central directory" in r.message]
    assert len(warnings) == 1


def test_retry_presence_probe_concurrent_failures_respect_cap(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent probes share the failure cap: fetch attempts and the warning stay bounded.

    All run_sample coroutines probe at eval start; each must not get its own
    fetch attempt (and warning) just because it passed the cap check while the
    failure count was still 0.
    """
    from inspect_ai._eval.task.run import (
        PRIOR_PROBE_MAX_FAILURES,
        eval_log_sample_source,
    )
    from inspect_ai._util import async_zip
    from inspect_ai._util._async import tg_collect
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset

    prior_log, _ = _write_prior_eval_log(tmp_path / "logs")
    probe_path = tmp_path / "prior.eval"
    probe_path.write_bytes(b"not a zip")

    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(str(probe_path)),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )

    fetches = 0
    parse_central_directory = async_zip._parse_central_directory

    async def counting_parse(*args: Any, **kwargs: Any) -> Any:
        nonlocal fetches
        fetches += 1
        return await parse_central_directory(*args, **kwargs)

    monkeypatch.setattr(async_zip, "_parse_central_directory", counting_parse)

    async def check() -> None:
        async with AsyncFilesystem():
            results = await tg_collect(
                [
                    functools.partial(source.prior_exists, 1, 1)
                    for _ in range(PRIOR_PROBE_MAX_FAILURES + 7)
                ]
            )
            assert all(result is False for result in results)

    with caplog.at_level(logging.WARNING, logger="inspect_ai._eval.task.run"):
        anyio.run(check)

    assert fetches == PRIOR_PROBE_MAX_FAILURES
    warnings = [r for r in caplog.records if "central directory" in r.message]
    assert len(warnings) == 1


def test_retry_presence_probe_missing_log_cached_without_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing prior log caches no-presence on the first probe, silently."""
    from inspect_ai._eval.task.run import eval_log_sample_source
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai.dataset import MemoryDataset

    prior_log, real_bytes = _write_prior_eval_log(tmp_path / "logs")
    probe_path = tmp_path / "never-written.eval"

    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(str(probe_path)),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )

    async def check() -> None:
        async with AsyncFilesystem():
            assert await source.prior_exists(1, 1) is False
            # cached as definitively absent — not re-fetched even if written
            probe_path.write_bytes(real_bytes)
            assert await source.prior_exists(1, 1) is False

    with caplog.at_level(logging.WARNING, logger="inspect_ai._eval.task.run"):
        anyio.run(check)

    assert not [r for r in caplog.records if "central directory" in r.message]


def test_retry_presence_probe_not_used_for_json_logs(tmp_path: Path) -> None:
    """A .json prior log keeps the default never-probe (no zip index to read)."""
    from inspect_ai._eval.task.run import _never_prior_exists, eval_log_sample_source
    from inspect_ai.dataset import MemoryDataset

    prior_log, _ = _write_prior_eval_log(tmp_path / "logs")
    source = eval_log_sample_source(
        prior_log,
        _retry_source_log_info(str(tmp_path / "prior.json")),
        MemoryDataset([Sample(id=1, input="x", target="y")]),
    )
    assert source.prior_exists is _never_prior_exists


def test_eval_raising_early_stopping_hook_keeps_sample_counted() -> None:
    """A raising `EarlyStopping.complete_sample` cannot leave a sample uncounted.

    Terminal state is recorded before the metrics/early-stopping await
    (design/sample-lifecycle.md): the hook raise still tears the eval down,
    but the errored-with-scores sample that triggered it has already reached
    its terminal bucket and the eval its finish stamp — with metrics-first
    ordering it landed in no bucket at all, so the dying eval could never
    reach `total`. The counters are observed from inside the hook (the
    registry is cleared at the run boundary, so there is nothing to read
    after `eval()` returns).
    """
    from inspect_ai._control.eval_state import clear_all_eval_states, get_eval_states
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer import SampleScore, Score, Target, accuracy, scorer
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util import EarlyStop

    @solver
    def always_boom():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            raise RuntimeError("solver boom")

        return solve

    @scorer(metrics=[accuracy()])
    def always_one():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value=1)

        return score

    observed: list[tuple[tuple[int, int, int], bool]] = []

    class RaisingEarlyStopping:
        async def start_task(
            self, task: EvalSpec, samples: list[Sample], epochs: int
        ) -> str:
            return "raiser"

        async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
            return None

        async def complete_sample(
            self, id: str | int, epoch: int, scores: dict[str, SampleScore]
        ) -> None:
            (state,) = get_eval_states()
            observed.append(
                (
                    (state.completed, state.errored, state.cancelled),
                    state.completed_at is not None,
                )
            )
            raise RuntimeError("hook failure")

        async def complete_task(self) -> dict[str, Any]:
            return {}

    clear_all_eval_states()
    try:
        log = eval(
            Task(
                dataset=[Sample(id="s1", input="x", target="y")],
                solver=always_boom(),
                scorer=always_one(),
                early_stopping=RaisingEarlyStopping(),
            ),
            model="mockllm/model",
            # score_on_error scores the errored sample, so its terminal
            # report reaches the metrics/early-stopping hook
            score_on_error=True,
            fail_on_error=False,
        )[0]
    finally:
        clear_all_eval_states()

    assert log.status == "error"
    assert log.error is not None and "hook failure" in log.error.message
    # the sample was in its terminal bucket, and the eval finish-stamped,
    # before the hook ran
    assert observed == [((0, 1, 0), True)]
