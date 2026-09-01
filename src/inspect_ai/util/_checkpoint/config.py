"""Checkpoint configuration types.

These dataclasses are the public surface that users construct when
configuring checkpointing on a :class:`Sample`, :class:`Task`, or
``eval(...)``. Configs at different levels are combined via per-field
merging — see :func:`merge_checkpoint_configs` in this module.

Every field on :class:`CheckpointConfig` defaults to ``None`` so that
"not set at this level" is distinguishable from "explicitly set to a
default value." The merge resolver materializes defaults at the end
and returns a :class:`ResolvedCheckpointConfig` — a strict type whose
``trigger`` is guaranteed non-None and whose container fields are
filled in with their canonical defaults.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Discriminator

from ._triggers import CheckpointTrigger, TokenInterval

if TYPE_CHECKING:
    from inspect_ai.solver._task_state import TaskState
    from inspect_ai.util._checkpoint.report import ResumeReport

    OnCheckpointCallback = Callable[[TaskState], Awaitable[None]]
    OnResumeCallback = Callable[
        [TaskState, Literal["initial", "resume", "resume_for_scoring"]],
        Awaitable["ResumeReport | str | None"],
    ]

DEFAULT_CHECKPOINT_TRIGGER = TokenInterval(every=500_000)
"""Trigger used when checkpointing is enabled but no layer set a trigger."""

MAX_LISTED_FILES = 100
"""Max files recorded per snapshot in a checkpoint file; the count beyond
this is recorded in ``additional_files``."""


@dataclass(frozen=True)
class ResticSnapshots:
    """Incremental restic-based sandbox snapshots (the default).

    Each checkpoint stores only data changed since the previous one.
    Best choice when most files are stable across checkpoints. Requires
    injecting a restic binary into the sandbox.
    """

    name: Literal["restic-incremental"] = "restic-incremental"
    """Discriminator identifying this strategy in serialized form. The
    strategy configs are otherwise field-less, so without it every JSON
    round-trip would collapse the union to its first member."""


@dataclass(frozen=True)
class ArchiveSnapshots:
    """One complete compressed tar archive per checkpoint.

    Captures with tools already present in effectively every image
    (tar, dd, sha256sum, zstd or gzip) — nothing is injected into the
    sandbox. Each checkpoint's archive is self-contained, so restore
    reads a single file. Best choice when restic injection is
    impractical, or when the captured data is dominated by large,
    high-entropy, frequently-rewritten files where incremental backup
    stores roughly the full dataset again at every checkpoint anyway.

    Unlike restic (which encrypts its repository with a per-sample
    password), archives are written unencrypted: checkpoint data —
    including any credentials or keys the agent wrote into captured
    paths — lands in the checkpoint storage location (possibly S3) as
    plaintext tar archives.
    """

    name: Literal["archive"] = "archive"
    """Discriminator identifying this strategy in serialized form. See
    :class:`ResticSnapshots`."""


SnapshotStrategyConfig = Annotated[
    ResticSnapshots | ArchiveSnapshots, Discriminator("name")
]
"""Configuration for a sandbox snapshot strategy."""


@dataclass(frozen=True)
class SandboxSnapshotConfig:
    """Per-sandbox snapshot configuration: what to capture and how.

    Used as a ``sandbox_paths`` value in place of a bare path list when
    a sandbox needs a non-default snapshot strategy. The ``paths``
    field carries the same semantics as a bare path-list value
    (``None`` = the sandbox default user's home directory; an empty
    list opts the sandbox out entirely).
    """

    paths: list[str] | None = None
    """Absolute paths to capture inside the sandbox. ``None`` = the
    default user's home directory; ``[]`` opts the sandbox out."""

    strategy: SnapshotStrategyConfig | None = None
    """Snapshot strategy for this sandbox. ``None`` = the default
    (:class:`ResticSnapshots`)."""


@dataclass
class CheckpointSampleConfig:
    """Checkpoint configuration fields that may be set at the sample layer.

    These fields can be specified on ``Sample(checkpoint=...)`` and are
    also accepted at the task and eval layers (where they participate in
    the per-field merge — precedence: eval > sample > task). Capture
    configuration — what to snapshot and with which strategy — is a
    property of the sample's workload, so it lives here.

    Excluded from the sample layer: ``checkpoints_location`` and
    ``retention``. These are eval-wide storage-policy concerns that the
    sample layer must not influence; they live only on
    :class:`CheckpointConfig`, the subclass used at the task and eval
    layers.
    """

    trigger: CheckpointTrigger | None = None
    """Checkpoint trigger strategy — any implementer of
    :class:`CheckpointTrigger` (see :mod:`.triggers`). ``None`` means
    "inherit from a lower-priority layer"; when no layer sets a
    trigger, resolution falls back to
    :data:`DEFAULT_CHECKPOINT_TRIGGER`."""

    sandbox_paths: dict[str, list[str] | SandboxSnapshotConfig] | None = None
    """Per-sandbox-name capture configuration. Each value is either a
    list of absolute paths to capture inside the sandbox (snapshotted
    with the default restic strategy) or a
    :class:`SandboxSnapshotConfig` that also selects the snapshot
    strategy. ``None`` = inherit; sandboxes without an entry are
    captured with the defaults (home directory, restic); an empty path
    list opts that sandbox out."""

    max_consecutive_failures: int | None = None
    """If set, the sample fails after N consecutive failed checkpoint
    attempts. ``None`` = inherit / unlimited tolerance. ``0`` = any
    failure is fatal."""


