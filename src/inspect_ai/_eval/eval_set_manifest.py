"""Eval-set capture mode.

When the `INSPECT_EVAL_SET_CAPTURE` environment variable names a file path,
`eval_set()` resolves its tasks (tasks × models), writes an `EvalSetCapture`
manifest describing every resolved task to that path, and exits the process
without running anything (and without touching `log_dir`). This gives external
runners a static enumeration of an eval set while preserving the side effects
of executing the definition that produced the `eval_set()` call.

This module is deliberately not part of the public API: the models here are a
versioned wire format (see `EVAL_SET_CAPTURE_VERSION`) consumed by external
runners (currently inspect_steward, which imports them from this module).
Schema changes require a version bump and corresponding golden-test updates
(see `tests/test_eval_set_capture.py`).
"""

import hashlib
import os
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydantic_core import to_json

from inspect_ai._eval.eval_set_overrides import EvalSetOverrides
from inspect_ai._eval.task import Epochs
from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.run import plan_agent_name, resolve_plan
from inspect_ai._eval.task.task import resolve_epochs
from inspect_ai._eval.task.util import resolve_task_sample_ids, sample_id_filter
from inspect_ai.dataset import Dataset
from inspect_ai.model._model import ModelName
from inspect_ai.model._model_config import model_args_for_log

if TYPE_CHECKING:
    from inspect_ai._eval.evalset import EvalSetArgsInTaskIdentifier

INSPECT_EVAL_SET_CAPTURE = "INSPECT_EVAL_SET_CAPTURE"

EVAL_SET_CAPTURE_VERSION = 3


def eval_set_capture_requested() -> str | None:
    """Manifest path if eval-set capture mode is active.

    Returns:
        The path named by the `INSPECT_EVAL_SET_CAPTURE` environment variable, or `None` when capture mode is not active (unset or empty are both treated as inactive).
    """
    value = os.environ.get(INSPECT_EVAL_SET_CAPTURE, "").strip()
    return value if value else None


class EvalSetCaptureTask(BaseModel):
    """A resolved task (task × model × solver combination) in a captured eval set."""

    name: str
    """Task name."""

    display_name: str | None = None
    """Task display name (if distinct from `name`)."""

    registry_name: str | None = None
    """Fully qualified registry name (`None` for ad-hoc tasks)."""

    file: str | None = None
    """Task source file (relative to the working directory)."""

    args: dict[str, Any]
    """Task arguments as passed (no defaults applied)."""

    args_full: dict[str, Any] | None = None
    """All named task parameters including defaults (when available)."""

    args_hash: str
    """Stable hash of `args` (the same hash used within `task_identifier`)."""

    solver: str | None = None
    """Resolved primary solver/agent name (`None` when unregistered)."""

    model: str
    """Model name."""

    model_args: dict[str, Any]
    """Model creation args (secrets redacted)."""

    model_roles: dict[str, str] | None = None
    """Model role names mapped to model names.

    A role bound to a list of models is rendered as a comma-separated join of
    the model names — the same syntax the `--model-role` CLI flag accepts, so
    the value can be fed back through a model-role flag verbatim. Consumers
    must not assume the value names a single model.
    """

    sequence: int
    """Sequence of the task within its eval set."""

    identifier: str
    """Stable task identifier (used to pair tasks with logs)."""

    samples: int
    """Number of dataset samples that would run (after any `limit`)."""

    epochs: int
    """Effective number of epochs."""


class EvalSetCaptureScan(BaseModel):
    """The definition's scanner configuration, serialized for an external runner.

    Added in version 3, present iff the definition passed `scanner`. Workers scan record-only in selection mode, so the runner owns the scan directory's lifecycle — and this is what lets it do that without executing the definition: `spec` is the material a fresh init writes, `scans` is where.
    """

    spec: dict[str, Any]
    """Scout `ScanSpec` dump for a fresh scan of this eval set — scanner names and `ScannerSpec`s, tags, and metadata (including the inspect-side config hash). `scan_id` is informational here; the runner stamps the authoritative id at init time."""

    scans: str | None = None
    """The definition's scan output-location override, or `None` to default to `scans/` under the runner's resolved log directory (capture cannot compute that default, since a definition may name no `log_dir`)."""


