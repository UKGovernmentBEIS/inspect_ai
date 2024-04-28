from typing import (
    Any,
    Callable,
    Protocol,
    TypeVar,
    cast,
    overload,
    runtime_checkable,
)

from typing_extensions import Unpack

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_name,
    registry_tag,
)
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfigArgs,
    ModelName,
    ModelOutput,
    ToolChoice,
)

from ._tool.tool import Tool


class TaskState:
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

        self.sample_id = sample_id
        """Unique id for sample."""

        self.epoch = epoch
        """Epoch number for sample."""

        self._input = input

        self.choices = choices
        """Sample choices."""

        self.messages = messages
        """Chat conversation history for sample."""

        self.tools = tools
        """Tools available to the model."""

        self.tool_choice = tool_choice
        """Tool choice directive."""

        self.output = output if output else ModelOutput(model=str(model), choices=[])
        """Model output."""

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
        """Sample input."""
        return self._input

    @property
    def input_text(self) -> str:
        """Sample input as text."""
        if isinstance(self._input, str):
            return self._input
        else:
            return next(
                (message.text for message in self.messages if message.role == "user"),
                "",
            )

    @property
    def user_prompt(self) -> ChatMessageUser:
        """User prompt for this state.

        Tasks are very general and can have may types of inputs.
        However, in many cases solvers assume they can interact with
        the state as a "chat" in a predictable fashion (e.g. prompt
        engineering solvers). This propery enables easy read and
        write access to the user chat prompt. Raises an
        exception if there is no user prompt

        Returns:
           First user `ChatMessage` if the current state has one, else `None`
        """
        prompt = next(
            (m for m in self.messages if isinstance(m, ChatMessageUser)), None
        )
        if prompt:
            return prompt
        else:
            raise ValueError("User prompt requested from TaskState but none available")


@runtime_checkable
class Generate(Protocol):
    """Generate using the model and add the assistant message to the task state.

    Args:
       state (TaskState): Beginning task state.
       **kwargs: Optional generation config arguments.

    Returns:
       Updated TaskState.
    """

    async def __call__(
        self, state: TaskState, **kwargs: Unpack[GenerateConfigArgs]
    ) -> TaskState:
        ...


@runtime_checkable
class Solver(Protocol):
    r"""Contribute to solving an evaluation task.

    Contribute to the solution of a task by transforming a TaskState
    (e.g. prompt enhancement, eliciation, etc.). Solvers return a
    TaskState (which could simply be a modified version of the one
    they were passed) and optionally may call the generate() function
    to generate output (and a new TaskState with that output).


    Args:
        state (TaskState): States for tasks being evaluated.
        generate (Generate): Function for generating outputs.

    Returns:
        Updated TaskState.
    """

    async def __call__(
        self,
        state: TaskState,
        generate: Generate,
    ) -> TaskState:
        ...


SolverType = TypeVar("SolverType", Callable[..., Solver], type[Solver])
r"""Solver type.

Valid solver types include:
 - Functions that return a Solver
 - Classes derivied from Solver
"""


def solver_register(solver: SolverType, name: str = "") -> SolverType:
    r"""Register a function or class as a solver.

    Args:
        solver (SolverType):
            Function that returns a Solver or class derived Solver.
        name (str): Name of solver (Optional, defaults to object name)

    Returns:
        Solver with registry attributes.
    """
    solver_name = (name if name else getattr(solver, "__name__")).lower()
    registry_add(solver, RegistryInfo(type="solver", name=solver_name))
    return solver


def solver_create(name: str, **kwargs: Any) -> Solver:
    r"""Create a Solver based on its registered name.

    Args:
        name (str): Name of solver (Optional, defaults to object name)
        **kwargs (dict): Optional creation arguments for the solver

    Returns:
        Solver with registry info attribute
    """
    return cast(Solver, registry_create("solver", name, **kwargs))


@overload
def solver(name: str) -> Callable[..., SolverType]:
    ...


@overload
# type: ignore
def solver(name: Callable[..., Solver]) -> Callable[..., Solver]:
    ...


@overload
def solver(name: type[Solver]) -> type[Solver]:
    ...


def solver(name: str | SolverType) -> Callable[..., SolverType] | SolverType:
    r"""Decorator for registering solvers.

    Args:
        name: (str | SolverType):
            Optional name for solver. If the decorator has no name
            argument then the name of the underlying SolverType
            object will be used to automatically assign a name.

    Returns:
        Solver with registry attributes.

    Exmaples:
        @solver
        def prompt_cot(state: TaskState, generate: Generate) -> None:
            ...

        @solver(name = "prompt_cot")
        def cot(state: TaskState, generate: Generate) -> None:
            ...

        @solver
        def prompt_cot(template: str) -> Solver:
            def solve(state: TaskState, generate: Generate) -> None:
                ...
            return solve
    """

    # create_solver_wrapper:
    #  (a) Add the SolverType to the registry using the appropriately
    #      package-namespaced name
    #  (b) Ensure that instances of Solver created by SolverType also
    #      carry registry info.
    def create_solver_wrapper(
        solver_type: SolverType, name: str | None = None
    ) -> SolverType:
        solver_name = registry_name(
            solver_type, name if name else getattr(solver_type, "__name__")
        )

        def solver_wrapper(*args: Any, **kwargs: dict[str, Any]) -> Solver:
            solver = solver_type(*args, **kwargs)

            registry_tag(
                solver_type,
                solver,
                RegistryInfo(type="solver", name=solver_name),
                *args,
                **kwargs,
            )

            return solver

        return solver_register(cast(SolverType, solver_wrapper), solver_name)

    # for decorators with an explicit name, one more wrapper for the name
    if isinstance(name, str):

        def wrapper(solver_type: SolverType) -> SolverType:
            return create_solver_wrapper(solver_type, name)

        return wrapper

    # create a solver wrapper for the passsed solver_type
    else:
        solver_type = name
        return create_solver_wrapper(solver_type)


@solver
def generate() -> Solver:
    r"""Generate output from the model and append it to task message history.

    generate() is the default plan/solver if none is specified for a given task.
    """

    # call generate on the tasks
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state)

    # return solve
    return solve
