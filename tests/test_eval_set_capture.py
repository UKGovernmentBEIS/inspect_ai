import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any, Literal

import pytest
from test_helpers.buffer import simulate_crashed_buffer_db
from test_helpers.utils import identity_solver

from inspect_ai import Task, TaskSource, eval, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    EVAL_SET_CAPTURE_VERSION,
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
    EvalSetCaptureTask,
    samples_for_limit,
    task_args_hash,
)
from inspect_ai._eval.evalset import TASK_IDENTIFIER_VERSION
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import local_path
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.dataset import Sample
from inspect_ai.event import SampleInitEvent
from inspect_ai.log import (
    ProvenanceData,
    invalidate_samples,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import LogStart
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.scorer import Score, exact
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


@task
def capture_task_one(difficulty: str = "easy") -> Task:
    return Task(
        dataset=[
            Sample(input="1+1", target="2"),
            Sample(input="2+2", target="4"),
            Sample(input="3+3", target="6"),
        ],
        solver=[generate()],
        scorer=exact(),
    )


@task
def capture_task_two() -> Task:
    return Task(
        dataset=[Sample(input="hello", target="hello")],
        solver=[generate()],
        scorer=exact(),
        epochs=3,
    )


def capture_eval_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: object
) -> EvalSetCapture:
    manifest_path = tmp_path / "capture" / "manifest.json"
    manifest_path.parent.mkdir()
    log_dir = tmp_path / "logs"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    with pytest.raises(SystemExit) as exc_info:
        eval_set(
            tasks=[capture_task_one(difficulty="hard"), capture_task_two()],
            model=["mockllm/model", "mockllm/model2"],
            log_dir=str(log_dir),
            display="plain",
            **kwargs,  # type: ignore[arg-type]
        )
    assert exc_info.value.code == 0
    assert not log_dir.exists()
    return EvalSetCapture.model_validate_json(manifest_path.read_bytes())


def test_eval_set_capture_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = capture_eval_set(monkeypatch, tmp_path, eval_set_id="capture-test")

    assert capture.version == EVAL_SET_CAPTURE_VERSION
    assert capture.identifier_version == TASK_IDENTIFIER_VERSION
    assert capture.eval_set_id == "capture-test"
    assert capture.options["log_dir"] == str(tmp_path / "logs")
    # effective value (default 10), not the raw None parameter
    assert capture.options["retry_attempts"] == 10
    # unset means the definition expressed no preference, which is different
    # from asking for whatever the runner's default happens to be
    assert capture.options["max_samples"] is None

    # two tasks crossed over two models
    assert len(capture.tasks) == 4
    assert {t.name for t in capture.tasks} == {"capture_task_one", "capture_task_two"}
    assert {t.model for t in capture.tasks} == {"mockllm/model", "mockllm/model2"}

    # identifiers are unique and match the documented format
    identifiers = [t.identifier for t in capture.tasks]
    assert len(set(identifiers)) == 4
    for t in capture.tasks:
        assert t.identifier.startswith(f"{t.file}@{t.name}#{t.args_hash}/{t.model}/")

    task_one = next(t for t in capture.tasks if t.name == "capture_task_one")
    assert task_one.args == {"difficulty": "hard"}
    assert task_one.args_full == {"difficulty": "hard"}
    assert task_one.args_hash == task_args_hash({"difficulty": "hard"})
    assert task_one.samples == 3
    assert task_one.epochs == 1
    assert task_one.solver == "generate"

    # task-level epochs apply when eval-set level epochs are not specified
    task_two = next(t for t in capture.tasks if t.name == "capture_task_two")
    assert task_two.samples == 1
    assert task_two.epochs == 3

    # no log directory, so no task has a log
    assert all(t.log is None and t.complete is None for t in capture.tasks)


