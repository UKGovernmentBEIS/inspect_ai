"""Capabilities a bridged client may reach for are granted by the scaffold, not claimed.

A sandboxed agent that names a native tool in a request would otherwise obtain web
access through the model provider even when its sandbox has no network egress, so
`sandbox_agent_bridge()` withholds those tools unless the evaluation grants them.
In-process `agent_bridge()` stays permissive: that scaffold already runs with the
host's network and filesystem, so there is no boundary to defend.

Request fields that change billing, provider-side storage or context truncation,
and the options of declared provider tools, are the eval's on both bridges.
"""

from typing import Any, Awaitable, Callable, Iterator, cast

import pytest
from openai import AsyncOpenAI
from test_helpers.utils import (
    skip_if_no_anthropic_package,
    skip_if_no_openai_package,
)

from inspect_ai._util.content import ContentAudio, ContentDocument, ContentImage
from inspect_ai.agent import agent_bridge
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge import util as bridge_util
from inspect_ai.agent._bridge._errors import PROVIDER_ERROR_KEY, BridgePolicyError
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.anthropic_api_impl import tools_from_anthropic_tools
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.responses_impl import (
    tool_from_responses_tool,
    tools_from_responses_tool,
)
from inspect_ai.agent._bridge.sandbox.service import (
    _forward_provider_errors,
    generate_anthropic,
    generate_completions,
    generate_google,
    generate_responses,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    relax_tool_choice_for_withheld,
    resolve_bridge_code_execution,
    resolve_bridge_web_search,
    validate_bridge_media,
)
from inspect_ai.model import GenerateConfig, Model, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._generate_config import active_generate_config_context_var
from inspect_ai.model._model import (
    GenerateFilter,
    active_model_context_var,
    init_active_model,
)
from inspect_ai.tool import (
    CodeExecutionProviders,
    Tool,
    ToolChoice,
    ToolFunction,
    ToolInfo,
    WebSearchProviders,
)
from inspect_ai.tool._tool_util import tool_to_tool_info
from inspect_ai.util import media_resolver

WEB_SEARCH_PARAM = cast(Any, {"type": "web_search"})
MCP_PARAM = cast(
    Any,
    {
        "type": "mcp",
        "server_label": "elsewhere",
        "server_url": "https://elsewhere.example/mcp",
        "headers": None,
        "allowed_tools": None,
    },
)
ANTHROPIC_WEB_SEARCH = cast(Any, {"type": "web_search_20250305", "name": "web_search"})
CLIENT_SEARCH_VERSION = {"type": "web_search_20250305"}
ANTHROPIC_MCP_SERVER = cast(
    Any, {"type": "url", "name": "elsewhere", "url": "https://elsewhere.example/mcp"}
)


@pytest.fixture(autouse=True)
def _eval_model() -> Iterator[None]:
    """Make mockllm/model the eval's model, as it is inside a running eval.

    The sandbox bridge serves a model name it does not recognise with the eval's
    model, so the requests below name it. init_active_model() sets process-wide
    contextvars; reset them so they don't leak into other tests.
    """
    model_token = active_model_context_var.set(active_model_context_var.get(None))
    config_token = active_generate_config_context_var.set(
        active_generate_config_context_var.get()
    )
    init_active_model(get_model("mockllm/model"), GenerateConfig())
    try:
        yield
    finally:
        active_model_context_var.reset(model_token)
        active_generate_config_context_var.reset(config_token)


def sandbox_bridge(
    filter: GenerateFilter | None = None, **kwargs: Any
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=filter,
        retry_refusals=None,
        compaction=None,
        port=3000,
        model=None,
        **kwargs,
    )


def in_process_bridge(
    filter: GenerateFilter | None = None, **kwargs: Any
) -> AgentBridge:
    return AgentBridge(AgentState(messages=[]), filter=filter, **kwargs)


BridgeFactory = Callable[..., AgentBridge]
BOTH_BRIDGES = pytest.mark.parametrize(
    "make_bridge", [sandbox_bridge, in_process_bridge], ids=["sandbox", "in-process"]
)


# --- resolution -------------------------------------------------------------


@pytest.mark.parametrize(
    "value,granted",
    [
        (None, False),
        (False, False),
        (True, True),
        # an *empty* config means "the usual providers", which is how a caller
        # grants without pinning a provider list
        (WebSearchProviders(), True),
        ({"openai": True}, True),
        # ...whereas a config that enables nothing is a withhold, so that turning
        # every provider off cannot leave search reachable via one not named
        (
            WebSearchProviders(
                openai=False,
                anthropic=False,
                grok=False,
                gemini=False,
                mistral=False,
                perplexity=False,
            ),
            False,
        ),
    ],
)
def test_sandbox_web_search_resolution(value: Any, granted: bool) -> None:
    resolved = resolve_bridge_web_search(value, default_grant=False)
    assert (resolved is not None) is granted


def test_in_process_web_search_defaults_to_granted() -> None:
    assert resolve_bridge_web_search(None, default_grant=True) is not None


