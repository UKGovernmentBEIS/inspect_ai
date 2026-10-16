"""Run one sandbox service request through the real dispatcher, with faked I/O."""

import json
from typing import Any, Awaitable, Callable

import anyio
import anyio.abc
import pytest
from pydantic import JsonValue

from inspect_ai.agent._bridge.sandbox.bridge import _monitor_failure
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.util._sandbox.service import SandboxService
from inspect_ai.util._subprocess import ExecResult

REQUEST_ID = "r1"
REQUEST_FILE = f"/req/{REQUEST_ID}.json"


def dispatching_service(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    method: Callable[..., Awaitable[JsonValue]],
    params: dict[str, Any],
    errors: list[str | None],
) -> SandboxService:
    """A `SandboxService` holding one queued request for `method_name`.

    `_handle_request_tracked` runs the actual parse, dispatch and error handling;
    only reading the request, writing the response and removing the request file
    are faked. Each response's error (`None` for a result) is appended to `errors`.
    The response write yields to the event loop, as a real sandbox write does, so
    a task woken by the method gets to run before the response is recorded.
    """
    service = SandboxService.__new__(SandboxService)
    service._name = "svc"
    service._methods = {method_name: method}
    service._requests_dir = "/req"
    service._in_flight = {REQUEST_ID}

    request = json.dumps({"id": REQUEST_ID, "method": method_name, "params": params})

    async def fake_exec(cmd: list[str], **kwargs: Any) -> ExecResult[str]:
        return ExecResult(success=True, returncode=0, stdout=request, stderr="")

    async def fake_write_response(
        request_file: str,
        request_id: str,
        result: JsonValue | None,
        error: str | None = None,
    ) -> None:
        await anyio.sleep(0)
        errors.append(error)

    async def fake_remove(request_file: str) -> None:
        pass

    monkeypatch.setattr(service, "_exec", fake_exec)
    monkeypatch.setattr(service, "_write_response", fake_write_response)
    monkeypatch.setattr(service, "_remove_request_file", fake_remove)
    return service


def group_leaves(ex: BaseException) -> list[BaseException]:
    """The non-group exceptions in `ex`, in order (just `ex` if it is not a group)."""
    if isinstance(ex, BaseExceptionGroup):
        return [leaf for child in ex.exceptions for leaf in group_leaves(child)]
    return [ex]


async def serve_beside_failure_monitor(
    service: SandboxService, bridge: SandboxAgentBridge
) -> list[BaseException]:
    """Serve the queued request in a task group with the bridge's failure monitor.

    The shape `sandbox_agent_bridge` runs them in: the service and
    `_monitor_failure` share the task group that unwinds the agent. Returns the
    exceptions the group unwound with, or an empty list if neither raised.
    """
    unwound: list[BaseException] = []

    async def serve(tg: anyio.abc.TaskGroup) -> None:
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
        # let a monitor woken by the request raise before stopping it
        await anyio.wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    with anyio.fail_after(10):
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(_monitor_failure, bridge)
                tg.start_soon(serve, tg)
        except Exception as ex:
            unwound = group_leaves(ex)
    return unwound
