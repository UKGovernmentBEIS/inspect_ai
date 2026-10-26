"""Tests for MCP tools bridge functionality.

These tests verify that host-side Inspect tools can be exposed to sandboxed agents
via the MCP protocol using BridgedToolsSpec and sandbox_agent_bridge.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import anyio
import pytest
from pydantic import JsonValue
from sniffio import current_async_library
from test_helpers.service_dispatch import (
    REQUEST_FILE,
    REQUEST_ID,
    dispatching_service,
    serve_beside_failure_monitor,
)
from test_helpers.utils import fail_in_a_group_with_handled_context, skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent import BridgedToolsSpec, sandbox_agent_bridge
from inspect_ai.agent._bridge.sandbox.host_tool import _raised
from inspect_ai.agent._bridge.sandbox.service import call_tool
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.model._call_tools import tool_call_error, truncate_tool_output
from inspect_ai.model._generate_config import (
    GenerateConfig,
    active_generate_config_context_var,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import includes
from inspect_ai.solver import Solver, solver
from inspect_ai.tool import Tool, ToolError, tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.util import sandbox
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.limits import OutputLimitExceededError

if TYPE_CHECKING:
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

# =============================================================================
# Shared test tools with stateful call tracking
# =============================================================================


@tool
def calculator_add(call_log: list[dict]):
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        call_log.append({"tool": "calculator_add", "x": x, "y": y})
        return str(x + y)

    return execute


@tool
def get_structured_data(call_log: list[dict]):
    async def execute(key: str) -> str:
        """Get structured data for a key.

        Args:
            key: The key to look up.
        """
        call_log.append({"tool": "get_structured_data", "key": key})
        return json.dumps({"key": key, "values": [1, 2, 3], "nested": {"a": "b"}})

    return execute


@tool
def content_returning_tool(call_log: list[dict]):
    async def execute(text: str) -> list[ContentText]:
        """Echo a string back as a list of content blocks.

        Args:
            text: Text to echo back.
        """
        call_log.append({"tool": "content_returning_tool", "text": text})
        return [ContentText(text=text)]

    return execute


@tool
def image_content_returning_tool(call_log: list[dict]):
    async def execute(
        include_caption: bool,
    ) -> ContentImage | list[ContentText | ContentImage]:
        """Return text and image content blocks.

        Args:
            include_caption: Whether to return a text caption before the image.
        """
        call_log.append(
            {"tool": "image_content_returning_tool", "include_caption": include_caption}
        )
        image = ContentImage(image="data:image/png;name=screenshot;base64,iVBORw0KGgo=")
        if include_caption:
            return [ContentText(text="Screenshot:"), image]
        return image

    return execute


# =============================================================================
# Test helpers
# =============================================================================


NONROOT_SANDBOX = (
    "docker",
    str(Path(__file__).parent / "test_sandbox_compose.yaml"),
)
"""A sandbox whose default user is not root (root exec still works)."""


@task
def bridged_tools_task(test_solver: Solver, sandbox: str | tuple[str, str] = "docker"):
    return Task(
        dataset=[Sample(input="Test", target="Test")],
        solver=[test_solver],
        scorer=includes(),
        sandbox=sandbox,
    )


def eval_bridged_tools_task(
    test_solver: Solver, sandbox: str | tuple[str, str] = "docker"
) -> EvalLog:
    log = eval(
        bridged_tools_task(test_solver, sandbox), model=get_model("mockllm/model")
    )[0]
    assert log.status == "success"
    return log


def host_tool_events(log: EvalLog) -> list[ToolEvent]:
    """The tool events the bridge recorded for host tool calls."""
    assert log.samples is not None
    return [e for e in log.samples[0].events if isinstance(e, ToolEvent)]


def tool_span_parents(log: EvalLog) -> list[str | None]:
    assert log.samples is not None
    return [
        e.parent_id
        for e in log.samples[0].events
        if isinstance(e, SpanBeginEvent) and e.type == "tool"
    ]


async def _mcp_http_request_with_retry(
    url: str,
    request: str,
    max_retries: int = 30,
    retry_delay: float = 0.5,
    headers: dict[str, str] | None = None,
) -> dict:
    """Send HTTP POST to MCP endpoint with retry logic for server startup."""
    import asyncio

    header_args = [
        arg
        for name, value in (headers or {}).items()
        for arg in ("-H", f"{name}: {value}")
    ]
    last_error: Exception | None = None
    for attempt in range(max_retries):
        result = await sandbox().exec(
            cmd=[
                "curl",
                "-s",
                "-f",  # Fail silently on HTTP errors
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                *header_args,
                "-d",
                request,
                url,
            ],
            timeout=30,
        )
        if result.success and result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except json.JSONDecodeError as e:
                last_error = e
        else:
            last_error = Exception(
                f"curl failed: returncode={result.returncode}, "
                f"stdout={result.stdout}, stderr={result.stderr}"
            )
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    raise RuntimeError(f"MCP request failed after {max_retries} retries: {last_error}")


async def call_mcp_tool(
    config: MCPServerConfigHTTP, tool_name: str, arguments: dict
) -> dict:
    """Send a tools/call JSON-RPC request to MCP HTTP server and return parsed response."""
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    return await _mcp_http_request_with_retry(config.url, request)


async def call_mcp_tools_list(config: MCPServerConfigHTTP) -> dict:
    """Send a tools/list JSON-RPC request to MCP HTTP server and return parsed response."""
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return await _mcp_http_request_with_retry(config.url, request)


# =============================================================================
# E2E tests with Docker sandbox - actually invoke MCP server
# =============================================================================
#
# These tests drive `tools/call` straight from the solver, outside any model
# turn, so their specs opt out of the proposal requirement. The strict default
# (a host tool runs once per call the model proposed) is covered in the
# "Host tool execution" section below.


# The nonroot compose checks the bridge still starts its in-sandbox proxy (which
# lives in the root-owned tools tree) when the sandbox default user is not root.
@pytest.mark.parametrize(
    "sandbox",
    ["docker", NONROOT_SANDBOX],
)
@skip_if_no_docker
@pytest.mark.slow
def test_single_tool_call_returns_correct_result(
    sandbox: str | tuple[str, str],
) -> None:
    """Call a single bridged tool via MCP and verify the result."""
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="calc",
                        tools=[calculator_add(call_log)],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                response = await call_mcp_tool(
                    config, "calculator_add", {"x": 5, "y": 3}
                )

                assert response["jsonrpc"] == "2.0"
                assert response["id"] == 1
                assert response["result"]["content"][0]["text"] == "8"

            return state

        return solve

    log = eval_bridged_tools_task(test_solver(), sandbox)

    assert call_log == [{"tool": "calculator_add", "x": 5, "y": 3}]
    [event] = host_tool_events(log)
    assert event.function == "calculator_add"
    assert event.result == "8"
    assert event.error is None
    assert event.metadata is not None
    assert event.metadata["bridge"]["grant"] == "exempt"
    assert event.metadata["bridge"]["proposal_id"] is None


@skip_if_no_docker
@pytest.mark.slow
def test_single_tool_call_with_nonroot_default_user() -> None:
    """The model service runs as the non-root default user while the proxy runs as root.

    The service's request/response queues are private (0700) to the default user;
    the proxy inside the sandbox-tools daemon runs as root and must still be able to
    file requests into them and collect the responses.
    """
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="calc",
                        tools=[calculator_add(call_log)],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                whoami = await sandbox().exec(["id", "-u"])
                assert whoami.stdout.strip() not in ("", "0"), whoami
                config = bridge.mcp_server_configs[0]
                response = await call_mcp_tool(
                    config, "calculator_add", {"x": 5, "y": 3}
                )
                assert response["result"]["content"][0]["text"] == "8"

                queues = await sandbox().exec(
                    [
                        "sh",
                        "-c",
                        "stat -c '%U %a' /var/tmp/sandbox-services/bridge_model_service/*/requests "
                        "/var/tmp/sandbox-services/bridge_model_service/*/responses",
                    ]
                )
                assert queues.success, queues.stderr
                assert queues.stdout.split("\n")[:-1] == ["nonroot 700"] * 2, queues

            return state

        return solve

    eval_bridged_tools_task(test_solver(), NONROOT_SANDBOX)

    assert call_log == [{"tool": "calculator_add", "x": 5, "y": 3}]


@skip_if_no_docker
@pytest.mark.slow
def test_multiple_tools_in_single_spec() -> None:
    """Call multiple tools from a single BridgedToolsSpec."""
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="tools",
                        tools=[calculator_add(call_log), get_structured_data(call_log)],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]

                add_response = await call_mcp_tool(
                    config, "calculator_add", {"x": 10, "y": 20}
                )
                assert add_response["result"]["content"][0]["text"] == "30"

                data_response = await call_mcp_tool(
                    config, "get_structured_data", {"key": "foo"}
                )
                data = json.loads(data_response["result"]["content"][0]["text"])
                assert data == {
                    "key": "foo",
                    "values": [1, 2, 3],
                    "nested": {"a": "b"},
                }

            return state

        return solve

    eval_bridged_tools_task(test_solver())

    assert len(call_log) == 2
    assert {"tool": "calculator_add", "x": 10, "y": 20} in call_log
    assert {"tool": "get_structured_data", "key": "foo"} in call_log


@skip_if_no_docker
@pytest.mark.slow
def test_multiple_bridged_tools_specs() -> None:
    """Call tools from multiple BridgedToolsSpec instances."""
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="calc",
                        tools=[calculator_add(call_log)],
                        require_proposal=False,
                    ),
                    BridgedToolsSpec(
                        name="data",
                        tools=[get_structured_data(call_log)],
                        require_proposal=False,
                    ),
                ]
            ) as bridge:
                assert len(bridge.mcp_server_configs) == 2

                calc_config = next(
                    c for c in bridge.mcp_server_configs if c.name == "calc"
                )
                data_config = next(
                    c for c in bridge.mcp_server_configs if c.name == "data"
                )

                calc_response = await call_mcp_tool(
                    calc_config, "calculator_add", {"x": 100, "y": 200}
                )
                assert calc_response["result"]["content"][0]["text"] == "300"

                data_response = await call_mcp_tool(
                    data_config, "get_structured_data", {"key": "bar"}
                )
                data = json.loads(data_response["result"]["content"][0]["text"])
                assert data == {
                    "key": "bar",
                    "values": [1, 2, 3],
                    "nested": {"a": "b"},
                }

            return state

        return solve

    eval_bridged_tools_task(test_solver())

    assert len(call_log) == 2
    assert {"tool": "calculator_add", "x": 100, "y": 200} in call_log
    assert {"tool": "get_structured_data", "key": "bar"} in call_log


@skip_if_no_docker
@pytest.mark.slow
def test_mcp_tools_list_returns_all_tools():
    """Test that tools/list returns all bridged tools with schemas."""

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="tools",
                        tools=[calculator_add([]), get_structured_data([])],
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                response = await call_mcp_tools_list(config)

                tools = response["result"]["tools"]
                assert len(tools) == 2
                assert {t["name"] for t in tools} == {
                    "calculator_add",
                    "get_structured_data",
                }

                for t in tools:
                    assert "description" in t
                    assert t["inputSchema"]["type"] == "object"

            return state

        return solve

    eval_bridged_tools_task(test_solver())


@skip_if_no_docker
@pytest.mark.slow
def test_duplicate_bridged_tools_names_raises_error():
    """Test that duplicate bridged_tools names raise ValueError."""
    error_raised = []

    @solver
    def test_solver():
        async def solve(state, generate):
            try:
                async with sandbox_agent_bridge(
                    bridged_tools=[
                        BridgedToolsSpec(name="same_name", tools=[calculator_add([])]),
                        BridgedToolsSpec(
                            name="same_name", tools=[get_structured_data([])]
                        ),
                    ]
                ):
                    pass
            except ValueError as e:
                if "Duplicate bridged_tools name" in str(e):
                    error_raised.append(True)
                else:
                    raise

            return state

        return solve

    eval_bridged_tools_task(test_solver())

    assert error_raised, "Expected ValueError for duplicate bridged_tools names"


@skip_if_no_docker
@pytest.mark.slow
def test_content_returning_tool_serializes_correctly() -> None:
    """Bridged tools returning list[ContentText] must serialize without error.

    Regression test for json.dumps choking on Pydantic BaseModel — list[ContentText]
    is the standard return type for inspect_ai MCP tools.
    """
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="content",
                        tools=[content_returning_tool(call_log)],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                response = await call_mcp_tool(
                    config, "content_returning_tool", {"text": "hello"}
                )

                assert response["jsonrpc"] == "2.0"
                # Bridge serializes the tool's return value into a single MCP
                # text part; for non-strings it's a JSON-encoded payload.
                payload = json.loads(response["result"]["content"][0]["text"])
                assert payload == [{"type": "text", "text": "hello"}]

            return state

        return solve

    eval_bridged_tools_task(test_solver())

    assert call_log == [{"tool": "content_returning_tool", "text": "hello"}]


@skip_if_no_docker
@pytest.mark.slow
def test_image_content_returning_tool_returns_mcp_image_content() -> None:
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="content",
                        tools=[image_content_returning_tool(call_log)],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                single_response = await call_mcp_tool(
                    bridge.mcp_server_configs[0],
                    "image_content_returning_tool",
                    {"include_caption": False},
                )
                assert single_response["result"]["content"] == [
                    {
                        "type": "image",
                        "data": "iVBORw0KGgo=",
                        "mimeType": "image/png",
                    }
                ]

                mixed_response = await call_mcp_tool(
                    bridge.mcp_server_configs[0],
                    "image_content_returning_tool",
                    {"include_caption": True},
                )
                assert mixed_response["result"]["content"] == [
                    {"type": "text", "text": "Screenshot:"},
                    {
                        "type": "image",
                        "data": "iVBORw0KGgo=",
                        "mimeType": "image/png",
                    },
                ]
            return state

        return solve

    eval_bridged_tools_task(test_solver())
    assert call_log == [
        {"tool": "image_content_returning_tool", "include_caption": False},
        {"tool": "image_content_returning_tool", "include_caption": True},
    ]


# =============================================================================
# Tool approval over the sandbox bridge
# =============================================================================


async def post_completions(port: int, body: dict) -> dict:
    """POST a Completions request to the in-container model proxy."""
    return await _mcp_http_request_with_retry(
        f"http://localhost:{port}/v1/chat/completions", json.dumps(body)
    )


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_rejection_hides_the_call_from_the_agent() -> None:
    """A rejected call must not reach an agent running inside the sandbox.

    Full round trip: sandbox HTTP -> model proxy -> sandbox service RPC ->
    completions dialect -> bridge_generate -> approval -> regenerate.
    """
    from inspect_ai.approval import ApprovalPolicy, auto_approver
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
    from inspect_ai.tool._tool_call import ToolCall

    seen: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                state,
                approval=[
                    ApprovalPolicy(auto_approver("reject"), "bash"),
                    ApprovalPolicy(auto_approver("approve"), "*"),
                ],
            ) as bridge:
                response = await post_completions(
                    bridge.port,
                    {
                        "model": "inspect",
                        "messages": [{"role": "user", "content": "Tidy up."}],
                    },
                )
                seen.append(response)
            return state

        return solve

    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    outputs = [
        ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="On it.", tool_calls=[unsafe]),
                    stop_reason="tool_calls",
                )
            ],
        ),
        ModelOutput.from_content(model="mockllm/model", content="safer plan"),
    ]

    log = eval(
        bridged_tools_task(test_solver()),
        model=get_model("mockllm/model", custom_outputs=outputs),
    )[0]
    assert log.status == "success"

    # the agent in the sandbox received the replacement, never the rejected call
    message = seen[0]["choices"][0]["message"]
    assert message.get("tool_calls") in (None, [])
    assert message["content"] == "safer plan"

    # and the rejection is on the record host-side
    assert log.samples is not None
    approvals = [e for e in log.samples[0].events if e.event == "approval"]
    assert [(e.decision, e.call.function) for e in approvals] == [("reject", "bash")]


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_redirects_unknown_model_to_eval_model() -> None:
    """A model name the eval did not configure is served by the eval's model.

    Full round trip through the in-container proxy; the requested name is
    recorded on the model event.
    """
    seen: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(state) as bridge:
                seen.append(
                    await post_completions(
                        bridge.port,
                        {
                            "model": "claude-haiku-4-5",
                            "messages": [{"role": "user", "content": "Hello"}],
                        },
                    )
                )
            return state

        return solve

    log = eval(
        bridged_tools_task(test_solver()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(model="mockllm/model", content="hi there")
            ],
        ),
    )[0]
    assert log.status == "success"

    assert seen[0]["model"] == "model"
    assert seen[0]["choices"][0]["message"]["content"] == "hi there"

    assert log.samples is not None
    events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert [(e.model, e.requested_model) for e in events] == [
        ("mockllm/model", "claude-haiku-4-5")
    ]


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_forwards_allowed_betas_and_decodes_brotli() -> None:
    """Client headers reach the provider through the in-container proxy.

    Full round trip: sandbox HTTP (Anthropic dialect) -> model proxy -> sandbox
    service RPC -> header filter -> Anthropic provider. The provider answers
    brotli-encoded, as Anthropic does once `br` is forwarded.
    """
    import importlib

    import httpx2

    try:
        brotli = importlib.import_module("brotli")
    except ImportError:
        brotli = importlib.import_module("brotlicffi")

    provider_requests: list[httpx2.Request] = []
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": "decoded"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        provider_requests.append(request)
        return httpx2.Response(
            200,
            content=brotli.compress(json.dumps(message).encode()),
            headers={"content-encoding": "br", "content-type": "application/json"},
        )

    target_model = get_model(
        "anthropic/claude-sonnet-4-5",
        api_key="local-fake-key",
        memoize=False,
        streaming=False,
        config=GenerateConfig(max_tokens=64),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    seen: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                state,
                model_aliases={"agent-model": target_model},
                forward_client_headers={"anthropic-beta": ["allowed-beta-2026-01-01"]},
            ) as bridge:
                seen.append(
                    await _mcp_http_request_with_retry(
                        f"http://localhost:{bridge.port}/v1/messages",
                        json.dumps(
                            {
                                "model": "agent-model",
                                "max_tokens": 64,
                                "messages": [{"role": "user", "content": "hi"}],
                            }
                        ),
                        headers={
                            "anthropic-beta": (
                                "allowed-beta-2026-01-01,unlisted-beta-2026-01-01"
                            ),
                            "Accept-Encoding": "br",
                            "OpenAI-Organization": "org-sandbox",
                        },
                    )
                )
            return state

        return solve

    eval_bridged_tools_task(test_solver())

    assert seen[0]["content"][0]["text"] == "decoded"
    [request] = provider_requests
    assert request.headers["anthropic-beta"] == "allowed-beta-2026-01-01"
    assert request.headers["accept-encoding"] == "br"
    assert "openai-organization" not in request.headers


# =============================================================================
# Host tool execution: a bridged tool runs once per call the model proposed
# =============================================================================


def approve_all() -> list:
    from inspect_ai.approval import ApprovalPolicy, auto_approver

    return [ApprovalPolicy(auto_approver("approve"), "*")]


@pytest.mark.parametrize("approval", [None, approve_all()], ids=["no-policy", "policy"])
@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_denies_unproposed_host_tool_call(approval: list | None) -> None:
    """A `tools/call` no model generation proposed is denied, with the reason intact."""
    call_log: list[dict] = []
    seen: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                state,
                approval=approval,
                bridged_tools=[
                    BridgedToolsSpec(name="calc", tools=[calculator_add(call_log)])
                ],
            ) as bridge:
                seen.append(
                    await call_mcp_tool(
                        bridge.mcp_server_configs[0],
                        "calculator_add",
                        {"x": 5, "y": 3},
                    )
                )
            return state

        return solve

    log = eval_bridged_tools_task(test_solver())

    assert call_log == []
    # the denial reaches the agent intact as the JSON-RPC error message (the
    # sandbox service prefixes it with the failing RPC method)
    denial = (
        "Host tool call 'calc/calculator_add' was not proposed by the model in a "
        "bridged generation (a bridged host tool runs once per proposed call)"
    )
    assert seen[0]["error"]["message"].endswith(denial)
    [event] = host_tool_events(log)
    assert event.error is not None
    assert event.error.type == "permission"
    assert event.error.message == denial
    assert event.metadata is not None
    assert event.metadata["bridge"]["grant"] == "denied"


@pytest.mark.parametrize("approval", [None, approve_all()], ids=["no-policy", "policy"])
@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_executes_proposed_host_tool_call_once(
    approval: list | None,
) -> None:
    """A call the model proposed grants one matching MCP execution."""
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
    from inspect_ai.tool._tool_call import ToolCall

    call_log: list[dict] = []
    responses: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                state,
                approval=approval,
                bridged_tools=[
                    BridgedToolsSpec(name="calc", tools=[calculator_add(call_log)])
                ],
            ) as bridge:
                await post_completions(
                    bridge.port,
                    {
                        "model": "inspect",
                        "messages": [{"role": "user", "content": "Add the numbers."}],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "calculator_add",
                                    "description": "Add two numbers.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "x": {"type": "integer"},
                                            "y": {"type": "integer"},
                                        },
                                        "required": ["x", "y"],
                                    },
                                },
                            }
                        ],
                    },
                )
                config = bridge.mcp_server_configs[0]
                responses.append(
                    await call_mcp_tool(config, "calculator_add", {"y": 3, "x": 5})
                )
                responses.append(
                    await call_mcp_tool(config, "calculator_add", {"x": 5, "y": 3})
                )
            return state

        return solve

    proposed = ToolCall(
        id="proposed",
        function="calculator_add",
        arguments={"x": 5, "y": 3},
    )
    output = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="", tool_calls=[proposed]),
                stop_reason="tool_calls",
            )
        ],
    )
    log = eval(
        bridged_tools_task(test_solver()),
        model=get_model("mockllm/model", custom_outputs=[output]),
    )[0]

    assert log.status == "success"
    assert responses[0]["result"]["content"][0]["text"] == "8"
    assert "was not proposed by the model" in responses[1]["error"]["message"]
    assert call_log == [{"tool": "calculator_add", "x": 5, "y": 3}]

    executed, denied = host_tool_events(log)
    assert executed.id == "proposed"
    assert executed.function == "calculator_add"
    assert executed.arguments == {"y": 3, "x": 5}
    assert executed.result == "8"
    assert executed.metadata is not None
    assert executed.metadata["bridge"]["function"] == "calculator_add"
    assert executed.metadata["bridge"]["grant"] == "consumed"
    assert denied.id != "proposed"
    assert denied.function == "calculator_add"
    assert denied.error is not None and denied.error.type == "permission"
    assert log.samples is not None
    [model_event] = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert executed.span_id == denied.span_id == model_event.span_id
    assert tool_span_parents(log) == [model_event.span_id, model_event.span_id]


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_terminate_ends_the_sample() -> None:
    """`terminate` must reach the sample runner from the sandbox service task.

    The approver runs in the bridged generation, inside the service task. Its
    `TerminateSampleError` is re-raised past the provider-error forwarding to the
    service dispatcher, which answers the RPC and propagates it out of the service
    task; that unwinds the bridge's task group and ends the sample once.
    """
    from inspect_ai.approval import ApprovalPolicy, auto_approver
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
    from inspect_ai.tool._tool_call import ToolCall

    completed: list[bool] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                state,
                approval=[ApprovalPolicy(auto_approver("terminate"), "*")],
            ) as bridge:
                try:
                    await post_completions(
                        bridge.port,
                        {
                            "model": "inspect",
                            "messages": [{"role": "user", "content": "Tidy up."}],
                        },
                    )
                except Exception:
                    pass
                # must not be reached: termination unwinds the bridge
                completed.append(True)
            return state

        return solve

    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    outputs = [
        ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="On it.", tool_calls=[unsafe]),
                    stop_reason="tool_calls",
                )
            ],
        )
    ]

    log = eval(
        bridged_tools_task(test_solver()),
        model=get_model("mockllm/model", custom_outputs=outputs),
    )[0]

    _assert_terminated_once(
        log, "Tool call approver requested termination: Automatic decision."
    )
    # positive evidence the approver ran and terminated: without it an empty
    # `completed` could equally mean the bridge never started
    assert log.samples is not None
    approvals = [e for e in log.samples[0].events if e.event == "approval"]
    assert [e.decision for e in approvals] == ["terminate"]
    # the bridge unwound before the body could finish
    assert completed == []


# =============================================================================
# Host tool exceptions
# =============================================================================
#
# Natively, `execute_tools` shows the model a fixed set of exception types as a
# `ToolCallError`, ends the sample on a termination, and fails it on anything
# else. The bridge's `call_tool` runs in the sandbox service task, whose
# dispatcher answers a termination and propagates it out of the service task,
# but turns any other exception into an RPC error the scaffold reads as tool
# output. So an unexpected one has to be signalled to the bridge's monitor task
# to fail the sample the same way.


@tool
def raising_tool(error: Exception):
    async def execute(text: str) -> str:
        """Raise `error` instead of returning.

        Args:
            text: Ignored.
        """
        raise error

    return execute


def _bridge_with_tools(tools: list) -> "SandboxAgentBridge":
    """A bridge whose `srv` tools are called directly, outside any model turn.

    These tests exercise the service callback itself, so the server opts out of
    the proposal requirement (`require_proposal=False` on a `BridgedToolsSpec`).
    """
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
    from inspect_ai.tool._tool_def import ToolDef

    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={"srv": {ToolDef(t).name: t for t in tools}},
        proposal_exempt_servers={"srv"},
    )


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        PermissionError(),
        FileNotFoundError(),
        IsADirectoryError(),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ValueError("embedded null byte"),
        ToolError("tool says no"),
        ToolParsingError("bad arguments"),
        LimitExceededError("token", value=2, limit=1),
        OutputLimitExceededError("1 KiB", None),
        SandboxUnavailableError("sandbox gone"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_bridged_tool_model_facing_errors_follow_the_native_mapping(
    error: Exception,
) -> None:
    """The bridge decides with `tool_call_error`, the mapping `execute_tools` uses."""
    assert tool_call_error(error, "t") is not None


@pytest.mark.parametrize(
    "error",
    [KeyError("missing"), TypeError("bad call"), ValueError("other"), RuntimeError()],
    ids=lambda e: type(e).__name__,
)
def test_unexpected_exceptions_have_no_native_mapping(error: Exception) -> None:
    assert tool_call_error(error, "t") is None


async def test_bridged_tool_unexpected_exception_fails_the_sample() -> None:
    """A bug in a host tool answers the RPC with an error and fails the sample."""
    error = KeyError("missing")
    bridge = _bridge_with_tools([raising_tool(error)])

    with pytest.raises(KeyError):
        await call_tool(bridge)("srv", "raising_tool", {"text": "hi"})

    assert bridge._failure_requested.is_set()
    assert bridge._failure is error


async def test_bridged_tool_error_is_reported_to_the_model_only() -> None:
    """A `ToolError` is the model's problem, as natively: the sample continues."""
    bridge = _bridge_with_tools([raising_tool(ToolError("tool says no"))])

    with pytest.raises(ToolError, match="tool says no"):
        await call_tool(bridge)("srv", "raising_tool", {"text": "hi"})

    assert not bridge._failure_requested.is_set()
    assert bridge._failure is None


