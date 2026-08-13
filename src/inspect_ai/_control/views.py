"""TypedDicts for the control channel's config wire envelopes.

The wire boundary itself is HTTP/JSON, so these types validate nothing at
runtime — a ``TypedDict`` is a plain dict, so returning one from a route
changes nothing on the wire. What they buy (see "Wire envelopes: TypedDicts,
adopted lazily" in ``design/ctl/control-channel.md``): mypy checks every
server-side construction site (``_control/limits.py``) and the retyped test
doubles against the real shape, and the CLI ``cast()``s once at its
JSON-parse boundary — documentation plus downstream field-access checking,
*not* validation (strict client-side validation would fight version-skew
tolerance: an older server's envelope must stay acceptable). Keys
legitimately absent on older servers are ``NotRequired``, keyed to the
``CONTROL_API_VERSION`` history in ``inspect_ai._control``.

Other envelopes (task summaries, sample listing/show, events, keep/release,
the error envelope) get typed here lazily, when roadmap work next touches
them — not as a big-bang sweep.
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


MaxSamplesView = Union[AdjustableMaxSamplesView, UnadjustableMaxSamplesView]
"""The two shapes of the ``max_samples`` view, discriminated by ``adjustable``."""


class ProcessConfigView(TypedDict):
    """Envelope of ``GET``/``PATCH /config``.

    Built by :func:`inspect_ai._control.limits.process_limits`. The
    ``NotRequired`` keys are absent on servers predating the noted
    ``CONTROL_API_VERSION``.
    """

    dry_run: bool
    max_sandboxes: list[SandboxLimiterView]
    max_subprocesses: NotRequired[SubprocessLimiterView | None]
    """``None`` = no subprocess limiter yet; absent before version 1."""

    adaptive: list[AdaptiveControllerView]
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
    buffer: dict[str, Any] | None
    """The sample-buffer params (``None`` = no live buffer). Sourced from
    ``_control/buffer.py`` — a typed-``Any`` island until that view is typed."""
