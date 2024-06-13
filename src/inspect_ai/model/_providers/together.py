import os

from openai.types.chat import (
    ChatCompletion,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS

from .._generate_config import GenerateConfig
from .._model_output import ChatCompletionChoice, Logprob, Logprobs
from .openai import (
    OpenAIAPI,
    chat_message_assistant,
)
from .util import as_stop_reason, model_base_url


def chat_choices_from_response_together(
    response: ChatCompletion,
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
            message=chat_message_assistant(choice.message),
            stop_reason=as_stop_reason(choice.finish_reason),
            logprobs=logprobs,
        )
        for choice, logprobs in zip(choices, logprobs_models)
    ]


class TogetherAIAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        api_key = os.environ.get("TOGETHER_API_KEY", None)
        if not api_key:
            raise RuntimeError("TOGETHER_API_KEY environment variable not set")
        base_url = model_base_url(base_url, "TOGETHER_BASE_URL")
        base_url = base_url if base_url else "https://api.together.xyz/v1"
        super().__init__(
            model_name=model_name, base_url=base_url, config=config, api_key=api_key
        )

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    # Together has a slightly different logprobs structure to OpenAI, so we need to remap it.
    def _chat_choices_from_response(
        self, response: ChatCompletion
    ) -> list[ChatCompletionChoice]:
        return chat_choices_from_response_together(response)
