"""Capabilities a bridged client may reach for are granted by the scaffold, not claimed.

A sandboxed agent that names a native tool in a request would otherwise obtain web
access through the model provider even when its sandbox has no network egress, so
`sandbox_agent_bridge()` withholds those tools unless the evaluation grants them.
In-process `agent_bridge()` stays permissive: that scaffold already runs with the
host's network and filesystem, so there is no boundary to defend.
"""

from typing import Any, cast

import pytest

from inspect_ai._util.content import ContentAudio, ContentDocument, ContentImage
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.anthropic_api_impl import tools_from_anthropic_tools
from inspect_ai.agent._bridge.responses_impl import tools_from_responses_tool
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    relax_tool_choice_for_withheld,
    resolve_bridge_code_execution,
    resolve_bridge_web_search,
    validate_bridge_media,
)
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.tool import ToolFunction, ToolInfo, WebSearchProviders

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
ANTHROPIC_MCP_SERVER = cast(
    Any, {"type": "url", "name": "elsewhere", "url": "https://elsewhere.example/mcp"}
)


def sandbox_bridge(**kwargs: Any) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=3000,
        model=None,
        **kwargs,
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
def test_sandbox_media_must_be_inline(uri: str) -> None:
    bridge = sandbox_bridge()
    messages = [ChatMessageUser(content=[ContentImage(image=uri)])]
    with pytest.raises(BridgePolicyError) as info:
        validate_bridge_media(bridge, messages)
    assert info.value.status_code == 400


def test_sandbox_media_covers_non_uri_locators() -> None:
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
            validate_bridge_media(
                sandbox_bridge(), [ChatMessageUser(content=[content])]
            )


def test_sandbox_media_allows_data_uri() -> None:
    messages = [
        ChatMessageUser(content=[ContentImage(image="data:image/png;base64,AAAA")])
    ]
    validate_bridge_media(sandbox_bridge(), messages)


def test_sandbox_media_covers_documents() -> None:
    messages = [
        ChatMessageUser(content=[ContentDocument(document="https://elsewhere/x.pdf")])
    ]
    with pytest.raises(BridgePolicyError):
        validate_bridge_media(sandbox_bridge(), messages)


def test_in_process_media_is_unrestricted() -> None:
    messages = [ChatMessageUser(content=[ContentImage(image="http://elsewhere/x.png")])]
    validate_bridge_media(AgentBridge(AgentState(messages=[])), messages)


def test_sandbox_media_can_be_re_enabled() -> None:
    messages = [ChatMessageUser(content=[ContentImage(image="http://elsewhere/x.png")])]
    validate_bridge_media(sandbox_bridge(allow_remote_media=True), messages)
