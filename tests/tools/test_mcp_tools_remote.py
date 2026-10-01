import json
from typing import Any

import httpx2
import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.agent import AgentState, react
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.approval import ApprovalPolicy, approval, auto_approver
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    ContentToolUse,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model import GenerateFilter
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import MCPServer, ToolChoice, ToolInfo, mcp_server_http


@skip_if_no_openai
@pytest.mark.flaky  # deepwiki sometimes causes this to fail with rate limit errors
def test_openai_remote_mcp() -> None:
    check_remote_mcp("openai/gpt-4o")


@skip_if_no_anthropic
@pytest.mark.flaky  # deepwiki sometimes causes this to fail with rate limit errors
def test_anthropic_remote_mcp() -> None:
    # This test is flaky because, sometimes, the model gets confused and does not
    # make do a remote tool use.
    check_remote_mcp("anthropic/claude-sonnet-4-6")


@skip_if_no_google
def test_google_remote_mcp() -> None:
    with pytest.raises(RuntimeError, match="Remote MCP"):
        check_remote_mcp("google/gemini-3.1-flash-lite", debug_errors=True)


# doesn't appear to be enabled server-side right now
# @skip_if_no_grok
# @pytest.mark.flaky  # deepwiki sometimes causes this to fail with rate limit errors
# def test_grok_remote_mcp() -> None:
#     check_remote_mcp("grok/grok-4-1-fast")


def check_remote_mcp(model: str, debug_errors: bool = False) -> None:
    deepwiki = mcp_server_http(
        name="deepwiki", url="https://mcp.deepwiki.com/mcp", execution="remote"
    )

    task = Task(
        dataset=[
            Sample(
                input="What transport protocols are supported in the 2025-03-26 version of the MCP spec?",
            )
        ],
        solver=[use_tools(deepwiki), generate()],
    )

    log = eval(task, model=model, debug_errors=debug_errors)[0]
    assert log.status == "success"
    assert log.samples
    content = log.samples[0].output.message.content
    assert isinstance(content, list)
    assert any(isinstance(c, ContentToolUse) for c in content)


# =============================================================================
# Approval policies
# =============================================================================
#
# The provider runs a remote server's tools during generation, where Inspect
# can't approve them, so a remote server is refused while a policy is active.
# The providers are mocked at the HTTP layer to check the request they send.

OPENAI_RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "created_at": 0,
    "model": "gpt-5",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Done.", "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}

ANTHROPIC_RESPONSE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "Done."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def remote_mcp_model(provider: str, requests: list[dict[str, Any]]) -> Model:
    """A model of `provider` that records each request body it sends."""
    response = OPENAI_RESPONSE if provider == "openai" else ANTHROPIC_RESPONSE

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=response, request=request)

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    if provider == "openai":
        return get_model(
            "openai/gpt-5",
            api_key="test",
            base_url="http://test/v1",
            http_client=http_client,
            responses_api=True,
            memoize=False,
        )
    else:
        return get_model(
            "anthropic/claude-sonnet-4-6",
            api_key="test",
            base_url="http://test",
            http_client=http_client,
            streaming=False,
            config=GenerateConfig(max_tokens=1024),
            memoize=False,
        )


