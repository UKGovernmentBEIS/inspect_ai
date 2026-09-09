from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

from openai import (
    APIError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    NotGiven,
    UnprocessableEntityError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion

from inspect_ai._util.logger import warn_once
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall, as_error_response
from .._model_output import ModelOutput
from .._openai import (
    chat_choices_from_openai,
    messages_to_openai,
    model_output_from_openai,
    openai_chat_completion_stream_final,
    openai_chat_tool_choice,
    openai_chat_tools,
    openai_completion_params,
    openai_handle_bad_request,
    openai_handle_stream_error,
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
    prompt_cache_key: str | NotGiven,
    prompt_cache_retention: str | NotGiven,
    safety_identifier: str | NotGiven,
    openai_api: "OpenAIAPI",
    batcher: OpenAIBatcher[ChatCompletion] | None,
    streaming: bool = False,
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
    # batching and streaming are mutually exclusive
    streaming = streaming and batcher is None

    # allocate request_id (so we can see it from ModelCall)
    request_id = http_hooks.start_request()

    # unlike text models, vision models require a max_tokens (and set it to a very low
    # default, see https://community.openai.com/t/gpt-4-vision-preview-finish-details/475911/10)
    OPENAI_IMAGE_DEFAULT_TOKENS = 4096
    if "vision" in openai_api.model_family():
        if isinstance(config.max_tokens, int):
            config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
        else:
            config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

    # o-series and gpt5 models use 'developer' rather than 'system' messages
    # https://platform.openai.com/docs/guides/reasoning#advice-on-prompting
    if openai_api.is_o_series() or openai_api.is_gpt_5():
        system_role: Literal["developer", "system"] = "developer"
    else:
        system_role = "system"

    # prepare request (we do this so we can log the ModelCall)
    request = dict(
        messages=await messages_to_openai(input, system_role),
        tools=openai_chat_tools(tools) if len(tools) > 0 else NOT_GIVEN,
        tool_choice=openai_chat_tool_choice(tool_choice)
        if len(tools) > 0
        else NOT_GIVEN,
        extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id}
        | (config.extra_headers or {}),
        **completion_params_completions(openai_api, config, len(tools) > 0),
    )
    if isinstance(prompt_cache_key, str):
        request["prompt_cache_key"] = prompt_cache_key
    if isinstance(prompt_cache_retention, str):
        request["prompt_cache_retention"] = prompt_cache_retention
    if isinstance(safety_identifier, str):
        request["safety_identifier"] = safety_identifier
    if streaming:
        # stream via a raw create(stream=True) call (recorded in the request
        # so the logged ModelCall matches the wire request), asking the server
        # for cumulative usage on the final chunk so the streamed completion
        # carries the same usage as a non-streamed one
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}

    model_call = set_active_model_event_call(
        request=request,
        filter=openai_media_filter,
    )

    try:
        completion: ChatCompletion
        if batcher:
            completion = await batcher.generate_for_request(request)
        elif streaming:
            async with await client.chat.completions.create(**request) as stream:
                completion = await openai_chat_completion_stream_final(stream)
        else:
            completion = await client.chat.completions.create(**request)
        # completion is `CharCompletion | Any`. The lazy type inference engine
        # threw up its hands because of the `**request`.
        assert isinstance(completion, ChatCompletion)

        model_call.set_response(
            completion.model_dump(), http_hooks.end_request(request_id)
        )

        # return output and call
        choices = chat_choices_from_openai(completion, tools)
        return model_output_from_openai(completion, choices), model_call
    except (BadRequestError, UnprocessableEntityError) as e:
        model_call.set_error(
            as_error_response(e.body), http_hooks.end_request(request_id)
        )
        return openai_handle_bad_request(openai_api.service_model_name(), e), model_call
    except APIError as e:
        output = openai_handle_stream_error(openai_api.service_model_name(), e)
        if output is None:
            raise
        model_call.set_error(
            as_error_response(e.body), http_hooks.end_request(request_id)
        )
        return output, model_call


def completion_params_completions(
    openai_api: "OpenAIAPI", config: GenerateConfig, tools: bool
) -> dict[str, Any]:
    # first call the default processing
    params = openai_completion_params(openai_api.api_model_name(), config, tools)

    # add service_tier if specified
    if openai_api.service_tier is not None:
        params["service_tier"] = openai_api.service_tier

    # now tailor to current model
    if config.max_tokens is not None:
        if openai_api.is_o_series() or openai_api.is_gpt_5():
            params["max_completion_tokens"] = config.max_tokens
            del params["max_tokens"]

    if config.temperature is not None:
        if openai_api.is_o_series() or openai_api.is_gpt_5():
            warn_once(
                logger,
                "gpt-5 and o-series models do not support the 'temperature' parameter (temperature is always 1).",
            )
            del params["temperature"]

    # remove parallel_tool_calls if not supported
    if "parallel_tool_calls" in params.keys() and openai_api.is_o_series():
        del params["parallel_tool_calls"]

    # remove reasoning_effort if not supported
    if "reasoning_effort" in params.keys() and (
        openai_api.is_gpt() and not openai_api.is_gpt_5()
    ):
        del params["reasoning_effort"]

    if config.reasoning_mode is not None:
        warn_once(
            logger,
            "The 'reasoning_mode' option is not supported by the chat completions API (use the responses API instead).",
        )

    return params
