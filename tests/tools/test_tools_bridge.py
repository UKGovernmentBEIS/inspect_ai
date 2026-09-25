"""Tests for MCP tools bridge functionality.

These tests verify that host-side Inspect tools can be exposed to sandboxed agents
via the MCP protocol using BridgedToolsSpec and sandbox_agent_bridge.
"""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent import BridgedToolsSpec, sandbox_agent_bridge
from inspect_ai.agent._bridge.sandbox.service import call_tool
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.model._call_tools import tool_call_error
from inspect_ai.scorer import includes
from inspect_ai.solver import Solver, solver
from inspect_ai.tool import ToolError, tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.util import sandbox
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.limits import OutputLimitExceededError

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

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


async def _mcp_http_request_with_retry(
    url: str, request: str, max_retries: int = 30, retry_delay: float = 0.5
) -> dict:
    """Send HTTP POST to MCP endpoint with retry logic for server startup."""
    import asyncio

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

    eval_bridged_tools_task(test_solver(), sandbox)

    assert call_log == [{"tool": "calculator_add", "x": 5, "y": 3}]


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

    eval_bridged_tools_task(test_solver())

    assert call_log == []
    # the denial reaches the agent intact as the JSON-RPC error message (the
    # sandbox service prefixes it with the failing RPC method)
    assert seen[0]["error"]["message"].endswith(
        "Host tool call 'calc/calculator_add' was not proposed by the model in a "
        "bridged generation (a bridged host tool runs once per proposed call)"
    )


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


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_terminate_ends_the_sample() -> None:
    """`terminate` must reach the sample runner from the sandbox service task.

    The service converts exceptions into RPC error responses, so this exercises
    the monitor task in the bridge's own task group — the path that actually
    unwinds the agent.
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

    assert log.status == "success"
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
# `ToolCallError` and fails the sample on anything else. The bridge's `call_tool`
# runs in the sandbox service task, where an exception only becomes an RPC error
# the scaffold reads as tool output, so an unexpected one has to be signalled to
# the bridge's monitor task to end the sample the same way.


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
