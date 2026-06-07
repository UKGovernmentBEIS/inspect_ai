"""Tests for ChatCompletionChoice.stop_details and the defensive collector.

Phase 1 covers the shared types/guard plus Anthropic as the reference provider.
"""

from logging import getLogger
from typing import Any, cast

import pytest

from inspect_ai.model import StopCategory, StopDetails
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    collect_stop_details,
)

logger = getLogger(__name__)


# ---- collect_stop_details (shared guard) ----------------------------------


def test_collect_stop_details_syncs_scalar_category_from_list() -> None:
    details = collect_stop_details(
        "test",
        logger,
        lambda: StopDetails(categories=[StopCategory(category="cyber", level="HIGH")]),
    )
    assert details is not None
    # scalar `category` is derived from the canonical list
    assert details.category == "cyber"


def test_collect_stop_details_drops_empty() -> None:
    # no categories and no explanation -> nothing to report
    assert collect_stop_details("test", logger, lambda: StopDetails()) is None
    assert collect_stop_details("test", logger, lambda: None) is None


def test_collect_stop_details_keeps_explanation_only() -> None:
    details = collect_stop_details(
        "test", logger, lambda: StopDetails(explanation="blocked")
    )
    assert details is not None
    assert details.explanation == "blocked"
    assert details.categories == []
    assert details.category is None


def test_collect_stop_details_defensive_on_unexpected_shape(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.model._model_output.warn_once",
        lambda _logger, message: warnings.append(message),
    )

    def boom() -> StopDetails | None:
        raise AttributeError("surprise: missing field")

    # an unexpected shape warns and degrades to None rather than raising
    result = collect_stop_details("test", logger, boom)
    assert result is None
    assert len(warnings) == 1
    assert "test" in warnings[0]


# ---- Anthropic reference extraction ---------------------------------------


def test_anthropic_message_stop_details_mirrors_category() -> None:
    from types import SimpleNamespace

    from anthropic.types import Message, RefusalStopDetails

    from inspect_ai.model._providers.anthropic import message_stop_details

    msg = cast(
        Message,
        SimpleNamespace(
            stop_details=RefusalStopDetails(
                type="refusal", category="cyber", explanation="can't help with that"
            )
        ),
    )
    details = collect_stop_details(
        "anthropic", logger, lambda: message_stop_details(msg)
    )
    assert details is not None
    assert details.type == "refusal"
    assert details.category == "cyber"
    assert details.explanation == "can't help with that"
    # single category mirrored into the canonical list so callers can iterate uniformly
    assert details.categories == [StopCategory(category="cyber")]


def test_anthropic_message_stop_details_none_when_absent() -> None:
    from types import SimpleNamespace

    from anthropic.types import Message

    from inspect_ai.model._providers.anthropic import message_stop_details

    msg = cast(Message, SimpleNamespace(stop_details=None))
    assert message_stop_details(msg) is None


# ---- serialization / backward compatibility -------------------------------


def test_chat_completion_choice_stop_details_roundtrip() -> None:
    choice = ChatCompletionChoice(
        message=ModelOutput.from_content("m", "hi").choices[0].message,
        stop_reason="content_filter",
        stop_details=StopDetails(
            type="refusal",
            category="bio",
            explanation="nope",
            categories=[StopCategory(category="bio", level="HIGH")],
        ),
    )
    restored = ChatCompletionChoice.model_validate_json(choice.model_dump_json())
    assert restored.stop_details is not None
    assert restored.stop_details.category == "bio"
    assert restored.stop_details.categories == [
        StopCategory(category="bio", level="HIGH")
    ]


def test_chat_completion_choice_backcompat_without_stop_details() -> None:
    # a legacy choice serialized before stop_details existed deserializes to None
    legacy = {
        "message": {"role": "assistant", "content": "hello", "source": "generate"},
        "stop_reason": "stop",
    }
    choice = ChatCompletionChoice.model_validate(legacy)
    assert choice.stop_details is None