def test_eval_set_capture_limit_and_epochs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = capture_eval_set(monkeypatch, tmp_path, limit=2, epochs=5)

    task_one = next(t for t in capture.tasks if t.name == "capture_task_one")
    assert task_one.samples == 2
    assert task_one.epochs == 5

    # eval-set level epochs override task-level epochs
    task_two = next(t for t in capture.tasks if t.name == "capture_task_two")
    assert task_two.samples == 1
    assert task_two.epochs == 5

    assert capture.options["limit"] == [2] or capture.options["limit"] == 2
    assert capture.options["epochs"] == 5


def test_eval_set_capture_max_samples(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a runner sets max_samples per worker through the selection document, so
    # it needs to see what the definition asked for or it will silently
    # override an explicit value with its own default
    capture = capture_eval_set(monkeypatch, tmp_path, max_samples=25)

    assert capture.options["max_samples"] == 25


def test_eval_set_capture_model_roles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = capture_eval_set(
        monkeypatch, tmp_path, model_roles={"grader": "mockllm/grader"}
    )
    assert all(
        task.model_roles == {"grader": "mockllm/grader"} for task in capture.tasks
    )


def test_eval_set_capture_model_roles_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = capture_eval_set(
        monkeypatch,
        tmp_path,
        model_roles={"grader": ["mockllm/grader_a", "mockllm/grader_b"]},
    )
    assert all(
        task.model_roles == {"grader": "mockllm/grader_a,mockllm/grader_b"}
        for task in capture.tasks
    )


def test_eval_set_capture_adhoc_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ad-hoc (non-@task) tasks capture with no registry name or full args."""
    manifest_path = tmp_path / "manifest.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    adhoc = Task(
        dataset=[Sample(input="1+1", target="2")],
        solver=[generate()],
        scorer=exact(),
        name="adhoc_task",
    )
    with pytest.raises(SystemExit):
        eval_set(
            tasks=[adhoc],
            model="mockllm/model",
            log_dir=str(log_dir),
            display="plain",
        )
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    task = capture.tasks[0]
    assert task.name == "adhoc_task"
    assert task.registry_name is None
    assert task.args == {}
    assert task.args_full is None
    assert task.identifier


def test_eval_set_capture_task_source_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(tmp_path / "manifest.json"))
    with pytest.raises(PrerequisiteError, match="TaskSource"):
        eval_set(
            tasks=TaskSource(),
            model="mockllm/model",
            log_dir=str(tmp_path / "logs"),
            display="plain",
        )


def test_eval_set_capture_subprocess_protocol(tmp_path: Path) -> None:
    """Full protocol: a definition script under capture writes the manifest and exits before any code after the eval_set() call runs."""
    script = tmp_path / "evalset.py"
    script.write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            from inspect_ai import Task, eval_set, task
            from inspect_ai.dataset import Sample
            from inspect_ai.scorer import exact
            from inspect_ai.solver import generate


            @task
            def subprocess_task() -> Task:
                return Task(
                    dataset=[Sample(input="1+1", target="2")],
                    solver=[generate()],
                    scorer=exact(),
                )


            eval_set(
                tasks=[subprocess_task()],
                model="mockllm/model",
                log_dir="logs",
            )

            Path("sentinel.txt").write_text("ran past eval_set")
            """
        )
    )
    manifest_path = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            INSPECT_EVAL_SET_CAPTURE: str(manifest_path),
            "INSPECT_DISPLAY": "plain",
        },
    )
    assert result.returncode == 0, result.stderr
    assert manifest_path.exists()
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    assert len(capture.tasks) == 1
    assert capture.tasks[0].name == "subprocess_task"
    # code after eval_set() never ran and log_dir was never created
    assert not (tmp_path / "sentinel.txt").exists()
    assert not (tmp_path / "logs").exists()


@solver
def capture_failing_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        raise ValueError("capture_failing_solver always fails")

    return solve


@task
def capture_failing_task() -> Task:
    return Task(
        dataset=[Sample(input="1+1", target="2")],
        solver=[capture_failing_solver()],
        scorer=exact(),
    )


def run_eval_set(log_dir: Path, tasks: list[Task], **kwargs: Any) -> list[str]:
    """Run an eval set for real, returning its logs' locations as a log listing names them."""
    _, logs = eval_set(
        tasks=tasks,
        model="mockllm/model",
        log_dir=str(log_dir),
        retry_attempts=0,
        display="plain",
        **kwargs,
    )
    return [Path(log.location).as_uri() for log in logs]


