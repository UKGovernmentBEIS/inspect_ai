"""Tests for bridge header extraction and filtering."""

import gzip
import importlib
import importlib.metadata
import importlib.util
import json
import sys
from typing import Any, cast

import httpx
import httpx2
import pytest
from httpx._decoders import SUPPORTED_DECODERS as HTTPX_DECODERS
from httpx2._decoders import SUPPORTED_DECODERS as HTTPX2_DECODERS
from packaging.requirements import Requirement

from inspect_ai._util import logger as inspect_logger
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge import bridge as bridge_module
from inspect_ai.agent._bridge.bridge import (
    _BLOCKED_BRIDGE_HEADER_PREFIXES,
    _BLOCKED_BRIDGE_HEADERS,
    filter_bridge_headers,
    filter_sandbox_client_headers,
    resolve_forward_client_headers,
)
from inspect_ai.agent._bridge.sandbox.service import (
    generate_anthropic,
    generate_completions,
    generate_responses,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.util import merge_extra_headers
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

# brotli ships no type stubs; binding it via importlib keeps mypy clean without a
# suppression. requirements-dev.txt installs it for these tests; Inspect does not
# depend on it. PyPy gets brotlicffi instead, as httpx does.
try:
    brotli = importlib.import_module("brotli")
except ImportError:
    brotli = importlib.import_module("brotlicffi")
zstandard = importlib.import_module("zstandard")


class TestFilterBridgeHeaders:
    """Test filter_bridge_headers function."""

    def test_none_input_returns_none(self):
        """Test that None input returns None."""
        assert filter_bridge_headers(None) is None

    def test_empty_dict_returns_none(self):
        """Test that empty dict returns None."""
        assert filter_bridge_headers({}) is None

    def test_custom_headers_pass_through(self):
        """Test that custom headers are preserved."""
        headers = {
            "x-custom-header": "value1",
            "x-my-app-id": "12345",
            "x-request-context": "test",
        }
        result = filter_bridge_headers(headers)
        assert result == headers

    def test_blocked_headers_removed(self):
        """Test that blocked headers are removed."""
        headers = {
            "authorization": "Bearer secret",
            "x-api-key": "sk-1234",
            "x-irid": "request-id-123",
            "content-type": "application/json",
            "content-length": "1024",
            "host": "api.example.com",
            "x-custom-header": "keep-me",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom-header": "keep-me"}

    def test_blocked_headers_case_insensitive(self):
        """Test that header blocking is case-insensitive."""
        headers = {
            "Authorization": "Bearer secret",
            "X-API-KEY": "sk-1234",
            "X-IRID": "request-id-123",
            "Content-Type": "application/json",
            "x-custom-header": "keep-me",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom-header": "keep-me"}

    def test_stainless_prefix_blocked(self):
        """Test that x-stainless-* headers are blocked."""
        headers = {
            "x-stainless-lang": "python",
            "x-stainless-package-version": "1.0.0",
            "x-stainless-os": "Darwin",
            "x-stainless-arch": "arm64",
            "x-stainless-retry-count": "0",
            "x-custom-header": "keep-me",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom-header": "keep-me"}

    def test_anthropic_beta_allowed(self):
        """Test that anthropic-beta header is NOT blocked.

        This header is used for legitimate feature flags like
        code-execution-2025-08-25.
        """
        headers = {
            "anthropic-beta": "code-execution-2025-08-25",
            "x-custom-header": "value",
        }
        result = filter_bridge_headers(headers)
        assert result == headers

    def test_anthropic_version_blocked(self):
        """Test that anthropic-version header IS blocked.

        This is SDK-managed and should not be overridden by clients.
        """
        headers = {
            "anthropic-version": "2023-06-01",
            "x-custom-header": "keep-me",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom-header": "keep-me"}

    def test_all_headers_blocked_returns_none(self):
        """Test that all-blocked headers returns None."""
        headers = {
            "authorization": "Bearer secret",
            "x-api-key": "sk-1234",
            "content-type": "application/json",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_transfer_encoding_blocked(self):
        """Test that transfer-encoding is blocked."""
        headers = {
            "transfer-encoding": "chunked",
            "connection": "keep-alive",
            "x-custom": "value",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom": "value"}

    def test_user_agent_blocked(self):
        """Test that User-Agent is blocked.

        Since Inspect transforms the request, the original client's
        User-Agent would be misleading. The SDK sets its own User-Agent
        which accurately reflects what's making the HTTP call.
        """
        headers = {
            "User-Agent": "pydantic-ai/1.44.0",
            "x-custom": "value",
        }
        result = filter_bridge_headers(headers)
        assert result == {"x-custom": "value"}

    def test_mixed_blocked_and_allowed(self):
        """Test mixed headers with some blocked and some allowed."""
        headers = {
            # Blocked
            "Authorization": "Bearer token",
            "x-stainless-os": "Linux",
            "Content-Type": "application/json",
            # Allowed
            "anthropic-beta": "computer-use-2024-10-22",
            "x-my-trace-id": "abc123",
            "x-request-source": "agent",
        }
        result = filter_bridge_headers(headers)
        assert result == {
            "anthropic-beta": "computer-use-2024-10-22",
            "x-my-trace-id": "abc123",
            "x-request-source": "agent",
        }

    def test_tenant_and_custom_headers_pass_through(self):
        """In-process, the scaffold is the eval's own code: its headers are kept."""
        headers = {
            "OpenAI-Organization": "org-123",
            "OpenAI-Project": "proj-456",
            "x-custom-header": "value",
            "Accept-Encoding": "gzip, br",
            "anthropic-beta": "beta-a-2026-01-01,beta-b-2026-01-01",
            "Authorization": "Bearer secret",
        }
        result = filter_bridge_headers(headers)
        assert result == {
            "OpenAI-Organization": "org-123",
            "OpenAI-Project": "proj-456",
            "x-custom-header": "value",
            "Accept-Encoding": "gzip, br",
            "anthropic-beta": "beta-a-2026-01-01,beta-b-2026-01-01",
        }

    def test_httpx_decodes_forwarded_brotli_response(self):
        """The bridge transport decodes any encoding it advertises.

        Forwarding Accept-Encoding is only faithful to the client if the
        transport can also read what the provider sends back: once `br` is
        forwarded, Anthropic actually responds brotli-encoded.
        """
        payload = {"model": "claude-fable-5", "type": "message"}

        def handler(request: httpx.Request) -> httpx.Response:
            assert "br" in request.headers["accept-encoding"].split(", ")
            return httpx.Response(
                200,
                content=brotli.compress(json.dumps(payload).encode()),
                headers={
                    "content-encoding": "br",
                    "content-type": "application/json",
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            assert client.get("https://api.anthropic.com/v1/messages").json() == payload


class TestBlockedHeadersConfiguration:
    """Test the blocked headers configuration."""

    def test_blocked_headers_are_lowercase(self):
        """Verify all blocked headers are lowercase for case-insensitive comparison."""
        for header in _BLOCKED_BRIDGE_HEADERS:
            assert header == header.lower(), f"Header '{header}' should be lowercase"

    def test_blocked_prefixes_are_lowercase(self):
        """Verify all blocked prefixes are lowercase."""
        for prefix in _BLOCKED_BRIDGE_HEADER_PREFIXES:
            assert prefix == prefix.lower(), f"Prefix '{prefix}' should be lowercase"

    def test_required_headers_in_blocklist(self):
        """Verify critical headers are in the blocklist."""
        required_blocked = [
            "authorization",
            "x-api-key",
            "x-irid",
            "content-type",
            "content-length",
            "host",
            "user-agent",
        ]
        for header in required_blocked:
            assert header in _BLOCKED_BRIDGE_HEADERS, (
                f"Critical header '{header}' should be blocked"
            )

    def test_anthropic_beta_not_blocked(self):
        """Verify anthropic-beta is NOT in the blocklist."""
        assert "anthropic-beta" not in _BLOCKED_BRIDGE_HEADERS


def _logged_drops() -> list[str]:
    return sorted(bridge_module._logged_client_header_drops)


def _sandbox_filter(
    headers: dict[str, str], forward_client_headers: dict[str, list[str]] | None
) -> dict[str, str] | None:
    return filter_sandbox_client_headers(
        headers, resolve_forward_client_headers(forward_client_headers)
    )


class TestForwardClientHeaders:
    """The sandbox bridge's `forward_client_headers` allowlist."""

    def setup_method(self) -> None:
        inspect_logger._warned.clear()
        bridge_module._logged_client_header_drops.clear()

    def test_default_forwards_only_accept_encoding(self) -> None:
        headers = {
            "anthropic-beta": "context-1m-2025-08-07",
            "Accept-Encoding": "gzip, br",
            "x-custom-header": "value",
        }
        assert _sandbox_filter(headers, None) == {"Accept-Encoding": "gzip, br"}
        assert _logged_drops() == [
            "Agent bridge did not forward the sandboxed agent's 'anthropic-beta' "
            "header. To forward it, list it in "
            "sandbox_agent_bridge(forward_client_headers=...).",
            "Agent bridge did not forward the sandboxed agent's 'x-custom-header' "
            "header. To forward it, list it in "
            "sandbox_agent_bridge(forward_client_headers=...).",
        ]

    def test_unlisted_and_blocked_headers_not_warned(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        headers = {
            "x-stainless-os": "Linux",
            "authorization": "Bearer secret",
            "x-custom-header": "value",
        }
        with caplog.at_level("INFO", logger=bridge_module.logger.name):
            assert _sandbox_filter(headers, None) is None
            _sandbox_filter(headers, None)
        # unlisted names are logged once each at info level; blocked ones never
        assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
            (
                "INFO",
                "Agent bridge did not forward the sandboxed agent's "
                "'x-custom-header' header. To forward it, list it in "
                "sandbox_agent_bridge(forward_client_headers=...).",
            )
        ]

    def test_tenant_headers_dropped_unless_listed(self) -> None:
        """Sandbox code must not choose another org or project on the host key."""
        headers = {
            "OpenAI-Organization": "org-attacker-controlled",
            "OpenAI-Project": "proj-attacker-controlled",
            "x-goog-user-project": "attacker-controlled-project",
            "Accept-Encoding": "gzip",
        }
        assert _sandbox_filter(headers, None) == {"Accept-Encoding": "gzip"}

    def test_listed_values_forwarded_and_others_dropped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only listed tokens survive; whitespace around them is tolerated."""
        headers = {"Anthropic-Beta": "beta-a-2026-01-01, beta-b-2026-01-01,beta-c"}
        with caplog.at_level("WARNING", logger=bridge_module.logger.name):
            result = _sandbox_filter(
                headers, {"anthropic-beta": ["beta-a-2026-01-01", "beta-c"]}
            )
            _sandbox_filter(headers, {"anthropic-beta": ["beta-a-2026-01-01"]})
        assert result == {"Anthropic-Beta": "beta-a-2026-01-01,beta-c"}
        # each dropped token is warned about once
        assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
            (
                "WARNING",
                "Agent bridge dropped 'beta-b-2026-01-01' from the sandboxed "
                "agent's 'anthropic-beta' header. To forward it, add it to "
                "sandbox_agent_bridge(forward_client_headers=...).",
            ),
            (
                "WARNING",
                "Agent bridge dropped 'beta-c' from the sandboxed agent's "
                "'anthropic-beta' header. To forward it, add it to "
                "sandbox_agent_bridge(forward_client_headers=...).",
            ),
        ]

    def test_header_dropped_when_no_values_remain(self) -> None:
        result = _sandbox_filter(
            {"anthropic-beta": "beta-d-2026-01-01", "Accept-Encoding": "br"},
            {"anthropic-beta": ["beta-a-2026-01-01"]},
        )
        assert result == {"Accept-Encoding": "br"}
        assert any("beta-d-2026-01-01" in m for m in _logged_drops())

    def test_dropped_header_logs_are_bounded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Client-chosen names and values cannot grow the log or its cache."""
        cap = bridge_module._MAX_LOGGED_CLIENT_HEADER_DROPS
        long_token = "beta-" + "x" * 500
        with caplog.at_level("INFO", logger=bridge_module.logger.name):
            _sandbox_filter(
                {"anthropic-beta": long_token}, {"anthropic-beta": ["beta-a"]}
            )
            for i in range(cap + 50):
                _sandbox_filter({f"x-minted-{i}": "1"}, None)
        assert len(bridge_module._logged_client_header_drops) == cap
        assert len(caplog.records) == cap
        assert "x" * 500 not in caplog.records[0].getMessage()
        assert "'beta-" + "x" * 59 + "...'" in caplog.records[0].getMessage()
        assert (
            caplog.records[-1]
            .getMessage()
            .endswith("Further dropped client headers will not be logged.")
        )

    @pytest.mark.parametrize(
        "headers",
        [
            ["anthropic-beta", "beta-a"],
            "anthropic-beta: beta-a",
            5,
        ],
    )
    def test_non_mapping_client_headers_ignored(self, headers: Any) -> None:
        """Headers arrive as untrusted JSON from the sandbox proxy."""
        assert (
            filter_sandbox_client_headers(
                headers, resolve_forward_client_headers({"anthropic-beta": ["beta-a"]})
            )
            is None
        )
        assert len(inspect_logger._warned) == 1

    def test_non_string_client_header_entries_dropped(self) -> None:
        headers: Any = {
            "anthropic-beta": ["beta-a"],
            "accept-encoding": None,
            "x-allowed": 1,
            5: "beta-a",
            "Anthropic-Beta": "beta-a, beta-b",
        }
        result = filter_sandbox_client_headers(
            headers,
            resolve_forward_client_headers(
                {"anthropic-beta": ["beta-a"], "x-allowed": ["1"]}
            ),
        )
        assert result == {"Anthropic-Beta": "beta-a"}
        assert [m for m in inspect_logger._warned if "not a string" in m] == [
            "Agent bridge dropped request headers from the sandboxed agent whose "
            "name or value was not a string."
        ]

    def test_header_names_case_insensitive(self) -> None:
        result = _sandbox_filter(
            {"X-MY-HEADER": "on"}, {"x-My-Header": ["on"], "X-Other": ["1"]}
        )
        assert result == {"X-MY-HEADER": "on"}

    def test_listing_accept_encoding_rejected(self) -> None:
        """Its codings follow what the host can decode, not an allowlist."""
        with pytest.raises(ValueError, match="accept-encoding"):
            resolve_forward_client_headers({"Accept-Encoding": ["br"]})

    @pytest.mark.parametrize("value", ["a, b", "a,b", ","])
    def test_values_with_commas_rejected(self, value: str) -> None:
        """The client's header is matched one comma-separated item at a time."""
        with pytest.raises(ValueError, match="comma"):
            resolve_forward_client_headers({"x-foo": [value]})

    def test_bare_string_mapping_rejected(self) -> None:
        with pytest.raises(TypeError, match="forward_client_headers"):
            resolve_forward_client_headers(cast(Any, "anthropic-beta"))

    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(TypeError, match="forward_client_headers"):
            resolve_forward_client_headers(cast(Any, ["anthropic-beta"]))

    def test_bare_string_values_rejected(self) -> None:
        """A bare string would otherwise become a set of its characters."""
        with pytest.raises(TypeError, match="anthropic-beta"):
            resolve_forward_client_headers(
                cast(Any, {"anthropic-beta": "context-1m-2025-08-07"})
            )

    @pytest.mark.parametrize(
        "forward_client_headers,match",
        [
            ({"anthropic-beta": None}, "anthropic-beta"),
            ({"anthropic-beta": 5}, "anthropic-beta"),
            ({"anthropic-beta": [None]}, "None"),
            ({"anthropic-beta": ["beta-a", 5]}, "5"),
            ({5: ["on"]}, "names must be strings"),
            ({None: ["on"]}, "names must be strings"),
        ],
    )
    def test_non_string_names_and_values_rejected(
        self, forward_client_headers: Any, match: str
    ) -> None:
        with pytest.raises(TypeError, match=match):
            resolve_forward_client_headers(forward_client_headers)

    def test_names_and_values_stripped(self) -> None:
        resolved = resolve_forward_client_headers(
            {" Anthropic-Beta ": [" beta-a-2026-01-01 "]}
        )
        assert resolved == {"anthropic-beta": frozenset({"beta-a-2026-01-01"})}
        assert _sandbox_filter(
            {"anthropic-beta": "beta-a-2026-01-01"},
            {" Anthropic-Beta ": [" beta-a-2026-01-01 "]},
        ) == {"anthropic-beta": "beta-a-2026-01-01"}

    @pytest.mark.parametrize(
        "name",
        [
            "Authorization",
            "x-api-key",
            "Host",
            "content-type",
            "Content-Length",
            "transfer-encoding",
            "connection",
            "anthropic-version",
            "User-Agent",
            "x-irid",
            "X-Stainless-Lang",
            "Api-Key",
            "x-goog-api-key",
            "X-Amz-Security-Token",
            "x-amz-date",
            "Proxy-Authorization",
            "Cookie",
        ],
    )
    def test_blocked_header_names_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match=name):
            resolve_forward_client_headers({name: ["anything"]})


def _zstd_decodable() -> bool:
    """Whether httpx2 (the OpenAI and Anthropic SDKs' client) can decode zstd."""
    return sys.version_info >= (3, 14) or (
        importlib.util.find_spec("backports") is not None
        and importlib.util.find_spec("backports.zstd") is not None
    )


class TestDecodableAcceptEncoding:
    """A forwarded `Accept-Encoding` lists only codings the host can decode."""

    def test_installed_decoders(self) -> None:
        codings = bridge_module._decodable_content_codings()
        assert {"gzip", "deflate", "br"} <= codings
        assert ("zstd" in codings) is _zstd_decodable()

    def test_inspect_does_not_require_brotli(self) -> None:
        """Installed brotli makes httpx and httpx2 advertise `br` on every request.

        Some proxies (e.g. LiteLLM proxy) cannot handle that, so brotli stays
        out of Inspect's runtime requirements.
        """
        runtime = [
            req
            for req in map(Requirement, importlib.metadata.requires("inspect_ai") or [])
            if req.marker is None or "extra" not in str(req.marker)
        ]
        assert [str(req) for req in runtime if req.name == "httpx"] == ["httpx"]
        assert not [req for req in runtime if req.name in ("brotli", "brotlicffi")]

    @pytest.mark.parametrize("sandbox", [False, True], ids=["in-process", "sandbox"])
    def test_missing_httpx_decoder_table_drops_accept_encoding(
        self, monkeypatch: pytest.MonkeyPatch, sandbox: bool
    ) -> None:
        """A moved private httpx table must not fail every bridged request."""
        monkeypatch.setitem(sys.modules, "httpx._decoders", None)
        bridge_module._decodable_content_codings.cache_clear()
        try:
            headers = {"Accept-Encoding": "gzip, br", "x-custom": "1"}
            result = (
                _sandbox_filter(headers, {"x-custom": ["1"]})
                if sandbox
                else filter_bridge_headers(headers)
            )
            assert result == {"x-custom": "1"}
        finally:
            bridge_module._decodable_content_codings.cache_clear()

    @pytest.mark.parametrize("sandbox", [False, True], ids=["in-process", "sandbox"])
    def test_undecodable_codings_dropped(
        self, monkeypatch: pytest.MonkeyPatch, sandbox: bool
    ) -> None:
        monkeypatch.setattr(
            bridge_module,
            "_decodable_content_codings",
            lambda: frozenset({"identity", "gzip", "deflate", "br"}),
        )
        headers = {"Accept-Encoding": "gzip, deflate, br, zstd, *;q=0.1"}
        result = (
            _sandbox_filter(headers, None)
            if sandbox
            else filter_bridge_headers(headers)
        )
        assert result == {"Accept-Encoding": "gzip, deflate, br"}

        only_zstd = {"Accept-Encoding": "zstd", "x-custom-header": "value"}
        result = (
            _sandbox_filter(only_zstd, None)
            if sandbox
            else filter_bridge_headers(only_zstd)
        )
        assert result == (None if sandbox else {"x-custom-header": "value"})

    @pytest.mark.anyio
    async def test_zstd_advertising_client_gets_a_decoded_response(self) -> None:
        """A Bun-based client (e.g. Claude Code) advertises zstd alongside br."""
        provider_requests: list[httpx2.Request] = []
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "decoded"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }

        def handler(request: httpx2.Request) -> httpx2.Response:
            provider_requests.append(request)
            body = json.dumps(message).encode()
            # a provider prefers zstd when the client offers it
            if "zstd" in request.headers["accept-encoding"]:
                content, encoding = zstandard.ZstdCompressor().compress(body), "zstd"
            else:
                content, encoding = brotli.compress(body), "br"
            return httpx2.Response(
                200,
                content=content,
                headers={
                    "content-encoding": encoding,
                    "content-type": "application/json",
                },
            )

        model = get_model(
            "anthropic/claude-sonnet-4-5",
            api_key="host-key",
            memoize=False,
            streaming=False,
            config=GenerateConfig(max_tokens=64),
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
        try:
            response: Any = await generate_anthropic(
                cast(WebSearchProviders, None),
                cast(CodeExecutionProviders, None),
                _route_bridge(model),
            )(
                {
                    "model": "agent-model",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                {"accept-encoding": "gzip, deflate, br, zstd"},
            )
        finally:
            await model.api.aclose()

        assert response["content"][0]["text"] == "decoded"
        [request] = provider_requests
        assert request.headers["accept-encoding"] == (
            "gzip, deflate, br, zstd" if _zstd_decodable() else "gzip, deflate, br"
        )


class TestSandboxAnthropicRequest:
    """Client headers through the sandbox service to the Anthropic provider."""

    @pytest.mark.anyio
    async def test_allowed_beta_reaches_provider_and_brotli_response_decodes(
        self,
    ) -> None:
        bridge_module._logged_client_header_drops.clear()
        provider_requests: list[httpx2.Request] = []
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "decoded"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }

        def handler(request: httpx2.Request) -> httpx2.Response:
            provider_requests.append(request)
            return httpx2.Response(
                200,
                content=brotli.compress(json.dumps(message).encode()),
                headers={"content-encoding": "br", "content-type": "application/json"},
            )

        model = get_model(
            "anthropic/claude-sonnet-4-5",
            api_key="test-key",
            memoize=False,
            streaming=False,
            config=GenerateConfig(max_tokens=64),
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
        bridge = SandboxAgentBridge(
            state=AgentState(messages=[]),
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"agent-model": model},
            forward_client_headers={"anthropic-beta": ["allowed-beta-2026-01-01"]},
        )
        generate = generate_anthropic(
            cast(WebSearchProviders, None), cast(CodeExecutionProviders, None), bridge
        )

        try:
            response: Any = await generate(
                {
                    "model": "agent-model",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                {
                    "anthropic-beta": "allowed-beta-2026-01-01,unlisted-beta-2026-01-01",
                    "accept-encoding": "br",
                    "authorization": "Bearer sandbox-token",
                },
            )
        finally:
            await model.api.aclose()

        assert response["content"][0]["text"] == "decoded"
        [request] = provider_requests
        assert request.headers["anthropic-beta"] == "allowed-beta-2026-01-01"
        assert request.headers["accept-encoding"] == "br"
        assert request.headers.get_list("authorization") == ["Bearer test-key"]
        assert "x-api-key" not in request.headers
        assert any("unlisted-beta-2026-01-01" in m for m in _logged_drops())

    @pytest.mark.anyio
    async def test_without_brotli_br_is_not_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without brotli, httpx and httpx2 have no `br` decoder and drop it.

        A provider that got `br` would answer Brotli-encoded, and httpx2 would
        pass that body on undecoded.
        """
        for decoders in (HTTPX_DECODERS, HTTPX2_DECODERS):
            monkeypatch.delitem(decoders, "br")
        bridge_module._decodable_content_codings.cache_clear()
        provider_requests: list[httpx2.Request] = []
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "decoded"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }

        def handler(request: httpx2.Request) -> httpx2.Response:
            provider_requests.append(request)
            body = json.dumps(message).encode()
            if "br" in request.headers["accept-encoding"]:
                content, encoding = brotli.compress(body), "br"
            else:
                content, encoding = gzip.compress(body), "gzip"
            return httpx2.Response(
                200,
                content=content,
                headers={
                    "content-encoding": encoding,
                    "content-type": "application/json",
                },
            )

        model = get_model(
            "anthropic/claude-sonnet-4-5",
            api_key="test-key",
            memoize=False,
            streaming=False,
            config=GenerateConfig(max_tokens=64),
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
        try:
            response: Any = await generate_anthropic(
                cast(WebSearchProviders, None),
                cast(CodeExecutionProviders, None),
                _route_bridge(model),
            )(
                {
                    "model": "agent-model",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                {"accept-encoding": "gzip, br"},
            )
        finally:
            await model.api.aclose()
            bridge_module._decodable_content_codings.cache_clear()

        assert response["content"][0]["text"] == "decoded"
        [request] = provider_requests
        assert request.headers["accept-encoding"] == "gzip"


class TestMergeExtraHeaders:
    """Forwarded client headers merge with model and eval `extra_headers`."""

    def test_model_headers_win_per_name(self) -> None:
        assert merge_extra_headers(
            {"X-Feature": "client", "Accept-Encoding": "br"},
            {"x-feature": "model", "x-model": "m"},
        ) == {"Accept-Encoding": "br", "x-feature": "model", "x-model": "m"}

    def test_anthropic_betas_combined(self) -> None:
        assert merge_extra_headers(
            {"Anthropic-Beta": "client-beta, shared-beta"},
            {"anthropic-beta": "shared-beta,model-beta"},
        ) == {"anthropic-beta": "client-beta,shared-beta,model-beta"}

    def test_either_side_empty(self) -> None:
        assert merge_extra_headers(None, None) is None
        assert merge_extra_headers({}, {"x-model": "m"}) == {"x-model": "m"}
        assert merge_extra_headers({"x-client": "c"}, None) == {"x-client": "c"}

    @pytest.mark.anyio
    async def test_forwarded_headers_kept_with_model_and_eval_extra_headers(
        self,
    ) -> None:
        from inspect_ai.model._generate_config import (
            active_generate_config_context_var,
        )
        from inspect_ai.model._model import active_model_context_var

        provider_requests: list[httpx2.Request] = []
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }

        def handler(request: httpx2.Request) -> httpx2.Response:
            provider_requests.append(request)
            return httpx2.Response(200, json=message)

        model = get_model(
            "anthropic/claude-sonnet-4-5",
            api_key="test-key",
            memoize=False,
            streaming=False,
            config=GenerateConfig(
                max_tokens=64,
                extra_headers={"anthropic-beta": "model-beta", "x-feature": "model"},
            ),
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )
        bridge = SandboxAgentBridge(
            state=AgentState(messages=[]),
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"agent-model": model},
            forward_client_headers={
                "anthropic-beta": ["client-beta"],
                "x-feature": ["client"],
            },
        )
        generate = generate_anthropic(
            cast(WebSearchProviders, None), cast(CodeExecutionProviders, None), bridge
        )
        model_token = active_model_context_var.set(model)
        config_token = active_generate_config_context_var.set(
            GenerateConfig(extra_headers={"x-eval": "eval"})
        )
        try:
            await generate(
                {
                    "model": "agent-model",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                {
                    "anthropic-beta": "client-beta",
                    "x-feature": "client",
                    "accept-encoding": "br",
                },
            )
        finally:
            active_generate_config_context_var.reset(config_token)
            active_model_context_var.reset(model_token)
            await model.api.aclose()

        [request] = provider_requests
        assert set(request.headers["anthropic-beta"].split(",")) == {
            "client-beta",
            "model-beta",
        }
        assert request.headers["x-feature"] == "model"
        assert request.headers["x-eval"] == "eval"
        assert request.headers["accept-encoding"] == "br"


# Headers a sandboxed client sends: credentials no `forward_client_headers` can
# list (host keys for OpenAI and Azure OpenAI, Anthropic and Foundry, Google,
# and an AWS session token for a SigV4-signed request), tenant and custom
# headers the eval did not list, and the two headers that do pass.
_CLIENT_CREDENTIALS = {
    "Authorization": "Bearer sandbox-token",
    "x-api-key": "sandbox-key",
    "Api-Key": "sandbox-key",
    "x-goog-api-key": "sandbox-key",
    "X-Amz-Security-Token": "sandbox-token",
    "OpenAI-Organization": "org-from-sandbox",
    "OpenAI-Project": "proj-from-sandbox",
    "X-Client-Header": "client-header-value",
    "Accept-Encoding": "br",
    "x-feature": "on",
}

_SANDBOX_CREDENTIAL_NAMES = {
    name.lower()
    for name in _CLIENT_CREDENTIALS
    if name not in ("x-feature", "Accept-Encoding")
}


def _route_bridge(model: Any) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"agent-model": model},
        forward_client_headers={"x-feature": ["on"]},
    )


def _capturing_client(
    requests: list[httpx2.Request], body: dict[str, Any]
) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=body)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


class TestSandboxRoutesKeepHostCredentials:
    """A sandboxed client's credential and unlisted headers never reach the SDK."""

    def _assert_host_credentials(
        self, request: httpx2.Request, host: dict[str, str]
    ) -> None:
        assert request.headers["x-feature"] == "on"
        assert request.headers["accept-encoding"] == "br"
        for name, value in host.items():
            assert request.headers.get_list(name) == [value]
        for name in _SANDBOX_CREDENTIAL_NAMES - set(host):
            assert name not in request.headers

    @pytest.mark.anyio
    async def test_completions_route_to_azure_openai(self) -> None:
        requests: list[httpx2.Request] = []
        model = get_model(
            "openai/azure/gpt-4o",
            api_key="host-key",
            base_url="https://example.openai.azure.com",
            memoize=False,
            responses_api=False,
            streaming=False,
            http_client=_capturing_client(
                requests,
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            ),
        )
        try:
            await generate_completions(_route_bridge(model))(
                {
                    "model": "agent-model",
                    "messages": [{"role": "user", "content": "hi"}],
                },
                _CLIENT_CREDENTIALS,
            )
        finally:
            await model.api.aclose()

        [request] = requests
        self._assert_host_credentials(request, {"api-key": "host-key"})

    @pytest.mark.anyio
    async def test_responses_route_to_azure_openai(self) -> None:
        requests: list[httpx2.Request] = []
        model = get_model(
            "openai/azure/gpt-4o",
            api_key="host-key",
            base_url="https://example.openai.azure.com",
            memoize=False,
            responses_api=True,
            streaming=False,
            http_client=_capturing_client(
                requests,
                {
                    "id": "resp_1",
                    "object": "response",
                    "created_at": 0,
                    "model": "gpt-4o",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "ok",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                },
            ),
        )
        try:
            await generate_responses(
                cast(WebSearchProviders, None),
                cast(CodeExecutionProviders, None),
                _route_bridge(model),
            )({"model": "agent-model", "input": "hi"}, _CLIENT_CREDENTIALS)
        finally:
            await model.api.aclose()

        [request] = [r for r in requests if r.url.path.endswith("/responses")]
        self._assert_host_credentials(request, {"api-key": "host-key"})

    @pytest.mark.anyio
    async def test_anthropic_route_to_anthropic(self) -> None:
        requests: list[httpx2.Request] = []
        model = get_model(
            "anthropic/claude-sonnet-4-5",
            api_key="host-key",
            memoize=False,
            streaming=False,
            config=GenerateConfig(max_tokens=64),
            http_client=_capturing_client(
                requests,
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            ),
        )
        try:
            await generate_anthropic(
                cast(WebSearchProviders, None),
                cast(CodeExecutionProviders, None),
                _route_bridge(model),
            )(
                {
                    "model": "agent-model",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                _CLIENT_CREDENTIALS,
            )
        finally:
            await model.api.aclose()

        [request] = requests
        self._assert_host_credentials(request, {"authorization": "Bearer host-key"})
