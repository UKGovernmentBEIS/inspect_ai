from inspect_ai import Task, eval, task
from inspect_ai.agent._react import react
from inspect_ai.agent._with import agent_with
from inspect_ai.dataset import Sample
from inspect_ai.tool import mcp_server_stdio, mcp_tools


@task
def git_task_with_mcp_server():
    git_server = mcp_server_stdio(
        command="python3", args=["-m", "mcp_server_git", "--repository", "."]
    )

    return Task(
        dataset=[
            Sample("What is the status of the git working tree?"),
            Sample("Can you tell me the git working tree status?"),
        ],
        solver=agent_with(
            react(
                name="git_worker",
                prompt="Please use the git tools to solve the problem.",
                tools=[mcp_tools(git_server, tools=["*_status"])],
            ),
            mcp_servers=git_server,
        ),
    )


if __name__ == "__main__":
    eval(git_task_with_mcp_server(), model="openai/gpt-4o-mini")
