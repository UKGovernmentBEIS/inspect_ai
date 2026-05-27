"""Tests for bridge header extraction and filtering."""

from inspect_ai.agent._bridge.bridge import (
    _BLOCKED_BRIDGE_HEADER_PREFIXES,
    _BLOCKED_BRIDGE_HEADERS,
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