def test_from_content_carries_stop_details() -> None:
    output = ModelOutput.from_content(
        "m",
        "refused",
        stop_reason="content_filter",
        stop_details=StopDetails(type="refusal", category="cyber"),
    )
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.category == "cyber"


# ---- synthesized explanation (central guard behavior) ---------------------


def test_collect_stop_details_synthesizes_explanation_from_categories() -> None:
    details = collect_stop_details(
        "test",
        logger,
        lambda: StopDetails(
            categories=[
                StopCategory(category="VIOLENCE", level="HIGH"),
                StopCategory(category="HATE", level="MEDIUM"),
            ]
        ),
    )
    assert details is not None
    # provider gave no text -> a readable summary is synthesized
    assert details.explanation == "Content filtered: VIOLENCE (HIGH), HATE (MEDIUM)"


def test_collect_stop_details_keeps_provider_explanation() -> None:
    details = collect_stop_details(
        "test",
        logger,
        lambda: StopDetails(
            explanation="provider text",
            categories=[StopCategory(category="cyber")],
        ),
    )
    assert details is not None
    assert details.explanation == "provider text"


# ---- Google extraction ----------------------------------------------------


def test_google_stop_details_from_safety_ratings() -> None:
    from types import SimpleNamespace

    from google.genai.types import (
        Candidate,
        FinishReason,
        HarmCategory,
        HarmProbability,
    )

    from inspect_ai.model._providers.google import google_stop_details

    rating = SimpleNamespace(
        blocked=True,
        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        probability=HarmProbability.HIGH,
    )
    candidate = cast(
        Candidate,
        SimpleNamespace(
            finish_reason=FinishReason.SAFETY,
            safety_ratings=[rating],
            finish_message=None,
        ),
    )
    details = collect_stop_details(
        "google", logger, lambda: google_stop_details(candidate)
    )
    assert details is not None
    assert details.type == "SAFETY"
    assert details.categories == [
        StopCategory(category="HARM_CATEGORY_DANGEROUS_CONTENT", level="HIGH")
    ]
    assert details.category == "HARM_CATEGORY_DANGEROUS_CONTENT"
    # no native text -> synthesized
    assert details.explanation is not None


def test_google_stop_details_none_for_normal_stop() -> None:
    from types import SimpleNamespace

    from google.genai.types import Candidate, FinishReason

    from inspect_ai.model._providers.google import google_stop_details

    candidate = cast(
        Candidate,
        SimpleNamespace(
            finish_reason=FinishReason.STOP, safety_ratings=None, finish_message=None
        ),
    )
    assert google_stop_details(candidate) is None


# ---- OpenAI family extraction ---------------------------------------------


def test_openai_stop_details_from_refusal_text() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._openai import openai_stop_details

    choice = SimpleNamespace(
        message=SimpleNamespace(refusal="I can't help with that"),
        finish_reason="stop",
        content_filter_results=None,
        model_extra=None,
    )
    details = openai_stop_details(choice)
    assert details is not None
    assert details.explanation == "I can't help with that"
    assert details.type == "refusal"
    assert details.categories == []


def test_openai_stop_details_from_azure_content_filter_results() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._openai import openai_stop_details

    choice = SimpleNamespace(
        message=SimpleNamespace(refusal=None),
        finish_reason="content_filter",
        content_filter_results=None,
        model_extra={
            "content_filter_results": {
                "hate": {"filtered": True, "severity": "high"},
                "violence": {"filtered": False, "severity": "safe"},
            }
        },
    )
    details = collect_stop_details(
        "openai", logger, lambda: openai_stop_details(choice)
    )
    assert details is not None
    assert details.type == "content_filter"
    assert details.categories == [StopCategory(category="hate", level="high")]
    assert details.category == "hate"


