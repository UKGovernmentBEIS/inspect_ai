import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, TaskSource, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
)
from inspect_ai._eval.eval_set_selection import (
    EVAL_SET_SELECTION_VERSION,
    INSPECT_EVAL_SET_SELECTION,
    EvalSetSelection,
    EvalSetSelectionTask,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log
from inspect_ai.scorer import Score, Scorer, Target, exact, scorer
from inspect_ai.scorer._metrics import accuracy
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver

MODELS = ["mockllm/model", "mockllm/model2"]


@task
def selection_task_one() -> Task:
    return Task(
        dataset=[Sample(input="1+1", target="2"), Sample(input="2+2", target="4")],
        solver=[generate()],
        scorer=exact(),
    )


@task
def selection_task_two() -> Task:
    return Task(
        dataset=[Sample(input="hello", target="hello")],
        solver=[generate()],
        scorer=exact(),
    )


def enumerate_eval_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: Any
) -> EvalSetCapture:
    """Enumerate the eval set under capture mode (how a runner learns identifiers)."""
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(
                tasks=[selection_task_one(), selection_task_two()],
                model=MODELS,
                log_dir=str(tmp_path / "capture-logs"),
                display="plain",
                **kwargs,
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    return EvalSetCapture.model_validate_json(manifest_path.read_bytes())


def run_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: EvalSetSelection,
    log_dir: Path,
    *,
    tasks: list[Task] | TaskSource | None = None,
    name: str = "selection",
    **kwargs: Any,
) -> tuple[bool, list[EvalLog]]:
    """Run a worker over `selection` (how a runner executes one task)."""
    selection_path = tmp_path / f"{name}.json"
    selection_path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        return eval_set(
            tasks=[selection_task_one(), selection_task_two()]
            if tasks is None
            else tasks,
            model=MODELS,
            log_dir=str(log_dir),
            display="plain",
            **kwargs,
        )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)


def selection_for(
    identifier: str, eval_set_id: str = "worker-test"
) -> EvalSetSelection:
    return EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id=eval_set_id,
        tasks=[EvalSetSelectionTask(identifier=identifier)],
    )


def test_eval_set_selection_runs_only_selected_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    assert len(capture.tasks) == 4
    selected = next(
        t
        for t in capture.tasks
        if t.name == "selection_task_two" and t.model == "mockllm/model2"
    )

    log_dir = tmp_path / "logs"
    success, logs = run_selection(
        monkeypatch, tmp_path, selection_for(selected.identifier), log_dir
    )

    assert success
    assert len(logs) == 1
    assert logs[0].eval.task == "selection_task_two"
    assert logs[0].eval.model == "mockllm/model2"
    # the eval set has four tasks; the worker ran exactly one
    assert len(list_eval_logs(str(log_dir))) == 1


def test_eval_set_selection_stamps_eval_set_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    log_dir = tmp_path / "logs"
    _, logs = run_selection(
        monkeypatch,
        tmp_path,
        selection_for(capture.tasks[0].identifier, eval_set_id="runner-assigned-id"),
        log_dir,
    )
    assert logs[0].eval.eval_set_id == "runner-assigned-id"


