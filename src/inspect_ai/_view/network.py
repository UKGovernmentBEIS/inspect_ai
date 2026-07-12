from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_VALIDATED_HOST_SCOPE_KEY = "inspect_ai.viewer_authority"
_VIEW_DOCS_URL = "https://inspect.aisi.org.uk/log-viewer.html"


class ViewerNetworkPolicyError(ValueError):
    """Invalid or unsafe standalone viewer network configuration."""


@dataclass(frozen=True)
class Authority:
    host: str
    port: int | None = None

    def __str__(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}" if self.port is not None else host


@dataclass(frozen=True)
class Origin:
    scheme: str
    authority: Authority

    def __str__(self) -> str:
        return f"{self.scheme}://{self.authority}"


@dataclass(frozen=True)
class ViewerNetworkPolicy:
    bind_host: str
    port: int
    trusted_hosts: frozenset[Authority]
    trusted_origins: frozenset[Origin]
    authorization: str | None = None
    unsafe_allow_unauthenticated: bool = False


def resolve_viewer_network_policy(
    *,
    bind_host: str,
    port: int,
    trusted_hosts: tuple[str, ...] = (),
    trusted_origins: tuple[str, ...] = (),
    authorization: str | None = None,
    unsafe_allow_unauthenticated: bool = False,
) -> ViewerNetworkPolicy:
    """Validate and resolve standalone viewer network trust configuration."""
    if not 1 <= port <= 65535:
        raise ViewerNetworkPolicyError(f"Invalid viewer port: {port}")

    canonical_bind_host = _canonical_hostname(bind_host)
    loopback = _is_loopback_host(canonical_bind_host)
    wildcard = _is_wildcard_host(canonical_bind_host)

    resolved_hosts: set[Authority] = set()
    for value in trusted_hosts:
        try:
            resolved_hosts.add(_parse_authority(value))
        except ValueError as ex:
            raise ViewerNetworkPolicyError(
                f"Invalid trusted host {value!r}: {ex}"
            ) from ex

    resolved_origins: set[Origin] = set()
    for value in trusted_origins:
        try:
            resolved_origins.add(_parse_origin(value))
        except ValueError as ex:
            raise ViewerNetworkPolicyError(
                f"Invalid trusted origin {value!r}: {ex}"
            ) from ex
    resolved_hosts.update(origin.authority for origin in resolved_origins)

    if loopback:
        default_hosts = _loopback_default_hosts(canonical_bind_host)
        for host in default_hosts:
            origin = _http_origin(host, port)
            resolved_hosts.add(origin.authority)
            resolved_origins.add(origin)
    elif not wildcard:
        origin = _http_origin(canonical_bind_host, port)
        resolved_hosts.add(origin.authority)
        resolved_origins.add(origin)

    authorization = authorization or None
    if not loopback and authorization is None and not unsafe_allow_unauthenticated:
        extra = (
            " Wildcard binds also require --trusted-origin or --trusted-host."
            if wildcard
            else ""
        )
        raise ViewerNetworkPolicyError(
            f"Refusing to expose Inspect View on {bind_host} without request "
            "authorization. Configure INSPECT_VIEW_AUTHORIZATION_TOKEN behind "
            "an authenticated proxy, or pass --unsafe-allow-unauthenticated "
            f"to acknowledge unauthenticated network access.{extra} "
            f"See {_VIEW_DOCS_URL}."
        )

    if wildcard and not trusted_hosts and not trusted_origins:
        raise ViewerNetworkPolicyError(
            f"Refusing wildcard bind {bind_host} without an explicit trusted "
            "origin or host. Configure --trusted-origin or --trusted-host. "
            f"See {_VIEW_DOCS_URL}."
        )

    return ViewerNetworkPolicy(
        bind_host=canonical_bind_host,
        port=port,
        trusted_hosts=frozenset(resolved_hosts),
        trusted_origins=frozenset(resolved_origins),
        authorization=authorization,
        unsafe_allow_unauthenticated=unsafe_allow_unauthenticated,
    )


def unsafe_network_warning(policy: ViewerNetworkPolicy) -> str | None:
    if not policy.unsafe_allow_unauthenticated or policy.authorization is not None:
        return None
    return (
        "Inspect View is allowing unauthenticated access on "
        f"{policy.bind_host}:{policy.port}. Any network client that can reach "
        "this address may call viewer APIs."
    )


