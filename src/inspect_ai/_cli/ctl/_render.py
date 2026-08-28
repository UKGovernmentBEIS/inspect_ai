"""Human-output rendering shared across nouns.

Every ``_print_*`` / ``_format_*`` helper, tables, footers, and the
output sanitizers.
"""

from __future__ import annotations

import json as json_lib
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import click

from ._knobs import _KNOB_SCOPE

# Rendered for a task-scoped knob that a process-level view can't show.
_PER_TASK_PLACEHOLDER = "per task (pass a task to view/set)"

# Display truncation for task ids (`task list` shows this many characters).
# Also the id-prefix length a busy-skipped resolution trusts (see
# `_resolve_target_eval` for the rationale).
_SHORT_ID_LEN = 12


def _paused_sources(value: Any) -> list[str]:
    """Normalize a ``paused`` field to its list of holding latches.

    Current servers send the source list (``["task", "process", "model"]``
    in any combination); pre-model-latch servers (<= 0.3.250) sent a single
    string with ``"both"`` for task+process. ``None``/empty means not
    paused.
    """
    if not value:
        return []
    if isinstance(value, str):
        return ["task", "process"] if value == "both" else [value]
    return [str(v) for v in value]


def _knob_label(display: str, knob: str) -> str:
    """Aligned human config label carrying the knob's scope from ``_KNOB_SCOPE``."""
    # width fits the longest label ("max subprocesses [process]:") plus a
    # space — widen it if a longer knob label is ever added
    return f"  {display} [{_KNOB_SCOPE[knob]}]:".ljust(30)


