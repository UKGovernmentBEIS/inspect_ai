import base64
import mimetypes
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Iterator, Literal
from urllib.parse import urlparse

import httpx

from .file import file as open_file
from .url import (
    data_uri_mime_type,
    data_uri_to_base64,
    is_data_uri,
    is_http_url,
)

MediaResolverFunc = Callable[[str], Awaitable[str]]
"""Type alias for media resolver functions.

A media resolver is an async function that takes a URI string and returns
a resolved path, URL, or data URI.
"""

MediaKind = Literal["image", "audio", "video", "document"]
"""Media type expected by an inline media consumer."""


class UnresolvedMediaError(ValueError):
    """Media reference must be explicitly materialized before use."""


_media_resolvers: ContextVar[dict[str, MediaResolverFunc]] = ContextVar(
    "_media_resolvers"
)


def _get_resolver(scheme: str) -> MediaResolverFunc | None:
    try:
        return _media_resolvers.get().get(scheme)
    except LookupError:
        return None


@contextmanager
def media_resolver(
    scheme: str,
    resolver: MediaResolverFunc,
) -> Iterator[None]:
    """Context manager for registering a media URI resolver.

    Registers a resolver scoped to the current context for resolving
    custom URI schemes in media content (images, audio, video). Stack-safe
    for nested use with the same scheme.

    Note: The resolver is called at most once per URI. The returned value
    is not re-resolved, so returning another custom scheme URI will not
    trigger additional resolver lookups.

    Args:
        scheme: URI scheme (e.g., "s3", "gs").
        resolver: Async function taking a URI and returning a resolved path,
            URL, or data URI.
    """
    try:
        current = _media_resolvers.get()
    except LookupError:
        current = {}
    new_scoped = current.copy()
    new_scoped[scheme] = resolver
    token = _media_resolvers.set(new_scoped)
    try:
        yield
    finally:
        _media_resolvers.reset(token)


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
            try:
                file = await resolver(file)
            except Exception as e:
                raise ValueError(
                    f"Media resolver for scheme '{scheme}' failed on '{file}'"
                ) from e

    if is_data_uri(file):
        # resolve mime type and base64 content
        mime_type = data_uri_mime_type(file) or "image/png"
        file_base64 = data_uri_to_base64(file)
        file_bytes = base64.b64decode(file_base64)
    else:
        # guess mime type; need strict=False for webp images
        guessed_type, _ = mimetypes.guess_type(file, strict=False)
        if guessed_type:
            mime_type = guessed_type
        else:
            mime_type = "image/png"

        # handle url or file
        if is_http_url(file):
            async with httpx.AsyncClient() as client:
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
        file_bytes, mime_type = await file_as_data(file)
        base64_file = base64.b64encode(file_bytes).decode("utf-8")
        return as_data_uri(mime_type, base64_file)


async def materialize_media(file: str) -> str:
    """Materialize a trusted media reference as a data URI.

    This function may invoke a configured media resolver, make an HTTP request,
    or read from a filesystem. Call it only where trusted code explicitly
    intends to grant a reference that authority.

    Args:
        file: Local path, URL, configured-scheme URI, or existing data URI.

    Returns:
        A data URI containing the materialized media bytes.
    """
    return await file_as_data_uri(file)


def inline_media_data(
    file: str, expected_kind: MediaKind | None = None
) -> tuple[bytes, str]:
    """Decode inline media without performing filesystem or network I/O."""
    if not is_data_uri(file):
        raise UnresolvedMediaError(
            "Media references must be materialized before model submission. "
            "Trusted code can call inspect_ai.util.materialize_media()."
        )

    mime_type = data_uri_mime_type(file)
    if mime_type is None:
        raise ValueError("Inline media data URI does not declare a MIME type.")

    if expected_kind is not None and not _mime_matches_kind(mime_type, expected_kind):
        raise ValueError(
            f"Inline {expected_kind} media has incompatible MIME type '{mime_type}'."
        )

    try:
        file_bytes = base64.b64decode(data_uri_to_base64(file), validate=True)
    except ValueError as ex:
        raise ValueError("Inline media data URI contains invalid base64 data.") from ex

    return file_bytes, mime_type


def inline_media_data_uri(file: str, expected_kind: MediaKind | None = None) -> str:
    """Validate and return an inline media data URI without performing I/O."""
    inline_media_data(file, expected_kind)
    return file


def _mime_matches_kind(mime_type: str, kind: MediaKind) -> bool:
    if kind == "document":
        return True
    return mime_type.startswith(f"{kind}/")


def as_data_uri(mime_type: str, data: str) -> str:
    return f"data:{mime_type};base64,{data}"
