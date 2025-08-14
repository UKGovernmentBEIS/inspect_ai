from textwrap import dedent

from inspect_ai.agent import Agent, AgentState, agent, sandbox_agent_bridge
from inspect_ai.agent._bridge.sandbox.bridge import SandboxAgentBridge
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.util import sandbox


@agent
def codex_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        # extract input from first message
        prompt = state.messages[0].text

        # file for agent output
        agent_output = "agent_output.txt"

        # run the agent under the bridge
        async with sandbox_agent_bridge() as bridge:
            # inspect provider (proxy url, etc.)
            await register_inspect_provider(bridge)

            # execute the agent
            result = await sandbox().exec(
                cmd=[
                    "codex",
                    "exec",
                    "--profile",
                    "inspect",
                    "--skip-git-repo-check",
                    # "--full-auto",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--color",
                    "never",
                    "--json",
                    "--output-last-message",
                    agent_output,
                    prompt,
                ],
                env={"RUST_LOG": "codex_core=trace,codex_tui=trace"},
            )

        if result.success:
            # output = await sandbox().read_file(agent_output)
            output = result.stdout
            with open("stderr.txt", "w") as f:
                f.write(result.stderr)
            state.output = ModelOutput.from_content(str(get_model()), output)
            return state
        else:
            raise RuntimeError(f"Error executing codex agent: {result.stderr}")

    return execute


async def register_inspect_provider(bridge: SandboxAgentBridge) -> None:
    # register a custom open-ai compatible model provider
    CODEX_CONFIG = dedent(f"""
    [model_providers.inspect]
    name = "inspect"
    base_url = "http://localhost:{bridge.port}/v1"

    [profiles.inspect]
    model_provider = "inspect"
    model = "inspect"
    """)
    await sandbox().exec(["mkdir", ".codex"])
    await sandbox().write_file(".codex/config.toml", CODEX_CONFIG)
