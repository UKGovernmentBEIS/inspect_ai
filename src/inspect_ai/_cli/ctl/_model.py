"""``inspect ctl model`` commands and their runner."""

from __future__ import annotations

import json as json_lib
from typing import Any, Literal

import click

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _http
from ._failure import _envelope_failures
from ._group import (
    _MUTATION_ENVELOPE_HELP,
    _json_option,
    _NounGroup,
    _now_option,
    ctl_command,
)
from ._http import _resolve_target_server
from ._mutate import _HELD_CAVEAT, _mutation_envelope, _pause_confirmation
from ._render import _echo, _echo_raw, _format_rate, _render_table, _sanitize_line


@ctl_command.group("model", cls=_NounGroup)
def model_group() -> None:
    """Operate on the models of running evals.

    MODEL is the exact model name as `inspect ctl task list` shows it
    (e.g. openai/gpt-5-nano). One latch per model: pausing holds every
    task whose primary model matches — including eval-set tasks that
    haven't started yet — while other models' work continues.
    """


assert isinstance(model_group, _NounGroup)
model_group.hint = lambda token: (
    f"No such command '{token}'. To pause or resume one model's dispatch: "
    f"`inspect ctl model pause {token}` / `inspect ctl model resume {token}`."
)


@model_group.command("pause")
@click.argument("model")
@click.argument("pid", required=False, type=int)
@_now_option(
    holds=(
        "generate calls to MODEL at their next attempt — including other "
        "tasks' role/grader calls to it"
    )
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be paused without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def model_pause_command(
    model: str, pid: int | None, now: bool, dry_run: bool, as_json: bool
) -> None:
    """Pause one model's dispatch (stop starting its tasks' work; in-flight finishes).

    Holds every task whose *primary* model is MODEL: no new samples or
    retry attempts start, and the eval-set scheduler does not start its
    not-yet-started tasks — which `inspect ctl task pause` cannot reach.
    Everything else keeps running, and in-flight samples (including other
    tasks' role/grader calls to this model) finish naturally. With `--now`
    (the hard pause), generate calls to MODEL — role/grader calls included
    — hold at their next attempt instead: the model's spend stops as soon
    as outstanding calls complete, while the wall clock keeps running for
    held samples. MODEL is the exact name shown by `inspect ctl task list`;
    an unknown name is an error. PID is required when several processes
    run. Idempotent; resume with `inspect ctl model resume`.
    """
    _run_model_pause_resume(
        model, pid, verb="pause", now=now, dry_run=dry_run, as_json=as_json
    )


@model_group.command("resume")
@click.argument("model")
@click.argument("pid", required=False, type=int)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be resumed without doing it.",
)
@_json_option(_MUTATION_ENVELOPE_HELP)
def model_resume_command(
    model: str, pid: int | None, dry_run: bool, as_json: bool
) -> None:
    """Resume a paused model (the inverse of `inspect ctl model pause`).

    The model's held tasks dispatch again exactly as they would have before
    the pause. Task-level and process-level pauses are deliberately left in
    place (independent latches). Idempotent and last-write-wins. PID is
    required when several processes run.
    """
    _run_model_pause_resume(model, pid, verb="resume", dry_run=dry_run, as_json=as_json)


@model_group.command("throughput")
@click.argument("pid", required=False, type=int)
@click.option(
    "--window",
    type=click.IntRange(min=1),
    metavar="SECONDS",
    default=60,
    help=(
        "Rate window in seconds (default 60; clamped server-side to the "
        "10-minute horizon). Cumulative totals are unaffected."
    ),
)
@_json_option(
    "an `{as_of, window_seconds, models}` envelope with per-model rates "
    "and cumulative totals"
)
def model_throughput_command(pid: int | None, window: int, as_json: bool) -> None:
    """Show each model's effective throughput across the run.

    One row per model the process has called, aggregated across every
    sample and task: recent output tokens/sec, requests/min and
    retries/min over `--window`, how many samples currently have a
    generate sleeping in a retry wait, and cumulative scheduled backoff.
    The "wait vs. switch" view for a throttled run — rates come from
    completed generates, so a model whose every call is stuck in backoff
    reads 0. PID is required when several processes run.
    """
    _run_model_throughput(pid, window=window, as_json=as_json)


_MODEL_THROUGHPUT_ROUTE_MISSING = (
    "This process is running an older inspect without the model throughput "
    "endpoint; restart the eval to pick up the current version."
)