async def test_bridged_tool_malformed_arguments_are_a_parsing_error() -> None:
    """Bad arguments from the scaffold's model are validated as for a native call.

    Without this, the `TypeError` from calling the tool with them would count as
    an unexpected exception and fail the sample, where natively the model gets a
    `ToolParsingError` it can recover from.
    """
    call_log: list[dict] = []
    bridge = _bridge_with_tools([calculator_add(call_log)])
    execute = call_tool(bridge)

    with pytest.raises(ToolParsingError, match="'y' is a required property"):
        await execute("srv", "calculator_add", {"x": 5})
    with pytest.raises(ToolParsingError, match="not of type 'integer'"):
        await execute("srv", "calculator_add", {"x": 5, "y": "three"})
    with pytest.raises(ToolParsingError, match="Additional properties"):
        await execute("srv", "calculator_add", {"x": 5, "y": 3, "z": 1})

    assert not bridge._failure_requested.is_set()
    assert call_log == []
    assert await execute("srv", "calculator_add", {"x": 5, "y": 3}) == "8"


@tool
def raising_in_task_group_tool(error: Exception):
    async def execute(text: str) -> str:
        """Raise `error` from a child task, so it arrives wrapped in a group.

        Args:
            text: Ignored.
        """

        async def child() -> None:
            raise error

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        return text

    return execute


