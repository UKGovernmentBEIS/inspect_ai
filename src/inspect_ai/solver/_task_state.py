from collections.abc import Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from random import Random
from typing import Any, Type, Union, cast, overload

from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._util.interrupt import check_sample_interrupt
from inspect_ai.dataset._dataset import MT, Sample, metadata_as
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    ModelName,
    ModelOutput,
)
from inspect_ai.model._call_tools import tools_info
from inspect_ai.model._model import sample_total_tokens
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._target import Target
from inspect_ai.tool import Tool, ToolChoice
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._limit import (
    check_message_limit,
    check_token_limit,
)
from inspect_ai.util._limit import message_limit as create_message_limit
from inspect_ai.util._limit import token_limit as create_token_limit
from inspect_ai.util._limited_conversation import ChatMessageList
from inspect_ai.util._store import Store, store_jsonable
from inspect_ai.util._store_model import SMT


@dataclass
class Choice:
    """
    A `Choice` represents a single choice in a multiple choice question.

    It is only relevant for the `multiple_choice` solver and corresponding
    `choice` scorer.
    """

    value: str
    """The original value of the choice from the `Sample`."""

    correct: bool | None
    """Did the model think this choice satisfies the question? `None`
    indicates this has not been set yet"""

    original_position: int
    """Choices may be re-ordered during processing, this represents the
    original position in the sample's list of choices"""


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

    def prompt(self, question: str, template: str) -> str:
        """Format a prompt for these choices.

        Args:
          question (str): Question to pose.
          template (str): Prompt template

        Returns:
          Prompt for question and choices using the provided template.
        """
        from ._multiple_choice import prompt

        return prompt(question, self, template)


