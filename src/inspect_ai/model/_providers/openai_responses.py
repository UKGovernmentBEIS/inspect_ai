from logging import getLogger
from typing import Any, Callable

import anyio
from openai import (
    APIStatusError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    NotGiven,
)
from openai._types import NOT_GIVEN
from openai.types.responses import (
    Response,
    ResponseFormatTextJSONSchemaConfigParam,
    ToolParam,
)
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
    ResponsesModelInfo,
    openai_responses_chat_choices,
    openai_responses_inputs,
    openai_responses_tool_choice,
    openai_responses_tools,
    responses_extra_body_fields,
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
    background: bool | None,
    service_tier: str | None,
    prompt_cache_key: str | NotGiven,
    prompt_cache_retention: str | NotGiven,
    safety_identifier: str | NotGiven,
    responses_store: bool | None,
    model_info: ResponsesModelInfo,
    batcher: OpenAIBatcher[Response] | None,
    handle_bad_request: Callable[[APIStatusError], ModelOutput | Exception]
    | None = None,
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
        input=await openai_responses_inputs(input, model_info),
        tools=tool_params,
        tool_choice=openai_responses_tool_choice(tool_choice, tool_params)
        if isinstance(tool_params, list) and tool_choice != "auto"
        else NOT_GIVEN,
        extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
        **completion_params_responses(
            model_name,
            model_info=model_info,
            config=config,
            service_tier=service_tier,
            prompt_cache_key=prompt_cache_key,
            prompt_cache_retention=prompt_cache_retention,
            safety_identifier=safety_identifier,
            responses_store=responses_store,
            tools=len(tools) > 0,
            tool_params=[] if isinstance(tool_params, NotGiven) else tool_params,
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
            usage=model_usage_from_response(model_response),
        ), model_call()
    except BadRequestError as e:
        if handle_bad_request:
            return handle_bad_request(e), model_call()
        else:
            return openai_handle_bad_request(model_name, e), model_call()


def model_usage_from_response(model_response: Response) -> ModelUsage | None:
    return (
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
    )


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
    model_info: ResponsesModelInfo,
    config: GenerateConfig,
    service_tier: str | None,
    prompt_cache_key: str | NotGiven,
    prompt_cache_retention: str | NotGiven,
    safety_identifier: str | NotGiven,
    responses_store: bool | None,
    tools: bool,
    tool_params: list[ToolParam],
) -> dict[str, Any]:
    # TODO: we'll need a computer_use_preview bool for the 'include'
    # and 'reasoning' parameters
    def unsupported_warning(param: str) -> None:
        warn_once(
            logger,
            f"OpenAI Responses API does not support the '{param}' parameter.",
        )

    params: dict[str, Any] = dict(model=model_name, include=[])
    if service_tier is not None:
        params["service_tier"] = service_tier
    if isinstance(prompt_cache_key, str):
        params["prompt_cache_key"] = prompt_cache_key
    if isinstance(prompt_cache_retention, str):
        params["prompt_cache_retention"] = prompt_cache_retention
    if isinstance(safety_identifier, str):
        params["safety_identifier"] = safety_identifier
    if model_info.is_computer_use_preview():
        params["truncation"] = "auto"

    # responses_store may have been specified in config.extra_body
    # (e.g. by a client talking to us through the agent bridge)
    if responses_store is None and config.extra_body and "store" in config.extra_body:
        responses_store = config.extra_body["store"]

    if responses_store is not True:
        params["store"] = False
        if model_info.has_reasoning_options() or model_info.is_computer_use_preview():
            params["include"].append("reasoning.encrypted_content")

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

    # models with reasoning enabled don't do sampling params
    reasoning_enabled = (
        model_info.is_o_series()
        or (model_info.is_gpt_5() and not model_info.is_gpt_5_plus())
        or (
            model_info.is_gpt_5_plus() and config.reasoning_effort not in [None, "none"]
        )
    )

    if config.temperature is not None:
        if reasoning_enabled:
            warn_once(
                logger,
                "Models with reasoning enabled do not support the 'temperature' parameter (temperature is always 1).",
            )
        else:
            params["temperature"] = config.temperature
    if config.top_p is not None:
        if reasoning_enabled:
            warn_once(
                logger,
                "Models with reasoning enabled do not support the 'top_p' parameter.",
            )
        else:
            params["top_p"] = config.top_p
    if config.num_choices is not None:
        unsupported_warning("num_choices")
    if config.logprobs is not None:
        if reasoning_enabled:
            warn_once(
                logger,
                "Models with reasoning enabled do not support the 'logprobs' parameter.",
            )
        else:
            params["include"].append("message.output_text.logprobs")
    if config.top_logprobs is not None:
        if reasoning_enabled:
            warn_once(
                logger,
                "Models with reasoning enabled do not support the 'top_logprobs' parameter.",
            )
        else:
            params["top_logprobs"] = config.top_logprobs
    if (
        tools
        and config.parallel_tool_calls is not None
        and not model_info.is_o_series()
    ):
        params["parallel_tool_calls"] = config.parallel_tool_calls

    if model_info.has_reasoning_options():
        reasoning: dict[str, str] = {}
        if config.reasoning_effort is not None:
            reasoning["effort"] = config.reasoning_effort
        if config.reasoning_summary != "none":
            reasoning["summary"] = config.reasoning_summary or "auto"
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
    if config.verbosity is not None:
        if "text" not in params:
            params["text"] = {}
        params["text"]["verbosity"] = config.verbosity

    if any(tp.get("type") == "code_interpreter" for tp in tool_params):
        params["include"].append("code_interpreter_call.outputs")

    # look for any of our native fields not in GenerateConfig in extra_body
    if config.extra_body is not None:
        for field in responses_extra_body_fields():
            if field in config.extra_body and field not in params:
                params[field] = config.extra_body[field]

    # remove metadata if store is true
    if responses_store is True:
        params.pop("metadata", None)

    return params
