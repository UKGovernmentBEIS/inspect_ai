from logging import getLogger

from inspect_ai._util.logger import warn_once
from inspect_ai.agent._as_solver import as_solver

from ._solver import Solver, solver

logger = getLogger(__name__)


@solver
def human_agent(
    answer: bool | str = True,
    intermediate_scoring: bool = False,
    record_session: bool = True,
    user: str | None = None,
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
       answer: Is an explicit answer required for this task or is it scored
          based on files in the container? Pass a `str` with a regex to validate
          that the answer matches the expected format.
       intermediate_scoring: Allow the human agent to check their score while working.
       record_session: Record all user commands and outputs in the sandbox bash session.
       user: User to login as. Defaults to the sandbox environment's default user.

    Returns:
       Solver: Human agent solver.
    """
    from inspect_ai.agent._human.agent import human_cli

    warn_once(
        logger,
        "The human_agent solver is deprecated. Please use the human_cli agent from the agents module instead.",
    )

    return as_solver(
        human_cli(
            answer=answer,
            intermediate_scoring=intermediate_scoring,
            record_session=record_session,
            user=user,
        )
    )
