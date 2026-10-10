import contextlib
from collections.abc import Mapping, Sequence
from logging import getLogger
from typing import TYPE_CHECKING, AsyncIterator

import anyio
from shortuuid import uuid

from inspect_ai._sentinel._context import warn_sentinel_bridged
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
)
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._tools_bridge import BridgedToolsSpec
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
)
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._checkpoint.checkpointer import Checkpointer
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox.exec_remote import (
    ExecCompleted,
    ExecRemoteProcess,
    ExecRemoteStreamingOptions,
    ExecStderr,
)

from ..._agent import AgentState
from ..util import resolve_bridge_code_execution, resolve_bridge_web_search
from .service import MODEL_SERVICE, run_model_service
from .types import SandboxAgentBridge

if TYPE_CHECKING:
    # deferred: importing `inspect_ai.approval` at module scope here cycles
    # through approval -> event -> scorer while `inspect_ai.agent` is still
    # initializing. Same reason `model/_call_tools.py` defers it.
    from inspect_ai.approval._policy import ApprovalPolicy

logger = getLogger(__name__)


@contextlib.asynccontextmanager
async def sandbox_agent_bridge(
    state: AgentState | None = None,
    *,
    model: str | None = None,
    model_aliases: dict[str, str | Model] | None = None,
    model_resolver: ModelResolver | None = None,
    filter: GenerateFilter | None = None,
    retry_refusals: int | None = None,
    compaction: CompactionStrategy | None = None,
    sandbox: str | None = None,
    port: int = 13131,
    poll_timeout_recovery: float | None = None,
    web_search: WebSearchProviders | bool | None = None,
    code_execution: CodeExecutionProviders | bool | None = None,
    client_mcp_servers: bool | None = None,
    bridged_tools: Sequence[BridgedToolsSpec] | None = None,
    model_event_sink: ModelEventSink | None = None,
    forward_generation_config: bool = False,
    approval: list["ApprovalPolicy"] | None = None,
    checkpointer: Checkpointer | None = None,
    forward_client_headers: Mapping[str, Sequence[str]] | None = None,
) -> AsyncIterator[SandboxAgentBridge]:
    """Sandbox agent bridge.

    Provide Inspect integration for agents running inside sandboxes. Runs
    a proxy server in the container that provides REST endpoints for the OpenAI Completions API, OpenAI Responses API, Anthropic API, and Google API. This proxy server
    runs on port 13131 and routes requests to the current Inspect model provider.

    You should set `OPENAI_BASE_URL=http://localhost:13131/v1`, `ANTHROPIC_BASE_URL=http://localhost:13131`, or `GOOGLE_GEMINI_BASE_URL=http://localhost:13131` when executing
    the agent within the container and ensure that your agent targets the
    model name "inspect" when calling OpenAI, Anthropic, or Google. Requests for other
    model names are served by the eval's model unless `model_aliases` or
    `model_resolver` maps them elsewhere.

    The eval's configuration, not the agent's request, governs `service_tier`,
    `store`, `truncation` and the options of provider tools the agent declares;
    requests with `previous_response_id` are refused, and of the agent's HTTP
    headers only `Accept-Encoding` and those listed in `forward_client_headers`
    are forwarded.

    Args:
        state: Initial state for agent bridge. Used as a basis for yielding
            an updated state based on traffic over the bridge.
        model: Pin every request the bridge does not otherwise recognise to
            this model (e.g. "inspect/openai/gpt-4o"; the "inspect/" prefix is
            optional). Aliases, resolver results and the name "inspect" are not
            pinned. Defaults to `None`, which routes unrecognised names to the
            eval's active model ("inspect" means the same); map other names
            with `model_aliases`.
        model_aliases: Map of model name aliases. When a request uses a name
            that appears here, the corresponding value (a ``Model`` instance
            or model spec string) is used instead. Checked before the ``model``
            pin. Keys are the exact names the agent sends. Use this to reach a
            model other than the eval's model (e.g.
            ``{"claude-haiku-4-5": get_model("anthropic/claude-haiku-4-5")}``),
            including a model role the agent is meant to call
            (``{"subagent": get_model(role="subagent")}``). Every key is a
            model the agent can call, so do not alias a role such as a grader.
        model_resolver: Dynamic routing policy called with the requested model
            name (provider-qualified on a provider-specific endpoint, e.g.
            ``openai/gpt-5.1``). Checked after ``model_aliases`` and before the ``model``
            pin; return a ``Model``/spec to route the request there, or
            ``None`` to defer. Routes by policy without enumerating every name.
        filter: Filter for bridge model generation.
        retry_refusals: Should refusals be retried? (pass number of times to retry)
        compaction: Compact the conversation when it it is close to overflowing
            the model's context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.
        sandbox: Sandbox to run model proxy server within.
        port: Port to run proxy server on.
        poll_timeout_recovery: Seconds to keep re-polling the proxy server's
            process after a poll of it times out. Defaults to `None`, where a
            proxy poll that times out fails the sample. Each re-issued poll can
            wait the proxy's full 600-second poll timeout, so recovery can run
            past this value by about that much (see
            `ExecRemoteCommonOptions.poll_timeout_recovery`).
        web_search: Configuration for mapping model internal web_search tools to
            Inspect. Withheld by default: a sandboxed agent that names the native
            tool in a request would otherwise reach the web through the model
            provider, bypassing the sandbox's own network policy. Pass `True` to
            map to the internal provider of the target model (supported for
            OpenAI, Anthropic, Gemini, Grok, and Perplexity), or a configuration
            to use an external provider like Tavily or Exa for models that don't
            support internal search.
        code_execution: Configuration for mapping model internal code_execution
            tools to Inspect. Withheld by default (see `web_search`). Pass `True`
            to map to the internal provider of the target model (supported for
            OpenAI, Anthropic, Google, and Grok); if the provider does not support
            native code execution then the bash() tool will be provided
            (note that this requires a sandbox by declared for the task).
        client_mcp_servers: Honor MCP servers declared by the sandboxed agent
            (defaults to `False`). When enabled, the agent may name any server URL
            and the model provider will connect to it. Prefer `bridged_tools` for
            exposing tools you choose.
        bridged_tools: Host-side Inspect tools to expose to the sandboxed agent
            via MCP protocol. Each BridgedToolsSpec creates an MCP server that
            makes the specified tools available to the agent. A bridged tool
            executes only for a call the model proposed in a bridged generation,
            once per proposal, unless its spec sets `require_proposal=False`
            (see `BridgedToolsSpec`); an agent that calls host tools from
            model-written code, such as Codex CLI in code mode, needs that
            opt-out. The resolved MCPServerConfigStdio objects
            to pass to CLI agents are available via bridge.mcp_server_configs.
        model_event_sink: Optional sink that takes ownership of `ModelEvent`
            emission for calls routed through the bridge. When set, the bridge
            installs it around `model.generate()` so the sink decides when and
            under which span each event is emitted to the transcript.
        forward_generation_config: Forward client generation parameters (e.g.
            `max_tokens`, `temperature`, reasoning effort) to the model. Defaults
            to `False`, in which case those parameters are dropped and the resolved
            Inspect model config and provider defaults govern generation (structural
            parameters like the system prompt, tools, and response format are always
            forwarded). Set `True` for faithful-proxy behavior where the client's
            generation parameters are authoritative.
        approval: Approval policies for tool calls made by the bridged agent.
            Temporarily replaces any active approval policies for the duration of
            each approval. Eval-level and task-level policies already apply without
            this, but an `approval()` block entered inside the agent body does not
            reach the sandbox service task — pass policies here instead. A rejected
            tool call is never handed to the agent: the model is told it was
            rejected and generation is retried.
        checkpointer: Checkpointer to drive through the bridge. When provided,
            the bridge ticks it after each generation and registers its agent
            state (messages, output, compaction prefix) for checkpoint backup
            and restore, so a checkpointed run survives resume. Defaults to
            `None` (no checkpointing).
        forward_client_headers: Client request headers the sandboxed agent may
            send to the model provider, mapping each header name
            (case-insensitive) to its allowed values, e.g.
            `{"anthropic-beta": ["context-management-2025-06-27"]}`. A
            comma-separated value is matched one item at a time; items not
            listed are dropped with a warning, and the header is dropped when
            none remain. Defaults to `None`: no client header is forwarded
            except `Accept-Encoding`. Credential and transport headers (e.g.
            `Authorization`, `api-key`, `x-goog-api-key`, `x-amz-*`, `Host`,
            `Content-Type`) cannot be listed.
    """
    warn_sentinel_bridged()

    # instance id for this bridge
    instance = f"proxy_{uuid()}"

    # resolve sandbox
    sandbox_env = await sandbox_with_injected_tools(sandbox_name=sandbox)

    # resolve granted capabilities. These default to withheld: the sandboxed agent
    # can otherwise obtain them just by naming the native tool in a request, which
    # reaches the web through the model provider even when the sandbox has no
    # network egress of its own.
    web_search_grant = resolve_bridge_web_search(web_search, default_grant=False)
    code_execution_grant = resolve_bridge_code_execution(
        code_execution, default_grant=False
    )
    allow_remote_mcp = False if client_mcp_servers is None else client_mcp_servers

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
                model_aliases=model_aliases,
                model_resolver=model_resolver,
                model_event_sink=model_event_sink,
                forward_generation_config=forward_generation_config,
                approval=approval,
                checkpointer=checkpointer,
                allow_remote_mcp=allow_remote_mcp,
                forward_client_headers=forward_client_headers,
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
            bridge.warn_indistinct_tools()

            # sandbox service that receives model requests (and tool calls)
            tg.start_soon(
                run_model_service,
                sandbox_env,
                web_search_grant,
                code_execution_grant,
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
                    user=sandbox_env._tools_user,
                    env={
                        f"{MODEL_SERVICE.upper()}_PORT": str(port),
                        f"{MODEL_SERVICE.upper()}_INSTANCE": instance,
                    },
                    poll_timeout=600,
                    poll_timeout_recovery=poll_timeout_recovery,
                ),
            )

            # monitor proxy for unexpected death
            tg.start_soon(_monitor_proxy, proxy)

            # monitor for a sample failure requested from the service task
            # (approver termination, fail_on_refusal, a host tool that raised)
            tg.start_soon(_monitor_failure, bridge)

            # main agent
            try:
                yield bridge
                agent_completed = True
            finally:
                with anyio.CancelScope(shield=True):
                    # ensure the process terminates (no-op if already dead)
                    await proxy.kill()

                # ensure the scope is cancelled
                tg.cancel_scope.cancel()
    except Exception as ex:
        # If the agent completed successfully but we got an error during cleanup,
        # log the error but don't fail the sample.
        if agent_completed:
            logger.warning(
                f"Error during sandbox_agent_bridge cleanup (agent completed successfully): {inner_exception(ex)}"
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
    bridge.register_bridged_tools(
        spec.name,
        {ToolDef(tool).name: tool for tool in spec.tools},
        require_proposal=spec.require_proposal,
    )

    # Return MCP config with HTTP URL
    return MCPServerConfigHTTP(
        name=spec.name,
        type="http",
        url=f"http://localhost:{port}/mcp/{spec.name}",
        tools="all",
    )


async def _monitor_failure(bridge: SandboxAgentBridge) -> None:
    """Raise the error a bridged generation or tool call asked the sample to fail with.

    Bridged generations and host tool calls run in the sandbox service task,
    whose exceptions never propagate (see `SandboxAgentBridge.request_fail`).
    Raising here instead puts the error in the bridge's own task group, so it
    unwinds the agent and reaches the sample runner.
    """
    await bridge._failure_requested.wait()
    raise bridge._failure or TerminateSampleError(
        "Sample terminated by tool call approver."
    )


async def _monitor_proxy(proxy: ExecRemoteProcess) -> None:
    """Monitor the proxy process event stream and raise if it dies unexpectedly."""
    stderr: list[str] = []
    async for event in proxy:
        if isinstance(event, ExecStderr):
            stderr.append(event.data)
            logger.debug("model_proxy stderr: %s", event.data.rstrip())
        if isinstance(event, ExecCompleted):
            if not event.success:
                raise RuntimeError(
                    f"Model proxy process exited unexpectedly with failure: {''.join(stderr)}."
                )
            if stderr:
                logger.warning(
                    "model_proxy stderr output on clean exit:\n%s",
                    "".join(stderr).rstrip(),
                )
