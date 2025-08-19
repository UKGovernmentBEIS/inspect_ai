from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.tool import mcp_server_http


@task
def remote_mcp():
    deepwiki = mcp_server_http(
        name="deepwiki", url="https://mcp.deepwiki.com/mcp", execution="remote"
    )

    dataset = [
        Sample(
            input="What transport protocols are supported in the 2025-03-26 version of the MCP spec?",
        )
    ]

    return Task(
        dataset=dataset,
        solver=react(tools=[deepwiki]),
    )