def test_eval_set_selection_writes_no_eval_set_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A worker touches nothing in the log directory but its own log.

    This is what lets many workers share one flat directory: the runner is the
    sole writer of the eval-set metadata, and no worker prunes or rewrites
    another's log.
    """
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # a sibling worker's log, already in place
    sibling = log_dir / "2024-01-01T00-00-00+00-00_sibling_abcdefghijklmnop.eval"
    sibling.write_bytes(b"not a real log, but it must survive untouched")

    run_selection(
        monkeypatch, tmp_path, selection_for(capture.tasks[0].identifier), log_dir
    )

    assert sibling.read_bytes() == b"not a real log, but it must survive untouched"
    for metadata in (".eval-set-id", "eval-set.json", "logs.json"):
        assert not (log_dir / metadata).exists(), metadata
    # exactly one new file (this worker's log)
    assert len(list(log_dir.iterdir())) == 2


def test_eval_set_selection_concurrent_workers(tmp_path: Path) -> None:
    """Two workers selecting different tasks into one flat directory both succeed.

    This is the concurrency property the whole selection protocol exists for,
    so it runs real processes rather than in-process eval sets.
    """
    definition = tmp_path / "definition.py"
    definition.write_text(
        textwrap.dedent(
            """
            from inspect_ai import Task, eval_set, task
            from inspect_ai.dataset import Sample
            from inspect_ai.scorer import exact
            from inspect_ai.solver import generate


            @task
            def alpha() -> Task:
                return Task(
                    dataset=[Sample(input="1+1", target="2")],
                    solver=[generate()],
                    scorer=exact(),
                )


            @task
            def beta() -> Task:
                return Task(
                    dataset=[Sample(input="hello", target="hello")],
                    solver=[generate()],
                    scorer=exact(),
                )


            eval_set(
                tasks=[alpha(), beta()],
                model="mockllm/model",
                log_dir="logs",
            )
            """
        )
    )

    # enumerate, exactly as a runner would
    manifest_path = tmp_path / "manifest.json"
    capture_result = subprocess.run(
        [sys.executable, str(definition)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            INSPECT_EVAL_SET_CAPTURE: str(manifest_path),
            "INSPECT_DISPLAY": "plain",
        },
    )
    assert capture_result.returncode == 0, capture_result.stderr
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    assert {t.name for t in capture.tasks} == {"alpha", "beta"}

    # launch one worker per task, both writing into the same flat directory
    # (the definition's own log_dir, relative to the working directory)
    log_dir = tmp_path / "logs"
    workers: list[subprocess.Popen[str]] = []
    for capture_task in capture.tasks:
        selection_path = tmp_path / f"selection-{capture_task.name}.json"
        selection_path.write_text(
            selection_for(
                capture_task.identifier, eval_set_id="concurrent"
            ).model_dump_json()
        )
        workers.append(
            subprocess.Popen(
                [sys.executable, str(definition)],
                cwd=tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    **os.environ,
                    INSPECT_EVAL_SET_SELECTION: str(selection_path),
                    "INSPECT_DISPLAY": "plain",
                },
            )
        )

    for worker in workers:
        _, stderr = worker.communicate(timeout=300)
        assert worker.returncode == 0, stderr

    logs = list_eval_logs(str(log_dir))
    assert len(logs) == 2
    headers = [read_eval_log(log.name, header_only=True) for log in logs]
    assert {header.eval.task for header in headers} == {"alpha", "beta"}
    assert all(header.status == "success" for header in headers)
    assert all(header.eval.eval_set_id == "concurrent" for header in headers)
    # neither worker wrote eval-set metadata
    assert {path.name for path in log_dir.iterdir()} == {
        log.name.split("/")[-1] for log in logs
    }


def test_eval_set_selection_resume_reuses_completed_samples(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resuming a failed log reuses its completed samples instead of re-running them."""
    solved: list[str] = []

    @solver
    def fail_second_sample_first_attempt() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            solved.append(str(state.sample_id))
            if state.sample_id == "two" and solved.count("two") == 1:
                raise ValueError("first attempt fails")
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def always_correct() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    def resumable_tasks() -> list[Task]:
        return [
            Task(
                dataset=[Sample(id="one", input="one"), Sample(id="two", input="two")],
                solver=fail_second_sample_first_attempt(),
                scorer=always_correct(),
                name="resumable",
            )
        ]

    manifest_path = tmp_path / "manifest.json"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(
                tasks=resumable_tasks(),
                model="mockllm/model",
                log_dir=str(log_dir),
                display="plain",
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    identifier = capture.tasks[0].identifier

    def run(selection: EvalSetSelection, name: str) -> tuple[bool, list[EvalLog]]:
        selection_path = tmp_path / f"{name}.json"
        selection_path.write_text(selection.model_dump_json())
        monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
        try:
            return eval_set(
                tasks=resumable_tasks(),
                model="mockllm/model",
                log_dir=str(log_dir),
                display="plain",
                max_samples=1,
            )
        finally:
            monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)

    # first worker: sample "two" errors. the task still completes (worker mode
    # forces fail_on_error=False) and performs no task-level retry of its own --
    # both are the runner's decisions to make from the log.
    success, logs = run(selection_for(identifier), "first")
    assert success
    assert logs[0].status == "success"
    assert solved.count("one") == 1
    assert solved.count("two") == 1
    # the residue the runner adjudicates: completed < total
    assert logs[0].results is not None
    assert logs[0].results.total_samples == 2
    assert logs[0].results.completed_samples == 1
    prior_location = logs[0].location

    # second worker resumes that log: sample "one" is reused (its solver is not
    # called again) and only the errored sample "two" runs
    success, logs = run(
        EvalSetSelection(
            version=EVAL_SET_SELECTION_VERSION,
            eval_set_id="worker-test",
            tasks=[EvalSetSelectionTask(identifier=identifier, resume=prior_location)],
        ),
        "second",
    )
    assert success
    assert solved.count("one") == 1
    assert solved.count("two") == 2
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 2