async def test_bridged_tool_grouped_tool_error_is_unwrapped_for_the_model() -> None:
    """A mapped exception raised inside a task group is still the model's problem.

    `execute_tools` unwraps the `ExceptionGroup` before classifying; so must
    the bridge, or a recoverable error from a tool using a task group (real MCP
    tools do) would fail the sample. The group itself still propagates, as it
    did before, so the service dispatcher sees what it always saw.
    """
    from inspect_ai.util._anyio import inner_exception

    bridge = _bridge_with_tools([raising_in_task_group_tool(ToolError("recoverable"))])

    with pytest.raises(ExceptionGroup) as excinfo:
        await call_tool(bridge)("srv", "raising_in_task_group_tool", {"text": "hi"})

    assert isinstance(inner_exception(excinfo.value), ToolError)
    assert not bridge._failure_requested.is_set()


async def test_bridged_tool_grouped_unexpected_exception_fails_the_sample() -> None:
    """The sample fails with the unwrapped exception, as it would natively."""
    error = KeyError("missing")
    bridge = _bridge_with_tools([raising_in_task_group_tool(error)])

    with pytest.raises(ExceptionGroup):
        await call_tool(bridge)("srv", "raising_in_task_group_tool", {"text": "hi"})

    assert bridge._failure is error


