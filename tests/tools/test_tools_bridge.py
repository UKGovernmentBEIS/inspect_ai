"""Tests for MCP tools bridge functionality.

These tests verify that host-side Inspect tools can be exposed to sandboxed agents
via the MCP protocol using BridgedToolsSpec and sandbox_agent_bridge.
"""

import json

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai.agent import BridgedToolsSpec, sandbox_agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import Solver, solver
from inspect_ai.tool import tool
from inspect_ai.util import sandbox

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


# =============================================================================
# Test helpers
# =============================================================================


@task
def bridged_tools_task(test_solver: Solver):
    return Task(
        dataset=[Sample(input="Test", target="Test")],
        solver=[test_solver],
        scorer=includes(),
        sandbox="docker",
    )


def eval_bridged_tools_task(test_solver: Solver) -> EvalLog:
    log = eval(bridged_tools_task(test_solver), model=get_model("mockllm/model"))[0]
    assert log.status == "success"
    return log


async def call_mcp_tool(script_path: str, tool_name: str, arguments: dict) -> dict:
    """Send a tools/call JSON-RPC request to MCP server and return parsed response."""
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    result = await sandbox().exec(
        cmd=["python3", script_path],
        input=request + "\n",
        timeout=30,
    )
    return json.loads(result.stdout.strip())


async def call_mcp_tools_list(script_path: str) -> dict:
    """Send a tools/list JSON-RPC request to MCP server and return parsed response."""
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    result = await sandbox().exec(
        cmd=["python3", script_path],
        input=request + "\n",
        timeout=30,
    )
    return json.loads(result.stdout.strip())


# =============================================================================
# E2E tests with Docker sandbox - actually invoke MCP server
# =============================================================================


@skip_if_no_docker
@pytest.mark.slow
def test_single_tool_call_returns_correct_result() -> None:
    """Call a single bridged tool via MCP and verify the result."""
    call_log: list[dict] = []

    @solver
    def test_solver():
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(name="calc", tools=[calculator_add(call_log)])
                ]
            ) as bridge:
                script_path = bridge.mcp_server_configs[0].args[0]
                response = await call_mcp_tool(
                    script_path, "calculator_add", {"x": 5, "y": 3}
                )

                assert response["jsonrpc"] == "2.0"
                assert response["id"] == 1
                assert response["result"]["content"][0]["text"] == "8"

            return state

        return solve

    eval_bridged_tools_task(test_solver())

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
                    )
                ]
            ) as bridge:
                script_path = bridge.mcp_server_configs[0].args[0]

                add_response = await call_mcp_tool(
                    script_path, "calculator_add", {"x": 10, "y": 20}
                )
                assert add_response["result"]["content"][0]["text"] == "30"

                data_response = await call_mcp_tool(
                    script_path, "get_structured_data", {"key": "foo"}
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
                    BridgedToolsSpec(name="calc", tools=[calculator_add(call_log)]),
                    BridgedToolsSpec(
                        name="data", tools=[get_structured_data(call_log)]
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
                    calc_config.args[0], "calculator_add", {"x": 100, "y": 200}
                )
                assert calc_response["result"]["content"][0]["text"] == "300"

                data_response = await call_mcp_tool(
                    data_config.args[0], "get_structured_data", {"key": "bar"}
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
                script_path = bridge.mcp_server_configs[0].args[0]
                response = await call_mcp_tools_list(script_path)

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
