"""Root ``ctl`` click group and shared click infrastructure.

The ``_NounGroup``/option-mirroring machinery that lets a bare noun
imply its ``list`` subcommand, shared option decorators, and the
echo/exit helpers used across noun modules.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, NoReturn

import click
from click.core import ParameterSource

from inspect_ai._control.discovery import discovery_dir

from ._failure import _fail
from ._render import _echo

if TYPE_CHECKING:
    # click 8.4 made ParamType generic in its stubs, but subscripting it at
    # runtime raises on the older click versions the package still supports
    # (>=8.1.3), so the parametrized base is typing-only.
    _IntOrClearBase = click.ParamType[int | Literal["clear"]]
else:
    _IntOrClearBase = click.ParamType


class _IntOrClearType(_IntOrClearBase):
    """Integer >= ``min``, or the keyword ``clear`` (restore launch config).

    The override knobs' value domain (the retry overrides and the per-sample
    limit overrides alike): every integer >= 0 (up to the server-shared
    ``MAX_GENERATE_CONFIG_OVERRIDE`` bound, which ``MAX_SAMPLE_LIMIT_OVERRIDE``
    matches) is a real value (``--max-retries 0`` means fail after the first
    attempt), so clearing an override needs an out-of-band spelling — the
    literal ``clear``, passed through to the server verbatim. ``--max-tasks``
    uses ``min=1`` (0 would be a disguised pause — `inspect ctl process
    pause` is the real spelling).
    """

    name = "integer or 'clear'"

    def __init__(self, min: int = 0) -> None:
        self._min = min

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> int | Literal["clear"]:
        from inspect_ai.model._generate_overrides import (
            MAX_GENERATE_CONFIG_OVERRIDE,
        )

        if isinstance(value, int):
            parsed = value
        elif value.strip().lower() == "clear":
            return "clear"
        else:
            try:
                parsed = int(value)
            except ValueError:
                self.fail(f"{value!r} is not an integer or 'clear'.", param, ctx)
        if parsed < self._min:
            bound = "negative" if self._min == 0 else f"less than {self._min}"
            self.fail(
                f"{parsed} is {bound} (pass 'clear' to restore launch config).",
                param,
                ctx,
            )
        if parsed > MAX_GENERATE_CONFIG_OVERRIDE:
            self.fail(
                f"{parsed} is larger than the maximum override value "
                f"({MAX_GENERATE_CONFIG_OVERRIDE}).",
                param,
                ctx,
            )
        return parsed


_INT_OR_CLEAR = _IntOrClearType()
_INT_MIN_ONE_OR_CLEAR = _IntOrClearType(min=1)


class _NounGroup(click.Group):
    """A resource-noun command group (``task`` / ``sample`` / ``process``).

    Bare invocation implies ``list`` (git precedent: bare ``git branch`` /
    ``git remote``) — implemented via ``invoke_without_command`` plus the
    ``list`` options mirrored onto the group, so ``ctl task --json`` works.
    The boundary is strict: the default never fires once a positional
    argument is present. A selector in the verb slot (``ctl sample my-task``)
    therefore fails — and the failure teaches the corrected spelling via
    ``hint`` rather than click's stock "No such command".
    """

    hint: Callable[[str], str] | None = None
    """Builds the unknown-command error message from the offending token."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        token = str(args[0])
        if (
            not token.startswith("-")
            and self.get_command(ctx, token) is None
            and self.hint is not None
        ):
            ctx.fail(self.hint(token))
        return super().resolve_command(ctx, args)


def _forward_group_options(ctx: click.Context) -> None:
    """Forward explicitly-given mirrored group options to the invoked verb.

    The ``list`` options are mirrored onto each noun group so the bare-noun
    default works (``ctl task --json``). When an explicit verb follows, those
    group-level values would otherwise be parsed and dropped — ``ctl task
    --json list`` silently emitting the human table, exactly the branch
    agents parse on. Forward them as defaults instead (the same option
    spelled after the verb still wins); a mirrored option the verb does not
    accept fails with the corrected spelling rather than being ignored.
    """
    if ctx.invoked_subcommand is None:
        return
    group = ctx.command
    assert isinstance(group, click.Group)
    given = {
        param.name: (ctx.params[param.name], param.opts[0])
        for param in group.params
        if param.name is not None
        and ctx.get_parameter_source(param.name) == ParameterSource.COMMANDLINE
    }
    if not given:
        return
    verb = group.get_command(ctx, ctx.invoked_subcommand)
    assert verb is not None
    verb_params = {param.name for param in verb.params}
    for name, (_, opt) in given.items():
        if name not in verb_params:
            ctx.fail(
                f"'{opt}' is a `list` option that `{group.name} "
                f"{ctx.invoked_subcommand}` does not accept. To use it, list "
                f"instead: `inspect ctl {group.name} list {opt} ...`."
            )
    # merge into (not over) any pre-existing defaults for the verb
    existing = dict((ctx.default_map or {}).get(ctx.invoked_subcommand) or {})
    ctx.default_map = {
        **(ctx.default_map or {}),
        ctx.invoked_subcommand: {
            **existing,
            **{name: value for name, (value, _) in given.items()},
        },
    }


