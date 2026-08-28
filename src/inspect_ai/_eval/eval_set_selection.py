"""Eval-set selection (worker) mode.

When the `INSPECT_EVAL_SET_SELECTION` environment variable names a JSON file
containing an `EvalSetSelection`, `eval_set()` resolves its tasks normally and
then runs only the selected ones through the ordinary `eval()` path, skipping
all eval-set orchestration (log directory scanning, `.eval-set-id`,
`eval-set.json`, `logs.json`, retry partitioning, and log cleanup).

This is the execution counterpart to capture mode (see `eval_set_manifest.py`).
An external runner first enumerates an eval set with
`INSPECT_EVAL_SET_CAPTURE`, then launches one worker per task with
`INSPECT_EVAL_SET_SELECTION`, naming tasks by the `identifier` values from the
capture manifest. Because a worker performs no eval-set bookkeeping, many
workers can write into a single flat log directory concurrently: each writes
one (atomically replaced) `.eval` file per selected task, and the runner is the
sole writer of the directory's eval-set metadata. A selection must therefore
name each task at most once — one task means one log, and two entries for it
would have the same task id competing for the same file.

The definition still calls `eval_set()` — that is what preserves the side
effects of executing it (registered models, `set_model_info`, dynamically
constructed `Model` objects) in every worker process.

A selection may also carry **operational overrides** for the worker, in an
`overrides` container: `log_dir`, `max_samples`, `limit`, `max_sandboxes`, and
`max_tasks`. These exist because an environment variable cannot help here —
`INSPECT_LOG_DIR` and friends supply *defaults*, and `eval_set()` declares
`log_dir` with no default, so every definition passes it explicitly and a
default can never win. A runner that needs a worker's logs to land somewhere
else (a rehearsal writing to local scratch rather than to the definition's S3
bucket), or two samples of a task rather than five thousand, has no other way
to say so.

Every one of them is deliberately *operational*, and the boundary is worth
stating precisely: an override may change how a worker is **operated** — where
its output goes, how fast it runs, how much of its dataset it runs, how many
sandboxes it stands up, how many of its tasks it runs at once — and never what
is evaluated. The operative test is
that no override participates in `task_identifier()`, which is what stops one
desynchronizing a worker from the capture manifest. `limit` passes it because
the identifier hashes a task's *execution* limits (message, token, turn, time,
working, cost) and not its dataset slice. `time_limit` is the field this rules
out: it *is* in the identifier, so a runner wanting to cap a rehearsal's wall
clock has to do it from outside rather than through here.

Omitting the container, or any field in it, keeps whatever the definition
chose. The container arrived in schema version 3, and a document may not use a
field newer than the version it declares — see `_FIELD_MIN_VERSION`. That gate
is on the container, not on its contents: a field added to `overrides` later
(`max_tasks`, in version 4) bumps the schema version so an older inspect
refuses the document as too new rather than as carrying an unknown field, but
nothing tracks which version each override arrived in. Recording that would
buy nothing an unknown-field error does not already say. The same reasoning
covers the per-task pruning facets added in version 5.

A selection task may also carry **pruning facets** — `registry_name` and
`args_hash` — which are an optimization and never a decision. Constructing a
task is what loads its dataset, so a worker that resolves the whole eval set
to find its own one task pays for every dataset in the set; per-worker cost
therefore scales with the eval set rather than with the work. The facets let
the `@task` registry wrapper skip construction of tasks the selection does not
name, before any dataset loads. They cannot be replaced by `identifier`,
which is the point: an identifier is computed *from* a constructed task, so it
can only answer the question after the cost has been paid. See
`eval_set_pruning.py`, where the safety argument lives — pruning can only
under-fire, and Layer 1 (the boundary filter here) remains the sole authority
on what runs.

**Emitting the facets asserts one thing about the definition, and it is the
only precondition this protocol places on one: a task's construction does not
depend on another task's having been constructed.** Skipping a `@task` body
skips its side effects. Executing the definition is unaffected, so
module-level and driver-level work — registered models, `set_model_info`,
dynamically constructed `Model` objects — still happens in every worker,
which is what the paragraph above about side effects rests on. What does not
happen is the *body* of an unselected `@task`. A definition where one task
body primes something another task body reads at construction time will
therefore build the selected task differently from the way capture built it,
and that difference is undetectable from here: a dataset is not part of
`task_identifier`, so the altered task matches its identifier exactly. A
runner whose definitions may do this should omit the facets, or set
`INSPECT_EVAL_SET_NO_PRUNE` in the worker's environment; there is no
mechanical check, and this is the reason there is a switch.

Two of the definition's options are overridden in worker mode, because both
are completion decisions that belong to the runner rather than the worker:
`fail_on_error` is forced to `False` (so sample errors never fail a task —
the runner sees them in the log and decides what to do) and task-level retry
is disabled (the runner retries by respawning a worker with `resume`, and an
in-process loop would multiply its attempt budget and leave a failed log per
attempt in the shared directory). `continue_on_fail` needs no override: it is
moot once `fail_on_error` is `False`. Everything else the definition set is
honoured, `retry_on_error` in particular — sample-level retry stays under the
definition author's control. The values the definition asked for are recorded
in the capture manifest's `options`, so a runner can see what it is honouring
and what is being overridden.

This module is deliberately not part of the public API: the models here are a
versioned wire format (see `EVAL_SET_SELECTION_VERSION`) written by external
runners (currently inspect_steward, which imports them from this module).
Schema changes require a version bump and corresponding golden-test updates
(see `tests/test_eval_set_selection.py`).
"""

