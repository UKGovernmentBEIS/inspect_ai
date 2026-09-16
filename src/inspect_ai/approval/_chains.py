"""Shared machinery for running independent policy chains on one call."""

import sys
from collections.abc import Awaitable, Callable, Hashable, Sequence
from typing import TypeVar

import anyio

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from inspect_ai.tool._tool_call import ToolCallContent, ToolCallView

ChainName = TypeVar("ChainName", bound=Hashable)
"""What a chain is keyed by: its name (`None` for the default chain)."""
Decision = TypeVar("Decision")
"""What a chain resolves to: an `Approval` or a `Review`."""

DEFAULT_CHAIN = "default"
"""Name used for the unlabelled chain in explanations and metadata."""


def chain_label(chain: str | None) -> str:
    return chain if chain is not None else DEFAULT_CHAIN


async def run_chains(
    chains: Sequence[tuple[ChainName, Callable[[], Awaitable[Decision]]]],
    decisive: Callable[[Decision], bool],
) -> dict[ChainName, Decision]:
    """Run every chain concurrently, each to its own decision.

    Nothing is combined here: every chain reaches its decision independently
    (a human in one chain answers their own request). A decisive result, one
    nothing can outrank such as `terminate`, cancels the chains still running,
    since the outcome is settled and, for example, a person should not be
    asked about a sample that is ending. Returns the decisions of the chains
    that finished, keyed by chain; a cancelled chain is absent, and appears as
    "cancelled" in the summary the caller records.
    """
    results: dict[ChainName, Decision] = {}

    try:
        async with anyio.create_task_group() as tg:

            async def run(
                key: ChainName, fn: Callable[[], Awaitable[Decision]]
            ) -> None:
                result = await fn()
                results[key] = result
                if decisive(result):
                    tg.cancel_scope.cancel()

            for key, fn in chains:
                tg.start_soon(run, key, fn)
    except ExceptionGroup as ex:
        # a single failing chain raises what it raised, as a lone chain would,
        # so the tool loop's handlers (limits, tool errors) still recognise it
        if len(ex.exceptions) == 1:
            raise ex.exceptions[0] from None
        raise

    return results


def with_escalation_context(
    view: ToolCallView, escalated_by: str, chain: str | None, explanation: str | None
) -> ToolCallView:
    """The view handed to the next policy in a chain after an escalation.

    The human surfaces render `view.context` above the call, so this is how a
    later approver or reviewer (typically a person) learns who escalated and why.
    """
    where = f' (chain "{chain}")' if chain is not None else ""
    reason = f": {explanation}" if explanation else ""
    text = f"Escalated by {escalated_by}{where}{reason}"
    if view.context is None:
        context = ToolCallContent(title="Escalation", format="markdown", content=text)
    else:
        context = ToolCallContent(
            title=view.context.title,
            format=view.context.format,
            content=f"{view.context.content}\n\n{text}",
        )
    return ToolCallView(context=context, call=view.call)