def mcp_requests(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The requests that carry a remote MCP server (OpenAI also sends a probe)."""
    return [
        r
        for r in requests
        if "mcp_servers" in r or any(t.get("type") == "mcp" for t in r.get("tools", []))
    ]


def deepwiki_server() -> MCPServer:
    return mcp_server_http(
        name="deepwiki", url="https://mcp.deepwiki.com/mcp", execution="remote"
    )


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("tools", ["*", "bash"], ids=["all-tools", "other-tools"])
async def test_remote_mcp_refused_under_approval_policy(
    provider: str, tools: str
) -> None:
    """Any active policy decides the server's tools, so the server is never sent.

    A policy that matches no tool call rejects it, so a policy naming other tools
    covers the server's tools as well.
    """
    requests: list[dict[str, Any]] = []
    async with remote_mcp_model(provider, requests) as model:
        with approval([ApprovalPolicy(auto_approver(), tools)]):
            with pytest.raises(RuntimeError, match="Remote MCP server 'deepwiki'"):
                await model.generate("Search the MCP spec.", tools=[deepwiki_server()])

    assert mcp_requests(requests) == []


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_remote_mcp_sent_unchanged_without_approval_policy(
    provider: str,
) -> None:
    requests: list[dict[str, Any]] = []
    async with remote_mcp_model(provider, requests) as model:
        await model.generate("Search the MCP spec.", tools=[deepwiki_server()])

    [request] = mcp_requests(requests)
    if provider == "openai":
        [server] = request["tools"]
        assert server["server_label"] == "deepwiki"
        assert server["server_url"] == "https://mcp.deepwiki.com/mcp"
        assert server["require_approval"] == "never"
    else:
        [server] = request["mcp_servers"]
        assert server["name"] == "deepwiki"
        assert server["url"] == "https://mcp.deepwiki.com/mcp"


def test_remote_mcp_refused_under_react_approval_policy() -> None:
    """A `react()` agent's own policies apply to the model calls it makes."""
    requests: list[dict[str, Any]] = []
    model = remote_mcp_model("openai", requests)
    task = Task(
        dataset=[Sample(input="Search the MCP spec.")],
        solver=react(
            tools=[deepwiki_server()],
            approval=[ApprovalPolicy(auto_approver(), "*")],
        ),
        message_limit=5,
    )

    log = eval(task, model=model)[0]

    assert log.status == "error"
    assert log.error is not None
    assert "Remote MCP server" in log.error.message
    assert "deepwiki" in log.error.message
    assert mcp_requests(requests) == []


def generating_filter(kind: str | None, model: Model) -> GenerateFilter | None:
    """A bridge filter that generates itself, with a `Model` or legacy `str` first parameter."""
    if kind == "model":

        async def model_filter(
            model: Model,
            messages: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice | None,
            config: GenerateConfig,
        ) -> ModelOutput:
            return await model.generate(
                messages, tools=tools, tool_choice=tool_choice, config=config
            )

        return model_filter
    elif kind == "str":

        async def legacy_filter(
            model_name: str,
            messages: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice | None,
            config: GenerateConfig,
        ) -> ModelOutput:
            return await model.generate(
                messages, tools=tools, tool_choice=tool_choice, config=config
            )

        return legacy_filter
    else:
        return None


async def run_bridge_with_remote_mcp(
    provider: str,
    filter: str | None,
    approval: list[ApprovalPolicy] | None,
    requests: list[dict[str, Any]],
) -> None:
    messages: list[ChatMessage] = [ChatMessageUser(content="Search.")]
    async with remote_mcp_model(provider, requests) as model:
        bridge = AgentBridge(
            AgentState(messages=list(messages)),
            filter=generating_filter(filter, model),
            approval=approval,
        )
        await bridge_generate(
            bridge,
            model,
            messages,
            await deepwiki_server().tools(),
            None,
            GenerateConfig(),
        )


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("filter", [None, "model", "str"])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_remote_mcp_refused_under_bridge_approval_policy(
    provider: str, filter: str | None
) -> None:
    """A bridge's own policies apply to the model calls it (or its filter) makes."""
    requests: list[dict[str, Any]] = []
    with pytest.raises(RuntimeError, match="Remote MCP server 'deepwiki'"):
        await run_bridge_with_remote_mcp(
            provider, filter, [ApprovalPolicy(auto_approver(), "*")], requests
        )

    assert mcp_requests(requests) == []


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("filter", [None, "model", "str"])
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_remote_mcp_sent_through_bridge_without_approval_policy(
    provider: str, filter: str | None
) -> None:
    requests: list[dict[str, Any]] = []
    await run_bridge_with_remote_mcp(provider, filter, None, requests)

    assert len(mcp_requests(requests)) == 1