def _print_config(config: dict[str, Any], *, changed: bool) -> None:
    """Render the composed config view as a short labeled block.

    Every knob line carries its scope (``task`` / ``process``) — the honest
    place to read a knob's blast radius, since the command path makes no
    scope claim.
    """
    dry_run = bool(config.get("dry_run"))
    if changed:
        _echo("would-be config (dry run):" if dry_run else "updated config:")
    else:
        _echo("config:")

    knobs = config.get("knobs") or {}

    # On a dry-run the server reports the pre-change view (nothing was mutated);
    # the intended values live in `requested`. Render `current → would-be` so the
    # header's promise is met without losing the current value. On a real set the
    # view already reflects the applied change, so no arrow is needed.
    requested = config.get("requested") if dry_run else None
    requested = requested if isinstance(requested, dict) else {}

    def _target(current: Any, key: str) -> str:
        proposed = requested.get(key)
        return f"{current}{'' if proposed is None or proposed == current else f' → {proposed}'}"

    # The process-level view carries no `max_samples` knob (it's per-task):
    # show it as per-task rather than claiming a value. Distinguish that from
    # a task view that carries an explicit `{"adjustable": false}`.
    if "max_samples" not in knobs:
        _echo(_knob_label("max samples", "max_samples") + _PER_TASK_PLACEHOLDER)
    else:
        max_samples = knobs.get("max_samples") or {}
        if max_samples.get("adjustable"):
            limit = _target(max_samples.get("limit"), "max_samples")
            in_use = max_samples.get("in_use")
            label = _knob_label("max samples", "max_samples")
            _echo(f"{label}{limit} ({in_use} in use)")
        elif max_samples.get("tracks_adaptive"):
            # sample concurrency tracks this task's adaptive controller, so
            # there's no user setpoint to show — point at where the numbers are
            _echo(
                _knob_label("max samples", "max_samples")
                + "tracks adaptive connections (see below)"
            )
        else:
            # no live sample limiter for this task (e.g. a reused log) — the
            # adaptive block below, if any, belongs to other tasks' models
            _echo(
                _knob_label("max samples", "max_samples")
                + "not adjustable (no live sample limiter)"
            )

    # max_tasks — the task dispatchers' live override (absent from an older
    # server's view). With no live dispatcher (during batch startup / between
    # sequential batches) there are no counters to show, but a set still
    # lands in the override layer — say so rather than looking parked.
    max_tasks_view = knobs.get("max_tasks")
    if max_tasks_view is not None:
        override = max_tasks_view.get("override")
        launch = max_tasks_view.get("launch")
        limit = max_tasks_view.get("limit")

        def fmt_tasks(value: Any) -> str:
            return "launch config" if value in (None, "clear") else f"{value}"

        if launch is not None:
            rendered = fmt_tasks(limit)
            proposed = requested.get("max_tasks")
            # a `clear` with no override in effect is a no-op (the effective
            # limit already is the launch config) — no arrow, like the retry
            # knobs' rendering of the same case
            is_change = (
                override is not None
                if proposed == "clear"
                else fmt_tasks(proposed) != fmt_tasks(limit)
            )
            if proposed is not None and is_change:
                rendered += f" → {fmt_tasks(proposed)}"
            rendered += (
                f" ({max_tasks_view.get('in_flight')} in flight, "
                f"{max_tasks_view.get('pending')} pending)"
            )
            if override is not None:
                rendered += f" (override; launch: {launch})"
        else:
            rendered = (
                f"{override} (override)" if override is not None else "launch config"
            )
            proposed = requested.get("max_tasks")
            if proposed is not None and fmt_tasks(proposed) != fmt_tasks(override):
                rendered += f" → {fmt_tasks(proposed)}"
            rendered += (
                " — no task dispatcher is live; applies to task dispatch "
                "later in this run"
            )
        _echo(_knob_label("max tasks", "max_tasks") + rendered)

    sandboxes = (knobs.get("max_sandboxes") or {}).get("providers") or []
    if sandboxes:
        rendered = ", ".join(
            f"{s.get('type')} {_target(s.get('limit'), 'max_sandboxes')} ({s.get('in_use')} in use)"
            for s in sandboxes
        )
        _echo(f"{_knob_label('max sandboxes', 'max_sandboxes')}{rendered}")
    else:
        _echo(_knob_label("max sandboxes", "max_sandboxes") + "none in effect")

    subprocesses = knobs.get("max_subprocesses") or {}
    if subprocesses.get("limit") is not None:
        limit = _target(subprocesses.get("limit"), "max_subprocesses")
        _echo(
            f"{_knob_label('max subprocesses', 'max_subprocesses')}{limit} "
            f"({subprocesses.get('in_use')} in use)"
        )
    else:
        _echo(
            _knob_label("max subprocesses", "max_subprocesses")
            + "inactive (no adjustable subprocess limiter yet)"
        )

    adaptive = (knobs.get("max_connections") or {}).get("adaptive") or []
    if adaptive:
        _echo(f"  adaptive connections [{_KNOB_SCOPE['max_connections']}]:")
        for a in adaptive:
            # on a dry-run set, `_target` renders the ceiling as `max → requested`
            ceiling = _target(a.get("max"), "max_connections")
            # sanitize the name before composing so a swallow in it can't
            # eat the line's data fields (`_echo` handles the rest)
            name = _sanitize_line(str(a.get("name") or ""))
            line = (
                f"    {name}: {a.get('limit')} ({a.get('in_use')} in use), "
                f"range {a.get('min')}–{ceiling}"
            )
            changes = a.get("recent_changes") or []
            if changes:
                last = changes[-1]
                line += (
                    f", last: {last.get('from')}→{last.get('to')} {last.get('reason')}"
                )
            _echo(line)

    # The retry-override knobs. Absent entirely from an older server's view
    # (which has no override layer) — skipped then rather than shown as a
    # value claim. A knob's current value is the live override or "launch
    # config" (no override — each generate call's own config applies); on a
    # dry-run the requested value renders as an arrow, with `clear` shown as
    # its meaning (back to launch config).
    def _render_override_knob(knob: str, display: str, unit: str) -> None:
        view = knobs.get(knob)
        if view is None:
            return

        def fmt(value: Any) -> str:
            return "launch config" if value in (None, "clear") else f"{value}{unit}"

        current = view.get("override")
        rendered = fmt(current) if current is None else f"{fmt(current)} (override)"
        proposed = requested.get(knob)
        if proposed is not None and fmt(proposed) != fmt(current):
            rendered += f" → {fmt(proposed)}"
        _echo(_knob_label(display, knob) + rendered)

    _render_override_knob("timeout", "timeout", "s")
    _render_override_knob("attempt_timeout", "attempt timeout", "s")
    _render_override_knob("max_retries", "max retries", "")

    # The per-sample limit overrides — task-scoped, so a process-level view
    # can't show them: mirror the max_samples placeholder there (keeping the
    # knobs discoverable), while a task view missing them means an older
    # server (skipped, like the retry knobs — no value claim to make).
    process_scope = (config.get("target") or {}).get("scope") == "process"
    for knob, display, unit in (
        ("time_limit", "time limit", "s"),
        ("token_limit", "token limit", ""),
        ("message_limit", "message limit", ""),
    ):
        if knob in knobs:
            _render_override_knob(knob, display, unit)
        elif process_scope:
            _echo(_knob_label(display, knob) + _PER_TASK_PLACEHOLDER)

    # The named concurrency() registry entries, addressable via `--key` by the
    # exact name shown. Entries appear lazily on first use, so an empty
    # registry gets a placeholder (like the sibling knobs) that keeps the
    # knob discoverable and distinguishes it from an older server whose view
    # omits the section (`keys` is None).
    keys = (knobs.get("concurrency") or {}).get("keys")
    if keys:
        _echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]:")
        for row in keys:
            # on a dry-run set, `_target` renders the requested key's limit as
            # `current → requested` (the request rides `concurrency:<name>`)
            limit = _target(row.get("limit"), f"concurrency:{row.get('name')}")
            # concurrency() names are arbitrary registry strings; sanitize
            # before composing so a swallow can't eat the line's data fields
            name = _sanitize_line(str(row.get("name") or ""))
            line = f"    {name}: {limit} ({row.get('in_use')} in use)"
            if not row.get("adjustable"):
                line += " — not adjustable"
            _echo(line)
    else:
        empty = (
            "none registered yet (named limits appear on first use)"
            if keys is not None
            else "not reported (older server)"
        )
        _echo(f"  concurrency keys [{_KNOB_SCOPE['key']}]: {empty}")

    # The process-level view carries no buffer knobs (they're per-task, read
    # off one task's live logger): mirror the max_samples placeholder so the
    # knobs' existence — and how to see them — stays visible. A *task* view
    # missing them (no live buffer) is reported via warnings instead.
    if "log_buffer" in knobs:
        log_buffer = knobs.get("log_buffer") or {}
        value = _target(log_buffer.get("value"), "log_buffer")
        _echo(
            f"{_knob_label('log buffer', 'log_buffer')}{value} samples "
            f"({log_buffer.get('pending')} pending)"
        )
    elif process_scope:
        _echo(_knob_label("log buffer", "log_buffer") + _PER_TASK_PLACEHOLDER)
    if "log_shared" in knobs:
        shared = (knobs.get("log_shared") or {}).get("value")
        rendered_shared = _target(shared, "log_shared") if shared is not None else None
        _echo(
            _knob_label("shared sync", "log_shared")
            + f"{f'{rendered_shared}s' if rendered_shared is not None else 'off'}"
        )
    elif process_scope:
        _echo(_knob_label("shared sync", "log_shared") + _PER_TASK_PLACEHOLDER)

    for warning in config.get("warnings") or []:
        _echo(f"  ! {warning}")
    for note in config.get("notes") or []:
        _echo(f"  note: {note}")


def _events_carry_content(events: list[dict[str, Any]]) -> bool:
    """True when a compact events page came back with free-text fields.

    The withheld-content footers key on the response, not the request: a
    pre-v6 server ignores the unknown ``content`` query param and returns
    the old content-bearing projection, and a "metadata only" footer must
    not contradict text printed right above it. The listed keys are emitted
    by ``events._project`` only under ``content`` (v6+) and unconditionally
    on the typed branches before v6, so their presence means content came
    back; a page of header-only events has no signal, but then the footer
    claims nothing false either.
    """
    fields = ("completion", "arguments", "result", "error", "data")
    return any(field in event for event in events for field in fields)


