from logging import getLogger
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI, BadRequestError
from openai._types import NOT_GIVEN
from openai.types.responses import Response, ResponseFormatTextJSONSchemaConfigParam

from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import ModelOutput, ModelUsage
from .._openai import (
    OpenAIResponseError,
    is_computer_use_preview,
    is_o1_early,
    is_o_series,
    openai_handle_bad_request,
    openai_media_filter,
)
from .._openai_responses import (
    openai_responses_chat_choices,
    openai_responses_inputs,
    openai_responses_tool_choice,
    openai_responses_tools,
)
from .util.hooks import HttpxHooks

logger = getLogger(__name__)


async def generate_responses(
    client: AsyncAzureOpenAI | AsyncOpenAI,
    http_hooks: HttpxHooks,
    model_name: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    service_tier: str | None,
    store: bool,
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
            # TODO: is this the right filter?
            filter=openai_media_filter,
            time=http_hooks.end_request(request_id),
        )

    # prepare request (we do this so we can log the ModelCall)
    tool_params = openai_responses_tools(tools, config) if len(tools) > 0 else NOT_GIVEN
    request = dict(
        input=await openai_responses_inputs(input, model_name, store),
        tools=tool_params,
        tool_choice=openai_responses_tool_choice(tool_choice, tool_params)
        if isinstance(tool_params, list) and tool_choice != "auto"
        else NOT_GIVEN,
        truncation="auto" if is_computer_use_preview(model_name) else NOT_GIVEN,
        extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
        **completion_params_responses(
            model_name,
            config=config,
            service_tier=service_tier,
            tools=len(tools) > 0,
            store=store,
        ),
    )

    try:
        # generate response
        model_response: Response = await client.responses.create(**request)

        # check for error
        if model_response.error is not None:
            raise OpenAIResponseError(
                code=model_response.error.code, message=model_response.error.message
            )

        # save response for model_call
        response = model_response.model_dump()

        # parse out choices
        choices = openai_responses_chat_choices(model_name, model_response, tools)

        # return output and call
        return ModelOutput(
            model=model_response.model,
            choices=choices,
            usage=(
                ModelUsage(
                    input_tokens=model_response.usage.input_tokens,
                    output_tokens=model_response.usage.output_tokens,
                    input_tokens_cache_read=(
                        model_response.usage.input_tokens_details.cached_tokens
                    ),
                    reasoning_tokens=model_response.usage.output_tokens_details.reasoning_tokens,
                    total_tokens=model_response.usage.total_tokens,
                )
                if model_response.usage
                else None
            ),
        ), model_call()
    except BadRequestError as e:
        return openai_handle_bad_request(model_name, e), model_call()


def completion_params_responses(
    model_name: str,
    *,
    config: GenerateConfig,
    service_tier: str | None,
    tools: bool,
    store: bool,
) -> dict[str, Any]:
    # TODO: we'll need a computer_use_preview bool for the 'include'
    # and 'reasoning' parameters
    def unsupported_warning(param: str) -> None:
        warn_once(
            logger,
            f"OpenAI Responses API does not support the '{param}' parameter.",
        )

    params: dict[str, Any] = dict(model=model_name, store=store)
    if service_tier is not None:
        params["service_tier"] = service_tier
    if config.max_tokens is not None:
        params["max_output_tokens"] = config.max_tokens
    if config.frequency_penalty is not None:
        unsupported_warning("frequency_penalty")
    if config.stop_seqs is not None:
        unsupported_warning("stop_seqs")
    if config.presence_penalty is not None:
        unsupported_warning("presence_penalty")
    if config.logit_bias is not None:
        unsupported_warning("logit_bias")
    if config.seed is not None:
        unsupported_warning("seed")
    if config.temperature is not None:
        if is_o_series(model_name):
            warn_once(
                logger,
                "o series models do not support the 'temperature' parameter (temperature is always 1).",
            )
        else:
            params["temperature"] = config.temperature
    if config.top_p is not None:
        params["top_p"] = config.top_p
    if config.num_choices is not None:
        unsupported_warning("num_choices")
    if config.logprobs is not None:
        unsupported_warning("logprobs")
    if config.top_logprobs is not None:
        unsupported_warning("top_logprobs")
    if tools and config.parallel_tool_calls is not None and not is_o_series(model_name):
        params["parallel_tool_calls"] = config.parallel_tool_calls
    if is_o_series(model_name) and not is_o1_early(model_name):
        reasoning: dict[str, str] = {}
        if config.reasoning_effort is not None:
            reasoning["effort"] = config.reasoning_effort
        if config.reasoning_summary is not None:
            reasoning["summary"] = config.reasoning_summary
        if len(reasoning) > 0:
            params["reasoning"] = reasoning
    if config.response_schema is not None:
        params["text"] = dict(
            format=ResponseFormatTextJSONSchemaConfigParam(
                type="json_schema",
                name=config.response_schema.name,
                schema=config.response_schema.json_schema.model_dump(exclude_none=True),
                description=config.response_schema.description
                or config.response_schema.name,
                strict=config.response_schema.strict,
            )
        )

    return params