def test_eval_set_selection_forces_fail_on_error_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A definition demanding fail-fast still completes: completion is the runner's call.

    `fail_on_error=True` (the default) would mark the log `error` on the first
    sample error. Worker mode overrides it so the errored sample becomes an
    entry in the runner's adjudication queue rather than a failed task.
    """

    @solver
    def fail_one_sample() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "bad":
                raise ValueError("this sample always errors")
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def always_correct() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    def tasks() -> list[Task]:
        return [
            Task(
                dataset=[Sample(id="ok", input="ok"), Sample(id="bad", input="bad")],
                solver=fail_one_sample(),
                scorer=always_correct(),
                name="fail_fast",
            )
        ]

    manifest_path = tmp_path / "manifest.json"
    log_dir = tmp_path / "logs"
    kwargs: dict[str, Any] = dict(
        model="mockllm/model",
        log_dir=str(log_dir),
        display="plain",
        fail_on_error=True,
        continue_on_fail=False,
    )

    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(tasks=tasks(), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())

    # the manifest records what the definition asked for, so a runner can see
    # what is being honoured and what is being overridden
    assert capture.options["fail_on_error"] is True
    assert capture.options["continue_on_fail"] is False
    assert capture.options["retry_on_error"] is None
    assert capture.options["scanners"] is False

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        selection_for(capture.tasks[0].identifier).model_dump_json()
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        success, logs = eval_set(tasks=tasks(), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)

    assert success
    assert logs[0].status == "success"
    assert logs[0].results is not None
    assert logs[0].results.total_samples == 2
    assert logs[0].results.completed_samples == 1


def test_eval_set_selection_honors_retry_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`retry_on_error` stays under the definition author's control."""
    attempts: list[str] = []

    @solver
    def fail_twice() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts.append(str(state.sample_id))
            if len(attempts) <= 2:
                raise ValueError("transient")
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def always_correct() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    def tasks() -> list[Task]:
        return [
            Task(
                dataset=[Sample(id="one", input="one")],
                solver=fail_twice(),
                scorer=always_correct(),
                name="retrying",
            )
        ]

    manifest_path = tmp_path / "manifest.json"
    kwargs: dict[str, Any] = dict(
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="plain",
        retry_on_error=3,
    )

    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(tasks=tasks(), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    assert capture.options["retry_on_error"] == 3

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        selection_for(capture.tasks[0].identifier).model_dump_json()
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        success, logs = eval_set(tasks=tasks(), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)

    # two failures then a success: the definition's three sample attempts ran
    assert success
    assert len(attempts) == 3
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 1


def test_eval_set_selection_unknown_identifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(PrerequisiteError, match="does not match any of the 4 tasks"):
        run_selection(
            monkeypatch,
            tmp_path,
            selection_for("nope@nope#nope/nope/nope"),
            tmp_path / "logs",
        )


def test_eval_set_selection_resume_log_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A resume log belonging to a different task is rejected rather than reused."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    log_dir = tmp_path / "logs"
    identifiers = {t.name: t.identifier for t in capture.tasks if t.model == MODELS[0]}

    _, logs = run_selection(
        monkeypatch, tmp_path, selection_for(identifiers["selection_task_one"]), log_dir
    )
    assert logs[0].location

    with pytest.raises(PrerequisiteError, match="belongs to a different task"):
        run_selection(
            monkeypatch,
            tmp_path,
            EvalSetSelection(
                version=EVAL_SET_SELECTION_VERSION,
                eval_set_id="worker-test",
                tasks=[
                    EvalSetSelectionTask(
                        identifier=identifiers["selection_task_two"],
                        resume=logs[0].location,
                    )
                ],
            ),
            log_dir,
            name="mismatch",
        )


def test_eval_set_selection_resume_log_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    with pytest.raises(PrerequisiteError, match="does not exist"):
        run_selection(
            monkeypatch,
            tmp_path,
            EvalSetSelection(
                version=EVAL_SET_SELECTION_VERSION,
                eval_set_id="worker-test",
                tasks=[
                    EvalSetSelectionTask(
                        identifier=capture.tasks[0].identifier,
                        resume=str(tmp_path / "absent.eval"),
                    )
                ],
            ),
            tmp_path / "logs",
        )


@pytest.mark.parametrize(
    "content,error_match",
    [
        ("{not json", "Unable to read the eval set selection"),
        (json.dumps({"version": 1}), "Unable to read the eval set selection"),
        (
            json.dumps(
                {"version": 99, "eval_set_id": "x", "tasks": [{"identifier": "y"}]}
            ),
            "schema version 99",
        ),
        (json.dumps({"version": 1, "eval_set_id": "x", "tasks": []}), "names no tasks"),
    ],
)
def test_eval_set_selection_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str, error_match: str
) -> None:
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(content)
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    with pytest.raises(PrerequisiteError, match=error_match):
        eval_set(
            tasks=[selection_task_one()],
            model="mockllm/model",
            log_dir=str(tmp_path / "logs"),
            display="plain",
        )


