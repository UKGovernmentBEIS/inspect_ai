from logging import getLogger
from typing import TYPE_CHECKING, Any

import anyio
from openai import AsyncAzureOpenAI, AsyncOpenAI, BadRequestError, NotGiven
from openai._types import NOT_GIVEN
from openai.types.responses import Response, ResponseFormatTextJSONSchemaConfigParam
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai._util.logger import warn_once
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_output import ModelOutput, ModelUsage
from .._openai import (
    OpenAIResponseError,
    openai_handle_bad_request,
    openai_media_filter,
)
from .._openai_responses import (
    openai_responses_chat_choices,
    openai_responses_inputs,
    openai_responses_tool_choice,
    openai_responses_tools,
    responses_extra_body_fields,
)
from .util.hooks import HttpxHooks

if TYPE_CHECKING:
    from .openai import OpenAIAPI

logger = getLogger(__name__)


async def generate_responses(
    client: AsyncAzureOpenAI | AsyncOpenAI,
    http_hooks: HttpxHooks,
    model_name: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
    background: bool | None,
    service_tier: str | None,
    prompt_cache_key: str | NotGiven,
    safety_identifier: str | NotGiven,
    responses_store: bool | None,
    openai_api: "OpenAIAPI",
    batcher: OpenAIBatcher[Response] | None,
) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
    # batch mode and background are incompatible
    if batcher:
        background = False

    # background in extra_body should be applied
    if background is None and config.extra_body:
        background = config.extra_body.pop("background", None)

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
    tool_params = (
        openai_responses_tools(tools, model_name, config)
        if len(tools) > 0
        else NOT_GIVEN
    )
    request = dict(
        input=await openai_responses_inputs(input, openai_api),
        tools=tool_params,
        tool_choice=openai_responses_tool_choice(tool_choice, tool_params)
        if isinstance(tool_params, list) and tool_choice != "auto"
        else NOT_GIVEN,
        extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
        **completion_params_responses(
            model_name,
            openai_api=openai_api,
            config=config,
            service_tier=service_tier,
            prompt_cache_key=prompt_cache_key,
            safety_identifier=safety_identifier,
            responses_store=responses_store,
            tools=len(tools) > 0,
        ),
    )
    if isinstance(background, bool):
        request["background"] = background

    try:
        # generate response
        model_response: Response = await (
            batcher.generate_for_request(request)
            if batcher
            else client.responses.create(**request)
        )
        # model_response is `Response | Any`. The lazy type inference engine
        # threw up its hands because of the `**request`.
        assert isinstance(model_response, Response)

        # if this is a background request then poll for status until we get it
        if background:
            model_response = await wait_for_background_response(client, model_response)

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
        return openai_handle_bad_request(
            openai_api.service_model_name(), e
        ), model_call()


async def wait_for_background_response(
    client: AsyncAzureOpenAI | AsyncOpenAI, model_response: Response
) -> Response:
    # do some retrying so we don't waste expensive background work
    # because of transient networking issues
    @retry(
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(5) | stop_after_delay(60),
        retry=retry_if_exception(httpx_should_retry),
        before_sleep=log_httpx_retry_attempt(
            f"background polling: {model_response.model}"
        ),
    )
    async def check_model_response(model_response: Response) -> Response:
        return await client.responses.retrieve(model_response.id)

    try:
        # keep checking status until we get "complete", "incomplete", of "failed"
        while model_response.status in {"queued", "in_progress"}:
            await anyio.sleep(5)
            model_response = await check_model_response(model_response)
        return model_response
    except anyio.get_cancelled_exc_class():
        # if the entire sample is cancelled then let the provider know
        # so we can stop racking up token costs
        with anyio.move_on_after(5, shield=True):
            try:
                await client.responses.cancel(model_response.id)
            except BaseException as ex:
                logger.warning(
                    f"Error while attempting to cancel background request: {ex}"
                )
                pass
        raise


def completion_params_responses(
    model_name: str,
    *,
    openai_api: "OpenAIAPI",
    config: GenerateConfig,
    service_tier: str | None,
    prompt_cache_key: str | NotGiven,
    safety_identifier: str | NotGiven,
    responses_store: bool | None,
    tools: bool,
) -> dict[str, Any]:
    # TODO: we'll need a computer_use_preview bool for the 'include'
    # and 'reasoning' parameters
    def unsupported_warning(param: str) -> None:
        warn_once(
            logger,
            f"OpenAI Responses API does not support the '{param}' parameter.",
        )

    params: dict[str, Any] = dict(model=model_name)
    if service_tier is not None:
        params["service_tier"] = service_tier
    if isinstance(prompt_cache_key, str):
        params["prompt_cache_key"] = prompt_cache_key
    if isinstance(safety_identifier, str):
        params["safety_identifier"] = safety_identifier
    if openai_api.is_computer_use_preview():
        params["truncation"] = "auto"

    if responses_store is False:
        if openai_api.is_computer_use_preview():
            raise RuntimeError(
                "OpenAI computer use model requires responses store=True"
            )
        params["store"] = False
        params["include"] = ["reasoning.encrypted_content"]

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
        if openai_api.is_o_series() or openai_api.is_gpt_5():
            warn_once(
                logger,
                "gpt-5 and o-series models do not support the 'temperature' parameter (temperature is always 1).",
            )
        else:
            params["temperature"] = config.temperature
    if config.top_p is not None:
        if openai_api.is_o_series() or openai_api.is_gpt_5():
            warn_once(
                logger,
                "gpt-5 and o-series models do not support the 'top_p' parameter.",
            )
        else:
            params["top_p"] = config.top_p
    if config.num_choices is not None:
        unsupported_warning("num_choices")
    if config.logprobs is not None:
        unsupported_warning("logprobs")
    if config.top_logprobs is not None:
        unsupported_warning("top_logprobs")
    if (
        tools
        and config.parallel_tool_calls is not None
        and not openai_api.is_o_series()
    ):
        params["parallel_tool_calls"] = config.parallel_tool_calls

    if (
        (openai_api.is_o_series() and not openai_api.is_o1_early())
        or openai_api.is_gpt_5()
        or openai_api.is_codex()
    ):
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

    # look for any of our native fields not in GenerateConfig in extra_body
    if config.extra_body is not None:
        for field in responses_extra_body_fields():
            if field in config.extra_body and field not in params:
                params[field] = config.extra_body[field]

    return params
