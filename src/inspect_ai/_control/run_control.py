"""Process-level controller for run-mutating control-channel directives.

Phase-3 directives mutate the *run* rather than just reading it. The first is
**adding a task to a running eval**: ``POST /evals`` (``inspect ctl add``)
submits a task spec that runs in this process under the same ``run_id``.

This module is the thin coordination layer between the HTTP route and the eval
runner, mirroring how :mod:`inspect_ai._control.eval_state` bridges the read
routes. The heavy lifting — resolving a spec to a :class:`ResolvedTask` against
the eval's models/config, and running it — lives as closures built by the eval
runner (which has that context) and handed here at run start, exactly as
``register_eval`` hands over ``summaries_provider`` / ``sample_provider``.

Scope (first increment): the controller is registered only for an *addable*
run — a standalone ``inspect eval --ctl-server=keep-alive``. Added specs are buffered onto
a stream that the keep-alive park drains, starting a fresh task session for
them under the same run (the "restart" path). Live injection into a
still-running session (the "inject" path) is a later increment.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)

if TYPE_CHECKING:
    from inspect_ai._eval.task.resolved import ResolvedTask

# Resolve a task spec (registry name / file path, task args, optional model
# override) to its concrete ``ResolvedTask``s plus a JSON-able report (task
# names / ids / model / sample counts). Raises on a spec that can't be resolved
# (unknown task, bad args) — the route turns that into a 400. Built by the eval
# runner so it captures the eval's models / config / roles / sandbox.
ResolveTaskFn = Callable[
    [str, "dict[str, Any] | str | None", "str | None"],
    "tuple[list[ResolvedTask], dict[str, Any]]",
]


@dataclass
class RunController:
    """Accepts task additions for one run and feeds them to the keep-alive park.

    Owned by the eval runner for the lifetime of an addable run and registered
    process-globally so the control route can reach it. Added specs are resolved
    synchronously (so a bad spec fails the request) and the resolved tasks are
    buffered onto an unbounded stream; the park drains them.
    """

    run_id: str
    _resolve: ResolveTaskFn
    _send: MemoryObjectSendStream[list["ResolvedTask"]]
    _receive: MemoryObjectReceiveStream[list["ResolvedTask"]]

    def submit(
        self,
        task: str,
        task_args: dict[str, Any] | str | None = None,
        model: str | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Resolve a task spec and (unless ``dry_run``) queue it to run.

        Returns a report of what was (or would be) added. Raises if the spec
        can't be resolved — the caller surfaces that as a client error.
        """
        resolved, report = self._resolve(task, task_args, model)
        report["dry_run"] = dry_run
        if not dry_run:
            # unbounded stream → send never blocks; the park receives
            self._send.send_nowait(resolved)
            report["accepted"] = True
        return report

    async def next_pending(self) -> list["ResolvedTask"]:
        """Block until a batch of added tasks is available (for the park)."""
        return await self._receive.receive()


def create_run_controller(run_id: str, resolve: ResolveTaskFn) -> RunController:
    """Build a controller with an unbounded pending-task stream."""
    send, receive = anyio.create_memory_object_stream[list["ResolvedTask"]](
        float("inf")
    )
    return RunController(run_id=run_id, _resolve=resolve, _send=send, _receive=receive)


# Process-global slot. A process hosts one addable run at a time (the keep-alive
# park is the single owner), so a single slot suffices.
_controller: RunController | None = None
_lock = Lock()


def register_run_controller(controller: RunController) -> None:
    global _controller
    with _lock:
        _controller = controller


def get_run_controller() -> RunController | None:
    with _lock:
        return _controller


def clear_run_controller() -> None:
    global _controller
    with _lock:
        _controller = None


def add_task(
    task: str,
    task_args: dict[str, Any] | str | None = None,
    model: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Submit a task to the running addable eval (the route entry point).

    Returns the add report, or ``None`` when no run is accepting tasks (not
    launched ``--ctl-server=keep-alive``) — the route turns that into a clear error.
    """
    controller = get_run_controller()
    if controller is None:
        return None
    return controller.submit(task, task_args, model, dry_run=dry_run)
