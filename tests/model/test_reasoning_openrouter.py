import json
from unittest.mock import patch

from inspect_ai._util.content import ContentReasoning
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._openrouter_reasoning import (
    sanitize_reasoning_details_for_replay,
)
from inspect_ai.model._providers.openrouter import (
    OPENROUTER_REASONING_DETAILS_SIGNATURE,
    OpenRouterAPI,
    openrouter_reasoning_details_to_reasoning,
    reasoning_to_openrouter_reasoning_details,
)

# =============================================================================
# Tests for openrouter_reasoning_details_to_reasoning()
# =============================================================================


class TestOpenrouterReasoningDetailsToReasoning:
    """Tests for converting OpenRouter reasoning_details to ContentReasoning."""

    def test_text_type(self):
        """reasoning.text type extracts text as reasoning."""
        details = [
            {
                "type": "reasoning.text",
                "text": "Let me think about this step by step...",
                "id": "r1",
                "format": "anthropic-claude-v1",
            }
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        assert result.reasoning == "Let me think about this step by step..."
        assert result.summary is None
        assert result.redacted is False
        assert result.signature is not None
        assert result.signature.startswith(OPENROUTER_REASONING_DETAILS_SIGNATURE)

    def test_summary_type_only(self):
        """reasoning.summary alone becomes the reasoning (fallback behavior)."""
        details = [
            {
                "type": "reasoning.summary",
                "summary": "The model analyzed the problem",
                "id": "s1",
                "format": "anthropic-claude-v1",
            }
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        # When only summary exists, it becomes the reasoning
        assert result.reasoning == "The model analyzed the problem"
        assert result.summary is None  # summary moved to reasoning
        assert result.redacted is False

    def test_text_and_summary_combined(self):
        """Both text and summary preserves both fields."""
        details = [
            {
                "type": "reasoning.summary",
                "summary": "High-level summary",
                "id": "s1",
                "format": "anthropic-claude-v1",
            },
            {
                "type": "reasoning.text",
                "text": "Detailed reasoning content",
                "id": "t1",
                "format": "anthropic-claude-v1",
            },
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        assert result.reasoning == "Detailed reasoning content"
        assert result.summary == "High-level summary"
        assert result.redacted is False

    def test_encrypted_type(self):
        """reasoning.encrypted sets redacted=True."""
        details = [
            {
                "type": "reasoning.encrypted",
                "data": "eyJlbmNyeXB0ZWQiOiJ0cnVlIn0=",
                "id": "e1",
                "format": "anthropic-claude-v1",
            }
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        assert result.reasoning == "eyJlbmNyeXB0ZWQiOiJ0cnVlIn0="
        assert result.redacted is True

    def test_text_and_encrypted_combined(self):
        """Both text and encrypted preserves text as summary."""
        details = [
            {
                "type": "reasoning.text",
                "format": "google-gemini-v1",
                "text": "Let me think about this step by step...",
                "id": "t1",
            },
            {
                "type": "reasoning.encrypted",
                "format": "google-gemini-v1",
                "data": "CiQBjz1rXxKfW2fJuqbBlfGrk8wxR",
                "id": "e1",
            },
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        assert result.reasoning == "CiQBjz1rXxKfW2fJuqbBlfGrk8wxR"
        assert result.summary == "Let me think about this step by step..."
        assert result.redacted is True

    def test_empty_list_logs_warning(self):
        """Empty reasoning_details list logs warning and returns raw JSON."""
        with patch("inspect_ai.model._openrouter_reasoning.logger") as mock_logger:
            details = []
            result = openrouter_reasoning_details_to_reasoning(details)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Reasoning content not provided" in call_args
            assert result.reasoning == "[]"

    def test_invalid_format_logs_warning(self):
        """Invalid/malformed data logs warning and returns raw JSON."""
        with patch("inspect_ai.model._openrouter_reasoning.logger") as mock_logger:
            details = [{"type": "unknown.type", "foo": "bar"}]
            result = openrouter_reasoning_details_to_reasoning(details)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Error parsing OpenRouter reasoning details" in call_args
            # Falls back to raw JSON
            assert result.signature is not None

    def test_signature_contains_original_json(self):
        """Signature preserves full original JSON for round-tripping."""
        details = [
            {
                "type": "reasoning.text",
                "text": "Some reasoning",
                "id": "r1",
                "format": "anthropic-claude-v1",
                "index": 0,
            }
        ]
        result = openrouter_reasoning_details_to_reasoning(details)

        # Extract JSON from signature
        assert result.signature is not None
        json_str = result.signature.replace(OPENROUTER_REASONING_DETAILS_SIGNATURE, "")
        recovered = json.loads(json_str)

        assert recovered == details


# =============================================================================
# Tests for reasoning_to_openrouter_reasoning_details()
# =============================================================================


class TestReasoningToOpenrouterReasoningDetails:
    """Tests for converting ContentReasoning back to OpenRouter format."""

    def test_valid_signature_returns_details(self):
        """ContentReasoning with OpenRouter signature returns reasoning_details."""
        original_details = [
            {
                "type": "reasoning.text",
                "text": "My reasoning",
                "id": "r1",
                "format": "anthropic-claude-v1",
            }
        ]
        signature = (
            f"{OPENROUTER_REASONING_DETAILS_SIGNATURE}{json.dumps(original_details)}"
        )
        content = ContentReasoning(
            reasoning="My reasoning",
            signature=signature,
        )

        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is not None
        assert "reasoning_details" in result
        assert result["reasoning_details"] == original_details

    def test_no_signature_returns_none(self):
        """ContentReasoning without signature returns None."""
        content = ContentReasoning(reasoning="Some reasoning")

        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is None

    def test_wrong_signature_returns_none(self):
        """ContentReasoning with non-OpenRouter signature returns None."""
        content = ContentReasoning(
            reasoning="Some reasoning",
            signature="some-other-signature-format",
        )

        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is None

    def test_empty_signature_returns_none(self):
        """ContentReasoning with empty signature returns None."""
        content = ContentReasoning(
            reasoning="Some reasoning",
            signature="",
        )

        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is None


# =============================================================================
# Round-trip tests
# =============================================================================


class TestRoundTrip:
    """Tests that reasoning_details survives round-trip conversion."""

    def test_text_round_trip(self):
        """Text type round-trips correctly."""
        original = [
            {
                "type": "reasoning.text",
                "text": "Step by step reasoning",
                "id": "r1",
                "format": "anthropic-claude-v1",
                "index": 0,
            }
        ]

        # Convert to ContentReasoning
        content = openrouter_reasoning_details_to_reasoning(original)

        # Convert back to reasoning_details
        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is not None
        assert result["reasoning_details"] == original

    def test_encrypted_round_trip(self):
        """Encrypted type round-trips correctly."""
        original = [
            {
                "type": "reasoning.encrypted",
                "data": "encrypted-base64-data",
                "id": "e1",
                "format": "anthropic-claude-v1",
            }
        ]

        content = openrouter_reasoning_details_to_reasoning(original)
        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is not None
        assert result["reasoning_details"] == original

    def test_complex_round_trip(self):
        """Complex multi-element reasoning_details round-trips correctly."""
        original = [
            {
                "type": "reasoning.summary",
                "summary": "Analyzed the problem",
                "id": "s1",
                "format": "anthropic-claude-v1",
                "index": 0,
            },
            {
                "type": "reasoning.text",
                "text": "First, let me consider...\nThen, I'll analyze...",
                "signature": None,
                "id": "t1",
                "format": "anthropic-claude-v1",
                "index": 1,
            },
        ]

        content = openrouter_reasoning_details_to_reasoning(original)
        result = reasoning_to_openrouter_reasoning_details(content)

        assert result is not None
        assert result["reasoning_details"] == original


# =============================================================================
# Tests for sanitize_reasoning_details_for_replay()
# =============================================================================


class TestSanitizeReasoningDetailsForReplay:
    """Tests for the reasoning-detail replay filter.

    Mirrors OpenRouter's own SDK: for signed formats (Gemini, Anthropic) an
    unsigned reasoning.text is dropped while the encrypted continuity blob and
    everything else is preserved.
    """

    def test_gemini_unsigned_text_dropped_encrypted_kept(self):
        details = [
            {"type": "reasoning.text", "text": "hi", "format": "google-gemini-v1"},
            {
                "type": "reasoning.encrypted",
                "data": "BLOB",
                "format": "google-gemini-v1",
                "id": "call_1",
            },
        ]
        result = sanitize_reasoning_details_for_replay(details)
        assert [d["type"] for d in result] == ["reasoning.encrypted"]
        assert result[0]["data"] == "BLOB"

    def test_gemini_signed_text_kept(self):
        details = [
            {
                "type": "reasoning.text",
                "text": "hi",
                "format": "google-gemini-v1",
                "signature": "sig",
            }
        ]
        assert sanitize_reasoning_details_for_replay(details) == details

    def test_anthropic_signed_text_kept(self):
        details = [
            {
                "type": "reasoning.text",
                "text": "hi",
                "format": "anthropic-claude-v1",
                "signature": "sig",
            }
        ]
        assert sanitize_reasoning_details_for_replay(details) == details

    def test_anthropic_unsigned_text_dropped(self):
        details = [
            {"type": "reasoning.text", "text": "hi", "format": "anthropic-claude-v1"}
        ]
        assert sanitize_reasoning_details_for_replay(details) == []

    def test_missing_format_defaults_to_anthropic_and_drops_unsigned(self):
        # No format => anthropic-claude-v1 (SDK default), which is a signed
        # format, so unsigned text is dropped.
        details = [{"type": "reasoning.text", "text": "hi"}]
        assert sanitize_reasoning_details_for_replay(details) == []

    def test_non_signed_format_text_kept(self):
        # e.g. OpenAI/xAI-style formats do not gate on signature.
        details = [
            {"type": "reasoning.text", "text": "hi", "format": "openai-responses-v1"}
        ]
        assert sanitize_reasoning_details_for_replay(details) == details

    def test_summary_and_encrypted_pass_through(self):
        details = [
            {"type": "reasoning.summary", "summary": "s", "format": "google-gemini-v1"},
            {"type": "reasoning.encrypted", "data": "B", "format": "google-gemini-v1"},
        ]
        assert sanitize_reasoning_details_for_replay(details) == details

    def test_entry_without_type_passes_through(self):
        # Only reasoning.text entries are ever filtered; anything else is kept.
        details = [{"foo": "bar"}, {"type": "reasoning.encrypted", "data": "B"}]
        assert sanitize_reasoning_details_for_replay(details) == details

    def test_mixed_array_filters_per_rule_and_preserves_order(self):
        details = [
            {
                "type": "reasoning.text",
                "text": "signed",
                "format": "google-gemini-v1",
                "signature": "sig",
            },
            {
                "type": "reasoning.text",
                "text": "unsigned",
                "format": "google-gemini-v1",
            },
            {
                "type": "reasoning.text",
                "text": "openai",
                "format": "openai-responses-v1",
            },
            {
                "type": "reasoning.summary",
                "summary": "sum",
                "format": "google-gemini-v1",
            },
            {"type": "reasoning.encrypted", "data": "B", "format": "google-gemini-v1"},
        ]
        result = sanitize_reasoning_details_for_replay(details)
        # the unsigned signed-format text (index 1) is the only entry dropped
        assert result == [details[0], details[2], details[3], details[4]]

    def test_unsigned_signed_format_text_only_yields_empty_list(self):
        details = [
            {"type": "reasoning.text", "text": "hi", "format": "google-gemini-v1"}
        ]
        assert sanitize_reasoning_details_for_replay(details) == []


# =============================================================================
# End-to-end: messages_to_openai replays reasoning structurally (no <think>)
# =============================================================================


class TestGeminiReplayIsStructural:
    """Regression for the Gemini `<think>`-tag fallback.

    Reasoning must be replayed as structural reasoning_details, never
    serialized into the assistant text channel (where a later turn could echo
    it back as output).
    """

    GEMINI_DETAILS = [
        {
            "type": "reasoning.text",
            "text": "let me think",
            "format": "google-gemini-v1",
        },
        {
            "type": "reasoning.encrypted",
            "data": "ENCRYPTED_BLOB",
            "format": "google-gemini-v1",
            "id": "call_1",
        },
    ]

    async def test_replay_emits_structural_details_without_think_tag(self):
        api = OpenRouterAPI(
            model_name="google/gemini-3.1-pro-preview", api_key="test-key"
        )
        reasoning = openrouter_reasoning_details_to_reasoning(self.GEMINI_DETAILS)
        message = ChatMessageAssistant(content=[reasoning], model="gemini")

        result = await api.messages_to_openai([message])

        assert len(result) == 1
        param = result[0]
        # structural details present, unsigned text filtered, encrypted kept
        assert "reasoning_details" in param
        details = param["reasoning_details"]
        assert [d["type"] for d in details] == ["reasoning.encrypted"]
        # nothing leaked into the text channel
        serialized = json.dumps(param)
        assert "<think" not in serialized
        assert "reasoning-details://" not in serialized

    async def test_replay_keeps_signed_text(self):
        api = OpenRouterAPI(
            model_name="google/gemini-3.1-pro-preview", api_key="test-key"
        )
        signed = [
            {
                "type": "reasoning.text",
                "text": "signed thought",
                "format": "google-gemini-v1",
                "signature": "abc",
            }
        ]
        reasoning = openrouter_reasoning_details_to_reasoning(signed)
        message = ChatMessageAssistant(content=[reasoning], model="gemini")

        result = await api.messages_to_openai([message])
        details = result[0]["reasoning_details"]
        assert [d["type"] for d in details] == ["reasoning.text"]
        assert "<think" not in json.dumps(result[0])