def _print_events(page: dict[str, Any], *, content: bool, full: bool) -> None:
    """Render a page of transcript events (table) plus a cursor footer.

    The metadata-only footer is response-keyed (see
    :func:`_events_carry_content`).
    """
    events = page.get("events") or []
    if full:
        # Raw mode is for machine consumption; the human rendering is the
        # compact projection (whose flattened fields the table expects), so
        # just pretty-print the raw events.
        _echo_raw(json_lib.dumps(events, indent=2))
    elif not events:
        _echo("(no events)")
    else:
        rows: list[tuple[str, ...]] = []
        for e in events:
            ts = e.get("timestamp")
            rows.append(
                (
                    _format_started(ts) if isinstance(ts, (int, float)) else "",
                    str(e.get("event", "") or ""),
                    _event_summary(e),
                )
            )
        _render_table(("time", "event", "summary"), rows)

    parts = [f"{len(events)} event" + ("" if len(events) == 1 else "s")]
    parts.append("done" if page.get("done") else "more")
    if not full and not content and not _events_carry_content(events):
        parts.append("metadata only (pass --content for text)")
    _echo()
    _echo("  ·  ".join(parts))
    nxt = page.get("next")
    if nxt and not page.get("done"):
        _echo(f"next: {_sanitize_line(str(nxt))}  (resume with --cursor)")


def _print_messages(page: dict[str, Any], *, content: bool, full: bool) -> None:
    """Render a conversation snapshot (per-message rows) plus a count footer.

    The metadata-only footer is response-keyed, like the events one (see
    :func:`_events_carry_content`): a ``content`` key on any message means a
    pre-v6 server returned the old always-content projection, so the footer
    would contradict the table above it.
    """
    messages = page.get("messages") or []
    count = int(page.get("count") or 0)
    status = page.get("status")

    if full:
        # Raw mode is for machine consumption; the human rendering is the
        # compact projection, so just pretty-print the raw messages.
        _echo_raw(json_lib.dumps(messages, indent=2))
    elif not messages:
        _echo("(no messages)")
    else:
        rows: list[tuple[str, ...]] = []
        for m in messages:
            rows.append(
                (
                    str(m.get("index", "")),
                    str(m.get("role", "") or ""),
                    _message_summary(m),
                )
            )
        _render_table(("#", "role", "content"), rows)

    shown = len(messages)
    footer = f"{shown} of {count} message" + ("" if count == 1 else "s")
    if shown < count:
        footer += " (use --all for the whole conversation)"
    if status:
        footer += f"  ·  {_sanitize_line(str(status))}"
    if not full and not content and not any("content" in m for m in messages):
        footer += "  ·  metadata only (pass --content for text)"
    _echo()
    _echo(footer)


def _message_summary(m: dict[str, Any]) -> str:
    """One-line summary for a message row (best-effort over compact fields).

    Tolerates the metadata-only projection (no content / arguments / error
    text): tool calls render as bare function names, a tool message as its
    function, and a withheld error as a bare ``error`` marker.

    Every wire field is sanitized at its interpolation site (provenance is
    irrelevant — see ``_sanitize_control``) so an unterminated string
    sequence in one (e.g. the message content) can't swallow the parts
    appended after it — the tool-call list or the ``error:`` tag.
    """
    parts = [_sanitize_control(str(m.get("content") or ""))]
    if m.get("role") == "tool" and "content" not in m and m.get("function"):
        parts.append(f"[{_sanitize_control(str(m['function']))} output]")
    for call in m.get("tool_calls") or []:
        arguments = (
            _truncate(str(call["arguments"]), 30) if call.get("arguments") else ""
        )
        parts.append(
            f"→ {_sanitize_control(str(call.get('function') or '?'))}({arguments})"
        )
    if m.get("error"):
        parts.append(f"error: {_sanitize_control(str(m['error']))}")
    elif m.get("has_error"):
        parts.append("error")
    return _truncate("  ".join(p for p in parts if p), 100)


def _print_store(page: dict[str, Any], *, content: bool, full: bool) -> None:
    """Render a store snapshot (per-key rows) plus a count footer.

    The table is ``key | type | size [| value]`` per the design
    (design/ctl/sample-store.md); ``--full`` pretty-prints the raw values.
    The footer distinguishes an empty store from a filter that matched
    nothing (``count`` is always the whole store's key count), and a
    ``missing`` line names requested exact keys not present.
    """
    store = page.get("store") or {}
    count = int(page.get("count") or 0)
    status = page.get("status")

    if full:
        # Raw mode is for machine consumption; the human rendering is the
        # compact projection, so just pretty-print the raw values.
        _echo_raw(json_lib.dumps(store, indent=2))
    elif not store:
        _echo("(store is empty)" if count == 0 else "(no matching keys)")
    else:
        rows: list[tuple[str, ...]] = []
        for key, projected in store.items():
            projected = projected if isinstance(projected, dict) else {}
            row: tuple[str, ...] = (
                str(key),
                str(projected.get("type", "") or ""),
                str(projected.get("size", "") or ""),
            )
            if content:
                # clamp client-side like the sibling tables (the server
                # preview can be 256 chars, which would blow out the padded
                # table width); the full preview remains available via --json
                row += (_truncate(str(projected.get("value", "") or ""), 100),)
            rows.append(row)
        headers = ("key", "type", "size") + (("value",) if content else ())
        _render_table(headers, rows)

    shown = len(store)
    footer = f"{shown} of {count} key" + ("" if count == 1 else "s")
    if status:
        footer += f"  ·  {_sanitize_line(str(status))}"
    if not full and not content:
        footer += "  ·  metadata only (pass --content for values)"
    _echo()
    _echo(footer)
    missing = page.get("missing") or []
    if missing:
        _echo("missing: " + ", ".join(_sanitize_line(str(key)) for key in missing))


