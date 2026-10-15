import base64
import mimetypes
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Iterator, Literal
from urllib.parse import urlparse

import httpx

from .file import file as open_file
from .http_defaults import connect_timeout, default_async_client
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
_PROVIDER_IMAGE_MAX_BYTES = 20 * 1024 * 1024


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
            # Fetched on the eval loop alongside model requests, so it needs
            # the same connect deadline — but not the 600s request budget a
            # provider call gets; 30s matches the web-search tool clients.
            async with default_async_client(
                timeout=httpx.Timeout(30.0, connect=connect_timeout())
            ) as client:
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

    if resolved_mime_type in _GENERIC_MIME_TYPES:
        resolved_mime_type = _sniff_image_mime_type(file_bytes) or resolved_mime_type

    # return bytes and type
    return file_bytes, resolved_mime_type


async def file_as_data_uri(file: str, mime_type: str | None = None) -> str:
    if is_data_uri(file):
        declared_mime_type = _normalize_mime_type(data_uri_mime_type(file))
        if mime_type is not None and (
            declared_mime_type is None or declared_mime_type in _GENERIC_MIME_TYPES
        ):
            resolved_mime_type = _select_mime_type(
                declared=declared_mime_type,
                hint=mime_type,
            )
            return as_data_uri(resolved_mime_type, data_uri_to_base64(file))
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


def provider_image_data_uri(image: str) -> str:
    """Validate an inline image returned by a model provider.

    Provider output is untrusted, so only inline data URIs are accepted, and
    only for recognized raster formats up to 20 MiB. Remote image URLs are
    never downloaded.

    Args:
        image: Data URI returned by a model provider.

    Returns:
        A validated inline image data URI.

    Raises:
        ValueError: If `image` is not a data URI or is not a valid image.
    """
    if not is_data_uri(image):
        raise ValueError(
            "Provider images must be inline data URIs; image URLs are not downloaded."
        )
    return _validated_provider_inline_image(image)


def _validated_provider_inline_image(image: str) -> str:
    payload_length = len(image) - image.index(",") - 1
    max_payload_length = 4 * ((_PROVIDER_IMAGE_MAX_BYTES + 2) // 3)
    if payload_length > max_payload_length:
        raise ValueError("Provider image exceeds the 20 MiB size limit.")

    image_bytes, _ = inline_media_data(image, "image")
    if len(image_bytes) > _PROVIDER_IMAGE_MAX_BYTES:
        raise ValueError("Provider image exceeds the 20 MiB size limit.")
    return _provider_image_bytes_data_uri(image_bytes)


def _provider_image_bytes_data_uri(image_bytes: bytes) -> str:
    mime_type = _sniff_image_mime_type(image_bytes)
    if mime_type is None:
        raise ValueError("Provider image is not a recognized raster image.")
    return as_data_uri(
        mime_type,
        base64.b64encode(image_bytes).decode("ascii"),
    )


def inline_media_data(
    file: str,
    expected_kind: MediaKind | None = None,
    mime_type_hint: str | None = None,
) -> tuple[bytes, str]:
    """Decode inline media without performing filesystem or network I/O."""
    _require_inline_media(file)
    file_bytes = _decode_inline_media(file)
    mime_type = _inline_media_mime_type(file, expected_kind, mime_type_hint, file_bytes)

    return file_bytes, mime_type


def inline_media_data_uri(
    file: str,
    expected_kind: MediaKind | None = None,
    mime_type_hint: str | None = None,
) -> str:
    """Validate and return a typed inline media data URI without performing I/O."""
    mime_type = _inline_media_mime_type(file, expected_kind, mime_type_hint)
    if data_uri_mime_type(file) is None:
        return as_data_uri(mime_type, data_uri_to_base64(file))
    return file


def _require_inline_media(file: str) -> None:
    if not is_data_uri(file):
        raise UnresolvedMediaError(
            "Media references must be materialized before model submission. "
            "Trusted code can call inspect_ai.util.materialize_media()."
        )


def _decode_inline_media(file: str) -> bytes:
    try:
        return base64.b64decode(data_uri_to_base64(file), validate=True)
    except ValueError as ex:
        raise ValueError("Inline media data URI contains invalid base64 data.") from ex


def _inline_media_mime_type(
    file: str,
    expected_kind: MediaKind | None,
    mime_type_hint: str | None,
    file_bytes: bytes | None = None,
) -> str:
    _require_inline_media(file)

    mime_type = _normalize_mime_type(data_uri_mime_type(file))
    if mime_type is None:
        mime_type = _normalize_mime_type(mime_type_hint)
    if mime_type is None and expected_kind == "image":
        mime_type = (
            _sniff_image_mime_type(
                file_bytes if file_bytes is not None else _decode_inline_media(file)
            )
            or "image/png"
        )
    if mime_type is None:
        raise ValueError(
            "Inline media data URI does not declare a MIME type and its "
            "content type could not be inferred from the media metadata."
        )

    if expected_kind is not None and not _mime_matches_kind(mime_type, expected_kind):
        raise ValueError(
            f"Inline {expected_kind} media has incompatible MIME type '{mime_type}'."
        )

    return mime_type


def _mime_matches_kind(mime_type: str, kind: MediaKind) -> bool:
    if kind == "document":
        return True
    return mime_type.startswith(f"{kind}/")


def _sniff_image_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


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