import json
import os
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file

INSPECT_EVAL_SET_SELECTION = "INSPECT_EVAL_SET_SELECTION"

EVAL_SET_SELECTION_VERSION = 5


def eval_set_selection_requested() -> str | None:
    """Selection path if eval-set selection (worker) mode is active.

    Returns:
        The path named by the `INSPECT_EVAL_SET_SELECTION` environment variable, or `None` when worker mode is not active (unset or empty are both treated as inactive).
    """
    value = os.environ.get(INSPECT_EVAL_SET_SELECTION, "").strip()
    return value if value else None


# Every model here forbids extra fields: a selection is hand-built by an
# external runner, where a misspelled key would otherwise be dropped silently
# and change what the worker does (`"resuem"` reads as no resume at all, so a
# resumed task reruns every completed sample). Strictness costs no forward
# compatibility — any added field bumps EVAL_SET_SELECTION_VERSION, and a
# document written at a version this inspect doesn't know is refused before it
# is validated at all.


class EvalSetSelectionTask(BaseModel):
    """A single task selected for execution by a worker.

    `identifier` is the authoritative field and the only one the boundary
    filter consults. The two facets below are an optimization hint and nothing
    more: they let unselected tasks be skipped *before* they are constructed,
    which an opaque identifier cannot support because computing one requires
    the constructed task. See `eval_set_pruning.py`.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: str
    """Task identifier (as produced by `task_identifier()` and recorded in the capture manifest)."""

    resume: str | None = None
    """Location of a prior log for this task to resume (completed samples are reused)."""

    # `registry_name` rather than the capture manifest's `name`, and the
    # difference is the whole reason this field is easy to get wrong. `name` is
    # `Task.name`, which is the *registry* name only when the task did not pass
    # `Task(name=...)` -- and a task that did is renamed inside its function
    # body, which pruning runs before. The registry name is the only name
    # knowable at the moment the decision has to be made.
    registry_name: str | None = None
    """Registry name of the task, for pruning before construction (`None` for an ad-hoc task, which cannot be pruned).

    Supplying this and `args_hash` asserts that the definition's task bodies do not depend on one another — see the module docstring. Omit both to run without pruning.
    """

    args_hash: str | None = None
    """`task_args_hash()` of the task's args, as the capture manifest records it. Paired with `registry_name` to identify a task without constructing it."""


