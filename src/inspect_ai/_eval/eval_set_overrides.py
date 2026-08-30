"""Operational overrides for an externally-driven eval set.

An external runner drives `eval_set()` twice over: once in capture mode to
enumerate the eval set (`eval_set_manifest.py`), then once per worker in
selection mode to run a share of it (`eval_set_selection.py`). Both times the
*definition* supplies the arguments, because both times the definition is what
is executed — so a runner that needs a value other than the one the definition
passed has nowhere to say so. Environment variables do not help: `INSPECT_*`
variables supply *defaults*, and a definition that passes an argument
explicitly beats a default every time.

This module is where a runner says so. An overrides document is a JSON object
of `EvalSetOverrides`, reaching `eval_set()` two ways:

- `INSPECT_EVAL_SET_OVERRIDES` names a file that applies to the **whole run**,
  and is read in both capture and selection mode. That is what keeps the
  manifest describing the run that actually happens: `epochs` and `limit`
  decide how many samples a task has, so a selection that overrode them
  without capture seeing the same values would leave every per-task count in
  the manifest wrong, and every progress figure derived from one.
- a selection's own `overrides` container applies to **one worker**, and wins
  where both set the same field. A runner sets `log_dir`, `max_samples`, and
  `max_tasks` per worker as a matter of course; nothing else usually differs
  between them.

## What may be overridden, and why the answer is computed rather than chosen

**An eval-set argument is overridable if and only if `task_identifier()`
ignores it.** That is not a curated list — it is a partition of `eval_set()`'s
signature that `evalset.py` already computes, and `test_eval_set_overrides.py`
fails by name when a parameter is added that lands in neither half.

It is the right rule because the identifier is what pairs a task with its log
across retries and across runs. Override something identity-bearing and a
worker computes a different identifier than the capture manifest recorded,
which breaks resumption and deduplication silently — the log is written, the
runner cannot find it, and the task looks unstarted forever. Override
something identity-neutral and nothing downstream can tell.

Three things are true of the rule that are worth stating rather than
discovering:

**It inherits whatever the identity set gets wrong.** `sandbox` and
`model_base_url` are identity-neutral today and both plausibly change what a
task produces — a different image, a different gateway. Making them
overridable exposes that gap rather than creating it. The alternative is to
fix identity, which is a larger change with a compatibility cost
(`TASK_IDENTIFIER_VERSION`), and is not made here.

**Identity-neutral is not the same as free.** `epochs` and `limit` change how
many samples a task has, which is why the run-wide document exists and why
capture honours it. Anything else a future field can desynchronize belongs in
the manifest's `options` for the same reason.

**Not everything identity-neutral fits on a wire.** `approval` accepts a
`list[ApprovalPolicy]`, whose approvers are callables, and `epochs` accepts an
`Epochs` carrying `ScoreReducer` objects. The override surface covers the
serializable arms of both — a policy config or its name, an epoch count with
reducer names — and the un-serializable arms simply cannot be said from
outside the process. That is a property of the transport rather than a
judgement about the field.

Fields the rule admits but selection mode has already decided are excluded
with their reason recorded in `NOT_OVERRIDABLE`: `fail_on_error` is forced
`False` for a worker, task retry is disabled, and the eval-set orchestration
arguments (`retry_*`, `bundle_*`, `log_dir_allow_dirty`, `embed_viewer`) never
reach a worker at all.

## Versioning

The document has no version of its own. Every model here forbids extra fields,
so an inspect too old to know a field refuses the document by name rather than
ignoring it — which is the whole of what a version gate would buy for a
container whose fields are all optional. The selection document *does* carry a
version, and `overrides` is gated within it as a container
(`EVAL_SET_SELECTION_VERSION`); adding a field here bumps that version so a
selection carrying it is refused wholesale by an older reader.

This module is deliberately not part of the public API: the models here are a
wire format written by external runners (currently inspect_steward, which
imports them from this module).
"""

import os
from dataclasses import asdict
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
)

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file
from inspect_ai.approval._policy import ApprovalPolicyConfig
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_data.model_data import ModelCost
from inspect_ai.util import DisplayType, SandboxEnvironmentType
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

