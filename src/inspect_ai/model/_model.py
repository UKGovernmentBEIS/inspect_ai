import abc
import contextlib
import functools
import json
import logging
import os
import time
from contextvars import ContextVar
from copy import copy, deepcopy
from datetime import datetime, timezone
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Literal,
    NamedTuple,
    Sequence,
    Type,
    TypeAlias,
    cast,
)

if TYPE_CHECKING:
    from inspect_ai.tool import ToolInfo

import anyio
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from tenacity import (
    RetryCallState,
    retry,
)
from tenacity.wait import WaitBaseT

from inspect_ai._util.constants import (
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS_BATCH,
    HTTP,
)
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.error import exception_message
from inspect_ai._util.logger import warn_once
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_find,
    registry_info,
    registry_unqualified_name,
)
from inspect_ai._util.retry import report_http_retry
from inspect_ai._util.rich import format_traceback
from inspect_ai._util.trace import trace_action
from inspect_ai._util.working import report_sample_waiting_time, sample_working_time
from inspect_ai.model._retry import model_retry_config
from inspect_ai.tool import Tool, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
from inspect_ai.tool._tool import ToolSource
from inspect_ai.tool._tool_call import ToolCallModelInputHints
from inspect_ai.tool._tool_def import ToolDef, tool_defs
from inspect_ai.util import concurrency
from inspect_ai.util._limit import (
    check_cost_limit,
    check_message_limit,
    check_token_limit,
    record_model_cost,
    record_model_usage,
)

from ._cache import CacheEntry, CachePolicy, cache_fetch, cache_store, epoch
from ._call_tools import (
    disable_parallel_tools,
    execute_tools,
    get_tools_info,
    resolve_tools,
    tool_call_view,
)
from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._display import (
    display_conversation_assistant,
    display_conversation_assistant_error,
)
from ._generate_config import (
    GenerateConfig,
    active_generate_config,
    set_active_generate_config,
)
from ._model_call import ModelCall, as_error_response
from ._model_data.model_data import ModelCost
from ._model_output import ModelOutput, ModelUsage
from ._tokens import count_media_tokens, count_text_tokens, count_tokens

logger = logging.getLogger(__name__)


class GenerateInput(NamedTuple):
    """Input parameters for generate function."""

    input: list[ChatMessage]
    """Chat message input."""

    tools: list[ToolInfo]
    """Tools available for the model to call."""

    tool_choice: ToolChoice | None
    """Directives to the model as to which tools to prefer."""

    config: GenerateConfig
    """Model configuration."""


GenerateFilter: TypeAlias = Callable[
    [str, list[ChatMessage], list[ToolInfo], ToolChoice | None, GenerateConfig],
    Awaitable[ModelOutput | GenerateInput | None],
]
"""Filter a model generation.

A filter may substitute for the default model generation by returning a
`ModelOutput`, modify the input parameters by returning a `GenerateInput`, or return `None` to allow default processing to continue.
"""


class ModelAPI(abc.ABC):
    """Model API provider.

    If you are implementing a custom ModelAPI provider your `__init__()`
    method will also receive a `**model_args` parameter that will carry
    any custom `model_args` (or `-M` arguments from the CLI) specified
    by the user. You can then pass these on to the approriate place in
    your model initialisation code (for example, here is what many
    of the built-in providers do with the `model_args` passed to them:
    https://inspect.aisi.org.uk/models.html#model-args)
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        """Create a model API provider.

        Args:
           model_name (str): Model name.
           base_url (str | None): Alternate base URL for model.
           api_key (str | None): API key for model.
           api_key_vars (list[str]): Environment variables that
              may contain keys for this provider (used for override)
           config (GenerateConfig): Model configuration.
        """
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.api_key_vars = api_key_vars
        self._apply_api_key_overrides()

    def _apply_api_key_overrides(self) -> None:
        from inspect_ai.hooks._hooks import override_api_key

        # apply api key override
        api_key = self.api_key
        for key in self.api_key_vars:
            # if there is an explicit api_key passed then it
            # overrides anything in the environment so use it
            if api_key is not None:
                override = override_api_key(key, api_key)
                if override is not None:
                    api_key = override
            # otherwise look it up in the environment and
            # override it if it has a value
            else:
                value = os.environ.get(key, None)
                if value is not None:
                    override = override_api_key(key, value)
                    if override is not None:
                        os.environ[key] = override

        # set any explicitly specified api key
        self.api_key = api_key

    def initialize(self) -> None:
        """Reinitialize the model API client.

        This can be used to reinitialize the API keys.
        """
        self._apply_api_key_overrides()

    async def aclose(self) -> None:
        """Async close method for closing any client allocated for the model."""
        self.close()

    def close(self) -> None:
        """Sync close method for closing any client allocated for the model."""
        # if this is is called and aclose is implemented by a subclass then
        # raise a runtime error (as this model reuqires async close)
        aclose_method = getattr(self.__class__, "aclose")
        base_aclose_method = getattr(ModelAPI, "aclose")
        if aclose_method != base_aclose_method:
            raise RuntimeError(
                f"{self.__class__.__name__} models require an async close / context manager."
            )

    def canonical_name(self) -> str:
        """Canonical model name for querying results."""
        return self.model_name

    @abc.abstractmethod
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        """Generate output from the model.

        Args:
          input: Chat message input (if a `str` is passed it is converted to a `ChatUserMessage`).
          tools: Tools available for the model to call.
          tool_choice: Directives to the model as to which tools to prefer.
          config: Model configuration.

        Returns:
           ModelOutput or tuple[ModelOutput,ModelCall], the latter being
           useful if you want the underlying model API call logged as
           part of the ModelEvent.
        """
        ...

    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        """Estimate token count for input.

        This default implementation uses character-based heuristics for text
        and size-based estimates for media. Model providers can override
        `count_text_tokens()` and `count_media_tokens()` for more accurate results,
        or override this method entirely to use their native token counting APIs.

        Args:
            input: Input to count tokens for.
            config: Optional generation config for provider-specific counting
                (e.g., reasoning parameters that affect token allocation).
        """
        if isinstance(input, str):
            return await self.count_text_tokens(input)
        else:
            return await count_tokens(
                input, self.count_text_tokens, self.count_media_tokens
            )

    async def count_text_tokens(self, text: str) -> int:
        """Estimate tokens from text using tiktoken (o200k_base with 10% buffer).

        Override this method to use model-specific tokenizers.

        Args:
            text: Text to count.
        """
        return count_text_tokens(text)

    async def count_media_tokens(
        self, media: ContentImage | ContentAudio | ContentVideo | ContentDocument
    ) -> int:
        """Estimate tokens for media content (images, audio, video, documents).

        For data URIs, estimates are based on decoded size. For URLs/file paths,
        uses conservative fixed fallbacks. Override this method for provider-specific
        media token calculations.

        Args:
            media: Media content to count tokens for.
        """
        return count_media_tokens(media)

    def max_tokens(self) -> int | None:
        """Default max_tokens."""
        return None

    def max_tokens_for_config(self, config: GenerateConfig) -> int | None:
        """Default max_tokens for a given config.

        Args:
           config: Generation config.

        Returns:
           Default maximum tokens for specified configuration.
        """
        return None

    def max_connections(self) -> int:
        """Default max_connections."""
        return DEFAULT_MAX_CONNECTIONS

    def connection_key(self) -> str:
        """Scope for enforcement of max_connections."""
        return "default"

    def should_retry(self, ex: Exception) -> bool:
        """Should this exception be retried?

        Args:
           ex: Exception to check for retry
        """
        return False

    def retry_wait(self) -> WaitBaseT | None:
        return None

    def is_auth_failure(self, ex: Exception) -> bool:
        """Check if this exception indicates an authentication failure.

        Args:
           ex: Exception to check for authentication failure

        Returns:
           True if this is an authentication error (e.g., 401 Unauthorized)
        """
        return False

    def collapse_user_messages(self) -> bool:
        """Collapse consecutive user messages into a single message."""
        return False

    def collapse_assistant_messages(self) -> bool:
        """Collapse consecutive assistant messages into a single message."""
        return False

    def tools_required(self) -> bool:
        """Any tool use in a message stream means that tools must be passed."""
        return False

    def supports_remote_mcp(self) -> bool:
        """Does this provider support remote execution of MCP tools?."""
        return False

    def tool_result_images(self) -> bool:
        """Tool results can contain images"""
        return False

    def disable_computer_screenshot_truncation(self) -> bool:
        """Some models do not support truncation of computer screenshots."""
        return False

    def force_reasoning_history(self) -> Literal["none", "all", "last"] | None:
        """Force a specific reasoning history behavior for this provider."""
        return None

    def auto_reasoning_history(self) -> Literal["none", "all", "last"]:
        """Behavior to use for reasoning_history='auto'"""
        return "all"

    def compact_reasoning_history(self) -> bool:
        """Is reasoning history eligible for compation for this provider?"""
        return True

    async def compact(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        config: GenerateConfig,
        instructions: str | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        """Compact messages using provider-native compaction.

        Some model providers (e.g., OpenAI Codex models) support native context
        compaction, which reduces the token count of a conversation while preserving
        semantic meaning. This is useful for long conversations that approach the
        context window limit.

        Args:
            input: Chat message input (if a `str` is passed it is converted to a `ChatUserMessage`).
            tools: Tools available for the model to call.
            config: Model configuration.
            instructions: Additional instructions to give the model about compaction
                (e.g. "Focus on preserving code snippets, variable names, and technical decisions.")

        Returns:
            A tuple of (compacted_messages, usage) where compacted_messages is a
            list containing a single message with compaction metadata, and usage
            contains token counts for the compaction operation.

        Raises:
            NotImplementedError: For providers without native compaction support.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support native compaction."
        )


