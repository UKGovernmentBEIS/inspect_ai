"""Thread-free observation of the control channel during a real `eval_set`.

The control-channel integration tests need to observe process-global state
(``current_eval_summaries`` / ``current_sample_summaries`` /
``sample_error_detail``) at specific moments of a live eval — both terminal
("after the task finished") and mid-run ("while two samples are in flight").

The earlier approach ran ``eval_set`` on a background thread and polled the
HTTP endpoint over its AF_UNIX socket while hang-forever solvers held the eval
open. That was the source of indeterminate hangs: a test task that died
mid-run left a non-daemon thread spinning on ``while not release.is_set()``
forever.

This module replaces all of that with in-loop observation:

- A globally-registered ``@hooks`` probe (``_ProbeHook``) runs *on the eval's
  own anyio loop*, so it can read the control state directly — no socket, no
  second thread. The HTTP layer just JSON-serializes these same dicts, so
  asserting on them is equivalent to asserting on the endpoint responses.
- :func:`capturing` snapshots every eval's terminal state at ``on_run_end``
  (no sibling "hang" task needed — a task's own ``on_run_end`` fires when the
  run finishes).
- :func:`probe` + the :func:`gate` solver observe a *mid-run* state: ``gate``
  parks designated samples in-flight, the probe captures the moment a
  (synchronous) readiness predicate holds, then releases the gate so the eval
  completes. The gate is self-releasing — it never waits on an external signal
  and always times out — so a misconfigured test fails fast instead of hanging.

CLI formatting is covered by feeding captured data straight to the ``ctl``
render functions (``_print_samples_table`` etc., which emit via ``click.echo``)
and capturing stdout — again, no HTTP round-trip.
"""

import contextlib
import inspect
import io
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import anyio

from inspect_ai._control.events import sample_events
from inspect_ai._control.state import (
    current_eval_summaries,
    current_sample_summaries,
    sample_error_detail,
)
from inspect_ai.hooks import Hooks, RunEnd, hooks
from inspect_ai.solver import Generate, Solver, TaskState, solver

# The coordinator for the currently-running test, or None. The probe hook and
# the gate solver dispatch to it; both are no-ops while it's None, so the
# globally-registered hook never touches evals outside a `capturing()` /
# `probe()` block.
_ACTIVE: "_Coordinator | None" = None


class _Coordinator:
    """Base for the two observation strategies (terminal / mid-run)."""

    async def on_run_end(self, data: RunEnd) -> None:  # noqa: D102
        pass

    def should_park(self, sample_id: Any) -> bool:
        """Whether the gate solver should hold this sample in-flight."""
        return False

    async def gate_wait(self) -> None:
        """Block a parked sample until the observation is done (or times out)."""


@hooks(name="control_test_probe", description="Test-only control-channel probe.")
class _ProbeHook(Hooks):
    """Bridges the eval's hook bus to the active coordinator.

    Only ``on_run_end`` is needed: terminal :class:`Capture` snapshots there,
    and :class:`Probe` uses it as a backstop release. Mid-run observation is
    driven by the :func:`gate` solver (on a sample task), NOT by per-sample
    hooks — emitting them is serialized behind sample execution, so polling
    from a sample task sees state changes a hook would only learn about late.
    """

    def enabled(self) -> bool:
        return _ACTIVE is not None

    async def on_run_end(self, data: RunEnd) -> None:
        if _ACTIVE is not None:
            await _ACTIVE.on_run_end(data)


async def park_now() -> None:
    """Park the current sample in-flight until the active probe releases.

    For solvers that must do something first (e.g. fail their first attempt)
    and only then park — they can't use the :func:`gate` solver directly. Like
    the gate, it self-releases and is a no-op outside a :func:`probe` block.
    """
    if _ACTIVE is not None:
        await _ACTIVE.gate_wait()