@pytest.mark.parametrize("annotated", [False, True], ids=["bare", "Any"])
async def test_bridged_tool_with_explicit_schema_keeps_keyword_forwarding(
    annotated: bool,
) -> None:
    """A tool declared via `ToolDef(parameters=...)` need not have a typed signature.

    Arguments are validated against the declared schema and forwarded as sent,
    so variadic tools (as the MCP adapter uses) keep working.
    """
    from typing import Any

    from inspect_ai.tool._tool_def import ToolDef
    from inspect_ai.tool._tool_params import ToolParam, ToolParams

    received: list[dict] = []

    async def bare(**arguments) -> str:
        received.append(arguments)
        return "hello"

    async def typed(**arguments: Any) -> str:
        received.append(arguments)
        return "hello"

    schema = ToolParams(
        properties={"text": ToolParam(type="string", description="Text.")},
        required=["text"],
    )
    tool = ToolDef(
        typed if annotated else bare,
        name="echo",
        description="Echo.",
        parameters=schema,
    ).as_tool()
    bridge = _bridge_with_tools([tool])
    execute = call_tool(bridge)

    assert await execute("srv", "echo", {"text": "hi"}) == "hello"
    assert received == [{"text": "hi"}]
    with pytest.raises(ToolParsingError):
        await execute("srv", "echo", {"other": "hi"})
    assert not bridge._failure_requested.is_set()