def _event_summary(e: dict[str, Any]) -> str:
    """One-line summary for an event row (best-effort over compact fields).

    A pending (in-flight) event renders its live state — ``generating M:SS``
    for a model call, ``running M:SS`` for a tool call — instead of the
    completion fields, whose placeholder values (zero tokens, a default stop
    reason) would read as "finished with nothing". Tolerates the
    metadata-only projection (no completion / arguments / result / error
    text): a withheld model/tool error renders as a bare ``error`` marker,
    while an ``error``-type event renders an empty summary (its type column
    already reads ``error``, so a marker would only duplicate it).

    Every wire field is sanitized at its interpolation site (provenance is
    irrelevant — see ``_sanitize_control``) so an unterminated string
    sequence in one can't swallow the fields appended after it within the
    summary.
    """
    t = e.get("event")
    if t == "model":
        bits = [_sanitize_control(str(e.get("model") or ""))]
        if e.get("pending"):
            bits.append(_format_pending("generating", e.get("timestamp")))
            return _truncate(" · ".join(b for b in bits if b), 80)
        if e.get("tokens") is not None:
            bits.append(f"{e['tokens']} tok")
        if e.get("stop_reason"):
            bits.append(_sanitize_control(str(e["stop_reason"])))
        if e.get("completion"):
            bits.append(_sanitize_control(str(e["completion"])))
        if e.get("error"):
            bits.append(f"error: {_sanitize_control(str(e['error']))}")
        elif e.get("has_error"):
            bits.append("error")
        return _truncate(" · ".join(b for b in bits if b), 80)
    if t == "tool":
        arguments = _truncate(str(e["arguments"]), 30) if e.get("arguments") else ""
        s = f"{_sanitize_control(str(e.get('function') or '?'))}({arguments})"
        if e.get("pending"):
            s += f" · {_format_pending('running', e.get('timestamp'))}"
        elif e.get("error"):
            s += f" → error: {_sanitize_control(str(e['error']))}"
        elif e.get("has_error"):
            s += " → error"
        elif e.get("result"):
            s += f" → {_truncate(str(e['result']), 40)}"
        return _truncate(s, 80)
    if t == "error":
        return _truncate(str(e.get("error") or ""), 80)
    if t == "info":
        bits = [
            _sanitize_control(str(e.get("source") or "")),
            _sanitize_control(str(e.get("data") or "")),
        ]
        return _truncate(" · ".join(b for b in bits if b), 80)
    return ""


def _print_errors_table(samples: list[dict[str, Any]], show_task: bool = False) -> None:
    """Render errored/retried samples as a triage table on stdout.

    ``show_task`` adds a leading task column — the rendering for a listing
    that spans tasks (the ``--json`` rows carry ``task_id`` regardless).
    """
    rows: list[tuple[str, ...]] = []
    for s in samples:
        row = [
            str(s["sample_id"]) if s.get("sample_id") is not None else "?",
            str(s.get("epoch", "")),
            s.get("status", "") or "",
            str(s["retries"]) if s.get("retries") else "",
            _truncate(s.get("error") or "", 64),
        ]
        if show_task:
            row.insert(0, str(s.get("task") or _short_id(str(s.get("task_id") or ""))))
        rows.append(tuple(row))
    headers = ["sample", "epoch", "status", "retries", "error"]
    if show_task:
        headers.insert(0, "task")
    _render_table(tuple(headers), rows)


def _print_sample_detail(detail: dict[str, Any], show_traceback: bool) -> None:
    """Render one sample's summary + error history (prior attempts, then final)."""
    parts = [
        f"sample {detail.get('sample_id')}",
        f"epoch {detail.get('epoch')}",
        detail.get("status") or "",
    ]
    activity = _format_activity(
        detail.get("activity"), datetime.now(timezone.utc).timestamp()
    )
    if activity:
        parts.append(activity)
    if detail.get("total_time") is not None:
        parts.append(_format_duration(detail.get("total_time")))
    if detail.get("total_tokens"):
        parts.append(f"{detail['total_tokens']} tok")
    if detail.get("message_count"):
        parts.append(f"{detail['message_count']} msgs")
    if detail.get("retries"):
        parts.append(f"{detail['retries']} retries")
    scores = detail.get("scores") or {}
    if scores:
        # sanitize each k=v pair before joining so an unterminated string
        # sequence in one score value can't swallow the scores after it
        parts.append(
            "score "
            + ", ".join(
                _sanitize_control(f"{k}={_format_score(v)}") for k, v in scores.items()
            )
        )
    # sanitize each part separately so an unterminated string sequence in one
    # can't swallow the fields joined after it, and flatten newlines so one
    # part can't forge a plausible header line of its own; filter on the
    # sanitized value so a part that was all control bytes doesn't leave a
    # dangling separator
    sanitized_parts = (_sanitize_line(p) for p in parts)
    _echo("  ·  ".join(p for p in sanitized_parts if p))

    # `is not None`, not truthiness: a metadata-only read (no --content)
    # carries a present-but-withheld error as an *empty* dict
    error = detail.get("error")
    retries = detail.get("error_retries") or []
    if error is None and not retries:
        _echo("\n(no errors)")
        return

    if retries:
        _echo("\nprior attempts:")
        for i, retry_error in enumerate(retries, start=1):
            _echo_error(f"attempt {i}:", retry_error, show_traceback)
    if error is not None:
        _echo("\nfinal error:")
        _echo_error("", error, show_traceback)


def _echo_error(label: str, error: dict[str, Any], show_traceback: bool) -> None:
    """Echo one error: ``label  message`` plus an indented traceback if asked.

    A metadata-only detail (no ``--content``) carries each error as an empty
    dict — no ``message`` key at all — rendered as an explicit withheld
    marker rather than a blank line a reader would take for an empty message.
    """
    # flatten newlines so a crafted message can't print continuation lines at
    # column 0 that mimic surrounding output (full text remains via --json)
    message = (
        _sanitize_line(error.get("message") or "")
        if "message" in error
        else "(message withheld — pass --content to include it)"
    )
    _echo(f"  {label} {message}".rstrip() if label else f"  {message}")
    if show_traceback:
        traceback_ansi = error.get("traceback_ansi")
        if traceback_ansi:
            tb = _sanitize_keep_sgr(traceback_ansi)
        else:
            tb = _sanitize_control(error.get("traceback") or "")
        for line in tb.rstrip("\n").splitlines():
            # raw: `_echo` would strip the SGR styling `_sanitize_keep_sgr` kept
            _echo_raw(f"    {line}")


def _format_pending(verb: str, timestamp: Any) -> str:
    """In-flight marker for a pending event's summary: ``generating M:SS``."""
    elapsed = (
        _format_duration(datetime.now(timezone.utc).timestamp() - timestamp)
        if isinstance(timestamp, (int, float))
        else ""
    )
    return f"{verb} {elapsed}".rstrip()


