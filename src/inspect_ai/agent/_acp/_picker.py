"""Phase 9 — in-channel session picker.

Pure helpers that compute the set of attachable ACP target sessions
from the eval's :data:`_active_samples` registry, format them into an
ACP ``session/update`` notification payload, and resolve a user's
selection string back to a target.

The picker has no socket dependency. ``_AcpServer`` (and tests) call
:func:`list_picker_targets`, :func:`build_picker_notification`, and
:func:`resolve_selection` directly. Each accepted connection sees the
*current* set of targets at picker-build time, so clients connecting
late enumerate samples that came up after server start, and samples
that have finished are correctly excluded.

The picker's selection surface accepts a numeric index (``"1"``,
``"2"``, ...) matching the visible order, or a uuid string matching
one of ``targets[i].session_id``. Tuple parsing
(``"task/sample_id/epoch"``) was considered and deferred — the native
``inspect acp`` client (Phase 11) reads the structured target list out
of the notification's ``_meta["inspect.picker.targets"]`` field and
submits the matching uuid directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acp.helpers import session_notification, text_block, update_agent_message
from acp.schema import SessionNotification

from inspect_ai.log._samples import active_samples

__all__ = [
    "PICKER_META_KEY",
    "_PickerTarget",
    "build_picker_notification",
    "list_picker_targets",
    "resolve_selection",
]

# `_meta` key on the picker notification carrying the structured target
# list for clients that prefer not to parse the human-readable text.
# Namespaced with `inspect.` so it can never collide with another
# tool's extension on the same notification.
PICKER_META_KEY = "inspect.picker.targets"


@dataclass(frozen=True)
class _PickerTarget:
    """A single attachable ACP session target."""

    session_id: str
    """The target ``_LiveAcpSession.session_id`` (uuid)."""

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

    total_tokens: int = 0
    """Running total tokens for the sample (from
    :attr:`inspect_ai.log._samples.ActiveSample.total_tokens`). Drives
    the picker's ``tokens`` column; refreshed on rescan."""


def list_picker_targets() -> list[_PickerTarget]:
    """Snapshot active samples that have claimed ACP.

    Filters :func:`inspect_ai.log._samples.active_samples` to those
    whose ``acp_session`` is set to a non-noop live session — i.e.
    agents that have called ``before_turn`` at least once and
    therefore have a real ``_LiveAcpSession.session_id``.
    """
    targets: list[_PickerTarget] = []
    for sample in active_samples():
        session = sample.acp_session
        if session is None or session.session_id == "noop":
            continue
        targets.append(
            _PickerTarget(
                session_id=session.session_id,
                task=sample.task,
                sample_id=str(sample.sample.id) if sample.sample.id is not None else "",
                epoch=sample.epoch,
                agent_name=sample.agent_name,
                started_at=sample.started,
                total_tokens=sample.total_tokens,
            )
        )
    return targets


def build_picker_notification(
    session_id: str,
    targets: list[_PickerTarget],
) -> SessionNotification:
    """Build the picker ``session/update`` notification payload.

    ``session_id`` is the value to address the notification at — the
    caller chooses whether to use a synthetic control session uuid
    (the typical picker case) or a target's id (the auto-bind /
    confirmation case). The picker module doesn't care which; it
    just builds the payload.

    The notification body is an ``agent_message_chunk`` with a
    numbered list of targets that any ACP-aware client can render as
    text. The ``_meta`` field on the notification carries the same
    list as a structured array under :data:`PICKER_META_KEY` so a
    capability-aware client (e.g. ``inspect acp``) can match by
    ``(task, sample_id, epoch)`` without re-parsing the text.
    """
    if not targets:
        text = (
            "No sessions are currently available. Wait for an eval to start "
            "and try again."
        )
    else:
        lines = ["Available sessions — reply with a number or sessionId:"]
        for i, target in enumerate(targets, start=1):
            lines.append(
                f"  {i}. {target.task} / sample {target.sample_id} / "
                f"epoch {target.epoch}    [{target.session_id}]"
            )
        text = "\n".join(lines)

    meta: dict[str, Any] = {
        PICKER_META_KEY: [
            {
                "sessionId": t.session_id,
                "task": t.task,
                "sampleId": t.sample_id,
                "epoch": t.epoch,
                "agentName": t.agent_name,
                "startedAt": t.started_at,
                "totalTokens": t.total_tokens,
            }
            for t in targets
        ],
    }

    notification = session_notification(
        session_id=session_id,
        update=update_agent_message(text_block(text)),
    )
    notification.field_meta = meta
    return notification


def resolve_selection(
    prompt_text: str,
    targets: list[_PickerTarget],
) -> _PickerTarget | None:
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
