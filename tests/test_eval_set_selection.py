import json
import os
import socket
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, TaskSource, eval_set, task
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
)
from inspect_ai._eval.eval_set_selection import (
    EVAL_SET_SELECTION_VERSION,
    INSPECT_EVAL_SET_SELECTION,
    EvalSetSelection,
    EvalSetSelectionOverrides,
    EvalSetSelectionTask,
)
from inspect_ai._eval.evalset import task_identifier
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


def _acp_probe_tasks(
    observed: list[bool], discovered: list[tuple[int, str]] | None = None
) -> list[Task]:
    """One sample that records whether ACP is the live human channel."""

    @solver
    def observe_acp() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            from inspect_ai.agent._acp.discovery import list_discovered_evals
            from inspect_ai.agent._acp.server import acp_server_accepting_clients

            observed.append(acp_server_accepting_clients())
            if discovered is not None:
                discovered.extend(
                    (e.pid, str(e.target.socket_path)) for e in list_discovered_evals()
                )
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def always_correct() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    return [
        Task(
            dataset=[Sample(id="one", input="one")],
            solver=observe_acp(),
            scorer=always_correct(),
            name="acp_probe",
        )
    ]


@pytest.fixture
def short_acp_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the ACP discovery dir at /tmp so AF_UNIX paths fit in 104 bytes.

    pytest's `tmp_path` is buried under `/private/var/folders/...` on macOS,
    which is over the limit before the socket name is appended.
    """
    import shutil
    import tempfile

    dirpath = Path(tempfile.mkdtemp(prefix="acp_", dir="/tmp"))
    monkeypatch.setattr(
        "inspect_ai.agent._acp.discovery.inspect_data_dir",
        lambda subdir: _mkdir(dirpath / (subdir or "")),
    )
    try:
        yield dirpath
    finally:
        shutil.rmtree(dirpath, ignore_errors=True)


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="AF_UNIX sockets not available."
)
def test_eval_set_selection_binds_an_acp_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, short_acp_dir: Path
) -> None:
    """A selection-mode worker is reachable over ACP without being asked.

    Detached, the human-input chain is ACP -> Textual panel -> console, and a
    worker has neither of the last two. Binding the server is what turns
    `approver: human` and `ask_user()` from an errored sample in a successful
    log into a sample that parks for someone to attach to.
    """
    observed: list[bool] = []
    discovered: list[tuple[int, str]] = []

    kwargs: dict[str, Any] = dict(
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="plain",
    )
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(tasks=_acp_probe_tasks([]), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    # nothing bound during the enumeration pass -- it never runs a sample
    assert observed == []

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        selection_for(capture.tasks[0].identifier).model_dump_json()
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        success, logs = eval_set(tasks=_acp_probe_tasks(observed, discovered), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)

    assert success
    assert logs[0].status == "success"
    # the routing shims commit to ACP rather than falling through to a panel
    # and a console that are not there
    assert observed == [True]
    # and the socket is discoverable from the pid, which is all an external
    # runner knows about the worker it spawned
    expected = (short_acp_dir / "acp" / f"{os.getpid()}.sock").resolve()
    assert discovered == [(os.getpid(), str(expected))]


def test_eval_set_selection_fails_on_an_unbindable_acp_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A worker that cannot bind its ACP server fails at startup.

    Worker mode is detached: ACP *is* the human channel, and the panel and
    console the routing would otherwise fall through to are a display that
    does not exist and a closed stdin. So a path that cannot be bound (here,
    one past the `sun_path` limit) is not a lost surface with a fallback
    behind it -- it is a worker that would run until something asked for a
    person and then error a sample, which is worth refusing up front.
    """
    too_long = tmp_path / ("d" * 120)
    monkeypatch.setattr(
        "inspect_ai.agent._acp.discovery.inspect_data_dir",
        lambda subdir: _mkdir(too_long / (subdir or "")),
    )

    observed: list[bool] = []
    kwargs: dict[str, Any] = dict(
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="plain",
    )
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(tasks=_acp_probe_tasks([]), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        selection_for(capture.tasks[0].identifier).model_dump_json()
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        with pytest.raises(OSError, match="path too long"):
            eval_set(tasks=_acp_probe_tasks(observed), **kwargs)
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)

    # it failed before running a sample rather than while pretending to work
    assert observed == []


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


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


