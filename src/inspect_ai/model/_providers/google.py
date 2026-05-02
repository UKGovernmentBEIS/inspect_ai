import base64
import functools
import hashlib
import json
import os
from copy import copy
from io import BytesIO
from logging import getLogger
from textwrap import dedent
from typing import Any, Literal, NamedTuple, cast

# SDK Docs: https://googleapis.github.io/python-genai/
import anyio
import httpx
from google.genai import Client
from google.genai.errors import APIError, ClientError
from google.genai.types import (
    Candidate,
    CodeExecutionResult,
    Content,
    ContentListUnion,
    ContentListUnionDict,
    ContentUnion,
    ExecutableCode,
    File,
    FinishReason,
    FunctionCall,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    FunctionDeclaration,
    FunctionResponse,
    GenerateContentConfig,
    GenerateContentResponse,
    GenerateContentResponsePromptFeedback,
    GenerateContentResponseUsageMetadata,
    GoogleSearch,
    HarmBlockThreshold,
    HarmCategory,
    HttpOptions,
    Image,
    Language,
    Outcome,
    Part,
    SafetySetting,
    SafetySettingDict,
    ThinkingConfig,
    ThinkingLevel,
    Tool,
    ToolCodeExecution,
    ToolConfig,
    ToolListUnion,
)
from pydantic import JsonValue
from shortuuid import uuid
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentAudio,
    ContentData,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data
from inspect_ai._util.kvstore import inspect_kvstore
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Logprob,
    Logprobs,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._generate_config import has_image_output, normalized_batch_config
from inspect_ai.model._model import log_model_retry
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._providers._google_batch import GoogleBatcher, batch_request_dict
from inspect_ai.model._providers._google_citations import (
    distribute_citations_to_text_parts,
    get_candidate_citations,
)
from inspect_ai.model._providers._google_computer_use import (
    computer_tool_result_parts,
    gemini_action_from_tool_call,
    maybe_computer_use_tool,
    tool_call_from_gemini_computer_action,
)
from inspect_ai.model._reasoning import reasoning_to_think_tag
from inspect_ai.model._retry import model_retry_config
from inspect_ai.tool import (
    ToolCall,
    ToolChoice,
    ToolFunction,
    ToolInfo,
)
from inspect_ai.util._json import json_schema_dump

from .util import model_base_url
from .util.hooks import HttpHooks, HttpxHooks

logger = getLogger(__name__)


GOOGLE_API_KEY = "GOOGLE_API_KEY"
VERTEX_API_KEY = "VERTEX_API_KEY"

