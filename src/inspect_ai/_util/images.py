import base64
import ipaddress
import mimetypes
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Iterable, Iterator, Literal
from urllib.parse import urlparse

import anyio
import httpcore
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
_IPV4_TRANSLATED_NETWORK = ipaddress.ip_network("::ffff:0:0:0/96")
_NAT64_WELL_KNOWN_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_USE_NETWORK = ipaddress.ip_network("64:ff9b:1::/48")
_PROVIDER_IMAGE_MAX_BYTES = 20 * 1024 * 1024
_PROVIDER_IMAGE_MAX_REDIRECTS = 5
_PROVIDER_IMAGE_REQUEST_TIMEOUT = 10.0
_PROVIDER_IMAGE_TOTAL_TIMEOUT = 30.0
_PROVIDER_IMAGE_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


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
            async with httpx.AsyncClient(follow_redirects=True) as client:
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


async def provider_image_data_uri(image: str) -> str:
    """Safely materialize an image URL returned by a model provider.

    Provider output is untrusted. Remote images are therefore restricted to
    HTTPS on the default port, public IP addresses, bounded responses, and
    recognized raster image formats. DNS is resolved and pinned by the network
    backend so a hostname cannot be rebound to a private address between
    validation and connection.

    Args:
        image: Data URI or remote image URL returned by a model provider.

    Returns:
        A validated inline image data URI.
    """
    if is_data_uri(image):
        return _validated_provider_inline_image(image)

    url = _validated_provider_image_url(httpx.URL(image))
    try:
        with anyio.fail_after(_PROVIDER_IMAGE_TOTAL_TIMEOUT):
            async with httpcore.AsyncConnectionPool(
                network_backend=_PublicNetworkBackend(),
                max_connections=1,
                max_keepalive_connections=1,
            ) as pool:
                return await _download_provider_image(url, pool)
    except (httpcore.NetworkError, httpcore.ProtocolError, TimeoutError, OSError) as ex:
        raise ValueError(
            f"Provider image could not be downloaded from {_url_origin(url)}."
        ) from ex


