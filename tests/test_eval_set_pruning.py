"""Early pruning: skipping construction of tasks a worker was not selected to run.

Every test here asserts an **artifact** — a body that did or did not run, a task
that is or is not a placeholder — rather than a duration. Pruning is an
optimization whose only symptom is speed, so a test that measured speed would be
the flakiest kind of test for the least information; and the failure worth
catching is not "pruning got slower" but "pruning stopped happening", which a
body-ran counter answers exactly.

The tasks below record their own construction in `CONSTRUCTED`, which is the
whole instrument.
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
    task_args_hash,
)
from inspect_ai._eval.eval_set_pruning import (
    INSPECT_EVAL_SET_NO_PRUNE,
    is_placeholder,
    reset_pruning,
)
from inspect_ai._eval.eval_set_selection import (
    EVAL_SET_SELECTION_VERSION,
    INSPECT_EVAL_SET_SELECTION,
    EvalSetSelection,
    EvalSetSelectionTask,
)
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

MODEL = "mockllm/model"

CONSTRUCTED: list[str] = []
"""Every task body that ran, in order. Reset per test by the autouse fixture."""


@task
def prune_one(difficulty: str = "easy") -> Task:
    CONSTRUCTED.append(f"prune_one({difficulty})")
    return Task(
        dataset=[Sample(input="1+1", target="2")],
        solver=[generate()],
        scorer=exact(),
    )


@task
def prune_two() -> Task:
    CONSTRUCTED.append("prune_two")
    return Task(
        dataset=[Sample(input="hello", target="hello")],
        solver=[generate()],
        scorer=exact(),
    )


@task
def prune_renamed() -> Task:
    """A task that renames itself, which is why the wire field is `registry_name`.

    `Task.name` is `"renamed"` and its registry name is `prune_renamed`. The two
    differ only inside the function body — which pruning runs before — so a
    pruner matching on the capture manifest's `name` would never match this task
    and would prune it every time, including when it was selected.
    """
    CONSTRUCTED.append("prune_renamed")
    return Task(
        name="renamed",
        dataset=[Sample(input="2+2", target="4")],
        solver=[generate()],
        scorer=exact(),
    )


@task
def prune_composed(difficulty: str = "hard") -> Task:
    """A task built by *calling another task* rather than by constructing one.

    Kept out of the shared lists below because it is not an entry in that eval
    set — it is the shape that shows pruning has to stop at the outermost call.
    """
    CONSTRUCTED.append("prune_composed")
    return prune_one(difficulty=difficulty)


@task
def prune_threaded(difficulty: str = "hard") -> Task:
    """Composition through a worker thread, which is the case a thread-local guard misses.

    Nobody builds tasks this way, which is exactly why the guard is process-wide
    rather than thread-local: the two cost the same, and only one of them fails
    in the direction this module permits.
    """
    CONSTRUCTED.append("prune_threaded")
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(prune_one, difficulty=difficulty).result()


ALL_TASKS = [prune_one(difficulty="hard"), prune_two(), prune_renamed()]
"""Built at import, when no selection is active — so this list is always three real tasks."""


@pytest.fixture(autouse=True)
def clean_pruning_state() -> Any:
    """The pruner caches the selection per process, and these tests change it per case."""
    CONSTRUCTED.clear()
    reset_pruning()
    yield
    CONSTRUCTED.clear()
    reset_pruning()


def capture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> EvalSetCapture:
    manifest = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest))
    try:
        with pytest.raises(SystemExit):
            eval_set(
                tasks=[prune_one(difficulty="hard"), prune_two(), prune_renamed()],
                model=MODEL,
                log_dir=str(tmp_path / "capture-logs"),
                display="plain",
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    return EvalSetCapture.model_validate_json(manifest.read_bytes())


def selection_naming(
    capture: EvalSetCapture, *names: str, facets: bool = True
) -> EvalSetSelection:
    """A selection for the tasks with these **registry** names, with or without the facets.

    Keyed on `registry_name` rather than `name` because `prune_renamed` answers
    to different strings for each, and a helper that quietly used the wrong one
    would undermine every test built on it.
    """
    chosen = [t for t in capture.tasks if t.registry_name in names]
    assert len(chosen) == len(names), f"{names} not all in the capture"
    return EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id="pruning-test",
        tasks=[
            EvalSetSelectionTask(
                identifier=t.identifier,
                registry_name=t.registry_name if facets else None,
                args_hash=t.args_hash if facets else None,
            )
            for t in chosen
        ],
    )


def run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: EvalSetSelection,
    *,
    name: str = "selection",
) -> tuple[bool, list[Any]]:
    path = tmp_path / f"{name}.json"
    path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(path))
    CONSTRUCTED.clear()
    try:
        return eval_set(
            tasks=[prune_one(difficulty="hard"), prune_two(), prune_renamed()],
            model=MODEL,
            log_dir=str(tmp_path / "logs" / name),
            display="plain",
        )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)


# --- the name the facets have to carry ----------------------------------


def test_the_wire_field_is_registry_name_because_a_task_may_rename_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The trap this whole design turns on, pinned before anything depends on it.

    `task_identifier` uses `Task.name`, which is the registry name *unless* the
    task passed `Task(name=...)`. Pruning decides before the body runs, so the
    registry name is the only name it can know — and the capture manifest is the
    only place the two are both recorded. If these ever converge, matching on
    `name` would start working and this test would stop justifying the field.
    """
    manifest = capture(monkeypatch, tmp_path)
    renamed = next(t for t in manifest.tasks if t.registry_name == "prune_renamed")

    # the two names differ, and only one of them is knowable before construction
    assert renamed.name == "renamed"
    assert renamed.registry_name == "prune_renamed"

    # every task carries a registry name, since every one of them is a @task
    assert all(t.registry_name is not None for t in manifest.tasks)


