from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from inspect_ai._sentinel._scope import sentinel_scope


@contextmanager
def model_origin(origin: Literal["environment", "helper"]) -> Iterator[None]:
    """Mark the model calls made within a block as not the agent's own turns.

    Each model call records where it was made (`ModelEvent.origin`). During the solve a call is `"agent"`, one of its conversation's agent turns, unless it is made by a tool, a compaction, an approver, a reviewer, MCP sampling, a sentinel or a scorer, which Inspect marks itself. Use `model_origin()` for a call that is part of the solve but is not the evaluated agent's turn:

    - `"environment"`: the setup being evaluated against, such as an auditor model or a simulated user.
    - `"helper"`: a scaffold's own helper call in its loop, such as its own summarizer.

    A sentinel checks only agent turns at its generate stages, and the transcript timeline shows other calls as utility.

    ```python
    with model_origin("environment"):
        reply = await get_model(role="user").generate(messages)
    ```

    A marked region cannot be overridden from inside it: an agent run within it, or another `model_origin()`, keeps the outer kind, and a sentinel does not check the tool calls made within it.

    The marker is a context variable, so it reaches the calls made in the task that entered the block and in tasks that task starts while inside it, and no others. A task started before the block, or by another task, is not marked. A design that makes the evaluated agent's calls from inside an environment region (for example, an auditor's tool that generates the target's turn) marks those calls as environment too; make them outside the block instead.

    Use it as a `with` block, not as a decorator on an `async def`: as a decorator it marks only the creation of the coroutine, so the calls it makes are left unmarked.

    Args:
        origin: `"environment"` or `"helper"`.
    """
    if origin not in ("environment", "helper"):
        raise ValueError(
            f"model_origin() takes 'environment' or 'helper', not {origin!r}."
        )
    with sentinel_scope(origin, final=True):
        yield
