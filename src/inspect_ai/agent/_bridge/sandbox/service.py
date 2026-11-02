from logging import getLogger  # noqa: E402
from typing import Awaitable, Callable, Protocol, cast

import anyio
from pydantic import JsonValue

from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.model._model import ModelRefusalError
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util._limit import LimitExceededError, check_turn_limit
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service
from inspect_ai.util._sandbox.service import find_control_flow

from .._errors import PROVIDER_ERROR_KEY, ResponseFilterError, provider_error_payload
from ..anthropic_api import inspect_anthropic_api_request
from ..bridge import filter_sandbox_client_headers
from ..completions import inspect_completions_api_request
from ..google_api import inspect_google_api_request
from ..responses import inspect_responses_api_request
from .host_tool import execute_host_tool
from .types import SandboxAgentBridge

logger = getLogger(__name__)

MODEL_SERVICE = "bridge_model_service"


class GenerateMethod(Protocol):
    async def __call__(
        self,
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]: ...


def _forward_provider_errors(
    generate: GenerateMethod, bridge: SandboxAgentBridge
) -> GenerateMethod:
    """Convert a failed generate into a forwardable provider-error result.

    Any exception from the wrapped generate is returned (not raised) under
    `PROVIDER_ERROR_KEY` so the sandbox service RPC delivers it via the `result`
    channel. This lets the model proxy emit a provider-dialect error response
    and stay up, instead of the RPC `error` channel triggering a fatal exit.

    A termination is re-raised: a `TerminateSampleError` (from an approver's
    `terminate` decision, too many consecutive rejections, or a request or
    response filter), bare or anywhere in the exception as `find_control_flow`
    finds it. The sandbox service dispatcher answers the RPC and propagates the
    termination out of the service task, which ends the sample.

    A `ModelRefusalError` (`fail_on_refusal`) and a `ResponseFilterError` (a
    `response_filter` is eval logic, not a passive observer) must also end the
    sample, but the dispatcher would turn a re-raise into an RPC error, so they
    are signalled through `bridge.request_fail` (raised on the agent's side by
    the bridge's monitor task) while the scaffold still gets an error reply.

    A `LimitExceededError` (message, token, cost or turn limit), bare or in an
    exception group such as a filter's task group, is returned as an error
    reply too. The first limit reached is recorded in `bridge.generation_limit`:
    once the agent has unwound, `sandbox_agent_bridge` raises it, so the scope
    that applied it (`run()`, or the sample) handles it, as for a native agent.
    A limit only in an exception's cause or context is not recorded: it was
    handled, or replaced by the error that escaped (a refusal reduced from a
    response filter's group, a `ResponseFilterError`, a fallback's provider
    error), which takes its own route. A group of only limits and refusals
    that holds a limit, such as a generate filter's, counts as its first
    member, as a response filter's group does: a refusal first fails the
    sample, a limit first is recorded. Other errors in a group a limit was
    selected from are logged, as for any error forwarded with no HTTP status.

    A turn limit is checked after a generation, so a request that arrives
    once one is exceeded gets its error reply without another generation.
    """

    async def generate_forwarding_errors(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        try:
            check_turn_limit()
            return await generate(json_data, headers)
        except Exception as ex:
            if find_control_flow(ex) is not None:
                # the service dispatcher ends the sample with it
                raise
            control = _first_control(ex)
            if isinstance(control, LimitExceededError):
                # only the first is raised, so later ones are not kept
                if bridge.generation_limit is None:
                    bridge.generation_limit = control
                _warn_other_errors(ex)
                return {PROVIDER_ERROR_KEY: cast(JsonValue, provider_error_payload(ex))}
            failure = control or ex
            if isinstance(failure, (ModelRefusalError, ResponseFilterError)):
                bridge.request_fail(failure)
                # no non-provider-error warning: the failure is reported once,
                # by the sample error the monitor task raises
                return {
                    PROVIDER_ERROR_KEY: cast(JsonValue, provider_error_payload(failure))
                }
            payload = provider_error_payload(ex)
            # A payload with no recoverable HTTP status almost always means the
            # failure came from our own request translation rather than the
            # provider (a provider error carries a status). Log it with a
            # traceback so a real bug isn't silently masked by forwarding it to
            # the client as an error response.
            if payload["status"] is None:
                logger.warning(
                    "Agent bridge model request failed with a non-provider error "
                    "(forwarding to the client as an error response): %s",
                    ex,
                    exc_info=True,
                )
            return {PROVIDER_ERROR_KEY: cast(JsonValue, payload)}

    return generate_forwarding_errors


def _first_control(ex: Exception) -> LimitExceededError | ModelRefusalError | None:
    """The limit to record, or refusal to fail with, for a failed generation.

    The first limit of `ex` and its group members, except that a group of only
    limits and refusals that holds a limit counts as its first member, depth
    first in order, as `_apply_response_filter` reduces a response filter's
    group.
    """
    if isinstance(ex, ExceptionGroup):
        control, rest = ex.split((LimitExceededError, ModelRefusalError))
        if (
            control is not None
            and rest is None
            and control.subgroup(LimitExceededError) is not None
        ):
            first: Exception = control
            while isinstance(first, ExceptionGroup):
                first = first.exceptions[0]
            return cast(LimitExceededError | ModelRefusalError, first)
    return _first_limit(ex)


def _warn_other_errors(ex: Exception) -> None:
    """Log the members of a group other than limits and refusals, with their traceback.

    They are likely bugs (a filter's own), which the limit's error reply would
    otherwise mask.
    """
    if isinstance(ex, ExceptionGroup):
        _, rest = ex.split((LimitExceededError, ModelRefusalError))
        if rest is not None:
            logger.warning(
                "Agent bridge model request reached a limit and failed with other "
                "errors (forwarding the limit to the client as an error response): %s",
                rest,
                exc_info=rest,
            )


def _first_limit(ex: BaseException) -> LimitExceededError | None:
    """The first `LimitExceededError` of `ex` and its group members, depth first in order."""
    if isinstance(ex, LimitExceededError):
        return ex
    if isinstance(ex, BaseExceptionGroup):
        for member in ex.exceptions:
            limit = _first_limit(member)
            if limit is not None:
                return limit
    return None


async def run_model_service(
    sandbox: SandboxEnvironment,
    web_search: WebSearchProviders | None,
    code_execution: CodeExecutionProviders | None,
    bridge: SandboxAgentBridge,
    instance: str,
    started: anyio.Event,
) -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods={
            "generate_completions": _forward_provider_errors(
                generate_completions(bridge), bridge
            ),
            "generate_responses": _forward_provider_errors(
                generate_responses(web_search, code_execution, bridge), bridge
            ),
            "generate_anthropic": _forward_provider_errors(
                generate_anthropic(web_search, code_execution, bridge), bridge
            ),
            "generate_google": _forward_provider_errors(
                generate_google(web_search, code_execution, bridge), bridge
            ),
            "list_tools": list_tools(bridge),
            "call_tool": call_tool(bridge),
        },
        until=lambda: False,
        sandbox=sandbox,
        instance=instance,
        polling_interval=2,
        started=started,
        requires_python=False,
    )