SAFETY_SETTINGS = "safety_settings"
DEFAULT_SAFETY_SETTINGS: list[SafetySettingDict] = [
    {
        "category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
]


class CategorizedTools(NamedTuple):
    google_search: GoogleSearch | None
    code_execution: ToolCodeExecution | None
    computer_use: Tool | None
    function_declarations: list[FunctionDeclaration]


class GoogleGenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        config: GenerateConfig = GenerateConfig(),
        api_version: str | None = None,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOOGLE_API_KEY, VERTEX_API_KEY],
            config=config,
        )

        # record api version
        self.api_version = api_version

        # record streaming preference
        self.streaming = bool(model_args.pop("streaming", False))

        # pick out user-provided safety settings and merge against default
        self.safety_settings: list[SafetySettingDict] = DEFAULT_SAFETY_SETTINGS.copy()
        if SAFETY_SETTINGS in model_args:

            def update_safety_setting(
                category: HarmCategory, threshold: HarmBlockThreshold
            ) -> None:
                for setting in self.safety_settings:
                    if setting["category"] == category:
                        setting["threshold"] = threshold
                        break

            user_safety_settings = parse_safety_settings(
                model_args.get(SAFETY_SETTINGS)
            )
            for safety_setting in user_safety_settings:
                if safety_setting["category"] and safety_setting["threshold"]:
                    update_safety_setting(
                        safety_setting["category"], safety_setting["threshold"]
                    )

            del model_args[SAFETY_SETTINGS]

        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # vertex can also be forced by the GOOGLE_GENAI_USE_VERTEX_AI flag
        if self.service is None:
            if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
                self.service = "vertex"

        # ensure we haven't specified an invalid service
        if self.service is not None and self.service != "vertex":
            raise RuntimeError(
                f"Invalid service name for google: {self.service}. "
                + "Currently 'vertex' is the only supported service."
            )

        # handle auth (vertex or standard google api key)
        if self.is_vertex():
            # see if we are running in express mode (propagate api key if we are)
            # https://cloud.google.com/vertex-ai/generative-ai/docs/start/express-mode/overview
            vertex_api_key = os.environ.get(VERTEX_API_KEY, None)
            if vertex_api_key and not self.api_key:
                self.api_key = vertex_api_key

            # When not using express mode the GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION
            # environment variables should be set, OR the 'project' and 'location' should be
            # passed within the model_args.
            # https://cloud.google.com/vertex-ai/generative-ai/docs/gemini-v2
            if not vertex_api_key:
                if not os.environ.get(
                    "GOOGLE_CLOUD_PROJECT", None
                ) and not model_args.get("project", None):
                    raise PrerequisiteError(
                        "Google provider requires either the GOOGLE_CLOUD_PROJECT environment variable "
                        + "or the 'project' custom model arg (-M) when running against vertex."
                    )
                if not os.environ.get(
                    "GOOGLE_CLOUD_LOCATION", None
                ) and not model_args.get("location", None):
                    raise PrerequisiteError(
                        "Google provider requires either the GOOGLE_CLOUD_LOCATION environment variable "
                        + "or the 'location' custom model arg (-M) when running against vertex."
                    )

            # custom base_url
            self.base_url = model_base_url(
                self.base_url, ["GOOGLE_VERTEX_BASE_URL", "VERTEX_BASE_URL"]
            )

        # normal google endpoint
        else:
            # read api key from env
            if not self.api_key:
                self.api_key = os.environ.get(GOOGLE_API_KEY, None)

            # custom base_url
            self.base_url = model_base_url(self.base_url, "GOOGLE_BASE_URL")

        # save model args
        self.model_args = model_args

        # initialize batcher
        self._batcher: GoogleBatcher | None = None

    def is_vertex(self) -> bool:
        return self.service == "vertex"

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # http options
        http_options = HttpOptions(
            base_url=self.base_url,
            api_version=self.api_version,
        )

        # apply timeout if specified
        if config.timeout:
            http_options.timeout = config.timeout * 1000

        # resolve batcher as required
        self._resolve_batcher(config, http_options)

        # create client and manage its lifetime to this call
        client = self.model_client(http_options)
        async with client.aio:
            # create hooks and allocate request
            async_httpx_client = client._api_client._async_httpx_client
            if async_httpx_client is not None:
                http_hooks: HttpHooks = HttpxHooks(async_httpx_client)
            else:
                http_hooks = HttpHooks()
            request_id = http_hooks.start_request()

            # Create google-genai types.
            gemini_contents = await as_chat_messages(
                client, input, emulate_reasoning=not self.is_gemini_thinking()
            )
            has_native_tools, gemini_tools = (
                self.chat_tools(tools) if len(tools) > 0 else (False, None)
            )
            if gemini_native_tool_combination(gemini_tools):
                gemini_tool_config = gemini_native_tool_combination_config(tool_choice)
            elif not has_native_tools and len(tools) > 0:
                gemini_tool_config = chat_tool_config(tool_choice)
            else:
                gemini_tool_config = None
            system_instruction = await extract_system_message_as_parts(
                client, input, tools, include_function_calling_hint=not has_native_tools
            )
            # Map modalities to Google's response_modalities
            response_modalities = None
            if config.modalities:
                if has_image_output(config.modalities):
                    response_modalities = ["TEXT", "IMAGE"]
                else:
                    raise PrerequisiteError(
                        f"Unsupported modalities for Google: {config.modalities}"
                    )

            parameters = GenerateContentConfig(
                http_options=HttpOptions(
                    headers={HttpHooks.REQUEST_ID_HEADER: request_id}
                    | (config.extra_headers or {})
                ),
                temperature=config.temperature,
                top_p=config.top_p,
                top_k=config.top_k,
                max_output_tokens=config.max_tokens,
                stop_sequences=config.stop_seqs,
                candidate_count=config.num_choices,
                presence_penalty=config.presence_penalty,
                frequency_penalty=config.frequency_penalty,
                response_logprobs=config.logprobs,
                logprobs=config.top_logprobs,
                safety_settings=safety_settings_to_list(self.safety_settings),
                tools=gemini_tools,
                tool_config=gemini_tool_config,
                system_instruction=system_instruction,  # type: ignore[arg-type]
                thinking_config=self.chat_thinking_config(config),
                response_modalities=response_modalities,
            )
            if config.response_schema is not None:
                parameters.response_mime_type = "application/json"
                parameters.response_json_schema = json_schema_dump(
                    config.response_schema.json_schema
                )

            model_call = start_model_call(
                contents=gemini_contents,  # type: ignore[arg-type]
                safety_settings=self.safety_settings,
                generation_config=parameters,
                tools=gemini_tools,
                tool_config=gemini_tool_config,
                system_instruction=system_instruction,
            )

            response: GenerateContentResponse | None = None

            try:
                # google sometimes requires retries for malformed function calls
                # (see https://github.com/googleapis/python-genai/issues/430#issuecomment-3592369131)
                tool_calling_attempts = 0
                while tool_calling_attempts < 3:
                    if self._batcher:
                        response = await self._batcher.generate_for_request(
                            batch_request_dict(parameters, gemini_contents)
                        )
                    elif self.streaming:
                        response = await self._stream_generate_content(
                            client=client,
                            model=self.service_model_name(),
                            contents=gemini_contents,  # type: ignore[arg-type]
                            config=parameters,
                        )
                    else:
                        response = await client.aio.models.generate_content(
                            model=self.service_model_name(),
                            contents=gemini_contents,  # type: ignore[arg-type]
                            config=parameters,
                        )
                    # retry for MALFORMED_FUNCTION_CALL
                    if (
                        response.candidates
                        and response.candidates[0].finish_reason
                        == FinishReason.MALFORMED_FUNCTION_CALL
                        and not has_native_tools
                    ):
                        # tick retries
                        tool_calling_attempts += 1

                        # apply retry context
                        retry_contents, retry_tool_config = _malformed_function_retry(
                            response, tool_choice
                        )
                        gemini_contents.extend(retry_contents)
                        if retry_tool_config is not None:
                            parameters.tool_config = retry_tool_config

                    # otherwise we are done
                    else:
                        break
            except ClientError as ex:
                model_call.set_error(
                    {"error": {"message": str(ex.message), "code": ex.code}},
                    http_hooks.end_request(request_id),
                )
                return self.handle_client_error(ex), model_call

            assert response is not None  # mypy confused by retry loop

            model_call.set_response(response, http_hooks.end_request(request_id))

            model_name = response.model_version or self.service_model_name()
            has_computer_use = gemini_tools is not None and any(
                isinstance(tool, Tool) and tool.computer_use is not None
                for tool in gemini_tools
            )
            output = ModelOutput(
                model=model_name,
                choices=completion_choices_from_candidates(
                    model_name, response, has_computer_use
                ),
                usage=usage_metadata_to_model_usage(response.usage_metadata),
            )

            return output, model_call

    async def _stream_generate_content(
        self,
        client: Client,
        model: str,
        contents: list[ContentUnion],
        config: GenerateContentConfig,
    ) -> GenerateContentResponse:
        """Stream content generation and accumulate response.

        Accumulates parts from streaming chunks and constructs a response
        that matches non-streaming structure, allowing existing parsing logic
        to handle the conversion to Inspect format.

        Raises:
            RuntimeError: If no chunks received from stream
        """
        candidates_parts: dict[int, list[Part]] = {}
        last_chunk: GenerateContentResponse | None = None

        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )

        async for chunk in stream:
            last_chunk = chunk
            if chunk.candidates:
                for candidate in chunk.candidates:
                    if candidate.index is None:
                        continue

                    idx = candidate.index
                    if idx not in candidates_parts:
                        candidates_parts[idx] = []

                    if candidate.content and candidate.content.parts:
                        candidates_parts[idx].extend(candidate.content.parts)

        if last_chunk is None:
            raise RuntimeError(
                f"No response chunks received from streaming API for model {model}"
            )

        final_candidates = []
        for idx in sorted(candidates_parts.keys()):
            accumulated_parts = candidates_parts[idx]

            merged_parts: list[Part] = []
            thinking_texts: list[str] = []
            output_texts: list[str] = []

            for part in accumulated_parts:
                if part.thought_signature:
                    if thinking_texts:
                        merged_parts.append(
                            Part(thought=True, text="".join(thinking_texts))
                        )
                        thinking_texts = []

                    if part.text:
                        combined_text = "".join(output_texts) + part.text
                        merged_parts.append(
                            Part(
                                thought_signature=part.thought_signature,
                                text=combined_text,
                            )
                        )
                        output_texts = []
                    elif part.function_call or part.executable_code:
                        if output_texts:
                            merged_parts.append(Part(text="".join(output_texts)))
                            output_texts = []

                        if part.function_call:
                            merged_parts.append(
                                Part(
                                    thought_signature=part.thought_signature,
                                    function_call=part.function_call,
                                )
                            )
                        elif part.executable_code:
                            merged_parts.append(
                                Part(
                                    thought_signature=part.thought_signature,
                                    executable_code=part.executable_code,
                                )
                            )
                    else:
                        if output_texts:
                            merged_parts.append(
                                Part(
                                    thought_signature=part.thought_signature,
                                    text="".join(output_texts),
                                )
                            )
                            output_texts = []

                elif part.thought is True and part.text:
                    if output_texts:
                        merged_parts.append(Part(text="".join(output_texts)))
                        output_texts = []
                    thinking_texts.append(part.text)
                elif part.text:
                    if thinking_texts:
                        merged_parts.append(
                            Part(thought=True, text="".join(thinking_texts))
                        )
                        thinking_texts = []
                    output_texts.append(part.text)
                else:
                    if thinking_texts:
                        merged_parts.append(
                            Part(thought=True, text="".join(thinking_texts))
                        )
                        thinking_texts = []
                    if output_texts:
                        merged_parts.append(Part(text="".join(output_texts)))
                        output_texts = []
                    merged_parts.append(part)

            if thinking_texts:
                merged_parts.append(Part(thought=True, text="".join(thinking_texts)))
            if output_texts:
                merged_parts.append(Part(text="".join(output_texts)))

            last_candidate_for_idx = None
            if last_chunk.candidates:
                for c in last_chunk.candidates:
                    if c.index == idx:
                        last_candidate_for_idx = c
                        break

            if last_candidate_for_idx:
                final_candidates.append(
                    Candidate(
                        content=Content(parts=merged_parts, role="model"),
                        finish_reason=last_candidate_for_idx.finish_reason,
                        safety_ratings=last_candidate_for_idx.safety_ratings,
                        citation_metadata=last_candidate_for_idx.citation_metadata,
                        token_count=last_candidate_for_idx.token_count,
                        grounding_metadata=last_candidate_for_idx.grounding_metadata,
                        avg_logprobs=last_candidate_for_idx.avg_logprobs,
                        index=idx,
                    )
                )

        return GenerateContentResponse(
            candidates=final_candidates,
            usage_metadata=last_chunk.usage_metadata,
            model_version=last_chunk.model_version,
        )

    @override
    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        client = self.model_client()
        async with client.aio:
            # normalize to messages
            if isinstance(input, str):
                input = [ChatMessageUser(content=input)]

            # turn system into user for purposes of counting
            count_messages = [
                ChatMessageUser(content=m.content)
                if isinstance(m, ChatMessageSystem)
                else m
                for m in input
            ]
            contents: list[ContentUnion] = [
                await content(
                    client, m, emulate_reasoning=not self.is_gemini_thinking()
                )
                for m in count_messages
            ]
            response = await client.aio.models.count_tokens(
                model=self.service_model_name(), contents=contents
            )
            if response.total_tokens is not None:
                return response.total_tokens
            else:
                logger.warning("Gemini token count returned None")
                return await super().count_tokens(input, config)

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup."""
        return f"google/{self.service_model_name()}"

    def is_gemini(self) -> bool:
        return "gemini-" in self.service_model_name()

    def is_gemini_flash(self) -> bool:
        return "flash" in self.service_model_name()

    def is_gemini_1_5(self) -> bool:
        return "gemini-1.5" in self.service_model_name()

    def is_gemini_2_0(self) -> bool:
        return "gemini-2.0" in self.service_model_name()

    def is_gemini_2_5(self) -> bool:
        return "gemini-2.5" in self.service_model_name()

    def is_gemini_3(self) -> bool:
        return "gemini-3" in self.service_model_name()

    def is_gemini_3_flash(self) -> bool:
        return self.is_gemini_3() and self.is_gemini_flash()

    def is_gemini_3_plus(self) -> bool:
        return (
            self.is_gemini()
            and not self.is_gemini_1_5()
            and not self.is_gemini_2_0()
            and not self.is_gemini_2_5()
        )

    def is_gemini_thinking(self) -> bool:
        return not self.is_gemini_1_5() and not self.is_gemini_2_0()

    def is_gemini_thinking_only(self) -> bool:
        return (
            self.is_gemini_2_5() or self.is_gemini_3()
        ) and "-pro" in self.service_model_name()

    @override
    def should_retry(self, ex: BaseException) -> bool:
        if isinstance(ex, APIError) and ex.code is not None:
            return is_retryable_http_status(ex.code)
        else:
            return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections."""
        return str(self.api_key)

    @override
    def tool_result_images(self) -> bool:
        return True

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, APIError):
            return ex.code == 401
        return False

    def model_client(self, http_options: HttpOptions | None = None) -> Client:
        from inspect_ai._util._async import current_async_backend

        http_options = http_options or HttpOptions(
            base_url=self.base_url,
            api_version=self.api_version,
        )
        # aiohttp requires asyncio; use httpx under trio for compatibility
        if (
            current_async_backend() == "trio"
            and http_options.httpx_async_client is None
        ):
            http_options.httpx_async_client = httpx.AsyncClient()
        return Client(
            vertexai=self.is_vertex(),
            api_key=self.api_key,
            http_options=http_options,
            **self.model_args,
        )

    def handle_client_error(self, ex: ClientError) -> ModelOutput | Exception:
        # exceeding a quota with a limit of 0 means no access to model or capability,
        # for these cases convert to a runtime error so the sample fails.
        if (
            ex.code == 429
            and ex.message
            and "quota" in ex.message
            and "limit: 0" in ex.message
        ):
            return RuntimeError(ex.message)

        # detect context overflow and convert to ModelOutput
        if (
            ex.code == 400
            and ex.message
            and (
                "maximum number of tokens" in ex.message
                or "size exceeds the limit" in ex.message
            )
        ):
            return ModelOutput.from_content(
                self.service_model_name(),
                content=ex.message,
                stop_reason="model_length",
            )
        elif ex.code == 400:
            return ex
        else:
            raise ex

    def chat_thinking_config(self, config: GenerateConfig) -> ThinkingConfig | None:
        # thinking_config is only supported for gemini 2.5 above
        has_thinking_config = (
            self.is_gemini() and not self.is_gemini_1_5() and not self.is_gemini_2_0()
        )
        if has_thinking_config:
            # user is attempting to turn off reasoning, this only works for some models
            # so we warn for those models where it can't be done.
            if config.reasoning_tokens == 0 or config.reasoning_effort == "none":
                if self.is_gemini_thinking_only():
                    # When reasoning_tokens is set to 0 and it's a thinking only model we don't
                    # bother trying to shut down thinking as this is not possible:
                    #   https://ai.google.dev/gemini-api/docs/thinking#set-budget
                    # warn and return include_thoughts=True so the user sees what is happening
                    warn_once(
                        logger,
                        f"Thinking cannot be disabled for model {self.service_model_name()}.",
                    )
                    return ThinkingConfig(include_thoughts=True)
                else:
                    # otherwise do the disable
                    return ThinkingConfig(include_thoughts=False, thinking_budget=0)

            # thinking_level is now the preferred way of setting reasoning (thinking_budget is deprecated)
            # consult it first for gemini 3+ models, otherwise fall through to tokens for other models
            elif config.reasoning_effort is not None and self.is_gemini_3_plus():
                # note: minimal and medium currently only supported by flash model
                is_flash = self.is_gemini_3_flash()
                match config.reasoning_effort:
                    case "minimal":
                        thinking_level = (
                            ThinkingLevel.MINIMAL if is_flash else ThinkingLevel.LOW
                        )
                    case "low":
                        thinking_level = ThinkingLevel.LOW
                    case "medium":
                        thinking_level = (
                            ThinkingLevel.MEDIUM if is_flash else ThinkingLevel.HIGH
                        )
                    case "high" | "xhigh" | "max":
                        thinking_level = ThinkingLevel.HIGH
                    case _:
                        thinking_level = None  # can't happen, keep mypy happy
                return ThinkingConfig(
                    include_thoughts=True, thinking_level=thinking_level
                )

            # enable thinking_budget if specified
            elif config.reasoning_tokens is not None:
                return ThinkingConfig(
                    include_thoughts=True, thinking_budget=config.reasoning_tokens
                )

            # generic thinking with defaults
            else:
                return ThinkingConfig(include_thoughts=True)
        else:
            return None

    def _use_native_search(self, tool: ToolInfo) -> bool:
        return (
            tool.name == "web_search"
            and tool.options is not None
            and "gemini" in tool.options
            # Support "starts with" Gemini 2.0
            and (self.is_gemini() and not self.is_gemini_1_5())
        )

    def _use_native_code_execution(self, tool: ToolInfo) -> bool:
        return (
            tool.name == "code_execution"
            and tool.options is not None
            and "google" in tool.options.get("providers", {})
            # Support "starts with" Gemini 2.0
            and (self.is_gemini() and not self.is_gemini_1_5())
        )

    def _categorize_tool(
        self,
        acc: CategorizedTools,
        tool: ToolInfo,
    ) -> CategorizedTools:
        """Reducer function that categorizes tools into native search vs function declarations.

        Returns:
            Tuple of (has_native_search, function_declarations) where has_native_search
            is True if any tool uses native search, and function_declarations contains
            all non-native-search tools converted to FunctionDeclaration objects.
        """
        if tool.options and self._use_native_search(tool):
            return acc._replace(google_search=self._google_search_options(tool.options))
        elif tool.options and self._use_native_code_execution(tool):
            return acc._replace(code_execution=ToolCodeExecution())
        else:
            computer_use = maybe_computer_use_tool(self.model_name, tool)
            if computer_use is not None:
                return acc._replace(computer_use=computer_use)
            else:
                return acc._replace(
                    function_declarations=acc.function_declarations
                    + [
                        FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=json_schema_dump(tool.parameters)
                            if len(tool.parameters.properties) > 0
                            else None,
                        )
                    ],
                )

    def _google_search_options(self, options: dict[str, Any]) -> GoogleSearch:
        gemini_options = options.get("gemini", None)
        if isinstance(gemini_options, dict):
            return GoogleSearch.model_validate(gemini_options)
        else:
            return GoogleSearch()

    def chat_tools(self, tools: list[ToolInfo]) -> tuple[bool, ToolListUnion]:
        # categorize tools into native tools vs function declarations
        google_search, code_execution, computer_use, function_declarations = (
            functools.reduce(
                self._categorize_tool,
                tools,
                CategorizedTools(
                    google_search=None,
                    code_execution=None,
                    computer_use=None,
                    function_declarations=[],
                ),
            )
        )

        # native search/code execution tools
        if google_search or code_execution:
            if function_declarations:
                if not self.is_gemini_3_plus():
                    raise ValueError(
                        f"Combining native web search or code execution with custom function tools requires Gemini 3 or later. The model '{self.model_name}' does not support this combination."
                    )
                combined_native_tools: ToolListUnion = [
                    Tool(function_declarations=function_declarations)
                ]
                if google_search:
                    combined_native_tools.append(Tool(google_search=google_search))
                if code_execution:
                    combined_native_tools.append(Tool(code_execution=code_execution))
                return (
                    True,
                    combined_native_tools,
                )
            native_tools: ToolListUnion = []
            if google_search:
                native_tools.append(Tool(google_search=google_search))
            if code_execution:
                native_tools.append(Tool(code_execution=code_execution))
            return (True, native_tools)

        # computer use (can coexist with function declarations)
        if computer_use is not None:
            native_tools = [computer_use]
            if function_declarations:
                native_tools.append(Tool(function_declarations=function_declarations))
            return (True, native_tools)

        # client tools only
        return (False, [Tool(function_declarations=function_declarations)])

    def _resolve_batcher(
        self, config: GenerateConfig, http_options: HttpOptions
    ) -> None:
        if self._batcher or not (batch_config := normalized_batch_config(config.batch)):
            return

        # verify we aren't trying to use the batcher with vertex
        if self.is_vertex():
            raise NotImplementedError(
                "Cannot use batch inference with Vertex AI (GCS-based batch jobs not supported)"
            )

        # create a dedicated client instance for the batcher
        client = Client(
            vertexai=self.is_vertex(),
            api_key=self.api_key,
            http_options=http_options,
            **self.model_args,
        )

        self._batcher = GoogleBatcher(
            client,
            batch_config,
            model_retry_config(
                self.model_name,
                config.max_retries,
                config.timeout,
                self.should_retry,
                lambda ex: None,
                log_model_retry,
            ),
            self.service_model_name(),
        )


