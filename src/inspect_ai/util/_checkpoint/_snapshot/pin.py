"""The per-sample strategy pin (design §4.7).

Resume must never run one strategy over another strategy's data, and a
strategy change between attempts must surface as an error, never be
applied silently. The pin file (``restic/snapshot-strategies.json``,
sandbox name → strategy name) is written by the core at fresh-sample
hydration and rides across attempts with the cross-cutting retry copy,
so every attempt's dir carries it no matter how many retries preceded.
Absent file ⇒ ``restic-incremental`` for every sandbox (pre-pin dirs).

It lives under ``restic/`` deliberately: that directory is already the
home of core-owned per-sample files (the host repo, the config), and
in the host-egress safe order the pin (catch-all tier) ships before
the ``ckpt-*.json`` tier — required so a crash window can never leave
a resumable dir without its pin.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from inspect_ai._util.asyncfiles import get_async_filesystem

STRATEGY_PIN_SUBPATH = "restic/snapshot-strategies.json"


class SnapshotStrategiesPin(BaseModel):
    """On-disk schema of the strategy pin file."""

    model_config = ConfigDict(extra="allow")

    strategies: dict[str, str] = Field(default_factory=dict)
    """Sandbox name → strategy name, fixed at fresh-sample hydration."""


def strategy_pin_path(sample_root: str) -> str:
    return f"{sample_root}/{STRATEGY_PIN_SUBPATH}"


async def read_strategy_pin(sample_root: str) -> dict[str, str] | None:
    """Read the pin, or ``None`` when the file is absent (pre-pin dir)."""
    async_fs = get_async_filesystem()
    path = strategy_pin_path(sample_root)
    if not await async_fs.exists(path):
        return None
    raw = await async_fs.read_file(path)
    return SnapshotStrategiesPin.model_validate_json(raw).strategies


async def write_strategy_pin(sample_root: str, strategies: dict[str, str]) -> None:
    await get_async_filesystem().write_file(
        strategy_pin_path(sample_root),
        SnapshotStrategiesPin(strategies=strategies).model_dump_json(indent=2).encode(),
    )


def check_strategy_pin(
    *,
    pinned: dict[str, str] | None,
    configured: dict[str, str],
    known_strategies: frozenset[str],
    default_strategy: str,
    live_sandboxes: set[str],
    opted_out: set[str],
) -> None:
    """Validate this attempt's configured strategies against the pin.

    Any mismatch is a hard error naming the sandbox, the pinned and
    configured strategies, and the remedy — strategy migration on
    resume is explicitly a non-goal. Checked cases:

    - pinned strategy != configured strategy for a sandbox;
    - pinned strategy name unknown to this build;
    - a configured sandbox with no pin entry (sandbox set changed);
    - a pin entry whose sandbox is absent from this attempt's effective
      set — either a config change (removed / opted out) or, when the
      sandbox is live and not opted out, an auto-home resolution
      failure (today a skip-with-warning; for a *pinned* sandbox that
      would be silent data loss, so it errors with its own remedy).

    ``pinned=None`` (pre-pin dir) means ``default_strategy`` for every
    sandbox.

    Args:
        pinned: Sandbox → strategy from the pin file, or ``None``.
        configured: Sandbox → strategy for this attempt's effective
            backup set.
        known_strategies: Strategy names this build can instantiate.
        default_strategy: Name assumed for sandboxes absent from the
            pin when the pin file itself is absent.
        live_sandboxes: Names of the sample's live sandboxes.
        opted_out: Sandboxes explicitly opted out via an empty
            ``paths`` entry in this attempt's config.
    """
    remedy = (
        "restore the original checkpoint configuration and resume, or "
        "start a fresh eval"
    )
    if pinned is None:
        for name, strategy in configured.items():
            if strategy != default_strategy:
                raise RuntimeError(
                    f"checkpoint resume: sandbox {name!r} is configured with "
                    f"snapshot strategy {strategy!r}, but the prior attempt "
                    f"predates strategy selection and used "
                    f"{default_strategy!r}. Changing a sample's snapshot "
                    f"strategy between attempts is not supported — {remedy}."
                )
        return

    for name, pinned_strategy in pinned.items():
        if pinned_strategy not in known_strategies:
            raise RuntimeError(
                f"checkpoint resume: sandbox {name!r} was captured with "
                f"snapshot strategy {pinned_strategy!r}, which this version "
                f"of inspect does not provide. Resume with a version that "
                f"provides it, or start a fresh eval."
            )
        if name in configured:
            continue
        if name in live_sandboxes and name not in opted_out:
            raise RuntimeError(
                f"checkpoint resume: sandbox {name!r} was captured in the "
                f"prior attempt (strategy {pinned_strategy!r}) but dropped "
                f"out of this attempt's backup set because its home "
                f"directory could not be resolved. Resuming would silently "
                f"lose its captured state — resume again (resolution "
                f"failures are typically transient), or configure the "
                f"sandbox's paths explicitly so home-dir resolution is no "
                f"longer involved."
            )
        raise RuntimeError(
            f"checkpoint resume: sandbox {name!r} was captured in the prior "
            f"attempt (strategy {pinned_strategy!r}) but is absent from this "
            f"attempt's configuration. Resuming would silently lose its "
            f"captured state — {remedy}."
        )

    for name, strategy in configured.items():
        pinned_entry = pinned.get(name)
        if pinned_entry is None:
            raise RuntimeError(
                f"checkpoint resume: sandbox {name!r} is configured for "
                f"capture, but the prior attempt did not capture it — the "
                f"sandbox set changed between attempts. {remedy[0].upper()}"
                f"{remedy[1:]}."
            )
        if pinned_entry != strategy:
            raise RuntimeError(
                f"checkpoint resume: sandbox {name!r} was captured with "
                f"snapshot strategy {pinned_entry!r}, but this attempt "
                f"configures {strategy!r}. Changing a sample's snapshot "
                f"strategy between attempts is not supported — {remedy}."
            )