def generate_completions(
    bridge: SandboxAgentBridge,
) -> GenerateMethod:
    async def generate(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        completion = await inspect_completions_api_request(
            json_data,
            filter_sandbox_client_headers(headers, bridge.forward_client_headers),
            bridge,
        )
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_responses(
    web_search: WebSearchProviders | None,
    code_execution: CodeExecutionProviders | None,
    bridge: SandboxAgentBridge,
) -> GenerateMethod:
    async def generate(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        completion = await inspect_responses_api_request(
            json_data,
            filter_sandbox_client_headers(headers, bridge.forward_client_headers),
            web_search,
            code_execution,
            bridge,
        )
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_anthropic(
    web_search: WebSearchProviders | None,
    code_execution: CodeExecutionProviders | None,
    bridge: SandboxAgentBridge,
) -> GenerateMethod:
    async def generate(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        completion = await inspect_anthropic_api_request(
            json_data,
            filter_sandbox_client_headers(headers, bridge.forward_client_headers),
            web_search,
            code_execution,
            bridge,
        )
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_google(
    web_search: WebSearchProviders | None,
    code_execution: CodeExecutionProviders | None,
    bridge: SandboxAgentBridge,
) -> GenerateMethod:
    async def generate(
        json_data: dict[str, JsonValue],
        headers: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        del headers
        completion = await inspect_google_api_request(
            json_data, web_search, code_execution, bridge
        )
        return completion

    return generate


def list_tools(
    bridge: SandboxAgentBridge,
) -> Callable[[str], Awaitable[JsonValue]]:
    """Return tool schemas for a bridged tools server."""

    async def execute(server: str) -> JsonValue:
        if server not in bridge.bridged_tools:
            raise ValueError(f"Unknown bridged tools server: {server}")

        tools = list(bridge.bridged_tools[server].values())
        tools_info = get_tools_info(tools)

        return [
            {
                "name": info.name,
                "description": info.description,
                "inputSchema": info.parameters.model_dump(exclude_none=True),
            }
            for info in tools_info
        ]

    return execute


def call_tool(
    bridge: SandboxAgentBridge,
) -> Callable[[str, str, JsonValue], Awaitable[JsonValue]]:
    """Execute a bridged tool and return its result (`execute_host_tool`)."""

    async def execute(server: str, tool: str, arguments: JsonValue) -> JsonValue:
        return await execute_host_tool(bridge, server, tool, arguments)

    return execute
