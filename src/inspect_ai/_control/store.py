"""One sample's current Store for the control channel.

Backs ``GET /evals/<id>/sample/store`` (and ``inspect ctl sample store``): a
**snapshot** of one sample's ``Store`` — the shared state solvers, tools, and
agents coordinate through — read from the live ``TaskState.store`` while the
sample is running, and once terminal from the recorder's sample (buffer, then
on-disk log). No event replay on either path: the answer already exists as a
plain dict in memory (live) or on the logged sample (terminal), which is why
a sample whose transcript is bounded (or buffered-only) still answers.

Like ``sample messages``, this is deliberately *not* cursored. The store is
rewritable — ``set`` overwrites, ``delete`` removes, and agent code mutates
values in place — so no index or version cursor over it could deliver
exactly-once resume. Each call returns the current snapshot, enveloped with
``as_of`` / the sample ``status`` / the total key ``count``; a watcher polls,
or follows ``sample events --type store`` when it wants the change *stream*.

See ``design/ctl/sample-store.md`` for the full rationale.
"""

from __future__ import annotations

import json
import time
from typing import Any, NamedTuple

# The per-key projection shares its truncation helpers with the events
# projection so the two renderings of the same underlying values can't drift.
from inspect_ai._control.events import _to_text, _truncate
from inspect_ai._control.terminal_cache import (
    TerminalSourceCache,
    resolve_sample_source,
)


class StoreSource(NamedTuple):
    """One resolvable source of a sample's store.

    Produced by :func:`_running_source` (live ``TaskState``) and
    :func:`_resolve_logged_source` (recorder / on-disk log); consumed by
    :func:`sample_store`. ``store`` holds the *raw* values (not yet
    JSON-serialized) so the ``--key`` filter can run before serialization —
    a targeted read of one small key never pays serialization of a sibling
    megabyte blob.
    """

    store: dict[str, Any]
    """The sample's current store (a snapshot copy, raw values)."""

    status: str
    """``running`` / ``completed`` / ``error``."""


# Short-TTL cache of resolved terminal sources. A terminal sample's store is
# immutable, but resolving it re-pays the whole-sample parse per poll (see
# _resolve_logged_source). See terminal_cache for the staleness bounds.
_terminal_sources: TerminalSourceCache[StoreSource] = TerminalSourceCache()


async def sample_store(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    keys: list[str] | None = None,
    content: bool = False,
    full: bool = False,
) -> dict[str, Any] | None:
    """A snapshot of one sample's current store.

    Returns an ``{as_of, status, count, store[, missing]}`` envelope (see the
    module docstring), or ``None`` when the eval/sample isn't found in this
    process — the endpoint turns that into a 404.

    Args:
        eval_id: The eval's id.
        sample_id: The sample's id (string; matched against running + logged).
        epoch: The sample epoch.
        keys: Server-side key selection — exact names plus trailing-``*``
            prefixes (the ``StoreModel`` namespacing convention); ``None`` or
            empty selects every key. ``count`` still reports the whole
            store's key count, and ``missing`` (present only when keys were
            requested) lists the exact names not in the store — an unknown
            key is not an error, the store is schemaless.
        content: Include a truncated single-line preview of each value in the
            compact projection. The default is metadata only (see
            :func:`_project`).
        full: Raw jsonable values (what ``store_jsonable`` yields — the same
            serialization ``EvalSample.store`` gets, with non-serializable
            values falling back to ``None``) instead of the compact
            projection.
    """
    # `as_of` is stamped before the read so a client comparing successive
    # `count`s can't miss a change that lands mid-read.
    as_of = time.time()

    source = await resolve_sample_source(
        (eval_id, sample_id, epoch),
        running=lambda: _running_source(eval_id, sample_id, epoch),
        cache=_terminal_sources,
        resolve_terminal=lambda: _resolve_logged_source(eval_id, sample_id, epoch),
    )
    if source is None:
        return None

    raw, status = source
    count = len(raw)

    # Filter before serialize: both sources hold raw Python values (the
    # terminal path's pre-flush recorder samples carry `state.store` verbatim,
    # not yet JSON-serialized), so the selected values run through the same
    # `dict_jsonable` the log's `EvalSample.store` gets — on both paths, and
    # only for the selected keys.
    missing: list[str] | None = None
    if keys:
        raw, missing = _filter_keys(raw, keys)
    from inspect_ai.util._store import dict_jsonable

    # No await between `_running_source`'s dict() copy and this call: the
    # copy is shallow, so nested values alias live state until serialized —
    # an inserted await would break live-read atomicity with no test failing.
    jsonable = dict_jsonable(raw)

    projected = (
        jsonable
        if full
        else {key: _project(value, content=content) for key, value in jsonable.items()}
    )

    envelope: dict[str, Any] = {
        "as_of": as_of,
        "status": status,
        "count": count,
        "store": projected,
    }
    # present only when keys were requested (stable shape per mode)
    if missing is not None:
        envelope["missing"] = missing
    return envelope