INSPECT_EVAL_SET_OVERRIDES = "INSPECT_EVAL_SET_OVERRIDES"


class EvalSetOverridesEpochs(BaseModel):
    """An epoch count with the reducers to combine its scores.

    The wire form of `Epochs`, which cannot be sent as itself because its
    reducers resolve to `ScoreReducer` callables. A bare integer says the count
    alone, exactly as `eval_set(epochs=4)` does — which means it drops a
    definition's reducers the same way that call would.
    """

    model_config = ConfigDict(extra="forbid")

    epochs: StrictInt
    """Number of epochs to repeat samples over."""

    reducer: str | list[str] | None = None
    """Registry name(s) of the reducers combining scores across epochs (`None` for the default)."""


class EvalSetOverrides(BaseModel):
    """How an eval set is operated, overriding what the definition passed.

    `None` on any field keeps the definition's value, which is also what an
    absent document means. Nothing here changes what is evaluated: every field
    is one `task_identifier()` ignores, and the module docstring gives the rule
    and the three things that are true of it.

    Strictness is per-field rather than model-wide, because model-wide strict
    mode would refuse the two coercions this format depends on — a JSON array
    becoming a tuple, and a JSON object becoming a nested model. Where a
    scalar can be read leniently it is `Strict*` instead: lax coercion would
    read `true` as `1` and `"3"` as `3`, so a runner's templating bug could
    silently pin a run to one concurrent sample rather than failing.

    `use_attribute_docstrings` is on so that a runner exposing these as flags
    of its own can take the help text from here rather than keeping a third
    copy of it in step with the other two.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    # --- where output goes ---------------------------------------------------

    log_dir: str | None = None
    """Log directory, overriding the definition's.

    The field the whole container was built for. `eval_set()` declares `log_dir` with no default, so every definition passes it explicitly and `INSPECT_LOG_DIR` can never win — a runner whose workers must write somewhere else (a rehearsal on local scratch rather than the definition's S3 bucket) has no other way to say so.
    """

    log_format: Literal["eval", "json"] | None = None
    """Log file format, overriding the definition's."""

    log_samples: StrictBool | None = None
    """Whether to log individual samples, overriding the definition's."""

    log_realtime: StrictBool | None = None
    """Whether to log sample events in realtime, overriding the definition's."""

    log_images: StrictBool | None = None
    """Whether to log base64-encoded images, overriding the definition's."""

    log_model_api: StrictBool | None = None
    """Whether to log model API calls, overriding the definition's."""

    log_refusals: StrictBool | None = None
    """Whether to log model refusals, overriding the definition's."""

    log_buffer: StrictInt | None = None
    """Samples to buffer before writing, overriding the definition's."""

    log_shared: StrictBool | StrictInt | None = None
    """Whether (and how often) to sync logs to a shared filesystem, overriding the definition's."""

    log_level: str | None = None
    """Console log level, overriding the definition's."""

    log_level_transcript: str | None = None
    """Transcript log level, overriding the definition's."""

    # --- how much of the dataset runs ----------------------------------------

    # `StrictInt` rather than `Field(strict=True)`, which pydantic cannot apply
    # to a union at all -- and strictness matters more here than anywhere else
    # in this model, because a `limit` read leniently is a rehearsal that runs
    # the whole dataset. The tuple arm stays lax about list-to-tuple so a JSON
    # `[1, 5]` round-trips; its members do not.
    limit: StrictInt | tuple[StrictInt, StrictInt] | None = None
    """Dataset slice, overriding the definition's: a sample count, or a `(start, end)` range."""

    sample_id: (
        StrictStr
        | StrictInt
        | list[StrictStr]
        | list[StrictInt]
        | list[StrictStr | StrictInt]
        | None
    ) = None
    """Specific sample id(s) to run, overriding the definition's."""

    sample_shuffle: StrictBool | StrictInt | None = None
    """Whether to shuffle the dataset (optionally with a seed), overriding the definition's."""

    epochs: StrictInt | EvalSetOverridesEpochs | None = None
    """Epochs to repeat samples over, overriding the definition's.

    Together with `limit`, this is why the run-wide document is read by capture as well as by a worker: both change a task's sample count, and a manifest whose counts describe a different run is one every progress figure is computed from.
    """

    # --- how fast it runs ----------------------------------------------------

    max_samples: StrictInt | None = None
    """Sample concurrency, overriding the definition's."""

    # the one override a worker running several tasks cannot do without, and
    # the default it displaces is not a stable one: outside selection mode
    # `eval_set()` fills `max_tasks` in itself, but that happens below the
    # selection branch, so a worker inherits `eval()`'s rule instead -- one
    # task at a time for a single model, the model count for several. A runner
    # that hands a worker five tasks and says nothing gets whichever of those
    # applies, having chosen neither.
    max_tasks: StrictInt | None = None
    """Task concurrency, overriding the definition's."""

    max_subprocesses: StrictInt | None = None
    """Subprocess concurrency, overriding the definition's."""

    max_sandboxes: StrictInt | None = None
    """Sandbox concurrency, overriding the definition's."""

    max_dataset_memory: StrictInt | None = None
    """Maximum MiB of dataset sample data to hold in memory per task, overriding the definition's. Zero pages every sample to disk."""

    generate_config: GenerateConfig | None = None
    """Model transport settings, overriding the definition's.

    Restricted to the fields `task_identifier()` excludes from the generate config — `max_retries`, `timeout`, `attempt_timeout`, `max_connections`, `adaptive_connections`, `batch`, `cache`, and `cache_prompt`. Every other generate-config field is part of what the model is asked to do, so setting one here is refused by name rather than silently changing task identity.
    """

    @field_validator("generate_config", mode="before")
    @classmethod
    def _strict_config(cls, value: object) -> object:
        """Validate a generate config as strictly as the scalars beside it.

        Every scalar on this model is a `Strict*`, because the document is written by a template or a script and the coercions pydantic performs by default are exactly that layer's mistakes: `"3"` for three, `true` for one. `GenerateConfig` is not strict, so a nested field slipped through the door the outer ones are bolted — `max_connections: true` became one connection, and nothing said so.

        A `before` validator rather than a stricter annotation, because the strictness has to reach *inside* the sub-model and `Strict*` on the field itself would only govern the outer shape.
        """
        if isinstance(value, dict):
            # a member explicitly `null` is silence, not an instruction. Whole
            # documents are written with `model_dump_json()`, which spells every
            # unset field that way -- so keeping them would put the identity-
            # bearing half of the config in `model_fields_set` and make a
            # document carrying nothing but `max_connections` fail the check
            # below, and would let `{"max_connections": null}` replace a
            # definition's seventeen with nothing at all
            supplied = {
                name: member
                for name, member in cast(dict[str, Any], value).items()
                if member is not None
            }
            return GenerateConfig.model_validate(supplied, strict=True)
        return value

    @field_validator("generate_config", mode="after")
    @classmethod
    def _identity_neutral_config(
        cls, value: GenerateConfig | None
    ) -> GenerateConfig | None:
        """Refuse a generate-config field that participates in task identity.

        Imported inside the validator: `evalset.py` imports this module, so a module-level import of its exclusion set would close a cycle.
        """
        if value is None:
            return value
        from .evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE

        bearing = sorted(value.model_fields_set - GENERATE_CONFIG_FIELDS_TO_EXCLUDE)
        if bearing:
            raise ValueError(
                f"sets {', '.join(bearing)}, which "
                f"{'is' if len(bearing) == 1 else 'are'} part of task identity "
                f"— only {', '.join(sorted(GENERATE_CONFIG_FIELDS_TO_EXCLUDE))} "
                f"may be overridden"
            )
        return value

    # --- what the run is made of, other than the evaluation ------------------

    model_base_url: str | None = None
    """Base URL for model API requests, overriding the definition's."""

    model_cost_config: str | dict[str, ModelCost] | None = None
    """Model pricing table (or a path to one), overriding the definition's."""

    sandbox: SandboxEnvironmentType | None = None
    """Sandbox environment, overriding the definition's."""

    sandbox_cleanup: StrictBool | None = None
    """Whether to clean up sandboxes after a task, overriding the definition's."""

    sandbox_prebuilt: StrictBool | None = None
    """Whether sandbox images are prebuilt, overriding the definition's."""

    checkpoint: CheckpointConfig | StrictBool | None = None
    """Sample checkpointing, overriding the definition's.

    A trigger travels with its kind named (`{"kind": "token", "every": 500000}`), which the union it belongs to cannot express on its own: `TurnInterval`, `TokenInterval` and `CostInterval` are all `{"every": N}`, so a document written from a `--checkpoint token:500k` came back as *every five hundred thousand turns* — checkpointing switched off, silently, for any run that does not take half a million turns.
    """

    @field_serializer("checkpoint")
    def _tag_trigger(self, value: CheckpointConfig | bool | None) -> Any:
        """Write the trigger's kind beside its fields."""
        if not isinstance(value, CheckpointConfig):
            return value
        # a dataclass rather than a model, so `asdict` rather than
        # `model_dump`; unset fields are dropped for the reason the nested
        # generate config drops them, which is that a document read back has
        # to say what it set and nothing else
        config = {
            name: field for name, field in asdict(value).items() if field is not None
        }
        if value.trigger is not None:
            config["trigger"] = {
                "kind": _trigger_kind(value.trigger),
                **asdict(value.trigger),
            }
        return config

    @field_validator("checkpoint", mode="before")
    @classmethod
    def _read_tagged_trigger(cls, value: object) -> object:
        """Build the trigger the document names, and refuse one it does not.

        An untagged trigger is not read as a default — it is refused. Two of the three shapes it could be mean different things by the same JSON, so guessing would be choosing one at random and doing it quietly, which is the failure this tag exists to end.
        """
        if not isinstance(value, dict):
            return value
        trigger = value.get("trigger")
        if not isinstance(trigger, dict):
            return value

        fields = dict(cast(dict[str, Any], trigger))
        kind = fields.pop("kind", None)
        if kind not in TRIGGER_KINDS:
            raise ValueError(
                f"checkpoint trigger must name its kind — one of "
                f"{', '.join(sorted(TRIGGER_KINDS))} — because "
                f"{'turn'!r}, {'token'!r} and {'cost'!r} triggers are "
                f"otherwise the same document"
            )
        # through a `TypeAdapter` rather than by calling the dataclass, so that
        # the field coercions still happen: `TimeInterval.every` is a
        # `timedelta`, and constructing it raw leaves the ISO string the wire
        # carries sitting in a field nothing will do arithmetic on
        adapter: TypeAdapter[Any] = TypeAdapter(TRIGGER_KINDS[cast(str, kind)])
        return {**value, "trigger": adapter.validate_python(fields)}

    approval: str | ApprovalPolicyConfig | None = None
    """Approval policy (or a path to one), overriding the definition's.

    The `list[ApprovalPolicy]` arm of the parameter is absent because its approvers are callables. A named policy or a policy config says the same thing from outside the process.
    """

    # --- what happens when something goes wrong -------------------------------

    retry_on_error: StrictInt | None = None
    """Sample-level retries before an error is recorded, overriding the definition's."""

    score_on_error: StrictBool | None = None
    """Whether to score samples that errored, overriding the definition's."""

    debug_errors: StrictBool | None = None
    """Whether to raise sample errors rather than recording them, overriding the definition's."""

    # --- what the run reports -------------------------------------------------

    score: StrictBool | None = None
    """Whether to score the run, overriding the definition's."""

    score_display: StrictBool | None = None
    """Whether to display scoring metrics, overriding the definition's."""

    tags: list[str] | None = None
    """Tags to stamp into the logs, overriding the definition's."""

    metadata: dict[str, Any] | None = None
    """Metadata to stamp into the logs, overriding the definition's."""

    notification: StrictBool | str | None = None
    """Notification target for run completion, overriding the definition's."""

    display: DisplayType | None = None
    """Display type, overriding the definition's."""

    trace: StrictBool | None = None
    """Whether to trace message interactions to the console, overriding the definition's."""


NOT_OVERRIDABLE: dict[str, str] = {
    "tasks": "the subject of the run rather than a way of operating it",
    "model": "part of task identity (the resolved task carries its own model)",
    "model_args": "part of task identity",
    "model_roles": "part of task identity",
    "task_args": "part of task identity",
    "solver": "part of task identity",
    "message_limit": "part of task identity",
    "token_limit": "part of task identity",
    "turn_limit": "part of task identity",
    "time_limit": "part of task identity",
    "working_limit": "part of task identity",
    "cost_limit": "part of task identity",
    "eval_set_id": "carried by the selection document itself",
    "scanner": "refused outright in selection mode (one scan directory, one writer)",
    "fail_on_error": "forced to False for a worker, so the runner adjudicates",
    "continue_on_fail": "moot once fail_on_error is False",
    "acp_server": "forced on for a worker, which is detached and cannot prompt",
    "ctl_server": "demoted to eval-set's own on/off, which owns the keep-alive park",
    "retry_attempts": "eval-set retry orchestration, which a worker never performs",
    "retry_wait": "eval-set retry orchestration, which a worker never performs",
    "retry_connections": "eval-set retry orchestration, which a worker never performs",
    "retry_cleanup": "eval-set retry orchestration, which a worker never performs",
    "retry_immediate": "eval-set retry orchestration, which a worker never performs",
    "bundle_dir": "eval-set bundling, which a worker skips",
    "bundle_overwrite": "eval-set bundling, which a worker skips",
    "embed_viewer": "eval-set bundling, which a worker skips",
    "log_dir_allow_dirty": "eval-set log directory bookkeeping, which a worker skips",
}
"""Every `eval_set()` parameter that is deliberately not overridable, and why.

Read by `test_eval_set_overrides.py` together with `EvalSetOverrides.model_fields`: the two must account for every parameter of `eval_set()` between them, so a parameter added upstream fails by name here rather than quietly landing outside the rule. `kwargs` is accounted for by `generate_config`, which carries the identity-neutral half of the generate config and refuses the rest.
"""

GENERATE_CONFIG_PARAMETER = "kwargs"
"""The `eval_set()` parameter `EvalSetOverrides.generate_config` stands in for."""

TRIGGER_KINDS: dict[str, type[CheckpointTrigger]] = {
    "manual": Manual,
    "turn": TurnInterval,
    "time": TimeInterval,
    "token": TokenInterval,
    "cost": CostInterval,
    "budget": BudgetPercent,
}
"""Every checkpoint trigger, by the word `--checkpoint` names it with.

The union these belong to is undiscriminated and three of its arms serialize identically — `TurnInterval`, `TokenInterval` and `CostInterval` are each `{"every": N}` — so a document has to carry the kind or pydantic picks the first arm that validates. It picked `turn`, which turned `--checkpoint token:500k` into a checkpoint every five hundred thousand turns.

Spelled with the CLI's words rather than the class names, so that a hand-written document and a `--checkpoint` argument say the same thing.
"""


def _trigger_kind(trigger: CheckpointTrigger) -> str:
    """The word a trigger is named by, for the wire."""
    for kind, cls in TRIGGER_KINDS.items():
        if type(trigger) is cls:
            return kind
    raise ValueError(f"unknown checkpoint trigger {type(trigger).__name__}")


SELECTORS = ("limit", "sample_id", "sample_shuffle")
"""The three fields that say *which* samples run, which move together.

`eval()` accepts `sample_id` with neither of the other two, so these cannot be resolved one at a time: every layer that combines two sources of them has to take all three from whichever source spoke, or produce a combination the run will refuse. `merge_eval_set_overrides` does that between the run-wide document and a worker's, `evalset._overridden_selection` between an overrides document and the definition, and `check_eval_set_overrides` refuses a single document that names both sides.
"""


def eval_set_overrides_requested() -> str | None:
    """Overrides path if a run-wide overrides document is named.

    Returns:
        The path named by the `INSPECT_EVAL_SET_OVERRIDES` environment variable, or `None` when none is (unset or empty are both treated as absent).
    """
    value = os.environ.get(INSPECT_EVAL_SET_OVERRIDES, "").strip()
    return value if value else None


def read_eval_set_overrides(overrides_path: str) -> EvalSetOverrides:
    """Read and validate a run-wide overrides document.

    Args:
        overrides_path: Path to the overrides JSON file.

    Returns:
        The overrides.

    Raises:
        PrerequisiteError: If the file cannot be read or parsed, or carries a value that cannot mean anything.
    """
    try:
        with file(overrides_path, mode="rb") as f:
            contents = f.read()
    except OSError as ex:
        raise _unreadable(overrides_path, ex) from ex

    try:
        overrides = EvalSetOverrides.model_validate_json(contents)
    except (ValidationError, ValueError) as ex:
        raise _unreadable(overrides_path, ex) from ex

    validate_eval_set_overrides(overrides, overrides_path)
    return overrides


def merge_eval_set_overrides(
    run: EvalSetOverrides | None, worker: EvalSetOverrides | None
) -> EvalSetOverrides | None:
    """Combine the run-wide overrides with one worker's, the worker winning.

    Field by field rather than document by document, so a run-wide `epochs` survives a worker that only sets `log_dir`. That is the arrangement the split is for: the run-wide document says what this run is, and the per-worker container says which share of it this process has.

    **`generate_config` merges by its own members, and it is the only field that does.** It is a container of independently-set settings rather than one value — the `**kwargs` an `eval_set()` caller spreads — so replacing it wholesale would let a worker that sets `max_connections` silently drop a run-wide `timeout`. Applying the rule one level down is the same rule, not an exception to it.

    The other sub-models are values rather than containers and must replace whole. `epochs` is the one that shows why: a bare count means what `eval_set(epochs=5)` means, which is *five epochs and the definition's reducers dropped*. Merged by member, a worker's bare five would inherit the run-wide `["max"]` and quietly mean something the caller cannot write.

    Args:
        run: Overrides for the whole run, or `None`.
        worker: Overrides for this worker, or `None`.

    Returns:
        The combined overrides, or `None` when neither source said anything.
    """
    if run is None:
        return worker
    if worker is None:
        return run
    # `None` rather than *unset* is what a worker's silence looks like, and the
    # difference is not academic: a selection is serialized with
    # `model_dump_json()`, which writes every field, so a container read back
    # off the wire has all of them set and none of them meaning anything. `None`
    # is the one reading that survives the round trip -- and it costs nothing,
    # since no field has a use for an explicit `None` that differs from silence.
    merged = run.model_copy()
    # the three selectors are one choice rather than three fields (see
    # `_overridden_selection`), so a worker naming any of them takes all three
    # -- merged field by field, a run-wide `sample_id` and a worker `limit`
    # both survive into a document that `eval()` refuses, and whichever the
    # application happens to prefer silently discards the *narrower*
    # instruction
    if any(getattr(worker, name) is not None for name in SELECTORS):
        for name in SELECTORS:
            setattr(merged, name, getattr(worker, name))
    for name in EvalSetOverrides.model_fields:
        if name in SELECTORS:
            continue
        value = getattr(worker, name)
        if value is None:
            continue
        if name == "generate_config" and isinstance(value, BaseModel):
            existing = getattr(run, name)
            if isinstance(existing, BaseModel):
                value = existing.model_copy(
                    update=value.model_dump(exclude_unset=True, exclude_none=True)
                )
        setattr(merged, name, value)
    return merged


def validate_eval_set_overrides(overrides: EvalSetOverrides, source: str) -> None:
    """Refuse an override whose value cannot mean anything.

    Args:
        overrides: The container to check.
        source: Path to the document the overrides came from, for the message.

    Raises:
        PrerequisiteError: An override carries a value that is not usable.
    """
    if (found := check_eval_set_overrides(overrides)) is not None:
        _, detail = found
        raise PrerequisiteError(
            f"The eval set overrides at '{source}' have {detail} "
            "(omit the field to keep the definition's value)."
        )


def check_eval_set_overrides(overrides: EvalSetOverrides) -> tuple[str, str] | None:
    """The first override whose value cannot mean anything, and what is wrong with it.

    Every override is optional, but an explicitly supplied nonsense value is a runner bug worth reporting rather than letting it surface as an empty path, a semaphore that admits nothing, or an empty dataset. Separated from the raising above so that a runner reading these from somewhere other than a file can name its own source — an environment variable, say — rather than being told about a path it never wrote.

    Args:
        overrides: The container to check.

    Returns:
        The offending field and a phrase describing the problem, or `None` where everything is usable.
    """
    for name in ("log_dir", "log_level", "log_level_transcript", "model_base_url"):
        value = getattr(overrides, name)
        if value is not None and not value.strip():
            return name, f"an empty '{name}'"
    # the same rule `build_apprise` applies, applied here so that it is applied
    # *early*. A runner resolves these before it runs anything and typically
    # persists them -- inspect_steward writes them into a manifest it commits to
    # git -- so a notification URL supplied as the option's value is a
    # credential in a repository by the time the worker rejects it. The URL
    # belongs in INSPECT_EVAL_NOTIFICATION, which `notification=True` reads and
    # nothing records
    if isinstance(overrides.notification, str) and not os.path.isfile(
        overrides.notification
    ):
        return (
            "notification",
            f"notification={overrides.notification!r}, which is not an existing "
            "file; supply URLs through the INSPECT_EVAL_NOTIFICATION "
            "environment variable with notification=true, so that they never "
            "end up somewhere they are recorded",
        )
    # the rule `eval()` enforces at its own door, enforced here so that a
    # document carrying the contradiction is refused where it is written rather
    # than where it is read. Applying the three selectors displaces whichever
    # side the override did not name, which is only well defined because a
    # document cannot name both
    if overrides.sample_id is not None:
        for name in ("limit", "sample_shuffle"):
            if getattr(overrides, name) is not None:
                return (
                    "sample_id",
                    f"sample_id and {name} together; they select samples two "
                    "different ways and `eval()` accepts only one",
                )
    for name in (
        "max_samples",
        "max_sandboxes",
        "max_tasks",
        "max_subprocesses",
        "log_buffer",
    ):
        value = getattr(overrides, name)
        if value is not None and value < 1:
            return name, f"{name}={value}; it must be at least 1"
    # zero is a real setting here rather than the degenerate one it is for the
    # concurrency ceilings above: `maybe_page_to_disk` multiplies it out to a
    # budget of zero bytes, which pages every sample to disk. `--max-dataset-
    # memory` is an `IntRange(min=0)` for the same reason
    if overrides.max_dataset_memory is not None and overrides.max_dataset_memory < 0:
        return (
            "max_dataset_memory",
            f"max_dataset_memory={overrides.max_dataset_memory}; it cannot be negative",
        )
    if overrides.retry_on_error is not None and overrides.retry_on_error < 0:
        return (
            "retry_on_error",
            f"retry_on_error={overrides.retry_on_error}; it cannot be negative",
        )
    if isinstance(overrides.limit, int):
        if overrides.limit < 1:
            return "limit", f"limit={overrides.limit}; it must be at least 1"
    elif overrides.limit is not None:
        start, end = overrides.limit
        # a half-open range as `eval_set()` reads it, so start == end is an
        # empty slice rather than one sample -- worth refusing for the same
        # reason limit=0 is
        if start < 0 or end <= start:
            return (
                "limit",
                f"limit=({start}, {end}); a range must be ordered and non-negative",
            )
    epochs = overrides.epochs
    count = epochs.epochs if isinstance(epochs, EvalSetOverridesEpochs) else epochs
    if count is not None and count < 1:
        return "epochs", f"epochs={count}; it must be at least 1"
    return None


def _unreadable(overrides_path: str, ex: Exception) -> PrerequisiteError:
    return PrerequisiteError(
        f"Unable to read the eval set overrides at '{overrides_path}' "
        f"(named by {INSPECT_EVAL_SET_OVERRIDES}):\n{ex}"
    )
