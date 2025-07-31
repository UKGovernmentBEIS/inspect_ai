import os
from json import dumps
from typing import Any, cast

import httpx
from openai import APIStatusError
from openai.types.chat import (
    ChatCompletion,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.model._retry import model_retry_config
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig, normalized_batch_config
from .._model import ModelAPI, log_model_retry
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
    as_stop_reason,
)
from .._openai import chat_message_assistant_from_openai
from ._together_batch import TogetherBatcher
from .openai_compatible import OpenAICompatibleAPI
from .util import (
    chat_api_input,
    chat_api_request,
    model_base_url,
    should_retry_chat_api_error,
)
from .util.chatapi import ChatAPIHandler


def chat_choices_from_response_together(
    response: ChatCompletion, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    logprobs_dicts = [
        choice.logprobs.model_dump() if choice.logprobs is not None else None
        for choice in choices
    ]
    logprobs_models: list[Logprobs | None] = []
    for logprob_dict in logprobs_dicts:
        if logprob_dict is None:
            logprobs_models.append(logprob_dict)
            continue
        tokens = logprob_dict["tokens"]
        token_logprobs = logprob_dict["token_logprobs"]
        logprobs_sequence = []
        for token, logprob in zip(tokens, token_logprobs):
            logprobs_sequence.append(
                Logprob(
                    token=token,
                    logprob=logprob,
                    bytes=list(map(ord, token)),
                    top_logprobs=None,
                )
            )
        logprobs_models.append(Logprobs(content=logprobs_sequence))
    return [
        ChatCompletionChoice(
            message=chat_message_assistant_from_openai(
                response.model, choice.message, tools
            ),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=logprobs,
        )
        for choice, logprobs in zip(choices, logprobs_models)
    ]


class TogetherAIAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Together",
            service_base_url="https://api.together.xyz/v1",
            emulate_tools=emulate_tools,
        )
        self._batcher: TogetherBatcher | None = None

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int | None:
        return DEFAULT_MAX_TOKENS

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        response = ex.response.json()
        if "error" in response and "message" in response.get("error"):
            content = response.get("error").get("message")
        else:
            content = str(response)
        if "max_new_tokens" in ex.message:
            return ModelOutput.from_content(
                model=self.model_name, content=content, stop_reason="model_length"
            )
        else:
            return ex

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)
        if "logprobs" in params:
            params["logprobs"] = 1
        if "top_logprobs" in params:
            del params["top_logprobs"]

        # together requires temperature with num_choices
        if config.num_choices is not None and config.temperature is None:
            params["temperature"] = 1

        return params

    # Together has a slightly different logprobs structure to OpenAI, so we need to remap it.
    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        return chat_choices_from_response_together(completion, tools)

    @override
    async def _generate_completion(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ChatCompletion:
        self._resolve_batcher(config)
        return (
            await self._batcher.generate_for_request(request)
            if self._batcher
            else cast(
                ChatCompletion, await self.client.chat.completions.create(**request)
            )
        )

    def _resolve_batcher(self, config: GenerateConfig) -> None:
        if self._batcher or not (batch_config := normalized_batch_config(config.batch)):
            return

        self._batcher = TogetherBatcher(
            self.client,
            batch_config,
            # TODO: In the future, we could pass max_retries and timeout
            # from batch_config falling back to config
            model_retry_config(
                self.model_name,
                config.max_retries,
                config.timeout,
                self.should_retry,
                log_model_retry,
            ),
        )


# Implementation of REST client for Together (currently not used)

TOGETHER_API_KEY = "TOGETHER_API_KEY"


class TogetherRESTAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        if not api_key:
            api_key = os.environ.get(TOGETHER_API_KEY, None)
            if not api_key:
                raise RuntimeError(f"{TOGETHER_API_KEY} environment variable not set")
        base_url = model_base_url(base_url, "TOGETHER_BASE_URL")
        base_url = base_url if base_url else "https://api.together.xyz/v1"
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[TOGETHER_API_KEY],
            config=config,
        )

        self.client = httpx.AsyncClient()
        self.model_args = model_args

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # chat url
        chat_url = f"{self.base_url}/chat/completions"

        # chat api input
        json: dict[str, Any] = dict(**self.model_args)
        json["model"] = self.model_name
        if config.max_tokens is not None:
            json["max_tokens"] = config.max_tokens
        if config.temperature is not None:
            json["temperature"] = config.temperature
        if config.top_p is not None:
            json["top_p"] = config.top_p
        if config.top_k is not None:
            json["top_k"] = config.top_k
        if config.num_choices is not None:
            json["n"] = config.num_choices
        if config.logprobs:
            json["logprobs"] = config.logprobs
        json["messages"] = chat_api_input(input, tools, self.chat_api_handler())

        # make the call
        response = await chat_api_request(
            self.client,
            model_name=self.model_name,
            url=f"{chat_url}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=json,
        )

        if "error" in response:
            error = response.get("error")
            raise RuntimeError(f"Error calling TogetherAI model: {dumps(error)}")
        else:
            # model name used by back end
            model = response.get("model", self.model_name)

            # generated choices
            choices = together_choices(
                response.get("choices"), tools, self.chat_api_handler()
            )

            # model usage
            if "usage" in response:
                usage_response = response.get("usage")
                usage = ModelUsage(
                    input_tokens=usage_response.get("prompt_tokens", 0),
                    output_tokens=usage_response.get("completion_tokens", 0),
                    total_tokens=usage_response.get("total_tokens", 0),
                )
            else:
                usage = ModelUsage()

            return ModelOutput(model=model, choices=choices, usage=usage)

    @override
    def should_retry(self, ex: Exception) -> bool:
        return should_retry_chat_api_error(ex)

    # cloudflare enforces rate limits by model for each account
    @override
    def connection_key(self) -> str:
        return f"{self.api_key}"

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    def chat_api_handler(self) -> ChatAPIHandler:
        return ChatAPIHandler(self.model_name)


