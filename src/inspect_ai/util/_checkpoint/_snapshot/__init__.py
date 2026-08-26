"""Pluggable sandbox snapshot strategies.

Implements the ``SandboxSnapshotStrategy`` boundary described in
``design/checkpoint-snapshot-strategy.md``: per-sandbox capture/restore
of bulk state is routed through a Protocol so that evals whose sandbox
data is dominated by large, high-entropy, frequently-rewritten files
can choose a strategy other than restic's incremental model.

Modules:

- ``types`` — the Protocol and its supporting types.
- ``restic`` — ``ResticIncrementalStrategy`` (the default; extraction
  of the pre-existing inlined code).
- ``archive`` — ``ArchiveStrategy`` (one complete compressed tar per
  checkpoint).
- ``pin`` — the per-sample strategy pin (§4.7 of the design).
"""

from .archive import ArchiveStrategy
from .registry import (
    STRATEGY_ARCHIVE,
    STRATEGY_RESTIC,
    create_strategy,
    strategy_config_name,
    strategy_storage_subpath,
)
from .restic import ResticIncrementalStrategy
from .types import (
    PriorAttempt,
    SandboxSnapshotSession,
    SandboxSnapshotStrategy,
    SnapshotContext,
    snapshot_strategy_name,
)

__all__ = [
    "ArchiveStrategy",
    "PriorAttempt",
    "ResticIncrementalStrategy",
    "STRATEGY_ARCHIVE",
    "STRATEGY_RESTIC",
    "SandboxSnapshotSession",
    "SandboxSnapshotStrategy",
    "SnapshotContext",
    "create_strategy",
    "snapshot_strategy_name",
    "strategy_config_name",
    "strategy_storage_subpath",
]