def test_eval_set_selection_log_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A selection's `log_dir` redirects the worker, leaving the definition's untouched."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = capture.tasks[0]

    definition_log_dir = tmp_path / "definition-logs"
    override_log_dir = tmp_path / "scratch" / "smoke"
    selection = selection_for(selected.identifier)
    selection.overrides = EvalSetSelectionOverrides(log_dir=str(override_log_dir))

    success, logs = run_selection(monkeypatch, tmp_path, selection, definition_log_dir)

    assert success
    # the override directory is created and receives the log...
    assert len(list_eval_logs(str(override_log_dir))) == 1
    assert logs[0].location.startswith(str(override_log_dir))
    # ...and the definition's own log directory is left entirely alone, which is
    # the property a rehearsal run depends on
    assert not definition_log_dir.exists()
    # identifiers are unaffected by the redirect: the task the runner asked for
    # is the task that ran, even though it was enumerated against another dir
    assert logs[0].eval.task == selected.name


def test_eval_set_selection_max_samples_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A selection's `max_samples` overrides the definition's sample concurrency."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = capture.tasks[0]

    selection = selection_for(selected.identifier)
    selection.overrides = EvalSetSelectionOverrides(max_samples=3)

    success, logs = run_selection(
        monkeypatch,
        tmp_path,
        selection,
        tmp_path / "logs",
        max_samples=11,
    )

    assert success
    assert logs[0].eval.config.max_samples == 3


def test_eval_set_selection_limit_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A selection's `limit` truncates the worker's dataset without moving its identity.

    The property a rehearsal rests on, and the reason `limit` is allowed to be
    an override at all: `task_identifier` hashes a task's *execution* limits and
    not its dataset slice, so a worker running one sample of a task still
    matches the manifest row enumerated for all of them.
    """
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    # this one has two samples, so a limit of one is visible in the result
    selected = next(t for t in capture.tasks if t.name == "selection_task_one")

    selection = selection_for(selected.identifier)
    selection.overrides = EvalSetSelectionOverrides(limit=1)

    success, logs = run_selection(monkeypatch, tmp_path, selection, tmp_path / "logs")

    assert success
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 1
    assert task_identifier(logs[0], None) == selected.identifier


def test_eval_set_selection_limit_override_as_a_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `(start, stop)` limit is a slice, and survives the JSON round trip as one."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = next(t for t in capture.tasks if t.name == "selection_task_one")

    selection = selection_for(selected.identifier)
    selection.overrides = EvalSetSelectionOverrides(limit=(1, 2))

    success, logs = run_selection(monkeypatch, tmp_path, selection, tmp_path / "logs")

    assert success
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 1
    # the second sample rather than the first, which is what makes it a slice
    # (the returned logs are headers, so the samples come from a full read)
    full = read_eval_log(logs[0].location)
    assert full.samples is not None
    assert [sample.input for sample in full.samples] == ["2+2"]
    assert task_identifier(logs[0], None) == selected.identifier


def test_eval_set_selection_max_sandboxes_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A selection's `max_sandboxes` reaches the worker's config."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = capture.tasks[0]

    selection = selection_for(selected.identifier)
    selection.overrides = EvalSetSelectionOverrides(max_sandboxes=2)

    success, logs = run_selection(monkeypatch, tmp_path, selection, tmp_path / "logs")

    assert success
    assert logs[0].eval.config.max_sandboxes == 2


def test_eval_set_selection_max_tasks_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A selection's `max_tasks` reaches the worker and outranks the definition.

    The override a runner giving one worker several tasks cannot do without.
    Every other field left unset falls back to what the definition passed;
    `max_tasks` does not, because `eval_set()` fills its own default in below
    the selection branch — so a worker with no override gets `eval()`'s rule
    rather than anyone's decision.
    """
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = [t for t in capture.tasks if t.model == "mockllm/model"]
    assert len(selected) == 2

    selection = EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id="worker-test",
        tasks=[EvalSetSelectionTask(identifier=t.identifier) for t in selected],
        overrides=EvalSetSelectionOverrides(max_tasks=2),
    )

    success, logs = run_selection(
        monkeypatch, tmp_path, selection, tmp_path / "logs", max_tasks=1
    )

    assert success
    assert len(logs) == 2
    assert [log.eval.config.max_tasks for log in logs] == [2, 2]


