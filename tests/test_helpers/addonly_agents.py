"""Scripted agents for tamper-evident logs (tests and scripts).

A react agent with one parallel stage (two adds and two sub-agents used as
tools, so two sub-agents run at once), then a serial stage, then submit.
"""

from pathlib import Path
from typing import Any

import anyio

from inspect_ai import Task, eval
from inspect_ai.agent import as_tool, react
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, ToolCall, ToolChoice, ToolInfo, tool, tool_with


@tool(parallel=True)
def add() -> Tool:
    async def execute(x: int, y: int) -> int:
        """Add two numbers.

        Args:
          x: First number.
          y: Second number.
        """
        await anyio.sleep(0.01)
        return x + y

    return execute


@tool(parallel=False)
def note() -> Tool:
    async def execute(text: str) -> str:
        """Record a note (runs as its own stage).

        Args:
          text: The note.
        """
        return f"noted: {text}"

    return execute


@tool(parallel=True)
def lookup() -> Tool:
    async def execute(query: str) -> str:
        """Look something up.

        Args:
          query: What to look up.
        """
        await anyio.sleep(0.02)
        return f"result for {query}"

    return execute


def scripted_call(id: str, function: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=id, function=function, arguments=arguments)


def scripted_output(content: str, *calls: ToolCall) -> ModelOutput:
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=content, tool_calls=list(calls) or None, model="model"
                ),
                stop_reason="tool_calls" if calls else "stop",
            )
        ],
    )


async def scripted_model(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    """Main agent: one parallel stage (2 adds, 2 sub-agents), a serial stage, submit.

    Sub-agent: one lookup, then submit.
    """
    await anyio.sleep(0)
    turn = sum(isinstance(m, ChatMessageAssistant) for m in input)
    if any(t.name == "researcher" for t in tools):
        match turn:
            case 0:
                return scripted_output(
                    "working",
                    scripted_call("a1", "add", x=1, y=2),
                    scripted_call("a2", "add", x=3, y=4),
                    scripted_call("r1", "researcher", input="alpha"),
                    scripted_call("r2", "researcher", input="beta"),
                )
            case 1:
                return scripted_output(
                    "noting", scripted_call("n1", "note", text="sums done")
                )
            case _:
                return scripted_output("", scripted_call("s1", "submit", answer="42"))
    match turn:
        case 0:
            return scripted_output(
                "searching", scripted_call("l1", "lookup", query="q")
            )
        case _:
            return scripted_output("", scripted_call("s1", "submit", answer="found"))


def agent_task(epochs: int = 1, samples: int = 2) -> Task:
    researcher = react(
        name="researcher",
        description="Researches a question.",
        prompt="You research.",
        tools=[lookup()],
    )
    return Task(
        # plain ids: moto's IAM signature check fails on a "%" in a key, so
        # the URL-encoding of ids is covered by test_sample_key_encoding
        dataset=[
            Sample(id=f"s{i}", input="What is it?", target="42") for i in range(samples)
        ],
        solver=react(
            prompt="You are the main agent.",
            tools=[add(), note(), tool_with(as_tool(researcher), parallel=True)],
        ),
        scorer=includes(),
        epochs=epochs,
    )


def run(task: Task, log_dir: Path, **kwargs: Any) -> EvalLog:
    model = get_model("mockllm/model", custom_outputs=scripted_model)
    return eval(task, model=model, log_dir=str(log_dir), display="none", **kwargs)[0]
