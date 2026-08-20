import json
from logging import getLogger
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from inspect_ai._util.content import ContentReasoning

logger = getLogger(__name__)

OPENROUTER_REASONING_DETAILS_SIGNATURE = "reasoning-details://"

# Reasoning-detail formats whose readable `reasoning.text` must carry a
# `signature` to be safely replayed. Gemini and Anthropic sign their thinking
# and reject (or ignore) unsigned/unverifiable text on replay; the encrypted
# entry is what actually carries multi-turn continuity for these formats.
# Matches OpenRouter's own SDK (convert-to-openrouter-chat-messages.ts), where
# an absent `format` defaults to anthropic-claude-v1.
SIGNED_TEXT_REASONING_FORMATS = frozenset({"anthropic-claude-v1", "google-gemini-v1"})
DEFAULT_REASONING_FORMAT = "anthropic-claude-v1"


class ReasoningDetailBase(BaseModel):
    id: str | None = Field(default=None)
    format: str | None = Field(default=None)
    index: int | None = Field(default=None)


class ReasoningDetailSummary(ReasoningDetailBase):
    type: Literal["reasoning.summary"]
    summary: str


class ReasoningDetailEncrypted(ReasoningDetailBase):
    type: Literal["reasoning.encrypted"]
    data: str


class ReasoningDetailText(ReasoningDetailBase):
    type: Literal["reasoning.text"]
    # `text` is optional: Gemini (and per OpenRouter's own SDK, any signed
    # format) can return a thought carried only as a `signature`, with no
    # readable text. Requiring `text` here would fail validation for the whole
    # array and lose any sibling blocks (e.g. an encrypted continuity entry).
    text: str | None = Field(default=None)
    signature: str | None = Field(default=None)


ReasoningDetail = Annotated[
    Union[ReasoningDetailSummary, ReasoningDetailEncrypted, ReasoningDetailText],
    Field(discriminator="type"),
]


def openrouter_reasoning_details_to_reasoning(
    reasoning_details: list[dict[str, Any]],
) -> ContentReasoning:
    details_json = json.dumps(reasoning_details)
    signature = f"{OPENROUTER_REASONING_DETAILS_SIGNATURE}{details_json}"

    try:
        adapter = TypeAdapter(list[ReasoningDetail])
        details = adapter.validate_python(reasoning_details)
    except ValidationError as ex:
        logger.warning(
            f"Error parsing OpenRouter reasoning details: {ex}\n\n{details_json}"
        )
        return ContentReasoning(reasoning=details_json, signature=signature)

    reasoning: str | None = None
    summary: str | None = None
    redacted = False
    for detail in details:
        match detail.type:
            case "reasoning.summary":
                summary = detail.summary
            case "reasoning.text":
                # skip signature-only text (no readable content) so it can't
                # clobber an encrypted sibling regardless of ordering
                if detail.text:
                    reasoning = detail.text
            case "reasoning.encrypted":
                if reasoning is not None:
                    summary = reasoning
                reasoning = detail.data
                redacted = True

    if reasoning is None:
        if summary is not None:
            reasoning = summary
            summary = None
        else:
            # A successfully-parsed array with no human-readable text: a thought
            # carried only as a signature, or an empty continuity slot. This is
            # valid, not an error — the raw details still round-trip via
            # `signature`. Represent it as opaque with no visible text rather
            # than surfacing the raw JSON as reasoning.
            reasoning = ""
            redacted = bool(details)

    return ContentReasoning(
        reasoning=reasoning, summary=summary, redacted=redacted, signature=signature
    )


def reasoning_to_openrouter_reasoning_details(
    content: ContentReasoning,
) -> dict[str, Any] | None:
    if content.signature and content.signature.startswith(
        OPENROUTER_REASONING_DETAILS_SIGNATURE
    ):
        return {
            "reasoning_details": json.loads(
                content.signature.replace(OPENROUTER_REASONING_DETAILS_SIGNATURE, "", 1)
            )
        }

    return None


def sanitize_reasoning_details_for_replay(
    reasoning_details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter stored reasoning details for safe replay to OpenRouter.

    For the signed formats (Gemini, Anthropic) a ``reasoning.text`` entry that
    lacks a ``signature`` cannot be verified by the upstream provider, so it is
    dropped; the accompanying ``reasoning.encrypted`` entry carries the
    continuity the provider actually needs. All other entries — signed text,
    encrypted blobs, summaries, and any non-signed-format text — pass through
    verbatim. An empty result is preserved (returned as ``[]``) rather than
    collapsed to "no reasoning details".

    This mirrors the signature filter in OpenRouter's own SDK
    (``convert-to-openrouter-chat-messages.ts``). It does not port that SDK's
    cross-message de-duplication of reasoning details: models return distinct
    per-turn details, so ordinary generated histories carry no duplicates. A
    history that repeats an identical detail (e.g. copied or hand-edited
    messages) is not de-duplicated here and may be rejected upstream.

    Args:
        reasoning_details: The raw OpenRouter reasoning-detail dicts recovered
            from a ``ContentReasoning`` signature.

    Returns:
        The details to replay, in their original order.
    """
    kept: list[dict[str, Any]] = []
    for detail in reasoning_details:
        if detail.get("type") == "reasoning.text":
            fmt = detail.get("format") or DEFAULT_REASONING_FORMAT
            if fmt in SIGNED_TEXT_REASONING_FORMATS and not detail.get("signature"):
                continue
        kept.append(detail)
    return kept