def log_dir_state(log_dir: Path) -> list[tuple[Path, int, int]] | None:
    """Every path under a log directory with its mtime and size, or `None` if it doesn't exist."""
    if not log_dir.exists():
        return None
    return sorted(
        (path, path.stat().st_mtime_ns, path.stat().st_size)
        for path in log_dir.rglob("*")
    )


def capture_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    log_dir: Path,
    tasks: list[Task],
    **kwargs: Any,
) -> dict[str, EvalSetCaptureTask]:
    """Capture an eval set over an existing log directory, by task name."""
    manifest_path = tmp_path / "manifest.json"
    before = log_dir_state(log_dir)
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    with pytest.raises(SystemExit) as exc_info:
        eval_set(
            tasks=tasks,
            model="mockllm/model",
            log_dir=str(log_dir),
            display="plain",
            **kwargs,
        )
    assert exc_info.value.code == 0
    # capture reads the log directory and never writes to it
    assert log_dir_state(log_dir) == before
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    return {t.name: t for t in capture.tasks}


def test_eval_set_capture_verdict_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    [location] = run_eval_set(log_dir, [capture_task_one()])

    tasks = capture_logs(
        monkeypatch, tmp_path, log_dir, [capture_task_one(), capture_task_two()]
    )

    assert tasks["capture_task_one"].log == location
    assert tasks["capture_task_one"].complete is True
    # a task with no log of its own
    assert tasks["capture_task_two"].log is None
    assert tasks["capture_task_two"].complete is None


def test_eval_set_capture_verdict_error_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    [location] = run_eval_set(log_dir, [capture_failing_task()])
    assert read_eval_log(location, header_only=True).status == "error"

    tasks = capture_logs(monkeypatch, tmp_path, log_dir, [capture_failing_task()])

    assert tasks["capture_failing_task"].log == location
    assert tasks["capture_failing_task"].complete is False


def test_eval_set_capture_verdict_invalidated_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    [location] = run_eval_set(log_dir, [capture_task_one()])
    log = read_eval_log(location)
    assert log.samples is not None and log.samples[0].uuid is not None
    log = invalidate_samples(
        log,
        sample_uuids=[log.samples[0].uuid],
        provenance=ProvenanceData(author="test", reason="test"),
    )
    write_eval_log(log, location=location)

    tasks = capture_logs(monkeypatch, tmp_path, log_dir, [capture_task_one()])

    assert tasks["capture_task_one"].log == location
    assert tasks["capture_task_one"].complete is False


@pytest.mark.parametrize(
    "run_kwargs,capture_kwargs",
    [
        pytest.param({}, {"epochs": 2}, id="epochs-changed"),
        pytest.param({"limit": 1}, {"limit": 2}, id="limit-raised"),
    ],
)
def test_eval_set_capture_verdict_short_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run_kwargs: dict[str, Any],
    capture_kwargs: dict[str, Any],
) -> None:
    log_dir = tmp_path / "logs"
    [location] = run_eval_set(log_dir, [capture_task_one()], **run_kwargs)

    tasks = capture_logs(
        monkeypatch, tmp_path, log_dir, [capture_task_one()], **capture_kwargs
    )

    assert tasks["capture_task_one"].log == location
    assert tasks["capture_task_one"].complete is False


def test_eval_set_capture_verdict_no_samples_planned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `bar` is named by no `task:id` selector, so it plans no samples and its
    # success log (with no results) is complete
    foo = Task(name="foo", dataset=[Sample(id=i, input="hi") for i in (1, 2)])
    bar = Task(name="bar", dataset=[Sample(id=i, input="hi") for i in (1, 2)])
    log_dir = tmp_path / "logs"
    run_eval_set(log_dir, [foo, bar], sample_id=["foo:1"])

    tasks = capture_logs(
        monkeypatch, tmp_path, log_dir, [foo, bar], sample_id=["foo:1"]
    )

    assert tasks["bar"].log is not None
    assert tasks["bar"].complete is True
    assert tasks["foo"].complete is True