def safety_settings_to_list(
    safety_settings: list[SafetySettingDict],
) -> list[SafetySetting]:
    settings: list[SafetySetting] = []
    for setting in safety_settings:
        settings.append(
            SafetySetting(category=setting["category"], threshold=setting["threshold"])
        )
    return settings


def start_model_call(
    contents: ContentListUnion | ContentListUnionDict,
    generation_config: GenerateContentConfig,
    safety_settings: list[SafetySettingDict],
    tools: ToolListUnion | None,
    tool_config: ToolConfig | None,
    system_instruction: list[File | Part | Image | str] | None,
) -> ModelCall:
    return set_active_model_event_call(
        request=dict(
            contents=contents,
            # the excluded fields are passed to the Python API as part of
            # GenerateContentConfig however they are passed separately in
            # the actual http request body, so reflect that here
            generation_config=generation_config.model_copy(
                update={
                    "safety_settings": None,
                    "tools": None,
                    "tool_config": None,
                    "system_instruction": None,
                }
            ),
            safety_settings=safety_settings,
            tools=tools if tools is not None else None,
            tool_config=tool_config if tool_config is not None else None,
            system_instruction=system_instruction,
        ),
        filter=model_call_filter,
    )


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    if key == "inline_data" and isinstance(value, dict) and "data" in value:
        value = copy(value)
        value.update(data=BASE_64_DATA_REMOVED)
    return value