class TaskState:
    """
    The `TaskState` represents the internal state of the `Task` being run for a single `Sample`.

    The `TaskState` is passed to and returned from each solver during a sample's
    evaluation. It allows us to manipulated the message history, the tools
    available to the model, the final output of the model, and whether the task
    is completed or has hit a limit.
    """

    def __init__(
        self,
        model: ModelName,
        sample_id: int | str,
        epoch: int,
        input: str | list[ChatMessage],
        messages: list[ChatMessage],
        target: Target = Target(""),
        choices: list[str] | None = [],
        output: ModelOutput | None = None,
        message_limit: int | None = None,
        token_limit: int | None = None,
        completed: bool = False,
        metadata: dict[str, Any] = {},
    ) -> None:
        self._model = model
        self._sample_id = sample_id
        self._epoch = epoch
        self._input = input
        self._target = target
        self._metadata = metadata
        self._messages: list[ChatMessage] = ChatMessageList(messages)
        self._tools: list[Tool] = []
        self._output = output if output else ModelOutput(model=str(model))
        self._message_limit = create_message_limit(message_limit)
        self._token_limit = create_token_limit(token_limit)
        self._completed = completed
        self._store = Store()
        self._uuid = uuid()

        if choices:
            self.choices = Choices(choices)
        else:
            self.choices = Choices([])

    @property
    def model(self) -> ModelName:
        """Name of model being evaluated."""
        return self._model

    @property
    def sample_id(self) -> int | str:
        """Unique id for sample."""
        return self._sample_id

    @property
    def epoch(self) -> int:
        """Epoch number for sample."""
        return self._epoch

    @property
    def input(self) -> str | list[ChatMessage]:
        """Input from the `Sample`, should be considered immutable."""
        return self._input

    @property
    def input_text(self) -> str:
        """
        Convenience function for accessing the initial input from the `Sample` as a string.

        If the `input` is a `list[ChatMessage]`, this will return the text from
        the last chat message
        """
        if isinstance(self._input, str):
            return self._input
        else:
            input = next(
                (
                    message.text
                    for message in reversed(self._input)
                    if message.role == "user"
                ),
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
        """
        prompt = next((m for m in reversed(self.messages) if m.role == "user"), None)
        if prompt:
            return prompt
        else:
            raise ValueError("user_prompt requested from TaskState but none available")

    @property
    def metadata(self) -> dict[str, Any]:
        """Metadata from the `Sample` for this `TaskState`"""
        return self._metadata

    @metadata.setter
    def metadata(self, metadata: dict[str, Any]) -> None:
        self._metadata = metadata

    @property
    def messages(self) -> list[ChatMessage]:
        """
        Chat conversation history for sample.

        This will generally get appended to every time a `generate` call is made
        to the model. Useful for both debug and for solvers/scorers to assess
        model performance or choose the next step.
        """
        return self._messages

    @messages.setter
    def messages(self, messages: list[ChatMessage]) -> None:
        self._messages = ChatMessageList(messages)

    @property
    def output(self) -> ModelOutput:
        """
        The 'final' model output once we've completed all solving.

        For simple evals this may just be the last `message` from the
        conversation history, but more complex solvers may set this directly.
        """
        return self._output

    @output.setter
    def output(self, output: ModelOutput) -> None:
        self._output = output

    @property
    def store(self) -> Store:
        """Store for shared data"""
        return self._store

    @property
    def tools(self) -> list[Tool]:
        """Tools available to the model."""
        return self._tools

    @tools.setter
    def tools(self, tools: list[Tool | ToolDef]) -> None:
        self._tools.clear()
        for tool in tools:
            self._tools.append(tool if isinstance(tool, Tool) else tool.as_tool())

    tool_choice: ToolChoice | None = None
    """Tool choice directive."""

    @property
    def max_messages(self) -> int | None:
        """Deprecated (use message_limit)."""
        return self.message_limit

    @max_messages.setter
    def max_messages(self, messages: int | None) -> None:
        """Deprecated (use message_limit)."""
        self.message_limit = messages

    @property
    def message_limit(self) -> int | None:
        """Limit on total messages allowed per conversation."""
        return self._message_limit.limit

    @message_limit.setter
    def message_limit(self, messages: int | None) -> None:
        """Set limit on total messages allowed per conversation.

        Also checks whether the current message count exceeds the new limit.
        """
        self._message_limit.limit = messages
        check_message_limit(len(self.messages), raise_for_equal=False)

        from inspect_ai.log._samples import set_active_sample_message_limit

        set_active_sample_message_limit(messages)

    @property
    def token_limit(self) -> int | None:
        """Limit on total tokens allowed per conversation."""
        return self._token_limit.limit

    @token_limit.setter
    def token_limit(self, tokens: int | None) -> None:
        """Set limit on total tokens allowed per conversation.

        Also checks whether the current token usage exceeds the new limit.
        """
        self._token_limit.limit = tokens
        check_token_limit()

        from inspect_ai.log._samples import set_active_sample_token_limit

        set_active_sample_token_limit(tokens)

    @property
    def token_usage(self) -> int:
        """Total tokens used for the current sample."""
        return sample_total_tokens()

    @property
    def completed(self) -> bool:
        """Is the task completed.

        Additionally, checks message and token limits and raises if they are exceeded, and also checks for an operator interrupt of the sample.
        """
        from inspect_ai.log._samples import set_active_sample_total_messages

        # update messages
        set_active_sample_total_messages(len(self.messages))

        if self._completed:
            return True
        else:
            check_sample_interrupt()
            return self._completed

    @completed.setter
    def completed(self, completed: bool) -> None:
        """Set the completed status."""
        self._completed = completed

    @property
    def target(self) -> Target:
        """The scoring target for this `Sample`."""
        return self._target

    scores: dict[str, Score] | None = None
    """Scores yielded by running task."""

    @property
    def uuid(self) -> str:
        """Globally unique identifier for sample run."""
        return self._uuid

    def metadata_as(self, metadata_cls: Type[MT]) -> MT:
        """Pydantic model interface to metadata.

        Args:
          metadata_cls: Pydantic model type

        Returns:
          BaseModel: Instance of metadata_cls bound to current Store.
        """
        if not self.metadata:
            raise ValueError("Sample does not have metadata")

        return metadata_as(self.metadata, metadata_cls)

    def store_as(self, model_cls: Type[SMT], instance: str | None = None) -> SMT:
        """Pydantic model interface to the store.

        Args:
          model_cls: Pydantic model type (must derive from StoreModel)
          instance: Optional instances name for store (enables multiple instances
            of a given StoreModel type within a single sample)

        Returns:
          StoreModel: model_cls bound to sample store data.
        """
        return model_cls(store=self.store, instance=instance)


def sample_state() -> TaskState | None:
    return _sample_state.get(None)


def set_sample_state(state: TaskState) -> None:
    _sample_state.set(state)


_sample_state: ContextVar[TaskState] = ContextVar("sample_state")


def state_jsonable(state: TaskState | None = None) -> dict[str, Any]:
    # use current sample state if none specified
    if state is None:
        state = sample_state()
        if state is None:
            return dict()

    def as_jsonable(value: Any) -> Any:
        return to_jsonable_python(value, exclude_none=True, fallback=lambda _x: None)

    state_data = dict(
        messages=as_jsonable(state.messages),
        tools=tools_info(state.tools),
        tool_choice=state.tool_choice,
        store=store_jsonable(state.store),
        output=state.output,
        completed=state.completed,
        metadata=as_jsonable(state.metadata),
    )
    jsonable = as_jsonable(state_data)
    return cast(dict[str, Any], deepcopy(jsonable))


def sample_jsonable(sample: Sample) -> dict[str, Any]:
    jsonable = to_jsonable_python(sample, exclude_none=True, fallback=lambda _x: None)
    return cast(dict[str, Any], deepcopy(jsonable))
