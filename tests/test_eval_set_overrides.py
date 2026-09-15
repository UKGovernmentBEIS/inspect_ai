"""Operational overrides for an externally-driven eval set.

The claim under test is the one that makes the override surface *derived*
rather than curated: an `eval_set()` argument is overridable if and only if
`task_identifier()` ignores it. Everything else here is the two ends of the
document — that a run-wide file reaches capture as well as a worker, and that
a worker's own container wins where both speak.
"""

import inspect
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from inspect_ai import Task, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
)
from inspect_ai._eval.eval_set_overrides import (
    GENERATE_CONFIG_PARAMETER,
    INSPECT_EVAL_SET_OVERRIDES,
    NOT_OVERRIDABLE,
    TRIGGER_KINDS,
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
from inspect_ai.util._checkpoint import CheckpointConfig
from inspect_ai.util._checkpoint._triggers.types import (
    BudgetPercent,
    CheckpointTrigger,
    CostInterval,
    Manual,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)

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


# --- only driven modes honour the run-wide document --------------------------


@task
def overridable_task() -> Task:
    return Task(
        dataset=[Sample(input=str(n), target=str(n)) for n in range(5)],
        solver=[generate()],
        scorer=exact(),
    )


def test_an_ordinary_eval_set_ignores_the_run_wide_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overrides environment variable belongs to the runner protocol.

    A normal Python API call in an environment inherited from a runner must
    still mean what its definition says. Only capture and selection mode opt
    into the document.
    """
    monkeypatch.setenv(INSPECT_EVAL_SET_OVERRIDES, written(tmp_path, {"limit": 1}))

    success, logs = eval_set(
        tasks=[overridable_task()],
        log_dir=str(tmp_path / "logs"),
        model="mockllm/model",
        display="plain",
        limit=2,
    )

    assert success
    assert logs[0].results is not None
    assert logs[0].results.completed_samples == 2


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


def test_a_workers_generate_config_keeps_the_runs_other_settings() -> None:
    """`generate_config` is a container of settings, not one setting.

    Replaced wholesale, a worker that names `max_connections` would silently
    drop a run-wide `timeout` — and nothing downstream could tell, since the
    result is a valid config that simply runs with inspect's default.
    """
    merged = merge_eval_set_overrides(
        EvalSetOverrides(generate_config=GenerateConfig(timeout=60, max_retries=3)),
        EvalSetOverrides(generate_config=GenerateConfig(max_connections=4)),
    )

    assert merged is not None and merged.generate_config is not None
    assert merged.generate_config.max_connections == 4
    assert merged.generate_config.timeout == 60
    assert merged.generate_config.max_retries == 3


def test_a_worker_can_still_replace_one_generate_config_setting() -> None:
    merged = merge_eval_set_overrides(
        EvalSetOverrides(generate_config=GenerateConfig(timeout=60)),
        EvalSetOverrides(generate_config=GenerateConfig(timeout=10)),
    )

    assert merged is not None and merged.generate_config is not None
    assert merged.generate_config.timeout == 10


@pytest.mark.parametrize(
    ("overrides", "beside"),
    [
        (EvalSetOverrides(sample_id=["a"], limit=5), "limit"),
        (EvalSetOverrides(sample_id=["a"], sample_shuffle=42), "sample_shuffle"),
    ],
    ids=["limit", "sample_shuffle"],
)
def test_a_document_selecting_samples_two_ways_is_refused(
    overrides: EvalSetOverrides, beside: str
) -> None:
    """The rule `eval()` enforces at its own door, enforced where the document is written.

    Refused here, a runner learns at launch; left to `eval()`, it learns once
    per worker, hours later, after a manifest naming the contradiction has
    already been committed. It is also what makes `_overridden_selection`
    well defined: displacing whichever side the override did not name only
    makes sense while a document cannot name both.
    """
    found = check_eval_set_overrides(overrides)

    assert found is not None
    field, detail = found
    assert field == "sample_id"
    assert beside in detail


SELECTION: list[tuple[str, dict[str, Any], dict[str, Any], tuple[Any, Any, Any]]] = [
    (
        "silence keeps everything",
        {"limit": 5, "sample_id": None, "sample_shuffle": None},
        {},
        (5, None, None),
    ),
    (
        "ids displace a limit",
        {"limit": 5, "sample_id": None, "sample_shuffle": None},
        {"sample_id": ["a", "b"]},
        (None, ["a", "b"], None),
    ),
    (
        "ids displace a shuffle",
        {"limit": None, "sample_id": None, "sample_shuffle": 42},
        {"sample_id": ["a"]},
        (None, ["a"], None),
    ),
    (
        "a limit displaces ids",
        {"limit": None, "sample_id": ["a", "b"], "sample_shuffle": None},
        {"limit": 5},
        (5, None, None),
    ),
    (
        "a shuffle displaces ids",
        {"limit": None, "sample_id": ["a"], "sample_shuffle": None},
        {"sample_shuffle": 42},
        (None, None, 42),
    ),
    (
        "a limit and a shuffle still compose",
        {"limit": None, "sample_id": None, "sample_shuffle": 42},
        {"limit": 5},
        (5, None, 42),
    ),
]


@pytest.mark.parametrize(
    ("definition", "overridden", "expected"),
    [
        (definition, overridden, expected)
        for _, definition, overridden, expected in SELECTION
    ],
    ids=[case for case, _, _, _ in SELECTION],
)
def test_the_three_selectors_are_overridden_as_one_choice(
    definition: dict[str, Any],
    overridden: dict[str, Any],
    expected: tuple[Any, Any, Any],
) -> None:
    """`eval()` forbids `sample_id` beside either of the other two.

    Applied as three independent fields, a definition naming `sample_id` and a
    runner saying `--limit 5` leave both set: capture counts by the ids and
    writes a manifest, and then every worker raises. The launch succeeds and
    the whole fleet fails, hours later and one worker at a time.

    It is also the only reading that lets an override say what it means. With
    `None` meaning *keep the definition's*, there is otherwise no way at all to
    say *ignore the ids and take the first five*.
    """
    from inspect_ai._eval.evalset import _overridden_selection

    resolved = _overridden_selection(
        definition["limit"],
        definition["sample_id"],
        definition["sample_shuffle"],
        EvalSetOverrides(
            limit=overridden.get("limit"),
            sample_id=overridden.get("sample_id"),
            sample_shuffle=overridden.get("sample_shuffle"),
        ),
    )

    assert resolved == expected
    # and whatever comes out is a combination `eval()` accepts
    limit, sample_id, sample_shuffle = resolved
    assert sample_id is None or (limit is None and sample_shuffle is None)


# --- the run-wide document and one worker's ----------------------------------


def test_a_workers_selector_takes_the_whole_trio() -> None:
    """The three move together across the merge, as they do everywhere else.

    Merged field by field, a run-wide `sample_id` and a worker `limit` both
    survive into a document `eval()` refuses — and whichever the application
    happens to prefer silently discards the *narrower* instruction, which is
    the one the split exists to let a worker give.
    """
    merged = merge_eval_set_overrides(
        EvalSetOverrides(sample_id=["run-id"]), EvalSetOverrides(limit=5)
    )
    assert merged is not None
    assert (merged.limit, merged.sample_id, merged.sample_shuffle) == (5, None, None)

    # and the other direction, which is the same rule rather than a special case
    reversed = merge_eval_set_overrides(
        EvalSetOverrides(limit=5, sample_shuffle=42), EvalSetOverrides(sample_id=["w"])
    )
    assert reversed is not None
    assert (reversed.limit, reversed.sample_id, reversed.sample_shuffle) == (
        None,
        ["w"],
        None,
    )


def test_a_worker_silent_on_selection_keeps_the_runs() -> None:
    merged = merge_eval_set_overrides(
        EvalSetOverrides(sample_id=["run-id"]), EvalSetOverrides(log_dir="/logs")
    )
    assert merged is not None
    assert merged.sample_id == ["run-id"] and merged.log_dir == "/logs"


def test_only_the_generate_config_merges_by_its_members() -> None:
    """`epochs` is a value; `generate_config` is a container of them.

    A bare count means what `eval_set(epochs=5)` means — five epochs and the
    definition's reducers dropped. Merged by member it would inherit the
    run-wide reducers and quietly mean something no caller can write.
    """
    merged = merge_eval_set_overrides(
        EvalSetOverrides(epochs=EvalSetOverridesEpochs(epochs=3, reducer=["max"])),
        EvalSetOverrides(epochs=5),
    )
    assert merged is not None and merged.epochs == 5


def test_a_worker_epochs_object_still_replaces_whole() -> None:
    merged = merge_eval_set_overrides(
        EvalSetOverrides(epochs=EvalSetOverridesEpochs(epochs=3, reducer=["max"])),
        EvalSetOverrides(epochs=EvalSetOverridesEpochs(epochs=5)),
    )
    assert merged is not None
    assert isinstance(merged.epochs, EvalSetOverridesEpochs)
    assert merged.epochs.epochs == 5 and merged.epochs.reducer is None


# --- the wire format is strict all the way down ------------------------------

COERCIONS: list[tuple[str, dict[str, Any]]] = [
    ("a boolean where a count goes", {"generate_config": {"max_connections": True}}),
    ("a quoted count", {"generate_config": {"max_connections": "3"}}),
    ("a quoted timeout", {"generate_config": {"timeout": "60"}}),
    ("a boolean sample id", {"sample_id": True}),
    ("a boolean inside a sample id list", {"sample_id": ["a", True]}),
]


@pytest.mark.parametrize(
    "document",
    [document for _, document in COERCIONS],
    ids=[case for case, _ in COERCIONS],
)
def test_a_coercion_the_outer_fields_refuse_is_refused_inside_them_too(
    document: dict[str, Any],
) -> None:
    """The document is written by a template or a script, not typed by a person.

    `"3"` for three and `true` for one are that layer's characteristic
    mistakes, which is why every scalar here is a `Strict*`. `GenerateConfig`
    is not strict and `sample_id` was not either, so the two of them were the
    door left open in a wall built for exactly this.
    """
    with pytest.raises(ValidationError):
        EvalSetOverrides.model_validate(document)


def test_the_values_those_coercions_would_have_produced_are_still_accepted() -> None:
    # the refusals above are about the *spelling*, not the value
    assert (
        EvalSetOverrides.model_validate(
            {"generate_config": {"max_connections": 3}}
        ).generate_config
        is not None
    )
    assert EvalSetOverrides.model_validate({"sample_id": ["a", "b"]}).sample_id == [
        "a",
        "b",
    ]
    assert EvalSetOverrides.model_validate({"sample_id": 3}).sample_id == 3


# --- the document survives being written and read back -----------------------

TRIGGERS: list[tuple[str, CheckpointTrigger]] = [
    ("manual", Manual()),
    ("turn", TurnInterval(every=3)),
    ("time", TimeInterval(every=timedelta(minutes=10))),
    ("token", TokenInterval(every=500_000)),
    ("cost", CostInterval(every=2.5)),
    ("budget", BudgetPercent(budget="token", percent=25.0)),
]


def test_every_checkpoint_trigger_has_a_name_on_the_wire() -> None:
    """The table is the union, so a trigger added upstream is caught here."""
    assert set(TRIGGER_KINDS.values()) == {type(trigger) for _, trigger in TRIGGERS}


@pytest.mark.parametrize(
    "trigger", [trigger for _, trigger in TRIGGERS], ids=[kind for kind, _ in TRIGGERS]
)
def test_a_checkpoint_trigger_survives_the_round_trip(
    trigger: CheckpointTrigger,
) -> None:
    """Three of the six are the same JSON without a name for the kind.

    `TurnInterval`, `TokenInterval` and `CostInterval` are each `{"every": N}`,
    so an undiscriminated union reads whichever arm validates first — `turn`.
    `--checkpoint token:500k` therefore came back as a checkpoint every five
    hundred thousand *turns*, which for any ordinary run is checkpointing
    switched off, with nothing said.
    """
    overrides = EvalSetOverrides(checkpoint=CheckpointConfig(trigger=trigger))

    back = EvalSetOverrides.model_validate_json(overrides.model_dump_json())

    assert isinstance(back.checkpoint, CheckpointConfig)
    assert back.checkpoint.trigger == trigger
    assert type(back.checkpoint.trigger) is type(trigger)


def test_an_unnamed_trigger_is_refused_rather_than_guessed() -> None:
    # guessing would be picking one of three meanings at random and doing it
    # quietly, which is the failure the name exists to end
    with pytest.raises(ValidationError, match="kind"):
        EvalSetOverrides.model_validate({"checkpoint": {"trigger": {"every": 500}}})


def test_the_whole_document_survives_a_full_dump() -> None:
    """`model_dump_json()` writes every unset field as null, and that has to be readable.

    It was not. The nulls came back in `model_fields_set`, so a document
    carrying nothing but `max_connections` failed the identity check on
    `temperature` and every other field it had never set.
    """
    overrides = EvalSetOverrides(
        limit=5,
        sample_shuffle=None,
        generate_config=GenerateConfig(max_connections=4),
        checkpoint=CheckpointConfig(trigger=TokenInterval(every=500_000)),
        tags=["smoke"],
    )

    back = EvalSetOverrides.model_validate_json(overrides.model_dump_json())

    assert back == overrides
    assert back.generate_config is not None
    assert back.generate_config.model_fields_set == {"max_connections"}


def test_a_null_generate_config_member_keeps_the_definitions_value() -> None:
    """`None` means *keep what the definition chose* one level down too.

    Read as an instruction, `{"max_connections": null}` replaced a definition's
    seventeen with nothing — the opposite of what the field's own contract
    says, reachable from any document written with a plain `model_dump_json()`.
    """
    overrides = EvalSetOverrides.model_validate(
        {"generate_config": {"max_connections": None, "timeout": 60}}
    )

    assert overrides.generate_config is not None
    assert overrides.generate_config.model_fields_set == {"timeout"}
    applied = overrides.generate_config.model_dump(
        exclude_unset=True, exclude_none=True
    )
    assert applied == {"timeout": 60}