async def as_chat_messages(
    client: Client, messages: list[ChatMessage], emulate_reasoning: bool = False
) -> list[Content]:
    # There is no "system" role in the `google-genai` package. Instead, system messages
    # are included in the `GenerateContentConfig` as a `system_instruction`. Strip any
    # system messages out.
    supported_messages = [message for message in messages if message.role != "system"]

    # build google chat messages
    chat_messages = [
        await content(client, message, emulate_reasoning)
        for message in supported_messages
    ]

    # combine consecutive tool messages
    chat_messages = functools.reduce(
        consecutive_tool_message_reducer, chat_messages, []
    )

    # return messages
    return chat_messages


def consecutive_tool_message_reducer(
    messages: list[Content],
    message: Content,
) -> list[Content]:
    if is_tool_message(message) and len(messages) > 0 and is_tool_message(messages[-1]):
        messages[-1] = Content(
            role="user", parts=(messages[-1].parts or []) + (message.parts or [])
        )
    else:
        messages.append(message)
    return messages


def is_tool_message(message: Content) -> bool:
    return (
        message.role == "user"
        and message.parts is not None
        and len(message.parts) > 0
        and message.parts[0].function_response is not None
    )


async def content(
    client: Client,
    message: ChatMessageUser | ChatMessageAssistant | ChatMessageTool,
    emulate_reasoning: bool = False,
) -> Content:
    working_reasoning_block = None
    if isinstance(message, ChatMessageUser):
        if isinstance(message.content, str):
            return Content(
                role="user", parts=[await content_part(client, message.content)]
            )
        return Content(
            role="user",
            parts=(
                [await content_part(client, content) for content in message.content]
            ),
        )
    elif isinstance(message, ChatMessageAssistant):
        content_parts: list[Part] = []
        emitted_tool_call_ids: set[str] = set()
        server_tool_signature: bytes | None = None

        def part_from_tool_call(tool_call: ToolCall) -> Part:
            if tool_call.function == "computer":
                action_name = (
                    tool_call.id.rsplit("_", 1)[0] if tool_call.id else "computer"
                )
                _, action_args = gemini_action_from_tool_call(tool_call)
                return Part(
                    function_call=FunctionCall(
                        id=tool_call.id,
                        name=action_name,
                        args=action_args,
                    )
                )
            else:
                return Part(
                    function_call=FunctionCall(
                        id=tool_call.id,
                        name=tool_call.function,
                        args=tool_call.arguments,
                    )
                )

        def apply_reasoning_signature(
            part: Part, reasoning_block: ContentReasoning
        ) -> None:
            if reasoning_block.reasoning is not None and reasoning_block.redacted:
                part.thought_signature = base64.b64decode(
                    reasoning_block.reasoning.encode()
                )
            else:
                logger.warning(
                    "Reasoning block must have a reasoning signature to set thought_signature."
                )

        if isinstance(message.content, str):
            content_parts.append(Part(text=message.content or NO_CONTENT))
        else:
            for i, content in enumerate(message.content):
                if isinstance(content, ContentReasoning):
                    if emulate_reasoning:
                        content_parts.append(Part(text=reasoning_to_think_tag(content)))
                    else:
                        # if this is encrypted reasoning, save it for applying the thought_signature
                        # to the next part (don't emit a separate thought part during replay)
                        if content.redacted:
                            function_call_id = (
                                content.internal.get("gemini_function_call_id")
                                if isinstance(content.internal, dict)
                                else None
                            )
                            if (
                                isinstance(function_call_id, str)
                                and message.tool_calls is not None
                            ):
                                tool_call = next(
                                    (
                                        tool_call
                                        for tool_call in message.tool_calls
                                        if tool_call.id == function_call_id
                                    ),
                                    None,
                                )
                                if tool_call is not None:
                                    part = part_from_tool_call(tool_call)
                                    apply_reasoning_signature(part, content)
                                    content_parts.append(part)
                                    emitted_tool_call_ids.add(tool_call.id)
                                    working_reasoning_block = None
                                    continue
                            working_reasoning_block = content
                        else:
                            # unencrypted reasoning (for older models or debugging)
                            content_parts.append(
                                Part(text=content.reasoning, thought=True)
                            )

                else:
                    # server side tool use
                    if isinstance(content, ContentToolUse):
                        parts_to_append = parts_from_server_tool_use(content)
                        if (
                            message.tool_calls is not None
                            and server_tool_signature is None
                        ):
                            server_tool_signature = next(
                                (
                                    part.thought_signature
                                    for part in parts_to_append
                                    if part.thought_signature is not None
                                ),
                                None,
                            )

                    # other content
                    else:
                        parts_to_append = [await content_part(client, content)]

                    if not parts_to_append:
                        continue

                    # If previously there was a reasoning block, we need to set the "thought_signature"
                    # using the reasoning from that block.
                    # However, if there are tool calls in this message, the signature should go on
                    # the first tool call instead, not on text or server tool use parts
                    # (per Gemini API docs).
                    if (
                        working_reasoning_block is not None
                        and message.tool_calls is None
                    ):
                        if (
                            working_reasoning_block.reasoning is not None
                            and working_reasoning_block.redacted
                        ):
                            parts_to_append[0].thought_signature = base64.b64decode(
                                working_reasoning_block.reasoning.encode()
                            )
                        else:
                            logger.warning(
                                "Reasoning block must have a reasoning signature to set thought_signature."
                            )
                        # Now, reset the previous reasoning block.
                        working_reasoning_block = None
                    content_parts.extend(parts_to_append)

        # Now handle tool calls
        if message.tool_calls is not None:
            # Per Gemini API docs: thought_signature goes on the first tool call in a message.
            # For parallel function calls, only the first FC gets the signature.
            # For sequential function calls (multi-step), each step is a separate message,
            # so each will have its own reasoning block and signature.
            # The loop below applies the signature to the first tool call (when working_reasoning_block
            # is not None), then clears it so subsequent tool calls don't get it.
            for tool_call in message.tool_calls:
                if tool_call.id in emitted_tool_call_ids:
                    continue

                part = part_from_tool_call(tool_call)

                # handle reasoning block if available
                if working_reasoning_block is not None:
                    # tool call reasoning should always use a thought_signature
                    apply_reasoning_signature(part, working_reasoning_block)
                    working_reasoning_block = None
                elif server_tool_signature is not None:
                    # Gemini can omit a signature on a client function_call when
                    # the same step also includes signed server-side tool calls.
                    # On replay, Gemini still validates the client function_call,
                    # so use the step's server-side signature for the first
                    # unsigned client function_call.
                    part.thought_signature = server_tool_signature
                    server_tool_signature = None

                content_parts.append(part)
        return Content(role="model", parts=content_parts)

    elif isinstance(message, ChatMessageTool):
        content_text = (
            message.error.message if message.error is not None else message.text
        )
        response_dict: dict[str, object] = {
            "content": content_text,
            "safety_acknowledgement": "true",
        }
        if message.function == "computer":
            response_dict["url"] = ""
            response_name = (
                message.tool_call_id.rsplit("_", 1)[0]
                if message.tool_call_id
                else "computer"
            )
            # Computer-use models support multimodal function responses.
            fn_response_parts = await computer_tool_result_parts(message)
        else:
            response_name = message.function or ""
            fn_response_parts = None
        response = FunctionResponse(
            id=message.tool_call_id,
            name=response_name,
            response=response_dict,
            parts=fn_response_parts,
        )
        parts: list[Part] = [Part(function_response=response)]
        # For non-computer tools, include images as sibling content parts
        # since most models don't support multimodal function responses.
        if message.function != "computer" and isinstance(message.content, list):
            for item in message.content:
                if isinstance(item, ContentImage):
                    parts.append(await content_part(client, item))
        return Content(role="user", parts=parts)


