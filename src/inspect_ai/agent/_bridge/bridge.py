import contextlib
import importlib
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, AsyncGenerator, Awaitable, Callable, Type, cast

from jsonschema import Draft7Validator
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import to_json

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.log._samples import sample_active
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import GenerateFilter, get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai_convert import (
    messages_from_openai,
    messages_to_openai,
)
from inspect_ai.model._providers.providers import (
    validate_anthropic_client,
    validate_openai_client,
)
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
)

from .anthropic_api import inspect_anthropic_api_request
from .completions import inspect_completions_api_request
from .google_api import inspect_google_api_request
from .responses import inspect_responses_api_request
from .util import (
    default_code_execution_providers,
    internal_web_search_providers,
    resolve_web_search_providers,
)

# Headers blocked from bridge clients (exact match, case-insensitive)
_BLOCKED_BRIDGE_HEADERS = frozenset(
    [
        # Inspect internal tracking
        "x-irid",
        # Authentication
        "authorization",
        "x-api-key",
        # Protocol headers
        "content-type",
        "content-length",
        "transfer-encoding",
        "host",
        "connection",
        # SDK internal headers
        "anthropic-version",
        # User-Agent would be misleading since Inspect transforms the request
        "user-agent",
    ]
)

# Header prefixes blocked from bridge clients
_BLOCKED_BRIDGE_HEADER_PREFIXES = ("x-stainless-",)


