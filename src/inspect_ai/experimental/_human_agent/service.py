from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._sandbox import sandbox, sandbox_service

from .view import HumanAgentView


async def run_human_agent_service(state: TaskState, view: HumanAgentView) -> None:
    async def start() -> None:
        pass

    async def stop() -> None:
        pass

    async def note() -> None:
        pass

    return await sandbox_service(
        name="human_agent",
        methods=[start, stop, note],
        until=lambda: False,
        sandbox=sandbox(),
    )