async def test_bridged_tool_exception_unwinds_the_bridge_task_group() -> None:
    """The shape `sandbox_agent_bridge` relies on.

    The service answers the scaffold (an RPC error, not a hang) and signals the
    bridge; the monitor task in the same task group then raises the exception
    so the group unwinds with it, which is what reaches the sample runner.
    """
    from inspect_ai.agent._bridge.sandbox.bridge import _monitor_failure
    from inspect_ai.util._anyio import inner_exception

    bridge = _bridge_with_tools([raising_tool(KeyError("missing"))])
    execute = call_tool(bridge)
    scaffold_replies: list[str] = []

    async def scaffold() -> None:
        try:
            await execute("srv", "raising_tool", {"text": "hi"})
        except KeyError as ex:
            scaffold_replies.append(str(ex))
        # the scaffold carries on regardless; the monitor tears the group down
        await anyio.sleep(30)

    try:
        # without the signal the monitor waits forever: bound the wait so a
        # regression fails rather than hangs
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:
                tg.start_soon(_monitor_failure, bridge)
                tg.start_soon(scaffold)
    except Exception as ex:
        error = inner_exception(ex)
    else:
        raise AssertionError("task group completed without the tool's exception")

    assert isinstance(error, KeyError)
    assert scaffold_replies == ["'missing'"]


@tool
def raising_group_tool():
    async def execute(text: str) -> str:
        """Fail with a bug and a termination together, as a task group can.

        Args:
            text: Ignored.
        """
        raise ExceptionGroup(
            "mixed", [KeyError("missing"), TerminateSampleError("tool says stop")]
        )

    return execute