def eval_set_verdict(
    log_dir: Path, tasks: list[Task], **kwargs: Any
) -> tuple[str | None, bool | None]:
    """What `eval_set()` does with a copy of a one-task log directory, as capture reports it.

    Returns the name of the log it resumes from and `False`, or `(None, None)`
    when it runs the task fresh, or the name of the log it keeps and `True`
    when it runs nothing.
    """
    stock_dir = log_dir.with_name(f"{log_dir.name}-stock")
    shutil.copytree(log_dir, stock_dir)
    by_task_id = {
        read_eval_log(str(path), header_only=True).eval.task_id: path.name
        for path in stock_dir.glob("*.eval")
    }
    _, logs = eval_set(
        tasks=tasks,
        model="mockllm/model",
        log_dir=str(stock_dir),
        retry_attempts=0,
        display="plain",
        **kwargs,
    )
    ran = [log for log in logs if Path(log.location).name not in by_task_id.values()]
    if not ran:
        [kept] = logs
        return Path(kept.location).name, True
    [run] = ran
    resumed = by_task_id.get(run.eval.task_id)
    return (resumed, False) if resumed else (None, None)


@pytest.mark.parametrize("earlier_log", [False, True])
def test_eval_set_capture_verdict_shuffle_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, earlier_log: bool
) -> None:
    # under a limit a log of another shuffle holds other samples, so eval_set
    # neither reuses nor resumes it: it keeps a log of the current shuffle, or
    # runs the task fresh when there is none
    log_dir = tmp_path / "logs"
    earlier = None
    if earlier_log:
        [earlier] = run_eval_set(
            log_dir, [capture_task_one()], limit=2, sample_shuffle=1
        )
    [other] = run_eval_set(
        tmp_path / "other", [capture_task_one()], limit=2, sample_shuffle=2
    )
    other_log = read_eval_log(other)
    other_log.status = "error"
    log_dir.mkdir(exist_ok=True)
    other_location = log_dir / Path(local_path(other)).name
    write_eval_log(other_log, location=str(other_location))

    expected = (Path(local_path(earlier)).name, True) if earlier else (None, None)
    assert (
        eval_set_verdict(log_dir, [capture_task_one()], limit=2, sample_shuffle=1)
        == expected
    )

    tasks = capture_logs(
        monkeypatch, tmp_path, log_dir, [capture_task_one()], limit=2, sample_shuffle=1
    )
    verdict = tasks["capture_task_one"]

    assert (
        Path(local_path(verdict.log)).name if verdict.log else None,
        verdict.complete,
    ) == expected


def test_eval_set_capture_verdict_ignores_other_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a log of a task outside the eval set is neither refused nor matched
    log_dir = tmp_path / "logs"
    run_eval_set(log_dir, [capture_task_one(difficulty="easy")])

    tasks = capture_logs(
        monkeypatch, tmp_path, log_dir, [capture_task_one(difficulty="hard")]
    )

    assert tasks["capture_task_one"].log is None
    assert tasks["capture_task_one"].complete is None


def test_eval_set_capture_verdict_newest_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # the second run resumes the first (same task id) and both logs are kept
    log_dir = tmp_path / "logs"
    [short] = run_eval_set(log_dir, [capture_task_one()], limit=1, retry_cleanup=False)
    [full] = run_eval_set(log_dir, [capture_task_one()], limit=2, retry_cleanup=False)
    assert short != full

    tasks = capture_logs(monkeypatch, tmp_path, log_dir, [capture_task_one()], limit=2)

    assert tasks["capture_task_one"].log == full
    assert tasks["capture_task_one"].complete is True


