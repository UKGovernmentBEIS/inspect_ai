from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import user_prompt
from inspect_ai.util import sandbox


@agent
def codex() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        # Use bridge to map OpenAI API to Inspect within the sandbox
        async with sandbox_agent_bridge() as bridge:
            # extract prompt from last user message
            prompt = user_prompt(state.messages)

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
                    prompt.text,
                ],
                env={
                    "OPENAI_BASE_URL": f"http://localhost:{bridge.port}/v1",
                    "RUST_LOG": "codex_core=debug,codex_tui=debug",
                },
            )

        print(result.stdout)
        print(result.stderr)

        if result.success:
            return bridge.state
        else:
            raise RuntimeError(f"Error executing codex agent: {result.stderr}")

    return execute
