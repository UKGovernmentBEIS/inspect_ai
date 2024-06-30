from collections.abc import Sequence
from dataclasses import dataclass
from random import Random
from typing import Any, Union, overload

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ModelName,
    ModelOutput,
    ToolChoice,
)
from inspect_ai.solver._tool.tool_def import tool_defs

from ._tool.tool import Tool
from ._util import append_system_message


@dataclass
class Choice:
    """
    A `Choice` represents a single choice in a multiple choice question.

    It is only relevant for the `multiple_choice` solver and corresponding `choice` scorer.
    """

    value: str
    """The original value of the choice from the `Sample`."""

    correct: bool | None
    """Did the model think this choice satisfies the question? `None` indicates this has not been set yet"""

    original_position: int
    """Choices may be re-ordered during processing, this represents the original position in the sample's list of choices"""


class Choices(Sequence[Choice]):
    """
    Wrapper class for a list of `Choice` objects.

    Primarily simply to abstract away implementations of choice-specific
    functionality from the already-big `TaskState` class.
    """

    def __init__(self, choices: list[str] | list[Choice]) -> None:
        """
        Setter for choices, intended to only be used with the `multiple_choice` scorer.

        Choices come from a list of choices for the sample, specifically used by
        the `multiple_choice` scorer.

        For example, if the sample was a multiple choice question like "What is
        the capital of France? A) Paris B) London C) Berlin", we would store the
        possible answers here.
        """
        self._choices: list[Choice] = []

        for i, choice in enumerate(choices):
            if isinstance(choice, str):
                self._choices.append(
                    Choice(value=choice, correct=None, original_position=i)
                )
            elif isinstance(choice, Choice):
                self._choices.append(choice)

    @overload
    def __getitem__(self, index: int) -> Choice: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Choice]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[Choice, Sequence[Choice]]:
        return self._choices[index]

    def __len__(self) -> int:
        return len(self._choices)

    def mark_choice(self, index: int, correct: bool) -> None:
        """Set the value of a specific choice"""
        self._choices[index].correct = correct

    def shuffle(self, rand: Random = Random()) -> None:
        """
        Shuffle the choice order, setting the `original_position` so they can be mapped back to their original order.

        Some evals will shuffle the choices from the original sample to try to
        avoid the model answering correctly due to fine-tuning (or similar) on
        specific datasets.
        """
        shuffled_positions = list(range(len(self._choices)))
        rand.shuffle(shuffled_positions)

        shuffled_choices = [Choice("notachoice", None, -1)] * len(self._choices)

        for i, shuffled_position in enumerate(shuffled_positions):
            shuffled_choices[i] = self._choices[shuffled_position]
            shuffled_choices[i].original_position = shuffled_position

        self._choices = shuffled_choices


class TaskState:
    """
    The `TaskState` represents the internal state of the `Task` being run for a single `Sample`.

    It's a mutable object that is updated by each solver during a sample's
    evaluation. It allows us to maintain things like the message history between
    the running `Task` and the model, the tools available to the model, the
    final output of the model and whether or not it's completed yet.
    """

    def __init__(
        self,
        model: ModelName,
        sample_id: int | str,
        epoch: int,
        input: str | list[ChatMessage],
        messages: list[ChatMessage],
        choices: list[str] | None = [],
        tools: list[Tool] = [],
        tool_choice: ToolChoice | None = None,
        output: ModelOutput | None = None,
        max_messages: int | None = None,
        completed: bool = False,
        metadata: dict[str, Any] = {},
    ) -> None:
        self._model = model
        """Model name used for this task."""

        self.sample_id = sample_id
        """Unique id for sample."""

        self.epoch = epoch
        """Epoch number for sample."""

        self._input = input
        """
        The original input from the `Sample` for this `TaskState`.

        Should be treated as immutable and not changed during the run, so that
        it can be referenced or checked wherever needed. Access through `input`
        or `input_text` only
        """

        self.messages = messages
        """
        Chat conversation history for sample.

        This will generally get appended to every time a `generate` call is made
        to the model. Useful for both debug and for solvers/scorers to assess
        model performance or choose the next step.
        """

        self.tools = tools
        """Tools available to the model."""

        self.tool_choice = tool_choice
        """Tool choice directive."""

        self.output = output if output else ModelOutput(model=str(model), choices=[])
        """
        The 'final' model output once we've completed all solving.

        For simple evals this may just be the last `message` from the
        conversation history, but more complex solvers may generate this in
        different ways depending on what solvers are used..
        """

        self._max_messages = max_messages
        self._completed = completed

        self.metadata = metadata
        """Additional task state metadata."""

        if choices:
            self.choices = Choices(choices)
        else:
            self.choices = Choices([])

    @property
    def model(self) -> ModelName:
        """Name of model being evaluated."""
        return self._model

    @property
    def input(self) -> str | list[ChatMessage]:
        """Input from the `Sample`, should be considered immutable."""
        return self._input

    @property
    def input_text(self) -> str:
        """
        Convenience function for accessing the initial input from the `Sample` as a string.

        If the `input` is a `list[ChatMessage]`, this will return the text from
        the first chat message
        """
        if isinstance(self._input, str):
            return self._input
        else:
            input = next(
                (message.text for message in self._input if message.role == "user"),
                None,
            )
            if input:
                return input
            else:
                raise ValueError(
                    "input_text requested from TaskState but none available"
                )

    @property
    def user_prompt(self) -> ChatMessageUser:
        """User prompt for this state.

        Tasks are very general and can have may types of inputs.
        However, in many cases solvers assume they can interact with
        the state as a "chat" in a predictable fashion (e.g. prompt
        engineering solvers). This property enables easy read and
        write access to the user chat prompt. Raises an
        exception if there is no user prompt

        Returns:
           First user `ChatMessage` in the task state.
        """
        prompt = next((m for m in self.messages if m.role == "user"), None)
        if prompt:
            return prompt
        else:
            raise ValueError("user_prompt requested from TaskState but none available")

    @property
    def completed(self) -> bool:
        """Is the task completed."""
        if self._completed:
            return True
        elif self._max_messages and len(self.messages) >= self._max_messages:
            return True
        else:
            return False

    @completed.setter
    def completed(self, completed: bool) -> None:
        """Set the completed status."""
        self._completed = completed

    @property
    def tools(self) -> list[Tool]:
        return self._tools

    @tools.setter
    def tools(self, tools: list[Tool]) -> None:
        # clear out any tool-derivied system messages
        self.messages = [
            message
            for message in self.messages
            if not isinstance(message, ChatMessageSystem) or message.tool is None
        ]

        # add system messages for the new set of tools
        for tool in tool_defs(tools):
            if tool.prompt:
                append_system_message(
                    self.messages,
                    ChatMessageSystem(content=tool.prompt, tool=tool.name),
                )

        # set the tools
        self._tools = tools

    @property
    def tool_calls_pending(self) -> bool:
        if (
            isinstance(self.messages[-1], ChatMessageAssistant)
            and self.messages[-1].tool_calls
        ):
            return True
        else:
            return False
