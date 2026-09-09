"""Provider HTTP client defaults (connect deadline, pooling, connect retries)."""

import os
import socket
import urllib.request
from typing import Any, NamedTuple

import anthropic
import groq
import httpx
import httpx._utils
import httpx2._utils
import pytest
from test_helpers.utils import skip_if_trio

import inspect_ai._util._async as _async_backend
import inspect_ai._util.logger as logger_module
from inspect_ai._util import http_defaults, http_defaults_httpx2
from inspect_ai._util.http_defaults import (
    CONNECT_RETRIES_ENV,
    CONNECT_TIMEOUT_ENV,
    DEFAULT_CONNECT_RETRIES,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_POOL_CONNECTIONS,
    KEEPALIVE_EXPIRY_ENV,
    POOL_CONNECTIONS_ENV,
    POOL_KEEPALIVE_CONNECTIONS_ENV,
    REQUEST_TIMEOUT_ENV,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.google import GoogleGenAIAPI
from inspect_ai.model._providers.groq import GroqAPI
from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI

# Most tests need only the module under test; FLAVORS is for the few that also
# construct flavor-typed objects, whose classes are unrelated across the two.
DEFAULT_MODULES = [
    pytest.param(http_defaults, id="httpx"),
    pytest.param(http_defaults_httpx2, id="httpx2"),
]
FLAVORS = [
    pytest.param(http_defaults, httpx, id="httpx"),
    pytest.param(http_defaults_httpx2, httpx2, id="httpx2"),
]


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin proxy resolution to the environment, then clear it.

    `HTTPS_PROXY` is exported on many CI runners and changes how the transport
    is built; a macOS or Windows system proxy would do the same. The
    `INSPECT_HTTP_*` variables are cleared by the fixture in `conftest.py`.
    """
    for var in [name for name in os.environ if name.lower().endswith("_proxy")]:
        monkeypatch.delenv(var, raising=False)
    # httpx binds `getproxies` at import, so patch the name it actually calls;
    # this also keeps a developer's macOS system proxy out of the assertions.
    monkeypatch.setattr(
        httpx._utils, "getproxies", urllib.request.getproxies_environment
    )
    monkeypatch.setattr(
        httpx2._utils, "getproxies", urllib.request.getproxies_environment
    )


def timeout_of(client: Any) -> Any:
    """The SDK client's timeout, which it types as `float | Timeout | None`."""
    timeout = client.timeout
    assert isinstance(timeout, (httpx.Timeout, httpx2.Timeout))
    return timeout


def pool_of(transport: Any) -> Any:
    """The httpcore pool behind a transport (httpx or httpx2).

    httpx publishes no accessor for retries, limits or socket options and is
    unpinned here, so the one reach-through lives here with a diagnosable
    failure.
    """
    pool = getattr(transport, "_pool", None)
    if pool is None:
        raise AssertionError(
            f"{type(transport).__module__}.{type(transport).__name__} has no "
            "_pool; these tests read pool internals to verify transport "
            "configuration"
        )
    return pool


def anthropic_api(**model_args: Any) -> AnthropicAPI:
    return AnthropicAPI(
        model_name="claude-haiku-4-5-20251001", api_key="sk-test", **model_args
    )


def openai_api(**model_args: Any) -> OpenAIAPI:
    return OpenAIAPI(model_name="gpt-4o", api_key="sk-test", **model_args)


def openai_compatible_api(**model_args: Any) -> OpenAICompatibleAPI:
    return OpenAICompatibleAPI(
        model_name="svc/model",
        base_url="https://example.invalid",
        api_key="sk-test",
        service="svc",
        **model_args,
    )


def google_api() -> GoogleGenAIAPI:
    return GoogleGenAIAPI(
        model_name="gemini-2.0-flash",
        base_url=None,
        api_key="test",
        config=GenerateConfig(),
    )


# --- the values themselves --------------------------------------------------


def test_both_flavors_export_the_same_names() -> None:
    # Edit http_defaults.py, then mirror to http_defaults_httpx2.py. The
    # parametrized tests below catch a changed function that was not mirrored;
    # only this catches an added one, because no test references it yet.
    def names(module: object) -> set[str]:
        return {
            n
            for n in dir(module)
            if not n.startswith("__") and n not in ("httpx", "httpx2")
        }

    assert names(http_defaults_httpx2) == names(http_defaults)


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_the_connect_deadline_is_sixty_seconds(defaults: Any) -> None:
    # 5s failed 75% of connects behind a 26s loop block and 15s failed 76.7%;
    # 30s was the first value that cleared it. Changing this needs new data.
    assert defaults.DEFAULT_CONNECT_TIMEOUT == 60.0


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize("limit", [None, "50"], ids=["default", "lowered"])
def test_keepalive_tracks_the_connection_limit(
    monkeypatch: pytest.MonkeyPatch, limit: str | None, defaults: Any
) -> None:
    # Below the cap every connection is destroyed the moment it goes idle,
    # stepping the new-connection rate ~20x once concurrency passes ~120. Two
    # independent defaults would also let the cap sit above the limit.
    expected = DEFAULT_POOL_CONNECTIONS
    if limit is not None:
        monkeypatch.setenv(POOL_CONNECTIONS_ENV, limit)
        expected = int(limit)
    limits = defaults.default_limits()
    assert limits.max_connections == expected
    assert limits.max_keepalive_connections == expected


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_keepalive_can_still_be_set_below_the_connection_limit(
    monkeypatch: pytest.MonkeyPatch, defaults: Any
) -> None:
    monkeypatch.setenv(POOL_KEEPALIVE_CONNECTIONS_ENV, "7")
    limits = defaults.default_limits()
    assert limits.max_connections == DEFAULT_POOL_CONNECTIONS
    assert limits.max_keepalive_connections == 7


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize("limit", [None, "200"], ids=["unset", "explicit"])
def test_an_uncapped_caller_default_yields_only_to_an_explicit_limit(
    monkeypatch: pytest.MonkeyPatch, limit: str | None, defaults: Any
) -> None:
    if limit is not None:
        monkeypatch.setenv(POOL_CONNECTIONS_ENV, limit)
    limits = defaults.default_limits(max_connections=None)
    expected = int(limit) if limit is not None else None
    assert limits.max_connections == expected
    assert limits.max_keepalive_connections == expected


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize(
    "value,expected",
    [
        ("12.5", 12.5),
        ("0", 0.0),
        ("", DEFAULT_CONNECT_TIMEOUT),
        ("   ", DEFAULT_CONNECT_TIMEOUT),
        ("garbage", DEFAULT_CONNECT_TIMEOUT),
        ("-1", DEFAULT_CONNECT_TIMEOUT),
    ],
)
def test_connect_timeout_env_override(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: float,
    defaults: Any,
) -> None:
    monkeypatch.setenv(CONNECT_TIMEOUT_ENV, value)
    assert defaults.default_timeout().connect == expected


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize("value", ["garbage", "-1"], ids=["junk", "negative"])
def test_an_unusable_env_value_keeps_the_caller_default(
    monkeypatch: pytest.MonkeyPatch, value: str, defaults: Any
) -> None:
    # Falling back to the module default instead would silently widen a
    # provider's tighter budget or cap a pool it deliberately left uncapped.
    monkeypatch.setenv(REQUEST_TIMEOUT_ENV, value)
    monkeypatch.setenv(POOL_CONNECTIONS_ENV, value)
    assert defaults.default_timeout(request_timeout=60.0).read == 60.0
    assert defaults.default_limits(max_connections=None).max_connections is None


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_a_zero_connection_pool_is_rejected(
    monkeypatch: pytest.MonkeyPatch, defaults: Any
) -> None:
    # A pool of zero can never issue a request, so it is junk rather than a
    # deliberately tiny setting.
    monkeypatch.setenv(POOL_CONNECTIONS_ENV, "0")
    assert defaults.default_limits().max_connections == DEFAULT_POOL_CONNECTIONS


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize(
    "var,value", [(CONNECT_TIMEOUT_ENV, "60s"), (POOL_CONNECTIONS_ENV, "0")]
)
def test_an_ignored_env_value_is_warned_about(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    var: str,
    value: str,
    defaults: Any,
) -> None:
    # Falling back silently leaves an operator believing their setting took.
    monkeypatch.setattr(logger_module, "_warned", [])
    monkeypatch.setenv(var, value)
    with caplog.at_level("WARNING"):
        defaults.default_limits()
        defaults.default_timeout()
    assert any(var in r.message and value in r.message for r in caplog.records)


@pytest.mark.parametrize("defaults,httpx_mod", FLAVORS)
def test_keepalive_expiry_left_alone_unless_asked(
    monkeypatch: pytest.MonkeyPatch, defaults: Any, httpx_mod: Any
) -> None:
    # Raising it past an intermediary's idle timeout trades these failures for
    # stale-connection ones, so it only moves when a deployment sets it.
    assert (
        defaults.default_limits().keepalive_expiry
        == httpx_mod.Limits().keepalive_expiry
    )
    monkeypatch.setenv(KEEPALIVE_EXPIRY_ENV, "45")
    assert defaults.default_limits().keepalive_expiry == 45.0


# --- the transport ----------------------------------------------------------


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize(
    "env,expected", [(None, DEFAULT_CONNECT_RETRIES), ("4", 4)], ids=["default", "env"]
)
def test_transport_retries_connection_establishment(
    monkeypatch: pytest.MonkeyPatch, env: str | None, expected: int, defaults: Any
) -> None:
    if env is not None:
        monkeypatch.setenv(CONNECT_RETRIES_ENV, env)
    assert pool_of(defaults.default_async_client()._transport)._retries == expected


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_transport_keeps_the_sdk_tcp_keepalive_options(defaults: Any) -> None:
    # Socket options live on the transport, so supplying one drops those the
    # SDK installs and a reaped connection then hangs to the read deadline
    # instead of being surfaced by the kernel.
    pool = pool_of(defaults.default_async_client()._transport)
    sdk_pool = pool_of(anthropic.DefaultAsyncHttpxClient()._transport)
    assert sorted(pool._socket_options) == sorted(sdk_pool._socket_options)
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in pool._socket_options


@pytest.mark.parametrize("defaults,httpx_mod", FLAVORS)
def test_a_caller_transport_is_left_alone(defaults: Any, httpx_mod: Any) -> None:
    supplied = httpx_mod.AsyncHTTPTransport()
    assert defaults.default_async_client(transport=supplied)._transport is supplied


@pytest.mark.parametrize("defaults,httpx_mod", FLAVORS)
async def test_a_caller_request_hook_still_runs(defaults: Any, httpx_mod: Any) -> None:
    seen: list[str] = []

    async def caller_hook(request: httpx.Request) -> None:
        seen.append("caller")

    client = defaults.default_async_client(
        transport=httpx_mod.MockTransport(lambda request: httpx_mod.Response(200)),
        event_hooks={"request": [caller_hook]},
    )
    await client.get("https://example.invalid")
    assert seen == ["caller"]


async def test_the_floor_hook_survives_httpx_hooks_on_httpx2() -> None:
    import httpx2

    from inspect_ai.model._providers.util.hooks import HttpxHooks

    # A client whose own connect deadline is BELOW the floor, so the hook has
    # something to raise and its absence is observable.
    client = http_defaults_httpx2.default_async_client(
        timeout=httpx2.Timeout(30.0, connect=5.0),
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200)),
    )
    # Appends its own request hook after ours; must not displace it.
    HttpxHooks(client)

    seen: dict[str, float] = {}

    async def record(request: httpx2.Request) -> None:
        seen.update(request.extensions.get("timeout") or {})

    client.event_hooks["request"].append(record)
    await client.get("https://example.invalid")

    assert seen["connect"] == http_defaults_httpx2.DEFAULT_CONNECT_TIMEOUT
    assert seen["read"] == 30.0


