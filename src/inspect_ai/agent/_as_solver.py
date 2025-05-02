from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inspect_ai.util._limit import Limit, apply_limits
from inspect_ai.util._span import span

if TYPE_CHECKING:
    from inspect_ai.solver._solver import Solver

from inspect_ai._util.registry import (
    is_registry_object,
    registry_unqualified_name,
)
from inspect_ai.tool._tool_info import parse_tool_info

from ._agent import Agent, AgentState


def as_solver(agent: Agent, limits: list[Limit] = [], **agent_kwargs: Any) -> Solver:
    """Convert an agent to a solver.

    Note that agents used as solvers will only receive their first parameter
    (`state`). Any other parameters must provide appropriate defaults
    or be explicitly specified in `agent_kwargs`

    Args:
       agent: Agent to convert.
       limits: List of limits to apply to the agent. Should a limit
          be exceeded, the Sample ends and proceeds to scoring.
       **agent_kwargs: Arguments to curry to Agent function (required
          if the agent has parameters without default values).

    Solver:
       Solver from agent.
    """
    from inspect_ai.solver._solver import Generate, solver
    from inspect_ai.solver._task_state import TaskState

    # agent must be registered (so we can get its name)
    if not is_registry_object(agent):
        raise RuntimeError(
            "Agent passed to as_solver was not created by an @agent decorated function"
        )
    agent_name = registry_unqualified_name(agent)

    # check to make sure we have all the parameters we need to run the agent
    agent_info = parse_tool_info(agent)
    for name, param in list(agent_info.parameters.properties.items())[1:]:
        if param.default is None and name not in agent_kwargs:
            raise ValueError(
                f"To use the {agent_name} agent as a solver "
                + f"you must pass a value for the agent's required '{name}' "
                + "parameter to the as_solver() function."
            )

    @solver(name=agent_name)
    def agent_to_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            agent_state = AgentState(messages=state.messages)

            try:
                # run the agent with limits
                with apply_limits(limits):
                    async with span(name=agent_name, type="agent"):
                        agent_state = await agent(agent_state, **agent_kwargs)
            # if an exception occurs, we still want to update the TaskState with the
            # AgentState's messages + output so that it appears in the log and is scored
            finally:
                # update messages
                state.messages = agent_state.messages

                # update output if its not empty
                if agent_state.output:
                    state.output = agent_state.output

            return state

        # return solver
        return solve

    return agent_to_solver()
