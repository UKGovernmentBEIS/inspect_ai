import abc
import asyncio
import functools
import logging
import os
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Callable, Type, cast

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    stop_never,
    wait_exponential_jitter,
)

from inspect_ai._util.constants import DEFAULT_MAX_CONNECTIONS
from inspect_ai._util.entrypoints import ensure_entry_points
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_find,
    registry_info,
    registry_unqualified_name,
)
from inspect_ai._util.retry import log_rate_limit_retry
from inspect_ai.util import concurrency
from inspect_ai.util._context.concurrency import using_concurrency

from ._cache import CacheEntry, CachePolicy, cache_fetch, cache_store
from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from ._content import Content, ContentText
from ._generate_config import GenerateConfig
from ._model_output import ModelOutput, ModelUsage
from ._tool import ToolChoice, ToolFunction, ToolInfo

logger = logging.getLogger(__name__)


class ModelAPI(abc.ABC):
    """Model API provider."""

    def __init__(
        self, model_name: str, base_url: str | None, config: GenerateConfig
    ) -> None:
        """Create a model API provider.

        Args:
           model_name (str): Model name.
           base_url (str | None): Alternate base URL for model.
           config (GenerateConfig): Model configuration.
        """
        self.model_name = model_name
        self.base_url = base_url
        self.config = config

    @abc.abstractmethod
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
          input (str | list[ChatMessage]): Chat message
            input (if a `str` is passed it is converted
            to a `ChatUserMessage`).
          tools (list[ToolInfo]): Tools available for the
            model to call.
          tool_choice (ToolChoice): Directives to the model
            as to which tools to prefer.
          config (GenerateConfig): Model configuration.

        Returns:
           ModelOutput
        """
        ...

    def max_tokens(self) -> int | None:
        """Default max_tokens."""
        return None

    def max_connections(self) -> int:
        """Default max_connections."""
        return DEFAULT_MAX_CONNECTIONS

    def connection_key(self) -> str:
        """Scope for enforcement of max_connections."""
        return "default"

    def is_rate_limit(self, ex: BaseException) -> bool:
        """Is this exception a rate limit error."""
        return False

    def collapse_user_messages(self) -> bool:
        """Collapse consecutive user messages into a single message."""
        return False

    def collapse_assistant_messages(self) -> bool:
        """Collapse consecutive assistant messages into a single message."""
        return False


class Model:
    """Model interface."""

    def __init__(self, api: ModelAPI, config: GenerateConfig) -> None:
        """Create a model.

        Args:
           api (ModelAPI): Model API provider.
           config (GenerateConfig): Model configuration.
        """
        self.api = api
        self.config = config

        # if using the Model API standalone in a notebook this will
        # get hit before score() or eval() so we activate nest_asyncio
        platform_init()

    @property
    def name(self) -> str:
        """Model name."""
        return self.api.model_name

    def __str__(self) -> str:
        return f"{ModelName(self)}"

    async def generate(
        self,
        input: str | list[ChatMessage],
        tools: list[ToolInfo] = [],
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig = GenerateConfig(),
        cache: bool | CachePolicy = False,
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
          input (str | list[ChatMessage]): Chat message
            input (if a `str` is passed it is converted
            to a `ChatMessageUser`).
          tools (list[ToolInfo]): Tools available for the
            model to call.
          tool_choice (ToolChoice): Directives to the model
            as to which tools to prefer.
          cache (bool | CachePolicy): Caching behavior for
            generate responses (defaults to no caching).
          config (GenerateConfig): Model configuration.

        Returns:
           ModelOutput
        """
        # merge with config from init
        config = self.config.merge(config)

        # provide max_tokens from the model api if required
        config.max_tokens = (
            config.max_tokens if config.max_tokens else self.api.max_tokens()
        )

        # normalize input to chat
        if isinstance(input, str):
            input = [ChatMessageUser(content=input)]

        # insert any system message provided in config
        if config.system_message:
            input = [ChatMessageSystem(content=config.system_message)] + input

        # see if we have a connection semaphore (we won't if we
        # are running outside of an eval()). this is how we enforce
        # concurrency limits (max_connections) for the model
        if using_concurrency():
            async with self._connection_concurrency(config):
                return await self._generate(
                    input=input,
                    tools=tools,
                    tool_choice=tool_choice,
                    config=config,
                    cache=cache,
                )

        # no connection semaphore, just proceed straight to the call
        else:
            return await self._generate(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                cache=cache,
            )

    async def _generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
        cache: bool | CachePolicy = False,
    ) -> ModelOutput:
        # default to 'auto' for tool_choice (same as underlying model apis)
        tool_choice = tool_choice if tool_choice else "auto"

        # if we have a specific tool selected then filter out the others
        if isinstance(tool_choice, ToolFunction):
            tools = [tool for tool in tools if tool.name == tool_choice.name]

        # if tool_choice is "none" or if there are no tools then fully purge
        # the tools (as some models (e.g. openai and mistral) get confused
        # if you pass them tool definitions along with tool_choice == "none"
        # (they both 'semi' use the tool by placing the arguments in JSON
        # in their output!)
        if tool_choice == "none" or len(tools) == 0:
            tools = []
            tool_choice = "none"

        # filter out system messages for tools not in play on this pass
        if isinstance(input, list):
            # does this message belong to a tool not active on this pass?
            def is_inactive_tool_system_message(message: ChatMessage) -> bool:
                return (
                    isinstance(message, ChatMessageSystem)
                    and message.tool is not None
                    and (
                        tool_choice == "none"
                        or message.tool not in [tool.name for tool in tools]
                    )
                )

            # filter out inactive tool system messages
            input = [
                message
                for message in input
                if not is_inactive_tool_system_message(message)
            ]

            # optionally collapse *consecutive* messages into one - some apis e.g. anthropic require this
            if self.api.collapse_user_messages():
                input = collapse_consecutive_user_messages(input)

            if self.api.collapse_assistant_messages():
                input = collapse_consecutive_assistant_messages(input)

        # retry for rate limit errors
        @retry(
            wait=wait_exponential_jitter(jitter=5),
            retry=retry_if_exception(self.api.is_rate_limit),
            stop=(
                (
                    stop_after_delay(config.timeout)
                    | stop_after_attempt(config.max_retries)
                )
                if config.timeout and config.max_retries
                else (
                    stop_after_delay(config.timeout)
                    if config.timeout
                    else (
                        stop_after_attempt(config.max_retries)
                        if config.max_retries
                        else stop_never
                    )
                )
            ),
            before_sleep=functools.partial(log_rate_limit_retry, self.api.model_name),
        )
        async def generate() -> ModelOutput:
            if cache:
                if isinstance(cache, CachePolicy):
                    policy = cache
                else:
                    policy = CachePolicy()

                cache_entry = CacheEntry(
                    base_url=self.api.base_url,
                    config=deepcopy(config),
                    input=input,
                    model=str(self),
                    policy=policy,
                    tool_choice=tool_choice,
                    tools=tools,
                )
                existing = cache_fetch(cache_entry)
                if isinstance(existing, ModelOutput):
                    return existing

            output = await self.api.generate(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
            )

            if cache:
                cache_store(entry=cache_entry, output=output)

            return output

        # call the model
        model_output = await generate()

        # record usage
        if model_output.usage:
            record_model_usage(f"{self}", model_output.usage)

        # return results
        return model_output

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

    def _connection_concurrency(self, config: GenerateConfig) -> asyncio.Semaphore:
        """Get the appropriate connection semaphore for this model instance."""
        max_connections = (
            config.max_connections
            if config.max_connections
            else self.api.max_connections()
        )
        model_name = ModelName(self)
        return concurrency(
            name=f"{model_name.api}/{model_name.name}",
            concurrency=max_connections,
            key=f"Model{self.api.connection_key()}",
        )


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
           model: (str | Model): Model to create name for.
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
            self.api = "/".join(parts[1:]) if len(parts) else name
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
    config: GenerateConfig = GenerateConfig(),
    base_url: str | None = None,
    **model_args: Any,
) -> Model:
    """Get an instance of a model.

    Args:
       model (str | Model | None): Model specification.
         If `Model` is passed it is returned unmodified,
         if `None` is passed then the model currently being
         evaluated is returned (or if there is no evaluation
         then the model referred to by `INSPECT_MODEL_NAME`).
       config (GenerationConfig): Configuration for model.
       base_url (str | None): Optional. Alternate base URL for model.
       **model_args (dict[str,Any]): Additional args to
         pass to model constructor.

    Returns:
        Model instance.

    """
    # if the model is None then use the current model from our async
    # context, else try to use INSPECT_EVAL_MODEL (or the legacy INSPECT_MODEL_NAME)
    model = (
        model
        or active_model()
        or os.getenv("INSPECT_EVAL_MODEL", None)
        or os.getenv("INSPECT_MODEL_NAME", None)
    )
    if model is None:
        raise ValueError("No model specified (and no INSPECT_EVAL_MODEL defined)")

    # reflect back model -- we take model as a convenience so that
    # function that accept str | Model can always call get_model and
    # have it resolve correctly (even if trivially)
    if isinstance(model, Model):
        return model

    # ensure that inspect model provider extensions are loaded
    ensure_entry_points()

    # split model into api name and model name if necessary
    api_name = None
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
        modelapi_type = cast(type[ModelAPI], modelapi_types[0])
        modelapi_instance = modelapi_type(
            model_name=model, base_url=base_url, config=config, **model_args
        )
        return Model(modelapi_instance, config)

    else:
        from_api = f" from {api_name}" if api_name else ""
        raise ValueError(f"Model name {model}{from_api} not recognized.")


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
    if isinstance(a.content, str) and isinstance(b.content, str):
        return message_type(content=f"{a.content}\n{b.content}")
    elif isinstance(a.content, list) and isinstance(b.content, list):
        return message_type(content=a.content + b.content)
    elif isinstance(a.content, str) and isinstance(b.content, list):
        return message_type(content=b.content + [ContentText(text=a.content)])
    else:
        content: list[Content] = [ContentText(text=a.text)]
        content.extend(cast(list[Content], b.content))
        return message_type(content=content)


def init_async_context_model(model: Model) -> None:
    active_model_context_var.set(model)
    init_model_usage()


def active_model() -> Model | None:
    """The model currently being evaluated.

    Returns:
       The model currently being evaluated.
    """
    return active_model_context_var.get(None)


# shared contexts for asyncio tasks
active_model_context_var: ContextVar[Model] = ContextVar("active_model")


def init_model_usage() -> None:
    model_usage_context_var.set({})


def record_model_usage(model: str, usage: ModelUsage) -> None:
    model_usage = model_usage_context_var.get(None)
    if model_usage is not None:
        total_usage = model_usage.get(model, None)
        if not total_usage:
            total_usage = ModelUsage()
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.total_tokens += usage.total_tokens
        model_usage[model] = total_usage


def collect_model_usage() -> dict[str, ModelUsage]:
    usage = model_usage_context_var.get()
    model_usage_context_var.set({})
    return usage


model_usage_context_var: ContextVar[dict[str, ModelUsage]] = ContextVar("model_usage")
