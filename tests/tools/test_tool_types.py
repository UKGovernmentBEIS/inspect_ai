from typing import Literal

from pydantic import BaseModel
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model import ChatMessageTool
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ToolFunction, tool


class Word(BaseModel):
    type: Literal["adjective", "noun"]
    word: str


@tool(
    prompt="Use the extract words tool if you are asked to extract the nouns and adjectives from a sentence."
)
def extract_words():
    async def extract(extracted: list[Word]):
        """
        Accepts the extracted nouns and adjectives from the sentence

        Args:
          extracted: A list of Word objects each with a type and word.

        Returns:
          The same structured output passed, for consumption by the application
        """
        return str(extracted)

    return extract


def check_list_of_pydantic_objects(model: str) -> None:
    task = Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="Extract the nouns and adjectives from the following sentence.\nSentence:\nThe quick brown fox jumped over the lazy dog."
                )
            ]
        ),
        plan=[
            use_tools([extract_words()], tool_choice=ToolFunction("extract_words")),
            generate(),
        ],
    )

    log = eval(task, model="openai/gpt-4o")[0]
    verify_tool_call(log, "[{'type':")


def check_tool_types(model: str):
    check_list_of_pydantic_objects(model)


@skip_if_no_openai
def test_openai_tool_types() -> None:
    check_tool_types("openai/gpt-4o")


@skip_if_no_anthropic
def test_anthropoic_tool_types() -> None:
    check_tool_types("anthropic/claude-3-5-sonnet-20240620")


@skip_if_no_google
def test_google_tool_types() -> None:
    check_tool_types("google/gemini-1.5-pro")


@skip_if_no_mistral
def test_mistral_tool_types() -> None:
    check_tool_types("mistral/mistral-large-latest")


def verify_tool_call(log: EvalLog, startswith: str):
    assert log.samples
    tool_message = log.samples[0].messages[-2]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.text.startswith(startswith)
