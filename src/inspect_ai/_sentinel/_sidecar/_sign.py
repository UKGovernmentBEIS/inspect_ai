"""Signing what an eval sends a sentinel sidecar with the eval's token, so the token itself is sent only in a registration."""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping, Sequence

MODEL_REQUEST_FIELDS = (
    "task",
    "sample_id",
    "epoch",
    "sample_uuid",
    "attempt",
    "attempt_number",
)
"""The fields of a model request's `x-inspect-context` its signature covers, in the order they are signed."""

_clock: Callable[[], float] = time.time


def sign(token: str, values: Sequence[object]) -> str:
    """The HMAC-SHA256 of values with an eval's token, as hex.

    The message is the values as strings, in a compact JSON array, so the sidecar builds the same bytes from what it reads.
    """
    message = json.dumps([str(value) for value in values], separators=(",", ":"))
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


def now() -> int:
    """Now, in whole seconds since the epoch, as a signature's timestamp."""
    return int(_clock())


def eval_call_message(method: str, eval_id: str, timestamp: int) -> list[object]:
    """What a call to the endpoint for evals signs: the method, the eval and the time, and none of its other params."""
    return [method, eval_id, timestamp]


def model_request_message(
    context: Mapping[str, object], irid: str, timestamp: int
) -> list[object]:
    """What a model request signs: the sample and attempt its `x-inspect-context` names, the request's `x-irid`, and the time.

    The `x-irid` is signed so that a signature made for one request can't be sent with another request's `x-irid`, as the sidecar keeps what it decided of each request under that id. The eval's id isn't signed, as the sidecar checks the signature with that eval's token; nor is the model.

    Raises:
        KeyError: If the context lacks one of the signed fields.
    """
    return [
        "model-request",
        *(context[name] for name in MODEL_REQUEST_FIELDS),
        irid,
        timestamp,
    ]