class _PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend that connects only to DNS-pinned public IP addresses."""

    def __init__(self, backend: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await _public_ip_addresses(host, port)
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    host=str(address),
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as ex:
                last_error = ex

        if last_error is not None:
            raise last_error
        raise ValueError("Provider image hostname did not resolve to a public address.")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.UnsupportedProtocol(
            "Unix sockets are not supported for provider images."
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


async def _public_ip_addresses(
    host: str, port: int
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        address_info = await anyio.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
        addresses = [ipaddress.ip_address(info[4][0]) for info in address_info]

    public_addresses = list(
        dict.fromkeys(a for a in addresses if _is_public_ip_address(a))
    )
    if not public_addresses:
        raise ValueError("Provider image hostname did not resolve to a public address.")
    return public_addresses


def _is_public_ip_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _is_public_ip_address(address.ipv4_mapped)
        if address in _IPV4_TRANSLATED_NETWORK:
            return _is_public_ip_address(ipaddress.IPv4Address(address.packed[-4:]))
        if address in _NAT64_WELL_KNOWN_NETWORK:
            return _is_public_ip_address(ipaddress.IPv4Address(address.packed[-4:]))
        if address in _NAT64_LOCAL_USE_NETWORK:
            # RFC 8215 does not define where a local translator embeds IPv4.
            return False
        if address.sixtofour is not None:
            return _is_public_ip_address(address.sixtofour)
        if address.teredo is not None:
            server, client = address.teredo
            return _is_public_ip_address(server) and _is_public_ip_address(client)
    return address.is_global


def _validated_provider_image_url(url: httpx.URL) -> httpx.URL:
    if url.scheme != "https":
        raise ValueError("Provider image URLs must use HTTPS.")
    if not url.host:
        raise ValueError("Provider image URL must include a hostname.")
    if url.userinfo:
        raise ValueError("Provider image URLs must not include credentials.")
    if url.port is not None and url.port != 443:
        raise ValueError("Provider image URLs must use the default HTTPS port.")
    return url.copy_with(fragment=None)


async def _download_provider_image(
    url: httpx.URL, pool: httpcore.AsyncConnectionPool
) -> str:
    current_url = url
    for redirect_count in range(_PROVIDER_IMAGE_MAX_REDIRECTS + 1):
        async with pool.stream(
            "GET",
            str(current_url),
            headers={
                "Accept": "image/*",
                "Accept-Encoding": "identity",
                "User-Agent": "inspect-ai",
            },
            extensions={
                "timeout": {
                    "connect": _PROVIDER_IMAGE_REQUEST_TIMEOUT,
                    "pool": _PROVIDER_IMAGE_REQUEST_TIMEOUT,
                    "read": _PROVIDER_IMAGE_REQUEST_TIMEOUT,
                    "write": _PROVIDER_IMAGE_REQUEST_TIMEOUT,
                }
            },
        ) as response:
            if response.status in _PROVIDER_IMAGE_REDIRECT_STATUSES:
                location = _response_header(response, b"location")
                if location is None:
                    raise ValueError("Provider image redirect omitted its location.")
                if redirect_count == _PROVIDER_IMAGE_MAX_REDIRECTS:
                    raise ValueError("Provider image URL redirected too many times.")
                current_url = _validated_provider_image_url(current_url.join(location))
                continue

            if not 200 <= response.status < 300:
                raise ValueError(
                    f"Provider image request to {_url_origin(current_url)} returned "
                    f"HTTP {response.status}."
                )

            content_encoding = _response_header(response, b"content-encoding")
            if content_encoding is not None and content_encoding.lower() != "identity":
                raise ValueError("Provider image response must not be encoded.")

            return await _provider_image_response_data_uri(response)

    raise AssertionError("Provider image redirect loop terminated unexpectedly.")


def _validated_provider_inline_image(image: str) -> str:
    payload_length = len(image) - image.index(",") - 1
    max_payload_length = 4 * ((_PROVIDER_IMAGE_MAX_BYTES + 2) // 3)
    if payload_length > max_payload_length:
        raise ValueError("Provider image exceeds the 20 MiB size limit.")

    image_bytes, _ = inline_media_data(image, "image")
    if len(image_bytes) > _PROVIDER_IMAGE_MAX_BYTES:
        raise ValueError("Provider image exceeds the 20 MiB size limit.")
    return _provider_image_bytes_data_uri(image_bytes)


async def _provider_image_response_data_uri(response: httpcore.Response) -> str:
    content_length = _response_header(response, b"content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as ex:
            raise ValueError(
                "Provider image response has an invalid content length."
            ) from ex
        if declared_size < 0 or declared_size > _PROVIDER_IMAGE_MAX_BYTES:
            raise ValueError("Provider image exceeds the 20 MiB size limit.")

    image_bytes = bytearray()
    async for chunk in response.aiter_stream():
        image_bytes.extend(chunk)
        if len(image_bytes) > _PROVIDER_IMAGE_MAX_BYTES:
            raise ValueError("Provider image exceeds the 20 MiB size limit.")

    return _provider_image_bytes_data_uri(bytes(image_bytes))


def _provider_image_bytes_data_uri(image_bytes: bytes) -> str:
    mime_type = _sniff_image_mime_type(image_bytes)
    if mime_type is None:
        raise ValueError("Provider image is not a recognized raster image.")
    return as_data_uri(
        mime_type,
        base64.b64encode(image_bytes).decode("ascii"),
    )


def _response_header(response: httpcore.Response, name: bytes) -> str | None:
    values = [value for key, value in response.headers if key.lower() == name]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(
            f"Provider image response has multiple {name.decode('ascii')} headers."
        )
    try:
        return values[0].decode("ascii")
    except UnicodeDecodeError as ex:
        raise ValueError("Provider image response contains an invalid header.") from ex


def _url_origin(url: httpx.URL) -> str:
    port = f":{url.port}" if url.port is not None else ""
    return f"{url.scheme}://{url.host}{port}"


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
