from re import Pattern

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import display_type, input_panel, input_screen, sandbox

from .commands import human_agent_commands
from .install import install_human_agent
from .panel import HumanAgentPanel
from .service import run_human_agent_service
from .view import ConsoleView, HumanAgentView


@solver
def human_agent(
    answer: bool | Pattern[str] = True, record_session: bool = True
) -> Solver:
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
        async def run_human_agent(view: HumanAgentView) -> TaskState:
            # create agent commands
            commands = human_agent_commands(answer)

            # install agent tools
            await install_human_agent(state, commands, record_session)

            # set connection on view
            view.connect(await sandbox().connection())

            # run sandbox service
            return await run_human_agent_service(state, commands, view)

        # support both fullscreen ui and fallback
        if display_type() == "full":
            async with await input_panel(HumanAgentPanel) as panel:
                return await run_human_agent(panel)
        else:
            with input_screen(transient=False) as console:
                return await run_human_agent(ConsoleView(console))

    return solve