class HostValidationMiddleware:
    def __init__(self, app: ASGIApp, policy: ViewerNetworkPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        try:
            host = _single_header(scope, b"host", required=True)
            authority = _parse_authority(host)
        except ValueError:
            await _reject(scope, receive, send, 400, "Invalid host header")
            return

        scheme = _http_scheme(str(scope.get("scheme", "http")).lower())
        if not any(
            _authority_matches(authority, trusted, scheme)
            for trusted in self.policy.trusted_hosts
        ):
            await _reject(scope, receive, send, 400, "Invalid host header")
            return

        scope[_VALIDATED_HOST_SCOPE_KEY] = authority  # type: ignore[literal-required]
        await self.app(scope, receive, send)


class BrowserOriginMiddleware:
    def __init__(self, app: ASGIApp, policy: ViewerNetworkPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        try:
            origin_value = _single_header(scope, b"origin", required=False)
            fetch_site = _single_header(
                scope, b"sec-fetch-site", required=False
            ).lower()
        except ValueError:
            await _reject(scope, receive, send, 403, "Forbidden browser origin")
            return

        if fetch_site in ("cross-site", "same-site"):
            await _reject(scope, receive, send, 403, "Forbidden browser origin")
            return

        request_host = scope.get(_VALIDATED_HOST_SCOPE_KEY)
        request_scheme = _http_scheme(str(scope.get("scheme", "http")).lower())

        if origin_value:
            try:
                origin = _parse_origin(origin_value)
            except ValueError:
                await _reject(scope, receive, send, 403, "Forbidden browser origin")
                return

            if (
                origin not in self.policy.trusted_origins
                or origin.scheme != request_scheme
                or not isinstance(request_host, Authority)
                or not _authority_matches(request_host, origin.authority, origin.scheme)
            ):
                await _reject(scope, receive, send, 403, "Forbidden browser origin")
                return
        elif fetch_site == "same-origin" and (
            not isinstance(request_host, Authority)
            or not any(
                origin.scheme == request_scheme
                and _authority_matches(request_host, origin.authority, origin.scheme)
                for origin in self.policy.trusted_origins
            )
        ):
            await _reject(scope, receive, send, 403, "Forbidden browser origin")
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("Content-Security-Policy", "frame-ancestors 'none'")
                headers["X-Frame-Options"] = "DENY"
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _parse_origin(value: str) -> Origin:
    _validate_header_value(value)
    if value == "null" or "?" in value or "#" in value or "\\" in value:
        raise ValueError("Invalid origin")

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if (
        scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise ValueError("Invalid origin")

    try:
        port = parsed.port
    except ValueError as ex:
        raise ValueError("Invalid origin port") from ex

    if parsed.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535):
        raise ValueError("Invalid origin port")

    if port == _default_port(scheme):
        port = None

    return Origin(
        scheme=scheme,
        authority=Authority(_canonical_hostname(parsed.hostname), port),
    )


def _parse_authority(value: str) -> Authority:
    _validate_header_value(value)
    if any(char in value for char in ("/", "\\", "@", ",", "#", "?")):
        raise ValueError("Invalid authority")

    if value.startswith("["):
        close = value.find("]")
        if close == -1:
            raise ValueError("Invalid IPv6 authority")
        host = value[1:close]
        remainder = value[close + 1 :]
        if remainder:
            if not remainder.startswith(":"):
                raise ValueError("Invalid IPv6 authority")
            port = _parse_port(remainder[1:])
        else:
            port = None
        canonical_host = _canonical_hostname(host)
        if ":" not in canonical_host:
            raise ValueError("Bracketed authority is not IPv6")
        return Authority(canonical_host, port)

    if value.count(":") > 1:
        raise ValueError("IPv6 authorities must be bracketed")

    if ":" in value:
        host, port_value = value.rsplit(":", 1)
        port = _parse_port(port_value)
    else:
        host = value
        port = None

    return Authority(_canonical_hostname(host), port)


def _canonical_hostname(value: str) -> str:
    _validate_header_value(value)
    host = value[:-1] if value.endswith(".") else value
    if not host or host.endswith(".") or "%" in host or "*" in host:
        raise ViewerNetworkPolicyError(f"Invalid hostname: {value}")

    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        pass

    ascii_host = host.lower()
    if len(ascii_host) > 253:
        raise ViewerNetworkPolicyError(f"Invalid hostname: {value}")
    labels = ascii_host.split(".")
    if any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise ViewerNetworkPolicyError(f"Invalid hostname: {value}")
    return ascii_host


def _parse_port(value: str) -> int:
    if not value or not value.isascii() or not value.isdigit():
        raise ValueError("Invalid port")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return port


def _validate_header_value(value: str) -> None:
    if (
        not value
        or not value.isascii()
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("Invalid header value")


def _single_header(scope: Scope, name: bytes, *, required: bool) -> str:
    values: list[bytes] = [
        value
        for header_name, value in scope.get("headers", [])
        if header_name.lower() == name
    ]
    if len(values) > 1 or (required and not values):
        raise ValueError("Missing or duplicate header")
    if not values:
        return ""
    try:
        return values[0].decode("ascii")
    except UnicodeDecodeError as ex:
        raise ValueError("Invalid header encoding") from ex


def _authority_matches(request: Authority, trusted: Authority, scheme: str) -> bool:
    if request.host != trusted.host:
        return False
    if request.port == trusted.port:
        return True
    default_port = _default_port(scheme)
    request_port = request.port if request.port is not None else default_port
    trusted_port = trusted.port if trusted.port is not None else default_port
    return request_port == trusted_port


def _default_port(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _http_scheme(scheme: str) -> str:
    if scheme == "ws":
        return "http"
    if scheme == "wss":
        return "https"
    return scheme


def _http_origin(host: str, port: int) -> Origin:
    return Origin(
        "http",
        Authority(host, None if port == 80 else port),
    )


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_wildcard_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def _loopback_default_hosts(bind_host: str) -> tuple[str, ...]:
    if bind_host == "localhost":
        return ("127.0.0.1", "localhost", "::1")
    return (bind_host, "localhost")


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    status_code: int,
    message: str,
) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
    else:
        await PlainTextResponse(message, status_code=status_code)(scope, receive, send)
