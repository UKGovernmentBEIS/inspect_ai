"""Eval checkpoints dir resolution from checkpoint config.

For an eval log at ``<log>.eval`` with no override, the eval
checkpoints dir lives at ``<log-base>.checkpoints/`` (sibling to the
log; ``.eval`` stripped from the basename). With a ``checkpoints_location``
override on :class:`CheckpointConfig`, the dir lands at
``<override>/<log-base>.checkpoints/`` (the override is the *evals
checkpoints dir*; the per-eval subdir name is unchanged). The path rule
itself is :func:`inspect_ai._util.log_layout.eval_checkpoints_dir`.

Pure path computation — no filesystem side effects.
"""

from __future__ import annotations

# re-exported: the package facade and checkpoint callers import it from here
from inspect_ai._util.log_layout import eval_checkpoints_dir as eval_checkpoints_dir

from ..config import CheckpointConfig, checkpoint_vetoed


def eval_checkpoints_dir_from_config(
    log_location: str,
    task: CheckpointConfig | None,
    eval_: CheckpointConfig | None,
) -> str | None:
    """Resolve the eval checkpoints dir from task + eval config layers.

    Returns ``None`` if either layer vetoes checkpointing
    (``checkpoint=False``), or if neither layer supplies a config.
    Otherwise computes the dir, honoring an explicit
    ``checkpoints_location`` override (eval layer wins over task;
    sample layer cannot set this field).
    """
    if checkpoint_vetoed(task, eval_):
        return None
    if task is None and eval_ is None:
        return None
    override: str | None = None
    for layer in (task, eval_):
        if layer is not None and layer.checkpoints_location is not None:
            override = layer.checkpoints_location
    return eval_checkpoints_dir(log_location, override)