@dataclass
class CheckpointConfig(CheckpointSampleConfig):
    """User-facing checkpoint configuration for the task and eval layers.

    Specify on ``Task(checkpoint=...)`` or ``eval(checkpoint=...)``. All
    fields default to ``None`` so that each level can supply a partial
    config; the layers are combined per-field at sample-run time
    (precedence: eval > sample > task).

    Adds the eval-wide storage-policy fields (``checkpoints_location``,
    ``retention``) to the sample-permitted surface it inherits from
    :class:`CheckpointSampleConfig`.
    """

    checkpoints_location: str | None = None
    """Override the parent directory under which the eval checkpoints
    dir lands. ``None`` = sibling of the eval log file. When set,
    inspect places ``<log-base>.checkpoints/`` under this root.
    Supports any fsspec-resolvable path (``s3://``, ``gs://``, plain
    local). Eval-wide — settable only at the task or eval layer."""

    retention: Literal["delete", "retain"] | None = None
    """Controls when checkpoint data is deleted after eval completion.
    ``"delete"`` removes the checkpoint directory after successful eval
    completion; ``"retain"`` keeps it for later inspection or replay.
    ``None`` = inherit / use the default (``"delete"``). Eval-wide —
    settable only at the task or eval layer."""


class CheckpointDisabled(CheckpointConfig):
    """Sentinel ``CheckpointConfig`` meaning checkpointing is vetoed.

    Produced by ``normalize_checkpoint(False)``. When the task or eval layer is
    this value, checkpointing is disabled for that scope, overriding an enable
    at any other layer (see ``checkpoint_vetoed`` and
    ``merge_checkpoint_configs``). It subclasses ``CheckpointConfig`` so that
    existing ``CheckpointConfig | None`` annotations accept it unchanged;
    resolvers detect it via ``isinstance``.
    """


def checkpoint_vetoed(
    task: CheckpointConfig | None, eval_: CheckpointConfig | None
) -> bool:
    """True if the task or eval layer vetoes checkpointing (``checkpoint=False``).

    A veto at either layer disables checkpointing, overriding an enable at the
    other. The sample layer cannot veto (it has no ``False`` form).
    """
    return isinstance(task, CheckpointDisabled) or isinstance(eval_, CheckpointDisabled)


@dataclass
class ResolvedCheckpointConfig:
    """Merged checkpoint config — the runtime contract for sample execution.

    Produced by :func:`merge_checkpoint_configs`. Distinct from the
    user-facing :class:`CheckpointConfig` because every field has been
    resolved: ``trigger`` is non-None (caller-provided or raise),
    ``sandbox_paths`` is a real (possibly-empty) dict, and ``retention``
    has its canonical default applied. Internal callers downstream of
    the merge depend on these invariants — typing them out lets the
    type system enforce them rather than asking each consumer to
    re-validate.
    """

    trigger: CheckpointTrigger
    sandbox_snapshots: dict[str, SandboxSnapshotConfig] = field(default_factory=dict)
    retention: Literal["delete", "retain"] = "delete"
    checkpoints_location: str | None = None
    max_consecutive_failures: int | None = None
    on_checkpoint: OnCheckpointCallback | None = None
    on_resume: OnResumeCallback | None = None

    @property
    def sandbox_paths(self) -> dict[str, list[str]]:
        """Paths-only view of ``sandbox_snapshots``.

        Derived so the two can never diverge: entries with explicit
        paths appear verbatim (empty list = opt-out), entries with
        ``paths=None`` are omitted so the auto-home default applies
        downstream.
        """
        return {
            name: cfg.paths
            for name, cfg in self.sandbox_snapshots.items()
            if cfg.paths is not None
        }

    def sandbox_strategy_config(self, sandbox_name: str) -> SnapshotStrategyConfig:
        """Effective snapshot strategy config for one sandbox."""
        entry = self.sandbox_snapshots.get(sandbox_name)
        if entry is not None and entry.strategy is not None:
            return entry.strategy
        return ResticSnapshots()