def test_eval_set_capture_records_what_a_runner_may_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The manifest carries the definition's values for every override.

    Without them a runner that sets one per worker cannot see what it is
    replacing, so a definition's explicit choice is silently overwritten by the
    runner's default.
    """
    capture = enumerate_eval_set(
        monkeypatch, tmp_path, max_samples=9, max_sandboxes=4, limit=3, max_tasks=2
    )

    assert capture.options["max_samples"] == 9
    assert capture.options["max_sandboxes"] == 4
    assert capture.options["limit"] == 3
    assert capture.options["max_tasks"] == 2


def test_eval_set_selection_overrides_default_to_the_definition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Omitting the container, or a field in it, keeps whatever the definition chose."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selected = capture.tasks[0]

    log_dir = tmp_path / "logs"
    selection = selection_for(selected.identifier)
    assert selection.overrides is None

    success, logs = run_selection(
        monkeypatch, tmp_path, selection, log_dir, max_samples=7
    )

    assert success
    assert logs[0].location.startswith(str(log_dir))
    assert logs[0].eval.config.max_samples == 7

    # and a container present but silent about a field is the same answer, which
    # is the case a runner setting only `log_dir` actually writes
    selection.overrides = EvalSetSelectionOverrides(log_dir=str(log_dir))
    success, logs = run_selection(
        monkeypatch, tmp_path, selection, log_dir, max_samples=7, name="partial"
    )

    assert success
    assert logs[0].eval.config.max_samples == 7


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("log_dir", "   ", "empty 'log_dir'"),
        ("max_samples", 0, "max_samples=0"),
        ("max_samples", -1, "max_samples=-1"),
        ("max_sandboxes", 0, "max_sandboxes=0"),
        ("max_tasks", 0, "max_tasks=0"),
        ("limit", 0, "limit=0"),
        ("limit", -1, "limit=-1"),
        # a range is a Python slice, so an unordered one selects nothing and an
        # empty one is the same mistake `limit=0` is
        ("limit", (5, 2), r"limit=\(5, 2\)"),
        ("limit", (3, 3), r"limit=\(3, 3\)"),
        ("limit", (-1, 4), r"limit=\(-1, 4\)"),
    ],
)
def test_eval_set_selection_invalid_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    """A nonsense override is a runner bug, reported rather than silently applied."""
    selection = selection_for("unused@unused#unused/unused/unused")
    selection.overrides = EvalSetSelectionOverrides.model_validate({field: value})
    with pytest.raises(PrerequisiteError, match=match):
        run_selection(monkeypatch, tmp_path, selection, tmp_path / "logs")


@pytest.mark.parametrize("declared", [1, 2])
def test_eval_set_selection_overrides_require_their_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, declared: int
) -> None:
    """An older document may not use the v3 container, though one model parses both.

    The declared version is what an older inspect gates on, so honouring it here
    while that inspect rejects it as an unknown field would make the same
    document behave two different ways. It matters most for `limit`: ignored, it
    means a worker asked for two samples runs the whole dataset.
    """
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "version": declared,
                "eval_set_id": "worker-test",
                "tasks": [{"identifier": "whatever"}],
                "overrides": {"limit": 2},
            }
        )
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        with pytest.raises(
            PrerequisiteError, match=f"version {declared} but sets overrides"
        ):
            eval_set(
                tasks=[selection_task_one()],
                model=MODELS,
                log_dir=str(tmp_path / "logs"),
                display="plain",
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)


def test_eval_set_selection_v1_document_still_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A v1 document that uses no later fields keeps working."""
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "version": 1,
                "eval_set_id": "worker-test",
                "tasks": [{"identifier": capture.tasks[0].identifier}],
            }
        )
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        success, logs = eval_set(
            tasks=[selection_task_one(), selection_task_two()],
            model=MODELS,
            log_dir=str(tmp_path / "logs"),
            display="plain",
        )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)
    assert success
    assert logs[0].eval.eval_set_id == "worker-test"


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_samples", True),
        ("max_samples", "3"),
        ("max_samples", 3.0),
        ("max_sandboxes", True),
        ("max_tasks", True),
        # a `limit` read leniently is the worst of these: `true` as 1 pins
        # concurrency, but a dropped or coerced limit runs five thousand samples
        # where two were asked for
        ("limit", True),
        ("limit", "3"),
        ("limit", 3.0),
        ("limit", [1, "5"]),
        ("limit", [1, 2, 3]),
    ],
)
def test_eval_set_selection_override_ints_are_strict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, value: object
) -> None:
    """Lax coercion would read `true` as 1, silently pinning what it touches."""
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "version": EVAL_SET_SELECTION_VERSION,
                "eval_set_id": "worker-test",
                "tasks": [{"identifier": "whatever"}],
                "overrides": {field: value},
            }
        )
    )
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        with pytest.raises(PrerequisiteError, match="Unable to read"):
            eval_set(
                tasks=[selection_task_one()],
                model=MODELS,
                log_dir=str(tmp_path / "logs"),
                display="plain",
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)


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
        (
            json.dumps(
                {
                    "version": 1,
                    "eval_set_id": "x",
                    "tasks": [{"identifier": "y"}, {"identifier": "y"}],
                }
            ),
            "names the same task more than once: y",
        ),
        # a misspelled optional field must fail rather than be dropped: read as
        # `resume=None`, this selection would silently rerun completed samples
        (
            json.dumps(
                {
                    "version": 1,
                    "eval_set_id": "x",
                    "tasks": [{"identifier": "y", "resuem": "prior.eval"}],
                }
            ),
            "resuem",
        ),
        (
            json.dumps(
                {
                    "version": 1,
                    "eval_set_id": "x",
                    "runner_notes": "unknown",
                    "tasks": [{"identifier": "y"}],
                }
            ),
            "runner_notes",
        ),
        # a version this inspect doesn't understand is reported as a version
        # mismatch even when the newer schema's fields are what fail validation
        (
            json.dumps(
                {
                    "version": 99,
                    "eval_set_id": "x",
                    "tasks": [{"identifier": "y", "field_from_v99": True}],
                }
            ),
            "schema version 99",
        ),
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