# --- sources ---------------------------------------------------------------


def _running_source(eval_id: str, sample_id: str, epoch: int) -> StoreSource | None:
    """The live source for a sample, or ``None`` if it isn't running here.

    Reads the sample's live ``TaskState.store`` off ``ActiveSample
    .live_state`` — an in-memory snapshot, no log involved. The control
    server shares the eval's event loop, so copying the dict here can never
    observe a half-applied mutation.
    """
    from inspect_ai._control.state import find_active_sample

    s = find_active_sample(eval_id, sample_id, epoch)
    if s is None or s.live_state is None:
        return None
    return StoreSource(
        store=dict(s.live_state.store.items()),
        status="completed" if s.completed is not None else "running",
    )


async def _resolve_logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> StoreSource | None:
    """The terminal source for a sample (recorder buffer, then on-disk log).

    ``None`` when the eval/sample isn't available here. Reads the
    ``EvalSample`` via :func:`inspect_ai._control.state._full_sample` — the
    same gap-free recorder-then-log source the sibling reads use — excluding
    every heavy field the response never consumes (``events`` dwarfs the rest
    for a long agentic sample; ``error_retries`` can carry full retry
    transcripts of its own). ``EvalSample.store`` is stored verbatim —
    ``condense_sample`` never pools the sample-level store — so no attachment
    resolution is needed.
    """
    from inspect_ai._control.state import _full_sample

    sample = await _full_sample(
        eval_id,
        sample_id,
        epoch,
        exclude_fields={"messages", "events", "attachments", "output", "error_retries"},
    )
    if sample is None:
        return None
    return StoreSource(
        store=dict(sample.store or {}),
        status="error" if sample.error is not None else "completed",
    )


# --- key filtering ----------------------------------------------------------


def _filter_keys(
    raw: dict[str, Any], keys: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """Select ``keys`` from ``raw``: exact names plus trailing-``*`` prefixes.

    The only glob form is the trailing ``*`` — it covers the ``StoreModel``
    namespacing convention (``ClassName:field``), and a closed grammar keeps
    the wire contract simple. Returns the selection (in store order, so a key
    matched by several patterns appears once) and the exact-name misses (in
    request order, deduplicated) — an unknown key is not an error, the store
    is schemaless.
    """
    exact = {key for key in keys if not key.endswith("*")}
    prefixes = [key[:-1] for key in keys if key.endswith("*")]
    selected = {
        name: value
        for name, value in raw.items()
        if name in exact or any(name.startswith(prefix) for prefix in prefixes)
    }
    missing = [key for key in dict.fromkeys(keys) if key in exact and key not in raw]
    return selected, missing


# --- projection ------------------------------------------------------------


def _project(value: Any, *, content: bool) -> dict[str, Any]:
    """Compact, context-cheap summary of one (already jsonable) store value.

    The metadata form carries the value's JSON ``type``, its serialized
    ``size`` in UTF-8 bytes (compact JSON — cheap and deterministic, for
    spotting the big keys; it differs from Python memory size and on-disk
    size), and a
    ``len`` hint (string length, array length, or object key count) — no
    values. ``content`` adds ``value``, a truncated single-line preview.
    Store values are agent-controlled text, so the metadata default exists
    for monitors that must never ingest it (see "Trust boundary for readers"
    in design/ctl/control-channel.md); ``--full`` bypasses this projection
    entirely.
    """
    projected: dict[str, Any] = {
        "type": _json_type(value),
        # ensure_ascii=False so non-ASCII text counts its real UTF-8 bytes
        # rather than the ~3x-larger \uXXXX escape form
        "size": len(
            json.dumps(
                value, separators=(",", ":"), default=str, ensure_ascii=False
            ).encode("utf-8")
        ),
    }
    length = _length_hint(value)
    if length is not None:
        projected["len"] = length
    if content:
        projected["value"] = _truncate(_to_text(value))
    return projected


def _json_type(value: Any) -> str:
    """The JSON type name of an already-jsonable value.

    ``bool`` before ``int`` — Python bools are ints. Anything unrecognized
    reads ``null`` (post-``dict_jsonable`` the non-serializable fallback is
    ``None``, so this arm is belt-and-braces).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def _length_hint(value: Any) -> int | None:
    """String length, array length, or object key count; ``None`` for scalars."""
    if isinstance(value, (str, list, dict)):
        return len(value)
    return None
