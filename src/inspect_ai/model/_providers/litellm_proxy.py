from collections.abc import AsyncIterable
from typing import Any

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
)
from typing_extensions import override

from inspect_ai.tool import ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_output import ChatCompletionChoice
from .._openai import chat_choices_from_openai, openai_chat_completion_stream_final
from ._litellm_proxy_reasoning import (
    ThinkingBlocksAccumulator,
    choice_with_litellm_reasoning,
    litellm_messages_to_openai,
    with_streamed_thinking_blocks,
    without_thinking_block_deltas,
)
from .openai_compatible import ModelInfo, OpenAICompatibleAPI
from .util import environment_prerequisite_error, model_base_url

LITELLM_PROXY_API_KEY = "LITELLM_PROXY_API_KEY"
LITELLM_PROXY_BASE_URL = "LITELLM_PROXY_BASE_URL"


class LiteLLMProxyAPI(OpenAICompatibleAPI):
    """Provider for models served by a LiteLLM proxy.

    The proxy is self-hosted, so the base URL has no default and must be
    passed as `base_url` or set in `LITELLM_PROXY_BASE_URL`.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        base_url = model_base_url(base_url, LITELLM_PROXY_BASE_URL)
        if not base_url:
            raise environment_prerequisite_error(
                "LiteLLM Proxy", LITELLM_PROXY_BASE_URL
            )
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="LiteLLM Proxy",
            api_key_var=LITELLM_PROXY_API_KEY,
            **model_args,
        )

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # chat_choices_from_openai returns choices ordered by index
        sources = sorted(completion.choices, key=lambda choice: choice.index)
        return [
            choice_with_litellm_reasoning(choice, source.message)
            for choice, source in zip(
                chat_choices_from_openai(completion, tools), sources, strict=True
            )
        ]

    @override
    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        return await litellm_messages_to_openai(input)

    @override
    async def stream_completion(
        self, stream: AsyncIterable[ChatCompletionChunk]
    ) -> ChatCompletion:
        accumulators: dict[int, ThinkingBlocksAccumulator] = {}
        completion = await openai_chat_completion_stream_final(
            without_thinking_block_deltas(stream, accumulators)
        )
        return with_streamed_thinking_blocks(completion, accumulators)

    @override
    def responses_model_info(self) -> ModelInfo:
        # LiteLLM converts Responses reasoning items to each upstream
        # provider's format: reasoning with no encrypted content (open models)
        # must be sent back as text, and some upstreams reject empty text
        return ModelInfo(
            self.model_family(),
            supports_max_reasoning_effort=self.supports_max_reasoning_effort(),
            replays_reasoning_text=True,
            omits_empty_tool_call_text=True,
        )
