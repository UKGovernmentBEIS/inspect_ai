from logging import Logger
from typing import Callable, NamedTuple

from inspect_ai.core._model_output import (
    ChatCompletionChoice as ChatCompletionChoice,
)
from inspect_ai.core._model_output import (
    Logprob as Logprob,
)
from inspect_ai.core._model_output import (
    Logprobs as Logprobs,
)
from inspect_ai.core._model_output import (
    ModelFallback as ModelFallback,
)
from inspect_ai.core._model_output import (
    ModelOutput as ModelOutput,
)
from inspect_ai.core._model_output import (
    ModelUsage as ModelUsage,
)
from inspect_ai.core._model_output import (
    StopCategory as StopCategory,
)
from inspect_ai.core._model_output import (
    StopDetails as StopDetails,
)
from inspect_ai.core._model_output import (
    StopReason as StopReason,
)
from inspect_ai.core._model_output import (
    TopLogprob as TopLogprob,
)

from ._model_data.model_data import ModelCost


class ServedModelUsage(NamedTuple):
    """Part of a call's usage and the model that served it, for pricing."""

    model: str
    """Model info name of the serving model (e.g. `"anthropic/claude-opus-4-8"`)."""

    usage: ModelUsage
    """Usage served by `model`."""

    cost: ModelCost | None = None
    """Cost data for `model`, when the provider has it (otherwise looked up by `model`)."""


def collect_stop_details(
    provider: str,
    logger: Logger,
    fn: Callable[[], StopDetails | None],
) -> StopDetails | None:
    """Defensively collect `StopDetails` from a provider response.

    Calls `fn()` (a provider-specific extractor), catching any unexpected data
    shape so a surprising payload warns rather than breaking generation. Also
    normalizes the result: drops empty details and keeps the scalar `category`
    in sync with `categories[0]`.

    Args:
        provider: Provider name (used in the warning message).
        logger: Logger to emit a one-time warning to on failure.
        fn: Extractor returning `StopDetails | None`.

    Returns:
        Normalized `StopDetails`, or `None` when there is nothing to report or
        an unexpected shape was encountered.
    """
    try:
        details = fn()
    except Exception as ex:
        from inspect_ai._util.logger import warn_once

        warn_once(
            logger,
            f"Unexpected data shape collecting stop_details from {provider}: {ex}",
        )
        return None

    # only attach when there is something to report
    if details is None or (not details.categories and not details.explanation):
        return None

    # keep the high-level summary in sync with the canonical list
    if details.category is None and details.categories:
        details.category = details.categories[0].category
    if details.explanation is None and details.categories:
        details.explanation = _summarize_stop_categories(details.categories)

    return details


def _summarize_stop_categories(categories: list[StopCategory]) -> str:
    """Synthesize a human-readable explanation from a list of categories."""
    parts = [f"{c.category} ({c.level})" if c.level else c.category for c in categories]
    return "Content filtered: " + ", ".join(parts)


def as_stop_reason(reason: str | None) -> StopReason:
    """Encode common reason strings into standard StopReason."""
    match reason:
        case "stop" | "eos":
            return "stop"
        case "length":
            return "max_tokens"
        case "tool_calls" | "function_call":
            return "tool_calls"
        case "content_filter" | "model_length" | "max_tokens":
            return reason
        case _:
            return "unknown"
