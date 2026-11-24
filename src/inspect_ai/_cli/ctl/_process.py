"""``inspect ctl process`` commands and their runners."""

from __future__ import annotations

import json as json_lib
import time
from pathlib import Path
from typing import Any, Literal, NamedTuple

import click
from rich.markup import escape as escape_markup

from inspect_ai._cli.trace import (
    TraceAnomalies,
    anomalies_options,
    anomaly_buckets_json,
    filter_traces,
    rendered_anomalies,
    trace_anomalies,
)
from inspect_ai._control.discovery import DiscoveredControlServer
from inspect_ai._util.process import pid_alive
from inspect_ai._util.trace import ActionTraceRecord, inspect_trace_dir, read_trace_file

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _fetch, _http
from ._failure import _CtlFailure, _envelope_failures, _exception_name, _fail
from ._group import (
    _MUTATION_ENVELOPE_HELP,
    _forward_group_options,
    _json_option,
    _mirror_list_options,
    _NounGroup,
    _now_option,
    ctl_command,
)
from ._http import _resolve_target_server
from ._mutate import (
    _HELD_CAVEAT,
    _PAUSE_ROUTE_MISSING,
    _mutation_envelope,
    _pause_confirmation,
)
from ._render import (
    _echo,
    _echo_raw,
    _format_started,
    _render_table,
    _sanitize_keep_sgr,
    _sanitize_line,
)