# --- proxies ----------------------------------------------------------------


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
@pytest.mark.parametrize(
    "var,proxied",
    [
        ("HTTPS_PROXY", True),
        ("Https_Proxy", True),
        ("https_proxy", True),
        ("FTP_PROXY", False),
    ],
)
def test_a_proxy_variable_is_mounted_for_every_spelling(
    monkeypatch: pytest.MonkeyPatch,
    var: str,
    proxied: bool,
    defaults: Any,
) -> None:
    # httpx matches `<scheme>_proxy` case-insensitively but mounts only
    # http/https/all, so an ftp proxy must not produce a mount.
    monkeypatch.setenv(var, "http://proxy.example:3128")
    assert bool(defaults.default_async_client()._mounts) is proxied


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_a_proxy_mount_keeps_the_keepalive_options(
    monkeypatch: pytest.MonkeyPatch, defaults: Any
) -> None:
    # Supplying a transport turns off httpx's proxy discovery. Rebuilding the
    # mounts is what stops a proxied deployment from silently losing the kernel
    # keepalive probes, which is what the SDK's own client would have carried.
    # httpx's proxy pool takes no `retries`, so the connect retry is genuinely
    # unavailable behind a proxy.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    client = defaults.default_async_client()
    mounted = [t for t in client._mounts.values() if t is not None]
    assert mounted, "expected a proxy mount"
    for transport in mounted:
        pool = pool_of(transport)
        assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in pool._socket_options
    assert pool_of(client._transport)._retries == DEFAULT_CONNECT_RETRIES


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_no_proxy_excludes_a_host(
    monkeypatch: pytest.MonkeyPatch, defaults: Any
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("NO_PROXY", "localhost")
    mounts = defaults.default_async_client()._mounts
    assert any(
        transport is None and "localhost" in pattern.pattern
        for pattern, transport in mounts.items()
    )


@pytest.mark.parametrize("defaults", DEFAULT_MODULES)
def test_trust_env_false_disables_proxy_mounts(
    monkeypatch: pytest.MonkeyPatch, defaults: Any
) -> None:
    # httpx itself gates environment proxy discovery on `trust_env`
    # (`allow_env_proxies = trust_env and transport is None`); rebuilding the
    # mounts unconditionally would silently ignore a caller's opt-out.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    assert defaults.default_async_client()._mounts
    assert defaults.default_async_client(trust_env=False)._mounts == {}


def test_openai_sdk_client_takes_our_proxy_mounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DefaultAsyncHttpxClient may build proxy mounts of its own, which ours
    # would replace wholesale.
    from openai import DefaultAsyncHttpxClient

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    bare = DefaultAsyncHttpxClient()
    ours = DefaultAsyncHttpxClient(**http_defaults_httpx2.default_client_kwargs())

    # If the SDK builds its own mounts, ours must not lose any of its keys.
    assert {k.pattern for k in bare._mounts} <= {k.pattern for k in ours._mounts}
    mounted = [t for t in ours._mounts.values() if t is not None]
    assert mounted, "expected a proxy mount"
    for transport in mounted:
        pool = pool_of(transport)
        assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in pool._socket_options


def test_openai_sdk_client_respects_explicit_arguments() -> None:
    import httpx2
    from openai import DefaultAsyncHttpxClient

    client = DefaultAsyncHttpxClient(
        **http_defaults_httpx2.default_client_kwargs(
            timeout=httpx2.Timeout(timeout=1.0, connect=2.0)
        )
    )
    assert client.timeout.connect == 2.0


# --- the connect floor ------------------------------------------------------


@pytest.mark.parametrize("defaults,httpx_mod", FLAVORS)
@pytest.mark.parametrize(
    "connect,expected",
    [
        (5.0, DEFAULT_CONNECT_TIMEOUT),
        (DEFAULT_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT),
        (900.0, 900.0),
        (None, None),
    ],
    ids=["raised", "unchanged", "longer-kept", "no-deadline-kept"],
)
async def test_the_floor_only_ever_raises_the_connect_deadline(
    connect: float | None, expected: float | None, defaults: Any, httpx_mod: Any
) -> None:
    request = httpx_mod.Request(
        "POST",
        "https://example.invalid",
        extensions={"timeout": {"connect": connect, "read": 30.0}},
    )
    await defaults._floor_connect_timeout(request)
    assert request.extensions["timeout"] == {"connect": expected, "read": 30.0}


_CHAT_COMPLETION = {
    "id": "x",
    "object": "chat.completion",
    "created": 0,
    "model": "m",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }
    ],
}