@pytest.mark.parametrize(
    ("host_tool", "ended_by", "reply", "failure_requested"),
    [
        pytest.param(
            raising_tool(TerminateSampleError("tool says stop")),
            TerminateSampleError,
            "Terminating: tool says stop",
            False,
            id="terminate",
        ),
        pytest.param(
            raising_in_task_group_tool(TerminateSampleError("tool says stop")),
            TerminateSampleError,
            "Terminating: tool says stop",
            False,
            id="grouped-terminate",
        ),
        pytest.param(
            raising_group_tool(),
            TerminateSampleError,
            "Terminating: tool says stop",
            False,
            id="bug-and-terminate",
        ),
        pytest.param(
            raising_tool(KeyError("missing")),
            KeyError,
            "Error calling method call_tool: 'missing'",
            True,
            id="bug",
        ),
    ],
)
async def test_bridged_tool_failure_through_the_service_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
    host_tool: Tool,
    ended_by: type[Exception],
    reply: str,
    failure_requested: bool,
) -> None:
    """Each failure ends the sample by exactly one path, after at most one RPC reply.

    A termination is the service dispatcher's: it answers the RPC and propagates
    the termination out of the service task, so the bridge's monitor is not also
    signalled. Any other unexpected exception is answered as an RPC error and
    signalled through `bridge.request_fail`, so the monitor raises it.
    """
    from inspect_ai.tool._tool_def import ToolDef

    bridge = _bridge_with_tools([host_tool])
    replies: list[str | None] = []
    service = dispatching_service(
        monkeypatch,
        "call_tool",
        call_tool(bridge),
        {"server": "srv", "tool": ToolDef(host_tool).name, "arguments": {"text": "hi"}},
        replies,
    )

    unwound = await serve_beside_failure_monitor(service, bridge)

    assert [type(ex) for ex in unwound] == [ended_by]
    # the monitor's teardown may pre-empt the reply to a failed call (see
    # `call_tool`); trio's randomized scheduling sometimes lets it
    pre_empted = failure_requested and current_async_library() == "trio"
    assert replies == [reply] or (pre_empted and replies == [])
    assert bridge._failure_requested.is_set() == failure_requested


@pytest.mark.parametrize("outer_cause", [False, True])
async def test_bridged_tool_fatal_group_member_is_not_mapped_from_its_context(
    outer_cause: bool,
) -> None:
    """A handled ToolError in a failing group's context leaves the call fatal."""
    # the group's member and its context were ordered by a set: try fresh ones
    for _ in range(20):
        with pytest.raises(ExceptionGroup) as excinfo:
            await fail_in_a_group_with_handled_context(outer_cause)
        outcome = _raised(excinfo.value, "srv_tool", None)
        assert outcome.error is None
        assert outcome.fatal is excinfo.value.exceptions[0]


class _IdleProxy:
    """A model proxy process that runs until killed and emits nothing."""

    def __aiter__(self) -> "_IdleProxy":
        return self

    async def __anext__(self) -> None:
        await anyio.sleep_forever()

    async def kill(self) -> None:
        pass