@ctl_command.group(
    "process",
    cls=_NounGroup,
    invoke_without_command=True,
)
@click.pass_context
def process_group(ctx: click.Context, /, **mirrored: Any) -> None:
    """Operate on running Inspect processes (bare `process` lists them).

    The selector is a positional PID: optional for `keep` / `release` when
    a single process is running, and for `anomalies`, where no PID reads
    every running process.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(process_list_command, **mirrored)
    else:
        _forward_group_options(ctx)


assert isinstance(process_group, _NounGroup)
process_group.hint = lambda token: (
    f"No such command '{token}'. To list running processes: "
    "`inspect ctl process list` (or the bare `inspect ctl process`); to park "
    f"or release one: `inspect ctl process keep {token}` / "
    f"`inspect ctl process release {token}`; for one's in-flight actions: "
    f"`inspect ctl process anomalies {token}`."
)


@process_group.command("list")
@_json_option("an `{as_of, processes}` envelope")
def process_list_command(as_json: bool) -> None:
    """List running Inspect processes (pids, keep-alive, hosted tasks).

    The PID shown is the selector `process keep` / `process release` take.
    """
    _run_process_list(as_json)


_mirror_list_options(process_group, process_list_command)


@process_group.command("keep")
@click.argument("pid", required=False, type=int)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_keep_command(pid: int | None, as_json: bool) -> None:
    """Keep a running inspect process alive after its eval finishes.

    The process parks after the eval — state and results stay readable
    here — until `inspect ctl process release` or Ctrl+C. The runtime
    equivalent of launching with `--ctl-server=keep`; `keep` and `release`
    are last-write-wins while the eval is still running.
    """
    _run_keep_alive(pid, keep=True, as_json=as_json)


@process_group.command("release")
@click.argument("pid", required=False, type=int)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_release_command(pid: int | None, as_json: bool) -> None:
    """Release a lingering --ctl-server=keep process so it can exit.

    Issued while the eval is still running it means "exit when done",
    unless a later `keep` overrides it (last-write-wins). Does NOT cancel
    the eval or affect in-flight samples.
    """
    _run_keep_alive(pid, keep=False, as_json=as_json)


@process_group.command("pause")
@click.argument("pid", required=False, type=int)
@_now_option()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be paused without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_pause_command(
    pid: int | None, now: bool, dry_run: bool, as_json: bool
) -> None:
    """Pause a whole running eval or eval-set (stop dispatching new work; in-flight finishes).

    One process-scoped latch: no new eval-set tasks dispatch, no task
    retries start, and no samples dispatch in any task; in-flight samples
    finish naturally. With `--now` (the hard pause), in-flight samples
    additionally hold at their next model call — model spend stops as soon
    as outstanding calls complete, at the price of the wall clock running
    for held samples (a sample held past its time_limit resolves as an
    ordinary time-limit outcome). The process, its queue, and this control
    surface stay alive — watch `inspect ctl task list` for `quiesced`
    (paused with nothing in flight), after which completed work is flushed
    and the process can be killed cleanly if needed (under `--now`, a
    nonzero `held` count means samples are mid-flight: killing then
    forfeits their in-sample progress). Resume with `inspect ctl process
    resume`. Idempotent and non-destructive.
    """
    _run_process_pause_resume(
        pid, verb="pause", now=now, dry_run=dry_run, as_json=as_json
    )


@process_group.command("resume")
@click.argument("pid", required=False, type=int)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def process_resume_command(pid: int | None, dry_run: bool, as_json: bool) -> None:
    """Resume a paused eval or eval-set (the inverse of `process pause`).

    Dispatch picks up exactly where it left off. Task-level pauses (from
    `inspect ctl task pause`) are deliberately left in place. Note the
    distinction with `process release`: resume re-opens a *paused* run;
    release ends a keep-alive *park* after the eval finishes.
    """
    _run_process_pause_resume(pid, verb="resume", dry_run=dry_run, as_json=as_json)


@process_group.command("anomalies")
@click.argument("pid", required=False, type=int)
@anomalies_options(
    "an `{as_of, processes}` envelope; each process entry carries `pid`, "
    "`trace_file`, its own `as_of` (the timestamp running durations are "
    "computed against), and the `running`/`cancelled`/`errors`/`timeouts` "
    "buckets"
)
def process_anomalies_command(
    pid: int | None, filter: str | None, all: bool, as_json: bool
) -> None:
    """Show in-flight and anomalous actions from a process's trace log.

    Reconstructs from the pid's trace file what is running right now
    (entered, never exited — with live durations) plus what was cancelled;
    `--all` adds errored and timed-out actions. This is the "why" behind a
    stalled sample: a single in-flight operation (model call, sandbox exec)
    emits no transcript event until it returns, but its trace action is
    visible here.

    The trace file is read directly (nothing is asked of the process), so
    this works against a busy or hung process — the escalation path when
    another read reports "busy" — and even post-mortem: a PID with no live
    process falls back to its trace file (`trace-<pid>.log`, or `.log.gz`
    after a clean exit) while one still exists, with running durations dated
    to the file's last write (approximately the time of death) rather than
    now. No PID reads every running process, one section per pid. The
    analysis is shared with `inspect trace anomalies`, which reads any trace
    file by path.
    """
    _run_process_anomalies(pid, filter=filter, all=all, as_json=as_json)


@_envelope_failures
def _run_keep_alive(pid: int | None, *, keep: bool, as_json: bool) -> None:
    """Latch keep-alive on (``keep``) or off (``release``) for one process."""
    verb = "keep" if keep else "release"
    target = _resolve_target_server(pid)
    body = _http._request_json(
        str(target.socket_path),
        f"/{verb}",
        what=f"keep-alive for pid {target.pid}",
        not_found=(
            f"Pid {target.pid} does not support keep/release (older inspect version?)."
        ),
        mutate="post",
        retry_mutation=True,
        pid=target.pid,
    )

    # `changed` distinguishes applied from the idempotent already-in-that-state
    # no-op; an older server omits it (detail then just carries what it sent).
    detail = {k: v for k, v in body.items() if k != "ok"} if body else {}
    if as_json:
        result = {
            "target": {"pid": target.pid},
            "applied": True,
            "dry_run": False,
            "detail": detail,
        }
        _echo_raw(json_lib.dumps(result, indent=2))
        return

    already = detail.get("changed") is False
    if keep:
        _echo(
            f"Keep-alive already on for pid {target.pid}."
            if already
            else f"Keep-alive requested for pid {target.pid}."
        )
    else:
        _echo(
            f"Keep-alive already off for pid {target.pid}."
            if already
            else f"Release requested for pid {target.pid}."
        )


@_envelope_failures
def _run_process_pause_resume(
    pid: int | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Pause or resume a whole process (``POST /pause`` / ``POST /resume``).

    ``now`` (the hard pause) needs no version gate: an older server rejects
    the unknown param with a 400 (strict mutations), so it fails loudly
    rather than silently soft-pausing.
    """
    target = _resolve_target_server(pid)
    params: dict[str, Any] = {}
    if now:
        params["now"] = True
    if dry_run:
        params["dry_run"] = True
    result = _http._request_json(
        str(target.socket_path),
        f"/{verb}",
        params=params,
        what=f"{verb} for pid {target.pid}",
        not_found=_PAUSE_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
        pid=target.pid,
    )

    if as_json:
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope({"pid": target.pid}, result, dry_run=dry_run),
                indent=2,
            )
        )
        return

    if result.get("changed"):
        if verb == "pause":
            body = (
                f"in-flight samples {{will}} hold at their next model call "
                f"({_HELD_CAVEAT})"
                if now
                else "in-flight samples {will} finish"
            )
            _echo(
                _pause_confirmation(
                    now=now,
                    dry_run=dry_run,
                    target=f"pid {target.pid}",
                    body=body,
                    no_new="samples, task retries, or eval-set tasks",
                    hint_hard=(
                        ". Watch `inspect ctl task list` for the held count; "
                        "resume with `inspect ctl process resume`."
                    ),
                    hint_soft=(
                        ". Watch `inspect ctl task list` for quiesced; "
                        "resume with `inspect ctl process resume`."
                    ),
                )
            )
        elif dry_run:
            _echo(f"Would resume pid {target.pid}.")
        else:
            _echo(
                f"Resume requested for pid {target.pid} — dispatch picks up "
                "where it left off (task-level pauses, if any, stay in place)."
            )
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        _echo(f"Nothing to do: {reason} (pid {target.pid}).")