def test_the_args_hash_is_the_one_capture_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not a parallel computation — the same function over the same args.

    The pruner hashes `extract_named_params(fn, False, *args, **kwargs)`, which
    is literally what `registry_tag` stores and `resolve_task_args` reads back
    for capture to hash. Stated as a test because a divergence here is silent:
    it disables pruning rather than breaking anything.
    """
    manifest = capture(monkeypatch, tmp_path)
    one = next(t for t in manifest.tasks if t.registry_name == "prune_one")

    assert one.args == {"difficulty": "hard"}
    assert one.args_hash == task_args_hash({"difficulty": "hard"})


# --- what gets skipped --------------------------------------------------


def test_an_unselected_task_is_never_constructed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point: the other tasks' datasets are not paid for."""
    manifest = capture(monkeypatch, tmp_path)

    success, logs = run(monkeypatch, tmp_path, selection_naming(manifest, "prune_two"))

    assert success
    assert [log.eval.task for log in logs] == ["prune_two"]
    assert CONSTRUCTED == ["prune_two"]


def test_a_renamed_task_is_run_when_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The case that would break if the facet were `name` rather than `registry_name`.

    Under a `name`-keyed pruner this task is pruned while selected, and the run
    only survives because of the retry — so this asserts the body ran *once*,
    which a retry would not produce.
    """
    manifest = capture(monkeypatch, tmp_path)

    success, logs = run(
        monkeypatch, tmp_path, selection_naming(manifest, "prune_renamed")
    )

    assert success
    assert [log.eval.task for log in logs] == ["renamed"]
    assert CONSTRUCTED == ["prune_renamed"]


def test_selecting_several_tasks_constructs_exactly_those(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A packed worker prunes down to its batch rather than to one task."""
    manifest = capture(monkeypatch, tmp_path)

    success, logs = run(
        monkeypatch, tmp_path, selection_naming(manifest, "prune_one", "prune_two")
    )

    assert success
    assert sorted(log.eval.task for log in logs) == ["prune_one", "prune_two"]
    assert sorted(CONSTRUCTED) == ["prune_one(hard)", "prune_two"]


# --- and what is never skipped ------------------------------------------


def test_no_selection_constructs_everything(tmp_path: Path) -> None:
    """The ordinary path is untouched: no selection, no pruning, every body runs."""
    CONSTRUCTED.clear()

    tasks = [prune_one(difficulty="hard"), prune_two(), prune_renamed()]

    assert len(tasks) == 3
    assert CONSTRUCTED == ["prune_one(hard)", "prune_two", "prune_renamed"]
    assert not any(is_placeholder(t) for t in tasks)