# Well-formed ANSI escape sequences, removed whole so their printable payload
# (e.g. the `0;title` of an OSC title write) doesn't survive as stray text:
# CSI (params + intermediates + final byte), the string sequences (OSC and
# DCS/SOS/PM/APC — BEL-, ST-, or raw-C1-ST-terminated, tolerating an
# unterminated tail), charset designations, then any other two-byte ESC
# sequence.
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[\]PX^_][^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"  # OSC/DCS/SOS/PM/APC
    r"|\x1b[()*+./-][0-~]"  # charset designations
    r"|\x1b."  # C1 aliases, keypad modes, etc.
)

# Remaining C0 controls (newline and tab excepted — handled by callers and
# `_sanitize_control` respectively), DEL, raw 8-bit C1 controls, and Unicode
# bidi controls (ALM, LRM/RLM, embeddings/overrides, isolates): on
# BiDi-aware terminals (VTE, mintty) an RLO in one table cell visually
# reorders the rest of the physical line, trusted columns included (cf.
# Trojan Source, CVE-2021-42574). Costs explicit direction marks in
# legitimate RTL output — the right trade for a triage CLI.
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f"
    r"\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


def _sanitize_control(text: str) -> str:
    """Neutralize terminal control bytes in display text.

    Tool results and model completions land verbatim in the transcript and
    flow out through the read commands' human renderings, so a sample under
    evaluation can emit ESC/CSI/OSC sequences, carriage returns, or
    backspaces that rewrite what the operator's terminal shows (spoofed
    results, title/clipboard writes). Rather than classify which fields an
    agent can influence — a provenance analysis that silently rots as
    fields are added — the human rendering paths sanitize *every* dynamic
    string at its formatting boundary (table cells, summary/label
    interpolations, joined header parts, echoed status lines). The function
    is a no-op on clean text and idempotent, so blanket application costs
    nothing; where several fields join into one line, each is sanitized
    before the join so an unterminated string sequence in one can't swallow
    the fields after it.

    Well-formed escape sequences are removed whole (payload included), tabs
    become single spaces (they'd break the tables' width math), and any
    remaining C0/C1 control byte or Unicode bidi control is dropped —
    newline excepted: single-line renderings flatten it via
    ``_sanitize_line``, multi-line ones (tracebacks) keep it. The
    ``--json`` / ``--full`` machine paths are deliberately not routed
    through here (``json.dumps`` escapes control bytes);
    ``traceback_ansi`` goes through ``_sanitize_keep_sgr``, which
    preserves SGR styling and routes everything else through this
    function.
    """
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _CONTROL_CHARS_RE.sub("", text.replace("\t", " "))


def _sanitize_line(text: str) -> str:
    """``_sanitize_control`` plus newline flattening, for one-line renderings.

    Any field interpolated into a single-line rendering — a table cell, a
    joined header part, a status/reason echo — flattens embedded newlines to
    spaces so the field can't print a forged line of its own at column 0.
    Multi-line renderings (tracebacks) use ``_sanitize_control`` directly.
    """
    return _sanitize_control(text).replace("\n", " ")


# SGR (color/style) sequences — the one escape class rich's own tracebacks
# legitimately contain, and inert on their own (they can restyle, never
# rewrite or exfiltrate).
_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def _sanitize_keep_sgr(text: str) -> str:
    """`_sanitize_control`, but preserving SGR color/style sequences.

    For ``traceback_ansi``: usually Inspect's own rich rendering (SGR-only
    styling worth keeping), but it falls back to raw, un-rendered text for
    oversized tracebacks and in recovered logs — and a traceback embeds
    agent-influenced exception text — so everything except SGR is
    neutralized rather than trusted wholesale. Kept styling is closed with
    a trailing reset: a raw fallback can end mid-style (even an SGR 8
    conceal), which would otherwise bleed into subsequent trusted output.
    """
    out: list[str] = []
    last = 0
    for m in _SGR_RE.finditer(text):
        out.append(_sanitize_control(text[last : m.start()]))
        out.append(m.group())
        last = m.end()
    out.append(_sanitize_control(text[last:]))
    result = "".join(out)
    if last:
        stripped = result.rstrip("\n")
        if not stripped.endswith("\x1b[0m"):
            result = stripped + "\x1b[0m" + result[len(stripped) :]
    return result


def _echo(message: str = "", *, err: bool = False, nl: bool = True) -> None:
    """``click.echo`` with ``_sanitize_control`` applied — the module default.

    Every echoed line leaves through here so rendering code is sanitized by
    construction (see ``_sanitize_control`` for the policy) even when a
    call site misses a per-field wrap; ``_echo_raw`` is the explicit
    opt-out. A test walks this module's AST to keep direct ``click.echo``
    calls out of everything but these two wrappers.
    """
    click.echo(_sanitize_control(message), err=err, nl=nl)


def _echo_raw(message: str = "", *, err: bool = False, nl: bool = True) -> None:
    """``click.echo`` without sanitization.

    For machine output — the ``--json`` paths, which are bytes-faithful by
    contract (``json.dumps`` escapes control bytes itself) — and for the
    keep-SGR renderings (``traceback_ansi``, the anomalies export), whose
    deliberately kept styling ``_echo`` would strip.
    """
    click.echo(message, err=err, nl=nl)


