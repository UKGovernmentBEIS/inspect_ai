from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import ChatMessageSystem, ChatMessageUser
from inspect_ai.util import sandbox


@agent
def codex() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with sandbox_agent_bridge(state) as bridge:
            # extract prompt message text
            prompt = "\n\n".join(
                [
                    message.text
                    for message in state.messages
                    if isinstance(message, ChatMessageUser | ChatMessageSystem)
                ]
            )

            # execute the agent
            result = await sandbox().exec(
                cmd=[
                    "codex",
                    "exec",
                    "--model",
                    "inspect",
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--color",
                    "never",
                    prompt,
                ],
                env={
                    "OPENAI_BASE_URL": f"http://localhost:{bridge.port}/v1",
                },
            )

        if result.success:
            return bridge.state
        else:
            raise RuntimeError(f"Error executing codex agent: {result.stderr}")

    return execute