class EvalSetCapture(BaseModel):
    """Static enumeration of an eval set produced by capture mode."""

    version: int
    """Capture manifest schema version."""

    identifier_version: int
    """Version of the `task_identifier` computation used for `tasks[].identifier`."""

    eval_set_id: str | None = None
    """Eval set id as passed to `eval_set()` (never derived from `log_dir`)."""

    options: dict[str, Any]
    """Informational `eval_set()` options as the *definition* passed them (e.g. `log_dir`, `retry_attempts`, `limit`).

    What the definition asked for, never what this capture ran with — a runner already knows what it overrode and cannot otherwise learn what it displaced. Where the two differ, `overrides` says so.
    """

    overrides: "EvalSetOverrides | None" = None
    """Operational overrides in force for this capture, or `None` where the run is the definition's own.

    Added in version 2. Every field in it is one `task_identifier()` ignores, so no identifier here is affected by one — but `epochs` and `limit` change a task's sample count, so `tasks[].samples` reflects these and `options` does not. Recording them is what lets a reader account for the difference rather than infer it.
    """

    scan: "EvalSetCaptureScan | None" = None
    """Serialized scanner configuration, or `None` when the definition declares no scanners. Added in version 3; `options["scanners"]` remains the quick boolean beside it."""

    tasks: list[EvalSetCaptureTask]
    """Resolved tasks in the eval set."""


def task_args_hash(task_args: dict[str, Any]) -> str:
    """Stable hash of task args (the hash used within `task_identifier`).

    Args:
        task_args: Task arguments as passed (no defaults applied).

    Returns:
        Hex digest uniquely identifying the args.
    """
    return hashlib.sha256(
        to_json(task_args, exclude_none=True, fallback=lambda _x: None)
    ).hexdigest()


def samples_for_limit(count: int, limit: int | tuple[int, int] | None) -> int:
    """Number of dataset samples selected by a `limit`.

    Args:
        count: Total samples in the dataset.
        limit: Eval limit (first n samples, or [start, stop] range).

    Returns:
        Number of samples that would run.
    """
    if isinstance(limit, tuple):
        start, stop = limit
        if start >= count:
            count = 0
        else:
            count = min(stop, count) - start
    elif isinstance(limit, int):
        count = min(limit, count)
    return count


def samples_selected(
    dataset: Dataset,
    limit: int | tuple[int, int] | None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None,
    task: str | None = None,
) -> int:
    """Number of dataset samples a `limit` or a `sample_id` selects.

    The count `slice_dataset` would produce, without slicing — which is what
    the two callers need: one records it in the capture manifest, the other
    decides whether an existing log already holds every sample the task asks
    for. Counting only the `limit` leaves a `sample_id` run looking short of
    its own dataset forever: the log has the one sample that was requested,
    the count says the dataset has five, and the task is retried until the
    attempt budget runs out.

    `limit` and `sample_id` are mutually exclusive at the `eval()` door, so the
    branch order is presentational; `sample_id` leads because `slice_dataset`
    applies it first.

    **An unset id counts as the position it is about to be given.** `eval_run`
    numbers a dataset's samples from one just before slicing it, so a dataset
    written in Python without explicit ids still answers to `--sample-id 3`.
    Capture happens before that numbering, so matching `sample.id` as it stands
    would find nothing and record a task with zero samples.

    **A `task:id` selector belongs to one task and is stripped for it.**
    `--sample-id alpha:one,beta:two` runs one sample of each, because
    `resolve_task_sample_ids` narrows the list per task before the filter sees
    it. Matching the qualified list against every dataset instead counts zero
    for both, which is the same class of mistake as ignoring `sample_id`
    altogether and produces the same never-settling task.

    Args:
        dataset: The task's dataset.
        limit: Eval limit (first n samples, or [start, stop] range).
        sample_id: Sample id pattern(s) selected, if any.
        task: The task's registry name, for resolving `task:id` selectors. `None` skips that resolution, which is right only where the caller has already done it.

    Returns:
        Number of samples that would run.
    """
    if sample_id is not None:
        if task is not None:
            sample_id = resolve_task_sample_ids(task, sample_id)
            if not sample_id:
                # every selector named some other task
                return 0
        matcher = sample_id_filter(sample_id)
        return sum(
            1
            for position, sample in enumerate(dataset, start=1)
            if matcher.matches(sample.id if sample.id is not None else position)
        )
    return samples_for_limit(len(dataset), limit)