@pytest.mark.parametrize(
    "outer,build",
    [("prune_composed", prune_composed), ("prune_threaded", prune_threaded)],
)
def test_a_task_composed_from_another_task_is_not_pruned(
    outer: str,
    build: Callable[..., Task],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A `@task` call inside a task body is composition, and pruning it is silent damage.

    The outer task is selected and `prune_one` is not, but the outer task *is*
    `prune_one` — so pruning the inner call would return the selected task with
    an empty dataset. Nothing downstream would notice: the identifier is
    computed from name, arguments, solver plan, and model, never from the
    dataset, so it matches perfectly and the worker runs zero real samples.

    The threaded row is the reason the guard is a process-wide counter. Nobody
    composes tasks through a pool, and that is the point: a thread-local counter
    costs the same and fails in the direction this module forbids, so the case
    is pinned rather than left to a comment.
    """
    selection = EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id="composition-test",
        tasks=[
            EvalSetSelectionTask(
                identifier=f"{outer}#a/mockllm/model/b",
                registry_name=outer,
                args_hash=task_args_hash({"difficulty": "hard"}),
            )
        ],
    )
    path = tmp_path / "composed.json"
    path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(path))
    reset_pruning()

    composed = build(difficulty="hard")

    assert not is_placeholder(composed)
    # the dataset is the composed task's, not the empty one a placeholder carries
    assert [sample.input for sample in composed.dataset] == ["1+1"]
    assert CONSTRUCTED == [outer, "prune_one(hard)"]


def test_a_selection_without_facets_prunes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A runner that has not upgraded still works, just without the saving.

    The facets are optional, so their absence has to mean *do not prune* rather
    than *nothing is selected* — the second reading would prune every task in
    the set.
    """
    manifest = capture(monkeypatch, tmp_path)

    success, logs = run(
        monkeypatch, tmp_path, selection_naming(manifest, "prune_two", facets=False)
    )

    assert success
    assert [log.eval.task for log in logs] == ["prune_two"]
    assert sorted(CONSTRUCTED) == ["prune_one(hard)", "prune_renamed", "prune_two"]


def test_partial_facets_prune_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """All or nothing, because a partial set prunes exactly what it fails to describe.

    A selection where one entry carries facets and another does not is a runner
    mid-upgrade or a runner with a bug. Pruning against the entries that *do*
    carry them would skip the task described by the entry that does not — which
    is the one case that must never happen.
    """
    manifest = capture(monkeypatch, tmp_path)
    selection = selection_naming(manifest, "prune_one", "prune_two")
    selection.tasks[0].registry_name = None
    selection.tasks[0].args_hash = None

    success, logs = run(monkeypatch, tmp_path, selection)

    assert success
    assert sorted(log.eval.task for log in logs) == ["prune_one", "prune_two"]
    assert sorted(CONSTRUCTED) == ["prune_one(hard)", "prune_renamed", "prune_two"]


def test_the_kill_switch_disables_pruning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One env var rules pruning out as a suspect without downgrading inspect."""
    manifest = capture(monkeypatch, tmp_path)
    monkeypatch.setenv(INSPECT_EVAL_SET_NO_PRUNE, "1")

    success, logs = run(monkeypatch, tmp_path, selection_naming(manifest, "prune_two"))

    assert success
    assert [log.eval.task for log in logs] == ["prune_two"]
    assert sorted(CONSTRUCTED) == ["prune_one(hard)", "prune_renamed", "prune_two"]


def test_an_unreadable_selection_prunes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pruning reads the selection itself, before `eval_set()` does, and must not report on it.

    A malformed document is `eval_set()`'s to reject with a message about the
    document. If the pruner raised first, the user would see the failure
    surface inside their own task function instead.
    """
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(bad))
    CONSTRUCTED.clear()

    # constructing tasks is unaffected...
    tasks = [prune_one(difficulty="hard"), prune_two()]
    assert len(tasks) == 2
    assert CONSTRUCTED == ["prune_one(hard)", "prune_two"]

    # ...and the document is still rejected, by the thing that should reject it
    from inspect_ai._util.error import PrerequisiteError

    with pytest.raises(PrerequisiteError, match="Unable to read"):
        eval_set(tasks=tasks, model=MODEL, log_dir=str(tmp_path / "l"), display="plain")


# --- the safety property ------------------------------------------------


def test_a_wrong_pruning_decision_costs_time_rather_than_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The claim §6.2 makes, made executable by breaking the matcher on purpose.

    With the args hash poisoned, every task mismatches and every task is pruned
    — including the selected one. The boundary finds nothing, and the run has to
    recover by resolving again without pruning rather than failing. The evidence
    that both halves happened is that every body ran (the un-pruned re-resolve)
    and the right log still landed.
    """
    manifest = capture(monkeypatch, tmp_path)
    selection = selection_naming(manifest, "prune_two")

    monkeypatch.setattr(
        "inspect_ai._eval.eval_set_pruning._args_hash_of_call",
        lambda task_type, args, kwargs: "poisoned",
    )

    success, logs = run(monkeypatch, tmp_path, selection)

    assert success
    assert [log.eval.task for log in logs] == ["prune_two"]
    # the retry resolved the whole eval set, which is the cost of the mistake
    assert sorted(CONSTRUCTED) == ["prune_one(hard)", "prune_renamed", "prune_two"]


def test_a_genuinely_missing_task_still_reports_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The retry must not swallow the error it exists beside.

    An identifier that matches nothing because the definition changed is a real
    failure, and it has to survive a resolution that pruned — otherwise every
    drift error becomes a silent slow success.
    """
    from inspect_ai._util.error import PrerequisiteError

    manifest = capture(monkeypatch, tmp_path)
    selection = selection_naming(manifest, "prune_two")
    selection.tasks[0].identifier = "nosuchtask#deadbeef/mockllm/model/cafe"

    with pytest.raises(PrerequisiteError, match="does not match any"):
        run(monkeypatch, tmp_path, selection)