def test_eval_set_selection_parks_for_keep_alive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`ctl_server="keep"` parks a worker, exactly as it does an eval set.

    Selection mode returns before the eval-set park; the inner `eval()` runs
    with an eval_set_id so it doesn't park either. Without a park of its own a
    worker would silently exit instead of keeping its control surface up. A spy
    stands in for the (blocking) park.
    """
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    async def spy(eval_set_id: str, log_dir: str) -> None:
        captured["eval_set_id"] = eval_set_id
        captured["states"] = [s.task for s in get_eval_states()]

    monkeypatch.setattr("inspect_ai._eval.evalset._keep_alive_park", spy)

    success, _ = run_selection(
        monkeypatch,
        tmp_path,
        selection_for(capture.tasks[0].identifier, eval_set_id="parked-set"),
        tmp_path / "logs",
        ctl_server="keep",
    )

    assert success
    assert captured.get("eval_set_id") == "parked-set", "keep-alive park not entered"
    # the run's eval states are still registered at park time (they're what
    # `inspect ctl task list` shows through the lingering window)
    assert captured["states"] == ["selection_task_one"]


def test_eval_set_selection_clears_run_registries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A worker clears the process-scoped registries at its run boundary.

    The inner `eval()` leaves this to its caller when an eval_set_id is set, so
    a worker that returned without cleaning up would leak EvalStates (and
    config / limit overrides) into whatever the process does next.
    """
    capture = enumerate_eval_set(monkeypatch, tmp_path)
    run_selection(
        monkeypatch,
        tmp_path,
        selection_for(capture.tasks[0].identifier),
        tmp_path / "logs",
    )
    assert get_eval_states() == []


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
    },
    # v2 added the optional operational overrides `log_dir` and `max_samples`.
    # Additive though they are, the models forbid extra fields, so a v1 reader
    # would reject a document carrying them as an unknown-field error rather
    # than the version gate's actionable "upgrade inspect" -- which is exactly
    # why adding a field bumps the version here. v1 documents remain readable:
    # both overrides default to None, meaning "keep the definition's value".
    2: {
        "selection": {"version", "eval_set_id", "tasks", "log_dir", "max_samples"},
        "task": {"identifier", "resume"},
    },
    # v3 moved the overrides into a container of their own and added `limit` and
    # `max_sandboxes`. A clean break rather than a migration: nothing is
    # shipped, the runner writing these documents is the only one there is, and
    # no deployment reads v1 or v2 -- so the two fields moved rather than being
    # kept as accepted legacy, with no dual shape to carry. What the container
    # fixes is that `version`, `eval_set_id`, and `tasks` are the protocol while
    # the rest are knobs, and at v3 there are four of them.
    3: {
        "selection": {"version", "eval_set_id", "tasks", "overrides"},
        "task": {"identifier", "resume"},
        "overrides": {"log_dir", "max_samples", "limit", "max_sandboxes"},
    },
    # v4 added `max_tasks`, for a runner that gives one worker several tasks.
    # It is the one override whose absence is not neutral: every other field
    # left unset keeps what the definition passed, but `eval_set()` fills
    # `max_tasks` in below the selection branch, so an unset one falls through
    # to `eval()`'s own rule (one task at a time for a single model, the model
    # count for several) rather than to anything the definition chose.
    4: {
        "selection": {"version", "eval_set_id", "tasks", "overrides"},
        "task": {"identifier", "resume"},
        "overrides": {
            "log_dir",
            "max_samples",
            "limit",
            "max_sandboxes",
            "max_tasks",
        },
    },
    # v5 added the first fields to a *task* entry since v1, and they are the
    # first that are neither protocol nor knob: `registry_name` and `args_hash`
    # are an optimization hint, letting a worker skip constructing the tasks it
    # was not selected to run rather than paying for every dataset in the eval
    # set to find its own. `identifier` remains the only field that decides
    # anything -- these may be absent, and could be wrong, without changing
    # what runs (see eval_set_pruning.py).
    5: {
        "selection": {"version", "eval_set_id", "tasks", "overrides"},
        "task": {"identifier", "resume", "registry_name", "args_hash"},
        "overrides": {
            "log_dir",
            "max_samples",
            "limit",
            "max_sandboxes",
            "max_tasks",
        },
    },
}


def test_eval_set_selection_schema_stability() -> None:
    assert EVAL_SET_SELECTION_VERSION in _EXPECTED_SELECTION_FIELDS
    expected = _EXPECTED_SELECTION_FIELDS[EVAL_SET_SELECTION_VERSION]
    assert set(EvalSetSelection.model_fields.keys()) == expected["selection"]
    assert set(EvalSetSelectionTask.model_fields.keys()) == expected["task"]
    assert set(EvalSetSelectionOverrides.model_fields.keys()) == expected["overrides"]
    # the field sets above are the whole format: loosening this would let a
    # runner's typo through as a silently dropped field
    assert EvalSetSelection.model_config.get("extra") == "forbid"
    assert EvalSetSelectionTask.model_config.get("extra") == "forbid"
    assert EvalSetSelectionOverrides.model_config.get("extra") == "forbid"
    # and no override may participate in task identity, which is what stops one
    # desynchronizing a worker from the capture manifest. `time_limit` is the
    # field this rules out, so its absence is the assertion worth making
    assert "time_limit" not in EvalSetSelectionOverrides.model_fields
