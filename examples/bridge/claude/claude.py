from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import ChatMessageSystem, ChatMessageUser
from inspect_ai.util import sandbox


@agent
def claude_code() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with sandbox_agent_bridge(state) as bridge:
            # base options
            cmd = [
                "claude",
                "--print",  # run without interactions
                "--dangerously-skip-permissions",
                "--model",  # use current inspect model
                "inspect",
            ]

            # system message
            system_message = "\n\n".join(
                [m.text for m in state.messages if isinstance(m, ChatMessageSystem)]
            )
            if system_message:
                cmd.extend(["--append-system-prompt", system_message])

            # user prompt
            prompt = "\n\n".join(
                [m.text for m in state.messages if isinstance(m, ChatMessageUser)]
            )
            cmd.append(prompt)

            # execute the agent
            result = await sandbox().exec(
                cmd=cmd,
                env={
                    "ANTHROPIC_BASE_URL": f"http://localhost:{bridge.port}",
                    "ANTHROPIC_API_KEY": "sk-ant-api03-DOq5tyLPrk9M4hPE",
                    "ANTHROPIC_SMALL_FAST_MODEL": "inspect",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "IS_SANDBOX": "1",
                },
            )

        if result.success:
            return bridge.state
        else:
            raise RuntimeError(
                f"Error executing claude code agent: {result.stdout}\n{result.stderr}"
            )

    return execute
