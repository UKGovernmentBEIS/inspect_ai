from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.agent._agent import Agent
from inspect_ai.agent._execute import agent_execute
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState


@solver
def as_solver(agent: Agent) -> Solver:
    """Convert an agent to a solver.

    Note that agents used as solvers will only receive their first parameter
    (`input`). Any other parameters must provide appropriate defaults.

    Args:
       agent: Agent to convert.

    Solver:
       Solver from agent.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # run agent
        agent_state = await agent_execute(agent, None, state.messages)

        # append new messages
        message_ids = [message.id for message in state.messages]
        for message in agent_state.messages:
            if message.id not in message_ids:
                state.messages.append(message)

        # update output if its not empty
        if not agent_state.output.empty:
            state.output = agent_state.output
        return state

    # propagate the agent's name to the solver
    name = (
        registry_info(agent).name
        if is_registry_object(agent)
        else getattr(agent, "__name__", "agent")
    )
    solve.__name__ = name

    # return solver
    return solve