def together_choices(
    choices: list[dict[str, Any]], tools: list[ToolInfo], handler: ChatAPIHandler
) -> list[ChatCompletionChoice]:
    choices.sort(key=lambda c: c.get("index", 0))
    return [together_choice(choice, tools, handler) for choice in choices]


def together_choice(
    choice: dict[str, Any], tools: list[ToolInfo], handler: ChatAPIHandler
) -> ChatCompletionChoice:
    return ChatCompletionChoice(
        message=together_chat_message(choice.get("message", {}), tools, handler),
        stop_reason=together_stop_reason(choice.get("finish_reason", "")),
        logprobs=together_logprobs(choice),
    )


def together_chat_message(
    message: dict[str, str], tools: list[ToolInfo], handler: ChatAPIHandler
) -> ChatMessageAssistant:
    content: str = message.get("content", "")
    return handler.parse_assistant_response(content, tools)


def together_stop_reason(reason: str) -> StopReason:
    match reason:
        case "stop" | "eos":
            return "stop"
        case "length":
            return "max_tokens"
        case "tool_calls" | "max_tokens":
            return reason
        case _:
            return "unknown"


def together_logprobs(choice: dict[str, Any]) -> Logprobs | None:
    logprobs = choice.get("logprobs", None)
    if logprobs:
        logprobs_sequence = []
        for token, logprob in zip(
            logprobs.get("tokens", []), logprobs.get("token_logprobs", [])
        ):
            logprobs_sequence.append(
                Logprob(
                    token=token,
                    logprob=logprob,
                    bytes=list(map(ord, token)),
                    top_logprobs=None,
                )
            )
        tlp = Logprobs(content=logprobs_sequence)
        print(tlp.model_dump_json(indent=2))
        return tlp
    else:
        return None
