from collections.abc import Mapping

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.model._model_output import ModelOutput

SENTINEL_DECISION_HEADER = "x-sentinel-decision"


class SentinelRejectedError(Exception):
    """A sentinel rejected the model's reply. The call is retried."""


def sentinel_error(
    headers: Mapping[str, str] | None, outcome: Exception | ModelOutput
) -> Exception | None:
    """The error to raise in place of a model call's outcome, if a sentinel asks for one.

    A sentinel beside a model proxy refuses a reply with an HTTP error, and
    names its decision in a response header.
    """
    decision = headers.get(SENTINEL_DECISION_HEADER) if headers else None
    if decision == "reject":
        return SentinelRejectedError(_reason(outcome))
    if decision == "terminate":
        return TerminateSampleError(_reason(outcome))
    return None


def _reason(outcome: Exception | ModelOutput) -> str:
    # a provider may have turned the error into output, in its own wording
    if isinstance(outcome, ModelOutput):
        return outcome.error or outcome.completion
    # Anthropic's SDK keeps the error under "error"; OpenAI's unwraps it
    body = getattr(outcome, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) and message else str(outcome)
