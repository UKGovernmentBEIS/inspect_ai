import json
import zipfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic_core import to_jsonable_python
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.agent import AgentState, react
from inspect_ai.agent._bridge.anthropic_api_impl import tools_from_anthropic_tools
from inspect_ai.agent._bridge.responses_impl import tool_from_responses_tool
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.approval import ApprovalPolicy, approval, auto_approver
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent, StateEvent
from inspect_ai.log import read_eval_log
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    ContentToolUse,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.model._model import GenerateFilter
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import MCPServer, ToolChoice, ToolInfo, mcp_server_http
from inspect_ai.tool._mcp._remote import (
    redact_anthropic_mcp_servers,
    redact_grok_mcp_tools,
    redact_responses_mcp_tools,
)
from inspect_ai.tool._tool_info import REDACTED


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
            requested_model=None,
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


# =============================================================================
# Credentials
# =============================================================================

MCP_TOKEN = "mcp-test-token-4f1c9a"
MCP_API_KEY = "mcp-test-api-key-8d2e07"
# non-credential header values, which also appear in the conversation
MCP_VERSION = "2025-06-18"
MCP_MODE = "automatic-mode"
MCP_INPUT = f"Search the {MCP_VERSION} MCP spec in {MCP_MODE}."


def credentialed_server() -> MCPServer:
    return mcp_server_http(
        name="deepwiki",
        url="https://mcp.deepwiki.com/mcp",
        execution="remote",
        authorization=MCP_TOKEN,
        headers={
            "X-API-Key": MCP_API_KEY,
            "MCP-Protocol-Version": MCP_VERSION,
            "X-Mode": MCP_MODE,
        },
    )


def assert_no_credentials(text: str | bytes) -> None:
    data = text.encode() if isinstance(text, str) else text
    assert MCP_TOKEN.encode() not in data
    assert MCP_API_KEY.encode() not in data


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_remote_mcp_credentials_sent_but_not_logged(
    provider: str, tmp_path: Path
) -> None:
    requests: list[dict[str, Any]] = []
    task = Task(
        dataset=[Sample(input=MCP_INPUT)],
        solver=[use_tools(credentialed_server()), generate()],
    )

    log = eval(task, model=remote_mcp_model(provider, requests), log_dir=str(tmp_path))[
        0
    ]
    assert log.status == "success"

    # the provider still receives the real credentials
    [request] = mcp_requests(requests)
    if provider == "openai":
        [server] = request["tools"]
        assert server["headers"] == {
            "Authorization": f"Bearer {MCP_TOKEN}",
            "X-API-Key": MCP_API_KEY,
            "MCP-Protocol-Version": MCP_VERSION,
            "X-Mode": MCP_MODE,
        }
    else:
        # Anthropic's MCP connector takes only a bearer token
        [server] = request["mcp_servers"]
        assert server["authorization_token"] == MCP_TOKEN

    # the log has the events that previously carried them
    assert log.samples
    events = log.samples[0].events
    model_events = [e for e in events if isinstance(e, ModelEvent)]
    assert model_events and all(e.call is not None for e in model_events)
    assert any(t.name == "mcp_server_deepwiki" for t in model_events[0].tools)
    state_events = [e for e in events if isinstance(e, StateEvent)]
    assert any("mcp_server_deepwiki" in e.model_dump_json() for e in state_events)

    # the server's headers are redacted, the conversation is not
    call = model_events[0].call
    assert call is not None
    call_request: dict[str, Any] = call.request
    assert MCP_INPUT in json.dumps(call_request)
    if provider == "openai":
        [server] = call_request["tools"]
        assert server["headers"] == {
            "Authorization": REDACTED,
            "X-API-Key": REDACTED,
            "MCP-Protocol-Version": REDACTED,
            "X-Mode": REDACTED,
        }
    else:
        [server] = call_request["extra_body"]["mcp_servers"]
        assert server["authorization_token"] == REDACTED

    assert_no_credentials(log.model_dump_json())
    assert_no_credentials(read_eval_log(log.location).model_dump_json())
    log_files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert log_files
    for path in log_files:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    assert_no_credentials(zf.read(name))
        else:
            assert_no_credentials(path.read_bytes())


async def test_remote_mcp_tool_info_credentials_not_serialized() -> None:
    [tool] = await credentialed_server().tools()
    [info] = get_tools_info([tool])

    # live options keep the credentials for the provider
    assert info.options is not None
    assert info.options["headers"] == {
        "Authorization": f"Bearer {MCP_TOKEN}",
        "X-API-Key": MCP_API_KEY,
        "MCP-Protocol-Version": MCP_VERSION,
        "X-Mode": MCP_MODE,
    }

    for serialized in [
        info.model_dump_json(),
        json.dumps(info.model_dump()),
        json.dumps(to_jsonable_python(info)),
    ]:
        assert_no_credentials(serialized)
        assert "X-API-Key" in serialized
        assert "https://mcp.deepwiki.com/mcp" in serialized

    # other tools named like a server keep their options
    other = ToolInfo(
        name="mcp_server_other",
        description="other",
        options={"headers": {"Accept": "application/json"}},
    )
    assert "application/json" in other.model_dump_json()