def _truncate(text: str, width: int) -> str:
    text = _sanitize_line(text)
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_human_table(summaries: list[dict[str, Any]]) -> None:
    """Render eval summaries as a simple aligned table on stdout."""
    # Show errors / attempts columns only when at least one row has
    # something interesting to report there — keeps the common case
    # (no errors, no retries) uncluttered. The solver column is identity
    # (like model) but hidden when no row carries it — an older server
    # doesn't report it, and an all-blank column is just clutter.
    any_errors = any((s.get("samples") or {}).get("errored", 0) > 0 for s in summaries)
    any_retries = any(int(s.get("attempts", 1) or 1) > 1 for s in summaries)
    any_solver = any(s.get("solver") for s in summaries)
    # Same "only when there is something to report" rule as errors/attempts. Zero
    # is the overwhelmingly common value for both, and a permanent pair of 0
    # columns would push the columns that always matter off a narrow terminal.
    # `or 0` also covers an older server, which reports neither key.
    any_refusals = any((s.get("refusals") or 0) > 0 for s in summaries)
    any_http_retries = any((s.get("http_retries") or 0) > 0 for s in summaries)
    any_tps = any((s.get("tokens_per_second") or 0) > 0 for s in summaries)
    # shown only when some task is paused (or holding samples — a hard model
    # pause can hold another task's grader calls without any latch source on
    # that row), so a paused run doesn't read as stalled (the cell names the
    # holding latch; `quiesced` = nothing left in flight — the safe-to-kill
    # signal)
    any_paused = any(s.get("paused") or s.get("held") for s in summaries)

    rows = []
    for s in summaries:
        samples = s.get("samples") or {}
        # task_id (not eval_id): stable across retries, and the handle
        # `inspect ctl sample list` takes.
        cells = [
            _short_id(s.get("task_id", "")),
            s.get("task", "?") or "?",
            s.get("model", "") or "",
        ]
        if any_solver:
            cells.append(s.get("solver", "") or "")
        cells.append(_format_samples(samples))
        if any_errors:
            cells.append(str(samples.get("errored", 0)))
        # Blank, not 0, when the key is absent — the same rule the samples table
        # uses for an unknown turn count. A row from an older server does not
        # report these, and printing 0 there would assert "none happened" about a
        # task that may well have had plenty. Only reachable in a mixed-version
        # fleet, which is exactly when a false zero would mislead.
        if any_refusals:
            cells.append(_format_count(s.get("refusals")))
        if any_http_retries:
            cells.append(_format_count(s.get("http_retries")))
        if any_tps:
            cells.append(_format_rate(s.get("tokens_per_second")))
        if any_paused:
            cells.append(_format_paused(s))
        cells.append(_format_started(s.get("started_at", 0)))
        if any_retries:
            cells.append(str(int(s.get("attempts", 1) or 1)))
        rows.append(tuple(cells))

    headers_list = ["task_id", "task", "model"]
    if any_solver:
        headers_list.append("solver")
    headers_list.append("samples")
    if any_errors:
        headers_list.append("errors")
    if any_refusals:
        headers_list.append("refusals")
    if any_http_retries:
        # Spelled out rather than "retries": the `attempts` column is also a
        # retry count (of whole task attempts), and these are HTTP-level.
        headers_list.append("http_retries")
    if any_tps:
        # Total (not output) tokens per second — the task summary tracks only
        # total tokens; the per-model out tok/s view is `ctl model throughput`.
        headers_list.append("tok/s")
    if any_paused:
        headers_list.append("paused")
    headers_list.append("started")
    if any_retries:
        headers_list.append("attempts")

    _render_table(tuple(headers_list), rows)


def _format_count(value: Any) -> str:
    """A count cell: the number, or blank when the server didn't report it.

    ``None`` (key absent) and ``0`` (reported, nothing happened) are different
    claims and must not render the same way.
    """
    return "" if value is None else str(value)


def _format_rate(value: Any) -> str:
    """A rate cell: one decimal, or blank when the server didn't report it."""
    return "" if value is None else f"{float(value):,.1f}"


def _format_paused(summary: dict[str, Any]) -> str:
    """The task's paused cell: the holding latch(es), plus quiesced when idle.

    Hard-holding latches (``pause --now``) render as ``task(now)``, and a
    nonzero held count (samples parked at their next model call) replaces
    the quiesced marker — the two can't co-occur (a held sample is still
    dispatched), and under a hard pause held, not quiesced, is the signal
    the operator acts on (a kill while ``held > 0`` forfeits in-sample
    progress). A row can be held with *no* latch sources of its own: the
    hard model gate keys on the model actually being called, so another
    task's ``model pause --now`` holds this task's grader/role calls to
    that model — render the held count alone rather than suppressing it.
    """
    held = int(summary.get("held") or 0)
    now = set(_paused_sources(summary.get("paused_now")))
    paused = "+".join(
        f"{source}(now)" if source in now else source
        for source in _paused_sources(summary.get("paused"))
    )
    if not paused:
        return f"({held} held)" if held else ""
    if held:
        return f"{paused} ({held} held)"
    return f"{paused} (quiesced)" if summary.get("quiesced") else paused


def _print_keep_alive_footer(summaries: list[dict[str, Any]]) -> None:
    """Print a one-line keep-alive status footer below the tasks table.

    Keep-alive is a per-process property — every task a process hosts shares
    it — so across all running tasks it's ``on`` (all park after their eval),
    ``off`` (none do), or ``mixed``. When it's off everywhere, hint at
    ``inspect ctl process keep``, which turns it on for a running process.
    """
    flags = [bool(s.get("keep_alive")) for s in summaries]
    _echo()
    if all(flags):
        _echo("keep-alive: on")
    elif not any(flags):
        _echo("keep-alive: off  ·  set with `inspect ctl process keep`")
    else:
        on = sum(flags)
        _echo(f"keep-alive: mixed ({on}/{len(flags)} on)")

    # flag paused work below the table (the per-row cell can scroll away and
    # a paused run must not read as stalled). A paused run never finishes —
    # either latch holds work the run awaits — so also surface the
    # exit-when-done contradiction when keep-alive is off for a paused row.
    paused = [s for s in summaries if s.get("paused")]
    # held (`--now`) samples counted across ALL rows, not just paused ones:
    # a hard model pause holds other tasks' grader calls to that model
    # without stamping a latch source on their rows
    held_samples = sum(int(s.get("held") or 0) for s in summaries)
    if paused:
        quiesced = sum(1 for s in paused if s.get("quiesced"))
        details = [
            part
            for part in (
                f"{quiesced} quiesced" if quiesced else "",
                f"{held_samples} held" if held_samples else "",
            )
            if part
        ]
        detail = f" ({', '.join(details)})" if details else ""
        # only the latches actually holding a paused task can resume it — a
        # task held solely by the model latch isn't freed by `task resume` or
        # `process resume`, so don't advertise them. Fixed order: task, model,
        # process.
        held = {src for s in paused for src in _paused_sources(s.get("paused"))}
        resumes = [
            f"`inspect ctl {latch} resume`"
            for latch in ("task", "model", "process")
            if latch in held
        ]
        _echo(
            f"paused: {len(paused)}/{len(summaries)} task"
            f"{'' if len(summaries) == 1 else 's'}{detail}  ·  resume with "
            f"{' / '.join(resumes)}"
        )
        if any(not s.get("keep_alive") for s in paused):
            _echo(
                "note: a paused run never finishes — it will not exit until "
                "resumed (or cancelled), despite keep-alive being off."
            )
    elif held_samples:
        # no paused rows, yet samples are parked at the generate gate (a
        # hard model pause whose primary tasks have no rows yet) — the
        # don't-kill-yet warning must still print
        _echo(
            f"held: {held_samples} sample{'' if held_samples == 1 else 's'} "
            "held at the next model call (`pause --now`) — killing now "
            "forfeits in-sample progress"
        )
    # latched models whose tasks are all still queued have no paused row
    # above (an unstarted task has no summary) — surface them from the
    # process-level stamp so the latch can't hold work invisibly
    paused_models = sorted(
        {m for s in summaries for m in (s.get("paused_models") or [])}
    )
    if paused_models:
        _echo(
            f"paused models: {', '.join(paused_models)}  ·  resume with "
            "`inspect ctl model resume`"
        )