@pytest.mark.parametrize(
    "first_limit,second_limit,second_status,chosen",
    [
        # only one of the two runs was recorded for the requested limit (2)
        pytest.param(1, 2, "success", "second", id="requested-selection-wins"),
        pytest.param(2, 1, "success", "first", id="older-requested-selection-wins"),
        pytest.param(2, 2, "success", "second", id="newest-wins"),
        pytest.param(2, 2, "error", "second", id="newest-incomplete-wins"),
    ],
)
def test_eval_set_capture_verdict_logs_of_two_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first_limit: int,
    second_limit: int,
    second_status: Literal["success", "error"],
    chosen: Literal["first", "second"],
) -> None:
    # two runs of one task that did not resume each other (two task ids); the
    # second is newer. eval_set uses one of them, and capture reports that one
    log_dir = tmp_path / "logs"
    [first] = run_eval_set(log_dir, [capture_task_one()], limit=first_limit)
    [other] = run_eval_set(tmp_path / "other", [capture_task_one()], limit=second_limit)
    second_log = read_eval_log(other)
    second_log.status = second_status
    second = log_dir / Path(local_path(other)).name
    write_eval_log(second_log, location=str(second))
    location = Path(local_path(first)) if chosen == "first" else second
    complete = chosen == "first" or second_status == "success"

    assert eval_set_verdict(log_dir, [capture_task_one()], limit=2) == (
        location.name,
        complete,
    )

    tasks = capture_logs(monkeypatch, tmp_path, log_dir, [capture_task_one()], limit=2)

    assert tasks["capture_task_one"].log == location.as_uri()
    assert tasks["capture_task_one"].complete is complete


def test_eval_set_capture_verdict_default_log_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a definition that names no log_dir is recorded as naming none, while the
    # verdicts come from the directory eval_set() would use
    log_dir = tmp_path / "logs"
    [location] = run_eval_set(log_dir, [capture_task_one()])
    before = log_dir_state(log_dir)
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv("INSPECT_LOG_DIR", str(log_dir))
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    with pytest.raises(SystemExit):
        eval_set(tasks=[capture_task_one()], model="mockllm/model", display="plain")

    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    assert capture.options["log_dir"] is None
    assert capture.tasks[0].log == location
    assert capture.tasks[0].complete is True
    assert log_dir_state(log_dir) == before


def test_eval_set_capture_verdict_crashed_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a crashed log whose buffer an eval_set with incomplete_action="error"
    # would recover and finalize (see test_eval_set_incomplete_action_error_
    # finalizes): capture recovers nothing, so the log stays incomplete
    samples = [
        Sample(id=1, input="Say hello", target="hello"),
        Sample(id=2, input="Say hello", target="hello"),
    ]
    crashed_task = Task(
        dataset=samples, solver=[identity_solver()], name="capture_crashed"
    )
    log_dir = tmp_path / "logs"
    started_log = eval(
        crashed_task, model="mockllm/model", log_dir=str(log_dir), run_samples=False
    )[0]
    location = local_path(started_log.location)
    with zipfile.ZipFile(location, "w") as zf:
        zf.writestr(
            "_journal/start.json",
            to_json_str_safe(
                LogStart(
                    version=started_log.version,
                    eval=started_log.eval,
                    plan=started_log.plan,
                )
            ),
        )

    buffer = SampleBufferDatabase(started_log.location)
    try:
        now = "2026-01-01T00:00:00+00:00"
        completed = EvalSampleSummary(
            id=1,
            epoch=1,
            input="Say hello",
            target="hello",
            scores={"accuracy": Score(value="C", answer="hello")},
            started_at=now,
            completed_at=now,
        )
        buffer.start_sample(completed)
        buffer.log_events(
            [
                SampleEvent(
                    id=1, epoch=1, event=SampleInitEvent(sample=samples[0], state={})
                )
            ]
        )
        buffer.complete_sample(completed, sample_metadata=None)
        in_progress = EvalSampleSummary(
            id=2, epoch=1, input="Say hello", target="hello", started_at=now
        )
        buffer.start_sample(in_progress)
        buffer.log_events(
            [
                SampleEvent(
                    id=2, epoch=1, event=SampleInitEvent(sample=samples[1], state={})
                )
            ]
        )
        db_path = simulate_crashed_buffer_db(buffer)

        tasks = capture_logs(
            monkeypatch, tmp_path, log_dir, [crashed_task], incomplete_action="error"
        )

        assert tasks["capture_crashed"].log == Path(location).as_uri()
        assert tasks["capture_crashed"].complete is False
        # no recovered log was written (checked by capture_logs) and the
        # buffer a recovery would sweep is still there
        assert db_path.exists()
    finally:
        buffer.cleanup()