def test_eval_set_selection_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(tmp_path / "absent.json"))
    with pytest.raises(
        PrerequisiteError, match="Unable to read the eval set selection"
    ):
        eval_set(
            tasks=[selection_task_one()],
            model="mockllm/model",
            log_dir=str(tmp_path / "logs"),
            display="plain",
        )


def test_eval_set_selection_task_source_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(PrerequisiteError, match="TaskSource"):
        run_selection(
            monkeypatch,
            tmp_path,
            selection_for("anything"),
            tmp_path / "logs",
            tasks=TaskSource(),
        )


def test_eval_set_selection_scanner_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(PrerequisiteError, match="Scanners are not supported"):
        run_selection(
            monkeypatch,
            tmp_path,
            selection_for("anything"),
            tmp_path / "logs",
            scanner=[],
        )


def test_eval_set_capture_and_selection_are_exclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(tmp_path / "manifest.json"))
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(tmp_path / "selection.json"))
    with pytest.raises(PrerequisiteError, match="cannot both be set"):
        eval_set(
            tasks=[selection_task_one()],
            model="mockllm/model",
            log_dir=str(tmp_path / "logs"),
            display="plain",
        )


# Golden values for the selection schema. These must NOT be changed for an
# existing version -- an external runner writes these files. If the schema
# changes, bump EVAL_SET_SELECTION_VERSION and update accordingly.
_EXPECTED_SELECTION_FIELDS: dict[int, dict[str, set[str]]] = {
    1: {
        "selection": {"version", "eval_set_id", "tasks"},
        "task": {"identifier", "resume"},
    }
}


def test_eval_set_selection_schema_stability() -> None:
    assert EVAL_SET_SELECTION_VERSION in _EXPECTED_SELECTION_FIELDS
    expected = _EXPECTED_SELECTION_FIELDS[EVAL_SET_SELECTION_VERSION]
    assert set(EvalSetSelection.model_fields.keys()) == expected["selection"]
    assert set(EvalSetSelectionTask.model_fields.keys()) == expected["task"]
