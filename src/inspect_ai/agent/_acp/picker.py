"""In-channel session picker.

Pure helpers that compute the set of attachable ACP target sessions
from the eval's :data:`_active_samples` registry and resolve a user's
selection string back to a target.

The picker has no socket dependency. ``AcpServer`` (and tests) call
:func:`list_picker_targets` and :func:`resolve_selection` directly.
Each accepted connection sees the *current* set of targets at
picker-build time, so clients connecting late enumerate samples that
came up after server start, and samples that have finished are
correctly excluded.

The picker's selection surface accepts a numeric index (``"1"``,
``"2"``, ...) matching the visible order, or a uuid string matching
one of ``targets[i].session_id``. Tuple parsing
(``"task/sample_id/epoch"``) was considered and deferred — the native
``inspect acp`` client reads the structured target list out of the
notification's ``_meta`` (see :data:`inspect_ext.PICKER_META_KEY`)
and submits the matching uuid directly.

The picker notification's wire shape (numbered-list text body +
structured ``_meta`` target array) lives in :mod:`inspect_ext` —
``build_picker_notification`` and ``picker_target_meta_dict`` —
since both are Inspect-specific extensions on a standard ACP payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from inspect_ai.log._samples import active_samples

__all__ = [
    "PickerTarget",
    "SampleListing",
    "list_picker_targets",
    "list_all_samples",
    "resolve_selection",
]


@dataclass(frozen=True)
class PickerTarget:
    """A single attachable ACP session target."""

    session_id: str
    """The target ``LiveAcpTransport.session_id`` (uuid)."""

    task: str
    """Task name (e.g. ``"my_task"``)."""

    sample_id: str
    """Sample id as a string (``Sample.id`` may be int or str; we
    stringify for transport)."""

    epoch: int
    """Epoch number."""

    agent_name: str | None = None
    """Registered ``@agent`` / solver name (e.g. ``"react"``). Derived
    at ``active_sample()`` setup time using inspect_scout's
    ``log.eval.solver`` → last-plan-step heuristic. ``None`` when no
    solver name is available (rare; lifts to ``None`` in the TUI's
    meta row)."""

    started_at: float | None = None
    """Unix timestamp when the sample's task group started (from
    :attr:`inspect_ai.log._samples.ActiveSample.started`). ``None``
    before the sample's ``start()`` is called. Drives the picker's
    ``running`` column."""

    total_messages: int = 0
    """Running total messages for the sample (from
    :attr:`inspect_ai.log._samples.ActiveSample.total_messages`). Drives
    the picker's ``messages`` column; refreshed on rescan."""

    total_tokens: int = 0
    """Running total tokens for the sample (from
    :attr:`inspect_ai.log._samples.ActiveSample.total_tokens`). Drives
    the picker's ``tokens`` column; refreshed on rescan."""

    fails_on_error: bool = False
    """Mirror of :attr:`ActiveSample.fails_on_error`.

    Drives the cancel-sample bar's ``[e] error`` visibility: hidden
    when this is ``True`` (operator marking it errored is moot — the
    sample would error on its own), shown when ``False``. Matches the
    in-proc ``--display full`` TUI's rule
    (``cancel_with_error.display = not sample.fails_on_error``) so
    both display modes stay in lockstep — fractional thresholds and
    integer counts collapse to ``True`` here just as they do in
    ``--display full``.

    Snapshot at enumeration; never mutates."""


def list_picker_targets() -> list[PickerTarget]:
    """Snapshot active samples whose transport is currently interactive.

    Filters :func:`inspect_ai.log._samples.active_samples` to those
    whose ``acp_transport`` reports :attr:`AcpTransport.is_interactive`
    — i.e. a channel is bound and the agent loop is still live. Skips
    the pre-binding window (sample started, agent_channel not yet
    opened), the post-agent scoring window, and non-channel agents
    that never bind. Operators only see sessions they can actually
    drive.
    """
    targets: list[PickerTarget] = []
    for sample in active_samples():
        session = sample.acp_transport
        if session is None or not session.is_interactive:
            continue
        targets.append(
            PickerTarget(
                session_id=session.session_id,
                task=sample.task,
                sample_id=str(sample.sample.id) if sample.sample.id is not None else "",
                epoch=sample.epoch,
                agent_name=sample.agent_name,
                started_at=sample.started,
                total_messages=sample.total_messages,
                total_tokens=sample.total_tokens,
                # Mirror ActiveSample.fails_on_error verbatim so the
                # ACP TUI's [e] error visibility matches --display
                # full's `cancel_with_error.display = not
                # sample.fails_on_error` rule exactly.
                fails_on_error=sample.fails_on_error,
            )
        )
    return targets


