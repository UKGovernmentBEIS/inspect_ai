from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._sandbox import sandbox, sandbox_service

from .state import HumanAgentState
from .view import HumanAgentView


async def run_human_agent_service(state: TaskState, view: HumanAgentView) -> None:
    # initialise agent state
    agent_state = HumanAgentState(state.store)

    async def start() -> None:
        agent_state.running = True

    async def stop() -> None:
        agent_state.running = False

    async def note() -> None:
        pass

    # callback to check if task is completed (use this to periodically
    # update the view with the current state)
    def task_is_complete() -> bool:
        view.update_state(agent_state)
        return False

    return await sandbox_service(
        name="human_agent",
        methods=[start, stop, note],
        until=task_is_complete,
        sandbox=sandbox(),
    )
