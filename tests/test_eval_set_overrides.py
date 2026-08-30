"""Operational overrides for an externally-driven eval set.

The claim under test is the one that makes the override surface *derived*
rather than curated: an `eval_set()` argument is overridable if and only if
`task_identifier()` ignores it. Everything else here is the two ends of the
document — that a run-wide file reaches capture as well as a worker, and that
a worker's own container wins where both speak.
"""

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
)
from inspect_ai._eval.eval_set_overrides import (
    GENERATE_CONFIG_PARAMETER,
    INSPECT_EVAL_SET_OVERRIDES,
    NOT_OVERRIDABLE,
    EvalSetOverrides,
    EvalSetOverridesEpochs,
    check_eval_set_overrides,
    merge_eval_set_overrides,
    read_eval_set_overrides,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

# --- the partition -----------------------------------------------------------


def test_every_eval_set_parameter_is_overridable_or_says_why_not() -> None:
    """The whole of `eval_set()`'s signature is accounted for, by name.

    This is what stops the override surface drifting back into a curated list.
    A parameter added upstream lands in neither half and fails here, which is
    the moment to decide which half it belongs to — and the decision is not a
    matter of taste, since `task_identifier()` has already made it.
    """
    parameters = set(inspect.signature(eval_set).parameters)
    overridable = set(EvalSetOverrides.model_fields)
    # `kwargs` is the generate config, whose identity-neutral half travels as
    # `generate_config` and whose other half the field validator refuses
    accounted = overridable | set(NOT_OVERRIDABLE) | {GENERATE_CONFIG_PARAMETER}

    assert parameters - accounted == set(), (
        "eval_set() parameters are neither overridable nor excluded — add each "
        "to EvalSetOverrides if task_identifier() ignores it, or to "
        "NOT_OVERRIDABLE with the reason it is not overridable"
    )
    assert accounted - parameters - {"generate_config"} == set(), (
        "overrides or exclusions name something eval_set() no longer takes"
    )


def test_no_override_participates_in_task_identity() -> None:
    """The rule, stated against the fields the identifier actually hashes.

    An identity-bearing override desynchronizes a worker from the capture
    manifest: the log is written under an identifier the runner never recorded,
    so the task looks unstarted forever and the run never converges.
    """
    from inspect_ai._eval.evalset import EvalSetArgsInTaskIdentifier

    identity = set(EvalSetArgsInTaskIdentifier.__dataclass_fields__) - {"config"}

    assert identity & set(EvalSetOverrides.model_fields) == set()
    # and every one of them says so rather than being merely absent
    assert identity <= set(NOT_OVERRIDABLE)


def test_the_generate_config_override_is_the_identity_neutral_half() -> None:
    from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE

    for field in sorted(GENERATE_CONFIG_FIELDS_TO_EXCLUDE):
        EvalSetOverrides(generate_config=GenerateConfig(**{field: None}))

    with pytest.raises(ValueError, match="temperature"):
        EvalSetOverrides(generate_config=GenerateConfig(temperature=0.5))


# --- reading -----------------------------------------------------------------


def written(tmp_path: Path, document: dict[str, Any]) -> str:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_an_overrides_document_is_read(tmp_path: Path) -> None:
    overrides = read_eval_set_overrides(
        written(tmp_path, {"epochs": 2, "limit": [0, 5], "max_samples": 8})
    )

    assert overrides.epochs == 2
    assert overrides.limit == (0, 5)
    assert overrides.max_samples == 8


REFUSED: list[tuple[str, dict[str, Any], str]] = [
    ("an unknown field", {"wibble": 1}, "wibble"),
    ("a misspelled field", {"max_sample": 8}, "max_sample"),
    ("an identity-bearing field", {"time_limit": 60}, "time_limit"),
    # lax coercion would read each of these as a plausible number, which is
    # how a runner's templating bug pins a run to one concurrent sample
    ("a quoted count", {"max_samples": "8"}, "max_samples"),
    ("a boolean count", {"max_samples": True}, "max_samples"),
    ("a concurrency of zero", {"max_samples": 0}, "at least 1"),
    ("an empty log directory", {"log_dir": "  "}, "empty 'log_dir'"),
    ("a limit of zero", {"limit": 0}, "at least 1"),
    ("an inverted range", {"limit": [5, 5]}, "ordered and non-negative"),
    ("epochs of zero", {"epochs": 0}, "at least 1"),
    ("epochs of zero, spelled out", {"epochs": {"epochs": 0}}, "at least 1"),
]


@pytest.mark.parametrize(
    ("document", "says"),
    [(document, says) for _, document, says in REFUSED],
    ids=[case for case, _, _ in REFUSED],
)
def test_a_document_that_cannot_mean_anything_is_refused(
    document: dict[str, Any], says: str, tmp_path: Path
) -> None:
    with pytest.raises(PrerequisiteError, match=says):
        read_eval_set_overrides(written(tmp_path, document))


def test_an_absent_document_is_reported_by_name(tmp_path: Path) -> None:
    with pytest.raises(PrerequisiteError, match=INSPECT_EVAL_SET_OVERRIDES):
        read_eval_set_overrides(str(tmp_path / "missing.json"))


# --- the merge ---------------------------------------------------------------

MERGED: list[tuple[str, EvalSetOverrides | None, EvalSetOverrides | None, Any, Any]] = [
    ("neither said anything", None, None, None, None),
    ("only the run did", EvalSetOverrides(epochs=2), None, 2, None),
    ("only the worker did", None, EvalSetOverrides(max_samples=4), None, 4),
    (
        "each said a different thing",
        EvalSetOverrides(epochs=2),
        EvalSetOverrides(max_samples=4),
        2,
        4,
    ),
    (
        "both said the same thing",
        EvalSetOverrides(epochs=2, max_samples=1),
        EvalSetOverrides(max_samples=4),
        2,
        4,
    ),
]


def _round_tripped(overrides: EvalSetOverrides | None) -> EvalSetOverrides | None:
    if overrides is None:
        return None
    return EvalSetOverrides.model_validate_json(overrides.model_dump_json())


@pytest.mark.parametrize(
    ("run", "worker", "epochs", "max_samples"),
    [(run, worker, e, m) for _, run, worker, e, m in MERGED],
    ids=[case for case, _, _, _, _ in MERGED],
)
def test_a_workers_overrides_win_field_by_field(
    run: EvalSetOverrides | None,
    worker: EvalSetOverrides | None,
    epochs: int | None,
    max_samples: int | None,
) -> None:
    # field by field rather than document by document: a run-wide `epochs` has
    # to survive a worker that only names its own log directory.
    #
    # Round-tripped through JSON rather than passed as constructed, because
    # that is how a worker's container actually arrives -- `model_dump_json()`
    # writes every field, so a merge keying on *unset* sees a container that
    # sets all of them and silently wipes the run-wide document. Constructing
    # the models in Python hides exactly that bug.
    merged = merge_eval_set_overrides(_round_tripped(run), _round_tripped(worker))

    if epochs is None and max_samples is None:
        assert merged is None
    else:
        assert merged is not None
        assert merged.epochs == epochs
        assert merged.max_samples == max_samples


def test_epochs_carry_their_reducers() -> None:
    overrides = EvalSetOverrides.model_validate(
        {"epochs": {"epochs": 3, "reducer": ["mean", "max"]}}
    )

    assert isinstance(overrides.epochs, EvalSetOverridesEpochs)
    assert overrides.epochs.reducer == ["mean", "max"]


# --- capture honours the run-wide document ------------------------------------


@task
def overridable_task() -> Task:
    return Task(
        dataset=[Sample(input=str(n), target=str(n)) for n in range(5)],
        solver=[generate()],
        scorer=exact(),
    )


def test_capture_counts_the_samples_the_run_will_actually_have(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason the document is run-wide rather than per worker.

    `epochs` and `limit` change how many samples a task has. A selection that
    overrode them without capture seeing the same values would leave every
    per-task count in the manifest describing a run that is not happening, and
    every progress figure a runner derives from one wrong — silently, since
    nothing downstream compares them.
    """
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    monkeypatch.setenv(
        INSPECT_EVAL_SET_OVERRIDES, written(tmp_path, {"epochs": 3, "limit": 2})
    )

    with pytest.raises(SystemExit):
        eval_set(
            tasks=[overridable_task()],
            log_dir=str(tmp_path / "logs"),
            model="mockllm/model",
            display="plain",
            epochs=1,
        )

    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    (task,) = capture.tasks
    assert task.samples == 2
    assert task.epochs == 3
    # and `options` still records what the definition asked for, which is the
    # only way a runner learns what it displaced
    assert capture.options["epochs"] == 1
    assert capture.options["limit"] is None
    assert capture.overrides is not None
    assert capture.overrides.epochs == 3


def test_capture_counts_the_samples_a_sample_id_selects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sample_id` narrows a task exactly as `limit` does, and the count has to follow.

    Counting the whole dataset here is not a cosmetic error in a manifest: a
    runner comparing the count against a finished log sees one sample where it
    was told to expect five, calls the task short, and re-runs it until its
    attempt budget is gone. `log_samples_complete` reached the same wrong
    conclusion for a plain `eval_set(sample_id=...)` re-run, which is why both
    callers now take the count from `samples_selected`.
    """
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    monkeypatch.setenv(
        INSPECT_EVAL_SET_OVERRIDES, written(tmp_path, {"sample_id": ["1", "3"]})
    )

    with pytest.raises(SystemExit):
        eval_set(
            tasks=[overridable_task()],
            log_dir=str(tmp_path / "logs"),
            model="mockllm/model",
            display="plain",
        )

    capture = EvalSetCapture.model_validate_json(manifest_path.read_bytes())
    (task,) = capture.tasks
    assert task.samples == 2


def test_a_notification_url_is_refused_before_it_can_be_recorded() -> None:
    """A credential supplied as an option value, caught at the door rather than in a worker.

    `build_apprise` already refuses a `notification` string that is not a file
    — but it refuses it inside the worker, and a runner resolves overrides
    before it runs anything and typically writes them down first
    (inspect_steward commits them to git). By then the URL is in a repository.
    """
    found = check_eval_set_overrides(
        EvalSetOverrides(notification="slack://T000/B000/xoxb-secret")
    )

    assert found is not None
    field, detail = found
    assert field == "notification"
    assert "INSPECT_EVAL_NOTIFICATION" in detail


def test_a_notification_config_file_is_fine(tmp_path: Path) -> None:
    config = tmp_path / "apprise.cfg"
    config.write_text("mailto://example\n")

    assert (
        check_eval_set_overrides(EvalSetOverrides(notification=config.as_posix()))
        is None
    )


def test_a_zero_dataset_memory_budget_is_a_real_setting() -> None:
    # `--max-dataset-memory` is an IntRange(min=0) and the budget multiplies
    # out to zero bytes, which pages every sample to disk -- unlike the
    # concurrency ceilings beside it, where zero admits nothing
    assert check_eval_set_overrides(EvalSetOverrides(max_dataset_memory=0)) is None

    found = check_eval_set_overrides(EvalSetOverrides(max_dataset_memory=-1))
    assert found is not None and found[0] == "max_dataset_memory"
