import contextlib
from logging import getLogger
from typing import AsyncIterator

import anyio
from shortuuid import uuid

from inspect_ai.model._model import GenerateFilter
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    SANDBOX_TOOLS_CLI,
    sandbox_with_injected_tools,
)
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
)
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._sandbox import SandboxEnvironment

from ..._agent import AgentState
from ..util import internal_web_search_providers
from .service import MODEL_SERVICE, run_model_service
from .types import SandboxAgentBridge

logger = getLogger(__name__)


@contextlib.asynccontextmanager
async def sandbox_agent_bridge(
    state: AgentState | None = None,
    *,
    model: str | None = None,
    filter: GenerateFilter | None = None,
    retry_refusals: int | None = None,
    sandbox: str | None = None,
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
        model: Force the bridge to use a speicifc model (e.g. "inspect" to force the
            the default model for the task or "inspect/openai/gpt-4o" to force
            another specific model).
        filter: Filter for bridge model generation.
        retry_refusals: Should refusals be retried? (pass number of times to retry)
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
    sandbox_env = await sandbox_with_injected_tools(sandbox_name=sandbox)

    # resolve web search config
    web_search = web_search or internal_web_search_providers()

    # create a state value that will be used to track mesages going over the bridge
    state = state or AgentState(messages=[])

    try:
        async with anyio.create_task_group() as tg:
            # event to signal startup of model service
            started = anyio.Event()

            # create the bridge
            bridge = SandboxAgentBridge(
                state=state,
                filter=filter,
                retry_refusals=retry_refusals,
                port=port,
                model=model,
            )

            # sandbox service that receives model requests
            tg.start_soon(
                run_model_service, sandbox_env, web_search, bridge, instance, started
            )

            # proxy server that runs in container and forwards to sandbox service
            tg.start_soon(run_model_proxy, sandbox_env, port, instance, started)

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

    # run the model proxy script
    result = await sandbox.exec(
        cmd=[SANDBOX_TOOLS_CLI, "model_proxy"],
        env={
            f"{MODEL_SERVICE.upper()}_PORT": str(port),
            f"{MODEL_SERVICE.upper()}_INSTANCE": instance,
        },
        concurrency=False,
    )
    if not result.success:
        raise RuntimeError(
            f"Error running model proxy script for agent bridge: {result.stderr}"
        )