async def content_part(client: Client, content: InspectContent | str) -> Part:
    if isinstance(content, str):
        return Part.from_text(text=content or NO_CONTENT)
    elif isinstance(content, ContentText):
        return Part.from_text(text=content.text or NO_CONTENT)
    elif isinstance(content, ContentReasoning):
        raise RuntimeError("content_part should never encounter ContentReasoning")
    elif isinstance(content, ContentData):
        raise RuntimeError("Google provider should never encounter ContentData")
    elif isinstance(content, ContentToolUse):
        raise RuntimeError("Google provider should never encounter ContentToolUse")
    else:
        return await chat_content_to_part(client, content)


async def chat_content_to_part(
    client: Client,
    content: ContentImage | ContentAudio | ContentVideo | ContentDocument,
) -> Part:
    if isinstance(content, ContentImage):
        content_bytes, mime_type = await file_as_data(content.image)
        return Part.from_bytes(mime_type=mime_type, data=content_bytes)
    else:
        file = await file_for_content(client, content)
        if file.uri is None:
            raise RuntimeError(f"Failed to get URI for file: {file.display_name}")
        return Part.from_uri(file_uri=file.uri, mime_type=file.mime_type)


async def extract_system_message_as_parts(
    client: Client,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    include_function_calling_hint: bool = True,
) -> list[File | Part | Image | str] | None:
    system_parts: list[File | Part | Image | str] = []
    for message in messages:
        if message.role == "system":
            content = message.content
            if isinstance(content, str):
                system_parts.append(Part.from_text(text=content))
            elif isinstance(content, list):  # list[InspectContent]
                system_parts.extend(
                    [await content_part(client, content) for content in content]
                )
            else:
                raise ValueError(f"Unsupported system message content: {content}")

    # if there are function declaration tools then inject a hint to prevent
    # MALFORMED_FUNCTION_CALL. skipped for native-only tools (e.g. code execution)
    # as sending it causes FAILED_PRECONDITION from the API.
    # (see https://github.com/googleapis/python-genai/issues/430#issuecomment-3592369131)
    if len(tools) > 0 and include_function_calling_hint:
        system_parts.append(
            Part(
                text=dedent("""
                ## Function Calling
                - Do not generate code. Always generate the function call json
                When calling functions, output the function name exactly as defined. Do not prepend 'default_api.' or any other namespace to the function name
                """)
            )
        )

    # if every part is text then return list[str] rather than list[Part]
    # works around issue w/ open-telemetry not expecting parts
    if system_parts:
        text_parts: list[File | Part | Image | str] = []
        for p in system_parts:
            if isinstance(p, str):
                text_parts.append(p)
            elif isinstance(p, Part) and p.text is not None:
                text_parts.append(p.text)
            else:
                break

        if len(text_parts) == len(system_parts):
            return text_parts
        else:
            return system_parts

    else:
        # google-genai raises "ValueError: content is required." if the list is empty.
        return None


