"""Tests for bridge header extraction and filtering."""

import json

import brotli  # type: ignore[import-untyped]  # brotli ships no type stubs
import httpx

from inspect_ai.agent._bridge.bridge import (
    _ALLOWED_BRIDGE_HEADERS,
    filter_bridge_headers,
)


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

    def test_anthropic_beta_allowed(self):
        """Test that anthropic-beta header is forwarded.

        This header is used for legitimate feature flags like
        code-execution-2025-08-25, and dropping it would run Claude
        Code against a different feature surface than the same agent
        outside Inspect.
        """
        headers = {
            "anthropic-beta": "code-execution-2025-08-25",
            "x-custom-header": "value",
        }
        result = filter_bridge_headers(headers)
        assert result == {"anthropic-beta": "code-execution-2025-08-25"}

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
