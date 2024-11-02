import abc
import asyncio
import functools
import json
import logging
import os
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Callable, Literal, Type, cast

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    stop_never,
    wait_exponential_jitter,
)

from inspect_ai._util.constants import DEFAULT_MAX_CONNECTIONS
from inspect_ai._util.content import ContentText
from inspect_ai._util.hooks import init_hooks, override_api_key, send_telemetry
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_find,
    registry_info,
    registry_unqualified_name,
)
from inspect_ai._util.retry import log_rate_limit_retry
from inspect_ai.tool import Tool, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util import concurrency

from ._cache import CacheEntry, CachePolicy, cache_fetch, cache_store
from ._call_tools import disable_parallel_tools, tools_info
from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from ._generate_config import (
    GenerateConfig,
    active_generate_config,
    set_active_generate_config,
)
from ._model_call import ModelCall
from ._model_output import ModelOutput, ModelUsage
from ._trace import trace_assistant_message

logger = logging.getLogger(__name__)


class ModelAPI(abc.ABC):
    """Model API provider.

    If you are implementing a custom ModelAPI provider your `__init__()`
    method will also receive a `**model_args` parameter that will carry
    any custom `model_args` (or `-M` arguments from the CLI) specified
    by the user. You can then pass these on to the approriate place in
    your model initialisation code (for example, here is what many
    of the built-in providers do with the `model_args` passed to them:
    https://inspect.ai-safety-institute.org.uk/models.html#model-args)
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
        self.config = config

        # apply api key override
        for key in api_key_vars:
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

    @abc.abstractmethod
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
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
           ModelOutput or tuple[ModelOutput,ModelCall], the latter being
           useful if you want the underlying model API call logged as
           part of the ModelEvent.
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

    def tools_required(self) -> bool:
        """Any tool use in a message stream means that tools must be passed."""
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
        tools: list[Tool]
        | list[ToolDef]
        | list[ToolInfo]
        | list[Tool | ToolDef | ToolInfo] = [],
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig = GenerateConfig(),
        cache: bool | CachePolicy = False,
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
          input (str | list[ChatMessage]): Chat message
            input (if a `str` is passed it is converted
            to a `ChatMessageUser`).
          tools (list[Tool] | list[ToolDef] | list[ToolInfo]): Tools available for the
            model to call.
          tool_choice (ToolChoice): Directives to the model
            as to which tools to prefer.
          cache (bool | CachePolicy): Caching behavior for
            generate responses (defaults to no caching).
          config (GenerateConfig): Model configuration.

        Returns:
           ModelOutput
        """
        # base config for this model
        base_config = self.config

        # if we are the active_model then merge active generate config
        if self == active_model():
            base_config = base_config.merge(active_generate_config())

        # merge passed config
        config = base_config.merge(config)

        # provide max_tokens from the model api if required
        config.max_tokens = (
            config.max_tokens if config.max_tokens else self.api.max_tokens()
        )

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
        async with self._connection_concurrency(config):
            return await self._generate(
                input=input,
                tools=tools_info(tools),
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
        # in their output!). on the other hand, anthropic actually errors if
        # there are tools anywhere in the message stream and no tools defined.
        if tool_choice == "none" or len(tools) == 0:
            # allow model providers to implement a tools_required() method to
            # force tools to be passed (we need this for anthropic)
            if not self.api.tools_required():
                tools = []
            tool_choice = "none"

        # optionally collapse *consecutive* messages into one -
        # (some apis e.g. anthropic require this)
        if self.api.collapse_user_messages():
            input = collapse_consecutive_user_messages(input)

        if self.api.collapse_assistant_messages():
            input = collapse_consecutive_assistant_messages(input)

        # retry for rate limit errors (max of 30 minutes)
        @retry(
            wait=wait_exponential_jitter(max=(30 * 60), jitter=5),
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
                    await self._record_model_interaction(
                        input=input,
                        tools=tools,
                        tool_choice=tool_choice,
                        config=config,
                        output=existing,
                        cache="read",
                        call=None,
                    )
                    return existing

            result = await self.api.generate(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
            )
            if isinstance(result, tuple):
                output, call = result
            else:
                output = result
                call = None

            # write to transcript
            await self._record_model_interaction(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                output=output,
                cache="write" if cache else None,
                call=call,
            )

            # record usage
            if output.usage:
                record_model_usage(f"{self}", output.usage)
                await send_telemetry(
                    "model_usage",
                    json.dumps(dict(model=str(self), usage=output.usage.model_dump())),
                )

            if cache:
                cache_store(entry=cache_entry, output=output)

            return output

        # call the model
        model_output = await generate()

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
            name=f"{model_name.api}",
            concurrency=max_connections,
            key=f"Model{self.api.connection_key()}",
        )

    async def _record_model_interaction(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
        output: ModelOutput,
        cache: Literal["read", "write"] | None,
        call: ModelCall | None,
    ) -> None:
        from inspect_ai.log._transcript import ModelEvent, transcript

        trace_assistant_message(input, output.choices[0].message)

        transcript()._event(
            ModelEvent(
                model=str(self),
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                output=output,
                cache=cache,
                call=call,
            )
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
    config: GenerateConfig = GenerateConfig(),
    base_url: str | None = None,
    api_key: str | None = None,
    **model_args: Any,
) -> Model:
    """Get an instance of a model.

    Args:
       model (str | Model | None): Model specification.
         If `Model` is passed it is returned unmodified,
         if `None` is passed then the model currently being
         evaluated is returned (or if there is no evaluation
         then the model referred to by `INSPECT_EVAL_MODEL`).
       config (GenerateConfig): Configuration for model.
       base_url (str | None): Optional. Alternate base URL for model.
       api_key (str | None): Optional. API key for model.
       **model_args (dict[str,Any]): Additional args to
         pass to model constructor.

    Returns:
        Model instance.

    """
    # start with seeing if a model was passed
    if isinstance(model, Model):
        return model

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
            raise ValueError("No model specified (and no INSPECT_EVAL_MODEL defined)")

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
        # verify that model apis are allowed
        if (
            os.getenv("INSPECT_DISABLE_MODEL_API", None) is not None
            and api_name != "mockllm"
        ):
            raise RuntimeError("Model APIs disabled by INSPECT_DISABLE_MODEL_API")

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
        return Model(modelapi_instance, config)

    else:
        from_api = f" from {api_name}" if api_name else ""
        raise ValueError(f"Model name {model}{from_api} not recognized.")


def resolve_models(
    model: str | Model | list[str] | list[Model] | None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    config: GenerateConfig = GenerateConfig(),
) -> list[Model]:
    # reflect back a plain model
    if isinstance(model, Model):
        return [model]

    # helper to resolve model of various types
    def resolve_model(m: str | Model | None) -> Model:
        return get_model(
            model=m,
            base_url=model_base_url,
            config=config,
            **model_args,
        )

    # resolve None and str to list
    if model is None or isinstance(model, str):
        model = model or os.getenv("INSPECT_EVAL_MODEL", None)
        if model is None:
            raise ValueError("No model specified (and no INSPECT_EVAL_MODEL defined)")
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
        return message_type(content=[ContentText(text=a.content), *b.content])
    elif isinstance(a.content, list) and isinstance(b.content, str):
        return message_type(content=a.content + [ContentText(text=b.content)])
    else:
        raise TypeError(
            f"Cannot combine messages with invalid content types: {a.content!r}, {b.content!r}"
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


# shared contexts for asyncio tasks
active_model_context_var: ContextVar[Model] = ContextVar("active_model")


def init_model_usage() -> None:
    model_usage_context_var.set({})


def init_sample_model_usage() -> None:
    sample_model_usage_context_var.set({})


def record_model_usage(model: str, usage: ModelUsage) -> None:
    set_model_usage(model, usage, sample_model_usage_context_var.get(None))
    set_model_usage(model, usage, model_usage_context_var.get(None))


def set_model_usage(
    model: str, usage: ModelUsage, model_usage: dict[str, ModelUsage] | None
) -> None:
    if model_usage is not None:
        total_usage: ModelUsage | None = model_usage.get(model, None)
        if not total_usage:
            total_usage = ModelUsage()
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.total_tokens += usage.total_tokens
        if usage.input_tokens_cache_write is not None:
            if total_usage.input_tokens_cache_write is None:
                total_usage.input_tokens_cache_write = 0
            total_usage.input_tokens_cache_write += usage.input_tokens_cache_write
        if usage.input_tokens_cache_read is not None:
            if total_usage.input_tokens_cache_read is None:
                total_usage.input_tokens_cache_read = 0
            total_usage.input_tokens_cache_read += usage.input_tokens_cache_read

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
