from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._sandbox import sandbox, sandbox_service

from .view import HumanAgentView


async def run_human_agent_service(state: TaskState, view: HumanAgentView) -> None:
    async def start() -> None:
        await view.show_cmd("start")

    async def stop() -> None:
        await view.show_cmd("stop")

    async def note() -> None:
        await view.show_cmd("note")

    return await sandbox_service(
        name="human_agent",
        methods=[start, stop, note],
        until=lambda: False,
        sandbox=sandbox(),
    )