def test_bridged_remote_mcp_credentials_not_serialized() -> None:
    """Servers declared by a bridged agent carry its credentials the same way."""
    [anthropic_info] = tools_from_anthropic_tools(
        None,
        [
            {
                "type": "url",
                "name": "deepwiki",
                "url": "https://mcp.deepwiki.com/mcp",
                "authorization_token": MCP_TOKEN,
            }
        ],
        None,
        None,
        allow_remote_mcp=True,
    )
    responses_info = tool_from_responses_tool(
        {
            "type": "mcp",
            "server_label": "deepwiki",
            "server_url": "https://mcp.deepwiki.com/mcp",
            "headers": {
                "Authorization": f"Bearer {MCP_TOKEN}",
                "X-API-Key": MCP_API_KEY,
            },
            "allowed_tools": None,
        },
        None,
        None,
        allow_remote_mcp=True,
    )
    for info in [anthropic_info, responses_info]:
        assert isinstance(info, ToolInfo)
        assert info.options is not None and info.options["headers"]
        assert_no_credentials(info.model_dump_json())


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_remote_mcp_with_redacted_credentials_is_refused(provider: str) -> None:
    """A server read back from a log isn't sent with "<redacted>" credentials."""
    [tool] = await credentialed_server().tools()
    [info] = get_tools_info([tool])
    logged = ToolInfo.model_validate_json(info.model_dump_json())
    assert logged.options is not None
    assert logged.options["headers"]["Authorization"] == REDACTED

    requests: list[dict[str, Any]] = []
    async with remote_mcp_model(provider, requests) as model:
        with pytest.raises(ValueError, match="redacted credentials"):
            await model.generate("Search the MCP spec.", tools=[logged])

    assert mcp_requests(requests) == []


def test_structural_request_redaction_copies_only_when_needed() -> None:
    messages: list[Any] = [{"role": "user", "content": MCP_TOKEN}]
    anthropic: dict[str, Any] = {
        "messages": messages,
        "extra_body": {
            "mcp_servers": [{"name": "a", "authorization_token": MCP_TOKEN}]
        },
    }
    redacted = redact_anthropic_mcp_servers(anthropic)
    assert redacted["extra_body"]["mcp_servers"][0]["authorization_token"] == REDACTED
    assert redacted["messages"] is messages
    # the request sent to the provider is unchanged
    assert anthropic["extra_body"]["mcp_servers"][0]["authorization_token"] == MCP_TOKEN
    no_token = {"messages": messages, "mcp_servers": [{"name": "a"}]}
    assert redact_anthropic_mcp_servers(no_token) is no_token

    responses: dict[str, Any] = {
        "input": messages,
        "tools": [
            {"type": "function", "name": "f"},
            {"type": "mcp", "headers": {"Authorization": MCP_TOKEN}},
        ],
    }
    redacted = redact_responses_mcp_tools(responses)
    assert redacted["tools"][0] is responses["tools"][0]
    assert redacted["tools"][1]["headers"] == {"Authorization": REDACTED}
    assert redacted["input"] is messages
    assert responses["tools"][1]["headers"] == {"Authorization": MCP_TOKEN}
    no_headers = {"input": messages, "tools": [{"type": "mcp", "headers": None}]}
    assert redact_responses_mcp_tools(no_headers) is no_headers


def test_grok_request_redaction() -> None:
    """Grok can't use remote MCP today, but its recorded request is redacted too."""
    # MessageToDict(xai_sdk.tools.mcp(...)) as recorded by the provider
    server = {
        "mcp": {
            "serverLabel": "deepwiki",
            "serverUrl": "https://mcp.deepwiki.com/mcp",
            "authorization": MCP_TOKEN,
            "extraHeaders": {"X-API-Key": MCP_API_KEY},
        }
    }
    function = {"function": {"name": "f"}}
    request: dict[str, Any] = {"tools": [function, server]}
    sent = json.dumps(request)

    redacted = redact_grok_mcp_tools(request)
    assert redacted["tools"][0] is function
    assert redacted["tools"][1]["mcp"]["authorization"] == REDACTED
    assert redacted["tools"][1]["mcp"]["extraHeaders"] == {"X-API-Key": REDACTED}
    assert redacted["tools"][1]["mcp"]["serverUrl"] == "https://mcp.deepwiki.com/mcp"
    assert_no_credentials(json.dumps(redacted))
    assert json.dumps(request) == sent
    no_mcp: dict[str, Any] = {"tools": [function]}
    assert redact_grok_mcp_tools(no_mcp) is no_mcp
