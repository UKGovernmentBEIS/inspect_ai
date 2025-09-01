import contextlib
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator

import anyio
from shortuuid import uuid

from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
)
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._sandbox import SandboxEnvironment
from inspect_ai.util._sandbox import sandbox as default_sandbox

from ..._agent import AgentState
from ..types import AgentBridge
from ..util import internal_web_search_providers
from .service import run_model_service

logger = getLogger(__file__)


class SandboxAgentBridge(AgentBridge):
    """Sandbox agent bridge."""

    def __init__(self, state: AgentState, port: int) -> None:
        super().__init__(state)
        self.port = port

    port: int
    """Model proxy server port."""


@contextlib.asynccontextmanager
async def sandbox_agent_bridge(
    state: AgentState | None = None,
    *,
    sandbox: SandboxEnvironment | None = None,
    port: int = 13131,
    web_search: WebSearchProviders | None = None,
) -> AsyncIterator[SandboxAgentBridge]:
    """Sandbox agent bridge.

    Provide Inspect integration for agents running inside sandboxes. Runs
    a proxy server in the container that provides REST entpoints for the OpenAI Completions API, OpenAI Responses API, and Anthropic API. This proxy server
    runs on port 13131 and routes requests to the current Inspect model provider.

    You should set `OPENAI_BASE_URL=http://localhost:13131/v1` or `ANTHROPIC_BASE_URL=http://localhost:13131` when executing
    the agent within the container and ensure that your agent targets the
    model name "inspect" when calling OpenAI or Anthropic. Use "inspect/<full-model-name>" to target other Inspect model providers.

    Args:
        state: Initial state for agent bridge. Used as a basis for yielding
           an updated state based on traffic over the bridge.
        sandbox: Sandbox to run model proxy server within.
        port: Port to run proxy server on.
        web_search: Configuration for mapping model internal
            web_search tools to Inspect. By default, will map to the
            internal provider of the target model (supported for OpenAI,
            Anthropic, Gemini, Grok, and Perplxity). Pass an alternate
            configuration to use to use an external provider like
            Tavili or Exa for models that don't support internal search.
    """
    # instance id for this bridge
    instance = f"proxy_{uuid()}"

    # resolve sandbox
    sandbox = sandbox or default_sandbox()

    # resolve web search config
    web_search = web_search or internal_web_search_providers()

    # create a state value that will be used to track mesages going over the bridge
    state = AgentState(messages=state.messages.copy() if state else [])

    try:
        async with anyio.create_task_group() as tg:
            # event to signal startup of model service
            started = anyio.Event()

            # create the bridge
            bridge = SandboxAgentBridge(state=state, port=port)

            # sandbox service that receives model requests
            tg.start_soon(
                run_model_service, sandbox, web_search, bridge, instance, started
            )

            # proxy server that runs in container and forwards to sandbox service
            tg.start_soon(run_model_proxy, sandbox, port, instance, started)

            # ensure services are up
            await anyio.sleep(0.1)

            # main agent
            try:
                yield bridge
            finally:
                tg.cancel_scope.cancel()
    except Exception as ex:
        raise inner_exception(ex)


async def run_model_proxy(
    sandbox: SandboxEnvironment, port: int, instance: str, started: anyio.Event
) -> None:
    # wait for model service to be started up
    await started.wait()

    # install the model proxy script in the container
    MODEL_PROXY_PY = f"/var/tmp/inspect-sandbox/{instance}/model-proxy.py"
    with open(Path(__file__).parent / "proxy.py", "r") as f:
        proxy_script = f.read().replace("<<<instance>>>", instance)
        await sandbox.write_file(MODEL_PROXY_PY, proxy_script)
    result = await sandbox.exec(["chmod", "+x", MODEL_PROXY_PY])
    if not result.success:
        raise RuntimeError(
            f"Error installing model proxy script for agent bridge: {result.stderr}"
        )

    # run the model proxy script
    result = await sandbox.exec([MODEL_PROXY_PY, str(port)])
    if not result.success:
        raise RuntimeError(
            f"Error running model proxy script for agent bridge: {result.stderr}"
        )
