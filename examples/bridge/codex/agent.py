import json
from textwrap import dedent
from typing import Literal, TypeAlias, TypedDict

from pydantic import JsonValue

from inspect_ai.agent import (
    Agent,
    AgentState,
    SandboxAgentBridge,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentText,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import ToolCall
from inspect_ai.util import sandbox


@agent
def codex() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        # extract prompt from first message
        prompt = state.messages[0].text

        # file to capture last agent message
        last_message = "last_message.txt"

        # run the agent under the bridge
        async with sandbox_agent_bridge() as bridge:
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
                    prompt,
                ]
            )

        if result.success:
            # convert rollout history to messages
            messages = await read_codex_messages()

            # read and append the last message
            model_name = get_model().api.model_name
            last_message = await sandbox().read_file(last_message)
            messages.append(
                ChatMessageAssistant(
                    content=last_message, source="generate", model=model_name
                )
            )

            # update and return state
            state.messages = messages
            state.output = ModelOutput.from_content(model_name, last_message)
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
    return rollout_to_messages(result.stdout)


class FunctionCall(TypedDict):
    type: Literal["function_call"]
    name: str
    arguments: str
    call_id: str


class FunctionCallOutput(TypedDict):
    output: str
    metadata: dict[str, JsonValue] | None
    duration_seconds: float


class FunctionCallResult(TypedDict):
    type: Literal["function_call_output"]
    call_id: str
    output: FunctionCallOutput


class MessageContent(TypedDict):
    type: str


class Message(TypedDict):
    type: Literal["message"]
    role: Literal["user", "assistant", "tool"]
    content: list[MessageContent]


Record: TypeAlias = Message | FunctionCall | FunctionCallResult


def rollout_to_messages(
    rollout: str,
) -> list[ChatMessage]:
    records: list[Record] = [
        json.loads(line) for line in rollout.splitlines() if len(line) > 0
    ]

    messages: list[ChatMessage] = []
    function_names: dict[str, str] = dict()
    pending_function_call: list[FunctionCall] = []
    pending_function_call_result: list[FunctionCallResult] = []
    for record in records:
        if "type" not in record:
            continue

        if record["type"] == "message":
            if record["role"] == "user":
                messages.append(
                    ChatMessageUser(
                        content=[
                            ContentText(text=c["text"])
                            for c in record["content"]
                            if "text" in c
                        ]
                    )
                )
            if record["role"] == "assistant":
                messages.append(
                    ChatMessageAssistant(
                        content=[
                            ContentText(text=c["text"])
                            for c in record["content"]
                            if "text" in c
                        ],
                        tool_calls=[
                            to_tool_call(call) for call in pending_function_call
                        ]
                        if len(pending_function_call) > 0
                        else None,
                    )
                )
                for result in pending_function_call_result:
                    if "output" in result:
                        output: FunctionCallOutput = json.loads(result.get("output"))
                        if output:
                            messages.append(
                                ChatMessageTool(
                                    name=function_names[result["call_id"]],
                                    tool_call_id=result.get("call_id", None),
                                    content=result.get("output", None),
                                )
                            )
                pending_function_call.clear()
                pending_function_call_result.clear()
        elif record["type"] == "function_call":
            pending_function_call.append(record)
            function_names[record["call_id"]] = record["name"]
        elif record["type"] == "function_call_output":
            pending_function_call_result.append(record)

    return messages


def to_tool_call(call: FunctionCall) -> ToolCall:
    args, parse_error = parse_tool_arguments(call["arguments"])
    return ToolCall(
        id=call["call_id"],
        function=call["name"],
        arguments=args,
        parse_error=parse_error,
    )


def parse_tool_arguments(arguments: str) -> tuple[dict[str, JsonValue], str | None]:
    try:
        return json.loads(arguments), None
    except Exception as ex:
        return {}, str(ex)
