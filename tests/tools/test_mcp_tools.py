import pytest
from test_helpers.utils import (
    skip_if_no_mcp_fetch_package,
    skip_if_no_mcp_git_package,
    skip_if_no_mcp_package,
    skip_if_no_openai,
)

from inspect_ai import Task, eval, task
from inspect_ai._util.environ import environ_var
from inspect_ai.agent._react import react
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import MCPServer, mcp_server_stdio, mcp_tools
from inspect_ai.tool._mcp.connection import mcp_connection


@skip_if_no_mcp_fetch_package
async def test_mcp_server_stdio():
    server = mcp_server_stdio(command="python", args=["-m", "mcp_server_fetch"])
    async with mcp_connection(server):
        await check_fetch_server(server)


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


@task
def git_task_react_mcp_connection():
    git_server = mcp_server_stdio(
        command="python3", args=["-m", "mcp_server_git", "--repository", "."]
    )

    return Task(
        dataset=[
            Sample(
                "What is the status of the git working tree for the current directory?"
            ),
            Sample(
                "Can you tell me the git working tree status for the current directory?"
            ),
        ],
        solver=react(
            name="git_worker",
            prompt="Please use the git tools to solve the problem.",
            tools=[mcp_tools(git_server, tools=["git_status"])],
        ),
    )


@skip_if_no_openai
@skip_if_no_mcp_git_package
def test_react_mcp_connection():
    log = eval(git_task_react_mcp_connection(), model="openai/gpt-4o")[0]
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
        assert "sky" in result.content.text
