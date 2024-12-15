from re import Pattern

from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import input_panel, sandbox

from .commands import human_agent_commands
from .install import install_human_agent
from .panel import HumanAgentPanel
from .service import run_human_agent_service


@solver
def human_agent(answer: bool | Pattern, record_session: bool = True) -> Solver:
    """Human solver for agentic tasks that run in a Linux environment.

    The Human agent solver installs agent task tools in the default
    sandbox and presents the user with both task instructions and
    documentation for the various tools (e.g. `task submit`,
    `task clock`, `task instructions`, etc.). A human agent panel
    is displayed with instructions for logging in to the sandbox.

    If the user is running in VS Code with the Inspect extension,
    they will also be presented with links to login to the sandbox
    using a VS Code Window or Terminal.

    Args:
       answer (bool | Pattern): Is an explicit answer required for this
          task or is it scored based on files in the container? Pass a
          `Pattern` to validate that the answer matches the expected format.
       record_session (bool): Record all user commands and outputs in
          the sandbox bash session.

    Returns:
       Solver: Human agent solver.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with await input_panel(HumanAgentPanel) as panel:
            # get agent commands
            commands = human_agent_commands()

            # install agent tools
            await install_human_agent(state, commands, record_session)

            # show panel ui for agent session
            panel.connection = await sandbox().connection()

            # run sandbox service
            return await run_human_agent_service(state, commands, panel)

    return solve