def test_sandbox_and_in_process_grants_are_the_same_provider_set() -> None:
    assert resolve_bridge_web_search(True, default_grant=False) == (
        resolve_bridge_web_search(None, default_grant=True)
    )


@pytest.mark.parametrize(
    "value,granted", [(None, False), (False, False), (True, True), ({}, True)]
)
def test_sandbox_code_execution_resolution(value: Any, granted: bool) -> None:
    assert (resolve_bridge_code_execution(value, default_grant=False) is not None) is (
        granted
    )


# --- tool mapping -----------------------------------------------------------


def test_responses_native_tools_withheld_by_default() -> None:
    web_search = resolve_bridge_web_search(None, default_grant=False)
    code_execution = resolve_bridge_code_execution(None, default_grant=False)

    assert (
        tools_from_responses_tool(
            WEB_SEARCH_PARAM, web_search, code_execution, allow_remote_mcp=False
        )
        == []
    )
    assert (
        tools_from_responses_tool(
            MCP_PARAM, web_search, code_execution, allow_remote_mcp=False
        )
        == []
    )


def test_responses_native_tools_honored_when_granted() -> None:
    web_search = resolve_bridge_web_search(True, default_grant=False)
    code_execution = resolve_bridge_code_execution(True, default_grant=False)

    assert (
        len(
            tools_from_responses_tool(
                WEB_SEARCH_PARAM, web_search, code_execution, allow_remote_mcp=True
            )
        )
        == 1
    )
    mcp = tools_from_responses_tool(
        MCP_PARAM, web_search, code_execution, allow_remote_mcp=True
    )
    assert [getattr(t, "name", None) for t in mcp] == ["mcp_server_elsewhere"]


def test_responses_function_tools_are_never_withheld() -> None:
    """Function tools run inside the sandbox, so they are always forwarded."""
    tools = tools_from_responses_tool(
        cast(
            Any,
            {
                "type": "function",
                "name": "grep",
                "description": "search files",
                "parameters": {"type": "object", "properties": {}},
                "strict": False,
            },
        ),
        None,
        None,
        allow_remote_mcp=False,
    )
    assert [getattr(t, "name", None) for t in tools] == ["grep"]


def test_anthropic_native_tools_withheld_by_default() -> None:
    assert (
        tools_from_anthropic_tools(
            [ANTHROPIC_WEB_SEARCH], [ANTHROPIC_MCP_SERVER], None, None, False
        )
        == []
    )


def test_anthropic_native_tools_honored_when_granted() -> None:
    tools = tools_from_anthropic_tools(
        [ANTHROPIC_WEB_SEARCH],
        [ANTHROPIC_MCP_SERVER],
        resolve_bridge_web_search(True, default_grant=False),
        None,
        True,
    )
    assert len(tools) == 2
    assert "mcp_server_elsewhere" in [getattr(t, "name", None) for t in tools]


@pytest.mark.parametrize("granted", [False, True])
def test_anthropic_web_fetch_alone_grants_nothing(granted: bool) -> None:
    """web_fetch rides a granted web_search; alone it maps to nothing either way.

    Withheld, it must not re-enable search. Granted, mapping it to `web_search`
    would hand the client the search capability it did not declare.
    """
    assert (
        tools_from_anthropic_tools(
            [cast(Any, {"type": "web_fetch_20250910", "name": "web_fetch"})],
            None,
            resolve_bridge_web_search(granted, default_grant=False),
            None,
            False,
        )
        == []
    )


# --- tool choice ------------------------------------------------------------


def test_tool_choice_forcing_a_withheld_tool_relaxes_to_auto() -> None:
    """A forced choice at a missing tool makes the model layer purge *all* tools."""
    tools = tools_from_responses_tool(
        cast(
            Any,
            {
                "type": "function",
                "name": "grep",
                "description": "search files",
                "parameters": {"type": "object", "properties": {}},
                "strict": False,
            },
        ),
        None,
        None,
        allow_remote_mcp=False,
    )
    assert (
        relax_tool_choice_for_withheld(ToolFunction(name="web_search"), tools) == "auto"
    )


@pytest.mark.parametrize("choice", [None, "auto", "any", "none", ToolFunction("grep")])
def test_tool_choice_otherwise_passes_through(choice: Any) -> None:
    tools = [ToolInfo(name="grep", description="search files")]
    assert relax_tool_choice_for_withheld(choice, tools) == choice


# --- media ------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "http://elsewhere.example/x.png",
        "https://elsewhere.example/x.png",
        "/etc/hosts",
        "s3://bucket/key.png",
        "file:///etc/hosts",
    ],
)
async def test_sandbox_media_must_be_inline(uri: str) -> None:
    bridge = sandbox_bridge()
    messages = [ChatMessageUser(content=[ContentImage(image=uri)])]
    with pytest.raises(BridgePolicyError) as info:
        await validate_bridge_media(bridge, messages)
    assert info.value.status_code == 400
    assert uri not in str(info.value)
    assert "message index 0" in str(info.value)
    assert "content index 0" in str(info.value)


