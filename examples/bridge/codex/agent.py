from rollout import rollout_log_to_messages

from inspect_ai.agent import (
    Agent,
    AgentState,
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
                    "--output-last-message",
                    last_message,
                    prompt.text,
                ],
                env={
                    "OPENAI_BASE_URL": f"http://localhost:{bridge.port}/v1",
                },
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


async def read_codex_messages() -> list[ChatMessage]:
    result = await sandbox().exec(
        ["bash", "-c", "cat .codex/sessions/*/*/*/*rollout-*.jsonl"]
    )
    if not result.success:
        raise RuntimeError(f"Error reading codex messages: {result.stderr}")
    return rollout_log_to_messages(result.stdout)
