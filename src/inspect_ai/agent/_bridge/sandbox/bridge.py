import contextlib
from collections.abc import Sequence
from logging import getLogger
from typing import AsyncIterator

import anyio
from shortuuid import uuid

from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import GenerateFilter
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
)
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox.exec_remote import ExecRemoteStreamingOptions

from ..._agent import AgentState
from ..util import default_code_execution_providers, internal_web_search_providers
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
    compaction: CompactionStrategy | None = None,
    sandbox: str | None = None,
    port: int = 13131,
    web_search: WebSearchProviders | None = None,
    code_execution: CodeExecutionProviders | None = None,
    bridged_tools: Sequence[BridgedToolsSpec] | None = None,
) -> AsyncIterator[SandboxAgentBridge]:
    """Sandbox agent bridge.

    Provide Inspect integration for agents running inside sandboxes. Runs
    a proxy server in the container that provides REST endpoints for the OpenAI Completions API, OpenAI Responses API, Anthropic API, and Google API. This proxy server
    runs on port 13131 and routes requests to the current Inspect model provider.

    You should set `OPENAI_BASE_URL=http://localhost:13131/v1`, `ANTHROPIC_BASE_URL=http://localhost:13131`, or `GOOGLE_GEMINI_BASE_URL=http://localhost:13131` when executing
    the agent within the container and ensure that your agent targets the
    model name "inspect" when calling OpenAI, Anthropic, or Google. Use "inspect/<full-model-name>" to target other Inspect model providers.

    Args:
        state: Initial state for agent bridge. Used as a basis for yielding
            an updated state based on traffic over the bridge.
        model: Model to use when the request does not use "inspect" or an "inspect/"
            prefixed model (defaults to "inspect", can also specify e.g.
            "inspect/openai/gpt-4o" to force another specific model).
        filter: Filter for bridge model generation.
        retry_refusals: Should refusals be retried? (pass number of times to retry)
        compaction: Compact the conversation when it it is close to overflowing
            the model's context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.
        sandbox: Sandbox to run model proxy server within.
        port: Port to run proxy server on.
        web_search: Configuration for mapping model internal
            web_search tools to Inspect. By default, will map to the
            internal provider of the target model (supported for OpenAI,
            Anthropic, Gemini, Grok, and Perplexity). Pass an alternate
            configuration to use to use an external provider like
            Tavily or Exa for models that don't support internal search.
        code_execution: Configuration for mapping model internal
            code_execution tools to Inspect. By default, will map to the
            internal provider of the target model (supported for OpenAI,
            Anthropic, Google, and Grok). If the provider does not support
            native code execution then the bash() tool will be provided
            (note that this requires a sandbox by declared for the task).
        bridged_tools: Host-side Inspect tools to expose to the sandboxed agent
            via MCP protocol. Each BridgedToolsSpec creates an MCP server that
            makes the specified tools available to the agent. The resolved
            MCPServerConfigStdio objects to pass to CLI agents are available via
            bridge.mcp_server_configs.
    """
    # instance id for this bridge
    instance = f"proxy_{uuid()}"

    # resolve sandbox
    sandbox_env = await sandbox_with_injected_tools(sandbox_name=sandbox)

    # resolve internal services
    web_search = web_search or internal_web_search_providers()
    code_execution = code_execution or default_code_execution_providers()

    # create a state value that will be used to track mesages going over the bridge
    state = state or AgentState(messages=[])

    # Track whether the agent completed successfully. If so, cleanup errors
    # should be logged but not cause the sample to fail.
    agent_completed = False

    try:
        async with anyio.create_task_group() as tg:
            # event to signal startup of model service
            started = anyio.Event()

            # create the bridge (will register bridged tools below)
            bridge = SandboxAgentBridge(
                state=state,
                filter=filter,
                retry_refusals=retry_refusals,
                compaction=compaction,
                port=port,
                model=model,
            )

            # register bridged tools with the bridge
            seen_names: set[str] = set()
            for spec in bridged_tools or []:
                if spec.name in seen_names:
                    raise ValueError(
                        f"Duplicate bridged_tools name: '{spec.name}'. "
                        "Each BridgedToolsSpec must have a unique name."
                    )
                seen_names.add(spec.name)
                config = _register_bridged_tools(bridge, spec, port)
                bridge.mcp_server_configs.append(config)

            # sandbox service that receives model requests (and tool calls)
            tg.start_soon(
                run_model_service,
                sandbox_env,
                web_search,
                code_execution,
                bridge,
                instance,
                started,
            )

            # wait for model service to start
            await started.wait()

            # proxy server that runs in container and forwards to sandbox service
            proxy = await sandbox_env.exec_remote(
                cmd=[SANDBOX_CLI, "model_proxy"],
                options=ExecRemoteStreamingOptions(
                    concurrency=False,
                    env={
                        f"{MODEL_SERVICE.upper()}_PORT": str(port),
                        f"{MODEL_SERVICE.upper()}_INSTANCE": instance,
                    },
                ),
            )

            # main agent
            try:
                yield bridge
                agent_completed = True
            finally:
                await proxy.kill()
                tg.cancel_scope.cancel()
    except Exception as ex:
        # If the agent completed successfully but we got an error during cleanup,
        # log the error but don't fail the sample.
        if agent_completed:
            logger.warning(
                f"Error during sandbox_agent_bridge cleanup (agent completed successfully): {ex}"
            )
        else:
            # Error occurred before or during agent execution
            raise inner_exception(ex)


def _register_bridged_tools(
    bridge: SandboxAgentBridge, spec: BridgedToolsSpec, port: int
) -> MCPServerConfigHTTP:
    """Register bridged tools with the bridge and return MCP config.

    Tools are registered in bridge.bridged_tools for execution by the service.
    Returns an MCPServerConfigHTTP with URL pointing to the MCP HTTP endpoint.
    """
    # Build tool registry for this server
    tools_dict = {ToolDef(tool).name: tool for tool in spec.tools}
    bridge.bridged_tools[spec.name] = tools_dict

    # Return MCP config with HTTP URL
    return MCPServerConfigHTTP(
        name=spec.name,
        type="http",
        url=f"http://localhost:{port}/mcp/{spec.name}",
        tools="all",
    )