class EvalSetSelectionOverrides(BaseModel):
    """How a worker is operated, overriding what the definition passed.

    `None` on any field keeps the definition's value, which is also what an
    absent container means. Nothing here changes what is evaluated: see the
    module docstring for the rule and for the one field it rules out.
    """

    model_config = ConfigDict(extra="forbid")

    log_dir: str | None = None
    """Log directory for this worker, overriding the definition's."""

    # strict: lax coercion would read JSON `true` as 1 and `"3"` as 3, so a
    # runner's templating bug could silently pin a worker to one concurrent
    # sample instead of failing. `log_dir` needs no such guard -- pydantic
    # already refuses non-strings for it.
    max_samples: int | None = Field(default=None, strict=True)
    """Sample concurrency for this worker, overriding the definition's."""

    # `StrictInt` rather than `Field(strict=True)`, which pydantic cannot apply
    # to a union at all -- and strictness matters more here than anywhere else
    # in this model, because a `limit` read leniently is a rehearsal that runs
    # the whole dataset. The tuple arm stays lax about list-to-tuple so a JSON
    # `[1, 5]` round-trips; its members do not.
    limit: StrictInt | tuple[StrictInt, StrictInt] | None = None
    """Dataset slice for this worker, overriding the definition's: a sample count, or a `(start, end)` range."""

    max_sandboxes: int | None = Field(default=None, strict=True)
    """Sandbox concurrency for this worker, overriding the definition's."""

    # the one override a worker running several tasks cannot do without, and
    # the default it displaces is not a stable one: outside selection mode
    # `eval_set()` fills `max_tasks` in itself, but that happens below the
    # selection branch, so a worker inherits `eval()`'s rule instead -- one
    # task at a time for a single model, the model count for several. A runner
    # that hands a worker five tasks and says nothing gets whichever of those
    # applies, having chosen neither.
    max_tasks: int | None = Field(default=None, strict=True)
    """Task concurrency for this worker, overriding the definition's."""


class EvalSetSelection(BaseModel):
    """Tasks an external runner has selected for a worker to run."""

    model_config = ConfigDict(extra="forbid")

    version: int
    """Selection schema version."""

    eval_set_id: str
    """Eval set id to stamp into the logs written by this worker."""

    tasks: list[EvalSetSelectionTask]
    """Tasks to run (identified by `task_identifier`)."""

    overrides: EvalSetSelectionOverrides | None = None
    """How to operate this worker, or `None` to run it as the definition asked."""


# The version each optional field was introduced in. A document may not use a
# field newer than the version it declares: the declaration is what an older
# inspect gates on, so honouring `overrides` in a document claiming v2 would
# make the same file behave one way here and fail as an unknown field there.
# Failing now, on the writer's own machine, beats failing only in the one
# deployment that still runs an older inspect.
#
# The gate is not ceremony, and `limit` is what shows why: an unknown field an
# older inspect ignores usually costs nothing, but an ignored `limit` means a
# worker asked for two samples runs five thousand.
_FIELD_MIN_VERSION: dict[str, int] = {"overrides": 3}

# the same rule for fields of a *task* entry. It needs its own dict rather than
# a dotted key because the check has to look at every entry: a facet set on one
# task of fifty is as much a version error as one set on all fifty, and it is
# rather easier to write by accident.
#
# The `overrides` container is gated as a whole and its contents are not, which
# is a different case and not a precedent for these: a field added inside a
# gated container is already unreachable by an older inspect, because the
# container it lives in is refused first. These facets sit directly on the task
# entry with nothing gating them, so they need what `overrides` itself needs.
_TASK_FIELD_MIN_VERSION: dict[str, int] = {"registry_name": 5, "args_hash": 5}


def _document_version(document: object) -> int | None:
    """Read a selection document's version before it has been validated.

    Args:
        document: Parsed JSON of a selection document (any shape — it has not been validated yet).

    Returns:
        The version, read as leniently as pydantic would read it, or `None` when the document doesn't carry one that can be (a malformed version is left for validation to report).
    """
    version = document.get("version") if isinstance(document, dict) else None
    if isinstance(version, (int, str)) and not isinstance(version, bool):
        try:
            return int(version)
        except ValueError:
            return None
    return None