def _print_errored_samples_footer(summaries: list[dict[str, Any]]) -> None:
    """Print a one-line errored-samples footer below the tasks table.

    Points at the triage command when any row reports errored samples.
    The count sums `samples.errored` across rows, which is deliberately
    narrower than the view it points at: `errored` counts latest-attempt
    errors only, while `sample errors` also lists retried samples — so the
    view may show more rows than the count here, never fewer, and the
    count must not be "fixed" to match the view's row count (see
    design/ctl/agent-discoverability.md §3b).
    """
    errored = sum((s.get("samples") or {}).get("errored", 0) for s in summaries)
    if errored > 0:
        noun = "sample" if errored == 1 else "samples"
        _echo(f"{errored} {noun} errored — see `inspect ctl sample errors`")


def _task_header(target: dict[str, Any]) -> str:
    """One-line summary of the task above its sample table.

    e.g. ``inspect_evals/gpqa_diamond (ZByxJpK4bKSz)  ·  openai/gpt-5-nano
    ·  running  ·  12/40 (3 running)``.
    """
    name = target.get("task") or "?"
    short = _short_id(str(target.get("task_id", "")))
    parts = [f"{name} ({short})" if short else name]
    if target.get("model"):
        parts.append(str(target["model"]))
    if target.get("status"):
        parts.append(str(target["status"]))
    parts.append(_format_samples(target.get("samples") or {}))
    attempts = int(target.get("attempts", 1) or 1)
    if attempts > 1:
        parts.append(f"{attempts} attempts")
    # sanitize each part before the join and flatten newlines so no field
    # can swallow the parts after it or forge a plausible header line; filter
    # on the sanitized value so a part that was all control bytes doesn't
    # leave a dangling separator
    sanitized_parts = (_sanitize_line(p) for p in parts)
    return "  ·  ".join(p for p in sanitized_parts if p)


def _print_samples_table(
    samples: list[dict[str, Any]], show_task: bool = False
) -> None:
    """Render per-sample summaries as a simple aligned table on stdout.

    ``show_task`` adds a leading task column — the rendering for a listing
    that spans tasks (the ``--json`` rows carry ``task_id`` regardless).
    Several columns are conditional, shown only when relevant (keeping the
    common case uncluttered):
    - ``retries`` — when some sample was retried on error. Per-sample
      (sample-level ``retry_on_error``); blank for samples with none.
    - ``score`` — when the samples have exactly one scorer (multi-scorer
      rendering is a later refinement). Running samples aren't scored yet,
      so their cell is blank.
    - ``idle`` — when some sample is running: time since its last transcript
      event (``now - last_activity_at``). A high idle time on a long-running
      sample is the cheap "is it stalled?" cue. Blank for non-running rows.
    - ``activity`` — when some running sample has an in-flight operation:
      what it is doing right now and for how long (``generating 7:12``,
      ``bash 0:41``, ``retrying in 0:45``), so a long model call reads as
      busy rather than stalled (see :func:`_format_activity`). Blank for
      rows with nothing pending.
    - ``limit usage`` / ``limit total`` — when some sample has a token limit
      configured. ``limit usage`` is the metered value for that limit
      (respecting its type — ``all``/``output``/formula) and ``limit total``
      the configured ceiling. Blank for rows without either.
    """
    any_retries = any((s.get("retries") or 0) > 0 for s in samples)
    scorers = sorted({name for s in samples for name in (s.get("scores") or {})})
    score_col = scorers[0] if len(scorers) == 1 else None
    any_running = any(s.get("status") == "running" for s in samples)
    any_activity = any(s.get("activity") for s in samples)
    any_token_limit = any(s.get("token_limit_total") is not None for s in samples)
    now = datetime.now(timezone.utc).timestamp()

    rows: list[tuple[str, ...]] = []
    for s in samples:
        row = [
            str(s["sample_id"]) if s.get("sample_id") is not None else "?",
            str(s.get("epoch", "")),
            s.get("status", "") or "",
        ]
        if show_task:
            row.insert(0, str(s.get("task") or _short_id(str(s.get("task_id") or ""))))
        if any_retries:
            row.append(str(s["retries"]) if s.get("retries") else "")
        if score_col is not None:
            row.append(_format_score((s.get("scores") or {}).get(score_col)))
        # blank (not 0) when the turn count is unknown: pending rows and
        # samples logged before turn counting existed carry None
        turn_count = s.get("turn_count")
        cells = [
            _format_duration(s.get("total_time")),
            str(s.get("total_tokens", 0)),
            str(s.get("message_count") or 0),
            str(turn_count) if turn_count is not None else "",
        ]
        if any_running:
            last = s.get("last_activity_at")
            idle = (
                _format_duration(now - last)
                if s.get("status") == "running" and last is not None
                else ""
            )
            cells.insert(1, idle)  # after time, before tokens
        if any_activity:
            # after idle (a running row always shows idle when it shows
            # activity — the server only sets activity on running rows)
            cells.insert(
                2 if any_running else 1, _format_activity(s.get("activity"), now)
            )
        if any_token_limit:
            usage = s.get("token_limit_usage")
            total = s.get("token_limit_total")
            cells.append(str(usage) if usage is not None else "")
            cells.append(str(total) if total is not None else "")
        row.extend(cells)
        rows.append(tuple(row))

    headers = ["sample", "epoch", "status"]
    if show_task:
        headers.insert(0, "task")
    if any_retries:
        headers.append("retries")
    if score_col is not None:
        headers.append("score")
    headers.append("time")
    if any_running:
        headers.append("idle")
    if any_activity:
        headers.append("activity")
    headers.extend(["tokens", "messages", "turns"])
    if any_token_limit:
        headers.extend(["limit usage", "limit total"])
    _render_table(tuple(headers), rows)