@solver
def gate(should_park: Callable[[Any], bool] = lambda _sid: True) -> Solver:
    """A solver that parks its sample in-flight until the active probe releases.

    Replaces the old hang-forever solvers: instead of spinning on an external
    ``threading.Event`` that a test thread must remember to set, it waits on
    the active :class:`Probe`, which self-releases the moment its readiness
    predicate holds (and unconditionally after a timeout). Outside a
    :func:`probe` block it's a passthrough.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if _ACTIVE is not None and _ACTIVE.should_park(state.sample_id):
            await _ACTIVE.gate_wait()
        return state

    return solve


# --- terminal-state capture ------------------------------------------------


class Capture(_Coordinator):
    """Snapshot of every eval's terminal state, taken at ``on_run_end``.

    ``on_run_end`` fires while the eval's ``EvalState`` registry is still
    populated (it's cleared only at the outer ``eval_set`` boundary), so a
    single snapshot sees every eval the run registered — live, folded-retry,
    and reused alike.
    """

    # Safety bound for a held sample (see :meth:`gate_wait`): far longer than
    # any real teardown, so it only ever fires if a regression fails to cancel.
    _hold_timeout = 10.0

    def __init__(self) -> None:
        self.evals: list[dict[str, Any]] = []
        self.samples: dict[str, list[dict[str, Any]]] = {}
        self.errors: dict[tuple[str, str, int], dict[str, Any] | None] = {}
        self.events: dict[tuple[str, str, int], dict[str, Any] | None] = {}

    async def gate_wait(self) -> None:
        """Hold a sample in-flight until the eval tears it down.

        Used (via :func:`park_now`) to keep a sample running so a sibling's
        failure cancels it — the cancellation propagates through this wait. No
        timed sleep: the wait blocks on an event that's never set and is ended
        only by that external cancellation, bounded by a safety timeout so a
        regression that fails to cancel fails the test fast instead of hanging.
        """
        with anyio.move_on_after(self._hold_timeout):
            await anyio.Event().wait()

    async def on_run_end(self, data: RunEnd) -> None:
        self.evals = current_eval_summaries(0.0)
        for entry in self.evals:
            eval_id = entry["eval_id"]
            sample_rows = await current_sample_summaries(eval_id)
            self.samples[eval_id] = sample_rows
            for row in sample_rows:
                sid = str(row["sample_id"])
                epoch = int(row["epoch"])
                self.errors[(eval_id, sid, epoch)] = await sample_error_detail(
                    eval_id, sid, epoch
                )
                self.events[(eval_id, sid, epoch)] = await sample_events(
                    eval_id, sid, epoch
                )

    # query helpers -------------------------------------------------------

    def eval(self, task: str) -> dict[str, Any] | None:
        return next((e for e in self.evals if e["task"] == task), None)

    def eval_samples(self, task: str) -> list[dict[str, Any]]:
        entry = self.eval(task)
        return self.samples.get(entry["eval_id"], []) if entry else []

    def error_detail(
        self, task: str, sample_id: Any, epoch: int = 1
    ) -> dict[str, Any] | None:
        entry = self.eval(task)
        if entry is None:
            return None
        return self.errors.get((entry["eval_id"], str(sample_id), epoch))

    def events_page(
        self, task: str, sample_id: Any, epoch: int = 1
    ) -> dict[str, Any] | None:
        entry = self.eval(task)
        if entry is None:
            return None
        return self.events.get((entry["eval_id"], str(sample_id), epoch))


@contextlib.contextmanager
def capturing() -> Iterator[Capture]:
    """Capture terminal control state for an ``eval_set`` run.

    Usage::

        with capturing() as cap:
            eval_set(tasks=[...], ...)
        assert cap.eval("task_a")["status"] == "completed"
    """
    global _ACTIVE
    cap = Capture()
    _ACTIVE = cap
    try:
        yield cap
    finally:
        _ACTIVE = None


# --- mid-run capture -------------------------------------------------------


class Probe(_Coordinator):
    """Capture a mid-run state the instant a readiness predicate holds.

    The first sample to reach the gate becomes the **observer**: on its own
    sample task it polls the ``ready`` predicate (sync, or async when it needs
    to confirm a recorder read — e.g. that a just-completed sibling's sample is
    actually readable, not mid-teardown), and once it holds runs the async
    ``capture``, then releases the other parked samples. The remaining parked
    samples just wait to be released.

    Polling from a sample task — rather than reacting to per-sample hooks — is
    deliberate. Hook emission is serialized behind sample execution, so a hook
    learns of a state change (and the recorder read it would trigger) late or
    deadlocked; a sample task sees ``active_samples`` / the eval-state counters
    change immediately and reads the recorder in the same context the real HTTP
    endpoint uses. A never-satisfied predicate times out, leaving
    :attr:`result` ``None`` so the test fails fast instead of hanging.
    """

    def __init__(
        self,
        ready: Callable[[], bool | Awaitable[bool]],
        capture: Callable[[], Awaitable[Any]],
        *,
        park: Callable[[Any], bool],
        timeout: float,
        poll_interval: float = 0.02,
    ) -> None:
        self._ready = ready
        self._capture = capture
        self._park = park
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._open = anyio.Event()
        self._observer_claimed = False
        self.result: Any = None

    async def on_run_end(self, data: RunEnd) -> None:
        # Backstop: nothing should still be parked here, but release everything
        # so a misconfigured probe can't wedge the run.
        self._open.set()

    def should_park(self, sample_id: Any) -> bool:
        return self._park(sample_id)

    async def gate_wait(self) -> None:
        if not self._observer_claimed:
            self._observer_claimed = True  # atomic: no await before this
            with anyio.move_on_after(self._timeout):
                while not await self._is_ready():
                    await anyio.sleep(self._poll_interval)
                self.result = await self._capture()
            self._open.set()
        else:
            with anyio.move_on_after(self._timeout):
                await self._open.wait()

    async def _is_ready(self) -> bool:
        result = self._ready()
        if inspect.isawaitable(result):
            return await result
        return bool(result)


@contextlib.contextmanager
def probe(
    ready: Callable[[], bool | Awaitable[bool]],
    capture: Callable[[], Awaitable[Any]],
    *,
    park: Callable[[Any], bool] = lambda _sid: True,
    timeout: float = 15.0,
) -> Iterator[Probe]:
    """Observe a mid-run control-channel state during an ``eval_set`` run.

    Args:
        ready: Predicate over live state (``current_eval_summaries``,
            ``active_samples``, ``list_discovered_servers`` — anything sync).
            May be ``async`` when it needs to await the recorder (e.g. to
            confirm a just-completed sample is readable). The capture fires the
            first time it returns True.
        capture: Async callable run once when ``ready`` holds; its return value
            is exposed on :attr:`Probe.result`.
        park: Which sample ids the :func:`gate` solver should hold in-flight
            (default: all).
        timeout: Max seconds a parked sample waits before self-releasing.
    """
    global _ACTIVE
    p = Probe(ready, capture, park=park, timeout=timeout)
    _ACTIVE = p
    try:
        yield p
    finally:
        _ACTIVE = None


# --- CLI render capture ----------------------------------------------------


def render(fn: Callable[..., None], *args: Any, **kwargs: Any) -> str:
    """Call a ``ctl`` render function and return what it wrote to stdout.

    The render helpers (``_print_samples_table``, ``_print_sample_detail``, …)
    emit via ``click.echo``, so capturing stdout exercises the real formatting
    without an HTTP round-trip.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()