def merge_checkpoint_configs(
    task: CheckpointConfig | None = None,
    sample: CheckpointSampleConfig | None = None,
    eval_: CheckpointConfig | None = None,
    *,
    on_checkpoint: OnCheckpointCallback | None = None,
    on_resume: OnResumeCallback | None = None,
) -> ResolvedCheckpointConfig | None:
    """Merge checkpoint config layers across task, sample, and eval.

    Precedence: **eval > sample > task** — the layer closest to the run
    wins on per-field conflicts.

    The sample layer is typed :class:`CheckpointSampleConfig`, so it
    contributes capture configuration (``trigger``, ``sandbox_paths``
    including strategy selection, ``max_consecutive_failures``) but not
    the eval-wide storage-policy fields (``checkpoints_location``,
    ``retention``), which come only from the task or eval layers.

    For every field, the highest-priority layer with a non-None value
    wins; lower layers supply defaults that higher layers can override.
    ``sandbox_paths`` carries two concerns that merge differently:

    - **Capture paths** (*what* to snapshot) merge as a single
      whole-dict value (not key-wise): the highest-priority layer that
      set ``sandbox_paths`` wins.
    - **Snapshot-strategy selection** (*how* to snapshot — the
      ``strategy`` values on :class:`SandboxSnapshotConfig` entries)
      resolves per-sandbox (eval > sample > task), independently of
      which layer won the paths dict. A bare path list (and
      ``strategy=None``) expresses no opinion on strategy, so a
      higher-layer paths override narrows *what* is captured without
      silently resetting a lower-selected strategy back to the default;
      a higher layer resets a strategy by setting one explicitly (e.g.
      ``strategy=ResticSnapshots()``). A sandbox named only by a
      strategy selection (absent from the winning paths dict) is
      captured with the default paths under the configured strategy.

    The sample layer is **customize-only** — it never enables
    checkpointing. Only the task or eval layer turns it on. When
    neither task nor eval supplied a config, this returns ``None``
    (checkpointing disabled) and any sample-level config is silently
    ignored. Once enabled, the sample layer participates in the
    per-field merge like any other layer.

    Otherwise returns a :class:`ResolvedCheckpointConfig` with
    ``trigger`` guaranteed non-None and ``sandbox_paths`` /
    ``retention`` filled with canonical defaults. When checkpointing
    is enabled but no layer (including the sample) set a ``trigger``,
    the trigger defaults to :data:`DEFAULT_CHECKPOINT_TRIGGER`.
    """
    if checkpoint_vetoed(task, eval_):
        return None
    if task is None and eval_ is None:
        return None

    trigger: CheckpointTrigger | None = None
    winning_paths: dict[str, list[str] | SandboxSnapshotConfig] | None = None
    max_consecutive_failures: int | None = None
    for layer in (task, sample, eval_):
        if layer is None:
            continue
        if layer.trigger is not None:
            trigger = layer.trigger
        if layer.sandbox_paths is not None:
            winning_paths = layer.sandbox_paths
        if layer.max_consecutive_failures is not None:
            max_consecutive_failures = layer.max_consecutive_failures

    checkpoints_location: str | None = None
    retention: Literal["delete", "retain"] | None = None
    for layer in (task, eval_):
        if layer is None:
            continue
        if layer.checkpoints_location is not None:
            checkpoints_location = layer.checkpoints_location
        if layer.retention is not None:
            retention = layer.retention

    if trigger is None:
        trigger = DEFAULT_CHECKPOINT_TRIGGER

    # Strategy selection resolves per-sandbox across all layers,
    # independently of the whole-dict paths merge above — see the
    # docstring. Without this, a higher layer's bare-path-list entry
    # would silently revert a lower-selected strategy to the default.
    sandbox_strategies: dict[str, SnapshotStrategyConfig] = {}
    for layer in (task, sample, eval_):
        if layer is None or layer.sandbox_paths is None:
            continue
        for name, value in layer.sandbox_paths.items():
            if isinstance(value, SandboxSnapshotConfig) and value.strategy is not None:
                sandbox_strategies[name] = value.strategy

    resolved_snapshots: dict[str, SandboxSnapshotConfig] = {}
    for name, value in (winning_paths or {}).items():
        paths = value.paths if isinstance(value, SandboxSnapshotConfig) else value
        resolved_snapshots[name] = SandboxSnapshotConfig(
            paths=paths, strategy=sandbox_strategies.get(name)
        )
    for name, strategy in sandbox_strategies.items():
        if name not in resolved_snapshots:
            resolved_snapshots[name] = SandboxSnapshotConfig(strategy=strategy)

    return ResolvedCheckpointConfig(
        trigger=trigger,
        sandbox_snapshots=resolved_snapshots,
        retention=retention if retention is not None else "delete",
        checkpoints_location=checkpoints_location,
        max_consecutive_failures=max_consecutive_failures,
        on_checkpoint=on_checkpoint,
        on_resume=on_resume,
    )


def normalize_checkpoint(
    checkpoint: CheckpointConfig | bool | None,
) -> CheckpointConfig | None:
    """Normalize a public ``checkpoint=`` argument to a ``CheckpointConfig``.

    ``True`` enables checkpointing without pinning a trigger — the concrete
    default (:data:`DEFAULT_CHECKPOINT_TRIGGER`) is resolved per-sample by
    :func:`merge_checkpoint_configs`, matching the bare ``--checkpoint`` CLI
    flag. ``False`` is a **veto**: it returns :class:`CheckpointDisabled`, which
    disables checkpointing for that layer's scope, overriding an enable at
    another layer. ``None`` inherits (no opinion). A :class:`CheckpointConfig`
    is returned unchanged.
    """
    if checkpoint is True:
        return CheckpointConfig(trigger=None)
    if checkpoint is False:
        return CheckpointDisabled()
    if checkpoint is None:
        return None
    return checkpoint
