from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import input_panel, sandbox

from .install import install_human_agent
from .panel import HumanAgentPanel
from .service import run_human_agent_service


@solver
def human_agent() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with await input_panel(HumanAgentPanel) as panel:
            try:
                # install human agent tools in sandbox
                await install_human_agent()

                # hookup sandbox connection
                panel.connection = await sandbox().connection()

                # run sandbox service
                await run_human_agent_service(state, panel)

            except Exception:
                pass

        return state

    return solve