def test_samples_for_limit() -> None:
    cases: list[tuple[int, int | tuple[int, int] | None, int]] = [
        (10, None, 10),
        (10, 3, 3),
        (2, 3, 2),
        (10, (2, 5), 3),
        (10, (12, 15), 0),
        (4, (2, 15), 2),
    ]
    for count, limit, expected in cases:
        assert samples_for_limit(count, limit) == expected, (count, limit)


# Golden values for the capture schema. These must NOT be changed for an
# existing version. If the schema or the args hash computation changes, bump
# EVAL_SET_CAPTURE_VERSION and update accordingly (see also
# TASK_IDENTIFIER_VERSION in tests/test_task_identifier_version.py).
_EXPECTED_CAPTURE_TASK_FIELDS: dict[int, set[str]] = {
    1: {
        "name",
        "display_name",
        "registry_name",
        "file",
        "args",
        "args_full",
        "args_hash",
        "solver",
        "model",
        "model_args",
        "model_roles",
        "sequence",
        "identifier",
        "samples",
        "epochs",
    },
    # v2 changed the manifest and not the task entry: `overrides` records the
    # operational overrides in force, because `options` is now unambiguously a
    # record of the *definition* and a run with an `epochs` or `limit` override
    # has per-task `samples` the definition's options cannot account for.
    2: {
        "name",
        "display_name",
        "registry_name",
        "file",
        "args",
        "args_full",
        "args_hash",
        "solver",
        "model",
        "model_args",
        "model_roles",
        "sequence",
        "identifier",
        "samples",
        "epochs",
    },
}

# v3 changed the manifest and not the task entry: `scan` serializes the
# definition's scanner configuration (a scout `ScanSpec` dump plus the
# output-location override) so a runner can own the scan directory's
# lifecycle without executing the definition — workers scan record-only in
# selection mode. `options["scanners"]` remains the quick boolean beside it.
_EXPECTED_CAPTURE_TASK_FIELDS[3] = _EXPECTED_CAPTURE_TASK_FIELDS[2]

# v4 added Inspect's completion verdict on each task's logs (`complete`) and
# the log it applies to (`log`): the one `one_log_per_task_identifier()` chooses
# among the task's logs, as eval_set() chooses it. A runner can then plan from
# the capture without re-deriving completion from log headers.
_EXPECTED_CAPTURE_TASK_FIELDS[4] = _EXPECTED_CAPTURE_TASK_FIELDS[3] | {
    "log",
    "complete",
}

_EXPECTED_CAPTURE_FIELDS: dict[int, set[str]] = {
    1: {"version", "identifier_version", "eval_set_id", "options", "tasks"},
    2: {
        "version",
        "identifier_version",
        "eval_set_id",
        "options",
        "overrides",
        "tasks",
    },
    3: {
        "version",
        "identifier_version",
        "eval_set_id",
        "options",
        "overrides",
        "scan",
        "tasks",
    },
}
_EXPECTED_CAPTURE_FIELDS[4] = _EXPECTED_CAPTURE_FIELDS[3]


def test_eval_set_capture_schema_stability() -> None:
    assert EVAL_SET_CAPTURE_VERSION in _EXPECTED_CAPTURE_TASK_FIELDS
    assert (
        set(EvalSetCaptureTask.model_fields.keys())
        == _EXPECTED_CAPTURE_TASK_FIELDS[EVAL_SET_CAPTURE_VERSION]
    )
    assert (
        set(EvalSetCapture.model_fields.keys())
        == _EXPECTED_CAPTURE_FIELDS[EVAL_SET_CAPTURE_VERSION]
    )
    # empty task args hash (also pinned in test_task_identifier_version.py)
    assert (
        task_args_hash({})
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