def read_eval_set_selection(selection_path: str) -> EvalSetSelection:
    """Read and validate a selection written by an external runner.

    Args:
        selection_path: Path to the selection JSON file.

    Returns:
        The selection.

    Raises:
        PrerequisiteError: If the file cannot be read or parsed, if it uses a schema version this version of inspect does not understand, if it sets a field newer than the version it declares, or if it names no tasks, names the same task more than once, or carries a nonsensical override.
    """

    def unreadable(ex: Exception) -> PrerequisiteError:
        return PrerequisiteError(
            f"Unable to read the eval set selection at '{selection_path}' "
            f"(named by {INSPECT_EVAL_SET_SELECTION}):\n{ex}"
        )

    try:
        with file(selection_path, mode="rb") as f:
            contents = f.read()
        document = json.loads(contents)
    except (OSError, ValueError) as ex:
        raise unreadable(ex) from ex

    # gate on the version before validating fields, not after: a selection
    # written at a later version may carry fields this one doesn't know, and
    # the models forbid extras -- so the mismatch has to be reported as the
    # version problem it is rather than as an unknown field.
    version = _document_version(document)
    if version is not None and version > EVAL_SET_SELECTION_VERSION:
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' uses schema version "
            f"{version}, but this version of inspect understands at "
            f"most version {EVAL_SET_SELECTION_VERSION} (upgrade inspect-ai)."
        )

    try:
        selection = EvalSetSelection.model_validate_json(contents)
    except ValidationError as ex:
        raise unreadable(ex) from ex

    if not selection.tasks:
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' names no tasks."
        )

    # a repeated identifier would run the same task twice in one worker, under
    # one task id: the two runs share a log filename and a sample-buffer db, so
    # they overwrite each other's log or fail outright. Reject it here rather
    # than let the runner's bug surface as a mid-run error.
    counts = Counter(entry.identifier for entry in selection.tasks)
    duplicates = sorted(identifier for identifier, count in counts.items() if count > 1)
    if duplicates:
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' names the same task "
            f"more than once: {', '.join(duplicates)}. Each task in a selection "
            "must appear exactly once."
        )

    too_new = sorted(
        {
            name
            for name, introduced in _FIELD_MIN_VERSION.items()
            if introduced > selection.version and getattr(selection, name) is not None
        }
        | {
            name
            for name, introduced in _TASK_FIELD_MIN_VERSION.items()
            for entry in selection.tasks
            if introduced > selection.version and getattr(entry, name) is not None
        }
    )
    if too_new:
        required = max(
            {**_FIELD_MIN_VERSION, **_TASK_FIELD_MIN_VERSION}[name] for name in too_new
        )
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' declares schema "
            f"version {selection.version} but sets {', '.join(too_new)}, "
            f"added in version {required}. Declare version {required} (an "
            "older inspect would reject this document rather than honour it)."
        )

    # every override is optional, but an explicitly supplied nonsense value is a
    # runner bug worth reporting here rather than letting it surface as an empty
    # path, a semaphore that admits nothing, or an empty dataset.
    if selection.overrides is not None:
        _validate_overrides(selection.overrides, selection_path)

    return selection


def _validate_overrides(
    overrides: EvalSetSelectionOverrides, selection_path: str
) -> None:
    """Refuse an override whose value cannot mean anything.

    Args:
        overrides: The container to check.
        selection_path: Path to the selection, for the message.

    Raises:
        PrerequisiteError: An override carries a value that is not usable.
    """

    def refuse(detail: str) -> PrerequisiteError:
        return PrerequisiteError(
            f"The eval set selection at '{selection_path}' has {detail} "
            "(omit the field to keep the definition's value)."
        )

    if overrides.log_dir is not None and not overrides.log_dir.strip():
        raise refuse("an empty 'log_dir'")
    for name in ("max_samples", "max_sandboxes", "max_tasks"):
        value = getattr(overrides, name)
        if value is not None and value < 1:
            raise refuse(f"{name}={value}; it must be at least 1")
    if isinstance(overrides.limit, int):
        if overrides.limit < 1:
            raise refuse(f"limit={overrides.limit}; it must be at least 1")
    elif overrides.limit is not None:
        start, end = overrides.limit
        # a half-open range as `eval_set()` reads it, so start == end is an
        # empty slice rather than one sample -- worth refusing for the same
        # reason limit=0 is
        if start < 0 or end <= start:
            raise refuse(
                f"limit=({start}, {end}); a range must be ordered and non-negative"
            )
