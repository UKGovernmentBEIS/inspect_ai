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

from inspect_ai._eval.task import Epochs
from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.run import plan_agent_name, resolve_plan
from inspect_ai._eval.task.task import resolve_epochs
from inspect_ai.model._model import ModelName
from inspect_ai.model._model_config import model_args_for_log

if TYPE_CHECKING:
    from inspect_ai._eval.evalset import EvalSetArgsInTaskIdentifier

INSPECT_EVAL_SET_CAPTURE = "INSPECT_EVAL_SET_CAPTURE"

EVAL_SET_CAPTURE_VERSION = 1


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


class EvalSetCapture(BaseModel):
    """Static enumeration of an eval set produced by capture mode."""

    version: int
    """Capture manifest schema version."""

    identifier_version: int
    """Version of the `task_identifier` computation used for `tasks[].identifier`."""

    eval_set_id: str | None = None
    """Eval set id as passed to `eval_set()` (never derived from `log_dir`)."""

    options: dict[str, Any]
    """Informational `eval_set()` options (e.g. `log_dir`, `retry_attempts`, `limit`)."""

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


def build_eval_set_capture(
    resolved_tasks: list[ResolvedTask],
    eval_set_args: "EvalSetArgsInTaskIdentifier",
    *,
    epochs: int | Epochs | None,
    limit: int | tuple[int, int] | None,
    eval_set_id: str | None,
    options: dict[str, Any],
) -> EvalSetCapture:
    """Build a capture manifest for a set of resolved tasks.

    Args:
        resolved_tasks: Resolved tasks (tasks × models).
        eval_set_args: Eval-set level args that participate in task identity.
        epochs: Eval-set level epochs (task epochs are used when not specified).
        limit: Eval-set level sample limit.
        eval_set_id: Eval set id as passed to `eval_set()`.
        options: Informational `eval_set()` options to record.

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
                samples=samples_for_limit(len(task.task.dataset), limit),
                epochs=epoch_count,
            )
        )

    return EvalSetCapture(
        version=EVAL_SET_CAPTURE_VERSION,
        identifier_version=TASK_IDENTIFIER_VERSION,
        eval_set_id=eval_set_id,
        options=options,
        tasks=capture_tasks,
    )