def test_openai_stop_details_none_for_normal_stop() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._openai import openai_stop_details

    choice = SimpleNamespace(
        message=SimpleNamespace(refusal=None),
        finish_reason="stop",
        content_filter_results=None,
        model_extra=None,
    )
    assert openai_stop_details(choice) is None


# ---- OpenAI Responses extraction ------------------------------------------


def test_responses_stop_details_from_refusal() -> None:
    from types import SimpleNamespace

    from openai.types.responses import Response as OpenAIResponse
    from openai.types.responses import ResponseOutputMessage, ResponseOutputRefusal

    from inspect_ai.model._openai_responses import responses_stop_details

    message = ResponseOutputMessage(
        id="m1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputRefusal(type="refusal", refusal="I won't do that")],
    )
    response = cast(
        OpenAIResponse, SimpleNamespace(output=[message], incomplete_details=None)
    )
    details = responses_stop_details(response)
    assert details is not None
    assert details.explanation == "I won't do that"
    assert details.type == "refusal"


def test_responses_stop_details_content_filter_signal() -> None:
    from types import SimpleNamespace

    from openai.types.responses import Response as OpenAIResponse

    from inspect_ai.model._openai_responses import responses_stop_details

    response = cast(
        OpenAIResponse,
        SimpleNamespace(
            output=[], incomplete_details=SimpleNamespace(reason="content_filter")
        ),
    )
    details = responses_stop_details(response)
    assert details is not None
    assert details.type == "content_filter"


# ---- Bedrock extraction ---------------------------------------------------


def test_bedrock_stop_details_from_guardrail_trace() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._providers.bedrock import (
        ConverseResponse,
        bedrock_stop_details,
    )

    trace = {
        "guardrail": {
            "outputAssessments": {
                "gr-1": [
                    {
                        "contentPolicy": {
                            "filters": [
                                {
                                    "type": "VIOLENCE",
                                    "confidence": "HIGH",
                                    "action": "BLOCKED",
                                }
                            ]
                        },
                        "topicPolicy": {
                            "topics": [{"name": "Medical Advice", "action": "BLOCKED"}]
                        },
                    }
                ]
            }
        }
    }
    response = cast(
        ConverseResponse,
        SimpleNamespace(stopReason="guardrail_intervened", trace=trace),
    )
    details = collect_stop_details(
        "bedrock", logger, lambda: bedrock_stop_details(response)
    )
    assert details is not None
    assert details.type == "guardrail_intervened"
    assert details.categories == [
        StopCategory(category="VIOLENCE", level="HIGH"),
        StopCategory(category="Medical Advice"),
    ]
    assert details.category == "VIOLENCE"
    assert details.explanation is not None  # synthesized


def test_bedrock_stop_details_none_without_trace() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._providers.bedrock import (
        ConverseResponse,
        bedrock_stop_details,
    )

    response = cast(
        ConverseResponse,
        SimpleNamespace(stopReason="guardrail_intervened", trace=None),
    )
    # no trace -> no per-category detail to report
    assert bedrock_stop_details(response) is None


def test_bedrock_stop_details_none_for_normal_stop() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._providers.bedrock import (
        ConverseResponse,
        bedrock_stop_details,
    )

    response = cast(
        ConverseResponse, SimpleNamespace(stopReason="end_turn", trace=None)
    )
    assert bedrock_stop_details(response) is None


# ---- Grok extraction ------------------------------------------------------


def test_grok_permission_denied_sets_stop_details() -> None:
    from types import SimpleNamespace

    from inspect_ai.model._providers.grok import GrokAPI

    fake_self = cast(GrokAPI, SimpleNamespace(model_name="grok/grok-4"))
    ex = SimpleNamespace(details=lambda: "Request blocked by safety_check policy")
    output = GrokAPI._handle_grpc_permission_denied(fake_self, cast(Any, ex))
    assert output is not None
    assert output.choices[0].stop_reason == "content_filter"
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.type == "refusal"
    assert "safety_check" in (output.choices[0].stop_details.explanation or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