async def test_bridged_termination_survives_the_scaffold_exiting_on_its_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host tool's termination ends the sample even if the scaffold exits on its reply.

    The dispatcher publishes the RPC reply, then removes the request file with
    one more sandbox exec. A scaffold that reads `Terminating: ...` and exits
    lets the agent body leave `sandbox_agent_bridge` during that exec, and the
    bridge's cleanup then unwinds the service task. The termination must still
    reach the sample runner.
    """
    import inspect_ai.agent._bridge.sandbox.bridge as bridge_module

    replied = anyio.Event()

    async def run_model_service(
        sandbox: object,
        web_search: object,
        code_execution: object,
        bridge: "SandboxAgentBridge",
        instance: str,
        started: anyio.Event,
    ) -> None:
        service = dispatching_service(
            monkeypatch,
            "call_tool",
            call_tool(bridge),
            {"server": "srv", "tool": "raising_tool", "arguments": {"text": "hi"}},
            [],
        )

        async def write_response(
            request_file: str,
            request_id: str,
            result: JsonValue | None,
            error: str | None = None,
        ) -> None:
            # writing the response file, then removing the request file, are
            # each a sandbox exec; the scaffold sees the reply between them
            await anyio.sleep(0.01)
            replied.set()
            await anyio.sleep(0.05)

        monkeypatch.setattr(service, "_write_response", write_response)
        started.set()
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
        await anyio.sleep_forever()

    class FakeSandbox:
        _tools_user = None

        async def exec_remote(self, cmd: list[str], options: object) -> _IdleProxy:
            return _IdleProxy()

    async def sandbox_with_injected_tools(*, sandbox_name: str | None = None) -> object:
        return FakeSandbox()

    monkeypatch.setattr(bridge_module, "run_model_service", run_model_service)
    monkeypatch.setattr(
        bridge_module, "sandbox_with_injected_tools", sandbox_with_injected_tools
    )

    with pytest.raises(TerminateSampleError, match="stop"):
        with anyio.fail_after(10):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv",
                        tools=[raising_tool(TerminateSampleError("stop"))],
                        require_proposal=False,
                    )
                ]
            ):
                # the scaffold reads the reply and exits
                await replied.wait()


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_host_tool_exception_ends_the_sample() -> None:
    """An unexpected host tool exception must reach the sample runner via MCP.

    The bridge unwinds the agent as soon as the failure is signalled (usually
    before the MCP error reply reaches the caller, so the reply is not asserted
    here; the service-level test covers it), and the sample ends in error as
    with a native tool exception.
    """
    completed: list[bool] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv",
                        tools=[raising_tool(KeyError("missing"))],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                try:
                    await call_mcp_tool(config, "raising_tool", {"text": "hi"})
                except Exception:
                    pass
                # must not be reached: the failure unwinds the bridge
                await anyio.sleep(30)
                completed.append(True)
            return state

        return solve

    log = eval(bridged_tools_task(test_solver()), model=get_model("mockllm/model"))[0]

    assert log.status == "error"
    assert log.error is not None
    assert "KeyError" in log.error.message
    assert completed == []


@pytest.mark.parametrize(
    "service_failure",
    [
        pytest.param(TerminateSampleError("stop now"), id="terminate"),
        pytest.param(RuntimeError("ordinary failure"), id="ordinary-error"),
    ],
)
@pytest.mark.parametrize(
    "service_cancelled", [False, True], ids=["raised", "cancelled-mid-reply"]
)
async def test_bridge_exit_keeps_a_termination_the_scaffold_outran(
    monkeypatch: pytest.MonkeyPatch,
    service_failure: Exception,
    service_cancelled: bool,
) -> None:
    """A termination survives the scaffold finishing before it is raised.

    Runs the real `sandbox_agent_bridge` exit with sandbox and proxy I/O faked.
    The service method fails, the dispatcher writes its reply, and the scaffold
    returns from the bridge body on reading it, while the reply's request-file
    removal is still running. The service then either raises once the proxy is
    killed, or is cancelled mid-removal by the bridge's teardown. A termination
    must end the bridge either way. Negative control: after an ordinary error
    reply the service fails in teardown, which once the agent completed is
    still only logged as a cleanup error.
    """
    from test_helpers.service_dispatch import dispatching_service

    from inspect_ai.agent._bridge.sandbox import bridge as bridge_module
    from inspect_ai.util._sandbox.service import SandboxService

    reply_readable = anyio.Event()
    proxy_killed = anyio.Event()
    handler_done = anyio.Event()
    replies: list[str | None] = []

    class Proxy:
        async def kill(self) -> None:
            proxy_killed.set()
            if not service_cancelled:
                await handler_done.wait()

    class Sandbox:
        _tools_user = "root"

        async def exec_remote(self, **kwargs: object) -> Proxy:
            return Proxy()

    async def sandbox_with_injected_tools(**kwargs: object) -> Sandbox:
        return Sandbox()

    async def monitor_proxy(proxy: Proxy) -> None:
        await anyio.sleep_forever()

    async def run_model_service(
        sandbox: object,
        web_search: object,
        code_execution: object,
        bridge: object,
        instance: str,
        started: anyio.Event,
    ) -> None:
        async def method() -> str:
            raise service_failure

        service = dispatching_service(monkeypatch, "stop", method, {}, replies)
        service._responses_dir = "/resp"

        async def write_text_file(directory: str, name: str, contents: str) -> None:
            replies.append(json.loads(contents)["error"])
            reply_readable.set()

        async def remove_request_file(request_file: str) -> None:
            await proxy_killed.wait()
            if service_cancelled:
                await anyio.sleep_forever()

        monkeypatch.setattr(service, "_write_text_file", write_text_file)
        monkeypatch.setattr(service, "_remove_request_file", remove_request_file)
        monkeypatch.setattr(
            service,
            "_write_response",
            SandboxService._write_response.__get__(service),
        )
        started.set()
        try:
            await service._handle_request_tracked("/req/r1.json", "r1")
        finally:
            handler_done.set()
        raise RuntimeError("service teardown")

    monkeypatch.setattr(
        bridge_module, "sandbox_with_injected_tools", sandbox_with_injected_tools
    )
    monkeypatch.setattr(bridge_module, "run_model_service", run_model_service)
    monkeypatch.setattr(bridge_module, "_monitor_proxy", monitor_proxy)

    warnings: list[str] = []
    monkeypatch.setattr(
        bridge_module.logger,
        "warning",
        lambda message, *a, **k: warnings.append(message),
    )
    terminated: TerminateSampleError | None = None
    with anyio.fail_after(10):
        try:
            async with bridge_module.sandbox_agent_bridge():
                # the scaffold reads its reply and returns
                await reply_readable.wait()
        except TerminateSampleError as ex:
            terminated = ex

    if isinstance(service_failure, TerminateSampleError):
        assert terminated is service_failure
        assert replies == ["Terminating: stop now"]
        assert warnings == []
    else:
        assert terminated is None
        assert warnings == (
            []
            if service_cancelled
            else [
                "Error during sandbox_agent_bridge cleanup (agent completed "
                "successfully): service teardown"
            ]
        )
        assert replies == ["Error calling method stop: ordinary failure"]


def _assert_terminated_once(log: EvalLog, reason: str) -> None:
    """The sample ended by one termination with `reason`, not in error."""
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None, sample.error
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", reason)
    limits = [e for e in sample.events if e.event == "sample_limit"]
    assert [(e.type, e.message) for e in limits] == [("operator", reason)]


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_host_tool_terminate_ends_the_sample() -> None:
    """A host tool's `TerminateSampleError` ends the sample as a termination.

    The service dispatcher propagates it out of the service task, which unwinds
    the bridge's task group; the sample ends normally with an operator limit, as
    a native tool's termination does.
    """
    completed: list[bool] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv",
                        tools=[raising_tool(TerminateSampleError("tool says stop"))],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                try:
                    await call_mcp_tool(config, "raising_tool", {"text": "hi"})
                except Exception:
                    pass
                # must not be reached: the termination unwinds the bridge
                await anyio.sleep(30)
                completed.append(True)
            return state

        return solve

    log = eval(bridged_tools_task(test_solver()), model=get_model("mockllm/model"))[0]

    _assert_terminated_once(log, "tool says stop")
    assert completed == []


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_host_tool_error_does_not_end_the_sample() -> None:
    """A `ToolError` from a host tool is tool output for the model, as natively."""

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv",
                        tools=[raising_tool(ToolError("tool says no"))],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                response = await call_mcp_tool(config, "raising_tool", {"text": "hi"})
                assert "tool says no" in response["error"]["message"]
            return state

        return solve

    eval_bridged_tools_task(test_solver())


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_host_tool_timeout_is_recorded_with_the_native_error() -> None:
    """The scaffold reads the exception's own text; the event has the native wording."""
    responses: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv",
                        tools=[raising_tool(TimeoutError("tool-specific timeout"))],
                        require_proposal=False,
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                responses.append(
                    await call_mcp_tool(config, "raising_tool", {"text": "hi"})
                )
            return state

        return solve

    log = eval_bridged_tools_task(test_solver())

    assert responses[0]["error"]["message"].endswith("tool-specific timeout")
    [event] = host_tool_events(log)
    assert event.error is not None
    assert event.error.type == "timeout"
    assert event.error.message == "Command timed out before completing."


# =============================================================================
# Output limits
# =============================================================================
#
# A bridged tool's text result is truncated to the limit and in the format a
# native call gets (`truncate_tool_output`): the tool's own `max_output`, else
# `max_tool_output` from the active generate config, else 16 KiB.


@tool
def long_output_tool():
    async def execute(size: int) -> str:
        """Return `size` bytes of text.

        Args:
            size: Number of bytes to return.
        """
        return "x" * size

    return execute


@tool(max_output=8)
def capped_output_tool():
    async def execute(size: int) -> str:
        """Return `size` bytes of text, with an 8 byte output limit.

        Args:
            size: Number of bytes to return.
        """
        return "x" * size

    return execute


@tool
def long_structured_tool():
    async def execute(size: int) -> dict[str, str]:
        """Return a structured result holding `size` bytes of text.

        Args:
            size: Number of bytes of text.
        """
        return {"data": "x" * size}

    return execute


@tool
def long_content_tool():
    async def execute(size: int) -> list[ContentText]:
        """Return `size` bytes of text as content.

        Args:
            size: Number of bytes of text.
        """
        return [ContentText(text="x" * size)]

    return execute


@contextmanager
def max_tool_output(limit: int | None) -> Iterator[None]:
    """Set `max_tool_output` in the active generate config."""
    token = active_generate_config_context_var.set(
        GenerateConfig(max_tool_output=limit)
    )
    try:
        yield
    finally:
        active_generate_config_context_var.reset(token)


