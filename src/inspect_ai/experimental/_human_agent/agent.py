from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import input_panel, sandbox

from .install import install_human_agent
from .panel import HumanAgentPanel
from .service import run_human_agent_service


@solver
def human_agent(intermediate_scoring: bool = False) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with await input_panel(HumanAgentPanel) as panel:
            # install agent tool and hookup sandbox connection
            await install_human_agent(state, intermediate_scoring)
            panel.connection = await sandbox().connection()

            # run sandbox service
            return await run_human_agent_service(state, panel)

    return solve
