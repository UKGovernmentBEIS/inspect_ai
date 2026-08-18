"""Narrow facade for the checkpoint layout package.

The submodules in ``inspect_ai.util._checkpoint._layout`` own the full
checkpoint directory topology and on-disk schemas. This package-level
module intentionally re-exports only the small surface that other
subsystems need at a package boundary:

- eval/sample checkpoint dir discovery for eval/retry wiring

Checkpoint-internal code should import path helpers from the concrete
submodule that owns them rather than widening this facade.
"""

from .eval_checkpoints_dir import (
    eval_checkpoints_dir,
    eval_checkpoints_dir_from_config,
)
from .sample_checkpoints_dir import (
    has_sample_checkpoint,
    sample_checkpoints_dir,
)

# `host_context` is intentionally NOT imported here. It imports
# `inspect_ai.event._event.Event`, which is itself the union that
# (since `CheckpointEvent` landed) imports `Checkpoint` from
# `.schemas` below — eager `host_context` here would create a cycle
# at package-init time. Callers import the submodule directly:
# `from inspect_ai.util._checkpoint.layout import host_context`
# still works via Python's submodule-attribute fallback at the time
# of the import statement.

__all__ = [
    "eval_checkpoints_dir",
    "eval_checkpoints_dir_from_config",
    "has_sample_checkpoint",
    "sample_checkpoints_dir",
]