async def test_bridged_tool_result_over_default_limit_is_truncated() -> None:
    bridge = _bridge_with_tools([long_output_tool()])
    text = "x" * (20 * 1024)

    result = await call_tool(bridge)("srv", "long_output_tool", {"size": len(text)})

    expected = truncate_tool_output("long_output_tool", text, None)
    assert expected is not None
    assert result == expected.output
    assert isinstance(result, str)
    assert result.startswith(
        "\nThe output of your call to long_output_tool was too long"
    )
    assert "x" * (16 * 1024) in result
    assert "x" * (16 * 1024 + 1) not in result


async def test_bridged_tool_result_follows_max_tool_output() -> None:
    bridge = _bridge_with_tools([long_output_tool()])

    with max_tool_output(10):
        result = await call_tool(bridge)("srv", "long_output_tool", {"size": 50})
        expected = truncate_tool_output("long_output_tool", "x" * 50, None)

    assert expected is not None
    assert result == expected.output
    assert "\n" + "x" * 10 + "\n" in expected.output


async def test_bridged_tool_result_within_limit_is_unchanged() -> None:
    bridge = _bridge_with_tools([long_output_tool()])

    with max_tool_output(10):
        result = await call_tool(bridge)("srv", "long_output_tool", {"size": 10})

    assert result == "x" * 10


async def test_bridged_tool_max_output_wins_over_max_tool_output() -> None:
    bridge = _bridge_with_tools([capped_output_tool()])

    with max_tool_output(1000):
        result = await call_tool(bridge)("srv", "capped_output_tool", {"size": 50})

    expected = truncate_tool_output("capped_output_tool", "x" * 50, 8)
    assert expected is not None
    assert result == expected.output


async def test_bridged_tool_structured_result_is_truncated_as_json() -> None:
    bridge = _bridge_with_tools([long_structured_tool()])

    with max_tool_output(10):
        result = await call_tool(bridge)("srv", "long_structured_tool", {"size": 50})
        expected = truncate_tool_output(
            "long_structured_tool", to_json_str_safe({"data": "x" * 50}), None
        )

    assert expected is not None
    assert result == expected.output


async def test_bridged_tool_content_result_is_not_truncated() -> None:
    """Content results aren't truncated natively, so neither are they here."""
    bridge = _bridge_with_tools([long_content_tool()])

    with max_tool_output(10):
        result = await call_tool(bridge)("srv", "long_content_tool", {"size": 50})

    assert result == to_json_str_safe([ContentText(text="x" * 50)])


@pytest.mark.parametrize("limit", [1024, None], ids=["max_tool_output", "default"])
@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_records_the_result_the_scaffold_received(
    limit: int | None,
) -> None:
    responses: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(
                        name="srv", tools=[long_output_tool()], require_proposal=False
                    )
                ]
            ) as bridge:
                config = bridge.mcp_server_configs[0]
                responses.append(
                    await call_mcp_tool(config, "long_output_tool", {"size": 4096})
                )
            return state

        return solve

    log = eval(
        bridged_tools_task(test_solver()),
        model=get_model("mockllm/model"),
        max_tool_output=limit,
    )[0]

    assert log.status == "success"
    text = responses[0]["result"]["content"][0]["text"]
    [event] = host_tool_events(log)
    assert event.result == text
    if limit is None:
        assert text == "x" * 4096
        assert event.truncated is None
    else:
        assert "was too long to be displayed" in text
        assert "\n" + "x" * 1024 + "\n" in text
        assert event.truncated == (4096, 1024)


# =============================================================================
# Large arguments
# =============================================================================


@tool
def echo_text():
    async def execute(text: str) -> str:
        """Return `text`.

        Args:
            text: Text to return.
        """
        return text

    return execute


class PeakPythonMemory:
    """Peak Python heap growth from now until `stop()`, traced with `tracemalloc`.

    Unlike the process RSS, the traced peak does not depend on what the
    allocator kept from earlier tests (or an earlier attempt of this one).
    """

    def __init__(self) -> None:
        import tracemalloc

        self._started = not tracemalloc.is_tracing()
        if self._started:
            tracemalloc.start()
        tracemalloc.reset_peak()
        self.baseline, _ = tracemalloc.get_traced_memory()

    def stop(self) -> int:
        """Stop tracing and return the peak growth over the baseline, in bytes."""
        import tracemalloc

        _, peak = tracemalloc.get_traced_memory()
        if self._started:
            tracemalloc.stop()
        return peak - self.baseline


@pytest.mark.parametrize("char", ["x", "é"], ids=["ascii", "non-ascii"])
@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_records_a_large_denied_call_within_a_memory_bound(
    char: str,
) -> None:
    """A denied call near the proxy's 50 MiB body cap is recorded and condensed.

    Arguments are not capped beyond the request limits, so the record holds
    them whole. The non-ASCII case reaches about 135 MiB once the proxy
    re-serializes the request with escapes, near the service's 150 MiB read
    limit. Peak Python heap growth while the call is read, recorded and the
    log is written must stay within four times the request the service reads.
    """
    body_bytes = 45 * 1024 * 1024
    text = char * (body_bytes // len(char.encode()))
    service_request_bytes = len(json.dumps(text))
    measured: list[PeakPythonMemory] = []
    responses: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[BridgedToolsSpec(name="srv", tools=[echo_text()])]
            ) as bridge:
                request = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "echo_text", "arguments": {"text": text}},
                    },
                    ensure_ascii=False,
                ).encode()
                await sandbox().write_file("/tmp/request.json", request)
                del request
                measured.append(PeakPythonMemory())
                result = await sandbox().exec(
                    [
                        "curl",
                        "-s",
                        "-X",
                        "POST",
                        "-H",
                        "Content-Type: application/json",
                        "--data-binary",
                        "@/tmp/request.json",
                        bridge.mcp_server_configs[0].url,
                    ],
                    timeout=300,
                )
                assert result.success, result.stderr
                responses.append(json.loads(result.stdout))
            return state

        return solve

    log = eval_bridged_tools_task(test_solver())
    growth = measured[0].stop()

    assert "was not proposed by the model" in responses[0]["error"]["message"]
    [event] = host_tool_events(log)
    assert event.error is not None and event.error.type == "permission"
    assert log.samples is not None
    stored = log.samples[0].attachments
    reference = event.arguments["text"]
    assert isinstance(reference, str) and reference.startswith("attachment://")
    assert stored[reference.removeprefix("attachment://")] == text
    assert growth <= 4 * service_request_bytes, (
        f"peak Python heap growth {growth / 2**20:.0f} MiB for a "
        f"{service_request_bytes / 2**20:.0f} MiB request"
    )
