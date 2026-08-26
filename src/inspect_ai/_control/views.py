"""TypedDicts for the control channel's config wire envelopes.

Plain dicts at runtime — nothing is validated and nothing changes on the
wire. They exist so mypy checks the server's construction sites and the
test doubles, with the CLI casting once at its JSON-parse boundary; see
"Wire envelopes: TypedDicts, adopted lazily" in
``design/ctl/control-channel.md`` for the convention (including why the
CLI must not validate). Keys legitimately absent on older *released*
servers are ``NotRequired``, keyed to the ``CONTROL_API_VERSION`` history
in ``inspect_ai._control``; a key missing only from dead pre-release
version-0 builds stays required (so construction sites are checked), with
the CLI keeping a tolerant ``.get()`` read where the field notes say so.
The other envelopes get typed here lazily, when work next touches them.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from typing_extensions import NotRequired, TypedDict


class SandboxLimiterView(TypedDict):
    """One per-provider sandbox limiter (an entry of ``max_sandboxes``)."""

    type: str
    limit: int
    in_use: int


class SubprocessLimiterView(TypedDict):
    """The process-global subprocess limiter (the ``max_subprocesses`` view)."""

    limit: int
    in_use: int


# functional syntax: "from" is a Python keyword
AdaptiveChangeView = TypedDict(
    "AdaptiveChangeView",
    {"at": float, "from": int, "to": int, "reason": str},
)
"""One recent scale change of an adaptive controller."""


class AdaptiveControllerView(TypedDict):
    """One adaptive connection controller (an entry of ``adaptive``)."""

    name: str
    limit: int
    in_use: int
    min: int
    max: int
    recent_changes: list[AdaptiveChangeView]


class ConcurrencyKeyView(TypedDict):
    """One static ``concurrency()`` registry entry (an entry of ``concurrency``)."""

    name: str
    limit: int
    in_use: int
    adjustable: bool


class AdjustableMaxSamplesView(TypedDict):
    """``max_samples`` backed by a resizable limiter (a user setpoint)."""

    limit: int
    in_use: int
    adjustable: Literal[True]


class UnadjustableMaxSamplesView(TypedDict):
    """``max_samples`` with no adjustable limiter.

    ``tracks_adaptive`` distinguishes the adaptive path (sample concurrency
    follows the task's controller) from a task with no live limiter at all
    (a reused log, or one that ran no samples in this process).
    """

    adjustable: Literal[False]
    tracks_adaptive: bool
    """Required, though pre-release version-0 builds lacked it (see the
    module docstring for where the ``NotRequired`` line is drawn)."""


MaxSamplesView = Union[AdjustableMaxSamplesView, UnadjustableMaxSamplesView]
"""The two shapes of the ``max_samples`` view, discriminated by ``adjustable``."""


class MaxTasksView(TypedDict):
    """The ``max_tasks`` view (the task dispatchers' live override).

    Every counter is ``None`` when no task dispatcher is live (during batch
    startup / between sequential batches) — the override layer still exists
    then, which is why ``adjustable`` is unconditionally ``True``.
    """

    limit: int | None
    launch: int | None
    override: int | None
    in_flight: int | None
    pending: int | None
    adjustable: Literal[True]


class ProcessConfigView(TypedDict):
    """Envelope of ``GET``/``PATCH /config``.

    Built by :func:`inspect_ai._control.limits.process_limits`. The
    ``NotRequired`` keys are absent on servers predating the noted
    ``CONTROL_API_VERSION``.
    """

    dry_run: bool
    max_tasks: NotRequired[MaxTasksView]
    """Absent before version 7."""

    max_sandboxes: list[SandboxLimiterView]
    max_subprocesses: NotRequired[SubprocessLimiterView | None]
    """``None`` = no subprocess limiter yet; absent before version 1."""

    adaptive: list[AdaptiveControllerView]
    """Required, though pre-release version-0 builds lacked it — the CLI
    reads it with ``.get()`` (see the module docstring)."""

    retry: NotRequired[dict[str, int | None]]
    """Active retry-loop overrides (``None`` = launch config applies per
    call); absent before version 4."""

    concurrency: NotRequired[list[ConcurrencyKeyView]]
    """Absent before version 2."""

    requested: dict[str, int | str] | None
    warnings: list[str]
    persisted: NotRequired[dict[str, bool] | None]
    """Per applied knob, whether its eval-log record was written (``None`` =
    nothing applied); absent before version 5."""


class TaskConfigView(ProcessConfigView):
    """Envelope of ``GET``/``PATCH /tasks/{task_id}/config``.

    The process view plus the per-task knobs. Built by
    :func:`inspect_ai._control.limits.task_limits`.
    """

    max_samples: MaxSamplesView
    limits: NotRequired[dict[str, int | None]]
    """Per-sample limit overrides (``time_limit`` / ``token_limit`` /
    ``message_limit`` → live task-wide override, ``None`` = the launch
    config applies per sample). Absent on servers predating the retune-
    limits knobs. Sourced from ``sample_limit_overrides``."""
    buffer: dict[str, Any] | None
    """The sample-buffer params (``None`` = no live buffer). Sourced from
    ``_control/buffer.py`` — a typed-``Any`` island until that view is typed.
    Required, but the CLI must read it with ``.get()``: pre-release
    version-0 task envelopes lacked the key (see the module docstring)."""
