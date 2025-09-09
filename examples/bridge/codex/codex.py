# NOTE: This example is intended as a demonstration of the basic mechanics of using the
# sandbox agent bridge. For a more feature-rich implementation of a Codex CLI agent for
# Inspectsee <https://meridianlabs-ai.github.io/inspect_swe/>

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