def chat_tool_config(tool_choice: ToolChoice) -> ToolConfig:
    if isinstance(tool_choice, ToolFunction):
        return ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfigMode.ANY,
                allowed_function_names=[tool_choice.name],
            )
        )
    else:
        return ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=cast(FunctionCallingConfigMode, tool_choice.upper())
            )
        )


def gemini_native_tool_combination(tools: ToolListUnion | None) -> bool:
    """Check whether Gemini tools combine function declarations and native tools."""
    if tools is None:
        return False
    has_function_declarations = any(
        isinstance(tool, Tool) and bool(tool.function_declarations) for tool in tools
    )
    has_builtin_tool = any(
        isinstance(tool, Tool)
        and (tool.google_search is not None or tool.code_execution is not None)
        for tool in tools
    )
    return has_function_declarations and has_builtin_tool


def gemini_native_tool_combination_config(tool_choice: ToolChoice) -> ToolConfig:
    """Build ToolConfig for Gemini 3 native tools plus function declarations."""
    if isinstance(tool_choice, ToolFunction):
        function_calling_config = FunctionCallingConfig(
            mode=FunctionCallingConfigMode.ANY,
            allowed_function_names=[tool_choice.name],
        )
    else:
        # Gemini 3 requires VALIDATED rather than AUTO when a request combines
        # native server-side tools with custom function declarations.
        function_calling_config = FunctionCallingConfig(
            mode=(
                FunctionCallingConfigMode.VALIDATED
                if tool_choice == "auto"
                else cast(FunctionCallingConfigMode, tool_choice.upper())
            )
        )
    return ToolConfig(
        include_server_side_tool_invocations=True,
        function_calling_config=function_calling_config,
    )


def _consolidate_thought_signature(
    signature: bytes,
    working_reasoning_block: ContentReasoning | None,
    content: list[
        ContentText
        | ContentReasoning
        | ContentImage
        | ContentToolUse
        | ContentAudio
        | ContentVideo
        | ContentData
        | ContentDocument
    ],
) -> ContentReasoning | None:
    """Consolidate a thought_signature into the working reasoning block or create a new one.

    Returns the updated working_reasoning_block (None after consolidation).
    """
    if working_reasoning_block is None:
        content.append(
            ContentReasoning(
                reasoning=base64.b64encode(signature).decode(),
                redacted=True,
            )
        )
    else:
        working_reasoning_block.summary = working_reasoning_block.reasoning
        working_reasoning_block.reasoning = base64.b64encode(signature).decode()
        working_reasoning_block.redacted = True
    return None


def completion_choice_from_candidate(
    model: str, candidate: Candidate, computer_use: bool = False
) -> ChatCompletionChoice:
    # content we'll return
    content: list[
        ContentText
        | ContentReasoning
        | ContentImage
        | ContentToolUse
        | ContentAudio
        | ContentVideo
        | ContentData
        | ContentDocument
    ] = []

    # google distributes reasoning text and thought_signature across multiple
    # content parts -- we need to consolidate this into a single ContentReasoning
    # to match our schema (we'll unroll it back into parts on replay)
    working_reasoning_block: ContentReasoning | None = None
    function_call_ids: dict[int, str] = {}

    # content can be None when the finish_reason is SAFETY
    # content.parts can be None when the finish_reason is MALFORMED_FUNCTION_CALL
    if candidate.content is not None and candidate.content.parts is not None:
        # traverse parts
        parts = candidate.content.parts
        for i, part in enumerate(parts):
            if part.tool_response is not None:
                continue  # We pickup tool responses with part.tool_call

            if part.function_call is not None:
                if part.thought_signature is not None and part.function_call.name:
                    function_call_id = part.function_call.id or (
                        f"{part.function_call.name}_{uuid()}"
                    )
                    function_call_ids[i] = function_call_id
                    content.append(
                        ContentReasoning(
                            reasoning=base64.b64encode(part.thought_signature).decode(),
                            redacted=True,
                            internal={"gemini_function_call_id": function_call_id},
                        )
                    )
                    working_reasoning_block = None
                continue

            if part.tool_call is not None:
                tool_response_part = next(
                    (
                        candidate_part
                        for candidate_part in parts[i + 1 :]
                        if candidate_part.tool_response is not None
                        and candidate_part.tool_response.id == part.tool_call.id
                    ),
                    None,
                )
                server_tool_use = server_tool_use_from_tool_call(
                    part, tool_response_part
                )
                if server_tool_use is not None:
                    content.append(server_tool_use)
                continue

            if part.text is None and part.executable_code is None:
                # Handle inline_data parts (images, audio)
                if part.inline_data is not None:
                    # Process thought_signature before appending media content
                    # so that the ContentReasoning precedes the media in the list
                    # (on replay, the signature is applied to the next part)
                    if part.thought_signature is not None:
                        working_reasoning_block = _consolidate_thought_signature(
                            part.thought_signature, working_reasoning_block, content
                        )
                    blob = part.inline_data
                    if blob.data is not None:
                        b64 = base64.b64encode(blob.data).decode()
                        data_uri = f"data:{blob.mime_type};base64,{b64}"
                        mime = blob.mime_type or ""
                        if mime.startswith("image/"):
                            content.append(ContentImage(image=data_uri))
                        elif mime.startswith("audio/"):
                            if "wav" in mime:
                                fmt: Literal["wav", "mp3"] = "wav"
                            elif "mp3" in mime or "mpeg" in mime:
                                fmt = "mp3"
                            else:
                                logger.warning(
                                    f"Unsupported audio MIME type '{mime}', "
                                    f"skipping audio content."
                                )
                                continue
                            content.append(ContentAudio(audio=data_uri, format=fmt))
                    else:
                        logger.warning(
                            f"Received inline_data part with mime_type "
                            f"'{blob.mime_type}' but data was None — "
                            f"content dropped (intermittent API issue)."
                        )
                continue  # Skip other non-text/non-executable_code parts

            if part.code_execution_result is not None:
                continue  # We pickup code execution results with part.executable_code

            if part.text is not None and part.thought is True:
                # we'll create and append a reasoning block, saving a reference
                # to it so that we can ammend it with a thought signature if/when
                # one arrives later in the stream (note that multiple reasoning
                # parts without a signature can occur)
                working_reasoning_block = ContentReasoning(
                    reasoning=part.text,
                    redacted=False,
                )
                content.append(working_reasoning_block)
            else:
                # Check if this block has an associated thought_signature and
                # whether it corresponds to the previous ContentReasoning block.
                if part.thought_signature is not None:
                    working_reasoning_block = _consolidate_thought_signature(
                        part.thought_signature, working_reasoning_block, content
                    )

                if part.text is not None:
                    content.append(ContentText(text=part.text))
                if part.executable_code is not None:
                    # lookahead for execution result
                    code_execution_result = (
                        parts[i + 1].code_execution_result
                        if i + 1 < len(parts)
                        else None
                    )
                    # append tool use
                    content.append(
                        server_tool_use_from_executable_code(
                            part.executable_code, code_execution_result
                        )
                    )

    # distribute citations to individual ContentText parts with adjusted indexes
    citations = get_candidate_citations(candidate)
    if citations:
        distribute_citations_to_text_parts(content, citations)

    # now tool calls
    tool_calls: list[ToolCall] = []
    if candidate.content is not None and candidate.content.parts is not None:
        for i, part in enumerate(candidate.content.parts):
            if part.function_call:
                if (
                    part.function_call is None
                    or part.function_call.name is None
                    or part.function_call.args is None
                ):
                    raise ValueError(f"Incomplete function call: {part.function_call}")

                # If the part has a thought_signature, try and associate it with the previous working block
                if part.thought_signature and i not in function_call_ids:
                    function_call_reasoning = ContentReasoning(
                        reasoning=base64.b64encode(part.thought_signature).decode(),
                        redacted=True,
                    )
                    if working_reasoning_block is None:
                        # We make the assumption that tool calls don't have independent reasoning
                        # blocks unless they are preceded by a reasoning block.
                        content.append(function_call_reasoning)
                    elif not working_reasoning_block.redacted:
                        # Preserve visible thought text as a thought part on replay.
                        # The function_call signature still needs to be returned
                        # with the function_call part itself, so store it as a
                        # separate redacted reasoning carrier.
                        content.append(function_call_reasoning)
                        working_reasoning_block = None
                    else:
                        # attach the thought_signature to the previous reasoning block
                        working_reasoning_block.summary = (
                            working_reasoning_block.reasoning
                        )
                        working_reasoning_block.reasoning = base64.b64encode(
                            part.thought_signature
                        ).decode()
                        working_reasoning_block.redacted = True
                        working_reasoning_block = None

                if computer_use and part.function_call.name in {
                    "click_at",
                    "type_text_at",
                    "hover_at",
                    "key_combination",
                    "scroll_document",
                    "scroll_at",
                    "drag_and_drop",
                    "navigate",
                    "go_back",
                    "go_forward",
                    "open_web_browser",
                    "search",
                    "wait_5_seconds",
                }:
                    tool_calls.append(
                        tool_call_from_gemini_computer_action(part.function_call)
                    )
                else:
                    if part.function_call.args:
                        part.function_call.args.pop("safety_decision", None)
                    function_call_id = function_call_ids.get(i) or (
                        part.function_call.id or f"{part.function_call.name}_{uuid()}"
                    )
                    tool_calls.append(
                        ToolCall(
                            id=function_call_id,
                            function=part.function_call.name,
                            arguments=part.function_call.args,
                        )
                    )

    # stop reason
    stop_reason = finish_reason_to_stop_reason(
        candidate.finish_reason or FinishReason.STOP
    )

    # if finish reason is MALFORMED_FUNCTION_CALL then we should put words the model's
    # mouth indicating that it had trouble calling a tool
    # (see https://github.com/googleapis/python-genai/issues/430#issuecomment-3592369131)
    if candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
        content.append(
            ContentText(
                text=dedent(f"""
                I seem to have had trouble calling a function and replied with {_malformed_function_message(candidate)}.
                I need to fix this by generating the function call JSON instead.
                """)
            )
        )

    # build choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content if len(content) > 0 else "",
            tool_calls=tool_calls if len(tool_calls) > 0 else None,
            model=model,
            source="generate",
        ),
        stop_reason=stop_reason,
    )

    # add logprobs if provided
    if candidate.logprobs_result:
        logprobs: list[Logprob] = []
        if (
            candidate.logprobs_result.chosen_candidates
            and candidate.logprobs_result.top_candidates
        ):
            for chosen, top in zip(
                candidate.logprobs_result.chosen_candidates,
                candidate.logprobs_result.top_candidates,
            ):
                if chosen.token and chosen.log_probability:
                    logprobs.append(
                        Logprob(
                            token=chosen.token,
                            logprob=chosen.log_probability,
                            top_logprobs=[
                                TopLogprob(token=c.token, logprob=c.log_probability)
                                for c in (top.candidates or [])
                                if c.token and c.log_probability
                            ],
                        )
                    )
            choice.logprobs = Logprobs(content=logprobs)

    return choice


