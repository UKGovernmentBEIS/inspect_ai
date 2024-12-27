import asyncio

from inspect_ai.util import display_type, input_panel, sandbox

from .._solver import Generate, Solver, solver
from .._task_state import TaskState
from .commands import human_agent_commands
from .install import install_human_agent
from .panel import HumanAgentPanel
from .service import run_human_agent_service
from .view import ConsoleView, HumanAgentView


@solver
def human_agent(
    answer: bool | str = True,
    intermediate_scoring: bool = False,
    record_session: bool = True,
) -> Solver:
    """Human solver for agentic tasks that run in a Linux environment.

    The Human agent solver installs agent task tools in the default
    sandbox and presents the user with both task instructions and
    documentation for the various tools (e.g. `task submit`,
    `task start`, `task stop` `task instructions`, etc.). A human agent panel
    is displayed with instructions for logging in to the sandbox.

    If the user is running in VS Code with the Inspect extension,
    they will also be presented with links to login to the sandbox
    using a VS Code Window or Terminal.

    Args:
       answer (bool | str): Is an explicit answer required for this
          task or is it scored based on files in the container? Pass a
          `str` with a regex to validate that the answer matches
          the expected format.
       intermediate_scoring (bool): Allow the human agent to
          check their score while working.
       record_session (bool): Record all user commands and outputs in
          the sandbox bash session.

    Returns:
       Solver: Human agent solver.
    """
    # we can only run one human agent interaction at a time (use lock to enforce)
    agent_lock = asyncio.Lock()

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with agent_lock:
            # ensure that we have a sandbox to work with
            try:
                connection = await sandbox().connection()
            except ProcessLookupError:
                raise RuntimeError("Human agent must run in a task with a sandbox.")
            except NotImplementedError:
                raise RuntimeError(
                    "Human agent must run with a sandbox that supports connections."
                )

            # helper function to run the agent (called for fullscreen vs. fallback below)
            async def run_human_agent(view: HumanAgentView) -> TaskState:
                # create agent commands
                commands = human_agent_commands(
                    state, answer, intermediate_scoring, record_session
                )

                # install agent tools
                await install_human_agent(state, commands, record_session)

                # hookup the view ui
                view.connect(connection)

                # run sandbox service
                return await run_human_agent_service(state, commands, view)

            # support both fullscreen ui and fallback
            if display_type() == "full":
                async with await input_panel(HumanAgentPanel) as panel:
                    return await run_human_agent(panel)
            else:
                return await run_human_agent(ConsoleView())

    return solve
