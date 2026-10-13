import contextlib
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ResponseHeaders:
    """The headers of the latest HTTP response to a model call, if one was seen."""

    latest: Mapping[str, str] | None = None


_active: ContextVar[ResponseHeaders | None] = ContextVar(
    "_response_headers", default=None
)


@contextlib.contextmanager
def track_response_headers(headers: ResponseHeaders) -> Iterator[None]:
    token = _active.set(headers)
    try:
        yield
    finally:
        _active.reset(token)


def record_response_headers(headers: Mapping[str, str]) -> None:
    """Record the headers of an HTTP response to the model call in progress.

    For a model provider that makes its own HTTP calls. A provider built on
    Inspect's HTTP hooks has its response headers recorded for it.

    Experimental: not yet a stable API; may change without notice.

    Args:
        headers: The response's headers.
    """
    active = _active.get()
    if active is not None:
        active.latest = {name.lower(): value for name, value in headers.items()}
