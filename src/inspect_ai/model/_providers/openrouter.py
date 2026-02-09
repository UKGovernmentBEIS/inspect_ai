import json
from logging import getLogger
from typing import Annotated, Any, Literal, TypedDict, Union, cast

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
)
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from typing_extensions import NotRequired, override

from inspect_ai._util.content import ContentReasoning
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.model._openai import (
    CompletionsReasoningContent,
    OpenAIResponseError,
    chat_choices_from_openai,
    openai_chat_message,
)
from inspect_ai.model._reasoning import (
    reasoning_to_think_tag,
)
from inspect_ai.tool._tool_info import ToolInfo

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

OPENROUTER_API_KEY = "OPENROUTER_API_KEY"

logger = getLogger(__name__)


class ErrorResponse(TypedDict):
    code: int
    message: str
    metadata: NotRequired[dict[str, Any]]


class OpenRouterError(Exception):
    def __init__(self, response: ErrorResponse) -> None:
        self.response = response

    @property
    def message(self) -> str:
        return f"Error {self.response['code']} - {self.response['message']}"

    def __str__(self) -> str:
        return (
            self.message + ("\n" + json.dumps(self.response["metadata"], indent=2))
            if "metadata" in self.response
            else ""
        )


class OpenRouterAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        # collect known model args that we forward to generate
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        # models arg
        self.models = collect_model_arg("models")
        if self.models is not None:
            if not isinstance(self.models, list):
                raise PrerequisiteError("models must be a list of strings")

        # providers arg
        self.provider = collect_model_arg("provider")
        if self.provider is not None:
            if not isinstance(self.provider, dict):
                raise PrerequisiteError("provider must be a dict")

        # transforms arg
        self.transforms = collect_model_arg("transforms")
        if self.transforms is not None:
            if not isinstance(self.transforms, list):
                raise PrerequisiteError("transforms must be a list of strings")

        self.reasoning_enabled = collect_model_arg("reasoning_enabled")
        if self.reasoning_enabled is not None:
            if not isinstance(self.reasoning_enabled, bool):
                raise PrerequisiteError("reasoning_enabled must be a boolean")

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="OpenRouter",
            service_base_url="https://openrouter.ai/api/v1",
            emulate_tools=emulate_tools,
            **model_args,
        )

    @override
    def should_retry(self, ex: BaseException) -> bool:
        if super().should_retry(ex):
            return True
        elif isinstance(ex, json.JSONDecodeError):
            return True
        else:
            return False

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        OpenRouter model names may include provider prefixes like
        'together/meta-llama/Llama-3.1-8B'. For inference providers (together,
        fireworks, etc.), the prefix is stripped. For first-party providers
        (anthropic, openai, etc.), the full name is preserved.

        OpenRouter also supports suffixes like :free, :extended, :nitro,
        :thinking, :online which are stripped for database lookup.
        """
        from ._first_party import FIRST_PARTY_PROVIDERS

        name = self.service_model_name()

        # Strip OpenRouter suffixes (:free, :extended, :nitro, :thinking, :online)
        if ":" in name:
            name = name.split(":")[0]

        parts = name.split("/")
        if len(parts) >= 2:
            first_part = parts[0].lower()
            # If first part is a known first-party provider, keep the full name
            if first_part in FIRST_PARTY_PROVIDERS:
                return name
            # Otherwise strip the inference provider prefix (e.g., together/)
            if len(parts) >= 3:
                return "/".join(parts[1:])
        return name

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # extract reasoning details
        def extract_reasoning_details(
            content: CompletionsReasoningContent,
        ) -> ContentReasoning | None:
            if content.source == "reasoning_details":
                if isinstance(content.reasoning, list):
                    return openrouter_reasoning_details_to_reasoning(
                        cast(list[dict[str, Any]], content.reasoning)
                    )
                else:
                    logger.warning(
                        f"Unexpected type for openrouter reasoning details: f{type(content.reasoning)}"
                    )
                    return None
            else:
                return None

        return chat_choices_from_openai(completion, tools, extract_reasoning_details)

    @override
    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        # convert reasoning_details to an extra body parameter
        def handle_reasoning_details(
            content: ContentReasoning,
        ) -> dict[str, JsonValue] | str:
            details = reasoning_to_openrouter_reasoning_details(content)
            if details is not None:
                return details
            else:
                return reasoning_to_think_tag(content)

        return [
            await openai_chat_message(message, "system", handle_reasoning_details)
            for message in input
        ]

    @override
    def on_response(self, response: dict[str, Any]) -> None:
        """Handle documented OpenRouter error conditions.

        https://openrouter.ai/docs/api-reference/errors
        """
        # check if open-router yielded an error (raise explicit
        # OpenAIResponseError for cases where we should retry)
        error: ErrorResponse | None = response.get("error", None)
        if error is not None:
            if error["code"] == 429:
                raise OpenAIResponseError("rate_limit_exceeded", error["message"])
            elif error["code"] in [408, 500, 502, 504]:
                raise OpenAIResponseError("server_error", error["message"])
            else:
                raise OpenRouterError(error)

        # check for an empty response (which they document can occur on
        # startup). for this we'll return a "server_error" which will
        # trigger a retry w/ exponential backoff
        elif response.get("choices", None) is None:
            raise OpenAIResponseError(
                "server_error",
                "Model is warming up, please retry again after waiting for warmup.",
            )

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        # default params
        params = super().completion_params(config, tools)

        # remove reasoning_effort it is exists
        if "reasoning_effort" in params:
            del params["reasoning_effort"]

        # provide openrouter standard reasoning options
        # https://openrouter.ai/docs/use-cases/reasoning-tokens
        reasoning: dict[str, str | int] | None = None
        if (
            config.reasoning_effort is not None
            or config.reasoning_tokens is not None
            or self.reasoning_enabled is not None
        ):
            reasoning = dict()
            # openrouter supports one of max_tokens or effort, prefer effort
            if config.reasoning_effort is not None:
                reasoning["effort"] = config.reasoning_effort
                if config.reasoning_tokens is not None:
                    warn_once(
                        logger,
                        "You can only specify `reasoning_effort` or `reasoning_tokens`, not both. Ignoring `reasoning_tokens`.",
                    )
            elif config.reasoning_tokens is not None:
                reasoning["max_tokens"] = config.reasoning_tokens
            if self.reasoning_enabled is not None:
                # enabled=false will disable reasoning on hybrid models
                reasoning["enabled"] = self.reasoning_enabled

        # pass args if specifed
        EXTRA_BODY = "extra_body"
        if self.models or self.provider or self.transforms or reasoning:
            params[EXTRA_BODY] = params.get(EXTRA_BODY, {})
            if self.models:
                params[EXTRA_BODY]["models"] = self.models
            if self.provider:
                params[EXTRA_BODY]["provider"] = self.provider
            if self.transforms:
                params[EXTRA_BODY]["transforms"] = self.transforms
            if reasoning:
                params[EXTRA_BODY]["reasoning"] = reasoning

        return params


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


# openrouter uses reasoning_details
# https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#responses-api-shape
def openrouter_reasoning_details_to_reasoning(
    reasoning_details: list[dict[str, Any]],
) -> ContentReasoning:
    # store the full data structure in the signature for replay
    details_json = json.dumps(reasoning_details)
    signature = f"{OPENROUTER_REASONING_DETAILS_SIGNATURE}{details_json}"

    # attempt to parse out the details
    try:
        adapter = TypeAdapter(list[ReasoningDetail])
        details = adapter.validate_python(reasoning_details)
    except ValidationError as ex:
        logger.warning(
            f"Error parsing OpenRouter reasoning details: {ex}\n\n{details_json}"
        )
        return ContentReasoning(reasoning=details_json, signature=signature)

    # collect reasoning fields from details
    reasoning: str | None = None
    summary: str | None = None
    redacted: bool = False
    for detail in details:
        match detail.type:
            case "reasoning.summary":
                summary = detail.summary
            case "reasoning.text":
                reasoning = detail.text
            case "reasoning.encrypted":
                reasoning = detail.data
                redacted = True

    # resolve reasoning
    if reasoning is None:
        # summary becomes reasoning if there is no reasoning
        if summary is not None:
            reasoning = summary
            summary = None
        # otherwise this an unepxected state
        else:
            logger.warning(
                f"Error parsing OpenRouter reasoning details: Reasoning content not provided.\n\n{details_json}"
            )
            return ContentReasoning(reasoning=details_json, signature=signature)

    # return reasoning
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

    # default to no handling
    return None
