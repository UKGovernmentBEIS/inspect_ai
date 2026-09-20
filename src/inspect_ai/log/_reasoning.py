"""Detection and reporting for responses whose output budget was consumed by reasoning.

When a reasoning model spends its entire output budget on the reasoning channel, the
completion comes back empty while the request itself succeeds: the sample is scored from
nothing, no error is raised, and nothing is logged -- a *silent zero*, where a 0.000 is read
as "the model cannot answer" rather than "the model never spoke".

This module mirrors :mod:`inspect_ai.log._refusal`: the condition is counted per process
(surfaced in the task footer) and warned about once per distinct message, so a run with
three hundred empty completions says so once and reports the volume in the counter.
"""

from logging import getLogger
from typing import TYPE_CHECKING

from inspect_ai._util.logger import warn_once

if TYPE_CHECKING:
    from inspect_ai.model._model_output import ModelOutput

logger = getLogger(__name__)

_reasoning_exhausted_count: int = 0


def reasoning_exhausted_budget(output: "ModelOutput") -> bool:
    """Does this model output show an output budget consumed by reasoning?

    True only when all three conditions hold:

    - the response stopped at the output limit (``stop_reason == "max_tokens"``);
    - there is no visible completion;
    - reported reasoning tokens consumed the whole output token count.

    This requires usage that separates reasoning tokens from output tokens. Providers that
    report reasoning inline in the completion (so there is no separate count) never match,
    and neither do cases where the budget did not bind.
    """
    if output.stop_reason != "max_tokens":
        return False
    if output.completion.strip():
        return False

    usage = output.usage
    if (
        usage is None
        or usage.reasoning_tokens is None
        or usage.output_tokens <= 0
        or usage.reasoning_tokens < usage.output_tokens
    ):
        return False

    return True


def report_reasoning_exhausted(output: "ModelOutput") -> bool:
    """Count (and warn about, once) a response whose budget was consumed by reasoning.

    Returns whether the output matched. Warnings are deduplicated by message, so the first
    occurrence is reported with the model name and token counts and the rest are counted;
    :func:`reasoning_exhausted_count` carries the volume.
    """
    if not reasoning_exhausted_budget(output):
        return False

    global _reasoning_exhausted_count
    _reasoning_exhausted_count = _reasoning_exhausted_count + 1

    usage = output.usage
    reasoning_tokens = usage.reasoning_tokens if usage is not None else None
    output_tokens = usage.output_tokens if usage is not None else None
    warn_once(
        logger,
        f"Model '{output.model}' returned no completion: the output budget was consumed by "
        f"reasoning (reasoning_tokens={reasoning_tokens}, output_tokens={output_tokens}, "
        "stop_reason=max_tokens). Samples scored from this response were not answered by "
        "the model.",
    )
    return True


def reasoning_exhausted_count() -> int:
    """Number of responses whose output budget was consumed by reasoning.

    Process-global: one process can run several evals concurrently, so this cannot be
    reported per eval.
    """
    return _reasoning_exhausted_count


def init_reasoning_exhausted_tracking() -> None:
    """Reset the counter (eval runs start clean; tests use this too)."""
    global _reasoning_exhausted_count
    _reasoning_exhausted_count = 0