async def test_sandbox_media_covers_non_uri_locators() -> None:
    """A bare document/audio value is a *locator*, not a payload.

    `ContentDocument.document` and `ContentAudio.audio` reach the provider through
    `file_as_data`, which opens anything that isn't a `data:` URI off the host
    filesystem — so an Anthropic `source={"type": "text"}` document carrying
    "/etc/hosts" inlines that file into the request. The guard has to cover these
    even though the wire shape looks inline.
    """
    for content in (
        ContentDocument(document="/etc/hosts", mime_type="text/plain"),
        ContentAudio(audio="/etc/hosts", format="mp3"),
    ):
        with pytest.raises(BridgePolicyError):
            await validate_bridge_media(
                sandbox_bridge(), [ChatMessageUser(content=[content])]
            )


async def test_sandbox_media_allows_data_uri() -> None:
    messages = [
        ChatMessageUser(content=[ContentImage(image="data:image/png;base64,AAAA")])
    ]
    await validate_bridge_media(sandbox_bridge(), messages)


async def test_sandbox_media_covers_documents() -> None:
    messages = [
        ChatMessageUser(content=[ContentDocument(document="https://elsewhere/x.pdf")])
    ]
    with pytest.raises(BridgePolicyError):
        await validate_bridge_media(sandbox_bridge(), messages)


async def test_default_bridge_media_is_inline_only() -> None:
    messages = [ChatMessageUser(content=[ContentImage(image="test://bucket/x.png")])]

    with pytest.raises(BridgePolicyError):
        await validate_bridge_media(AgentBridge(AgentState(messages=[])), messages)


async def test_in_process_bridge_factory_grants_remote_media() -> None:
    async with agent_bridge(AgentState(messages=[])) as bridge:
        assert bridge.allow_remote_media is True


async def test_explicitly_granted_media_is_materialized() -> None:
    async def resolver(uri: str) -> str:
        assert uri == "test://bucket/x.png"
        return "data:image/png;base64,AAAA"

    messages = [ChatMessageUser(content=[ContentImage(image="test://bucket/x.png")])]
    with media_resolver("test", resolver):
        await validate_bridge_media(
            AgentBridge(AgentState(messages=[]), allow_remote_media=True), messages
        )

    content = messages[0].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    assert image.image == "data:image/png;base64,AAAA"


async def test_sandbox_media_can_be_re_enabled() -> None:
    async def resolver(uri: str) -> str:
        assert uri == "test://bucket/x.png"
        return "data:image/png;base64,AAAA"

    messages = [ChatMessageUser(content=[ContentImage(image="test://bucket/x.png")])]
    with media_resolver("test", resolver):
        await validate_bridge_media(sandbox_bridge(allow_remote_media=True), messages)

    content = messages[0].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    assert image.image == "data:image/png;base64,AAAA"


async def test_bridge_materialization_updates_document_mime_type() -> None:
    async def resolver(uri: str) -> str:
        assert uri == "test://bucket/document"
        return "data:application/pdf;base64,AAAA"

    document = ContentDocument(document="test://bucket/document")
    messages = [ChatMessageUser(content=[document])]
    with media_resolver("test", resolver):
        await validate_bridge_media(
            AgentBridge(AgentState(messages=[]), allow_remote_media=True), messages
        )

    assert document.document == "data:application/pdf;base64,AAAA"
    assert document.mime_type == "application/pdf"


# --- request settings -------------------------------------------------------

EVAL_GOVERNED_RESPONSES_FIELDS: dict[str, Any] = {
    "service_tier": "priority",
    "store": True,
    "truncation": "auto",
}
FORWARDED_RESPONSES_FIELDS: dict[str, Any] = {
    "metadata": {"run": "1"},
    "safety_identifier": "agent",
    "prompt_cache_key": "key",
    "prompt_cache_retention": "24h",
    "max_tool_calls": 3,
}


