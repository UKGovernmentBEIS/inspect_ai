# type: ignore

import json
from typing import Any, Dict, Protocol, cast, runtime_checkable

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages import ToolCall as LCToolCall
from langchain_core.outputs import (
    ChatGeneration,
    ChatResult,
)
from pydantic.v1 import Field
from typing_extensions import override

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    Content,
    ContentImage,
    ContentText,
    GenerateConfig,
    ModelName,
    ModelOutput,
    get_model,
)
from inspect_ai.solver import Generate, Solver, TaskState
from inspect_ai.tool import ToolCall, ToolChoice, ToolInfo


@runtime_checkable
class LangChainAgent(Protocol):
    async def __call__(
        self, llm: BaseChatModel, input: dict[str, Any]
    ) -> str | list[str | dict[str, Any]]: ...


def langchain_solver(agent: LangChainAgent) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # create the inspect model api bridge
        llm = InspectChatModel()

        # call the agent
        await agent(
            llm=llm,
            input=dict(
                input=state.user_prompt.text,
                chat_history=as_langchain_chat_history(state.messages[1:]),
            ),
        )

        # collect output from llm interface
        state.messages = llm.messages
        state.output = llm.output

        # return state
        return state

    return solve


class InspectChatModel(BaseChatModel):
    # track messages and model output so we can update
    # the inspect task state when we are complete
    messages: list[ChatMessage] = Field(default=[], exclude=True)
    output: ModelOutput = Field(default=ModelOutput(), exclude=True)

    @property
    def _llm_type(self) -> str:
        return f"Inspect ({ModelName(get_model()).api})"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": str(ModelName(get_model()).name),
        }

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # inspect uses async exclusively
        raise NotImplementedError

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: dict[str, Any],
    ) -> ChatResult:
        # extract tools from kwargs
        tools: list[ToolInfo] = []
        tool_choice: ToolChoice | None = None
        lc_tools = cast(list[dict[str, Any]] | None, kwargs.get("tools", None))
        if lc_tools:
            tools = [ToolInfo(**tool["function"]) for tool in lc_tools]
            tool_choice = "auto"

        # generate
        input = [as_inspect_message(message) for message in messages]
        result = await get_model().generate(
            input=input,
            tools=tools,
            tool_choice=tool_choice,
            config=GenerateConfig(stop_seqs=stop),
        )

        # track last messages / model output
        self.messages = input
        self.messages.append(result.message)
        self.output = result

        # extract choices
        generations = [
            ChatGeneration(message=as_langchain_message(choice.message))
            for choice in result.choices
        ]

        # return
        return ChatResult(generations=generations)


def as_inspect_message(message: BaseMessage) -> ChatMessage:
    if isinstance(message, SystemMessage):
        return ChatMessageSystem(content=as_inspect_content(message.content))
    elif isinstance(message, HumanMessage):
        return ChatMessageUser(content=as_inspect_content(message.content))
    elif isinstance(message, AIMessage):
        return ChatMessageAssistant(
            content=as_inspect_content(message.content),
            tool_calls=(
                [
                    ToolCall(
                        type="function",
                        function=call["name"],
                        id=call["id"] or call["name"],
                        arguments=call["args"],
                    )
                    for call in message.tool_calls
                ]
                if message.tool_calls and len(message.tool_calls) > 0
                else None
            ),
        )
    elif isinstance(message, ToolMessage):
        return ChatMessageTool(
            content=as_inspect_content(message.content),
            tool_call_id=message.tool_call_id,
            function=message.name,
        )
    elif isinstance(message, FunctionMessage):
        return ChatMessageTool(
            content=as_inspect_content(message.content),
            tool_call_id=message.name,
            function=message.name,
        )
    else:
        raise ValueError(f"Unexpected message type: {type(message)}")


def as_langchain_message(message: ChatMessage) -> BaseMessage:
    if isinstance(message, ChatMessageSystem):
        return SystemMessage(content=as_langchain_content(message.content))
    elif isinstance(message, ChatMessageUser):
        return HumanMessage(content=as_langchain_content(message.content))
    elif isinstance(message, ChatMessageAssistant):
        additional_kwargs: dict[str, Any] = {}
        if message.tool_calls and len(message.tool_calls) > 0:
            additional_kwargs["tool_calls"] = [
                dict(
                    id=call.id, name=call.function, arguments=json.dumps(call.arguments)
                )
                for call in message.tool_calls
            ]

        return AIMessage(
            content=as_langchain_content(message.content),
            tool_calls=(
                [
                    LCToolCall(id=call.id, name=call.function, args=call.arguments)
                    for call in message.tool_calls
                ]
                if message.tool_calls
                else []
            ),
            additional_kwargs=additional_kwargs,
        )
    elif isinstance(message, ChatMessageTool):
        return ToolMessage(
            content=as_langchain_content(message.content),
            tool_call_id=message.tool_call_id or "",
        )
    else:
        raise ValueError(f"Unexpected message type: {type(message)}")


def as_langchain_chat_history(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [dict(role=message.role, content=message.text) for message in messages]


def as_inspect_content(
    content: str | list[str | dict[str, Any]],
) -> str | list[Content]:
    if isinstance(content, str):
        return content
    else:
        return [
            (
                ContentText(text=c)
                if isinstance(c, str)
                else (
                    ContentText(text=c["text"])
                    if c["type"] == "text"
                    else ContentImage(image=c["image"])
                )
            )
            for c in content
        ]


def as_langchain_content(
    content: str | list[Content],
) -> str | list[str | dict[str, Any]]:
    if isinstance(content, str):
        return content
    else:
        return [c if isinstance(c, str) else c.model_dump() for c in content]
