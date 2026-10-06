"""Tests for bridge header extraction and filtering."""

import importlib
import json
from typing import Any, cast

import httpx
import httpx2
import pytest

from inspect_ai._util import logger as inspect_logger
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.bridge import (
    _ALLOWED_BRIDGE_HEADERS,
    filter_bridge_headers,
)
from inspect_ai.agent._bridge.sandbox.service import generate_anthropic
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

    def test_custom_headers_stripped(self):
        """A header with no demonstrated fidelity need is dropped.

        The filter is an explicit allowlist: arbitrary client headers are
        not forwarded just because they are unrecognized.
        """
        headers = {
            "x-custom-header": "value1",
            "x-my-app-id": "12345",
            "x-request-context": "test",
        }
        assert filter_bridge_headers(headers) is None

    def test_accept_encoding_passes_through(self):
        """The bridged client's supported response encodings are preserved."""
        headers = {"Accept-Encoding": "gzip, deflate, br, zstd"}
        assert filter_bridge_headers(headers) == headers

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

    def test_sensitive_headers_removed(self):
        """Sensitive/internal headers not on the allowlist are dropped."""
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
        assert result is None

    def test_filtering_case_insensitive(self):
        """Test that allowlist matching is case-insensitive."""
        headers = {
            "Authorization": "Bearer secret",
            "X-API-KEY": "sk-1234",
            "Accept-Encoding": "gzip",
        }
        result = filter_bridge_headers(headers)
        assert result == {"Accept-Encoding": "gzip"}

    def test_stainless_headers_stripped(self):
        """Test that x-stainless-* SDK-internal headers are dropped."""
        headers = {
            "x-stainless-lang": "python",
            "x-stainless-package-version": "1.0.0",
            "x-stainless-os": "Darwin",
            "x-stainless-arch": "arm64",
            "x-stainless-retry-count": "0",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_anthropic_beta_forwarded_without_beta_allowlist(self):
        """Without a beta allowlist, the client's anthropic-beta is forwarded as sent.

        This is the in-process `agent_bridge()` path, where the agent runs
        in the eval's own process.
        """
        headers = {
            "anthropic-beta": "code-execution-2025-08-25",
            "x-custom-header": "value",
        }
        result = filter_bridge_headers(headers)
        assert result == {"anthropic-beta": "code-execution-2025-08-25"}

    def test_anthropic_beta_restricted_to_allowed_betas(self):
        """Only allowed betas survive; whitespace around values is tolerated."""
        inspect_logger._warned.clear()
        headers = {"Anthropic-Beta": "beta-a-2026-01-01, beta-b-2026-01-01,beta-c"}
        result = filter_bridge_headers(
            headers,
            allowed_anthropic_betas=frozenset({"beta-a-2026-01-01", "beta-c"}),
        )
        assert result == {"Anthropic-Beta": "beta-a-2026-01-01,beta-c"}
        assert [m for m in inspect_logger._warned if "beta-" in m] == [
            "Agent bridge dropped Anthropic beta 'beta-b-2026-01-01' requested by "
            "the sandboxed agent. To forward it, add it to "
            "sandbox_agent_bridge(allowed_anthropic_betas=...)."
        ]

    def test_anthropic_beta_dropped_when_no_betas_allowed(self):
        """With an empty allowlist the header is removed; other headers remain."""
        inspect_logger._warned.clear()
        headers = {
            "anthropic-beta": "context-1m-2025-08-07",
            "Accept-Encoding": "gzip, br",
        }
        result = filter_bridge_headers(headers, allowed_anthropic_betas=frozenset())
        assert result == {"Accept-Encoding": "gzip, br"}
        assert any("context-1m-2025-08-07" in m for m in inspect_logger._warned)

    def test_anthropic_beta_only_header_dropped_returns_none(self):
        """Dropping the only forwarded header leaves no headers to forward."""
        result = filter_bridge_headers(
            {"anthropic-beta": "beta-d-2026-01-01"},
            allowed_anthropic_betas=frozenset(),
        )
        assert result is None

    def test_anthropic_version_stripped(self):
        """Test that anthropic-version header is dropped.

        This is SDK-managed and should not be overridden by clients.
        """
        headers = {
            "anthropic-version": "2023-06-01",
            "x-custom-header": "keep-me",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_all_headers_unlisted_returns_none(self):
        """Test that headers with no allowlist match return None."""
        headers = {
            "authorization": "Bearer secret",
            "x-api-key": "sk-1234",
            "content-type": "application/json",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_transfer_encoding_stripped(self):
        """Test that transfer-encoding is dropped."""
        headers = {
            "transfer-encoding": "chunked",
            "connection": "keep-alive",
            "x-custom": "value",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_user_agent_stripped(self):
        """Test that User-Agent is dropped.

        Since Inspect transforms the request, the original client's
        User-Agent would be misleading. The SDK sets its own User-Agent
        which accurately reflects what's making the HTTP call.
        """
        headers = {
            "User-Agent": "pydantic-ai/1.44.0",
            "x-custom": "value",
        }
        result = filter_bridge_headers(headers)
        assert result is None

    def test_openai_tenant_headers_stripped(self):
        """OpenAI-Organization/OpenAI-Project must never reach the provider.

        These headers select which org/project the host's API key bills
        and scopes data to. A bridge client is untrusted sandbox code, so
        letting it set these would let it re-route billing or data
        visibility to any org/project the host key can access.
        """
        headers = {
            "OpenAI-Organization": "org-attacker-controlled",
            "OpenAI-Project": "proj-attacker-controlled",
            "Accept-Encoding": "gzip",
        }
        result = filter_bridge_headers(headers)
        assert result == {"Accept-Encoding": "gzip"}

    def test_google_quota_project_header_stripped(self):
        """Google's tenant/billing equivalent is also never forwarded."""
        headers = {
            "x-goog-user-project": "attacker-controlled-project",
            "anthropic-beta": "computer-use-2024-10-22",
        }
        result = filter_bridge_headers(headers)
        assert result == {"anthropic-beta": "computer-use-2024-10-22"}

    def test_mixed_allowed_and_unlisted(self):
        """Test mixed headers with some allowed and some dropped."""
        headers = {
            # Not on the allowlist
            "Authorization": "Bearer token",
            "x-stainless-os": "Linux",
            "Content-Type": "application/json",
            "x-my-trace-id": "abc123",
            "x-request-source": "agent",
            # Allowed
            "anthropic-beta": "computer-use-2024-10-22",
        }
        result = filter_bridge_headers(headers)
        assert result == {
            "anthropic-beta": "computer-use-2024-10-22",
        }


class TestAllowedHeadersConfiguration:
    """Test the allowed headers configuration."""

    def test_allowed_headers_are_lowercase(self):
        """Verify all allowed headers are lowercase for case-insensitive comparison."""
        for header in _ALLOWED_BRIDGE_HEADERS:
            assert header == header.lower(), f"Header '{header}' should be lowercase"

    def test_tenant_billing_headers_not_in_allowlist(self):
        """Verify tenant/billing-routing headers are never in the allowlist."""
        excluded = [
            "openai-organization",
            "openai-project",
            "x-goog-user-project",
        ]
        for header in excluded:
            assert header not in _ALLOWED_BRIDGE_HEADERS, (
                f"Tenant/billing header '{header}' must not be allowlisted"
            )

    def test_anthropic_beta_allowlisted(self):
        """Verify anthropic-beta is in the allowlist."""
        assert "anthropic-beta" in _ALLOWED_BRIDGE_HEADERS

    def test_accept_encoding_allowlisted(self):
        """Verify accept-encoding is in the allowlist."""
        assert "accept-encoding" in _ALLOWED_BRIDGE_HEADERS


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
            allowed_anthropic_betas=["allowed-beta-2026-01-01"],
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