def capture_timeout(
    client: Any, payload: dict[str, Any], httpx_mod: Any = httpx
) -> dict[str, float]:
    """Swap in a mock transport and record the deadlines it is handed.

    The client's own `timeout` reads correct even when a connect deadline has
    collapsed, so it is the wrong thing to assert on. Event hooks are client
    level, so they still run. `httpx_mod` must match the client's flavor: a
    mock from the other flavor fails inside the client.
    """
    seen: dict[str, float] = {}

    def handler(request: Any) -> Any:
        seen.update(request.extensions.get("timeout") or {})
        return httpx_mod.Response(200, json=payload)

    client._transport = httpx_mod.MockTransport(handler)
    return seen


async def transport_timeout(api: Any) -> dict[str, float]:
    seen = capture_timeout(api.client._client, _CHAT_COMPLETION, httpx2)
    await api.client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )
    return seen


@pytest.mark.parametrize(
    "api_factory",
    [openai_api, openai_compatible_api],
    ids=["openai", "openai-compatible"],
)
async def test_a_scalar_client_timeout_does_not_shorten_the_connect_deadline(
    api_factory: Any,
) -> None:
    # The SDK stamps client_timeout into every request as a bare float, which
    # httpx expands to all four deadlines, so without the floor an overall
    # budget silently becomes the connect deadline.
    seen = await transport_timeout(api_factory(client_timeout=30.0))
    assert seen["connect"] == DEFAULT_CONNECT_TIMEOUT
    assert seen["read"] == 30.0


