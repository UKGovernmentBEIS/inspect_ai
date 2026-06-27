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

_GENERIC_MIME_TYPES = {"application/octet-stream", "binary/octet-stream"}


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


async def file_as_data(file: str, mime_type: str | None = None) -> tuple[bytes, str]:
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
        resolved_mime_type = _select_mime_type(
            declared=data_uri_mime_type(file),
            hint=mime_type,
        )
        file_base64 = data_uri_to_base64(file)
        file_bytes = base64.b64decode(file_base64)
    else:
        # guess mime type; need strict=False for webp images
        guessed_type, _ = mimetypes.guess_type(file, strict=False)

        # handle url or file
        if is_http_url(file):
            async with httpx.AsyncClient() as client:
                response = await client.get(file)
                response.raise_for_status()
                file_bytes = response.content
                resolved_mime_type = _select_mime_type(
                    declared=response.headers.get("content-type"),
                    guessed=guessed_type,
                    hint=mime_type,
                )
        else:
            with open_file(file, "rb") as f:
                file_bytes = f.read()
            resolved_mime_type = _select_mime_type(
                guessed=guessed_type,
                hint=mime_type,
            )

    # return bytes and type
    return file_bytes, resolved_mime_type


async def file_as_data_uri(file: str, mime_type: str | None = None) -> str:
    if is_data_uri(file):
        return file
    else:
        file_bytes, resolved_mime_type = await file_as_data(file, mime_type)
        base64_file = base64.b64encode(file_bytes).decode("utf-8")
        return as_data_uri(resolved_mime_type, base64_file)


async def materialize_media(file: str, mime_type: str | None = None) -> str:
    """Materialize a trusted media reference as a data URI.

    This function may invoke a configured media resolver, make an HTTP request,
    or read from a filesystem. Call it only where trusted code explicitly
    intends to grant a reference that authority.

    Args:
        file: Local path, URL, configured-scheme URI, or existing data URI.
        mime_type: MIME type to use when the reference and any HTTP response do
            not provide a specific type.

    Returns:
        A data URI containing the materialized media bytes.
    """
    return await file_as_data_uri(file, mime_type)


def inline_media_data(
    file: str, expected_kind: MediaKind | None = None
) -> tuple[bytes, str]:
    """Decode inline media without performing filesystem or network I/O."""
    mime_type = _inline_media_mime_type(file, expected_kind)

    try:
        file_bytes = base64.b64decode(data_uri_to_base64(file), validate=True)
    except ValueError as ex:
        raise ValueError("Inline media data URI contains invalid base64 data.") from ex

    return file_bytes, mime_type


def inline_media_data_uri(file: str, expected_kind: MediaKind | None = None) -> str:
    """Validate and return an inline media data URI without decoding or I/O."""
    _inline_media_mime_type(file, expected_kind)
    return file


def _inline_media_mime_type(file: str, expected_kind: MediaKind | None) -> str:
    if not is_data_uri(file):
        raise UnresolvedMediaError(
            "Media references must be materialized before model submission. "
            "Trusted code can call inspect_ai.util.materialize_media()."
        )

    mime_type = _normalize_mime_type(data_uri_mime_type(file))
    if mime_type is None:
        raise ValueError("Inline media data URI does not declare a MIME type.")

    if expected_kind is not None and not _mime_matches_kind(mime_type, expected_kind):
        raise ValueError(
            f"Inline {expected_kind} media has incompatible MIME type '{mime_type}'."
        )

    return mime_type


def _mime_matches_kind(mime_type: str, kind: MediaKind) -> bool:
    if kind == "document":
        return True
    return mime_type.startswith(f"{kind}/")


def _select_mime_type(
    *,
    declared: str | None = None,
    guessed: str | None = None,
    hint: str | None = None,
) -> str:
    declared = _normalize_mime_type(declared)
    guessed = _normalize_mime_type(guessed)
    hint = _normalize_mime_type(hint)

    if declared is not None and declared not in _GENERIC_MIME_TYPES:
        return declared
    if guessed is not None and guessed not in _GENERIC_MIME_TYPES:
        return guessed
    if hint is not None and hint not in _GENERIC_MIME_TYPES:
        return hint
    return declared or guessed or hint or "application/octet-stream"


def _normalize_mime_type(mime_type: str | None) -> str | None:
    if mime_type is None:
        return None
    mime_type = mime_type.partition(";")[0].strip().lower()
    return mime_type if "/" in mime_type else None


def as_data_uri(mime_type: str, data: str) -> str:
    return f"data:{mime_type};base64,{data}"
