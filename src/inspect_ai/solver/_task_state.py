from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    ModelName,
    ModelOutput,
    ToolChoice,
)

from ._tool.tool import Tool


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
        choices: list[str] | None,
        messages: list[ChatMessage],
        tools: list[Tool] = [],
        tool_choice: ToolChoice | None = None,
        output: ModelOutput | None = None,
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

        self.choices = choices
        """
        List of choices for the sample, specifically used by the `multiple_choice` scorer.

        For example, if the sample was a multiple choice question like "What is
        the capital of France? A) Paris B) London C) Berlin", we would store the
        possible answers here.
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

        self.completed = completed
        """Flag to indicate that the solver loop should terminate."""

        self.metadata = metadata
        """Additional task state metadata."""

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
