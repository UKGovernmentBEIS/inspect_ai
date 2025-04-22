from copy import copy
from pathlib import Path
from typing import Sequence

import pytest
from test_helpers.utils import (
    skip_if_no_docker,
    skip_if_no_mcp_fetch_package,
    skip_if_no_mcp_git_package,
    skip_if_no_mcp_package,
    skip_if_no_openai,
)

from inspect_ai import Task, eval, task
from inspect_ai._util.environ import environ_var
from inspect_ai.agent import Agent, AgentState, agent, react
from inspect_ai.dataset import Dataset, MemoryDataset, Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessage, ChatMessageSystem
from inspect_ai.model._model import Model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver import generate, solver, use_tools
from inspect_ai.tool import (
    MCPServer,
    mcp_connection,
    mcp_server_sandbox,
    mcp_server_stdio,
    mcp_tools,
)
from inspect_ai.tool._tool import Tool, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util import sandbox


@skip_if_no_mcp_fetch_package
async def test_mcp_server_stdio():
    server = mcp_server_stdio(command="python", args=["-m", "mcp_server_fetch"])
    async with mcp_connection(server):
        await check_fetch_server(server)


# TODO: make this test work
# @pytest.mark.slow
# def test_mcp_server_sandbox_fetch():
#     log = eval(fetch_task(), model="openai/gpt-4o")[0]
#     assert log.status == "success"
#     assert log.samples


@task
def fetch_task():
    fetch_server = mcp_server_sandbox(
        command="python3", args=["-m", "mcp_server_fetch"]
    )

    return Task(
        dataset=[
            Sample(
                "Use the fetch tool to read the website at https://example.com/, then please tell me what is there."
            ),
        ],
        solver=react(
            name="fetch_worker",
            prompt="Please use the fetch tools to solve the problem.",
            tools=[mcp_tools(fetch_server)],
        ),
        sandbox="docker",
    )


# to run this test:
# git clone https://github.com/modelcontextprotocol/python-sdk
# cd pip install python-sdk/examples/servers/simple-tool/
# mcp-simple-tool --transport sse --port 8000
#
# async def test_mcp_server_sse():
#     async with mcp_server_sse(url="http://localhost:8000/sse") as server:
#         await check_fetch_server(server)


async def check_fetch_server(server: MCPServer) -> None:
    _, output = await get_model("openai/gpt-4o").generate_loop(
        "Use the fetch tool to read the website at https://example.com/, then please tell me what is there.",
        tools=server,
    )
    assert "example.com" in output.completion


@task
def git_task():
    git_server = mcp_server_stdio(
        command="python3", args=["-m", "mcp_server_git", "--repository", "."]
    )

    return Task(
        dataset=[Sample("What is the status of the git working tree?")],
        solver=[use_tools(mcp_tools(git_server, tools=["*_status"])), generate()],
    )


@skip_if_no_openai
@skip_if_no_mcp_git_package
def test_mcp_filter():
    log = eval(git_task(), model="openai/gpt-4o")[0]
    assert log.status == "success"
    assert log.samples


def git_server() -> MCPServer:
    return mcp_server_stdio(
        command="python3", args=["-m", "mcp_server_git", "--repository", "."]
    )


def git_dataset() -> Dataset:
    return MemoryDataset(
        [
            Sample(
                "What is the status of the git working tree for the current directory?"
            ),
            Sample(
                "Can you tell me the git working tree status for the current directory?"
            ),
        ]
    )


@task
def git_task_react_mcp_connection():
    return Task(
        dataset=git_dataset(),
        solver=react(
            name="git_worker",
            prompt="Please use the git tools to solve the problem.",
            tools=[mcp_tools(git_server(), tools=["git_status"])],
        ),
    )


@skip_if_no_openai
@skip_if_no_mcp_git_package
def test_react_mcp_connection():
    log = eval(git_task_react_mcp_connection(), model="openai/gpt-4o")[0]
    assert log.status == "success"
    assert log.samples


@task
def git_task_mcp_connection_refcount():
    async def generate_loop(
        model: Model,
        input: list[ChatMessage],
        tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource = [],
    ) -> tuple[list[ChatMessage], ModelOutput]:
        async with mcp_connection(tools):
            messages = copy(input)
            while True:
                # call model
                output = await model.generate(input=messages, tools=tools)
                messages.append(output.message)

                # make tool calls or terminate if there are none
                if output.message.tool_calls:
                    tools_messages, tools_output = await execute_tools(messages, tools)
                    messages.extend(tools_messages)
                    if tools_output is not None:
                        output = tools_output
                else:
                    return messages[len(input) :], output

    @agent
    def git_agent() -> Agent:
        git_server = mcp_server_stdio(
            command="python3", args=["-m", "mcp_server_git", "--repository", "."]
        )

        async def execute(state: AgentState) -> AgentState:
            # some general guidance for the agent
            state.messages.append(
                ChatMessageSystem(
                    content="Please use the git tools to solve the problems."
                )
            )

            # run a tool loop then update & return state
            async with mcp_connection(git_server):
                messages, state.output = await generate_loop(
                    get_model(), state.messages, tools=git_server
                )
            state.messages.extend(messages)
            return state

        return execute

    return Task(
        dataset=[
            Sample(
                "What is the status of the git working tree for the current directory?. Additionally, "
                + "could you summarise recent commits that have been made to the reposiotry?"
            ),
            Sample(
                "Could you summarise recent commits that have been made to the repository?. Also, What "
                + "is the status of the git working tree for the current directory?"
            ),
        ],
        solver=git_agent(),
        config=GenerateConfig(parallel_tool_calls=False),
    )


@skip_if_no_openai
@skip_if_no_mcp_git_package
def test_mcp_connection_refcount():
    log = eval(git_task_mcp_connection_refcount(), model="openai/gpt-4o")[0]
    assert log.status == "success"
    assert log.samples


@pytest.mark.asyncio
@skip_if_no_openai
@skip_if_no_mcp_package
async def test_mcp_sampling_fn():
    from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

    from inspect_ai.tool._mcp.sampling import sampling_fn

    with environ_var("INSPECT_EVAL_MODEL", "openai/gpt-4o"):
        result = await sampling_fn(
            None,
            CreateMessageRequestParams(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text="What color is the sky?"),
                    )
                ],
                systemPrompt="You are a helpful assistant.",
                temperature=0.8,
                maxTokens=2048,
            ),
        )
        assert result.role == "assistant"
        assert isinstance(result.content, TextContent)
        assert "sky" in result.content.text or "mockllm" in result.content.text


@pytest.mark.slow
@skip_if_no_docker
def test_mcp_server_sandbox_nodejs():
    @solver
    def run_mcp_server():
        async def solve(state, generate):
            result = await sandbox().exec(["mcp-server-filesystem", "/"])
            if "MCP Filesystem Server" not in result.stderr:
                raise ValueError("Failed to run server")

            return state

        return solve

    dockerfile = Path(__file__).parent / "docker-mcp-server" / "Dockerfile"
    log = eval(
        Task(solver=[run_mcp_server()], sandbox=("docker", dockerfile.as_posix()))
    )[0]
    assert log.status == "success"