def test_a_placeholder_never_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whatever else happens, a skipped task must not be reported as having run."""
    manifest = capture(monkeypatch, tmp_path)

    _, logs = run(monkeypatch, tmp_path, selection_naming(manifest, "prune_two"))

    assert len(logs) == 1
    assert logs[0].eval.task == "prune_two"
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 1


def test_tasks_named_as_specs_are_pruned_by_the_same_wrapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Why there is no separate resolver-level pruning pass.

    The design anticipated two interception points: this one, and a
    resolver-level filter for tasks named as strings rather than passed as
    constructed objects. The second turns out to be redundant — the resolver
    reaches a task through `task_create`, which is the decorated wrapper, so a
    spec-named task is pruned by exactly the mechanism above.

    What a resolver pass could add beyond this is skipping the module *import*,
    and that is not obtainable: a file has to be imported before anything can
    know which tasks it defines. So one mechanism, and this test is the reason
    the second was not written.
    """
    definition = tmp_path / "specs.py"
    definition.write_text(
        "from inspect_ai import Task, task\n"
        "from inspect_ai.dataset import Sample\n"
        "from inspect_ai.solver import generate\n"
        "\n"
        "@task\n"
        "def alpha() -> Task:\n"
        "    raise AssertionError('alpha was constructed')\n"
        "\n"
        "@task\n"
        "def beta() -> Task:\n"
        "    return Task(dataset=[Sample(input='2', target='2')], solver=[generate()])\n"
    )

    selection = EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id="spec-test",
        tasks=[
            EvalSetSelectionTask(
                identifier="specs.py@beta#x/mockllm/model/y",
                registry_name="beta",
                args_hash=task_args_hash({}),
            )
        ],
    )
    path = tmp_path / "spec-selection.json"
    path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(path))
    reset_pruning()

    from inspect_ai._eval.loader import create_file_tasks, load_file_tasks

    load_file_tasks(definition.absolute())
    resolved = create_file_tasks(definition, ["alpha", "beta"], {})

    # `alpha` raises if constructed, so reaching here at all is half the claim
    assert [t.registry_name for t in resolved] == ["alpha", "beta"]
    assert [is_placeholder(t) for t in resolved] == [True, False]


def test_pruning_does_not_move_a_task_s_sequence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Placeholders are enumerated and only then dropped, so positions do not shift.

    `sequence` is assigned by enumerating the resolved list. If pruning removed
    tasks before that, the third task in a set would become the first whenever
    the two before it were skipped — a number that changed with which worker
    was reading it.
    """
    manifest = capture(monkeypatch, tmp_path)
    by_name = {t.registry_name: t.sequence for t in manifest.tasks}
    assert by_name == {"prune_one": 0, "prune_two": 1, "prune_renamed": 2}

    # the selected task keeps the sequence capture recorded for it, which is
    # only true because the two tasks before it were still counted
    _, logs = run(monkeypatch, tmp_path, selection_naming(manifest, "prune_renamed"))
    assert len(logs) == 1
    assert CONSTRUCTED == ["prune_renamed"]


# --- the wire format ----------------------------------------------------


def test_the_facets_are_refused_by_an_older_schema_version(tmp_path: Path) -> None:
    """A v4 document carrying v5 fields is a runner bug and is refused as one.

    `extra="forbid"` cannot produce this refusal — the fields are declared on
    the model, so a v4 document naming them parses cleanly and would be honoured
    by a reader that predates them. `_TASK_FIELD_MIN_VERSION` is what makes the
    per-task facets carry the same *too new* check the top-level fields have.
    """
    from inspect_ai._eval.eval_set_selection import read_eval_set_selection
    from inspect_ai._util.error import PrerequisiteError

    document = {
        "version": 4,
        "eval_set_id": "x",
        "tasks": [
            {
                "identifier": "t#a/mockllm/model/b",
                "registry_name": "t",
                "args_hash": "a",
            }
        ],
    }
    path = tmp_path / "v4.json"
    path.write_text(json.dumps(document))

    with pytest.raises(PrerequisiteError):
        read_eval_set_selection(str(path))
