import os
import re
from logging import getLogger
from typing import Any

import anyio
from openai import (
    APIStatusError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    NotGiven,
    RateLimitError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.responses import Response
from openai.types.shared_params.reasoning import Reasoning
from typing_extensions import override

from inspect_ai._util.logger import warn_once
from inspect_ai.model._generate_config import normalized_batch_config
from inspect_ai.model._providers.openai_completions import (
    completion_params_completions,
    generate_completions,
)
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.model._retry import ModelRetryConfig, model_retry_config
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI, log_model_retry
from .._model_call import ModelCall
from .._model_info import get_model_info
from .._model_output import ModelOutput, ModelUsage
from .._openai import (
    OpenAIAsyncHttpxClient,
    openai_should_retry,
)
from .._openai_responses import (
    chat_messages_from_compact_response,
    is_native_tool_configured,
    model_usage_from_compact_response,
    openai_responses_inputs,
    pad_tool_messages_for_token_counting,
)
from ._openai_batch import OpenAIBatcher
from .openai_o1 import generate_o1
from .util import (
    check_azure_deployment_mismatch,
    environment_prerequisite_error,
    model_base_url,
    require_azure_base_url,
    resolve_api_key,
    resolve_azure_token_provider,
)

logger = getLogger(__name__)

OPENAI_API_KEY = "OPENAI_API_KEY"
AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
AZUREAI_OPENAI_API_KEY = "AZUREAI_OPENAI_API_KEY"

# Azure base URL environment variables
AZURE_OPENAI_BASE_URL_VARS = [
    "AZUREAI_OPENAI_BASE_URL",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_ENDPOINT",
]


# NOTE: If you are creating a new provider that is OpenAI compatible you should inherit from OpenAICompatibleAPI rather than OpenAIAPI.


class OpenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        responses_api: bool | None = None,
        responses_store: bool | None = None,
        service_tier: str | None = None,
        client_timeout: float | None = None,
        background: bool | None = None,
        **model_args: Any,
    ) -> None:
        # extract azure service prefix from model name (other providers
        # that subclass from us like together expect to have the qualifier
        # in the model name e.g. google/gemma-2b-it)
        parts = model_name.split("/")
        if parts[0] == "azure" and len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # extract prompt_cache_key model arg if provided
        self.prompt_cache_key: str | NotGiven = model_args.pop(
            "prompt_cache_key", NOT_GIVEN
        )

        # extract prompt_cache_retention model arg if provided
        self.prompt_cache_retention: str | NotGiven = model_args.pop(
            "prompt_cache_retention", NOT_GIVEN
        )

        # extract safety_identifier model arg if provided
        self.safety_identifier: str | NotGiven = model_args.pop(
            "safety_identifier", NOT_GIVEN
        )

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[OPENAI_API_KEY, AZURE_OPENAI_API_KEY, AZUREAI_OPENAI_API_KEY],
            config=config,
        )

        # check for Azure model/URL mismatch
        if self.is_azure():
            check_azure_deployment_mismatch(
                self.service_model_name(),
                base_url,
                AZURE_OPENAI_BASE_URL_VARS,
                "AZUREAI_OPENAI",
            )

        # set background bit (automatically use background for deep research)
        if background is None and (self.is_deep_research() or self.is_gpt_5_pro()):
            background = True
        self.background = background

        # is this a model we use responses api by default for?
        responses_preferred = (
            (self.is_o_series() and not self.is_o1_early())
            or self.is_codex()
            or self.is_gpt_5()
        ) and config.num_choices is None

        # resolve whether we are forcing the responses api
        self.responses_api = (
            background
            or self.is_computer_use_preview()
            or (responses_api if responses_api is not None else responses_preferred)
        )

        # resolve whether we are using the responses store
        self.responses_store = responses_store

        # set service tier if specified
        self.service_tier = service_tier

        # bump up default client timeout to 15 minutes for service_tier=="flex"
        self.client_timeout = client_timeout or (
            900.0 if self.service_tier == "flex" else None
        )

        # resolve api_key or managed identity (for Azure)
        self.token_provider = None
        if not self.api_key:
            if self.is_azure():
                self.api_key = resolve_api_key(
                    [AZUREAI_OPENAI_API_KEY, AZURE_OPENAI_API_KEY]
                )
                if not self.api_key:
                    # try managed identity (Microsoft Entra ID)
                    self.token_provider = resolve_azure_token_provider("OpenAI")
            else:
                self.api_key = os.environ.get(OPENAI_API_KEY, None)

            if not self.api_key and not self.token_provider:
                raise environment_prerequisite_error(
                    "OpenAI",
                    [
                        OPENAI_API_KEY,
                        AZUREAI_OPENAI_API_KEY,
                        "managed identity (Entra ID)",
                    ],
                )

        # extract http_client and api_version before storing model_args
        self.http_client = (
            model_args.pop("http_client", None) or OpenAIAsyncHttpxClient()
        )
        if self.is_azure():
            # resolve version
            if model_args.get("api_version") is not None:
                self.api_version = model_args.pop("api_version")
            else:
                self.api_version = os.environ.get(
                    "AZUREAI_OPENAI_API_VERSION",
                    os.environ.get("OPENAI_API_VERSION", "2025-03-01-preview"),
                )

        # set initial reasoning_summaries bit (requires organizational verifification
        # so we will probe for it on-demand if a request w/ reasoning summaries comes in)
        self._reasoning_summaries: bool | None = None
        self._reasoning_summaries_lock = anyio.Lock()

        # store remaining model_args after extraction
        self.model_args = model_args
        self.initialize()

    def _create_client(self) -> AsyncAzureOpenAI | AsyncOpenAI:
        # azure client
        if self.is_azure():
            # resolve base_url (required for Azure)
            base_url = require_azure_base_url(
                self.base_url, AZURE_OPENAI_BASE_URL_VARS, "OpenAI"
            )

            # use managed identity if available, otherwise API key
            return AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_ad_token_provider=self.token_provider,
                api_version=self.api_version,
                azure_endpoint=base_url,
                http_client=self.http_client,
                timeout=self.client_timeout
                if self.client_timeout is not None
                else NOT_GIVEN,
                **self.model_args,
            )
        else:
            return AsyncOpenAI(
                api_key=self.api_key,
                base_url=model_base_url(self.base_url, "OPENAI_BASE_URL"),
                http_client=self.http_client,
                timeout=self.client_timeout
                if self.client_timeout is not None
                else NOT_GIVEN,
                **self.model_args,
            )

    def initialize(self) -> None:
        super().initialize()

        if self.http_client.is_closed:
            self.http_client = OpenAIAsyncHttpxClient()

        self.client = self._create_client()

        # TODO: Although we could enhance OpenAIBatcher to support requests with
        # homogenous endpoints (e.g. some going to completions and some going to
        # responses), the code would have to be more complex to retain type safety.
        # We'd have to track the endpoint and ResultCls for each request and also
        # cast? the result when resolving the generate promise. For now, we'll
        # side step that complexity and just use two different batchers.
        self._completions_batcher: OpenAIBatcher[ChatCompletion] | None = None
        self._responses_batcher: OpenAIBatcher[Response] | None = None
        self._http_hooks = HttpxHooks(self.client._client)

    @override
    async def count_text_tokens(self, text: str) -> int:
        import tiktoken

        try:
            enc = tiktoken.encoding_for_model(self.service_model_name())
        except KeyError:
            enc = tiktoken.get_encoding("o200k_base")  # fallback

        tokens = enc.encode(text)
        return len(tokens)

    @override
    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        """Count tokens using native API for messages, tiktoken for text.

        For messages, uses OpenAI's input_tokens endpoint which can accurately
        count encrypted reasoning blocks. Raises an exception if native
        counting fails.
        """
        if isinstance(input, str):
            return await self.count_text_tokens(input)

        # Use native counting for responses API (required for accurate counting)
        if self.responses_api:
            return await self._count_tokens_native(input, config)

        # For non-responses API, use tiktoken-based counting
        from .._tokens import count_tokens

        return await count_tokens(
            input, self.count_text_tokens, self.count_media_tokens
        )

    async def _count_tokens_native(
        self,
        messages: list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        """Count tokens using OpenAI's input_tokens endpoint.

        This endpoint can accurately count encrypted reasoning blocks
        that cannot be counted using tiktoken. Uses padding to handle
        orphaned tool calls/outputs for per-message counting.
        """
        # Convert messages to OpenAI input format
        input_items = await openai_responses_inputs(messages, self)

        # Apply padding to handle orphaned tool calls for per-message counting
        padded_items = pad_tool_messages_for_token_counting(input_items)

        # Call the input_tokens endpoint with reasoning settings
        response = await self.client.responses.input_tokens.count(
            model=self.service_model_name(),
            input=padded_items,
            reasoning=self._get_reasoning_params_for_config(config),
        )

        return response.input_tokens

    def is_azure(self) -> bool:
        return self.service == "azure"

    def has_reasoning_options(self) -> bool:
        return (
            (self.is_o_series() and not self.is_o1_early())
            or (self.is_gpt_5() and not self.is_gpt_5_chat())
            or self.is_codex()
        )

    def is_o_series(self) -> bool:
        name = self.service_model_name()
        if bool(re.match(r"^o\d+", name)):
            return True
        else:
            return not self.is_gpt() and bool(re.search(r"o\d+", name))

    def is_deep_research(self) -> bool:
        return "deep-research" in self.service_model_name()

    def is_gpt_5(self) -> bool:
        name = self.service_model_name()
        return "gpt-5" in name

    def is_gpt_5_plus(self) -> bool:
        name = self.service_model_name()
        return "gpt-5." in name

    def is_gpt_5_pro(self) -> bool:
        name = self.service_model_name()
        return self.is_gpt_5() and "-pro" in name

    def is_gpt_5_chat(self) -> bool:
        name = self.service_model_name()
        return self.is_gpt_5() and "-chat" in name

    def is_o1(self) -> bool:
        name = self.service_model_name()
        return "o1" in name and not self.is_o1_early()

    def is_o1_early(self) -> bool:
        name = self.service_model_name()
        return "o1-mini" in name or "o1-preview" in name

    def is_o3_mini(self) -> bool:
        name = self.service_model_name()
        return "o3-mini" in name

    def is_computer_use_preview(self) -> bool:
        name = self.service_model_name()
        return "computer-use-preview" in name

    def is_codex(self) -> bool:
        name = self.service_model_name()
        return "codex" in name

    def is_gpt(self) -> bool:
        name = self.service_model_name()
        return "gpt" in name

    @override
    async def aclose(self) -> None:
        await self.client.close()

    @override
    def emulate_reasoning_history(self) -> bool:
        return not self.responses_api

    @override
    def supports_remote_mcp(self) -> bool:
        return True

    @override
    def tool_result_images(self) -> bool:
        # computer_use_preview supports tool calls returning images
        if self.is_computer_use_preview() or self.responses_api:
            return True
        else:
            return False

    @override
    def disable_computer_screenshot_truncation(self) -> bool:
        # Because ComputerCallOutput has a required output field of type
        # ResponseComputerToolCallOutputScreenshot, we must have an image in
        # order to provide a valid tool call response. Therefore, we cannot
        # support image truncation.
        return True

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # short-circuit to call o1- models that are text only
        if self.is_o1_early():
            return await generate_o1(
                client=self.client,
                input=input,
                tools=tools,
                **completion_params_completions(self, config, False),
            )

        use_responses = self.responses_api or is_native_tool_configured(
            tools, self.model_name, config
        )
        self._resolve_batcher(config, use_responses)

        # if reasoning summaries are unset then try to auto-detect
        if config.reasoning_summary is None:
            if not await self.reasoning_summaries():
                config = config.model_copy(update={"reasoning_summary": "none"})

        return await (
            generate_responses(
                client=self.client,
                http_hooks=self._http_hooks,
                model_name=self.service_model_name(),
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                background=self.background,
                service_tier=self.service_tier,
                prompt_cache_key=self.prompt_cache_key,
                prompt_cache_retention=self.prompt_cache_retention,
                safety_identifier=self.safety_identifier,
                responses_store=self.responses_store,
                model_info=self,
                batcher=self._responses_batcher,
            )
            if use_responses
            else generate_completions(
                client=self.client,
                http_hooks=self._http_hooks,
                model_name=self.service_model_name(),
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                prompt_cache_key=self.prompt_cache_key,
                prompt_cache_retention=self.prompt_cache_retention,
                safety_identifier=self.safety_identifier,
                openai_api=self,
                batcher=self._completions_batcher,
            )
        )

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup."""
        return f"openai/{self.service_model_name()}"

    @override
    def should_retry(self, ex: BaseException) -> bool:
        if isinstance(ex, RateLimitError):
            # Do not retry on these rate limit errors
            # The quota exceeded one is related to monthly account quotas.
            if "You exceeded your current quota" in ex.message:
                warn_once(logger, f"OpenAI quota exceeded, not retrying: {ex.message}")
                return False
            else:
                return True
        else:
            return openai_should_retry(ex)

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            return ex.status_code == 401
        return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    async def reasoning_summaries(self) -> bool:
        # validate that reasoning summaries are supported for this account
        # (needs to be a 'verified organization'). we do this by making a
        # simple request with reasoning summaries and if it succeeds we
        # set the reasoning_summaries bit (we do this once for the lifetime
        # of the model provider instance). use the lock to guard against
        # multiple samples doing this concurrently at startup
        async with self._reasoning_summaries_lock:
            if self._reasoning_summaries is None:
                reasoning_summaries = False
                if self.responses_api and self.has_reasoning_options():
                    try:
                        await self.client.responses.create(
                            model=self.service_model_name(),
                            input="Please say 'hello, world'",
                            reasoning={"effort": "low", "summary": "auto"},
                        )
                        reasoning_summaries = True
                    except Exception:
                        pass
                self._reasoning_summaries = reasoning_summaries

            return self._reasoning_summaries

    def _resolve_batcher(self, config: GenerateConfig, for_responses_api: bool) -> None:
        def _resolve_retry_config() -> ModelRetryConfig:
            return model_retry_config(
                self.model_name,
                config.max_retries,
                config.timeout,
                self.should_retry,
                lambda ex: None,
                log_model_retry,
            )

        # TODO: Bogus that we have to do this on each call. Ideally, it would be
        # done only once and ideally by non-provider specific code.
        batch_config = normalized_batch_config(config.batch)
        if batch_config:
            # Select the appropriate batcher based on API type
            if for_responses_api:
                if not self._responses_batcher:
                    self._responses_batcher = OpenAIBatcher(
                        self.client,
                        batch_config,
                        _resolve_retry_config(),
                        Response,
                        endpoint="/v1/responses",
                    )
            else:
                if not self._completions_batcher:
                    self._completions_batcher = OpenAIBatcher(
                        self.client,
                        batch_config,
                        _resolve_retry_config(),
                        ChatCompletion,
                        endpoint="/v1/chat/completions",
                    )

    def _supports_compaction(self) -> bool:
        """Check if this model supports native compaction."""
        info = get_model_info(self.canonical_name())
        return info is not None and info.native_compaction_supported is True

    @override
    async def compact(
        self,
        messages: list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        """Compact messages using client.responses.compact().

        Args:
            messages: The messages to compact.
            config: Optional generation config for reasoning parameters.

        Returns:
            A tuple of (compacted messages, usage info).

        Raises:
            NotImplementedError: If the model doesn't support native compaction.
        """
        if not self._supports_compaction():
            raise NotImplementedError(
                f"Native compaction not supported for {self.service_model_name()}"
            )

        # Convert messages to OpenAI format
        input_params = await openai_responses_inputs(messages, self)

        # Call compact endpoint (note: compact() doesn't accept reasoning params)
        response = await self.client.responses.compact(
            model=self.service_model_name(),
            input=input_params,
        )

        # Extract compaction item and create ChatMessage with ContentData
        compacted_messages = chat_messages_from_compact_response(
            response, model=self.service_model_name()
        )
        usage = model_usage_from_compact_response(response)

        return compacted_messages, usage

    def _get_reasoning_params_for_config(
        self, config: GenerateConfig | None
    ) -> Reasoning | None:
        """Get reasoning parameters from config for compact/count_tokens calls."""
        if not self.has_reasoning_options():
            return None

        # Use config settings if provided, otherwise use defaults
        if config is not None:
            reasoning: Reasoning = {}
            if config.reasoning_effort is not None:
                reasoning["effort"] = config.reasoning_effort
            # Only include summary if explicitly set and not disabled
            if (
                config.reasoning_summary is not None
                and config.reasoning_summary != "none"
            ):
                reasoning["summary"] = config.reasoning_summary
            return reasoning if reasoning else None

        # Default reasoning settings
        return {"effort": "medium", "summary": "auto"}
