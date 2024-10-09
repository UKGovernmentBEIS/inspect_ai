import os
from json import dumps
from typing import Any

import httpx
from openai import BadRequestError
from openai.types.chat import (
    ChatCompletion,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.model._providers.util.chatapi import ChatAPIHandler
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .openai import (
    OpenAIAPI,
    chat_message_assistant,
)
from .util import (
    as_stop_reason,
    chat_api_input,
    chat_api_request,
    environment_prerequisite_error,
    is_chat_api_rate_limit,
    model_base_url,
)


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
            message=chat_message_assistant(choice.message, tools),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=logprobs,
        )
        for choice, logprobs in zip(choices, logprobs_models)
    ]


TOGETHER_API_KEY = "TOGETHER_API_KEY"


class TogetherAIAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        if not api_key:
            api_key = os.environ.get(TOGETHER_API_KEY, None)
            if not api_key:
                raise environment_prerequisite_error("TogetherAI", TOGETHER_API_KEY)
        base_url = model_base_url(base_url, "TOGETHER_BASE_URL")
        base_url = base_url if base_url else "https://api.together.xyz/v1"
        super().__init__(
            model_name=model_name, base_url=base_url, api_key=api_key, config=config
        )

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    @override
    def handle_bad_request(self, ex: BadRequestError) -> ModelOutput:
        if ex.status_code == 400 and "max_new_tokens" in ex.message:
            response = ex.response.json()
            if "error" in response and "message" in response.get("error"):
                content = response.get("error").get("message")
            else:
                content = str(response)
            return ModelOutput.from_content(
                model=self.model_name, content=content, stop_reason="model_length"
            )
        else:
            raise ex

    # Together has a slightly different logprobs structure to OpenAI, so we need to remap it.
    def _chat_choices_from_response(
        self, response: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        return chat_choices_from_response_together(response, tools)


# Implementation of REST client for Together (currently not used)


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
            config=config,
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
    def is_rate_limit(self, ex: BaseException) -> bool:
        return is_chat_api_rate_limit(ex)

    # cloudflare enforces rate limits by model for each account
    @override
    def connection_key(self) -> str:
        return f"{self.api_key}"

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    def chat_api_handler(self) -> ChatAPIHandler:
        return ChatAPIHandler()


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
