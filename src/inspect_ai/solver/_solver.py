from typing import (
    Any,
    Callable,
    Literal,
    Protocol,
    TypeVar,
    cast,
    overload,
    runtime_checkable,
)

from typing_extensions import Unpack

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_name,
    registry_tag,
)
from inspect_ai.model import CachePolicy, GenerateConfigArgs

from ._task_state import TaskState


@runtime_checkable
class Generate(Protocol):
    """Generate using the model and add the assistant message to the task state.

    Args:
       state (TaskState): Beginning task state.

       tool_calls (Literal["loop", "single", "none"]): Resolve tool calls:
          - `"loop"` resolves tools calls and then invokes `generate()`,
             proceeding in a loop which terminates when there are no more
             tool calls or `max_messages` is exceeded. This is the default behavior.
          - `"single"` resolves at most a single set of tool calls and then returns.
          - `"none"` does not resolve tool calls at all (in this
             case you will need to invoke `call_tools()` directly).

       cache: (bool | CachePolicy):
          Caching behaviour for generate responses (defaults to no caching).

       **kwargs: Optional generation config arguments.

    Returns:
       Updated TaskState.
    """

    async def __call__(
        self,
        state: TaskState,
        tool_calls: Literal["loop", "single", "none"] = "loop",
        cache: bool | CachePolicy = False,
        **kwargs: Unpack[GenerateConfigArgs],
    ) -> TaskState: ...


@runtime_checkable
class Solver(Protocol):
    r"""Contribute to solving an evaluation task.

    Contribute to the solution of a task by transforming a TaskState
    (e.g. prompt enhancement, elicitation, etc.). Solvers return a
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
    ) -> TaskState: ...


SolverType = TypeVar("SolverType", Callable[..., Solver], type[Solver])
r"""Solver type.

Valid solver types include:
 - Functions that return a Solver
 - Classes derived from Solver
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
    solver_name = name if name else getattr(solver, "__name__")
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
def solver(name: str) -> Callable[..., SolverType]: ...


@overload
# type: ignore
def solver(name: Callable[..., Solver]) -> Callable[..., Solver]: ...


@overload
def solver(name: type[Solver]) -> type[Solver]: ...


def solver(name: str | SolverType) -> Callable[..., SolverType] | SolverType:
    r"""Decorator for registering solvers.

    Args:
        name: (str | SolverType):
            Optional name for solver. If the decorator has no name
            argument then the name of the underlying SolverType
            object will be used to automatically assign a name.

    Returns:
        Solver with registry attributes.

    Examples:
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

            if not is_callable_coroutine(solver):
                raise TypeError(f"'{solver}' is not declared as an async callable.")

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

    # create a solver wrapper for the passed solver_type
    else:
        solver_type = name
        return create_solver_wrapper(solver_type)


@solver
def generate(
    tool_calls: Literal["loop", "single", "none"] = "loop",
    cache: bool | CachePolicy = False,
) -> Solver:
    r"""Generate output from the model and append it to task message history.

    generate() is the default plan/solver if none is specified for a given task.

    Args:
      tool_calls (Literal["loop", "single", "none"]): Resolve tool calls:
        - `"loop"` resolves tools calls and then invokes `generate()`,
            proceeding in a loop which terminates when there are no more
            tool calls or `max_messages` is exceeded. This is the default behavior.
        - `"single"` resolves at most a single set of tool calls and then returns.
        - `"none"` does not resolve tool calls at all (in this
            case you will need to invoke `call_tools()` directly).

      cache: (bool | CachePolicy):
        Caching behaviour for generate responses (defaults to no caching).
    """

    # call generate on the tasks
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state, tool_calls=tool_calls, cache=cache)

    # return solve
    return solve