@_envelope_failures
def _run_process_list(as_json: bool) -> None:
    as_of = time.time()
    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries if servers else []

    rows: list[dict[str, Any]] = []
    for server in servers:
        hosted = [s for s in summaries if s.get("pid") == server.pid]
        # keep-alive is a process-level property every hosted task shares;
        # unknown (None) when no task has registered yet. The process pause
        # latch is likewise process-level (also None against an older server
        # that doesn't report it).
        keep_alive = bool(hosted[0].get("keep_alive")) if hosted else None
        paused = (
            bool(hosted[0].get("process_paused"))
            if hosted and hosted[0].get("process_paused") is not None
            else None
        )
        # the hard (`pause --now`) strength of the process latch; False
        # against an older server that doesn't report it (soft is the only
        # strength such a server can hold)
        paused_now = bool(hosted[0].get("process_paused_now")) if hosted else False
        rows.append(
            {
                "pid": server.pid,
                "socket_path": str(server.socket_path),
                "started_at": server.started_at,
                "keep_alive": keep_alive,
                "paused": paused,
                "paused_now": paused_now,
                "tasks": [
                    {
                        "task_id": t.get("task_id"),
                        "task": t.get("task"),
                        "status": t.get("status"),
                    }
                    for t in hosted
                ],
            }
        )

    if as_json:
        _echo_raw(json_lib.dumps({"as_of": as_of, "processes": rows}, indent=2))
        return

    if not rows:
        _echo("No running inspect processes found.")
        return

    table_rows: list[tuple[str, ...]] = []
    for row in rows:
        keep = row["keep_alive"]
        paused = row["paused"]
        tasks = row["tasks"]
        table_rows.append(
            (
                str(row["pid"]),
                "?" if keep is None else ("on" if keep else "off"),
                _format_process_paused(paused, row["paused_now"]),
                ", ".join(str(t.get("task") or "?") for t in tasks) or "(starting)",
                _format_started(row["started_at"]),
            )
        )
    _render_table(("pid", "keep-alive", "paused", "tasks", "started"), table_rows)