def filter_bridge_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Filter headers from bridge clients, removing sensitive/internal headers.

    Note: `anthropic-beta` is intentionally NOT blocked - it's used for
    legitimate feature flags (e.g., `code-execution-2025-08-25`).
    """
    if headers is None:
        return None
    filtered = {
        k: v
        for k, v in headers.items()
        if k.lower() not in _BLOCKED_BRIDGE_HEADERS
        and not k.lower().startswith(_BLOCKED_BRIDGE_HEADER_PREFIXES)
    }
    return filtered if filtered else None


@contextlib.asynccontextmanager
async def agent_bridge(
    state: AgentState | None = None,
    *,
    filter: GenerateFilter | None = None,
    retry_refusals: int | None = None,
    compaction: CompactionStrategy | None = None,
    web_search: WebSearchProviders | None = None,
    code_execution: CodeExecutionProviders | None = None,
) -> AsyncGenerator[AgentBridge, None]:
    """Agent bridge.

    Provide Inspect integration for 3rd party agents that use the
    the OpenAI Completions API, OpenAI Responses API, or Anthropic API.
    The bridge patches the OpenAI and Anthropic client libraries
    to redirect any model named "inspect" (or prefaced with
    "inspect/" for non-default models) into the Inspect model API.

    See the [Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html)
    documentation for additional details.

    Args:
       state: Initial state for agent bridge. Used as a basis for yielding
          an updated state based on traffic over the bridge.
       filter: Filter for bridge model generation.
       retry_refusals: Should refusals be retried? (pass number of times to retry)
       compaction: Compact the conversation when it it is close to overflowing
          the model's context window. See [Compaction](https://inspect.aisi.org.uk/compaction.html) for details on compaction strategies.
       web_search: Configuration for mapping model internal
          web_search tools to Inspect. By default, will map to the
          internal provider of the target model (supported for OpenAI,
          Anthropic, Gemini, Grok, and Perplexity). Pass an alternate
          configuration to use to use an external provider like
          Tavili or Exa for models that don't support internal search.
       code_execution: Configuration for mapping model internal
          code_execution tools to Inspect. By default, will map to the
          internal provider of the target model (supported for OpenAI,
          Anthropic, Google, and Grok). If the provider does not support
          native code execution then the bash() tool will be provided
          (note that this requires a sandbox by declared for the task).
    """
    # ensure one time init
    init_bridge_request_patch()

    # resolve web search config
    web_search = resolve_web_search_providers(web_search)
    code_execution = code_execution or default_code_execution_providers()

    # create a state value that will be used to track mesages going over the bridge
    state = state or AgentState(messages=[])

    # create the bridge
    bridge = AgentBridge(state, filter, retry_refusals, compaction)

    # set the patch config for this context and child coroutines
    token = _patch_config.set(
        PatchConfig(
            enabled=True,
            web_search=web_search,
            code_execution=code_execution,
            bridge=bridge,
        )
    )
    try:
        yield bridge
    finally:
        _patch_config.reset(token)


_patch_initialised: bool = False


@dataclass
class PatchConfig:
    enabled: bool = field(default=False)
    web_search: WebSearchProviders = field(
        default_factory=internal_web_search_providers
    )
    code_execution: CodeExecutionProviders = field(
        default_factory=default_code_execution_providers
    )
    bridge: AgentBridge = field(
        default_factory=lambda: AgentBridge(AgentState(messages=[]))
    )


_patch_config: ContextVar[PatchConfig] = ContextVar(
    "bridge_request_patch_config", default=PatchConfig()
)


def init_bridge_request_patch() -> None:
    global _patch_initialised
    if _patch_initialised:
        return

    init_openai_request_patch()
    init_anthropic_request_patch()
    init_google_request_patch()

    _patch_initialised = True


def init_openai_request_patch() -> None:
    validate_openai_client("agent bridge")

    from openai._base_client import AsyncAPIClient, _AsyncStreamT
    from openai._models import FinalRequestOptions
    from openai._types import Omit, ResponseT

    # extract headers
    def request_headers(options: FinalRequestOptions) -> dict[str, str] | None:
        if isinstance(options.headers, dict) and len(options.headers) > 0:
            headers: dict[str, str] = {}
            for name, value in options.headers.items():
                if not isinstance(value, Omit):
                    headers[name] = value
            return headers

        return None

    # get reference to original method
    original_request = getattr(AsyncAPIClient, "request")
    if original_request is None:
        raise RuntimeError("Couldn't find 'request' method on AsyncAPIClient")

    @wraps(original_request)
    async def patched_request(
        self: AsyncAPIClient,
        cast_to: Type[ResponseT],
        options: FinalRequestOptions,
        *,
        stream: bool = False,
        stream_cls: type[_AsyncStreamT] | None = None,
    ) -> Any:
        # we have patched the underlying request method so now need to figure out when to
        # patch and when to stand down
        config = _patch_config.get()
        if (
            # enabled for this coroutine
            config.enabled
            # completions or responses request
            and options.url in ["/chat/completions", "/responses"]
        ):
            # must also be an explicit request for an inspect model
            json_data = cast(dict[str, Any], options.json_data)
            if targets_inspect_model(json_data):
                if stream:
                    raise_stream_error()

                headers = filter_bridge_headers(request_headers(options))

                if options.url == "/chat/completions":
                    return await inspect_completions_api_request(
                        json_data, headers, config.bridge
                    )
                else:
                    return await inspect_responses_api_request(
                        json_data,
                        headers,
                        config.web_search,
                        config.code_execution,
                        config.bridge,
                    )

        # otherwise just delegate
        return await original_request(
            self,
            cast_to,
            options,
            stream=stream,
            stream_cls=stream_cls,
        )

    setattr(AsyncAPIClient, "request", patched_request)


def init_anthropic_request_patch() -> None:
    # don't patch if no anthropic
    if not importlib.util.find_spec("anthropic"):
        return

    validate_anthropic_client("agent bridge")

    from anthropic._base_client import AsyncAPIClient, _AsyncStreamT
    from anthropic._models import FinalRequestOptions
    from anthropic._types import Omit, ResponseT

    # extract headers
    def request_headers(options: FinalRequestOptions) -> dict[str, str] | None:
        if isinstance(options.headers, dict) and len(options.headers) > 0:
            headers: dict[str, str] = {}
            for name, value in options.headers.items():
                if not isinstance(value, Omit):
                    headers[name] = value
            return headers

        return None

    # get reference to original method
    original_request = getattr(AsyncAPIClient, "request")
    if original_request is None:
        raise RuntimeError("Couldn't find 'request' method on AsyncAPIClient")

    @wraps(original_request)
    async def patched_request(
        self: AsyncAPIClient,
        cast_to: Type[ResponseT],
        options: FinalRequestOptions,
        *,
        stream: bool = False,
        stream_cls: type[_AsyncStreamT] | None = None,
    ) -> Any:
        # we have patched the underlying request method so now need to figure out when to
        # patch and when to stand down
        config = _patch_config.get()
        if (
            # enabled for this coroutine
            config.enabled
            # messages request
            and options.url in ["/v1/messages", "/v1/messages?beta=true"]
        ):
            # must also be an explicit request for an inspect model
            json_data = cast(dict[str, Any], options.json_data)
            if targets_inspect_model(json_data):
                if stream:
                    raise_stream_error()

                is_beta = "beta" in options.url
                return await inspect_anthropic_api_request(
                    json_data,
                    filter_bridge_headers(request_headers(options)),
                    config.web_search,
                    config.code_execution,
                    config.bridge,
                    beta=is_beta,
                )

        # otherwise just delegate
        return await original_request(
            self,
            cast_to,
            options,
            stream=stream,
            stream_cls=stream_cls,
        )

    setattr(AsyncAPIClient, "request", patched_request)


def init_google_request_patch() -> None:
    # don't patch if no google genai
    if not importlib.util.find_spec("google.genai"):
        return

    from google.genai._api_client import BaseApiClient
    from google.genai.types import HttpResponse as SdkHttpResponse

    # get reference to original method
    original_async_request = getattr(BaseApiClient, "async_request")
    if original_async_request is None:
        raise RuntimeError("Couldn't find 'async_request' method on BaseApiClient")

    @wraps(original_async_request)
    async def patched_async_request(
        self: BaseApiClient,
        http_method: str,
        path: str,
        request_dict: dict[str, object],
        http_options: Any = None,
    ) -> SdkHttpResponse:
        config = _patch_config.get()
        if config.enabled and ":generateContent" in path:
            model_name = _google_api_model_name(path)
            if model_name and targets_inspect_model({"model": model_name}):
                if ":streamGenerateContent" in path:
                    raise_stream_error()

                response = await inspect_google_api_request(
                    cast(dict[str, Any], request_dict),
                    config.web_search,
                    config.code_execution,
                    config.bridge,
                )
                import json

                return SdkHttpResponse(headers={}, body=json.dumps(response))

        # otherwise just delegate
        result: SdkHttpResponse = await original_async_request(
            self, http_method, path, request_dict, http_options
        )
        return result

    setattr(BaseApiClient, "async_request", patched_async_request)


def _google_api_model_name(path: str) -> str | None:
    """Extract model name from Google API path like 'models/inspect:generateContent'."""
    match = re.search(r"models/([^/:]+)", path)
    return match.group(1) if match else None


def targets_inspect_model(json_data: dict[str, Any]) -> bool:
    model_name = str(json_data["model"])
    return re.match(r"^inspect/?", model_name) is not None


def raise_stream_error() -> None:
    raise RuntimeError("Streaming not currently supported for agent_bridge()")


@agent
def bridge(
    agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> Agent:
    """Bridge an external agent into an Inspect Agent.

    ::: callout-note
    Note that this function is deprecated in favor of the `agent_bridge()`
    function. If you are creating a new agent bridge we recommend you use this function rather than `bridge()`.

    If you do choose to use the `bridge()` function, these [examples](https://github.com/UKGovernmentBEIS/inspect_ai/tree/b4670e798dc8d9ff379d4da4ef469be2468d916f/examples/bridge) demostrate its basic usage.
    :::

    Args:
      agent: Callable which takes a sample `dict` and returns a result `dict`.

    Returns:
      Inspect agent.
    """
    validate_openai_client("Agent bridge()")

    from openai.types.chat import ChatCompletionMessageParam

    class BridgeInput(BaseModel):
        messages: list[ChatCompletionMessageParam]

        # here for backward compatibilty w/ previous bridge
        # (we may choose to add this to AgentState at some point)
        metadata: dict[str, Any]

        # temporarily here for backward compatibility w/ previous bridge
        input: list[ChatCompletionMessageParam]

    class BridgeResult(BaseModel):
        output: str
        messages: list[ChatCompletionMessageParam] | None = Field(default=None)

    result_schema = BridgeResult.model_json_schema()
    result_validator = Draft7Validator(result_schema)

    # validate that the agent is an async function
    if not is_callable_coroutine(agent):
        raise TypeError(f"'{agent.__name__}' is not declared as an async callable.")

    async def execute(state: AgentState) -> AgentState:
        # create input (use standard gpt-4 message encoding -- i.e. no 'developer' messages)
        sample = sample_active()
        metadata = (sample.sample.metadata if sample is not None else None) or {}
        messages = await messages_to_openai(state.messages)
        input = BridgeInput(messages=messages, metadata=metadata, input=messages)

        # run target function with patch applied
        async with agent_bridge():
            # call the function
            result_dict = await agent(input.model_dump())
            try:
                result = BridgeResult.model_validate(result_dict)
            except ValidationError:
                # if we fail to validate provide a better human readable error
                errors = list(result_validator.iter_errors(result_dict))
                message = "\n".join(
                    ["Result returned from bridged solver is not valid:"]
                    + [f" - {error.message}" for error in errors]
                    + ["", to_json(result_dict, indent=2).decode()]
                )
                raise ValueError(message)

        # update and return state
        state.output = ModelOutput.from_content(
            model=get_model().name, content=result.output
        )
        if result.messages is not None:
            state.messages = await messages_from_openai(
                result.messages, state.output.model
            )

        return state

    return execute
