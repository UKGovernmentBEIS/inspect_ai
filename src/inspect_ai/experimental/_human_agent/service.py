from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._sandbox import sandbox, sandbox_service
from inspect_ai.util._store import Store

from .view import HumanAgentView


class AgentState:
    AGENT_STATE = "agent_state"

    def __init__(self, store: Store) -> None:
        self.store = store

    @property
    def running(self) -> bool:
        return self.store.get(f"{self.AGENT_STATE}:running", True)

    @running.setter
    def running(self, running: bool) -> None:
        self.store.set(f"{self.AGENT_STATE}:running", running)

    @property
    def time(self) -> float:
        return self.store.get(f"{self.AGENT_STATE}:time", 0.0)

    @time.setter
    def time(self, time: float) -> None:
        self.store.set(f"{self.AGENT_STATE}:time", time)


async def run_human_agent_service(state: TaskState, view: HumanAgentView) -> None:
    # agent_state = AgentState(state.store)

    async def start() -> None:
        view.start_task()

    async def stop() -> None:
        view.stop_task()

    async def note() -> None:
        pass

    def task_is_complete() -> bool:
        return False

    return await sandbox_service(
        name="human_agent",
        methods=[start, stop, note],
        until=task_is_complete,
        sandbox=sandbox(),
    )