@_envelope_failures
def _run_model_throughput(pid: int | None, *, window: int, as_json: bool) -> None:
    """Read per-model run throughput (``GET /models/throughput``)."""
    target = _resolve_target_server(pid)
    result = _http._request_json(
        str(target.socket_path),
        "/models/throughput",
        params={"window": window},
        what=f"model throughput (pid {target.pid})",
        not_found=(
            f"Model throughput not available from pid {target.pid} "
            "(older inspect version?)."
        ),
        not_found_missing_route=_MODEL_THROUGHPUT_ROUTE_MISSING,
        pid=target.pid,
    )

    if as_json:
        _echo_raw(json_lib.dumps(result, indent=2))
        return

    models = result.get("models") or []
    if not models:
        _echo(
            f"No model traffic recorded in this run (pid {target.pid}). "
            "Rates appear once a generate completes or a retry occurs."
        )
        return
    _print_throughput_table(models)


def _format_backoff(seconds: Any) -> str:
    """Cumulative backoff cell: compact duration, or a dash when none."""
    total = int(seconds or 0)
    if total <= 0:
        return "-"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _print_throughput_table(models: list[dict[str, Any]]) -> None:
    """Render the per-model throughput rows as an aligned table."""
    rows = [
        (
            str(m.get("model", "?") or "?"),
            _format_rate(m.get("output_tokens_per_second")),
            _format_rate(m.get("requests_per_minute")),
            _format_rate(m.get("retries_per_minute")),
            str(m.get("retry_waits_active", 0) or 0),
            _format_backoff((m.get("cumulative") or {}).get("retry_wait_seconds")),
        )
        for m in models
    ]
    _render_table(
        (
            "model",
            "out tok/s",
            "req/min",
            "retries/min",
            "in backoff",
            "backoff (cum)",
        ),
        rows,
    )


_MODEL_PAUSE_ROUTE_MISSING = (
    "This process is running an older inspect without the model pause/resume "
    "endpoints; restart the eval to pick up the current version."
)


@_envelope_failures
def _run_model_pause_resume(
    model: str,
    pid: int | None,
    *,
    verb: Literal["pause", "resume"],
    now: bool = False,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Pause or resume one model's dispatch (``POST /models/pause|resume``).

    The process selector matches keep/release (sole-process default, PID to
    disambiguate); MODEL is an exact model name, validated *server-side*
    against the models the process could dispatch — a client-side resolve
    against the task summaries would wrongly reject a model whose tasks are
    all still queued (not-yet-started eval-set tasks have no summary row),
    which is precisely the model latch's reason to exist. ``now`` (the hard
    pause) needs no version gate: an older server rejects the unknown param
    with a 400 (strict mutations), so it fails loudly rather than silently
    soft-pausing.
    """
    target = _resolve_target_server(pid)
    params: dict[str, Any] = {"model": model}
    if now:
        params["now"] = True
    if dry_run:
        params["dry_run"] = True
    result = _http._request_json(
        str(target.socket_path),
        f"/models/{verb}",
        params=params,
        what=f"{verb} of model {model} (pid {target.pid})",
        not_found=(
            f"Model '{model}' not found in pid {target.pid} (pass the exact "
            "model name as shown by `inspect ctl task list`)."
        ),
        not_found_missing_route=_MODEL_PAUSE_ROUTE_MISSING,
        mutate="post",
        retry_mutation=True,
    )

    if as_json:
        _echo_raw(
            json_lib.dumps(
                _mutation_envelope(
                    {"model": model, "pid": target.pid}, result, dry_run=dry_run
                ),
                indent=2,
            )
        )
        return

    if result.get("changed"):
        if verb == "pause":
            # `tasks`/`dispatched` count only registered tasks — the latch
            # additionally holds this model's not-yet-started eval-set
            # tasks, which have no row to count
            tasks = int(result.get("tasks", 0) or 0)
            dispatched = int(result.get("dispatched", 0) or 0)
            counts = (
                f"{tasks} running task{'' if tasks == 1 else 's'}, "
                f"{dispatched} dispatched sample{'' if dispatched == 1 else 's'}"
            )
            if now:
                body = (
                    f"{counts}; generate calls to it (role/grader calls "
                    f"included) {{will}} hold at their next attempt "
                    f"({_HELD_CAVEAT})"
                )
            else:
                body = f"{counts} {{will}} finish naturally"
            _echo(
                _pause_confirmation(
                    now=now,
                    dry_run=dry_run,
                    target=model,
                    body=body,
                    no_new="samples, retry attempts, or eval-set tasks of this model",
                    hint_hard=(
                        " (other models keep running)."
                        " Watch `inspect ctl task list` for held counts;"
                        " resume with `inspect ctl model resume`."
                    ),
                    hint_soft=(
                        " (other models keep running)."
                        " Resume with `inspect ctl model resume`."
                    ),
                )
            )
        elif dry_run:
            _echo(f"Would resume {model} — its held work would dispatch again.")
        else:
            _echo(
                f"Resume requested for {model} — its held work dispatches "
                "again (task- and process-level pauses, if any, stay in place)."
            )
    else:
        reason = _sanitize_line(str(result.get("reason") or "already in that state"))
        _echo(f"Nothing to do: {reason} ({model}).")
