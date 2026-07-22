"""Recording of applied ``ctl config`` changes into the affected eval logs.

The glue between the config appliers (:mod:`inspect_ai._control.limits`) and
the log schema (:mod:`inspect_ai.log._config_update`): when a ``PATCH``
config directive actually changes something, the applied changes are grouped
into provenance-carrying :class:`~inspect_ai.log._config_update.ConfigUpdate`
records and persisted into every affected task's live log (task-scoped
changes → that task's log; process-scoped changes → every task log active in
the process). Recording is bookkeeping, never control: a failure degrades to
a warning (plus ``persisted: false`` in the result envelope) and the retune
still succeeds.

Process-scoped state outlives individual attempts and eval-set children, so
the run's accumulated process-scoped updates are also kept here (run-scoped,
reset by ``reset_run_registries()``): each ``TaskLogger`` records them into
its log (original provenance/timestamps preserved, marked ``inherited`` via
``provenance.metadata``) via a watermark it advances as it records — at
``init()`` for retunes that predate the log (a retry attempt or a later
eval-set child), and again at task start for retunes applied while the task
sat queued between its up-front init and ``register_eval`` (see
``TaskLogger.record_inherited_config_updates``).

No lock: everything here runs on the eval's single event loop thread (the
control-server handlers and ``TaskLogger.init`` alike), and each accessor is
a plain list operation.
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import JsonValue

    from inspect_ai._control.eval_state import LiveEvalData
    from inspect_ai.log._config_update import ConfigUpdate, ConfigValueChange

logger = getLogger(__name__)

# The run's process-scoped updates, in application order (see module docstring).
_process_updates: list["ConfigUpdate"] = []


def inherited_config_updates(start: int = 0) -> list["ConfigUpdate"]:
    """Copies of the run's process-scoped updates from ``start`` onward.

    Original provenance and timestamps are preserved — the records say when
    the change really happened, which predates the receiving log's own record
    of it — and each copy is marked ``inherited: true`` in
    ``provenance.metadata`` so a reader can tell "recorded after the fact"
    from "applied while this log was a live fan-out target". ``start`` is the
    caller's watermark (how many it has already recorded), so a catch-up
    doesn't duplicate earlier records.
    """
    copies: list["ConfigUpdate"] = []
    for update in _process_updates[start:]:
        copy = update.model_copy(deep=True)
        copy.provenance.metadata = {**copy.provenance.metadata, "inherited": True}
        copies.append(copy)
    return copies


def process_config_update_count() -> int:
    """Number of process-scoped updates accumulated so far this run.

    The counterpart to :func:`inherited_config_updates`'s ``start`` — a
    ``TaskLogger`` compares its watermark to this to see whether it has
    updates to catch up on.
    """
    return len(_process_updates)


def reset_process_config_updates() -> None:
    """Clear the accumulated process-scoped updates (run-boundary reset)."""
    _process_updates.clear()


def _resolve_author(author: str | None) -> str:
    """The provenance author: the client-asserted value, else the OS user.

    The ctl CLI resolves the author client-side (git identity, then OS
    username) and forwards it on the PATCH; an older client sends none, in
    which case the server's OS user is the best available answer (the
    control socket is AF_UNIX, so client and server share a host and
    typically a user).
    """
    if author:
        return author
    import getpass

    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


async def _record_to(
    live: "LiveEvalData", update: "ConfigUpdate", log_location: str
) -> bool | None:
    """Record ``update`` into one live log, degrading failure to a warning.

    Returns ``True`` when the record was written, ``None`` when the logger
    declined because its log has already finished (a complete log is not a
    recording target — not a failure), and ``False`` when recording failed.
    """
    try:
        return True if await live.log_config_update(update) else None
    except Exception as ex:
        logger.warning(
            "Could not record config update in eval log %s: %s", log_location, ex
        )
        return False


async def record_config_changes(
    *,
    task_id: str | None,
    task_changes: "list[ConfigValueChange]",
    process_changes: "list[ConfigValueChange]",
    author: str | None = None,
    reason: str | None = None,
    metadata: "dict[str, JsonValue] | None" = None,
) -> dict[str, bool] | None:
    """Persist applied config changes into the affected eval logs.

    Called by the config directives after applying a ``PATCH``'s knobs (only
    changes that were actually applied are passed — no-ops and warn-and-skip
    knobs record nothing). One ``ConfigUpdate`` is written per scope:
    task-scoped changes go to ``task_id``'s live log; process-scoped changes
    fan out to every live task log in the process and join the run-scoped
    inheritance list. Both updates from one PATCH share provenance
    (``metadata`` rides in ``provenance.metadata`` — e.g. the model filter a
    ``max_connections`` retune was restricted to).

    Returns a per-knob ``persisted`` map (``True`` when the change was
    recorded in every targeted log, and at least one log was targeted), or
    ``None`` when there was nothing to record — the shape the result
    envelope's ``persisted`` field reports. A logger whose log has already
    finished declines the record (its record is complete — the change never
    governed it) and does not count as a target, so a process-scoped retune
    in a multi-task run isn't reported unpersisted just because an earlier
    task finished. Never raises for a recording failure (requirement: the
    record never blocks the retune).
    """
    from inspect_ai._control.eval_state import get_eval_states, latest_eval_for_task
    from inspect_ai.log._config_update import ConfigUpdate
    from inspect_ai.log._edit import ProvenanceData

    if not task_changes and not process_changes:
        return None

    provenance = ProvenanceData(
        author=_resolve_author(author), reason=reason, metadata=metadata or {}
    )
    persisted: dict[str, bool] = {}

    if task_changes:
        update = ConfigUpdate(changes=task_changes, scope="task", provenance=provenance)
        recorded = False
        state = latest_eval_for_task(task_id) if task_id else None
        if state is not None and state.live is not None:
            # a decline (finished log) leaves no target, so it reads as
            # unrecorded here — honest for a single-log scope
            recorded = await _record_to(state.live, update, state.log_location) is True
        for change in task_changes:
            persisted[change.name] = recorded

    if process_changes:
        update = ConfigUpdate(
            changes=process_changes, scope="process", provenance=provenance
        )
        _process_updates.append(update)
        # every task log currently live in the process gets the record (a
        # logger can back several registered attempts; record to it once);
        # finished logs decline (None) and drop out of the persisted fold
        results: list[bool] = []
        seen: set[int] = set()
        for state in get_eval_states():
            live = state.live
            if live is None or id(live) in seen:
                continue
            seen.add(id(live))
            result = await _record_to(live, update, state.log_location)
            if result is not None:
                results.append(result)
        recorded = bool(results) and all(results)
        for change in process_changes:
            persisted[change.name] = recorded

    return persisted
