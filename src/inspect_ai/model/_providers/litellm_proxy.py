from collections.abc import AsyncIterable
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
)
from typing_extensions import override

from inspect_ai.tool import ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_info import MODEL_INFO_LOOKUP_API_KEY, _get_model_info_direct
from .._model_output import ChatCompletionChoice, ModelOutput
from .._openai import (
    OpenAIResponseError,
    chat_choices_from_openai,
    openai_chat_completion_stream_final,
    openai_refusal_model_output,
)
from ._litellm_proxy_errors import litellm_error_model_output, upstream_message
from ._litellm_proxy_model_info import ProxyDeployment, proxy_deployments
from ._litellm_proxy_names import ProxyResolution, resolve_deployments
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
LITELLM_PROXY_API_BASE = "LITELLM_PROXY_API_BASE"
"""Base URL variable used by LiteLLM's own SDK; accepted as an alias."""


class LiteLLMProxyAPI(OpenAICompatibleAPI):
    """Provider for models served by a LiteLLM proxy.

    The proxy is self-hosted, so the base URL has no default and must be
    passed as `base_url` or set in `LITELLM_PROXY_BASE_URL` (or
    `LITELLM_PROXY_API_BASE`).

    Construction reads the proxy's `/model/info` listing (see
    `_litellm_proxy_model_info`) and fails if it cannot. Pass
    `model_info=False` to skip it.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        base_url_vars = [LITELLM_PROXY_BASE_URL, LITELLM_PROXY_API_BASE]
        base_url = model_base_url(base_url, base_url_vars)
        if not base_url:
            raise environment_prerequisite_error("LiteLLM Proxy", base_url_vars)
        fetch_model_info = model_args.pop("model_info", True)
        if not isinstance(fetch_model_info, bool):
            raise ValueError("model_info must be a bool")
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="LiteLLM Proxy",
            api_key_var=LITELLM_PROXY_API_KEY,
            **model_args,
        )

        # get_model_info() constructs providers with a placeholder key, which
        # the proxy would reject
        self._deployments: list[ProxyDeployment] | None = None
        if fetch_model_info and self.api_key != MODEL_INFO_LOOKUP_API_KEY:
            assert self.base_url is not None and self.api_key is not None
            alias = self.service_model_name()
            self._deployments = [
                deployment
                for deployment in proxy_deployments(
                    self.base_url,
                    self.api_key,
                    dict(self.model_args.get("default_headers") or {}),
                )
                if deployment.model_name == alias
            ]
        self._resolution: ProxyResolution | None = resolve_deployments(
            self.service_model_name(), self._deployments or []
        )

    def proxy_deployments(self) -> list[ProxyDeployment] | None:
        """The proxy's deployments for this alias (None if not fetched)."""
        return self._deployments

    @override
    def canonical_name(self) -> str:
        """The Inspect database key of the upstream model, when it resolves.

        Otherwise the normalized upstream model name, or the alias when the
        proxy listed no deployment for it (or model info was not fetched).
        """
        resolution = self._resolution
        if resolution is not None:
            name = resolution.db_key or resolution.upstream
            if name:
                return name
        return self.service_model_name()

    @override
    def model_family(self) -> str:
        """The upstream model's name, so request shaping follows the model.

        A `family` registered with `set_model_info` (under the alias, the
        `litellm-proxy/<alias>` model string, or the canonical name) wins.
        The organization is dropped from the canonical name: family checks
        such as `is_o_series_model` match patterns anywhere in the name.
        """
        alias = self.service_model_name()
        canonical = self.canonical_name()
        for name in (alias, f"litellm-proxy/{alias}", canonical):
            info = _get_model_info_direct(name)
            if info is not None and info.family:
                return info.family
        if self._resolution is None:
            return alias
        return canonical.split("/")[-1]

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

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        message = _error_message(ex)
        output = litellm_error_model_output(self.service_model_name(), message)
        if output is None:
            # the base class's message heuristics, recording the upstream
            # message rather than LiteLLM's wrapping of it
            output = openai_refusal_model_output(
                self.service_model_name(),
                ex.code,
                ex.type,
                message,
                upstream_message(message),
            )
        return output if output is not None else super().handle_bad_request(ex)

    @override
    def handle_stream_error(
        self, ex: APIError | OpenAIResponseError
    ) -> ModelOutput | None:
        # status, validation and connection errors keep their retry handling
        if not isinstance(
            ex, APIStatusError | APIResponseValidationError | APIConnectionError
        ):
            message = (
                ex.message
                if isinstance(ex, OpenAIResponseError)
                else _error_message(ex)
            )
            output = litellm_error_model_output(self.service_model_name(), message)
            if output is not None:
                return output
        return super().handle_stream_error(ex)


def _error_message(ex: APIError) -> str:
    """The proxy's error message (the SDK's `message` prefixes the status)."""
    message = ex.body.get("message") if isinstance(ex.body, dict) else None
    return message if isinstance(message, str) else ex.message
