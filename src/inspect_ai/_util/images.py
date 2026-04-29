import base64
import mimetypes
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from .file import file as open_file
from .url import (
    data_uri_mime_type,
    data_uri_to_base64,
    is_data_uri,
    is_http_url,
)

_UriResolver = Callable[[str], Awaitable[str]]

_global_uri_resolvers: dict[str, _UriResolver] = {}
_scoped_uri_resolvers: ContextVar[dict[str, _UriResolver]] = ContextVar(
    "_scoped_uri_resolvers", default={}
)


def _get_resolver(scheme: str) -> _UriResolver | None:
    scoped = _scoped_uri_resolvers.get()
    if scheme in scoped:
        return scoped[scheme]
    return _global_uri_resolvers.get(scheme)


def register_uri_resolver(
    scheme: str,
    resolver: Callable[[str], Awaitable[str]],
) -> Callable[[], None]:
    """Register a global URI resolver for a scheme.

    Registers a process-wide resolver. For task-scoped resolvers, use the
    `uri_resolver` context manager instead.

    Args:
        scheme: URI scheme (e.g., "s3", "gs").
        resolver: Async function taking a URI and returning a resolved path,
            URL, or data URI.

    Returns:
        Cleanup function to unregister the resolver.
    """
    _global_uri_resolvers[scheme] = resolver
    return lambda: unregister_uri_resolver(scheme)


def unregister_uri_resolver(scheme: str) -> None:
    """Remove a global URI resolver."""
    _global_uri_resolvers.pop(scheme, None)


@asynccontextmanager
async def uri_resolver(
    scheme: str,
    resolver: Callable[[str], Awaitable[str]],
) -> AsyncIterator[None]:
    """Context manager for task-local URI resolver registration.

    Registers a resolver scoped to the current async task. Takes precedence
    over global resolvers. Stack-safe for nested use with the same scheme.

    Args:
        scheme: URI scheme (e.g., "s3", "gs").
        resolver: Async function taking a URI and returning a resolved path,
            URL, or data URI.
    """
    current = _scoped_uri_resolvers.get()
    new_scoped = current.copy()
    new_scoped[scheme] = resolver
    token = _scoped_uri_resolvers.set(new_scoped)
    try:
        yield
    finally:
        _scoped_uri_resolvers.reset(token)


def _is_uri_with_scheme(file: str) -> str | None:
    # Require :// to distinguish URIs from Windows paths (C:\...)
    if "://" not in file:
        return None
    scheme = urlparse(file).scheme
    return scheme if scheme else None


async def file_as_data(file: str) -> tuple[bytes, str]:
    # Check for custom resolver first
    scheme = _is_uri_with_scheme(file)
    if scheme:
        resolver = _get_resolver(scheme)
        if resolver is not None:
            file = await resolver(file)

    if is_data_uri(file):
        # resolve mime type and base64 content
        mime_type = data_uri_mime_type(file) or "image/png"
        file_base64 = data_uri_to_base64(file)
        file_bytes = base64.b64decode(file_base64)
    else:
        # guess mime type; need strict=False for webp images
        type, _ = mimetypes.guess_type(file, strict=False)
        if type:
            mime_type = type
        else:
            mime_type = "image/png"

        # handle url or file
        if is_http_url(file):
            client = httpx.AsyncClient()
            file_bytes = (await client.get(file)).content
        else:
            with open_file(file, "rb") as f:
                file_bytes = f.read()

    # return bytes and type
    return file_bytes, mime_type


async def file_as_data_uri(file: str) -> str:
    if is_data_uri(file):
        return file
    else:
        bytes, mime_type = await file_as_data(file)
        base64_file = base64.b64encode(bytes).decode("utf-8")
        return as_data_uri(mime_type, base64_file)


def as_data_uri(mime_type: str, data: str) -> str:
    return f"data:{mime_type};base64,{data}"
