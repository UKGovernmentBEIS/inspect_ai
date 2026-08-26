"""Strategy name registry and config → instance construction.

The registry is internal: strategy configs are dataclasses
(:class:`ResticSnapshots` / :class:`ArchiveSnapshots`), and this module
maps them to instances and to the stable names recorded in checkpoint
files and the per-sample strategy pin (§4.7 of the design).
"""

from __future__ import annotations

from ..config import ArchiveSnapshots, ResticSnapshots, SnapshotStrategyConfig
from .archive import ArchiveStrategy
from .restic import ResticIncrementalStrategy
from .types import DEFAULT_STRATEGY_NAME, SandboxSnapshotStrategy

STRATEGY_RESTIC = DEFAULT_STRATEGY_NAME
STRATEGY_ARCHIVE = ArchiveStrategy.name

KNOWN_STRATEGY_NAMES: frozenset[str] = frozenset({STRATEGY_RESTIC, STRATEGY_ARCHIVE})


def strategy_config_name(config: SnapshotStrategyConfig) -> str:
    """Stable strategy name for a strategy config."""
    return config.name


def create_strategy(config: SnapshotStrategyConfig) -> SandboxSnapshotStrategy:
    """Construct a strategy instance from its config (one per sandbox)."""
    if isinstance(config, ResticSnapshots):
        return ResticIncrementalStrategy()
    if isinstance(config, ArchiveSnapshots):
        return ArchiveStrategy()
    raise ValueError(f"unknown snapshot strategy config: {config!r}")


def strategy_storage_subpath(strategy_name: str, sandbox_name: str) -> str:
    """Storage-area subpath under the sample root for one (sandbox, strategy).

    The core maps strategy → storage area in one place (here);
    strategies never compute sample-dir paths themselves. The restic
    strategy keeps ``restic/sandboxes/<name>`` verbatim so existing
    checkpoint dirs resume unchanged; other strategies use
    ``sandboxes/<name>/<strategy>``.
    """
    if strategy_name == STRATEGY_RESTIC:
        return f"restic/sandboxes/{sandbox_name}"
    return f"sandboxes/{sandbox_name}/{strategy_name}"