def completion_choices_from_candidates(
    model: str,
    response: GenerateContentResponse,
    computer_use: bool = False,
) -> list[ChatCompletionChoice]:
    candidates = response.candidates
    if candidates:
        candidates_list = sorted(candidates, key=lambda c: c.index or 0)
        return [
            completion_choice_from_candidate(model, candidate, computer_use)
            for candidate in candidates_list
        ]
    elif response.prompt_feedback:
        return [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=prompt_feedback_to_content(response.prompt_feedback),
                    model=model,
                    source="generate",
                ),
                stop_reason="content_filter",
            )
        ]
    else:
        return [
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=NO_CONTENT,
                    model=model,
                    source="generate",
                ),
                stop_reason="stop",
            )
        ]


def prompt_feedback_to_content(
    feedback: GenerateContentResponsePromptFeedback,
) -> str:
    content: list[str] = []
    block_reason = str(feedback.block_reason) if feedback.block_reason else "UNKNOWN"
    content.append(f"BLOCKED: {block_reason}")

    if feedback.block_reason_message is not None:
        content.append(feedback.block_reason_message)
    if feedback.safety_ratings is not None:
        content.extend(
            [rating.model_dump_json(indent=2) for rating in feedback.safety_ratings]
        )
    return "\n".join(content)


def usage_metadata_to_model_usage(
    metadata: GenerateContentResponseUsageMetadata | None,
) -> ModelUsage | None:
    if metadata is None:
        return None
    # Gemini reports `prompt_token_count` as the full prompt size including
    # any cached portion. To match the convention used by the OpenAI and
    # Anthropic providers — where `input_tokens` is fresh (uncached) input
    # and `input_tokens_cache_read` is the cache hit — subtract out the
    # cached count from `input_tokens` and surface it separately.
    cached = metadata.cached_content_token_count or 0
    prompt = metadata.prompt_token_count or 0
    return ModelUsage(
        input_tokens=max(prompt - cached, 0),
        output_tokens=metadata.candidates_token_count or 0,
        total_tokens=metadata.total_token_count or 0,
        input_tokens_cache_read=cached or None,
        reasoning_tokens=metadata.thoughts_token_count or 0,
    )


def server_tool_use_from_executable_code(
    executable_code: ExecutableCode, result: CodeExecutionResult | None
) -> ContentToolUse:
    # parse out output and error
    if result is not None:
        result_output = result.output or ""
        if result.outcome is not None and result.outcome != Outcome.OUTCOME_OK:
            result_error: str | None = result.outcome
        else:
            result_error = None
    else:
        result_output = ""
        result_error = None

    # return tool use
    return ContentToolUse(
        tool_type="code_execution",
        id="",
        name=executable_code.language or Language.LANGUAGE_UNSPECIFIED,
        arguments=executable_code.code or "",
        result=result_output,
        error=result_error,
    )


def server_tool_use_from_tool_call(
    tool_call_part: Part, tool_response_part: Part | None
) -> ContentToolUse | None:
    """Convert a Gemini server-side tool call into Inspect content."""
    assert tool_call_part.tool_call is not None
    tool_call = tool_call_part.tool_call
    tool_response = (
        tool_response_part.tool_response if tool_response_part is not None else None
    )
    internal_parts = [
        tool_call_part.model_dump(exclude_none=True, by_alias=True, mode="json")
    ]
    if tool_response_part is not None:
        internal_parts.append(
            tool_response_part.model_dump(exclude_none=True, by_alias=True, mode="json")
        )
    tool_type = str(tool_call.tool_type or "")
    if "SEARCH" not in tool_type:
        warn_once(
            logger,
            f"Skipping unsupported Google server-side tool call type: {tool_type}.",
        )
        return None
    return ContentToolUse(
        tool_type="web_search",
        id=tool_call.id or "",
        name=tool_type,
        arguments=json.dumps(tool_call.args or {}),
        result=json.dumps(tool_response.response if tool_response else {}),
        internal={"gemini_parts": cast(JsonValue, internal_parts)},
    )