def build_eval_set_capture(
    resolved_tasks: list[ResolvedTask],
    eval_set_args: "EvalSetArgsInTaskIdentifier",
    *,
    epochs: int | Epochs | None,
    limit: int | tuple[int, int] | None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    eval_set_id: str | None,
    options: dict[str, Any],
    overrides: "EvalSetOverrides | None" = None,
    scan: "EvalSetCaptureScan | None" = None,
) -> EvalSetCapture:
    """Build a capture manifest for a set of resolved tasks.

    Args:
        resolved_tasks: Resolved tasks (tasks × models).
        eval_set_args: Eval-set level args that participate in task identity.
        epochs: Eval-set level epochs (task epochs are used when not specified).
        limit: Eval-set level sample limit.
        sample_id: Eval-set level sample id selection.
        eval_set_id: Eval set id as passed to `eval_set()`.
        options: Informational `eval_set()` options as the definition passed them.
        overrides: Operational overrides in force, or `None`.
        scan: Serialized scanner configuration, or `None` when the definition declares no scanners.

    Returns:
        Capture manifest for the eval set.
    """
    # deferred to avoid a module import cycle (evalset.py imports this module)
    from inspect_ai._eval.evalset import (
        TASK_IDENTIFIER_VERSION,
        resolve_solver,
        task_identifier,
    )

    solver = resolve_solver(eval_set_args.solver)
    eval_epochs = resolve_epochs(epochs)

    capture_tasks: list[EvalSetCaptureTask] = []
    for task in resolved_tasks:
        # effective epochs mirrors log_samples_complete (eval-set level wins)
        task_epochs = eval_epochs or resolve_epochs(task.task.epochs or 1)
        epoch_count = task_epochs.epochs if task_epochs else 1

        args_full = getattr(task.task, TASK_ALL_PARAMS_ATTR, None)

        capture_tasks.append(
            EvalSetCaptureTask(
                name=task.task.name,
                display_name=task.task.display_name,
                registry_name=task.task.registry_name,
                file=task.task_file,
                args=task.task_args,
                args_full=args_full,
                args_hash=task_args_hash(task.task_args),
                solver=plan_agent_name(resolve_plan(task.task, solver)),
                model=str(ModelName(task.model)),
                model_args=model_args_for_log(task.model.model_args),
                model_roles=(
                    {
                        k: ",".join(str(ModelName(m)) for m in v)
                        if isinstance(v, list)
                        else str(ModelName(v))
                        for k, v in task.model_roles.items()
                    }
                    if task.model_roles
                    else None
                ),
                sequence=task.sequence,
                identifier=task_identifier(task, eval_set_args),
                samples=samples_selected(
                    task.task.dataset, limit, sample_id, task.task.name
                ),
                epochs=epoch_count,
            )
        )

    return EvalSetCapture(
        version=EVAL_SET_CAPTURE_VERSION,
        identifier_version=TASK_IDENTIFIER_VERSION,
        eval_set_id=eval_set_id,
        options=options,
        overrides=overrides,
        scan=scan,
        tasks=capture_tasks,
    )
