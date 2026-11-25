"""Call the control channel's HTTP routes from inside a running eval.

The routes ``inspect ctl`` calls, served by the control server's app over an
in-process transport on the eval's own loop, so a test can list, cancel and
drain the run's tasks while it runs, on either async backend.
"""

from typing import Any

import httpx


async def ctl_request(
    method: str, path: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    """Send one request to the control channel's routes."""
    from inspect_ai._control.server import ControlServer

    app = ControlServer(run_id="test")._build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        return await client.request(method, path, params=params)


async def ctl_tasks() -> dict[str, dict[str, Any]]:
    """``GET /tasks``, keyed by task name."""
    response = await ctl_request("GET", "/tasks")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()
    return {row["task"]: row for row in rows}


async def ctl_task_directive(
    task_id: str, verb: str, **params: Any
) -> tuple[int, dict[str, Any]]:
    """``POST /tasks/<task_id>/<verb>``: the status code and the JSON body."""
    response = await ctl_request("POST", f"/tasks/{task_id}/{verb}", params)
    return response.status_code, response.json()
