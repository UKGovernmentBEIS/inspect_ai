# NOTE: This example is intended as a demonstration of the basic mechanics of using the
# sandbox agent bridge. For a more feature-rich implementation of a Gemini CLI agent
# for Inspect see <https://meridianlabs-ai.github.io/inspect_swe/>.

from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import ChatMessageSystem, ChatMessageUser
from inspect_ai.util import sandbox


@agent
def gemini() -> Agent:
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
                    "gemini",
                    "--model",
                    "inspect",
                    "--yolo",  # Auto-approve all actions (required for non-interactive)
                    "--output-format",
                    "text",
                    prompt,  # Positional argument at end
                ],
                env={
                    "GOOGLE_GEMINI_BASE_URL": f"http://localhost:{bridge.port}",
                    "GEMINI_API_KEY": "sk-inspect-bridge",
                    "HOME": "/tmp",  # Gemini CLI needs a home directory
                },
            )

        if result.success:
            return bridge.state
        else:
            raise RuntimeError(f"Error executing gemini agent: {result.stderr}")

    return execute
