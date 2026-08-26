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

A selection may also carry **operational overrides** for the worker: `log_dir`
and `max_samples`. These exist because an environment variable cannot help
here — `INSPECT_LOG_DIR` and friends supply *defaults*, and `eval_set()`
declares `log_dir` with no default, so every definition passes it explicitly
and a default can never win. A runner that needs a worker's logs to land
somewhere else (a rehearsal run writing to local scratch rather than to the
definition's S3 bucket) has no other way to say so. Both are deliberately
*operational*: they change where output goes and how fast it is produced,
never what is evaluated, and neither participates in `task_identifier()` — so
overriding them cannot desynchronize a worker from the capture manifest.
Omitting either keeps whatever the definition chose. Both arrived in schema
version 2, and a document may not use a field newer than the version it
declares — see `_FIELD_MIN_VERSION`.

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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file

INSPECT_EVAL_SET_SELECTION = "INSPECT_EVAL_SET_SELECTION"

EVAL_SET_SELECTION_VERSION = 2


def eval_set_selection_requested() -> str | None:
    """Selection path if eval-set selection (worker) mode is active.

    Returns:
        The path named by the `INSPECT_EVAL_SET_SELECTION` environment variable, or `None` when worker mode is not active (unset or empty are both treated as inactive).
    """
    value = os.environ.get(INSPECT_EVAL_SET_SELECTION, "").strip()
    return value if value else None


# Both models forbid extra fields: a selection is hand-built by an external
# runner, where a misspelled key would otherwise be dropped silently and change
# what the worker does (`"resuem"` reads as no resume at all, so a resumed task
# reruns every completed sample). Strictness costs no forward compatibility —
# any added field bumps EVAL_SET_SELECTION_VERSION, and a document written at a
# version this inspect doesn't know is refused before it is validated at all.


class EvalSetSelectionTask(BaseModel):
    """A single task selected for execution by a worker."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    """Task identifier (as produced by `task_identifier()` and recorded in the capture manifest)."""

    resume: str | None = None
    """Location of a prior log for this task to resume (completed samples are reused)."""


class EvalSetSelection(BaseModel):
    """Tasks an external runner has selected for a worker to run."""

    model_config = ConfigDict(extra="forbid")

    version: int
    """Selection schema version."""

    eval_set_id: str
    """Eval set id to stamp into the logs written by this worker."""

    tasks: list[EvalSetSelectionTask]
    """Tasks to run (identified by `task_identifier`)."""

    log_dir: str | None = None
    """Log directory for this worker, overriding the definition's (`None` keeps it)."""

    # strict: lax coercion would read JSON `true` as 1 and `"3"` as 3, so a
    # runner's templating bug could silently pin a worker to one concurrent
    # sample instead of failing. `log_dir` needs no such guard -- pydantic
    # already refuses non-strings for it.
    max_samples: int | None = Field(default=None, strict=True)
    """Sample concurrency for this worker, overriding the definition's (`None` keeps it)."""


# The version each optional field was introduced in. A document may not use a
# field newer than the version it declares: the declaration is what an older
# inspect gates on, so honouring `log_dir` in a document claiming v1 would make
# the same file behave one way here and fail as an unknown field there. Failing
# now, on the writer's own machine, beats failing only in the one deployment
# that still runs an older inspect.
_FIELD_MIN_VERSION: dict[str, int] = {"log_dir": 2, "max_samples": 2}


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
        name
        for name, introduced in _FIELD_MIN_VERSION.items()
        if introduced > selection.version and getattr(selection, name) is not None
    )
    if too_new:
        required = max(_FIELD_MIN_VERSION[name] for name in too_new)
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' declares schema "
            f"version {selection.version} but sets {', '.join(too_new)}, "
            f"added in version {required}. Declare version {required} (an "
            "older inspect would reject this document rather than honour it)."
        )

    # both overrides are optional, but an explicitly supplied nonsense value is
    # a runner bug worth reporting here rather than letting it surface as an
    # empty path or a semaphore that admits nothing.
    if selection.log_dir is not None and not selection.log_dir.strip():
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' has an empty "
            "'log_dir' (omit the field to keep the definition's log directory)."
        )
    if selection.max_samples is not None and selection.max_samples < 1:
        raise PrerequisiteError(
            f"The eval set selection at '{selection_path}' has "
            f"max_samples={selection.max_samples}; it must be at least 1 "
            "(omit the field to keep the definition's value)."
        )

    return selection