def parts_from_server_tool_use(tool: ContentToolUse) -> list[Part]:
    """Reconstruct Gemini request parts from server-side tool use."""
    if tool.tool_type == "web_search":
        if (
            isinstance(tool.internal, dict)
            and (gemini_parts := tool.internal.get("gemini_parts")) is not None
            and isinstance(gemini_parts, list)
        ):
            gemini_request_parts = [Part.model_validate(part) for part in gemini_parts]
            missing_signature = any(
                part.tool_call is not None and part.thought_signature is None
                for part in gemini_request_parts
            )
            if not missing_signature:
                return gemini_request_parts
            warn_once(
                logger,
                "Skipping Gemini server-side web search replay because the saved tool call is missing a thought_signature.",
            )
        return []

    if tool.tool_type != "code_execution":
        return []

    code_execution_parts: list[Part] = [
        Part.from_executable_code(code=tool.arguments, language=Language(tool.name))
    ]
    if tool.result or tool.error:
        code_execution_parts.append(
            Part.from_code_execution_result(
                outcome=Outcome(tool.error) if tool.error else Outcome.OUTCOME_OK,
                output=tool.result,
            )
        )
    return code_execution_parts


def finish_reason_to_stop_reason(finish_reason: FinishReason) -> StopReason:
    match finish_reason:
        case FinishReason.STOP:
            return "stop"
        case FinishReason.MAX_TOKENS:
            return "max_tokens"
        case (
            FinishReason.SAFETY
            | FinishReason.RECITATION
            | FinishReason.BLOCKLIST
            | FinishReason.PROHIBITED_CONTENT
            | FinishReason.SPII
        ):
            return "content_filter"
        case _:
            # Note: to avoid adding another option to StopReason,
            # this includes FinishReason.MALFORMED_FUNCTION_CALL
            return "unknown"


def parse_safety_settings(
    safety_settings: Any,
) -> list[SafetySettingDict]:
    # ensure we have a dict
    if isinstance(safety_settings, str):
        safety_settings = json.loads(safety_settings)
    if not isinstance(safety_settings, dict):
        raise ValueError(f"{SAFETY_SETTINGS} must be dictionary.")

    parsed_settings: list[SafetySettingDict] = []
    for key, value in safety_settings.items():
        if not isinstance(key, str):
            raise ValueError(f"Unexpected type for harm category: {key}")
        if not isinstance(value, str):
            raise ValueError(f"Unexpected type for harm block threshold: {value}")
        key = str_to_harm_category(key)
        value = str_to_harm_block_threshold(value)
        parsed_settings.append({"category": key, "threshold": value})
    return parsed_settings


def str_to_harm_category(category: str) -> HarmCategory:
    category = category.upper()
    # `in` instead of `==` to allow users to pass in short version e.g. "HARASSMENT" or
    # long version e.g. "HARM_CATEGORY_HARASSMENT" strings.
    if "CIVIC_INTEGRITY" in category:
        return HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY
    if "DANGEROUS_CONTENT" in category:
        return HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT
    if "HATE_SPEECH" in category:
        return HarmCategory.HARM_CATEGORY_HATE_SPEECH
    if "HARASSMENT" in category:
        return HarmCategory.HARM_CATEGORY_HARASSMENT
    if "SEXUALLY_EXPLICIT" in category:
        return HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT
    if "UNSPECIFIED" in category:
        return HarmCategory.HARM_CATEGORY_UNSPECIFIED
    raise ValueError(f"Unknown HarmCategory: {category}")


def str_to_harm_block_threshold(threshold: str) -> HarmBlockThreshold:
    threshold = threshold.upper()
    if "LOW" in threshold:
        return HarmBlockThreshold.BLOCK_LOW_AND_ABOVE
    if "MEDIUM" in threshold:
        return HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
    if "HIGH" in threshold:
        return HarmBlockThreshold.BLOCK_ONLY_HIGH
    if "NONE" in threshold:
        return HarmBlockThreshold.BLOCK_NONE
    if "OFF" in threshold:
        return HarmBlockThreshold.OFF
    raise ValueError(f"Unknown HarmBlockThreshold: {threshold}")


async def file_for_content(
    client: Client, content: ContentAudio | ContentVideo | ContentDocument
) -> File:
    # helper to write trace messages
    def trace(message: str) -> None:
        trace_message(logger, "Google Files", message)

    # get the file bytes and compute sha256 hash
    if isinstance(content, ContentAudio):
        file = content.audio
    elif isinstance(content, ContentVideo):
        file = content.video
    else:
        file = content.document
    content_bytes, mime_type = await file_as_data(file)
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    # we cache uploads for re-use, open the db where we track that
    # (track up to 1 million previous uploads)
    with inspect_kvstore("google_files", 1000000) as files_db:
        # can we serve from existing uploads?
        uploaded_file = files_db.get(content_sha256)
        if uploaded_file:
            try:
                upload: File = client.files.get(name=uploaded_file)
                assert upload.state
                if upload.state.name == "ACTIVE":
                    trace(f"Using uploaded file: {uploaded_file}")
                    return upload
                else:
                    trace(
                        f"Not using uploaded file '{uploaded_file} (state was {upload.state})"
                    )
            except Exception as ex:
                trace(f"Error attempting to access uploaded file: {ex}")
                files_db.delete(content_sha256)
        # do the upload (and record it)
        upload = client.files.upload(
            file=BytesIO(content_bytes), config=dict(mime_type=mime_type)
        )
        while upload.state.name == "PROCESSING":  # type: ignore[union-attr]
            await anyio.sleep(3)
            assert upload.name
            upload = client.files.get(name=upload.name)
        if upload.state.name == "FAILED":  # type: ignore[union-attr]
            trace(f"Failed to upload file '{upload.name}: {upload.error}")
            raise ValueError(f"Google file upload failed: {upload.error}")
        # trace and record it
        trace(f"Uploaded file: {upload.name}")
        files_db.put(content_sha256, str(upload.name))
        # return the file
        return upload


def _malformed_function_retry(
    response: GenerateContentResponse, tool_choice: ToolChoice
) -> tuple[list[Content], ToolConfig | None]:
    content = [
        Content(
            role="model",
            parts=[
                Part(
                    text=f"I attempted to call a function but produced: {_malformed_function_message(response)}"
                )
            ],
        ),
        Content(
            role="user",
            parts=[
                Part(
                    text="Please try again and generate valid function call JSON, not Python code."
                )
            ],
        ),
    ]

    # force tool calling if it was 'auto'
    tool_config = chat_tool_config("any") if tool_choice == "auto" else None

    return content, tool_config


def _malformed_function_message(candidate: Candidate | GenerateContentResponse) -> str:
    DEFAULT_FINISH_MESSAGE = (
        "a malformed function call (possibly Python code instead of JSON)"
    )

    # resolve candidate
    if isinstance(candidate, GenerateContentResponse):
        if not candidate.candidates:
            return DEFAULT_FINISH_MESSAGE

        candidate = candidate.candidates[0]

    if candidate.finish_message:
        return candidate.finish_message
    else:
        return DEFAULT_FINISH_MESSAGE