@dataclass(frozen=True)
class SampleListing:
    """One entry in the ``inspect/list_samples`` enumeration.

    Same field set as :class:`PickerTarget` but ``session_id`` is
    optional — ``None`` only when there is nothing to attach to (the
    sample has no transport, only the noop placeholder, or has
    finalized). Any running sample — including custom solvers that
    never bind an agent channel — carries a live ``session_id`` so a
    client can attach to observe it; ``interactive`` then says whether
    it can also be driven.
    """

    session_id: str | None
    """Live ``LiveAcpTransport.session_id`` (uuid) for any attachable
    sample; ``None`` when the sample has no ACP session, only the noop
    placeholder, or has finalized."""

    task: str
    sample_id: str
    epoch: int
    agent_name: str | None = None
    started_at: float | None = None
    total_messages: int = 0
    total_tokens: int = 0
    fails_on_error: bool = False
    interactive: bool = False
    """True when the sample has a bound agent turn loop (drivable via
    ``session/prompt`` / ``session/cancel``). False for observe-only
    samples — custom solvers, the pre-bind window, and the scoring
    window — which can still be observed and lifecycle-controlled."""

    pending: Literal["approval", "question"] | None = None
    """Set when the sample is parked on a human-in-the-loop request
    routed through ACP — ``"approval"`` for tool-call permission,
    ``"question"`` for ``ask_user``. ``None`` otherwise. The Inspect
    TUI's picker reads this to surface a "pending" column and float
    waiting samples to the top of the table."""


def list_all_samples() -> list[SampleListing]:
    """Snapshot ALL active samples — attachable and not.

    Walks :func:`inspect_ai.log._samples.active_samples` unfiltered.
    Any **attachable** sample (running transport that hasn't finalized,
    regardless of whether an agent channel is bound) carries its live
    ``session_id`` so a client can attach to observe it; ``interactive``
    reports whether it can also be driven (bound agent turn loop). Only
    samples with nothing to attach to — no transport, the noop
    sentinel, or a finalized transport — surface as ``session_id=None``.

    ``agent_name`` is surfaced for every attachable sample (including
    observe-only custom solvers); it stays ``None`` only when there's no
    session to attach to.

    Sample-id stringification mirrors :func:`list_picker_targets`.
    """
    listings: list[SampleListing] = []
    for sample in active_samples():
        session = sample.acp_transport
        if session is None or not session.is_attachable:
            session_id: str | None = None
            agent_name: str | None = None
            interactive = False
        else:
            session_id = session.session_id
            agent_name = sample.agent_name
            interactive = session.is_interactive
        listings.append(
            SampleListing(
                session_id=session_id,
                task=sample.task,
                sample_id=str(sample.sample.id) if sample.sample.id is not None else "",
                epoch=sample.epoch,
                agent_name=agent_name,
                started_at=sample.started,
                total_messages=sample.total_messages,
                total_tokens=sample.total_tokens,
                fails_on_error=sample.fails_on_error,
                interactive=interactive,
                pending=sample.pending_interaction,
            )
        )
    return listings


def resolve_selection(
    prompt_text: str,
    targets: list[PickerTarget],
) -> PickerTarget | None:
    """Resolve a picker selection string to a target.

    Accepts:

    - A 1-based index (``"1"``, ``"2"``, ...) matching the order
      returned by :func:`list_picker_targets`.
    - A uuid string matching one of ``targets[i].session_id``.

    Returns the matched target, or ``None`` if the selection doesn't
    parse or doesn't match (caller is responsible for re-prompting or
    returning an error to the client).
    """
    selection = prompt_text.strip()
    if not selection:
        return None

    # Numeric-index branch.
    try:
        index = int(selection)
    except ValueError:
        pass
    else:
        if 1 <= index <= len(targets):
            return targets[index - 1]
        return None

    # SessionId-match branch.
    for target in targets:
        if target.session_id == selection:
            return target
    return None