def _mirror_list_options(group: click.Group, list_command: click.Command) -> None:
    """Mirror ``list``'s options onto its group for the bare-noun default.

    Deriving the mirror from the verb's own params keeps the two surfaces
    from drifting: an option added to ``list`` is mirrored automatically,
    where a hand-maintained copy would let bare ``ctl sample --new-opt``
    break while ``ctl sample list --new-opt`` works. Only options are
    mirrored — ``list``'s positional TASK would land in the verb slot
    (see ``_NounGroup``).
    """
    for param in list_command.params:
        if isinstance(param, click.Option):
            mirrored = copy.copy(param)
            # keep the verb's own help (the payload sketch especially — the
            # bare noun is the spelling scripted consumers reach for first)
            mirrored.help = (
                f"{param.help or ''} Mirrored from `list` for the bare-noun default."
            ).strip()
            group.params.append(mirrored)


def _json_option(what: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--json`` flag every command carries, with per-command envelope help.

    ``what`` sketches the payload's top-level keys so a scripted consumer can
    orient the first parse from ``--help`` alone, without a discovery
    round-trip through the command itself.
    """
    return click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help=f"Output as JSON ({what}).",
    )


def _model_option() -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--model`` disambiguator the task-selecting commands carry.

    One task run against several models (``--model a,b``) makes the task
    name ambiguous as a selector; this filters the selector's candidates
    (or, with no ``TASK``, all rows) to tasks whose model matches — the
    same rule ``ctl config --model`` uses (see `match_name_prefix`) — so
    the name resolves without falling back to opaque task ids.
    """
    return click.option(
        "--model",
        default=None,
        help=(
            "Only consider tasks running this model — matched at the name "
            "start or after a '/' (e.g. 'gpt-5' matches 'openai/gpt-5'). "
            "Disambiguates a task name that runs against several models."
        ),
    )


def _now_option(
    holds: str = "in-flight samples at their next model call",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--now`` (hard pause) flag the pause verbs carry.

    ``holds`` names what the scope's hard gate parks (the model scope holds
    calls *to* the model, role/grader calls included, rather than samples).
    """
    return click.option(
        "--now",
        is_flag=True,
        default=False,
        help=(
            f"Hard pause: additionally hold {holds} (outstanding calls "
            "finish; wall-clock time limits keep running while held)."
        ),
    )


def _terse_option(
    note: str = "",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """The ``--terse/--no-terse`` flag the task-scoped mutation verbs carry.

    Neither spelling given resolves by TTY (see :func:`_use_terse`).
    Deliberately not ``--quiet``: that spelling conventionally means *no*
    output, while this mode still reports each mutation's outcome — one
    scannable line per call (issue #160). ``note`` appends a per-command
    qualifier to the shared help text.
    """
    return click.option(
        "--terse/--no-terse",
        "terse",
        default=None,
        help=(
            "Report the outcome as one `verb target: outcome` line, without "
            "the task header — the default when stdout is not a TTY (pipes, "
            "captured output), so N repeated mutations read as N outcome lines. "
            "--no-terse forces the full rendering; --json takes precedence "
            "over both." + (f" {note}" if note else "")
        ),
    )


def _use_terse(terse: bool | None) -> bool:
    """Resolve the tri-state ``--terse/--no-terse`` flag (``None`` = by TTY).

    Piped or captured stdout — a script, an agent's Bash tool — gets the
    terse per-mutation line; an interactive terminal keeps the full
    task-header rendering, where the surrounding context earns its space.
    """
    if terse is not None:
        return terse
    # a detached/closed stdout (pythonw, a daemonized launcher) must not
    # crash the rendering path — it is certainly not an interactive terminal
    try:
        return not sys.stdout.isatty()
    except (AttributeError, ValueError):
        return True


def _terse_line(verb: str, target: str | None, outcome: str) -> str:
    """The one-line terse mutation grammar: ``verb target: outcome``.

    One composition site so the separator and shape can't drift per verb —
    scripts scan these lines (see the `--terse` help and the "Repeated
    Mutations" section of docs/control-channel.qmd). ``outcome`` starts with
    a status token (``requested`` / ``accepted`` / ``applied`` / ``dry-run``
    / ``no-op``), usually followed by `` — detail``.
    """
    return f"{verb} {target or '?'}: {outcome}"


# The payload sketch every mutation verb's `--json` help shows (pinned to
# `_mutation_envelope`'s keys by a test).
_MUTATION_ENVELOPE_HELP = "a `{target, applied, dry_run, detail}` mutation envelope"


@click.group("ctl")
def ctl_command() -> None:
    """Read and direct running evals and manage kept-alive processes.

    Commands are grouped by resource noun (listed below); `list` verbs are
    implied by the bare noun (`inspect ctl task` ≡ `inspect ctl task list`).
    All commands accept `--json`; a failed `--json` invocation emits an
    `{"error": {kind, exception, message, status}}` envelope on stdout
    (exit code stays non-zero; click usage errors — unknown option,
    missing argument — still exit 2 without one). With no running evals,
    commands that resolve a single task or sample target (and `config`)
    print `null`, except the paged reads (`sample events` / `sample
    messages`), which print an empty page (identifier echo with `task_id`
    null); list verbs print their usual envelope with empty rows.

    A process exits when its eval finishes; launch with `inspect eval
    --ctl-server=keep` to keep it inspectable here until you run
    `inspect ctl process release`.

    To launch an eval in the background — one that outlives your
    terminal and is driven entirely from here — use `inspect eval
    --detach` (see `inspect eval --help`).
    """
    return None


def _echo_no_running_evals() -> None:
    """Print the 'nothing to show' message shared by the read commands.

    Surfaces ``--ctl-server=keep`` here because this fires exactly
    when a user is confused that a just-finished eval isn't listed — its
    process has already exited unless it was launched to park.
    """
    _echo(
        f"No running evals found in {discovery_dir()}.\n"
        "Start an eval with `inspect eval <task>` — add `--ctl-server=keep` "
        "to keep the process inspectable after the eval finishes."
    )


def _busy_pids_label(busy_pids: list[int]) -> str:
    """Name the busy-skipped processes for an error message."""
    pids = ", ".join(str(p) for p in busy_pids)
    return f"pid{'s' if len(busy_pids) != 1 else ''} {pids}"


def _busy_note(busy_pids: list[int]) -> str:
    """Advise on busy-skipped processes in an error message."""
    return f"{_busy_pids_label(busy_pids)} busy — try again shortly"


def _anomalies_pointer(pid: int | None = None) -> str:
    """The stall-site escalation pointer at `inspect ctl process anomalies`.

    Printed wherever the human surface already shows a stall (a long-idle
    sample listing, a busy-skip note): the verb reads the pid's trace file
    directly — nothing is asked of the process — so it is the one `ctl`
    read that works against a busy or hung process. Without ``pid`` the
    bare verb is suggested (it reads every running process). Stderr / human
    rendering only: on ``--json`` the hint is omitted (no teaching prose
    inside envelopes — JSON consumers learn the verb from ``--help``).
    """
    if pid is not None:
        return (
            f"`inspect ctl process anomalies {pid}` shows the process's "
            "in-flight actions"
        )
    return (
        "`inspect ctl process anomalies` shows each running process's in-flight actions"
    )


def _exit_all_busy(busy_pids: list[int]) -> NoReturn:
    """Exit non-zero when no task summaries were collected and busy processes remain.

    The honest sibling of :func:`_echo_no_running_evals`: at least one alive
    process didn't answer (any responsive ones reported no tasks yet — a
    control endpoint binds before its first task registers), so the 'nothing
    running' message (and an empty ``--json`` envelope with exit 0) would be
    a false claim about the busy pids. Each busy pid's skip note has already
    printed the :func:`_anomalies_pointer` escalation (see
    :func:`_fetch_summaries`), so this terminal message doesn't repeat it —
    and the envelope message stays hint-free.
    """
    _fail("busy", f"No tasks visible: {_busy_note(busy_pids)}.")