def _format_process_paused(paused: bool | None, paused_now: bool) -> str:
    """The process latch cell: unknown / no / yes, with the hard strength marked."""
    if paused is None:
        return "?"
    if not paused:
        return "no"
    return "yes (now)" if paused_now else "yes"


class _PidAnomalies(NamedTuple):
    """One `process anomalies` section: a pid, its trace file, and the reconstruction.

    ``as_of`` is the timestamp the section's running durations are computed
    against: for a live pid, stamped just after its file is read (stamping
    before could date an ``enter`` record that lands mid-read to the future,
    i.e. a negative duration); for a dead pid's post-mortem read, the trace
    file's last write (a proxy for time of death).
    """

    pid: int
    trace_file: Path
    anomalies: TraceAnomalies
    as_of: float


def _trace_file_for_pid(pid: int) -> Path | None:
    """The pid's trace file: ``trace-<pid>.log``, or ``.log.gz`` after a clean exit.

    ``None`` when neither exists (swept by the keep-newest-10 rotation).
    Live and dead pids resolve the same way — the mapping is pure filename
    convention, which is what makes the post-mortem read possible.
    """
    for name in (f"trace-{pid}.log", f"trace-{pid}.log.gz"):
        path = inspect_trace_dir() / name
        if path.exists():
            return path
    return None


def _sanitized_anomalies(anomalies: TraceAnomalies) -> TraceAnomalies:
    """A copy of ``anomalies`` with its rendered text fields neutralized.

    The anomalies detail column embeds agent-controlled text verbatim — a
    stalled sandboxed ``bash`` call's shlex-joined command line preserves the
    agent's script bytes — and :func:`rendered_anomalies` (shared with
    `inspect trace anomalies`) renders through rich, which keeps escape bytes
    in ``export_text(styles=True)`` and parses cell strings as console markup
    (so e.g. ``[link=...]`` in agent text would export an OSC 8 hyperlink).
    Fields are therefore sanitized per record before they enter the table —
    not post-export, where one row's unterminated OSC would swallow the rows
    after it — with newlines flattened like the other table cells and markup
    escaped to render literally. The ``--json`` envelope keeps the raw bytes.
    """

    def clean(text: str) -> str:
        return escape_markup(_sanitize_line(text))

    def clean_record(record: ActionTraceRecord) -> ActionTraceRecord:
        return record.model_copy(
            update=dict(
                action=clean(record.action),
                message=clean(record.message),
                detail=clean(record.detail),
                error=None if record.error is None else clean(record.error),
            )
        )

    return TraceAnomalies(
        running=[clean_record(r) for r in anomalies.running],
        cancelled=[clean_record(r) for r in anomalies.cancelled],
        errors=[clean_record(r) for r in anomalies.errors],
        timeouts=[clean_record(r) for r in anomalies.timeouts],
    )


