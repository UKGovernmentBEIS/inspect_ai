import json
from logging import getLogger
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio
from anyio.abc import TaskGroup

from inspect_ai.agent._bridge.sandbox.proxy import MODEL_PROXY_PORT
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .service import run_model_service

logger = getLogger(__file__)


def create_sandbox_agent(
    agent: str,
    sandbox: SandboxEnvironment,
    timeout: int | None = None,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def sandbox_agent(input: dict[str, Any]) -> dict[str, Any]:
        # copy the model proxy script to the container
        MODEL_PROXY_PY = "/var/tmp/inspect-sandbox/model-proxy.py"
        with open(Path(__file__).parent / "proxy.py", "r") as f:
            proxy_script = f.read()
            await sandbox.write_file(MODEL_PROXY_PY, proxy_script)
        await sandbox.exec(["chmod", "+x", MODEL_PROXY_PY])

        # function we'll use to run the script
        async def run_model_proxy() -> None:
            await sandbox.exec([MODEL_PROXY_PY])

        # result we will set within run_agent()
        result: dict[str, Any] = {}

        # main agent
        async def run_agent(tg: TaskGroup) -> None:
            try:
                # run the agent
                agent_result = await sandbox.exec(
                    cmd=[agent],
                    input=json.dumps(input),
                    env={"OPENAI_BASE_URL": f"http://localhost:{MODEL_PROXY_PORT}/v1"},
                    timeout=timeout,
                    timeout_retry=False,
                )

                if agent_result.success:
                    nonlocal result
                    result = json.loads(agent_result.stdout)
                else:
                    raise RuntimeError(f"Error running agent: {agent_result.stderr}")
            finally:
                # ensure that the other background tasks are cancelled when we finish
                tg.cancel_scope.cancel()

        try:
            async with anyio.create_task_group() as tg:
                # sandbox service that receives model requests
                tg.start_soon(run_model_service)

                # proxy server that runs in container and forwards to sandbox service
                tg.start_soon(run_model_proxy)

                # main agent
                tg.start_soon(run_agent, tg)

            return result
        except Exception as ex:
            raise inner_exception(ex)

    return sandbox_agent