def _render_table(
    headers: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
    *,
    err: bool = False,
) -> None:
    """Print an aligned, dashed-underline table (to stderr when ``err``).

    Every cell is sanitized here (not only via `_truncate`) so no
    agent-controlled string reaches the terminal raw, the width math counts
    printable characters only, and an embedded newline can't forge rows.
    """
    headers = tuple(_sanitize_control(h) for h in headers)
    rows = [tuple(_sanitize_line(cell) for cell in row) for row in rows]
    widths = [
        max(len(h), max((len(r[i]) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]

    def _fmt_row(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    _echo(_fmt_row(headers), err=err)
    _echo(_fmt_row(tuple("-" * w for w in widths)), err=err)
    for row in rows:
        _echo(_fmt_row(row), err=err)


def _format_samples(samples: dict[str, Any]) -> str:
    """Compact one-cell representation of sample progress.

    Shape:
    - ``done/total (N running)`` when samples are in flight
    - ``done/total (complete)`` when total > 0 and nothing in flight + nothing queued
    - ``0/total (queued)`` when no samples started yet
    - ``done/total`` as the bland fallback

    ``done`` = ``completed + errored + cancelled`` (terminal counts).
    """
    total = int(samples.get("total", 0) or 0)
    completed = int(samples.get("completed", 0) or 0)
    errored = int(samples.get("errored", 0) or 0)
    cancelled = int(samples.get("cancelled", 0) or 0)
    in_flight = int(samples.get("in_flight", 0) or 0)
    queued = int(samples.get("queued", 0) or 0)

    done = completed + errored + cancelled
    if total == 0:
        # No total recorded — show in_flight as a single number so
        # the user sees something useful pre-EvalState registration.
        return f"{in_flight} running" if in_flight else "starting"

    if in_flight > 0:
        return f"{done}/{total} ({in_flight} running)"
    if done >= total:
        return f"{done}/{total} (complete)"
    if queued == total:
        return f"0/{total} (queued)"
    return f"{done}/{total}"


def _short_id(identifier: str) -> str:
    """Trim a long uuid for display — full id is in --json output."""
    if len(identifier) <= _SHORT_ID_LEN:
        return identifier
    return identifier[:_SHORT_ID_LEN]


def _format_started(started_at: float) -> str:
    if not started_at:
        return ""
    try:
        return datetime.fromtimestamp(float(started_at), tz=timezone.utc).strftime(
            "%H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return ""


def _format_duration(seconds: float | None) -> str:
    """Compact elapsed time: ``M:SS`` (under an hour) or ``H:MM:SS``."""
    if not seconds or seconds < 0:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_activity(activity: dict[str, Any] | None, now: float) -> str:
    """One-cell rendering of a running sample's in-flight operation.

    ``generating 7:12`` (with ``(N retries)`` for in-call provider retries
    and ``· 1.2k tok`` when streamed progress is reported), ``bash 0:41`` /
    ``2 tools 1:10`` for pending tool calls, ``retrying in 0:45`` for a
    generate retry backoff (time until the next attempt; bare ``retrying``
    once the deadline passes), and ``approval: bash 6:12`` / ``question
    2:03`` for a sample parked on a person. Elapsed is client-computed from
    ``started_at``, matching the idle column's convention. Empty for a
    null/absent activity; an unknown type from a newer server renders as
    its name rather than blank.
    """
    if not activity:
        return ""
    started = activity.get("started_at")
    elapsed = (
        _format_duration(now - started) if isinstance(started, (int, float)) else ""
    )
    activity_type = activity.get("type")
    if activity_type in ("approval", "question"):
        count = int(activity.get("count") or 1)
        if count > 1:
            cell = f"{count} {activity_type}s"
        elif activity_type == "approval" and activity.get("detail"):
            cell = f"approval: {activity.get('detail')}"
        else:
            cell = str(activity_type)
        return cell + (f" {elapsed}" if elapsed else "")
    if activity_type == "model":
        cell = "generating" + (f" {elapsed}" if elapsed else "")
        retries = activity.get("retries")
        if retries:
            suffix = "retry" if retries == 1 else "retries"
            cell += f" ({retries} {suffix})"
        tokens = activity.get("tokens")
        if tokens is not None:
            cell += f" · {_format_tokens(int(tokens))} tok"
        return cell
    if activity_type == "tool":
        count = int(activity.get("count") or 1)
        label = f"{count} tools" if count > 1 else str(activity.get("detail") or "tool")
        return label + (f" {elapsed}" if elapsed else "")
    if activity_type == "retry_wait":
        deadline = activity.get("deadline")
        remaining = (
            _format_duration(deadline - now)
            if isinstance(deadline, (int, float))
            else ""
        )
        cell = "retrying" + (f" in {remaining}" if remaining else "")
        # `count` is the attempt that just failed, so say "after attempt N" —
        # a bare "attempt N" reads as the upcoming attempt (which is N + 1).
        attempt = int(activity.get("count") or 0)
        if attempt > 1:
            cell += f" (after attempt {attempt})"
        return cell
    return str(activity_type or "")


def _format_tokens(tokens: int) -> str:
    """Compact token count: ``850``, ``1.2k``, ``3.4M``."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def _format_score(value: Any) -> str:
    """Compact score-value cell (floats trimmed; other values stringified)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
