"""Tests for bridge header extraction and filtering."""

import importlib
import json
from typing import Any, cast

import httpx
import httpx2
import pytest

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
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

# brotli ships no type stubs; binding it via importlib keeps mypy clean without a
# suppression, and still fails loudly if httpx[brotli] stops pulling it in. PyPy
# gets brotlicffi instead, as httpx does.
try:
    brotli = importlib.import_module("brotli")
except ImportError:
    brotli = importlib.import_module("brotlicffi")


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
        bridge_module._logged_unlisted_client_headers.clear()

    def test_default_forwards_only_accept_encoding(self) -> None:
        headers = {
            "anthropic-beta": "context-1m-2025-08-07",
            "Accept-Encoding": "gzip, br",
            "x-custom-header": "value",
        }
        assert _sandbox_filter(headers, None) == {"Accept-Encoding": "gzip, br"}
        assert bridge_module._logged_unlisted_client_headers == {
            "anthropic-beta",
            "x-custom-header",
        }

    def test_unlisted_and_blocked_headers_not_warned(self) -> None:
        headers = {
            "x-stainless-os": "Linux",
            "authorization": "Bearer secret",
            "x-custom-header": "value",
        }
        assert _sandbox_filter(headers, None) is None
        _sandbox_filter(headers, None)
        # unlisted names are logged once each at info level; blocked ones never
        assert bridge_module._logged_unlisted_client_headers == {"x-custom-header"}
        assert inspect_logger._warned == []

    def test_tenant_headers_dropped_unless_listed(self) -> None:
        """Sandbox code must not choose another org or project on the host key."""
        headers = {
            "OpenAI-Organization": "org-attacker-controlled",
            "OpenAI-Project": "proj-attacker-controlled",
            "x-goog-user-project": "attacker-controlled-project",
            "Accept-Encoding": "gzip",
        }
        assert _sandbox_filter(headers, None) == {"Accept-Encoding": "gzip"}

    def test_listed_values_forwarded_and_others_dropped_with_warning(self) -> None:
        """Only listed tokens survive; whitespace around them is tolerated."""
        headers = {"Anthropic-Beta": "beta-a-2026-01-01, beta-b-2026-01-01,beta-c"}
        result = _sandbox_filter(
            headers, {"anthropic-beta": ["beta-a-2026-01-01", "beta-c"]}
        )
        assert result == {"Anthropic-Beta": "beta-a-2026-01-01,beta-c"}
        assert inspect_logger._warned == [
            "Agent bridge dropped 'beta-b-2026-01-01' from the sandboxed agent's "
            "'anthropic-beta' header. To forward it, add it to "
            "sandbox_agent_bridge(forward_client_headers=...)."
        ]

    def test_header_dropped_when_no_values_remain(self) -> None:
        result = _sandbox_filter(
            {"anthropic-beta": "beta-d-2026-01-01", "Accept-Encoding": "br"},
            {"anthropic-beta": ["beta-a-2026-01-01"]},
        )
        assert result == {"Accept-Encoding": "br"}
        assert any("beta-d-2026-01-01" in m for m in inspect_logger._warned)

    def test_header_names_case_insensitive(self) -> None:
        result = _sandbox_filter(
            {"X-MY-HEADER": "on"}, {"x-My-Header": ["on"], "X-Other": ["1"]}
        )
        assert result == {"X-MY-HEADER": "on"}

    def test_listing_accept_encoding_narrows_it(self) -> None:
        result = _sandbox_filter(
            {"accept-encoding": "gzip, br, zstd"}, {"Accept-Encoding": ["br"]}
        )
        assert result == {"accept-encoding": "br"}

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


class TestSandboxAnthropicRequest:
    """Client headers through the sandbox service to the Anthropic provider."""

    @pytest.mark.anyio
    async def test_allowed_beta_reaches_provider_and_brotli_response_decodes(
        self,
    ) -> None:
        inspect_logger._warned.clear()
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
        assert request.headers["x-api-key"] == "test-key"
        assert "authorization" not in request.headers
        assert any("unlisted-beta-2026-01-01" in m for m in inspect_logger._warned)


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
        self._assert_host_credentials(request, {"x-api-key": "host-key"})
