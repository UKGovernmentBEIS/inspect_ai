"""``inspect ctl config``: compose, gate, and apply config knob changes."""

from __future__ import annotations

import json as json_lib
from typing import Any, Literal, NamedTuple, cast

import click

from inspect_ai._control.discovery import DiscoveredControlServer
from inspect_ai._control.views import ProcessConfigView, TaskConfigView

# Patch seam: tests monkeypatch functions on their defining module
# (e.g. `inspect_ai._cli.ctl._http._request_json`), so cross-module
# calls must resolve through the module object at call time — do not
# "simplify" to `from ._http import _request_json` (see
# design/ctl/cli-refactor.md).
from . import _fetch, _http
from ._failure import _CtlFailure, _envelope_failures, _fail
from ._group import (
    _INT_MIN_ONE_OR_CLEAR,
    _INT_OR_CLEAR,
    _echo_no_running_evals,
    _json_option,
    _terse_line,
    _terse_option,
    _use_terse,
    ctl_command,
)
from ._knobs import _KNOB_SCOPE, _PROVENANCE_SINCE, _STRICT_SINCE
from ._mutate import _DirectiveScope, _resolve_scope
from ._render import _echo, _echo_raw, _print_config


@ctl_command.command("config")
@click.argument("task", required=False)
@click.option(
    "--max-samples",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_samples']}] Max samples to run concurrently (under "
        "adaptive connections, sample concurrency tracks the controller instead)."
    ),
)
@click.option(
    "--max-tasks",
    type=_INT_MIN_ONE_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_tasks']}] Override the max concurrently running "
        "tasks ('clear' restores launch config). Raising it starts pending "
        "tasks immediately; more tasks can mean more concurrent sandbox "
        "startups (see --max-sandboxes)."
    ),
)
@click.option(
    "--max-sandboxes",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['max_sandboxes']}] Max sandboxes per provider.",
)
@click.option(
    "--max-subprocesses",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['max_subprocesses']}] Max concurrent subprocesses.",
)
@click.option(
    "--max-connections",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_connections']}] Adaptive-connections scaling "
        "ceiling — the controllers' max."
    ),
)
@click.option(
    "--model",
    default=None,
    help=(
        "Restrict --max-connections (and the adaptive view) to models matching "
        "this — at the name start or after a '/' (e.g. 'gpt-4' matches "
        "'openai/gpt-4')."
    ),
)
@click.option(
    "--key",
    "key",
    type=(str, click.IntRange(min=1)),
    default=None,
    metavar="NAME LIMIT",
    help=(
        f"[{_KNOB_SCOPE['key']}] Set the named `concurrency()` limit NAME to "
        "LIMIT — any limit tools or task code register by name (the output's "
        "`concurrency keys` section lists them, exactly as addressable here). "
        "An unknown NAME errors, listing the available keys."
    ),
)
@click.option(
    "--log-buffer",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['log_buffer']}] Completed samples buffered before a "
        "log write — the retune side of `inspect ctl task log-flush` (lower "
        "it to write to S3 more often)."
    ),
)
@click.option(
    "--log-shared",
    type=click.IntRange(min=1),
    metavar="INTEGER",
    default=None,
    help=f"[{_KNOB_SCOPE['log_shared']}] Shared-log event sync interval, in seconds.",
)
@click.option(
    "--time-limit",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['time_limit']}] Override the per-sample wall-clock "
        "time limit, in seconds — reaches in-flight samples too ('clear' "
        "restores launch config)."
    ),
)
@click.option(
    "--token-limit",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['token_limit']}] Override the per-sample token limit "
        "— applies at each sample's next token check, in-flight samples "
        "included ('clear' restores launch config)."
    ),
)
@click.option(
    "--message-limit",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['message_limit']}] Override the per-sample message "
        "limit — applies at each sample's next message check, in-flight "
        "samples included ('clear' restores launch config)."
    ),
)
@click.option(
    "--timeout",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['timeout']}] Override the total retry budget per "
        "generate call, in seconds ('clear' restores launch config)."
    ),
)
@click.option(
    "--attempt-timeout",
    type=_INT_OR_CLEAR,
    metavar="SECONDS",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['attempt_timeout']}] Override the per-attempt API "
        "timeout, in seconds ('clear' restores launch config)."
    ),
)
@click.option(
    "--max-retries",
    type=_INT_OR_CLEAR,
    metavar="INTEGER",
    default=None,
    help=(
        f"[{_KNOB_SCOPE['max_retries']}] Override the max retries per "
        "generate call (0 fails after the first attempt; 'clear' restores "
        "launch config)."
    ),
)
@click.option(
    "--reason",
    default=None,
    help=(
        "Why this change is being made (with a set option) — recorded with "
        "the change in each affected eval log."
    ),
)
@click.option(
    "--author",
    default=None,
    help=(
        "Author recorded with the change in each affected eval log (with a "
        "set option). Defaults to your git identity, then your OS username."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would change without applying it (with a set option).",
)
@_json_option(
    "a `{target, knobs, warnings, notes, applied, dry_run, persisted, "
    "requested}` view, every knob labeled with its scope"
)
@_terse_option(note="Applies when setting a knob; a pure view always renders in full.")
def config_command(
    task: str | None,
    max_samples: int | None,
    max_tasks: int | Literal["clear"] | None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None,
    log_buffer: int | None,
    log_shared: int | None,
    time_limit: int | Literal["clear"] | None,
    token_limit: int | Literal["clear"] | None,
    message_limit: int | Literal["clear"] | None,
    timeout: int | Literal["clear"] | None,
    attempt_timeout: int | Literal["clear"] | None,
    max_retries: int | Literal["clear"] | None,
    reason: str | None,
    author: str | None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None,
) -> None:
    """View or retune a running eval's launch configuration mid-flight.

    Any `inspect eval` launch flag that can be retuned while the eval runs
    is settable here, under the same spelling; with no set options, shows
    the current configuration. Each option below is tagged with its scope —
    [task] targets the selected task, [process] every task in the process —
    and the output labels every knob likewise. Pass `--dry-run` to see what
    would change without applying it.

    Beyond the named flags, any limit registered by name through the
    `concurrency()` API — by tools (e.g. web search providers) or task code —
    is settable with `--key NAME LIMIT`; the output lists the registered
    keys. Lowering a concurrency limit never interrupts running samples —
    new work waits until in-flight holders drain. `--log-buffer` /
    `--log-shared` are the retune side of `inspect ctl task log-flush`: they
    set the buffering policy for future writes, while log-flush writes
    what's already buffered now. `--timeout` / `--attempt-timeout` /
    `--max-retries` set live overrides read by the model retry loop, so a
    change reaches even generate calls already retrying (in-flight API
    requests still drain first); pass `clear` to remove an override.
    `--max-tasks` likewise sets a live override, read by the task dispatcher
    at each dispatch decision: raising it starts pending tasks immediately,
    lowering never interrupts running tasks (new ones wait until in-flight
    drains below the limit).
    `--time-limit` / `--token-limit` / `--message-limit` likewise set live
    overrides on the task's per-sample limits, read where each sample's
    limits are checked — so a retune reaches in-flight samples (a lowered
    time limit cancels a sample already past it) as well as ones not yet
    started; pass `clear` to restore launch config. Applied
    changes are recorded in each affected eval log (who / when / old → new);
    `--reason` annotates the record with why. TASK
    is required only for setting a task-scoped knob when several tasks run.

    Example: inspect ctl config --max-connections 20 --dry-run
    """
    _run_config(
        task,
        max_samples=max_samples,
        max_tasks=max_tasks,
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        log_buffer=log_buffer,
        log_shared=log_shared,
        time_limit=time_limit,
        token_limit=token_limit,
        message_limit=message_limit,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        reason=reason,
        author=author,
        dry_run=dry_run,
        as_json=as_json,
        terse=terse,
    )


def _as_task_view(
    limits_view: TaskConfigView | ProcessConfigView,
) -> TaskConfigView | None:
    """The config view as the task envelope, or ``None`` for a process one.

    Discriminates on ``max_samples``, which rides every task envelope on
    every server version. The cast is needed because mypy won't narrow the
    union from an ``in`` check (structurally, a process envelope could carry
    extra keys). Callers read ``buffer`` with ``.get()``: task envelopes
    from pre-release version-0 builds lacked that key.
    """
    return cast(TaskConfigView, limits_view) if "max_samples" in limits_view else None


def _applied_knob_names(
    limits_view: TaskConfigView | ProcessConfigView,
    *,
    max_samples: int | None,
    max_tasks: int | Literal["clear"] | None = None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    key: tuple[str, int] | None,
    timeout: int | Literal["clear"] | None,
    attempt_timeout: int | Literal["clear"] | None,
    max_retries: int | Literal["clear"] | None,
    time_limit: int | Literal["clear"] | None,
    token_limit: int | Literal["clear"] | None,
    message_limit: int | Literal["clear"] | None,
) -> list[str]:
    """Names of the requested knobs the server reported as adjustable.

    Serves the no-live-buffer hard-error path so its "other knobs were still
    applied" tail names only knobs that actually landed — a requested knob
    the server reported as not adjustable did NOT apply. The buffer knobs
    self-exclude: their adjustability check (no ``buffer`` view) is exactly
    the condition that put the caller on the error path. The retry and
    per-sample limit overrides are always adjustable: the override layers
    exist regardless of any task's launch config (a strict server too old
    to know them 400s the whole mutation atomically, and a pre-strict
    server is refused by `_gate_strict_floor` before the PATCH is sent, so
    neither reaches this path).
    """
    task_view = _as_task_view(limits_view)
    max_samples_view = task_view["max_samples"] if task_view is not None else None
    return [
        name
        for name, value, adjustable in (
            (
                "--max-samples",
                max_samples,
                bool(max_samples_view and max_samples_view["adjustable"]),
            ),
            (
                "--max-sandboxes",
                max_sandboxes,
                bool(limits_view.get("max_sandboxes")),
            ),
            (
                "--max-subprocesses",
                max_subprocesses,
                bool(limits_view.get("max_subprocesses")),
            ),
            (
                "--max-connections",
                max_connections,
                bool(limits_view.get("adaptive")),
            ),
            (
                "--key",
                key,
                key is not None
                and any(
                    row["name"] == key[0] and row["adjustable"]
                    for row in limits_view.get("concurrency") or []
                ),
            ),
            # like the retry overrides, max_tasks is always adjustable (the
            # override layer exists regardless of launch config)
            ("--max-tasks", max_tasks, True),
            ("--timeout", timeout, True),
            ("--attempt-timeout", attempt_timeout, True),
            ("--max-retries", max_retries, True),
            ("--time-limit", time_limit, True),
            ("--token-limit", token_limit, True),
            ("--message-limit", message_limit, True),
        )
        if value is not None and adjustable
    ]


@_envelope_failures
def _run_config(
    task: str | None,
    *,
    max_samples: int | None,
    max_tasks: int | Literal["clear"] | None = None,
    max_sandboxes: int | None,
    max_subprocesses: int | None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None,
    log_buffer: int | None,
    log_shared: int | None,
    time_limit: int | Literal["clear"] | None = None,
    token_limit: int | Literal["clear"] | None = None,
    message_limit: int | Literal["clear"] | None = None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    reason: str | None = None,
    author: str | None = None,
    dry_run: bool,
    as_json: bool,
    terse: bool | None = None,
) -> None:
    # `set_buffer` gates the no-live-buffer hard error below; whether the
    # request as a whole is a mutation is derived once, in _exec_limits
    # (returned as `mutated`), so the two can't skew for a future knob.
    set_buffer = log_buffer is not None or log_shared is not None

    # Task-scoped knobs follow the mutation selector rule (sole running task
    # default, explicit TASK otherwise); process-scoped knobs need no selector.
    per_task_option = next(
        (
            name
            for name, value in (
                ("--max-samples", max_samples),
                ("--log-buffer", log_buffer),
                ("--log-shared", log_shared),
                ("--time-limit", time_limit),
                ("--token-limit", token_limit),
                ("--message-limit", message_limit),
            )
            if value is not None
        ),
        None,
    )

    servers = _http.list_discovered_servers()
    summaries = _fetch._fetch_summaries(servers).summaries

    scope = _resolve_scope(
        servers,
        summaries,
        task,
        per_task_option=per_task_option,
        no_task_id_advice="Run without TASK to view or set the process-wide config.",
    )
    if scope is None:
        if as_json:
            _echo_raw("null")
            return
        _echo_no_running_evals()
        return

    knob_values: dict[str, int | Literal["clear"] | None] = {
        "max_samples": max_samples,
        "max_tasks": max_tasks,
        "max_sandboxes": max_sandboxes,
        "max_subprocesses": max_subprocesses,
        "max_connections": max_connections,
        "key": key[1] if key is not None else None,
        "log_buffer": log_buffer,
        "log_shared": log_shared,
        "timeout": timeout,
        "attempt_timeout": attempt_timeout,
        "max_retries": max_retries,
        "time_limit": time_limit,
        "token_limit": token_limit,
        "message_limit": message_limit,
    }
    # a knob missing here would make its set look like a pure read — the
    # provenance below would be silently dropped from a recorded mutation
    assert knob_values.keys() == _KNOB_SCOPE.keys()
    requested_knobs = [knob for knob, value in knob_values.items() if value is not None]

    # provenance rides recorded mutations only — a read records nothing. The
    # author default is resolved client-side — the server has no view of who
    # invoked the CLI — and gated on the server supporting the params. On a
    # pure read an explicit --author/--reason has nothing to annotate:
    # hard-error (like --log-buffer with no buffer) rather than silently
    # dropping the values.
    if requested_knobs:
        _gate_strict_floor(servers, scope.socket_path, requested_knobs)
        author, reason = _gate_provenance_support(
            servers, scope.socket_path, author=author, reason=reason
        )
    elif author is not None or reason is not None:
        flags = " / ".join(
            flag
            for flag, value in (("--author", author), ("--reason", reason))
            if value is not None
        )
        _fail(
            "invalid_request",
            f"{flags} annotates a config change, but no set option was given "
            "— there is no record to attach it to. Add a set option "
            "(e.g. --max-samples) or drop the flag.",
        )

    limits_view, mutated = _exec_limits(
        scope.socket_path,
        scope.task_id,
        max_samples=max_samples,
        max_tasks=max_tasks,
        max_sandboxes=max_sandboxes,
        max_subprocesses=max_subprocesses,
        max_connections=max_connections,
        model=model,
        key=key,
        log_buffer=log_buffer,
        log_shared=log_shared,
        time_limit=time_limit,
        token_limit=token_limit,
        message_limit=message_limit,
        timeout=timeout,
        attempt_timeout=attempt_timeout,
        max_retries=max_retries,
        author=author,
        reason=reason,
        pid=scope.pid,
        dry_run=dry_run,
    )

    # The buffer knobs ride the task config view (`buffer` key); a task with
    # no live sample buffer (e.g. a reused log, or a superseded retry attempt)
    # reports it as None. On a view that's just a knob with nothing to adjust,
    # reported as a warning like the limits knobs. Only an explicit
    # --log-buffer/--log-shared is an error (there's nothing to apply it to) —
    # and since any limits set has already landed in the same PATCH, the
    # error must say which of those knobs actually applied (a requested knob
    # the server reported as not adjustable did NOT), and surface the
    # server's warnings that this exit would otherwise swallow.
    buffer_warnings: list[str] = []
    task_view = _as_task_view(limits_view)
    buffer_view = task_view.get("buffer") if task_view is not None else None
    if scope.task_id is not None and buffer_view is None:
        if set_buffer:
            applied_names = _applied_knob_names(
                limits_view,
                max_samples=max_samples,
                max_tasks=max_tasks,
                max_sandboxes=max_sandboxes,
                max_subprocesses=max_subprocesses,
                max_connections=max_connections,
                key=key,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                max_retries=max_retries,
                time_limit=time_limit,
                token_limit=token_limit,
                message_limit=message_limit,
            )
            message = (
                f"Task '{scope.task_id}' has no sample buffer in this "
                "process (e.g. a reused log, or a retry attempt that's "
                "been superseded) — --log-buffer/--log-shared cannot be "
                "set for this task."
                + (
                    f" The other requested knobs ({', '.join(applied_names)}) "
                    "were still applied."
                    if applied_names and not dry_run
                    else ""
                )
            )
            _echo(message, err=True)
            for warning in limits_view.get("warnings") or []:
                # the buffer warning restates the headline error; skip it
                if not warning.startswith("log_buffer"):
                    _echo(f"! {warning}", err=True)
            raise _CtlFailure("invalid_request", message)
        buffer_warnings.append(
            "log_buffer/log_shared are not adjustable for this task "
            "(no live sample buffer — e.g. a reused log)"
        )

    # The process-scoped knobs reach every task in the process — surface that
    # blast radius structurally when a set (or dry-run) used one. Derived from
    # `_KNOB_SCOPE` (via the assert-tied `knob_values`) so a future
    # process-scoped knob can't silently miss the note.
    global_knobs = [
        f"--{knob.replace('_', '-')}"
        for knob, value in knob_values.items()
        if value is not None and _KNOB_SCOPE[knob] == "process"
    ]
    notes = []
    note = _process_scope_note(global_knobs, scope.siblings)
    if note:
        notes.append(note)

    config = _compose_config(
        scope,
        limits_view,
        dry_run=dry_run,
        set_values=mutated,
        notes=notes,
        extra_warnings=buffer_warnings,
    )

    if as_json:
        _echo_raw(json_lib.dumps(config, indent=2))
        return

    # terse covers only a set — a pure view's requested output *is* the full
    # config block, so there is no header noise to shed
    if mutated and _use_terse(terse):
        target_label = (
            scope.task
            or scope.task_id
            or (f"pid {scope.pid}" if scope.pid is not None else "process")
        )
        settings = []
        for knob, value in knob_values.items():
            if value is None or knob == "key":
                continue
            rendered = f"{knob}={value}"
            # --model narrows the connections retune to matching controllers —
            # dropped from the line, a scripted log misrecords the blast radius
            if knob == "max_connections" and model is not None:
                rendered += f" (models matching '{model}')"
            settings.append(rendered)
        if key is not None:
            settings.append(f"concurrency:{key[0]}={key[1]}")
        _echo(
            _terse_line(
                "config",
                target_label,
                f"{'dry-run' if dry_run else 'applied'} — {', '.join(settings)}",
            )
        )
        # warnings and notes must survive terseness — "applied" above may be
        # qualified by a not-adjustable knob or a process-wide blast radius
        for warning in config.get("warnings") or []:
            _echo(f"! {warning}")
        for note in config.get("notes") or []:
            _echo(f"note: {note}")
        return

    _echo(scope.header)
    _echo()
    _print_config(config, changed=mutated)


def _compose_config(
    scope: _DirectiveScope,
    limits_view: TaskConfigView | ProcessConfigView,
    *,
    dry_run: bool,
    set_values: bool,
    notes: list[str],
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Shape the server's config view into the scope-labeled CLI view.

    Every knob carries ``"scope": "task" | "process"`` — scope is a property
    of the knob, not of the command path, so the output (not the spelling)
    is where an agent reads a knob's blast radius.
    """
    task_view = _as_task_view(limits_view)
    knobs: dict[str, Any] = {}
    if task_view is not None:
        knobs["max_samples"] = {
            "scope": _KNOB_SCOPE["max_samples"],
            **task_view["max_samples"],
        }
    # max_tasks (absent from an older server's view — skipped then, like the
    # retry knobs, rather than shown as a value claim)
    max_tasks_view = limits_view.get("max_tasks")
    if max_tasks_view is not None:
        knobs["max_tasks"] = {
            "scope": _KNOB_SCOPE["max_tasks"],
            **max_tasks_view,
        }
    knobs["max_sandboxes"] = {
        "scope": _KNOB_SCOPE["max_sandboxes"],
        "providers": limits_view.get("max_sandboxes") or [],
    }
    # `limit` absent means the limiter doesn't exist yet (no subprocess has
    # run in the process) — rendered as inactive rather than claiming a value
    knobs["max_subprocesses"] = {
        "scope": _KNOB_SCOPE["max_subprocesses"],
        **(limits_view.get("max_subprocesses") or {}),
    }
    knobs["max_connections"] = {
        "scope": _KNOB_SCOPE["max_connections"],
        "adaptive": limits_view.get("adaptive") or [],
    }
    # The retry-override knobs (absent from an older server's view). `override`
    # is the live process-wide override, None = launch config applies per call.
    retry_view = limits_view.get("retry")
    if retry_view is not None:
        from inspect_ai.model._generate_overrides import (
            GENERATE_CONFIG_OVERRIDE_FIELDS,
        )

        for knob in GENERATE_CONFIG_OVERRIDE_FIELDS:
            knobs[knob] = {
                "scope": _KNOB_SCOPE[knob],
                "override": retry_view.get(knob),
            }
    # The per-sample limit overrides (task views only — the knobs are
    # task-scoped; also absent from an older server's view). `override` is
    # the live task-wide override, None = launch config applies per sample.
    limits_view_overrides = task_view.get("limits") if task_view is not None else None
    if limits_view_overrides is not None:
        from inspect_ai.util._limit_overrides import SAMPLE_LIMIT_OVERRIDE_FIELDS

        for limit_knob in SAMPLE_LIMIT_OVERRIDE_FIELDS:
            knobs[limit_knob] = {
                "scope": _KNOB_SCOPE[limit_knob],
                "override": limits_view_overrides.get(limit_knob),
            }
    # `keys: None` (vs an empty list) means the server predates the
    # concurrency view — rendered as unreported rather than empty
    knobs["concurrency"] = {
        "scope": _KNOB_SCOPE["key"],
        "keys": limits_view.get("concurrency"),
    }
    buffer_view = task_view.get("buffer") if task_view is not None else None
    if buffer_view is not None:
        knobs["log_buffer"] = {
            "scope": _KNOB_SCOPE["log_buffer"],
            "value": buffer_view.get("log_buffer"),
            "pending": buffer_view.get("pending"),
        }
        knobs["log_shared"] = {
            "scope": _KNOB_SCOPE["log_shared"],
            "value": buffer_view.get("log_shared"),
        }

    # applied but unrecorded knobs surface as a warning (the change itself
    # landed; only its eval-log record didn't — e.g. no live log to record
    # in, or a fan-out that failed for some of the affected logs)
    persisted = limits_view.get("persisted")
    unrecorded_warnings = (
        [
            f"{', '.join(knob for knob, ok in persisted.items() if not ok)} "
            "applied but not recorded in one or more affected eval logs "
            "(a log without the record will not reflect this change)."
        ]
        if isinstance(persisted, dict) and not all(persisted.values())
        else []
    )

    return {
        "target": {
            "scope": "task" if scope.task_id else "process",
            "task_id": scope.task_id,
            "task": scope.task,
        },
        "knobs": knobs,
        "warnings": [
            *(limits_view.get("warnings") or []),
            *(extra_warnings or []),
            *unrecorded_warnings,
        ],
        "notes": notes,
        "applied": bool(set_values and not dry_run),
        "dry_run": dry_run,
        # per applied knob, whether the change was recorded in the affected
        # eval log(s); None when nothing was applied — no set option, or a
        # server that predates config-change persistence
        "persisted": persisted,
        "requested": limits_view.get("requested") or None,
    }


def _process_scope_note(global_knobs: list[str], siblings: int) -> str | None:
    """Note that process-scoped config knobs reach every task in the process.

    ``global_knobs`` is the set (``--max-connections`` / ``--max-sandboxes``
    / ``--max-subprocesses`` / the retry overrides) supplied on this
    invocation; ``siblings`` counts the tasks the retune can
    reach (the process's active tasks, plus the named target when it is
    completed). Returns ``None`` when there's nothing to flag — no such knob
    was set, or the target task is the only one the change can reach, so
    "process-wide" is invisible.
    """
    if not global_knobs or siblings <= 1:
        return None
    verb = "applies" if len(global_knobs) == 1 else "apply"
    if len(global_knobs) == 1:
        names = global_knobs[0]
    else:
        names = f"{', '.join(global_knobs[:-1])} and {global_knobs[-1]}"
    return (
        f"{names} {verb} process-wide — every active task in this process is affected."
    )


def _gate_strict_floor(
    servers: list[DiscoveredControlServer],
    socket_path: str,
    requested_knobs: list[str],
) -> None:
    """Hard-error a config mutation aimed at a pre-strict server.

    A strict server (control-API version >= :data:`_STRICT_SINCE`) rejects a
    mutation carrying any query param it doesn't declare with a 400,
    atomically, so the CLI can rely on the server itself to fail closed on a
    knob it doesn't know. A pre-strict server's PATCH handler instead
    silently ignores unknown params while applying the ones it recognizes —
    a partial apply behind a success-shaped response (dry runs included: the
    view just omits the unknown knobs). Below the floor, every knob mutation
    is refused before the PATCH is sent. Deliberately tableless — no
    per-knob bookkeeping (unlike the retired `_KNOB_SINCE` table) — at the
    cost of also refusing mutations a pre-strict server could in fact honor;
    such processes predate strict mutations entirely and are effectively
    extinct. A process with no advertised version (a discovery file that
    predates the field) is version 0. The version integer is meaningless to
    users, so the error names the flags and the remedy, not the number.
    """
    server = next((s for s in servers if str(s.socket_path) == socket_path), None)
    api_version = server.api_version if server is not None else 0
    if api_version >= _STRICT_SINCE:
        return
    flags = ", ".join("--" + knob.replace("_", "-") for knob in requested_knobs)
    target = f"pid {server.pid}" if server is not None else "the target process"
    _fail(
        "invalid_request",
        f"Cannot set {flags} — {target} is running an older inspect that "
        "may silently ignore unrecognized config settings; restart the eval "
        "to pick up the current version. No changes were applied.",
    )


def _default_provenance_author() -> str:
    """Default provenance author: the git identity, else the OS username.

    Follows the convention inspect_flow's tag/metadata steps use for
    `log_updates` provenance — `git config user.name` + `user.email`
    rendered `Name <email>` (the bare name when there is no email).
    Resolved client-side: the server process has no view of who invoked
    the CLI.
    """
    import getpass
    import subprocess

    def git_config(key: str) -> str:
        try:
            result = subprocess.run(
                ["git", "config", key],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    name = git_config("user.name")
    email = git_config("user.email")
    if name and email:
        return f"{name} <{email}>"
    if name:
        return name
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _gate_provenance_support(
    servers: list[DiscoveredControlServer],
    socket_path: str,
    *,
    author: str | None,
    reason: str | None,
) -> tuple[str | None, str | None]:
    """Resolve the provenance params (`author` / `reason`) for a config mutation.

    Against a server that records config changes (api version >=
    :data:`_PROVENANCE_SINCE`) the author defaults to the client-side git
    identity / OS user, so every recorded retune says who made it. An older
    strict server 400s the whole mutation on the unknown params, so there a
    *defaulted* author is silently dropped (a param the user never typed
    must not fail their retune) while an explicit ``--author`` / ``--reason``
    hard-errors before sending.
    """
    server = next((s for s in servers if str(s.socket_path) == socket_path), None)
    api_version = server.api_version if server is not None else 0
    if api_version >= _PROVENANCE_SINCE:
        return (author or _default_provenance_author(), reason)
    if author is not None or reason is not None:
        flags = ", ".join(
            flag
            for flag, value in (("--author", author), ("--reason", reason))
            if value is not None
        )
        target = f"pid {server.pid}" if server is not None else "the target process"
        _fail(
            "invalid_request",
            f"{flags} not supported — {target} is running an older inspect; "
            "restart the eval to pick up the current version. No changes "
            "were applied.",
        )
    return (None, None)


def _exec_limits(
    socket_path: str,
    task_id: str | None,
    *,
    max_samples: int | None,
    max_tasks: int | Literal["clear"] | None = None,
    max_sandboxes: int | None,
    max_subprocesses: int | None = None,
    max_connections: int | None,
    model: str | None,
    key: tuple[str, int] | None = None,
    log_buffer: int | None = None,
    log_shared: int | None = None,
    time_limit: int | Literal["clear"] | None = None,
    token_limit: int | Literal["clear"] | None = None,
    message_limit: int | Literal["clear"] | None = None,
    timeout: int | Literal["clear"] | None = None,
    attempt_timeout: int | Literal["clear"] | None = None,
    max_retries: int | Literal["clear"] | None = None,
    author: str | None = None,
    reason: str | None = None,
    pid: int | None = None,
    dry_run: bool,
) -> "_ConfigResult":
    """Read (no set knobs) or retune (any set knob) a scope's config.

    With ``task_id`` set this targets that task's ``/tasks/<id>/config`` (the
    per-task view, including ``max_samples`` and the ``log_buffer`` /
    ``log_shared`` buffer params; task ids are stable across retry attempts);
    with ``task_id=None`` it targets the process-level ``/config``
    (``max_sandboxes`` / ``max_subprocesses`` / ``max_connections`` / the
    retry overrides / named-key knob). ``model`` filters the adaptive
    controllers (a read param, applies to both); ``key`` is the ``(name,
    limit)`` pair for a named ``concurrency()`` registry entry, carried on
    the wire as ``key`` / ``key_limit``. The retry overrides (``timeout`` /
    ``attempt_timeout`` / ``max_retries``) and the per-sample limit
    overrides (``time_limit`` / ``token_limit`` / ``message_limit``,
    task-scoped) accept the keyword ``clear`` to
    remove an override (``0`` is a real value for them). Any settable knob
    that is not ``None`` makes this a mutation: a single-shot PATCH given the
    full mutation budget (see :data:`_MUTATION_TIMEOUT`) — derived here, not
    caller-supplied, so a knob can never ride a GET as an ignored query
    param. A pure read is a GET that retries a busy process on timeout;
    ``pid`` scopes that policy's exhaustion pointer to the target process.
    ``dry_run`` only applies to a set.
    """
    knob_values: dict[str, int | Literal["clear"] | None] = {
        "max_samples": max_samples,
        "max_tasks": max_tasks,
        "max_sandboxes": max_sandboxes,
        "max_subprocesses": max_subprocesses,
        "max_connections": max_connections,
        "key": key[1] if key is not None else None,
        "log_buffer": log_buffer,
        "log_shared": log_shared,
        "timeout": timeout,
        "attempt_timeout": attempt_timeout,
        "max_retries": max_retries,
        "time_limit": time_limit,
        "token_limit": token_limit,
        "message_limit": message_limit,
    }
    # the settable knobs are exactly the scope table's — a knob added to one
    # without the other fails loudly here rather than silently no-opping
    assert knob_values.keys() == _KNOB_SCOPE.keys()
    set_values = any(value is not None for value in knob_values.values())
    # the key knob rides the wire as two params (key=<name>, key_limit=<n>),
    # so it's excluded from the value passthrough and added explicitly
    params: dict[str, Any] = {
        knob: value
        for knob, value in knob_values.items()
        if knob != "key" and value is not None
    }
    if key is not None:
        params["key"] = key[0]
        params["key_limit"] = key[1]
    if model is not None:
        params["model"] = model
    # provenance rides mutations only (recorded with the change in each
    # affected eval log); the caller has already version-gated the params
    if set_values:
        if author is not None:
            params["author"] = author
        if reason is not None:
            params["reason"] = reason
    if dry_run:
        params["dry_run"] = True
    # the 404 messages distinguish "task unknown to the server" from version
    # skew: a process running an older inspect has neither route, and the
    # process-level path can only 404 for that reason
    if task_id is not None:
        not_found = (
            f"Task '{task_id}' not found in this process (it may have "
            "finished, or the process may be running an older inspect "
            "without the config endpoints)."
        )
    else:
        not_found = (
            "This process does not support the config endpoints (older "
            "inspect version?)."
        )
    scope = f"task {task_id}" if task_id is not None else "process"
    raw_view = _http._request_json(
        socket_path,
        f"/tasks/{task_id}/config" if task_id is not None else "/config",
        what=f"config for {scope}",
        not_found=not_found,
        params=params,
        mutate="patch" if set_values else None,
        pid=pid,
    )
    # the one cast at the JSON-parse boundary — shape documentation for
    # downstream field access, never validation (see "Wire envelopes" in
    # design/ctl/control-channel.md)
    view: TaskConfigView | ProcessConfigView = (
        cast(TaskConfigView, raw_view)
        if task_id is not None
        else cast(ProcessConfigView, raw_view)
    )
    return _ConfigResult(view=view, mutated=set_values)


class _ConfigResult(NamedTuple):
    """A config read/retune: the server view + whether a PATCH was sent.

    ``mutated`` is the single source for "was this a mutation" — callers
    (the `applied` flag, `changed=` rendering) must not re-derive it from
    their own knob lists, which would skew for a future knob.
    """

    view: TaskConfigView | ProcessConfigView
    mutated: bool
