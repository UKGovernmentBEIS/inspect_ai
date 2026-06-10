"""Unit tests for the phase-3 run controller (add-task coordination layer).

The controller resolves a task spec (a closure the eval runner supplies) and
buffers the resolved tasks for the keep-alive park to run. These exercise the
buffering / dry-run / registration contract with a fake resolve fn; the
end-to-end resolve + run path is covered by the integration tests.
"""

from typing import Any

import anyio
import pytest

from inspect_ai._control.run_control import (
    add_task,
    clear_run_controller,
    create_run_controller,
    register_run_controller,
)


def _resolve_ok(sentinel: object) -> Any:
    """A resolve fn that returns a fixed (resolved tasks, report)."""

    def resolve(
        task: str, task_args: Any, model: str | None
    ) -> tuple[list[Any], dict[str, Any]]:
        return [sentinel], {
            "task": task,
            "tasks": [{"task_id": "id-1", "task": task, "dataset_samples": 3}],
        }

    return resolve


async def test_submit_buffers_resolved_tasks_and_reports() -> None:
    sentinel = object()
    controller = create_run_controller("run-1", _resolve_ok(sentinel))

    report = controller.submit("mytask", {"a": 1}, None, dry_run=False)
    assert report["accepted"] is True
    assert report["dry_run"] is False
    assert report["task"] == "mytask"

    # the resolved batch is queued for the park to pick up
    batch = await controller.next_pending()
    assert batch == [sentinel]


async def test_dry_run_reports_without_buffering() -> None:
    controller = create_run_controller("run-1", _resolve_ok(object()))

    report = controller.submit("mytask", None, None, dry_run=True)
    assert report["dry_run"] is True
    assert "accepted" not in report  # not queued to run

    # nothing was buffered → next_pending blocks (we time out waiting)
    with anyio.move_on_after(0.05) as scope:
        await controller.next_pending()
    assert scope.cancel_called


def test_submit_propagates_resolve_errors() -> None:
    def resolve(task: str, task_args: Any, model: str | None) -> Any:
        raise ValueError(f"No task found for '{task}'.")

    controller = create_run_controller("run-1", resolve)
    with pytest.raises(ValueError, match="No task found"):
        controller.submit("nope", None, None, dry_run=False)


def test_add_task_without_registered_controller_returns_none() -> None:
    # no addable run registered (e.g. not launched --ctl-server=keep-alive)
    clear_run_controller()
    assert add_task("mytask") is None


def test_add_task_routes_to_registered_controller() -> None:
    controller = create_run_controller("run-1", _resolve_ok(object()))
    register_run_controller(controller)
    try:
        report = add_task("mytask", {"k": "v"}, dry_run=True)
        assert report is not None
        assert report["task"] == "mytask"
        assert report["dry_run"] is True
    finally:
        clear_run_controller()


# --- keep-alive park race (the add ↔ release wakeup) ----------------------


async def test_park_wakes_on_added_batch_then_releases() -> None:
    """The keep-alive park returns an added batch, then None once released."""
    from inspect_ai._control.server import ControlServer
    from inspect_ai._eval.eval import _park_until_release_or_added

    server = ControlServer(run_id="t")
    sentinel = object()
    controller = create_run_controller("t", _resolve_ok(sentinel))

    # a task added while parked wakes the park with its resolved batch
    controller.submit("mytask", None, None, dry_run=False)
    batch = await _park_until_release_or_added(server, controller)
    assert batch == [sentinel]

    # with nothing pending, releasing makes the park return None (exit)
    server.shutdown_event.set()
    assert await _park_until_release_or_added(server, controller) is None


async def test_park_without_controller_waits_for_release() -> None:
    """A non-addable keep-alive run just waits for release (returns None)."""
    from inspect_ai._control.server import ControlServer
    from inspect_ai._eval.eval import _park_until_release_or_added

    server = ControlServer(run_id="t")
    server.shutdown_event.set()
    assert await _park_until_release_or_added(server, None) is None