def capture_config(captured: list[GenerateConfig]) -> GenerateFilter:
    """A bridge filter that records the config the provider would get, and answers."""

    async def capture(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        captured.append(config)
        return ModelOutput.from_content(model="mockllm/model", content="ok")

    return capture


def responses_request(**fields: Any) -> dict[str, Any]:
    return {"model": "inspect/mockllm/model", "input": "hi", **fields}


def anthropic_request(**fields: Any) -> dict[str, Any]:
    return {
        "model": "inspect/mockllm/model",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
        **fields,
    }


@pytest.fixture
def bridge_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(
        bridge_util.logger,
        "warning",
        lambda message, *args, **kwargs: messages.append(message),
    )
    return messages


def warned_fields(warnings: list[str]) -> list[str]:
    return [
        field
        for warning in warnings
        for field in ("service_tier", "store", "truncation")
        if f"agent's {field}=" in warning
    ]


@BOTH_BRIDGES
async def test_responses_settings_follow_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    captured: list[GenerateConfig] = []
    bridge = make_bridge(filter=capture_config(captured))

    await inspect_responses_api_request(
        responses_request(
            **EVAL_GOVERNED_RESPONSES_FIELDS, **FORWARDED_RESPONSES_FIELDS
        ),
        None,
        None,
        None,
        bridge,
    )

    assert captured[0].extra_body == FORWARDED_RESPONSES_FIELDS
    assert sorted(warned_fields(bridge_warnings)) == sorted(
        EVAL_GOVERNED_RESPONSES_FIELDS
    )
    assert "the eval's configuration governs service_tier" in bridge_warnings[0]


@BOTH_BRIDGES
async def test_warns_once_per_field_per_bridge(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    captured: list[GenerateConfig] = []
    bridge = make_bridge(filter=capture_config(captured))
    request = responses_request(service_tier="priority")

    await inspect_responses_api_request(request, None, None, None, bridge)
    await inspect_responses_api_request(request, None, None, None, bridge)
    assert warned_fields(bridge_warnings) == ["service_tier"]

    other = make_bridge(filter=capture_config(captured))
    await inspect_responses_api_request(request, None, None, None, other)
    assert warned_fields(bridge_warnings) == ["service_tier", "service_tier"]
    assert all(config.extra_body is None for config in captured)


@BOTH_BRIDGES
async def test_no_warning_when_client_matches_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    captured: list[GenerateConfig] = []
    bridge = make_bridge(filter=capture_config(captured))

    await inspect_responses_api_request(
        responses_request(service_tier="auto", store=False, truncation="disabled"),
        None,
        None,
        None,
        bridge,
    )

    assert captured[0].extra_body is None
    assert bridge_warnings == []


@BOTH_BRIDGES
async def test_eval_config_governs_withheld_settings(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    eval_extra_body = {"service_tier": "flex", "store": True, "truncation": "auto"}
    model = get_model(
        "mockllm/model", config=GenerateConfig(extra_body=eval_extra_body)
    )
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    await inspect_responses_api_request(
        {"model": "eval-model", "input": "hi", "service_tier": "flex", "store": False},
        None,
        None,
        None,
        bridge,
    )

    assert captured[0].extra_body == eval_extra_body
    assert warned_fields(bridge_warnings) == ["store"]


@skip_if_no_openai_package
@BOTH_BRIDGES
async def test_openai_model_args_govern_withheld_settings(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    model = get_model(
        "openai/gpt-5", api_key="test-key", service_tier="flex", responses_store=True
    )
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    request = {"model": "eval-model", "input": "hi", "service_tier": "flex"}
    await inspect_responses_api_request(
        {**request, "store": True}, None, None, None, bridge
    )
    assert bridge_warnings == []

    await inspect_responses_api_request(
        {**request, "service_tier": "priority"}, None, None, None, bridge
    )
    assert warned_fields(bridge_warnings) == ["service_tier"]
    assert all(config.extra_body is None for config in captured)


@skip_if_no_openai_package
@BOTH_BRIDGES
async def test_compatible_responses_store_arg_governs_store(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    model = get_model(
        "openai-api/compat/model",
        base_url="http://localhost:9/v1",
        api_key="test-key",
        responses_api=True,
        responses_store=True,
    )
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    request = {"model": "eval-model", "input": "hi"}
    await inspect_responses_api_request(
        {**request, "store": True}, None, None, None, bridge
    )
    assert bridge_warnings == []

    await inspect_responses_api_request(
        {**request, "store": False}, None, None, None, bridge
    )
    assert warned_fields(bridge_warnings) == ["store"]
    assert all(config.extra_body is None for config in captured)


@skip_if_no_anthropic_package
@BOTH_BRIDGES
async def test_anthropic_extra_body_arg_governs_service_tier(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    model = get_model(
        "anthropic/claude-sonnet-4-5",
        api_key="test-key",
        extra_body={"service_tier": "standard_only"},
    )
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    await inspect_anthropic_api_request(
        {**anthropic_request(service_tier="standard_only"), "model": "eval-model"},
        None,
        None,
        None,
        bridge,
    )
    assert bridge_warnings == []

    await inspect_anthropic_api_request(
        {**anthropic_request(service_tier="auto"), "model": "eval-model"},
        None,
        None,
        None,
        bridge,
    )
    assert warned_fields(bridge_warnings) == ["service_tier"]
    assert all(config.extra_body is None for config in captured)


@BOTH_BRIDGES
async def test_anthropic_service_tier_follows_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    captured: list[GenerateConfig] = []
    bridge = make_bridge(filter=capture_config(captured))

    await inspect_anthropic_api_request(
        anthropic_request(service_tier="standard_only", metadata={"user_id": "u"}),
        None,
        None,
        None,
        bridge,
    )

    assert captured[0].extra_body == {"metadata": {"user_id": "u"}}
    assert warned_fields(bridge_warnings) == ["service_tier"]


async def test_sandbox_refuses_previous_response_id() -> None:
    captured: list[GenerateConfig] = []
    bridge = sandbox_bridge(filter=capture_config(captured))
    generate = _forward_provider_errors(generate_responses(None, None, bridge), bridge)

    result = await generate(responses_request(previous_response_id="resp_elsewhere"))

    error = cast(dict[str, Any], result[PROVIDER_ERROR_KEY])
    assert error["status"] == 400
    assert "previous_response_id" in error["message"]
    assert captured == []


@BOTH_BRIDGES
async def test_accepts_null_previous_response_id(make_bridge: BridgeFactory) -> None:
    captured: list[GenerateConfig] = []
    bridge = make_bridge(filter=capture_config(captured))

    await inspect_responses_api_request(
        responses_request(previous_response_id=None), None, None, None, bridge
    )

    assert len(captured) == 1


async def test_in_process_bridge_withholds_settings_and_forwards_headers(
    bridge_warnings: list[str],
) -> None:
    captured: list[GenerateConfig] = []
    headers = {"openai-organization": "org-agent"}
    async with agent_bridge(
        AgentState(messages=[]), filter=capture_config(captured)
    ) as bridge:
        await inspect_responses_api_request(
            responses_request(
                **EVAL_GOVERNED_RESPONSES_FIELDS, **FORWARDED_RESPONSES_FIELDS
            ),
            headers,
            None,
            None,
            bridge,
        )
        await inspect_anthropic_api_request(
            anthropic_request(service_tier="standard_only", metadata={"user_id": "u"}),
            headers,
            None,
            None,
            bridge,
        )

    assert captured[0].extra_body == FORWARDED_RESPONSES_FIELDS
    assert captured[1].extra_body == {"metadata": {"user_id": "u"}}
    assert [config.extra_headers for config in captured] == [headers, headers]
    assert sorted(warned_fields(bridge_warnings)) == sorted(
        EVAL_GOVERNED_RESPONSES_FIELDS
    )


async def test_in_process_client_gets_policy_error() -> None:
    """The patched SDK call raises the bridge's policy error to the agent."""
    captured: list[GenerateConfig] = []
    async with agent_bridge(AgentState(messages=[]), filter=capture_config(captured)):
        client = AsyncOpenAI(api_key="test-key")
        with pytest.raises(BridgePolicyError, match="previous_response_id") as info:
            await client.responses.create(
                model="inspect/mockllm/model",
                input="hi",
                previous_response_id="resp_elsewhere",
            )
    assert info.value.status_code == 400
    assert captured == []


# --- provider tool options -------------------------------------------------


def tool_options(tools: list[ToolInfo | Tool]) -> dict[str, Any]:
    assert len(tools) == 1
    tool = tools[0]
    info = tool if isinstance(tool, ToolInfo) else tool_to_tool_info(tool)
    return info.options or {}


def test_observer_converts_declarations_without_a_bridge(
    bridge_warnings: list[str],
) -> None:
    """Callers that only record declarations (e.g. inspect_scout) pass no bridge."""
    function = cast(
        Any,
        {
            "type": "function",
            "name": "grep",
            "description": "search files",
            "parameters": {"type": "object", "properties": {}},
            "strict": False,
        },
    )
    tool = tool_from_responses_tool(function, {}, {}, allow_remote_mcp=True)
    assert isinstance(tool, ToolInfo) and tool.name == "grep"

    search = tools_from_responses_tool(
        cast(Any, {"type": "web_search", **CLIENT_SEARCH_OPTIONS}),
        WebSearchProviders(openai={}),
        {},
        allow_remote_mcp=True,
    )
    assert tool_options(search)["openai"] == {"search_context_size": "high"}

    anthropic_tools = tools_from_anthropic_tools(
        [
            cast(
                Any,
                {
                    "name": "grep",
                    "description": "search files",
                    "input_schema": {"type": "object", "properties": {}},
                },
            ),
            ANTHROPIC_CLIENT_SEARCH,
        ],
        None,
        {},
        {},
        allow_remote_mcp=True,
    )
    assert [getattr(t, "name", None) for t in anthropic_tools][0] == "grep"
    assert bridge_warnings == []


CLIENT_CONTAINER = {"type": "auto", "file_ids": ["file-from-agent"]}


def code_interpreter_param(container: Any) -> Any:
    return cast(Any, {"type": "code_interpreter", "container": container})


@BOTH_BRIDGES
def test_code_interpreter_container_follows_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    code_execution = resolve_bridge_code_execution(True, default_grant=False)
    bridge = make_bridge()

    tools = tools_from_responses_tool(
        code_interpreter_param(CLIENT_CONTAINER),
        None,
        code_execution,
        allow_remote_mcp=False,
        bridge=bridge,
    )

    assert tool_options(tools)["providers"]["openai"] == {}
    assert code_execution == resolve_bridge_code_execution(True, default_grant=False)
    assert len(bridge_warnings) == 1
    assert "agent's code_interpreter container=" in bridge_warnings[0]


@BOTH_BRIDGES
def test_author_container_wins(
    make_bridge: BridgeFactory, bridge_warnings: list[str]
) -> None:
    author = {"type": "auto", "memory_limit": "4g"}
    code_execution = CodeExecutionProviders(openai={"container": author})
    bridge = make_bridge()

    tools = tools_from_responses_tool(
        code_interpreter_param(CLIENT_CONTAINER),
        None,
        code_execution,
        allow_remote_mcp=False,
        bridge=bridge,
    )
    assert tool_options(tools)["providers"]["openai"] == {"container": author}
    assert len(bridge_warnings) == 1

    tools_from_responses_tool(
        code_interpreter_param(author),
        None,
        code_execution,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )
    assert len(bridge_warnings) == 1


@BOTH_BRIDGES
def test_default_container_does_not_warn(
    make_bridge: BridgeFactory, bridge_warnings: list[str]
) -> None:
    tools_from_responses_tool(
        code_interpreter_param({"type": "auto"}),
        None,
        resolve_bridge_code_execution(True, default_grant=False),
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )
    assert bridge_warnings == []


@BOTH_BRIDGES
def test_code_interpreter_still_withheld_without_grant(
    make_bridge: BridgeFactory,
) -> None:
    assert (
        tools_from_responses_tool(
            code_interpreter_param(CLIENT_CONTAINER),
            None,
            None,
            allow_remote_mcp=False,
            bridge=make_bridge(),
        )
        == []
    )


CLIENT_SEARCH_OPTIONS: dict[str, Any] = {
    "search_context_size": "high",
    "filters": {"allowed_domains": ["agent.example"]},
}


@BOTH_BRIDGES
def test_responses_web_search_options_follow_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    author = WebSearchProviders(openai={"filters": {"allowed_domains": ["eval.org"]}})
    bridge = make_bridge()

    tools = tools_from_responses_tool(
        cast(Any, {"type": "web_search", **CLIENT_SEARCH_OPTIONS}),
        author,
        None,
        allow_remote_mcp=False,
        bridge=bridge,
    )

    # the client's context size applies (the eval left it unset); its filters do not
    assert tool_options(tools)["openai"] == {
        "filters": {"allowed_domains": ["eval.org"]},
        "search_context_size": "high",
    }
    assert len(bridge_warnings) == 1
    assert "agent's web_search options={'filters'" in bridge_warnings[0]


@BOTH_BRIDGES
def test_responses_web_search_default_options_follow_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    web_search = resolve_bridge_web_search(True, default_grant=False)
    assert web_search is not None

    tools = tools_from_responses_tool(
        cast(Any, {"type": "web_search", **CLIENT_SEARCH_OPTIONS}),
        web_search,
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )
    assert tool_options(tools)["openai"] == {"search_context_size": "high"}
    assert len(bridge_warnings) == 1

    tools_from_responses_tool(
        WEB_SEARCH_PARAM,
        web_search,
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )
    assert len(bridge_warnings) == 1


@BOTH_BRIDGES
@pytest.mark.parametrize(
    "eval_options,expected,warned",
    [
        (
            {},
            {
                "search_context_size": "low",
                "user_location": {"type": "approximate", "city": "Leeds"},
            },
            False,
        ),
        (
            {"search_context_size": "high"},
            {
                "search_context_size": "high",
                "user_location": {"type": "approximate", "city": "Leeds"},
            },
            True,
        ),
    ],
    ids=["eval-unset", "eval-set"],
)
def test_responses_web_search_location_and_context_size_set_by_client(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    eval_options: dict[str, Any],
    expected: dict[str, Any],
    warned: bool,
) -> None:
    """The client may set them where the eval leaves them unset; the eval's win."""
    tools = tools_from_responses_tool(
        cast(
            Any,
            {
                "type": "web_search",
                "search_context_size": "low",
                "user_location": {"type": "approximate", "city": "Leeds"},
            },
        ),
        WebSearchProviders(openai=eval_options),
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["openai"] == expected
    assert (len(bridge_warnings) == 1) is warned


@BOTH_BRIDGES
@pytest.mark.parametrize(
    "eval_options,expected,warned",
    [
        ({}, {"user_location": {"type": "approximate", "city": "Leeds"}}, False),
        (
            {"user_location": {"type": "approximate", "city": "York"}},
            {"user_location": {"type": "approximate", "city": "York"}},
            True,
        ),
    ],
    ids=["eval-unset", "eval-set"],
)
def test_anthropic_web_search_location_set_by_client(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    eval_options: dict[str, Any],
    expected: dict[str, Any],
    warned: bool,
) -> None:
    tools = tools_from_anthropic_tools(
        [
            cast(
                Any,
                {
                    **ANTHROPIC_WEB_SEARCH,
                    "user_location": {"type": "approximate", "city": "Leeds"},
                },
            )
        ],
        None,
        WebSearchProviders(anthropic=eval_options),
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["anthropic"] == {**CLIENT_SEARCH_VERSION, **expected}
    assert (len(bridge_warnings) == 1) is warned


ANTHROPIC_CLIENT_SEARCH = cast(
    Any,
    {**ANTHROPIC_WEB_SEARCH, "max_uses": 50, "allowed_domains": ["agent.example"]},
)


@BOTH_BRIDGES
def test_anthropic_web_search_options_follow_eval(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    author = WebSearchProviders(anthropic={"blocked_domains": ["blocked.example"]})

    tools = tools_from_anthropic_tools(
        [ANTHROPIC_CLIENT_SEARCH],
        None,
        author,
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    # the client's version and lower search cap apply; its allowed domains do not
    assert tool_options(tools)["anthropic"] == {
        **CLIENT_SEARCH_VERSION,
        "blocked_domains": ["blocked.example"],
        "max_uses": 50,
    }
    assert len(bridge_warnings) == 1
    assert "agent's web_search options={'allowed_domains'" in bridge_warnings[0]

    tools_from_anthropic_tools(
        [ANTHROPIC_WEB_SEARCH],
        None,
        author,
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )
    assert len(bridge_warnings) == 1


@pytest.mark.parametrize(
    "eval_cap,client_cap,expected,warned",
    [(5, 50, 5, True), (5, 3, 3, False), (None, 8, 8, False)],
)
@BOTH_BRIDGES
def test_anthropic_max_uses_may_only_narrow(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    eval_cap: int | None,
    client_cap: int,
    expected: int,
    warned: bool,
) -> None:
    author = WebSearchProviders(
        anthropic={} if eval_cap is None else {"max_uses": eval_cap}
    )

    tools = tools_from_anthropic_tools(
        [cast(Any, {**ANTHROPIC_WEB_SEARCH, "max_uses": client_cap})],
        None,
        author,
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["anthropic"] == {
        **CLIENT_SEARCH_VERSION,
        "max_uses": expected,
    }
    assert (len(bridge_warnings) == 1) is warned


@pytest.mark.parametrize(
    "eval_options,client_type,expected,warned",
    [
        ({}, "web_search_20250305", {"type": "web_search_20250305"}, False),
        ({}, "web_search_20260209", {"type": "web_search_20260209"}, False),
        ({}, "web_search_20990101", {}, False),
        (
            {"type": "web_search_20260209"},
            "web_search_20250305",
            {"type": "web_search_20260209"},
            True,
        ),
    ],
    ids=["eval-unset", "eval-unset-latest", "unsupported", "eval-set"],
)
@BOTH_BRIDGES
def test_anthropic_web_search_version_set_by_client(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    eval_options: dict[str, Any],
    client_type: str,
    expected: dict[str, Any],
    warned: bool,
) -> None:
    """The client's supported version applies when the eval sets none."""
    tools = tools_from_anthropic_tools(
        [cast(Any, {"type": client_type, "name": "web_search"})],
        None,
        WebSearchProviders(anthropic=eval_options),
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["anthropic"] == expected
    assert (len(bridge_warnings) == 1) is warned
    if warned:
        assert "agent's web_search options={'type'" in bridge_warnings[0]


@BOTH_BRIDGES
def test_anthropic_client_options_apply_when_eval_enables_without_options(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    """`anthropic=True` sets no options, so the client's apply as under `{}`."""
    location = {"type": "approximate", "city": "Leeds"}
    client_search = cast(
        Any, {**ANTHROPIC_WEB_SEARCH, "max_uses": 8, "user_location": location}
    )

    tools = tools_from_anthropic_tools(
        [client_search],
        None,
        WebSearchProviders(anthropic=True),
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["anthropic"] == {
        **CLIENT_SEARCH_VERSION,
        "max_uses": 8,
        "user_location": location,
    }
    assert bridge_warnings == []


@pytest.mark.parametrize(
    "eval_options,client_access,expected,warned",
    [
        ({}, False, {"external_web_access": False}, False),
        ({}, True, {}, False),
        ({"external_web_access": False}, True, {"external_web_access": False}, True),
    ],
)
@BOTH_BRIDGES
def test_openai_live_web_access_may_only_narrow(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    eval_options: dict[str, Any],
    client_access: bool,
    expected: dict[str, Any],
    warned: bool,
) -> None:
    tools = tools_from_responses_tool(
        cast(Any, {"type": "web_search", "external_web_access": client_access}),
        WebSearchProviders(openai=eval_options),
        None,
        allow_remote_mcp=False,
        bridge=make_bridge(),
    )

    assert tool_options(tools)["openai"] == expected
    assert (len(bridge_warnings) == 1) is warned


@BOTH_BRIDGES
async def test_request_path_applies_eval_tool_options(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
) -> None:
    captured_tools: list[list[ToolInfo]] = []

    async def capture(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        captured_tools.append(tools)
        return ModelOutput.from_content(model="mockllm/model", content="ok")

    bridge = make_bridge(filter=capture)
    await inspect_responses_api_request(
        responses_request(tools=[code_interpreter_param(CLIENT_CONTAINER)]),
        None,
        None,
        resolve_bridge_code_execution(True, default_grant=False),
        bridge,
    )
    await inspect_anthropic_api_request(
        anthropic_request(tools=[ANTHROPIC_CLIENT_SEARCH]),
        None,
        resolve_bridge_web_search(True, default_grant=False),
        None,
        bridge,
    )

    assert tool_options(list(captured_tools[0]))["providers"]["openai"] == {}
    assert tool_options(list(captured_tools[1]))["anthropic"] == {
        **CLIENT_SEARCH_VERSION,
        "max_uses": 50,
    }
    assert len(bridge_warnings) == 2


COMPUTER_PARAM: dict[str, Any] = {"type": "computer"}
NAMESPACED_COMPUTER: dict[str, Any] = {
    "type": "namespace",
    "name": "nested",
    "description": "nested",
    "tools": [COMPUTER_PARAM],
}
COMPUTER_DECLARATIONS: dict[str, dict[str, Any]] = {
    "top-level": {"input": "hi", "tools": [COMPUTER_PARAM]},
    "namespace": {"input": "hi", "tools": [NAMESPACED_COMPUTER]},
    "additional-tools-namespace": {
        "input": [
            {"type": "additional_tools", "tools": [NAMESPACED_COMPUTER]},
            {"role": "user", "content": "hi"},
        ]
    },
}


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "model_args,config",
    [
        ({"responses_store": False}, GenerateConfig()),
        ({}, GenerateConfig(extra_body={"store": False})),
    ],
    ids=["model-arg", "extra-body"],
)
@pytest.mark.parametrize("declaration", list(COMPUTER_DECLARATIONS))
async def test_sandbox_computer_tool_refused_when_eval_turns_storage_off(
    model_args: dict[str, Any], config: GenerateConfig, declaration: str
) -> None:
    model = get_model("openai/gpt-5", api_key="test-key", config=config, **model_args)
    captured: list[GenerateConfig] = []
    bridge = sandbox_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )
    generate = _forward_provider_errors(generate_responses(None, None, bridge), bridge)

    result = await generate(
        {"model": "eval-model", **COMPUTER_DECLARATIONS[declaration]}
    )

    error = cast(dict[str, Any], result[PROVIDER_ERROR_KEY])
    assert error["status"] == 400
    assert "storage" in error["message"]
    assert captured == []


@skip_if_no_openai_package
@pytest.mark.parametrize("declaration", list(COMPUTER_DECLARATIONS))
async def test_in_process_computer_tool_refused_when_eval_turns_storage_off(
    declaration: str,
) -> None:
    model = get_model("openai/gpt-5", api_key="test-key", responses_store=False)
    captured: list[GenerateConfig] = []
    bridge = in_process_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    with pytest.raises(BridgePolicyError, match="storage"):
        await inspect_responses_api_request(
            {"model": "eval-model", **COMPUTER_DECLARATIONS[declaration]},
            None,
            None,
            None,
            bridge,
        )
    assert captured == []


@skip_if_no_openai_package
@pytest.mark.parametrize("responses_store", [None, True])
@BOTH_BRIDGES
async def test_computer_tool_served_unless_storage_off(
    make_bridge: BridgeFactory,
    responses_store: bool | None,
) -> None:
    model = get_model(
        "openai/gpt-5", api_key="test-key", responses_store=responses_store
    )
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    await inspect_responses_api_request(
        {"model": "eval-model", "input": "hi", "tools": [COMPUTER_PARAM]},
        None,
        None,
        None,
        bridge,
    )
    assert len(captured) == 1


@skip_if_no_openai_package
@pytest.mark.parametrize(
    "client_store,warned", [(False, ["store"]), (True, [])], ids=["false", "true"]
)
@BOTH_BRIDGES
async def test_computer_tool_store_warning_follows_forced_storage(
    make_bridge: BridgeFactory,
    bridge_warnings: list[str],
    client_store: bool,
    warned: list[str],
) -> None:
    """With storage unset, a computer tool turns it on, so `store=True` matches."""
    model = get_model("openai/gpt-5", api_key="test-key")
    captured: list[GenerateConfig] = []
    bridge = make_bridge(
        filter=capture_config(captured), model_aliases={"eval-model": model}
    )

    await inspect_responses_api_request(
        {
            "model": "eval-model",
            "input": "hi",
            "tools": [COMPUTER_PARAM],
            "store": client_store,
        },
        None,
        None,
        None,
        bridge,
    )

    assert warned_fields(bridge_warnings) == warned
    assert len(captured) == 1


# --- headers ----------------------------------------------------------------

SandboxGenerate = Callable[
    [SandboxAgentBridge], Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
]


@pytest.mark.parametrize(
    "service_method,request_body",
    [
        (
            generate_completions,
            {
                "model": "inspect/mockllm/model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        ),
        (
            lambda bridge: generate_responses(None, None, bridge),
            responses_request(),
        ),
        (
            lambda bridge: generate_anthropic(None, None, bridge),
            anthropic_request(),
        ),
        (
            lambda bridge: generate_google(None, None, bridge),
            {
                "model": "inspect/mockllm/model",
                "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            },
        ),
    ],
    ids=["completions", "responses", "anthropic", "google"],
)
async def test_sandbox_service_sends_no_client_headers(
    service_method: SandboxGenerate, request_body: dict[str, Any]
) -> None:
    """The sandbox service gets only the request body, so no client header reaches the provider.

    The in-container proxy's side (it forwards the body alone) is pinned by
    `test_proxy_forwards_no_client_headers` in the sandbox tools tests.
    """
    captured: list[GenerateConfig] = []
    bridge = sandbox_bridge(filter=capture_config(captured))

    await service_method(bridge)(request_body)

    assert len(captured) == 1
    assert captured[0].extra_headers is None