@_envelope_failures
def _run_process_anomalies(
    pid: int | None, *, filter: str | None, all: bool, as_json: bool
) -> None:
    """Anomalies from trace files: one section per targeted pid.

    Deliberately a client-side file read with no HTTP endpoint — the prime
    anomalies scenario is a wedged process, precisely when the control
    server (which shares the eval's loop) can't answer (see "Trace-log
    anomalies for stall diagnosis" in design/ctl/control-channel.md).
    """
    # Stamp the envelope as_of before the reads (same cursor rationale as the
    # other read envelopes: anything that changes during them has a timestamp
    # >= as_of and is caught by the next poll). Sections date their running
    # durations to their own as_of instead (see _PidAnomalies), where
    # stamp-after-read is the consistent choice — matching `inspect trace
    # anomalies`, which cannot produce negative durations.
    as_of = time.time()

    servers: list[DiscoveredControlServer] = []
    if pid is not None:
        # An explicit PID needs no discovery: the trace file is pid-keyed on
        # disk, so a dead process resolves exactly like a live one (the
        # post-mortem read).
        trace_file = _trace_file_for_pid(pid)
        if trace_file is None:
            looked_for = inspect_trace_dir() / f"trace-{pid}.log"
            _fail(
                "not_found",
                f"No trace file found for pid {pid} (looked for "
                f"{looked_for}[.gz]; rotation keeps only the newest 10 trace "
                "files). If you have a copy elsewhere, read it with "
                "`inspect trace anomalies <file>`.",
            )
        if pid_alive(pid):
            post_mortem_as_of: float | None = None
        else:
            # Post-mortem read: date running durations to the trace file's
            # last write — a proxy for the time of death — so an action in
            # flight when the process died doesn't accrue wall-clock time
            # since (an overnight death would otherwise show it "running"
            # for hours).
            post_mortem_as_of = trace_file.stat().st_mtime
            _echo(
                f"note: pid {pid} is not running — durations are as of the "
                "trace file's last write.",
                err=True,
            )
        targets = [(pid, trace_file, post_mortem_as_of)]
    else:
        servers = _http.list_discovered_servers()
        targets = []
        for server in servers:
            server_trace = _trace_file_for_pid(server.pid)
            if server_trace is None:
                # same warn-and-skip as the unscoped fan-out reads: this
                # pid's section can't be read, the others' still can
                _echo(
                    f"note: no trace file found for pid {server.pid} — skipped.",
                    err=True,
                )
                continue
            # discovery only lists live pids, so durations date to the read
            targets.append((server.pid, server_trace, None))

    sections: list[_PidAnomalies] = []
    for target_pid, target_file, target_post_mortem_as_of in targets:
        try:
            records = read_trace_file(target_file)
        except Exception as ex:
            # catch Exception, not (OSError, ValueError): "unreadable file"
            # has no closed exception vocabulary — e.g. mid-stream gz
            # corruption raises zlib.error, which is neither
            if pid is not None:
                # explicit-pid reads fail loudly (the caller asked for
                # exactly this pid), with the same clean stderr-plus-envelope
                # contract as every other terminal ctl error
                message = (
                    f"Could not read trace file {target_file} for pid "
                    f"{target_pid}: {ex}"
                )
                _echo(message, err=True)
                raise _CtlFailure(
                    "internal", message, exception=_exception_name(ex)
                ) from ex
            # the widened fan-out warns-and-skips like the missing-trace-file
            # case, keeping the other sections readable
            _echo(
                f"note: could not read {target_file} for pid {target_pid} "
                f"({ex}) — skipped.",
                err=True,
            )
            continue
        anomalies = trace_anomalies(filter_traces(records, filter))
        sections.append(
            _PidAnomalies(
                pid=target_pid,
                trace_file=target_file,
                anomalies=anomalies,
                as_of=(
                    time.time()
                    if target_post_mortem_as_of is None
                    else target_post_mortem_as_of
                ),
            )
        )

    if as_json:
        envelope = {
            "as_of": as_of,
            "processes": [
                {
                    "pid": section.pid,
                    "trace_file": section.trace_file.as_posix(),
                    "as_of": section.as_of,
                    **anomaly_buckets_json(section.anomalies, section.as_of),
                }
                for section in sections
            ],
        }
        _echo_raw(json_lib.dumps(envelope, indent=2))
        return

    if not sections:
        if servers:
            _echo(
                "No readable trace files found for the running processes "
                "(see notes above)."
            )
        else:
            _echo(
                "No running inspect processes found. Pass a PID to read an "
                "exited process's trace file post-mortem (`inspect trace "
                "list` shows the trace files still on disk)."
            )
        return

    # _sanitize_keep_sgr as a backstop over the already-sanitized rendering:
    # rich's own styling exports as SGR (kept), so anything else that ever
    # leaks into the export is neutralized without trusting its internals.
    _echo_raw(
        "\n\n".join(
            _sanitize_keep_sgr(
                rendered_anomalies(
                    section.trace_file,
                    _sanitized_anomalies(section.anomalies),
                    all,
                    pid=section.pid,
                    as_of=section.as_of,
                )
            )
            for section in sections
        )
    )
