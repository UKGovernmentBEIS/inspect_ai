import json
from logging import getLogger
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from inspect_ai._util.content import ContentReasoning

logger = getLogger(__name__)

OPENROUTER_REASONING_DETAILS_SIGNATURE = "reasoning-details://"


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
    text: str
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
            logger.warning(
                f"Error parsing OpenRouter reasoning details: Reasoning content not provided.\n\n{details_json}"
            )
            return ContentReasoning(reasoning=details_json, signature=signature)

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
