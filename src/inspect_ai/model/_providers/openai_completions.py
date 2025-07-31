from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

from openai import (
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    NotGiven,
    UnprocessableEntityError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion

from inspect_ai._util.logger import warn_once
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import ModelOutput
from .._openai import (
    chat_choices_from_openai,
    model_output_from_openai,
    openai_chat_messages,
    openai_chat_tool_choice,
    openai_chat_tools,
    openai_completion_params,
    openai_handle_bad_request,
    openai_media_filter,
)
from .util.hooks import HttpxHooks

if TYPE_CHECKING:
    from .openai import OpenAIAPI

logger = getLogger(__name__)


async def generate_completions(
    client: AsyncAzureOpenAI | AsyncOpenAI,
    http_hooks: HttpxHooks,
    model_name: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    user: str | NotGiven,
    openai_api: "OpenAIAPI",
    batcher: OpenAIBatcher[ChatCompletion] | None,
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
    # allocate request_id (so we can see it from ModelCall)
    request_id = http_hooks.start_request()

    # setup request and response for ModelCall
    request: dict[str, Any] = {}
    response: dict[str, Any] = {}

    def model_call() -> ModelCall:
        return ModelCall.create(
            request=request,
            response=response,
            filter=openai_media_filter,
            time=http_hooks.end_request(request_id),
        )

    # unlike text models, vision models require a max_tokens (and set it to a very low
    # default, see https://community.openai.com/t/gpt-4-vision-preview-finish-details/475911/10)
    OPENAI_IMAGE_DEFAULT_TOKENS = 4096
    if "vision" in openai_api.service_model_name():
        if isinstance(config.max_tokens, int):
            config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
        else:
            config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

    # determine system role
    # o1-mini does not support developer or system messages
    # (see Dec 17, 2024 changelog: https://platform.openai.com/docs/changelog)
    if openai_api.is_o1_early():
        system_role: Literal["user", "system", "developer"] = "user"
    # other o-series models use 'developer' rather than 'system' messages
    # https://platform.openai.com/docs/guides/reasoning#advice-on-prompting
    elif openai_api.is_o_series():
        system_role = "developer"
    else:
        system_role = "system"

    # prepare request (we do this so we can log the ModelCall)
    request = dict(
        messages=await openai_chat_messages(input, system_role),
        tools=openai_chat_tools(tools) if len(tools) > 0 else NOT_GIVEN,
        tool_choice=openai_chat_tool_choice(tool_choice)
        if len(tools) > 0
        else NOT_GIVEN,
        extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
        user=user,
        **completion_params_completions(openai_api, config, len(tools) > 0),
    )

    try:
        completion = await (
            batcher.generate_for_request(request)
            if batcher
            else client.chat.completions.create(**request)
        )
        # completion is `CharCompletion | Any`. The lazy type inference engine
        # threw up its hands because of the `**request`.
        assert isinstance(completion, ChatCompletion)

        # save response for model_call
        response = completion.model_dump()

        # return output and call
        choices = chat_choices_from_openai(completion, tools)
        return model_output_from_openai(completion, choices), model_call()
    except (BadRequestError, UnprocessableEntityError) as e:
        return openai_handle_bad_request(
            openai_api.service_model_name(), e
        ), model_call()


def completion_params_completions(
    openai_api: "OpenAIAPI", config: GenerateConfig, tools: bool
) -> dict[str, Any]:
    # first call the default processing
    params = openai_completion_params(openai_api.service_model_name(), config, tools)

    # add service_tier if specified
    if openai_api.service_tier is not None:
        params["service_tier"] = openai_api.service_tier

    # now tailor to current model
    if config.max_tokens is not None:
        if openai_api.is_o_series():
            params["max_completion_tokens"] = config.max_tokens
            del params["max_tokens"]

    if config.temperature is not None:
        if openai_api.is_o_series():
            warn_once(
                logger,
                "o series models do not support the 'temperature' parameter (temperature is always 1).",
            )
            del params["temperature"]

    # remove parallel_tool_calls if not supported
    if "parallel_tool_calls" in params.keys() and openai_api.is_o_series():
        del params["parallel_tool_calls"]

    # remove reasoning_effort if not supported
    if "reasoning_effort" in params.keys() and (
        openai_api.is_gpt() or openai_api.is_o1_early()
    ):
        del params["reasoning_effort"]

    return params
