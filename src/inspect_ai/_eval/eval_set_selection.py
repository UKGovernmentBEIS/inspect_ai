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
`overrides` container of `EvalSetOverrides` — see `eval_set_overrides.py`,
which owns the model, the rule deciding what may be in it, and the run-wide
document a worker's container is merged on top of. Only the split belongs
here: this container is what differs *between* workers, which in practice is
`log_dir`, `max_samples`, and `max_tasks`, while everything true of the run as
a whole is said once in the run-wide document so that capture sees it too.

Omitting the container, or any field in it, keeps whatever the definition
chose. The container arrived in schema version 3, and a document may not use a
field newer than the version it declares — see `_FIELD_MIN_VERSION`, and
`_OVERRIDE_FIELD_INTRODUCED` for the contents of the container, which are gated
one by one (`max_tasks` in version 4, the identity-neutral remainder of
`eval_set()`'s signature in version 6). Gating only the container was tried and
is not enough: it makes the *outcome* safe, since an older inspect forbids
extras and so fails on an unknown override rather than ignoring it, but it
leaves a document declaring version 5 and setting `metadata` accepted here and
rejected there — the exact split the gate exists to prevent, decided in the one
deployment that still runs an older inspect rather than on the writer's own
machine. The per-task pruning facets added in version 5 are gated the same way.

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

Scanning in selection mode is **record-only**: a worker dispatches scanners
per settled sample and writes scout's per-transcript buffer, but never touches
the scan directory's lifecycle — no init, no finalize, no orphan cleanup. The
bracket belongs to the runner, which lays the scan directory down before any
worker starts (a worker finding it absent refuses rather than silently not
scanning) and compacts/finalizes it as the single writer. A selection may also
carry `scanners` — runner-injected scanner specs merged with the definition's
own before dispatch (introduced in version 7).

This module is deliberately not part of the public API: the models here are a
versioned wire format (see `EVAL_SET_SELECTION_VERSION`) written by external
runners (currently inspect_steward, which imports them from this module).
Schema changes require a version bump and corresponding golden-test updates
(see `tests/test_eval_set_selection.py`).
"""

import json
import os
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file

from .eval_set_overrides import EvalSetOverrides, validate_eval_set_overrides

INSPECT_EVAL_SET_SELECTION = "INSPECT_EVAL_SET_SELECTION"

EVAL_SET_SELECTION_VERSION = 7


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


class EvalSetSelection(BaseModel):
    """Tasks an external runner has selected for a worker to run."""

    model_config = ConfigDict(extra="forbid")

    version: int
    """Selection schema version."""

    eval_set_id: str
    """Eval set id to stamp into the logs written by this worker."""

    tasks: list[EvalSetSelectionTask]
    """Tasks to run (identified by `task_identifier`)."""

    overrides: EvalSetOverrides | None = None
    """How to operate this worker, overriding both the definition and the run-wide overrides document, or `None` to take those as they come."""

    # a dict of plain dicts rather than of scout's `ScannerSpec`, deliberately:
    # inspect_scout is an optional dependency, and a model field typed on it
    # would make importing this module require it. The entries are validated as
    # `ScannerSpec`s at the moment they are realized, which is also the first
    # moment scout is needed.
    scanners: dict[str, dict[str, Any]] | None = None
    """Runner-injected scanners, as scout `ScannerSpec` dicts keyed by scanner name.

    These are *merged with* the definition's own `scanner` argument before per-sample dispatch — a name collision with a definition scanner is refused rather than resolved, since either resolution silently changes what one of the two records. A worker may scan through this field alone, with a definition that declares no scanners of its own. The scan directory's lifecycle (init/finalize) belongs to the runner in selection mode, so the merged set here must match the spec the runner wrote into the scan directory.
    """


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
_FIELD_MIN_VERSION: dict[str, int] = {"overrides": 3, "scanners": 7}

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

# and the same rule for fields *inside* the overrides container. The container
# being gated at 3 was once thought to cover them -- an older inspect forbids
# extras, so it fails on an unknown override rather than ignoring one -- but
# that only makes the outcome safe, not the check honest: a document declaring
# version 5 and setting `metadata` is accepted here and rejected there, which
# is precisely the split this gate exists to prevent, and the reason is the one
# `limit` gives above. Deciding it on the writer's machine is the whole point.
#
# Derived from the container's own fields rather than listed, so a field added
# upstream is gated without anybody remembering to add it. Only the pre-version-6
# entries are named, because everything else arrived with the identity-neutral
# expansion; `test_eval_set_selection.py` asserts the three account for every
# field.
_OVERRIDE_FIELD_INTRODUCED: dict[str, int] = {
    "log_dir": 3,
    "max_samples": 3,
    "max_sandboxes": 3,
    "limit": 3,
    "max_tasks": 4,
}


def _override_field_min_version(name: str) -> int:
    """The schema version an override field arrived in."""
    return _OVERRIDE_FIELD_INTRODUCED.get(name, 6)


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
        | {
            f"overrides.{name}"
            for name in (
                EvalSetOverrides.model_fields if selection.overrides is not None else ()
            )
            if _override_field_min_version(name) > selection.version
            and getattr(selection.overrides, name) is not None
        }
    )
    if too_new:
        versions = {**_FIELD_MIN_VERSION, **_TASK_FIELD_MIN_VERSION}
        required = max(
            _override_field_min_version(name.removeprefix("overrides."))
            if name.startswith("overrides.")
            else versions[name]
            for name in too_new
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
        validate_eval_set_overrides(selection.overrides, selection_path)

    # an explicitly empty scanners dict is the same kind of runner bug: it says
    # "inject scanners" and names none, which downstream would silently read as
    # no injection at all.
    if selection.scanners is not None and not selection.scanners:
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' sets `scanners` to "
            "an empty mapping. Omit the field to inject no scanners."
        )

    return selection
