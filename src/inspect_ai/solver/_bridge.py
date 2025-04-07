from logging import getLogger
from typing import Any, Awaitable, Callable

from inspect_ai._util.logger import warn_once
from inspect_ai.agent._as_solver import as_solver

from ._solver import Solver, solver

logger = getLogger(__name__)


@solver
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Solver:
    """Bridge an external agent into an Inspect Solver.

    See documentation at <https://inspect.ai-safety-institute.org.uk/agent-bridge.html>

    Args:
      agent: Callable which takes a sample `dict` and returns a result `dict`.

    Returns:
      Standard Inspect solver.
    """
    from inspect_ai.agent._bridge.bridge import bridge as agent_bridge

    warn_once(
        logger,
        "The bridge solver is deprecated. Please use the bridge agent from the agents module instead.",
    )

    return as_solver(agent_bridge(agent))