@pytest.mark.parametrize(
    "api_factory",
    [openai_api, openai_compatible_api],
    ids=["openai", "openai-compatible"],
)
async def test_default_connect_deadline_reaches_the_transport(
    api_factory: Any,
) -> None:
    assert (await transport_timeout(api_factory()))["connect"] == (
        DEFAULT_CONNECT_TIMEOUT
    )


async def test_a_longer_connect_deadline_is_left_alone() -> None:
    # service_tier="flex" sets a 900s budget with no user flag; the floor only
    # ever raises, so a deployment that wants a long deadline keeps it.
    assert (await transport_timeout(openai_api(service_tier="flex")))["connect"] == (
        900.0
    )


# --- providers --------------------------------------------------------------


_MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "m",
    "content": [{"type": "text", "text": "hi"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


async def anthropic_transport_timeout(api: AnthropicAPI) -> dict[str, float]:
    seen = capture_timeout(api.client._client, _MESSAGE, httpx2)
    await api.client.messages.create(
        model="m", max_tokens=1, messages=[{"role": "user", "content": "hi"}]
    )
    return seen


class TestAnthropicDefaults:
    def test_client_gets_the_defaults(self) -> None:
        client = anthropic_api().client
        pool = pool_of(client._client._transport)
        assert pool._max_keepalive_connections == DEFAULT_POOL_CONNECTIONS
        assert pool._retries == DEFAULT_CONNECT_RETRIES

    async def test_a_caller_timeout_keeps_the_connect_floor(self) -> None:
        # The caller's budget is theirs, but it must not drag the connect
        # deadline down with it — the failure this module exists to fix.
        seen = await anthropic_transport_timeout(anthropic_api(timeout=3.0))
        assert seen["read"] == 3.0
        assert seen["connect"] == DEFAULT_CONNECT_TIMEOUT

    def test_caller_http_client_wins(self) -> None:
        supplied = httpx2.AsyncClient()
        assert anthropic_api(http_client=supplied).client._client is supplied

    async def test_the_sdk_long_request_guard_still_fires(self) -> None:
        # The SDK runs this check only while `client.timeout` is its own
        # DEFAULT_TIMEOUT. Substituting an equivalent timeout would turn an
        # immediate ValueError into a request that stalls to the read deadline
        # and then retries — the failure this module exists to remove.
        api = anthropic_api()
        # The guard fires before any request, so this transport should never be
        # reached — it is here so a regression fails offline instead of calling
        # the live API.
        capture_timeout(api.client._client, _MESSAGE, httpx2)
        with pytest.raises(ValueError, match="Streaming is required"):
            await api.client.messages.create(
                model="m",
                max_tokens=100_000,
                messages=[{"role": "user", "content": "hi"}],
            )

    def test_an_operator_budget_still_reaches_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Overriding the budget necessarily gives up the SDK guard above; the
        # operator asked for it, so their value must win.
        monkeypatch.setenv(REQUEST_TIMEOUT_ENV, "123")
        assert timeout_of(anthropic_api().client).read == 123.0

    def test_skipped_when_sdk_is_not_httpx_based(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The SDK's own default timeout is our flavor sentinel: if anthropic
        # ever moves off httpx2, it would reject the httpx2 objects we build,
        # which is exactly how openai 3.0 broke every OpenAI-compatible request.
        sdk_default = anthropic.DEFAULT_TIMEOUT
        monkeypatch.setattr(anthropic, "DEFAULT_TIMEOUT", object())
        assert timeout_of(anthropic_api().client).connect == sdk_default.connect


class TestAnthropicClientLifetime:
    """`aclose()` + `initialize()` is the auth-retry path (_model.py before_retry)."""

    async def test_reinitialize_rebuilds_our_closed_client(self) -> None:
        # Reusing a closed client fails every later request with
        # APIConnectionError — the error class these defaults exist to remove,
        # and one inspect treats as transient, so the model retries forever.
        api = anthropic_api()
        first = api.client._client
        await api.aclose()
        assert first.is_closed

        api.initialize()
        second = api.client._client
        assert second is not first
        assert not second.is_closed
        assert second.timeout.connect == DEFAULT_CONNECT_TIMEOUT

    async def test_reinitialize_never_replaces_a_caller_client(self) -> None:
        # Only that we leave it alone. The SDK closes a caller-supplied client
        # on `aclose()` and the caller owns rebuilding it; that predates this
        # module, so do not read this as the client still being usable.
        supplied = httpx2.AsyncClient()
        api = anthropic_api(http_client=supplied)
        await api.aclose()
        api.initialize()
        assert api.client._client is supplied


class GroqSettings(NamedTuple):
    connect: float | None
    read: float | None
    max_connections: int | None
    max_keepalive: int | None
    keepalive_expiry: float | None
    retries: int
    socket_options: Any


def groq_settings(**model_args: Any) -> GroqSettings:
    api = GroqAPI(
        model_name="llama-3.3-70b-versatile", api_key="gsk-test", **model_args
    )
    timeout = timeout_of(api.client)
    pool = pool_of(api.client._client._transport)
    return GroqSettings(
        connect=timeout.connect,
        read=timeout.read,
        max_connections=pool._max_connections,
        max_keepalive=pool._max_keepalive_connections,
        keepalive_expiry=pool._keepalive_expiry,
        retries=pool._retries,
        socket_options=pool._socket_options,
    )


class TestGroqDefaults:
    """Groq supplies its own client, so it needs the defaults applied by hand."""

    def test_connect_deadline_is_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Use a value distinct from groq's own 60s read budget: otherwise
        # `connect == 60` is equally satisfied by connect merely inheriting it.
        monkeypatch.setenv(CONNECT_TIMEOUT_ENV, "77")
        settings = groq_settings()
        assert settings.connect == 77.0
        assert settings.read == groq.DEFAULT_TIMEOUT.read
        assert settings.retries == DEFAULT_CONNECT_RETRIES
        assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in (
            settings.socket_options
        )

    def test_provider_defaults_are_kept(self) -> None:
        # Widening the read budget would take a stalled response from ~3 to ~30
        # minutes, since the SDK retries twice and groq honours no inspect
        # timeout; the uncapped pool is likewise deliberate.
        settings = groq_settings()
        assert settings.read == groq.DEFAULT_TIMEOUT.read
        assert settings.max_connections is not None
        assert settings.max_connections > DEFAULT_POOL_CONNECTIONS

    @pytest.mark.parametrize(
        "var,value,setting,expected",
        [
            (REQUEST_TIMEOUT_ENV, "123", "read", 123.0),
            (KEEPALIVE_EXPIRY_ENV, "42", "keepalive_expiry", 42.0),
            (POOL_CONNECTIONS_ENV, "200", "max_connections", 200),
            (POOL_CONNECTIONS_ENV, "200", "max_keepalive", 200),
        ],
    )
    def test_an_operator_override_beats_a_provider_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        var: str,
        value: str,
        setting: str,
        expected: float,
    ) -> None:
        # Those defaults are a starting point, not a refusal to be configured,
        # and this is the provider most likely to exhaust a descriptor limit.
        monkeypatch.setenv(var, value)
        assert getattr(groq_settings(), setting) == expected

    def test_caller_http_client_wins(self) -> None:
        supplied = httpx.AsyncClient()
        api = GroqAPI(model_name="m", api_key="gsk-test", http_client=supplied)
        assert api.client._client is supplied


def test_mistral_gets_the_defaults() -> None:
    # The SDK client it replaces applies a flat 5s to every phase.
    from inspect_ai.model._providers.mistral import MistralAPI

    api = MistralAPI(model_name="mistral-large-latest", api_key="test")
    client = api._http_default_args()["async_client"]
    assert client.timeout.connect == DEFAULT_CONNECT_TIMEOUT
    pool = pool_of(client._transport)
    assert pool._retries == DEFAULT_CONNECT_RETRIES
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in pool._socket_options


def test_mistral_caller_async_client_wins() -> None:
    from inspect_ai.model._providers.mistral import MistralAPI

    supplied = httpx.AsyncClient()
    api = MistralAPI(
        model_name="mistral-large-latest", api_key="test", async_client=supplied
    )
    assert api._http_default_args()["async_client"] is supplied


def test_google_uses_the_defaults_on_its_httpx_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Google reaches httpx only under trio, and CI never passes --runtrio, so
    # drive the branch directly rather than depending on the live backend.
    #
    # Only transport-level settings apply: google stamps its own scalar timeout
    # (3600s by default) onto every request, so the connect floor never binds
    # and the client's own timeout never reaches the wire.
    monkeypatch.setattr(_async_backend, "current_async_backend", lambda: "trio")
    client = google_api().model_client()._api_client._async_httpx_client
    assert client is not None
    pool = pool_of(client._transport)
    assert pool._retries == DEFAULT_CONNECT_RETRIES
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True) in pool._socket_options


@skip_if_trio
async def test_google_leaves_its_aiohttp_path_alone() -> None:
    # Deliberately uncovered: that path sets no connect deadline at all, so
    # there is none there for a blocked loop to outlast. Drives model_client()
    # under the real (unmocked) asyncio backend: our defaults only apply under
    # trio, so the SDK's own default httpx client — recognisable by its
    # retries, which it never sets — must be the one that comes back.
    client = google_api().model_client()._api_client._async_httpx_client
    assert client is not None
    assert pool_of(client._transport)._retries == 0
