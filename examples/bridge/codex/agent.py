from textwrap import dedent

from rollout import rollout_log_to_messages

from inspect_ai.agent import (
    Agent,
    AgentState,
    SandboxAgentBridge,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ModelOutput, user_prompt
from inspect_ai.util import sandbox


@agent
def codex() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        # Use bridge to map OpenAI API to Inspect within the sandbox
        async with sandbox_agent_bridge() as bridge:
            # extract prompt from last user message
            prompt = user_prompt(state.messages)

            # file to capture last agent message
            last_message = "last_message.txt"

            # register inspect profile w/ code (proxy url, etc.)
            await register_inspect_provider(bridge)

            # execute the agent
            result = await sandbox().exec(
                cmd=[
                    "codex",
                    "exec",
                    "--profile",
                    "inspect",
                    "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--color",
                    "never",
                    "--output-last-message",
                    last_message,
                    prompt.text,
                ]
            )

        if result.success:
            # append rollout history to messages
            state.messages.extend((await read_codex_messages())[1:])

            # read the response
            response_message = ChatMessageAssistant(
                content=await sandbox().read_file(last_message), source="generate"
            )

            # update and return state
            state.output = ModelOutput.from_message(response_message)
            state.messages.append(response_message)
            return state
        else:
            raise RuntimeError(f"Error executing codex agent: {result.stderr}")

    return execute


async def register_inspect_provider(bridge: SandboxAgentBridge) -> None:
    """Register a custom OpenAI-compatible model provider for the bridge."""
    CODEX_CONFIG = dedent(f"""
    [model_providers.inspect]
    name = "inspect"
    base_url = "http://localhost:{bridge.port}/v1"
    wire_api = "chat"

    [profiles.inspect]
    model_provider = "inspect"
    model = "inspect"
    """)
    result = await sandbox().exec(["mkdir", ".codex"])
    if not result.success:
        raise RuntimeError(f"Error creating codex config directory: {result.stderr}")
    await sandbox().write_file(".codex/config.toml", CODEX_CONFIG)


async def read_codex_messages() -> list[ChatMessage]:
    result = await sandbox().exec(
        ["bash", "-c", "cat .codex/sessions/*/*/*/*rollout-*.jsonl"]
    )
    if not result.success:
        raise RuntimeError(f"Error reading codex messages: {result.stderr}")
    return rollout_log_to_messages(result.stdout)
