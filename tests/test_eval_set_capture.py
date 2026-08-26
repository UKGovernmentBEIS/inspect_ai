import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from inspect_ai import Task, TaskSource, eval_set, task
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
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


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
    }
}


def test_eval_set_capture_schema_stability() -> None:
    assert EVAL_SET_CAPTURE_VERSION in _EXPECTED_CAPTURE_TASK_FIELDS
    assert (
        set(EvalSetCaptureTask.model_fields.keys())
        == _EXPECTED_CAPTURE_TASK_FIELDS[EVAL_SET_CAPTURE_VERSION]
    )
    # empty task args hash (also pinned in test_task_identifier_version.py)
    assert (
        task_args_hash({})
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