class Model:
    """Model interface.

    Use `get_model()` to get an instance of a model. Model provides an
    async context manager for closing the connection to it after use.
    For example:

    ```python
    async with get_model("openai/gpt-4o") as model:
        response = await model.generate("Say hello")
    ```
    """

    api: ModelAPI
    """Model API."""

    config: GenerateConfig
    """Generation config."""

    def __init__(
        self,
        api: ModelAPI,
        config: GenerateConfig,
        model_args: dict[str, Any] | None = None,
    ) -> None:
        """Create a model.

        Args:
           api: Model API provider.
           config: Model configuration.
           model_args: Optional model args
        """
        self.api = api
        self.config = config
        self.model_args = model_args if model_args is not None else {}
        self._role: str | None = None

        # state indicating whether our lifetime is bound by a context manager
        self._context_bound = False
        self._closed = False

        # if using the Model API standalone in a notebook this will
        # get hit before score() or eval() so we activate nest_asyncio
        platform_init()

    def __enter__(self: "Model") -> "Model":
        self._context_bound = True
        return self

    async def __aenter__(self: "Model") -> "Model":
        return self.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._closed:
            self.api.close()
            self._closed = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._closed:
            await self.api.aclose()
            self._closed = True

    @property
    def name(self) -> str:
        """Model name."""
        return self.api.model_name

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup."""
        return self.api.canonical_name()

    @property
    def role(self) -> str | None:
        """Model role."""
        return self._role

    def _set_role(self, role: str) -> None:
        self._role = role

    def __str__(self) -> str:
        return f"{ModelName(self)}"

    async def generate(
        self,
        input: str | list[ChatMessage],
        tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource = [],
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig = GenerateConfig(),
        cache: bool | CachePolicy | NotGiven = NOT_GIVEN,
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
          input: Chat message input (if a `str` is passed it is converted
            to a `ChatMessageUser`).
          tools: Tools available for the model to call.
          tool_choice: Directives to the model as to which tools to prefer.
          config: Model configuration.
          cache: Caching behavior for generate responses (defaults to no caching).

        Returns:
           ModelOutput
        """
        # if we have a TaskState then update the epoch. without this, it's possible
        # we'd cache the same response for every single epoch
        from inspect_ai.solver._task_state import sample_state

        state = sample_state()
        if state is not None:
            epoch.set(state.epoch)

        # if we are the default model then update the displayed message count
        is_active_model = self == active_model()
        if is_active_model:
            set_total_messages(input)

        # check message limit, raise exception if we're already at the limit to prevent
        # a wasteful generate()
        conversation_length = len(input) if isinstance(input, list) else 1
        check_message_limit(conversation_length, raise_for_equal=True)

        # resolve config
        config = self._resolve_config(config)

        # resolve cache (prefer arg, fall back to config)
        if isinstance(cache, NotGiven):
            if config.cache is not None:
                cache = config.cache
            else:
                cache = False

        # provide max_tokens from the model api if required
        if config.max_tokens is None:
            config.max_tokens = self.api.max_tokens_for_config(config)
            if config.max_tokens is None:
                config.max_tokens = self.api.max_tokens()

        # disable parallel tool calls if requested by any of our tools
        if disable_parallel_tools(tools):
            config.parallel_tool_calls = False

        # normalize input to chat
        if isinstance(input, str):
            input = [ChatMessageUser(content=input)]

        # insert any system message provided in config
        if config.system_message:
            input = [ChatMessageSystem(content=config.system_message)] + input

        # enforce concurrency limits
        start_time = datetime.now(timezone.utc)
        working_start = sample_working_time()
        async with self._connection_concurrency(config):
            # generate
            output, event = await self._generate(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                cache=cache,
            )

            # update the most recent ModelEvent with the actual start/completed
            # times as well as a computation of working time (events are
            # created _after_ the call to _generate, potentially in response
            # to retries, so they need their timestamp updated so it accurately
            # reflects the full start/end time which we know here)
            from inspect_ai.event._model import ModelEvent

            assert isinstance(event, ModelEvent)
            event.timestamp = start_time
            event.working_start = working_start
            completed = datetime.now(timezone.utc)
            event.completed = completed
            event.working_time = (
                output.time
                if output.time is not None
                else (completed - start_time).total_seconds()
            )

            # return output
            return output

    async def generate_loop(
        self,
        input: str | list[ChatMessage],
        tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource = [],
        config: GenerateConfig = GenerateConfig(),
        cache: bool | CachePolicy | NotGiven = NOT_GIVEN,
    ) -> tuple[list[ChatMessage], ModelOutput]:
        """Generate output from the model, looping as long as the model calls tools.

        Similar to `generate()`, but runs in a loop resolving model tool calls.
        The loop terminates when the model stops calling tools. The final `ModelOutput`
        as well the message list for the conversation are returned as a tuple.

        Args:
          input: Chat message input (if a `str` is passed it is converted
            to a `ChatMessageUser`).
          tools: Tools available for the model to call.
          config: Model configuration.
          cache: Caching behavior for generate responses (defaults to no caching).

        Returns:
           Tuple of list[ChatMessage], ModelOutput
        """
        # initialise messages
        input = [ChatMessageUser(content=input)] if isinstance(input, str) else input
        messages = copy(input)
        while True:
            # call model
            output = await self.generate(
                input=messages,
                tools=tools,  # type:ignore[arg-type]
                config=config,
                cache=cache,
            )

            # append to new messages
            messages.append(output.message)

            # make tool calls or terminate if there are none
            if output.message.tool_calls:
                tools_messages, tools_output = await execute_tools(
                    messages, tools, config.max_tool_output
                )
                messages.extend(tools_messages)
                if tools_output is not None:
                    output = tools_output
            else:
                return messages[len(input) :], output

    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        """Estimate token count for input.

        Args:
           input: Input to count tokens for.
           config: Optional generation config for provider-specific counting
               (e.g., reasoning parameters that affect token allocation).
        """
        config = self._resolve_config(config)
        model_name = ModelName(self)
        key = f"ModelCountTokens({self.api.connection_key()})"
        async with concurrency(f"{model_name}_count_tokens", 10, key, visible=False):
            # retry handler for token counting
            @retry(
                **model_retry_config(
                    self.api.model_name,
                    self.config.max_retries,
                    self.config.timeout,
                    self.should_retry,
                    self.before_retry,
                    log_model_retry,
                    report_sample_waiting_time,
                    self.api.retry_wait(),
                )
            )
            async def _count_tokens(
                input: str | list[ChatMessage], config: GenerateConfig | None
            ) -> int:
                return await self.api.count_tokens(input, config)

            # count tokens
            return await _count_tokens(input, config)

    async def count_tool_tokens(self, tools: Sequence[ToolInfo]) -> int:
        """Count tokens for tool definitions.

        Args:
            tools: List of tool definitions.

        Returns:
            Total token count for all tool definitions.
        """
        # create a message with the tool tokens embedded and count that
        tool_json = ""
        for tool in tools:
            tool_json += json.dumps(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters.model_dump(exclude_none=True),
                    },
                }
            )
        return await self.count_tokens([ChatMessageUser(content=tool_json)])

    async def compact(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        instructions: str | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        """Compact messages using provider-native compaction.

        Delegates to the model provider's native compaction API when available.
        Automatically tracks token usage and enforces token limits.

        Args:
          input: Chat message input (if a `str` is passed it is converted to a `ChatUserMessage`).
          tools: Tools available for the model to call.
          config: Model configuration.
          instructions: Additional instructions to give the model about compaction
               (e.g. "Focus on preserving code snippets, variable names, and technical decisions.")

        Returns:
          A tuple of (compacted_messages, usage) where compacted_messages is
          a list of compacted messages and usage contains token counts.

        Raises:
            NotImplementedError: For providers without native compaction support.
        """
        config = self._resolve_config(None)

        # provide max_tokens from the model api if required (same as generate)
        if config.max_tokens is None:
            config.max_tokens = self.api.max_tokens_for_config(config)
            if config.max_tokens is None:
                config.max_tokens = self.api.max_tokens()

        model_name = ModelName(self)
        key = f"ModelCompact({self.api.connection_key()})"

        async with concurrency(f"{model_name}_compact", 10, key, visible=False):

            @retry(
                **model_retry_config(
                    self.api.model_name,
                    self.config.max_retries,
                    self.config.timeout,
                    self.should_retry,
                    self.before_retry,
                    log_model_retry,
                    report_sample_waiting_time,
                    self.api.retry_wait(),
                )
            )
            async def _compact(
                messages: list[ChatMessage],
            ) -> tuple[list[ChatMessage], ModelUsage | None]:
                return await self.api.compact(messages, tools, config, instructions)

            # Call compact with retry handling
            compacted_messages, usage = await _compact(input)

            # Record and check usage
            if usage:
                record_and_check_model_usage(f"{self}", usage)

            return compacted_messages, usage

    async def _generate(
        self,
        input: list[ChatMessage],
        tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource,
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
        cache: bool | CachePolicy | NotGiven = NOT_GIVEN,
    ) -> tuple[ModelOutput, BaseModel]:
        from inspect_ai.event._model import ModelEvent
        from inspect_ai.hooks._hooks import emit_model_cache_usage, emit_model_usage
        from inspect_ai.hooks._legacy import send_telemetry_legacy
        from inspect_ai.log._samples import track_active_model_event

        # default to 'auto' for tool_choice (same as underlying model apis)
        tool_choice = tool_choice if tool_choice is not None else "auto"

        # resolve tools
        resolved_tools = await resolve_tools(tools)

        # extract tool defs if we can
        tdefs = await tool_defs(
            [tool for tool in resolved_tools if not isinstance(tool, ToolInfo)]
        )

        # resolve all tools into tool_info
        tools_info = get_tools_info(resolved_tools)

        # raise error if we don't support remote_mcp and we have an mcp server
        if not self.api.supports_remote_mcp():
            for tool in tools_info:
                if is_mcp_server_tool(tool):
                    raise RuntimeError(
                        f"Remote MCP execution is not supported for {self}. "
                        + 'Please use "local" execution instead.'
                    )

        # if we have a specific tool selected then filter out the others
        if isinstance(tool_choice, ToolFunction):
            tools_info = [tool for tool in tools_info if tool.name == tool_choice.name]

        # if tool_choice is "none" or if there are no tools then fully purge
        # the tools (as some models (e.g. openai and mistral) get confused
        # if you pass them tool definitions along with tool_choice == "none"
        # (they both 'semi' use the tool by placing the arguments in JSON
        # in their output!). on the other hand, anthropic actually errors if
        # there are tools anywhere in the message stream and no tools defined.
        if tool_choice == "none" or len(tools_info) == 0:
            # allow model providers to implement a tools_required() method to
            # force tools to be passed (we need this for anthropic)
            if not self.api.tools_required():
                tools_info = []
            tool_choice = "none"

        # handle reasoning history
        input = resolve_reasoning_history(input, config, self.api)

        # apply any tool model_input handlers
        input = resolve_tool_model_input(
            tdefs,
            input,
            ToolCallModelInputHints(
                disable_computer_screenshot_truncation=self.api.disable_computer_screenshot_truncation()
            ),
        )

        # break tool image content out into user messages if the model doesn't
        # support tools returning images
        if not self.api.tool_result_images():
            input = tool_result_images_as_user_message(input)

        # optionally collapse *consecutive* messages into one -
        # (some apis e.g. anthropic require this)
        if self.api.collapse_user_messages():
            input = collapse_consecutive_user_messages(input)

        if self.api.collapse_assistant_messages():
            input = collapse_consecutive_assistant_messages(input)

        # resolve cache policy
        if isinstance(cache, NotGiven):
            cache_policy: bool | CachePolicy | None = config.cache
        else:
            cache_policy = cache

        # track reported waiting time during this generate call
        reported_waiting_time = 0.0

        def report_waiting_time(waiting_time: float) -> None:
            nonlocal reported_waiting_time
            report_sample_waiting_time(waiting_time)
            reported_waiting_time += waiting_time

        @retry(
            **model_retry_config(
                self.api.model_name,
                config.max_retries,
                config.timeout,
                self.should_retry,
                self.before_retry,
                log_model_retry,
                report_waiting_time,
                self.api.retry_wait(),
            )
        )
        async def generate() -> tuple[ModelOutput, BaseModel]:
            # type-checker can't see that we made sure tool_choice is not none in the outer frame
            assert tool_choice is not None

            cache_entry: CacheEntry | None
            if cache_policy:
                if isinstance(cache_policy, CachePolicy):
                    policy = cache_policy
                else:
                    policy = CachePolicy()

                cache_entry = CacheEntry(
                    base_url=self.api.base_url,
                    config=deepcopy(config),
                    input=input,
                    model=str(self),
                    policy=policy,
                    tool_choice=tool_choice,
                    tools=tools_info,
                )
                existing = cache_fetch(cache_entry)
                if isinstance(existing, ModelOutput):
                    _, event = self._record_model_interaction(
                        input=input,
                        tools=tools_info,
                        tool_choice=tool_choice,
                        config=config,
                        cache="read",
                        output=existing,
                        call=None,
                    )
                    if existing.usage:
                        await emit_model_cache_usage(
                            model_name=str(self), usage=existing.usage
                        )
                    return existing, event
            else:
                cache_entry = None

            # verify that model apis are allowed
            self.verify_model_apis()

            # record the interaction before the call to generate
            # (we'll update it with the results once we have them)
            complete, event = self._record_model_interaction(
                input=input,
                tools=tools_info,
                tool_choice=tool_choice,
                config=config,
                cache="write" if cache else None,
            )

            # create timeout context manager if we have an attempt timeout
            timeout_cm = (
                anyio.move_on_after(config.attempt_timeout)
                if config.attempt_timeout is not None
                else contextlib.nullcontext()
            )

            with trace_action(logger, "Model", f"generate ({str(self)})"):
                time_start = time.monotonic()
                try:
                    assert isinstance(event, ModelEvent)
                    with track_active_model_event(event):
                        with timeout_cm:
                            result = await self.api.generate(
                                input=input,
                                tools=tools_info,
                                tool_choice=tool_choice,
                                config=config,
                            )
                        if (
                            isinstance(timeout_cm, anyio.CancelScope)
                            and timeout_cm.cancel_called
                        ):
                            raise AttemptTimeoutError(config.attempt_timeout)
                except Exception as ex:
                    # Mark event as failed for uncaught provider exceptions
                    complete(ex, None)
                    raise
                finally:
                    time_elapsed = time.monotonic() - time_start

            if isinstance(result, tuple):
                output, call = result
            else:
                output = result
                call = None

            # raise error
            if isinstance(output, Exception):
                complete(output, call)

                # Wrap the error in a runtime error which will show the
                # request which caused the error
                error = repr(output)
                request = json.dumps(call.request, indent=2) if call is not None else ""
                error_message = f"\nRequest:\n{request}\n\n{error}"
                raise RuntimeError(error_message)

            # update output with time (call.time captures time spent
            # on the actual request that succeeds w/ status 200)
            if call and call.time is not None:
                output.time = call.time
            else:
                output.time = time_elapsed

            # add views to tool calls
            for choice in output.choices:
                for tool_call in choice.message.tool_calls or []:
                    tool_call.view = tool_call_view(tool_call, tdefs)

            # complete the transcript event
            complete(output, call)

            # record usage
            if output.usage:
                record_and_check_model_usage(f"{self}", output.usage)

                # send telemetry to hooks
                await emit_model_usage(
                    model_name=str(self), usage=output.usage, call_duration=output.time
                )
                await send_telemetry_legacy(
                    "model_usage",
                    json.dumps(dict(model=str(self), usage=output.usage.model_dump())),
                )

            if cache and cache_entry:
                cache_store(entry=cache_entry, output=output)

            return output, event

        # call the model (this will do retries, etc., so report waiting time
        # as elapsed time - actual time for successful model call)
        time_start = time.monotonic()
        model_output, event = await generate()
        total_time = time.monotonic() - time_start
        if model_output.time:
            # we've already reported some of the waiting time in tenacity callbacks
            # any remaining waiting time will have been due to internal retry within
            # model providers, which we can get from:
            #    total_time - reported_waiting_time - model_call_time
            report_sample_waiting_time(
                total_time - reported_waiting_time - model_output.time
            )

        # return results
        return model_output, event

    def should_retry(self, ex: BaseException) -> bool:
        if isinstance(ex, Exception):
            # attempt timeout is always retried (we rely on `timeout`
            # and/or `max_retries` for termination)
            if isinstance(ex, AttemptTimeoutError):
                return True

            # check standard should_retry() method
            retry = self.api.should_retry(ex)
            if retry:
                report_http_retry()
                return True

            from inspect_ai.hooks._hooks import has_api_key_override

            if has_api_key_override():
                retry = self.api.is_auth_failure(ex)
                if retry:
                    report_http_retry()
                    return True

            # see if the API implements legacy is_rate_limit() method
            is_rate_limit = getattr(self.api, "is_rate_limit", None)
            if is_rate_limit:
                warn_once(
                    logger,
                    f"provider '{self.name}' implements deprecated is_rate_limit() method, "
                    + "please change to should_retry()",
                )
                retry = cast(bool, is_rate_limit(ex))
                if retry:
                    report_http_retry()
                    return True

        # no retry
        return False

    async def before_retry(self, ex: BaseException) -> None:
        if isinstance(ex, Exception) and self.api.is_auth_failure(ex):
            # close existing model instance
            await self.api.aclose()
            # re-initialize
            self.api.initialize()

    # function to verify that its okay to call model apis
    def verify_model_apis(self) -> None:
        if (
            os.getenv("INSPECT_DISABLE_MODEL_API", None) is not None
            and ModelName(self).api != "mockllm"
        ):
            raise RuntimeError("Model APIs disabled by INSPECT_DISABLE_MODEL_API")

    # semaphore for model generate requests. these can be shared across
    # instances of Model.  This is so that each distinct model endpoint/account
    # combination shares the semaphore -- i.e. if you had 3 instances
    # of a model class (e.g. attacker model, evaluated model, and grader
    # model) in an eval, they won't each get the full max_connections allocated
    # (which would likely cause the rate limit to be exceeded). conversely if
    # you are using distinct models/endpoints/accounts within an eval you should
    # be able get the full max_connections for each of them. subclasses can
    # override the _connection_key() argument to provide a scope within which
    # to enforce max_connections (e.g. by account/api_key, by endpoint, etc.)

    @contextlib.asynccontextmanager
    async def _connection_concurrency(
        self, config: GenerateConfig
    ) -> AsyncIterator[None]:
        """Get the appropriate connection semaphore for this model instance."""
        max_connections = (
            config.max_connections
            if config.max_connections
            else DEFAULT_MAX_CONNECTIONS_BATCH
            if config.batch
            else self.api.max_connections()
        )
        model_name = ModelName(self)
        async with concurrency(
            name=str(model_name),
            concurrency=max_connections,
            key=f"Model{self.api.connection_key()}",
        ):
            yield

    def _resolve_config(self, config: GenerateConfig | None) -> GenerateConfig:
        # base config for this model
        base_config = self.config

        # if we are the active_model then merge active generate config
        active_config = active_generate_config()
        if self == active_model():
            base_config = base_config.merge(active_config)

        # otherwise merge connection-oriented config so its inherited everywhere
        else:
            base_config = base_config.merge(
                GenerateConfig(
                    max_connections=active_config.max_connections,
                    max_retries=active_config.max_retries,
                    timeout=active_config.timeout,
                )
            )

        # merge passed config
        return base_config.merge(config or GenerateConfig())

    def _record_model_interaction(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
        cache: Literal["read", "write"] | None,
        output: ModelOutput | None = None,
        call: ModelCall | None = None,
    ) -> tuple[
        Callable[[ModelOutput | Exception, ModelCall | None], None],
        BaseModel,
    ]:
        from inspect_ai.event._model import ModelEvent
        from inspect_ai.log._transcript import transcript

        # create event and add it to the transcript
        model = str(self)
        event = ModelEvent(
            model=model,
            role=self.role,
            input=input,
            tools=tools,
            tool_choice=tool_choice,
            config=config,
            output=output if output else ModelOutput.from_content(model, ""),
            cache=cache,
            call=call,
            pending=output is None,
        )
        transcript()._event(event)

        # callable that can be used to update the interaction w/ output
        def complete(
            result: ModelOutput | Exception, updated_call: ModelCall | None
        ) -> None:
            # trace
            if isinstance(result, ModelOutput):
                if result.choices:
                    display_conversation_assistant(input, result.choices[0].message)
                event.output = result
            else:
                display_conversation_assistant_error(result)
                event.error = exception_message(result)
                traceback_text, traceback_ansi = format_traceback(
                    type(result), result, result.__traceback__
                )
                event.traceback = traceback_text
                event.traceback_ansi = traceback_ansi

            if updated_call is not None:
                event.call = updated_call

            if (
                isinstance(result, Exception)
                and event.call is not None
                and event.call.response is None
            ):
                # We try to set these in the individual providers' error handling, but we make a last
                # ditch effort here to set them if we don't have a response.
                if hasattr(result, "body"):
                    event.call.response = as_error_response(result.body)
                elif hasattr(result, "response"):
                    event.call.response = as_error_response(result.response)
                else:
                    event.call.response = as_error_response(str(result))

            event.pending = None
            transcript()._event_updated(event)

        # if we have output then complete it now
        if output:
            complete(output, call)

        return complete, event


class AttemptTimeoutError(RuntimeError):
    def __init__(self, timeout: int | None) -> None:
        super().__init__(f"attempt_timeout '{timeout or 0}' exceeded.")


class ModelName:
    r"""Model name (api and specific model served by the api).

    Can be used for structural pattern matching of models against
    various string specifications of models. Used primarily by
    tasks to allow them to condition their behavior on models or
    model families.

    String specifications can be fully specified (e.g. openai/gpt-4),
    partially specified by model name only (e.g. gpt-4) or even
    partially specified by a substring of model name (e.g. gpt).
    """

    def __init__(self, model: str | Model) -> None:
        """Create a ModelName.

        Args:
           model: Model to create name for.
        """
        if isinstance(model, str):
            (api, name) = self._parse_model(model)
            if api is None:
                raise ValueError("API not specified for model name")
            self.api = api
            self.name = name
        else:
            # registry names have a package prefix, strip it off
            name = registry_info(model.api).name
            parts = name.split("/")
            self.api = "/".join(parts[1:]) if len(parts) > 1 else name
            self.name = model.name

    def __eq__(self, pattern: object) -> bool:
        if isinstance(pattern, str):
            (api, name) = self._parse_model(pattern)
            if (api and api in self.api) and name in self.name:
                return True
            else:
                return name in self.name
        else:
            return False

    def __str__(self) -> str:
        return f"{self.api}/{self.name}"

    def _parse_model(self, model: str) -> tuple[str | None, str]:
        parts = model.split("/")
        if len(parts) > 1:
            return (parts[0], "/".join(parts[1:]))
        else:
            return (None, model)


def get_model(
    model: str | Model | None = None,
    *,
    role: str | None = None,
    default: str | Model | None = None,
    config: GenerateConfig = GenerateConfig(),
    base_url: str | None = None,
    api_key: str | None = None,
    memoize: bool = True,
    **model_args: Any,
) -> Model:
    """Get an instance of a model.

    Calls to get_model() are memoized (i.e. a call with the same arguments
    will return an existing instance of the model rather than creating a
    new one). You can disable this with `memoize=False`.

    If you prefer to immediately close models after use (as well as
    prevent caching) you can employ the async context manager built in
    to the `Model` class. For example:

    ```python
    async with get_model("openai/gpt-4o") as model:
        response = await model.generate("Say hello")
    ```

    In this case, the model client will be closed at the end of the
    context manager and will not be available in the get_model() cache.

    Args:
       model: Model specification.
          If `Model` is passed it is returned unmodified,
          if `None` is passed then the model currently being
          evaluated is returned (or if there is no evaluation
          then the model referred to by `INSPECT_EVAL_MODEL`).
       role: Optional named role for model (e.g. for roles specified
          at the task or eval level). Provide a `default` as a fallback
          in the case where the `role` hasn't been externally specified.
       default: Optional. Fallback model in case the specified
          `model` or `role` is not found.
       config: Configuration for model.
       base_url: Optional. Alternate base URL for model.
       api_key: Optional. API key for model.
       memoize: Use/store a cached version of the model based on
          the parameters to `get_model()`
       **model_args: Additional args to
          pass to model constructor.

    Returns:
        Model instance.

    """
    from inspect_ai.hooks._startup import init_hooks

    # start with seeing if a model was passed
    if isinstance(model, Model):
        return model

    # next see if this is the special "none" model
    if model == "none":
        model = "none/none"

    # resolve model role
    if role is not None:
        model_for_role = model_roles().get(role, None)
        if model_for_role is not None:
            return model_for_role

    # if a default was specified then use it as the model if
    # no model was passed
    if model is None:
        if isinstance(default, Model):
            if role is not None:
                default._set_role(role)
            return default
        else:
            model = default

    # now try finding an 'ambient' model (active or env var)
    if model is None:
        # return active_model if there is one
        active = active_model()
        if active:
            return active

        # return based on env var if there is one
        # (handle lists by taking the first model)
        model = os.getenv("INSPECT_EVAL_MODEL", None)
        if model is not None:
            model = model.split(",")[0]
        else:
            raise ValueError(
                "No model specified (and no model environment varible defined)"
            )

    # see if we can return a memoized model instance
    # (exclude mockllm since custom_outputs is an infinite generator)
    model_cache_key: str = ""  # for mypy below
    if model.startswith("mockllm/"):
        memoize = False
    if memoize:
        model_cache_key = (
            model
            + str(role)
            + config.model_dump_json(exclude_none=True)
            + str(base_url)
            + str(api_key)
            + str(to_jsonable_python(model_args, fallback=lambda _: None))
        )
        cached = cached_model(model_cache_key)
        if cached is not None:
            return cached

    # split model into api name and model name if necessary
    api_name = None
    original_model = model
    parts = model.split("/")
    if len(parts) > 1:
        api_name = parts[0]
        model = "/".join(parts[1:])

    # check for api_name matching unqualified name (package prefix not
    # required as modelapi providers are registred globally for ease of
    # use from the command line and .env files)
    def match_modelapi_type(info: RegistryInfo) -> bool:
        if info.type == "modelapi" and registry_unqualified_name(info) == api_name:
            return True
        else:
            return False

    # find a matching model type
    modelapi_types = registry_find(match_modelapi_type)
    if len(modelapi_types) > 0:
        # create the model (init_hooks here in case the model api
        # is being used as a stadalone model interface outside of evals)
        init_hooks()
        modelapi_type = cast(type[ModelAPI], modelapi_types[0])
        modelapi_instance = modelapi_type(
            model_name=model,
            base_url=base_url,
            api_key=api_key,
            config=config,
            **model_args,
        )
        m = Model(modelapi_instance, config, model_args)
        if role is not None:
            m._set_role(role)
        if memoize:
            _models[model_cache_key] = m
        return m
    else:
        if api_name is None:
            raise ValueError(
                f"Model name {original_model!r} should be in the format of <api_name>/<model_name>."
            )
        else:
            raise ValueError(
                f"Model API {api_name} of model {original_model!r} not recognized."
            )


# cache for memoization of get_model
_models: dict[str, Model] = {}


def cached_model(key: str) -> Model | None:
    # clean out context bound models before accessing the cache
    for k in list(_models.keys()):
        if _models[k]._context_bound:
            del _models[k]

    # read from the cache
    return _models.get(key, None)


def resolve_models(
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    config: GenerateConfig = GenerateConfig(),
) -> list[Model]:
    # resolve NotGiven to current INSPECT_EVAL_MODEL
    if isinstance(model, NotGiven):
        model = os.getenv("INSPECT_EVAL_MODEL", None)

    # resolve None to NoModel
    if model is None:
        return [get_model("none")]

    # reflect back a plain model
    if isinstance(model, Model):
        return [model]

    # helper to resolve model of various types
    def resolve_model(m: str | Model) -> Model:
        return get_model(
            model=m,
            base_url=model_base_url,
            config=config,
            **model_args,
        )

    # str to list
    if isinstance(model, str):
        model = [m.strip() for m in model.split(",")]

    # resolve models
    return [resolve_model(m) for m in model]


def simple_input_messages(
    input: list[ChatMessage],
    fold_system_message: Callable[[str, str], str] | None = None,
) -> list[ChatMessage]:
    """Transform input messages into a format compatible with more simplistic chat APIs.

    Collects up system messages and folds them into the first user message
    (according to a passed in folding function). Also collapses consecutive
    user messages (as many LLMs require an alternating structure)
    """
    # start by making a deep copy so our mutations don't propagate (e.g. end up in log)
    input = deepcopy(input)

    # aggregate system message from all system messages
    system_message = " ".join(
        [message.text for message in input if isinstance(message, ChatMessageSystem)]
    ).strip()

    # collect all non-system messages and collapse consecutive user messages
    messages: list[ChatMessage] = collapse_consecutive_user_messages(
        [message for message in input if not isinstance(message, ChatMessageSystem)]
    )

    # fold the system message into the first user message
    first_user_message = next(
        message for message in messages if isinstance(message, ChatMessageUser)
    )
    if fold_system_message:
        first_user_message.text = fold_system_message(
            first_user_message.text, system_message
        )
    else:
        first_user_message.text = f"{system_message}\n\n{first_user_message.text}"

    # all done!
    return messages


def resolve_reasoning_history(
    messages: list[ChatMessage],
    config: GenerateConfig,
    model_api: ModelAPI,
) -> list[ChatMessage]:
    # determine up front if we have any reasoning content
    have_reasoning = any(
        [
            isinstance(m, ChatMessageAssistant)
            and isinstance(m.content, list)
            and any([c for c in m.content if isinstance(c, ContentReasoning)])
            for m in messages
        ]
    )
    if not have_reasoning:
        return messages

    # determine reasoning history configuration
    reasoning_history = (
        config.reasoning_history if config.reasoning_history is not None else "auto"
    )

    # see if the provider is forcing a reasoning history
    force = model_api.force_reasoning_history()
    if force is not None:
        reasoning_history = force
    # if it's 'auto' then defer to the provider
    elif reasoning_history == "auto":
        reasoning_history = model_api.auto_reasoning_history()

    # generate a version of message history with the correct history
    if reasoning_history == "all":
        resolved_messages: list[ChatMessage] = messages
    else:
        found_last = False
        resolved_messages = []
        for message in reversed(messages):
            if isinstance(message, ChatMessageAssistant) and isinstance(
                message.content, list
            ):
                # is there reasoning in this message?
                has_reasoning = any(
                    isinstance(c, ContentReasoning) for c in message.content
                )
                # remove it unless we are in "last" mode and haven't yet found last
                if has_reasoning:
                    if reasoning_history == "none" or found_last:
                        message = message.model_copy(
                            update={
                                "content": [
                                    content
                                    for content in message.content
                                    if not isinstance(content, ContentReasoning)
                                ]
                            }
                        )
                    found_last = True

            resolved_messages.append(message)

        # reverse them back
        resolved_messages.reverse()

    # return messages
    return resolved_messages


def resolve_tool_model_input(
    tdefs: list[ToolDef], messages: list[ChatMessage], hints: ToolCallModelInputHints
) -> list[ChatMessage]:
    # filter on tooldefs that have a model input handler
    tdefs = [tdef for tdef in tdefs if tdef.model_input is not None]

    # bail if there are no handlers
    if len(tdefs) == 0:
        return messages

    # don't mutate the original messages
    messages = deepcopy(messages)

    # extract tool messages
    tool_messages = [
        message for message in messages if isinstance(message, ChatMessageTool)
    ]
    # run model_input handlers over all tool_messages with the same function name
    for tdef in tdefs:
        assert tdef.model_input
        # filter messages down to just this tool
        tdef_tool_messages = [
            message for message in tool_messages if message.function == tdef.name
        ]
        # call the function for each tool, passing the index, total, and content
        for index, message in enumerate(tdef_tool_messages):
            message.content = tdef.model_input(
                index, len(tool_messages), message.content, hints
            )

    # return modified messages
    return messages


def tool_result_images_as_user_message(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    """
    To conform to models lacking support for images in tool responses, create an alternate message history that moves images into a fabricated user message.

    Tool responses will have images replaced with "Image content is included below.", and the new user message will contain the images.
    """
    chat_messages, user_message_content, tool_call_ids = functools.reduce(
        tool_result_images_reducer,
        messages,
        (list[ChatMessage](), list[Content](), list[str]()),
    )
    # if the last message was a tool result, we may need to flush the pending stuff here
    return maybe_adding_user_message(chat_messages, user_message_content, tool_call_ids)


ImagesAccumulator = tuple[list[ChatMessage], list[Content], list[str]]
"""
ImagesAccumulator is a tuple containing three lists:
- The first list contains ChatMessages that are the result of processing.
- The second list contains ContentImages that need to be inserted into a fabricated user message.
- The third list contains the tool_call_id's associated with the tool responses.
"""


def tool_result_images_reducer(
    accum: ImagesAccumulator,
    message: ChatMessage,
) -> ImagesAccumulator:
    messages, pending_content, tool_call_ids = accum
    # if there are tool result images, pull them out into a ChatUserMessage
    if (
        isinstance(message, ChatMessageTool)
        and isinstance(message.content, list)
        and any([isinstance(c, ContentImage) for c in message.content])
    ):
        new_user_message_content, edited_tool_message_content = functools.reduce(
            tool_result_image_content_reducer,
            message.content,
            (list[Content](), list[Content]()),
        )

        return (
            messages
            + [
                ChatMessageTool(
                    id=message.id,
                    content=edited_tool_message_content,
                    tool_call_id=message.tool_call_id,
                    function=message.function,
                )
            ],
            pending_content + new_user_message_content,
            tool_call_ids + ([message.tool_call_id] if message.tool_call_id else []),
        )

    else:
        return (
            maybe_adding_user_message(messages, pending_content, tool_call_ids)
            + [message],
            [],
            [],
        )


ImageContentAccumulator = tuple[list[Content], list[Content]]
"""
ImageContentAccumulator is a tuple containing two lists of Content objects:
- The first list contains ContentImages that will be included in a fabricated user message.
- The second list contains modified content for the tool message with images replaced with text.
"""


def tool_result_image_content_reducer(
    acc: ImageContentAccumulator, content: Content
) -> ImageContentAccumulator:
    """
    Reduces the messages Content into two separate lists: one for a fabricated user message that will contain the images and one for modified tool message with the images replaced with text.

    Returns:
      ImageContentReducer: A tuple containing two lists of Content objects.
        - The first list contains the images that will be included in a fabricated user message.
        - The second list contains modified content for the tool message with images replaced with text.
    """
    new_user_message_content, edited_tool_message_content = acc
    if isinstance(content, ContentImage):
        return new_user_message_content + [content], edited_tool_message_content + [
            ContentText(text="Image content is included below.")
        ]

    else:
        return new_user_message_content, edited_tool_message_content + [content]


def maybe_adding_user_message(
    messages: list[ChatMessage], content: list[Content], tool_call_ids: list[str]
) -> list[ChatMessage]:
    """If content is empty, return messages, otherwise, create a new ChatMessageUser with it and return a new messages list with that message added."""
    return (
        messages + [ChatMessageUser(content=content, tool_call_id=tool_call_ids)]
        if content
        else messages
    )


# Functions to reduce consecutive user messages to a single user message -> required for some models
def collapse_consecutive_user_messages(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    return functools.reduce(user_message_reducer, messages, [])


# Functions to reduce consecutive assistant messages to a single user message -> required for some models
def collapse_consecutive_assistant_messages(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    return functools.reduce(assistant_message_reducer, messages, [])


def user_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
) -> list[ChatMessage]:
    return consecutive_message_reducer(messages, message, ChatMessageUser)


def assistant_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
) -> list[ChatMessage]:
    return consecutive_message_reducer(messages, message, ChatMessageAssistant)


def consecutive_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
    message_type: Type[ChatMessage],
) -> list[ChatMessage]:
    if (
        isinstance(message, message_type)
        and len(messages) > 0
        and isinstance(messages[-1], message_type)
    ):
        messages[-1] = combine_messages(messages[-1], message, message_type)
    else:
        messages.append(message)
    return messages


def combine_messages(
    a: ChatMessage, b: ChatMessage, message_type: Type[ChatMessage]
) -> ChatMessage:
    # TODO: Although unlikely to happen based on the current call sites, these
    # fabricated messages drop interesting fields from the source messages -
    # such as `internal_name`, `tool_calls`, etc.
    # To be more specific, since all `ChatMessageXxx` fields other than `id` and
    # `content` have default values, it's more the case that they're reset to
    # default values rather than dropped.

    # track combination
    metadata = {"combined_from": [a.id, b.id]}

    if isinstance(a.content, str) and isinstance(b.content, str):
        return message_type(content=f"{a.content}\n{b.content}", metadata=metadata)
    elif isinstance(a.content, list) and isinstance(b.content, list):
        return message_type(content=a.content + b.content, metadata=metadata)
    elif isinstance(a.content, str) and isinstance(b.content, list):
        return message_type(
            content=[ContentText(text=a.content), *b.content], metadata=metadata
        )
    elif isinstance(a.content, list) and isinstance(b.content, str):
        return message_type(
            content=a.content + [ContentText(text=b.content)], metadata=metadata
        )
    else:
        raise TypeError(
            f"Cannot combine messages with invalid content types: {a.content!r}, {b.content!r}"
        )


def log_model_retry(model_name: str, retry_state: RetryCallState) -> None:
    logger.log(
        HTTP,
        f"-> {model_name} retry {retry_state.attempt_number} (retrying in {retry_state.upcoming_sleep:,.0f} seconds)",
    )


def init_active_model(model: Model, config: GenerateConfig) -> None:
    active_model_context_var.set(model)
    set_active_generate_config(config)


def active_model() -> Model | None:
    """The model currently being evaluated.

    Returns:
       The model currently being evaluated.
    """
    return active_model_context_var.get(None)


def init_model_roles(roles: dict[str, Model]) -> None:
    _model_roles.set(roles)


def model_roles() -> dict[str, Model]:
    return _model_roles.get()


active_model_context_var: ContextVar[Model | None] = ContextVar("active_model")

_model_roles: ContextVar[dict[str, Model]] = ContextVar("model_roles", default={})


# shared contexts for asyncio tasks
def set_total_messages(input: str | list[ChatMessage]) -> None:
    from inspect_ai.log._samples import set_active_sample_total_messages

    total_messages = 1 if isinstance(input, str) else len(input)

    # set total messages
    set_active_sample_total_messages(total_messages)


def init_model_usage(initial_usage: dict[str, ModelUsage] | None = None) -> None:
    # explicit intialization
    if initial_usage is not None:
        model_usage_context_var.set(initial_usage)

    # default initialization (ignore if we've already been explicitly intialized)
    elif len(model_usage_context_var.get()) == 0:
        model_usage_context_var.set({})


def init_sample_model_usage() -> None:
    sample_model_usage_context_var.set({})


def record_and_check_model_usage(model: str, usage: ModelUsage) -> None:
    from inspect_ai.log._samples import (
        set_active_sample_total_cost,
        set_active_sample_total_tokens,
    )
    from inspect_ai.model._model_info import get_model_info

    # compute cost and set on usage before recording (so ModelUsage.__add__
    # accumulates it in the per-model usage dicts)
    info = get_model_info(model)
    total_cost: float | None = None
    # Note that we handle info=None here because None is currently a valid output of get_model_info (e.g. for mock models)
    if info is not None and info.cost is not None:
        total_cost = compute_model_cost(info.cost, usage)
        usage.total_cost = total_cost

    # record usage
    set_model_usage(model, usage, sample_model_usage_context_var.get(None))
    set_model_usage(model, usage, model_usage_context_var.get(None))
    record_model_usage(usage)

    # compute total tokens and update active sample
    total_tokens = sample_total_tokens()
    set_active_sample_total_tokens(total_tokens)
    check_token_limit()

    # record cost to limit tree and check
    if total_cost is not None:
        record_model_cost(total_cost)
        set_active_sample_total_cost(sample_total_cost())
        check_cost_limit()


def set_model_usage(
    model: str, usage: ModelUsage, model_usage: dict[str, ModelUsage] | None
) -> None:
    if model_usage is not None:
        total_usage = model_usage.get(model, ModelUsage())
        total_usage += usage
        model_usage[model] = total_usage


def model_usage() -> dict[str, ModelUsage]:
    return model_usage_context_var.get()


model_usage_context_var: ContextVar[dict[str, ModelUsage]] = ContextVar(
    "model_usage", default={}
)


def sample_model_usage() -> dict[str, ModelUsage]:
    return sample_model_usage_context_var.get()


def sample_total_tokens() -> int:
    total_tokens = [usage.total_tokens for usage in iter(sample_model_usage().values())]
    return sum(total_tokens)


sample_model_usage_context_var: ContextVar[dict[str, ModelUsage]] = ContextVar(
    "sample_model_usage", default={}
)


def compute_model_cost(cost_data: ModelCost, usage: ModelUsage) -> float:
    """Compute cost for a model call based on usage and cost data.

    Args:
        cost_data: Per-token pricing for the model.
        usage: Token counts for the call.

    Returns:
        Cost in dollars.
    """
    cost = usage.input_tokens * cost_data.input / 1_000_000
    cost += usage.output_tokens * cost_data.output / 1_000_000

    if usage.input_tokens_cache_write is not None:
        cost += usage.input_tokens_cache_write * cost_data.input_cache_write / 1_000_000
    if usage.input_tokens_cache_read is not None:
        cost += usage.input_tokens_cache_read * cost_data.input_cache_read / 1_000_000

    return cost


def sample_total_cost() -> float:
    """Get total cost across all models for the current sample."""
    return sum(
        usage.total_cost
        for usage in sample_model_usage().values()
        if usage.total_cost is not None
    )
