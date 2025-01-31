from collections.abc import Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from itertools import tee
from random import Random
from typing import Any, Iterable, SupportsIndex, Type, Union, cast, overload

from pydantic_core import to_jsonable_python

from inspect_ai.dataset._dataset import MT, Sample, metadata_as
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    ModelName,
    ModelOutput,
)
from inspect_ai.model._call_tools import tools_info
from inspect_ai.model._chat_message import ChatMessageBase
from inspect_ai.model._model import sample_total_tokens
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._target import Target
from inspect_ai.tool import Tool, ToolChoice
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._store import Store, store_jsonable
from inspect_ai.util._store_model import SMT


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
        target: Target = Target(""),
        choices: list[str] | None = [],
        output: ModelOutput | None = None,
        message_limit: int | None = None,
        token_limit: int | None = None,
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

        self.target = target
        """The scoring target for this `Sample`."""

        self.metadata = metadata
        """Metadata from the `Sample` for this `TaskState`"""

        self._messages: list[ChatMessage] = ChatMessageList(messages, self)
        """
        Chat conversation history for sample.

        This will generally get appended to every time a `generate` call is made
        to the model. Useful for both debug and for solvers/scorers to assess
        model performance or choose the next step.
        """

        self._tools: list[Tool] = []
        """Tools available to the model."""

        self.tool_choice: ToolChoice | None = None
        """Tool choice directive."""

        self.output = output if output else ModelOutput(model=str(model), choices=[])
        """
        The 'final' model output once we've completed all solving.

        For simple evals this may just be the last `message` from the
        conversation history, but more complex solvers may generate this in
        different ways depending on what solvers are used..
        """

        self._message_limit = message_limit
        self._token_limit = token_limit
        self._completed = completed

        """Store for shared data"""
        self.store = Store()

        if choices:
            self.choices = Choices(choices)
        else:
            self.choices = Choices([])

        self.scores: dict[str, Score] | None = None
        """Scores yielded by running task."""

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
    def messages(self) -> list[ChatMessage]:
        """Messages in chat history"""
        return self._messages

    @messages.setter
    def messages(self, messages: list[ChatMessage]) -> None:
        """Set messages in chat history."""
        self._messages = ChatMessageList(messages, self)

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
        return self._message_limit

    @message_limit.setter
    def message_limit(self, messages: int | None) -> None:
        """Set limit on total messages allowed per conversation."""
        self._message_limit = messages

        from inspect_ai.log._samples import set_active_sample_message_limit

        set_active_sample_message_limit(messages)

    @property
    def token_limit(self) -> int | None:
        """Limit on total tokens allowed per conversation."""
        return self._token_limit

    @token_limit.setter
    def token_limit(self, tokens: int | None) -> None:
        """Set limit on total tokens allowed per conversation."""
        self._token_limit = tokens

        from inspect_ai.log._samples import set_active_sample_token_limit

        set_active_sample_token_limit(tokens)

    @property
    def token_usage(self) -> int:
        """Total tokens used for the current sample."""
        return sample_total_tokens()

    @property
    def completed(self) -> bool:
        """Is the task completed.

        Additionally, checks message and token limits and raises if they are exceeded.
        """
        from inspect_ai.log._samples import set_active_sample_total_messages

        from ._limit import SampleLimitExceededError

        # update messages
        set_active_sample_total_messages(len(self.messages))

        if self._completed:
            return True
        elif self.message_limit and len(self.messages) >= self.message_limit:
            raise SampleLimitExceededError(
                "message",
                value=len(self.messages),
                limit=self.message_limit,
                state=self,
            )
        elif self.token_limit and self.token_usage >= self.token_limit:
            raise SampleLimitExceededError(
                "token", value=self.token_usage, limit=self.token_limit, state=self
            )
        else:
            return self._completed

    @completed.setter
    def completed(self, completed: bool) -> None:
        """Set the completed status."""
        self._completed = completed

    @property
    def tools(self) -> list[Tool]:
        return self._tools

    @tools.setter
    def tools(self, tools: list[Tool | ToolDef]) -> None:
        self._tools.clear()
        for tool in tools:
            self._tools.append(tool if isinstance(tool, Tool) else tool.as_tool())

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

    def store_as(self, model_cls: Type[SMT]) -> SMT:
        """Pydantic model interface to the store.

        Args:
          model_cls: Pydantic model type (must derive from StoreModel)

        Returns:
          StoreModel: Instance of model_cls bound to current Store.
        """
        return model_cls(store=self.store)


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


class ChatMessageList(list[ChatMessage]):
    def __init__(self, iterable: Iterable[ChatMessage], parent_state: TaskState):
        self.parent_state = parent_state
        items, length = self._iterable_length(iterable)
        self._check_size(length)
        super().__init__(items)

    def _check_size(self, additional_items: int = 1) -> None:
        from inspect_ai.log._samples import active_sample_message_limit

        from ._limit import SampleLimitExceededError

        messages_limit = active_sample_message_limit()
        if messages_limit is not None:
            messages = len(self) + additional_items
            if messages > messages_limit:
                raise SampleLimitExceededError(
                    "message",
                    value=messages,
                    limit=messages_limit,
                    message=None,
                    state=self.parent_state,
                )

    def append(self, item: ChatMessage) -> None:
        self._check_size()
        super().append(item)

    def extend(self, items: Iterable[ChatMessage]) -> None:
        items, length = self._iterable_length(items)
        self._check_size(length)
        super().extend(items)

    def insert(self, index: SupportsIndex, item: ChatMessage) -> None:
        self._check_size()
        super().insert(index, item)

    @overload
    def __setitem__(self, index: SupportsIndex, item: ChatMessage) -> None: ...

    @overload
    def __setitem__(self, index: slice, item: Iterable[ChatMessage]) -> None: ...

    def __setitem__(
        self, index: SupportsIndex | slice, item: ChatMessage | Iterable[ChatMessage]
    ) -> None:
        if isinstance(index, slice) and not isinstance(item, ChatMessageBase):
            item, length = self._iterable_length(item)
            size_change = length - len(self[index])
            if size_change > 0:
                self._check_size(size_change)

        super().__setitem__(index, item)  # type: ignore[assignment,index]

    def _iterable_length(
        self, items: Iterable[ChatMessage]
    ) -> tuple[Iterable[ChatMessage], int]:
        items, counter = tee(items)
        length = sum(1 for _ in counter)
        return items, length
