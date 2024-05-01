import abc
import asyncio
import functools
import os
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Callable, Literal, Union, cast

from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    stop_never,
    wait_exponential_jitter,
)
from typing_extensions import TypedDict

from inspect_ai._util.constants import (
    DEFAULT_MAX_CONNECTIONS,
    PKG_NAME,
)
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import RegistryInfo, registry_find, registry_info
from inspect_ai._util.retry import log_rate_limit_retry
from inspect_ai.util import concurrency
from inspect_ai.util._context.concurrency import using_concurrency

from ._tool import ToolCall, ToolChoice, ToolFunction, ToolInfo


class GenerateConfigArgs(TypedDict, total=False):
    """Type for kwargs that selectively override GenerateConfig."""

    max_retries: int | None
    """Maximum number of times to retry request (defaults to 5)."""

    timeout: int | None
    """Request timeout (in seconds)."""

    max_connections: int | None
    """Maximum number of concurrent connections to Model API (default is model specific)."""

    system_message: str | None
    """Override the default system message."""

    max_tokens: int | None
    """The maximum number of tokens that can be generated in the completion (default is model specific)."""

    top_p: float | None
    """An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass."""

    temperature: float | None
    """What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic."""

    stop_seqs: list[str] | None
    """Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence."""

    best_of: int | None
    """Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). OpenAI only."""

    frequency_penalty: float | None
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI only."""

    presence_penalty: float | None
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI only."""

    logit_bias: dict[int, float] | None
    """Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10"). OpenAI only."""

    seed: int | None
    """Random seed. OpenAI only. OpenAI and Mistral only."""

    suffix: str | None
    """The suffix that comes after a completion of inserted text. OpenAI only."""

    top_k: int | None
    """Randomly sample the next word from the top_k most likely next words. Anthropic, Google, and HuggingFace only."""

    num_choices: int | None
    """How many chat completion choices to generate for each input message. Open AI, Google, and TogetherAI only."""

    logprobs: bool | None
    """Return log probabilities of the output tokens. OpenAI and TogetherAI only."""

    top_logprobs: int | None
    """Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI only."""


class GenerateConfig(BaseModel):
    """Base class for model generation configs."""

    max_retries: int | None = Field(default=None)
    """Maximum number of times to retry request (defaults to 5)."""

    timeout: int | None = Field(default=None)
    """Request timeout (in seconds)."""

    max_connections: int | None = Field(default=None)
    """Maximum number of concurrent connections to Model API (default is model specific)."""

    system_message: str | None = Field(default=None)
    """Override the default system message."""

    max_tokens: int | None = Field(default=None)
    """The maximum number of tokens that can be generated in the completion (default is model specific)."""

    top_p: float | None = Field(default=None)
    """An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass."""

    temperature: float | None = Field(default=None)
    """What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic."""

    stop_seqs: list[str] | None = Field(default=None)
    """Sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence."""

    best_of: int | None = Field(default=None)
    """Generates best_of completions server-side and returns the 'best' (the one with the highest log probability per token). OpenAI only."""

    frequency_penalty: float | None = Field(default=None)
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the model's likelihood to repeat the same line verbatim. OpenAI only."""

    presence_penalty: float | None = Field(default=None)
    """Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model's likelihood to talk about new topics. OpenAI only."""

    logit_bias: dict[int, float] | None = Field(default=None)
    """Map token Ids to an associated bias value from -100 to 100 (e.g. "42=10,43=-10"). OpenAI only."""

    seed: int | None = Field(default=None)
    """Random seed. OpenAI only. OpenAI and Mistral only."""

    suffix: str | None = Field(default=None)
    """The suffix that comes after a completion of inserted text. OpenAI only."""

    top_k: int | None = Field(default=None)
    """Randomly sample the next word from the top_k most likely next words. Anthropic, Google, and HuggingFace only."""

    num_choices: int | None = Field(default=None)
    """How many chat completion choices to generate for each input message. Open AI, Google, and TogetherAI only."""

    logprobs: bool | None = Field(default=None)
    """Return log probabilities of the output tokens. OpenAI and TogetherAI only."""

    top_logprobs: int | None = Field(default=None)
    """Number of most likely tokens (0-20) to return at each token position, each with an associated log probability. OpenAI only."""

    def merge(
        self, other: Union["GenerateConfig", GenerateConfigArgs]
    ) -> "GenerateConfig":
        """Merge another model configuration into this one.

        Args:
           other (Union[GenerateConfig, GenerateConfigArgs]):
              Configuration to merge.

        Returns:
           Merged configuration.
        """
        if not isinstance(other, GenerateConfig):
            other = GenerateConfig(**other)
        config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
        config = deepcopy(self)
        for key in config_keys:
            value = getattr(other, key, None)
            if value is not None:
                setattr(config, key, value)
        return config


class ContentText(BaseModel):
    type: Literal["text"] = Field(default="text")
    """Type."""

    text: str
    """Text content."""


class ContentImage(BaseModel):
    type: Literal["image"] = Field(default="image")
    """Type."""

    image: str
    """Either a URL of the image or the base64 encoded image data."""

    detail: Literal["auto", "low", "high"] = Field(default="auto")
    """Specifies the detail level of the image.

    Currently only supported for OpenAI. Learn more in the
    [Vision guide](https://platform.openai.com/docs/guides/vision/low-or-high-fidelity-image-understanding).
    """


Content = Union[ContentText, ContentImage]
"""Content sent to or received from a model."""


class ChatMessageBase(BaseModel):
    content: str | list[Content]
    """Content (simple string or list of string|image content)"""

    source: Literal["input", "generate"] | None = Field(default=None)
    """Source of message."""

    @property
    def text(self) -> str:
        """Get the text content of this message.

        ChatMessage content is very general and can contain either
        a simple text value or a list of content parts (each of which
        can either be text or an image). Solvers (e.g. for prompt
        engineering) often need to interact with chat messages with
        the assumption that they are a simple string. The text
        property returns either the plain str content, or if the
        content is a list of text and images, the text items
        concatenated together (separated by newline)

        Returns: Text content of `ChatMessage` If this message does
          not have text content then "" is returned.
        """
        if isinstance(self.content, str):
            return self.content
        else:
            all_text = [
                content.text for content in self.content if content.type == "text"
            ]
            return "\n".join(all_text)

    @text.setter
    def text(self, text: str) -> None:
        """Set the primary text content for this message.

        ChatMessage content is very general and can contain either
        a simple text value or a list of content parts (each of which
        can either be text or an image). Solvers (e.g. for prompt
        engineering) often need to interact with chat messages with
        the assumption that they are a simple string. The text property
        sets text either to content directly (if it is a `str`) or to
        the first text content item in the message (inserting one at
        the beginning if necessary). If there are multiple text content
        items in the message then after the set there will be only
        one remaining (image content will remain).
        """
        if isinstance(self.content, str):
            self.content = text
        else:
            all_images = [
                content for content in self.content if content.type == "image"
            ]
            self.content = [ContentText(text=text)] + all_images


class ChatMessageSystem(ChatMessageBase):
    role: Literal["system"] = Field(default="system")
    """Conversation role."""

    tool: str | None = Field(default=None)
    """Tool that injected this message."""


class ChatMessageUser(ChatMessageBase):
    role: Literal["user"] = Field(default="user")
    """Conversation role."""


class ChatMessageAssistant(ChatMessageBase):
    role: Literal["assistant"] = Field(default="assistant")
    """Conversation role."""

    tool_calls: list[ToolCall] | None = Field(default=None)
    """Tool calls made by the model."""


class ChatMessageTool(ChatMessageBase):
    role: Literal["tool"] = Field(default="tool")
    """Conversation role."""

    tool_call_id: str | None = Field(default=None)
    """ID of tool call."""

    tool_error: str | None = Field(default=None)
    """Error calling tool."""


ChatMessage = Union[
    ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool
]
"""Message in a chat conversation"""


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0)
    """Total input tokens used."""

    output_tokens: int = Field(default=0)
    """Total output tokens used."""

    total_tokens: int = Field(default=0)
    """Total tokens used."""


StopReason = Literal["stop", "length", "tool_calls", "content_filter", "unknown"]
"""Reason that the model stopped generating."""


class ChatCompletionChoice(BaseModel):
    message: ChatMessageAssistant
    """Assistent message."""

    stop_reason: StopReason = Field(default="unknown")
    """Reason that the model stopped generating."""

    logprobs: dict[str, Any] | None = Field(default=None)
    """Logprobs."""


class ModelOutput(BaseModel):
    model: str = Field(default="")
    """Model used for generation."""

    choices: list[ChatCompletionChoice] = Field(default=[])
    """Completion choices."""

    usage: ModelUsage | None = Field(default=None)
    """Model token usage"""

    error: str | None = Field(default=None)
    """Error message in the case of content moderation refusals."""

    @property
    def completion(self) -> str:
        """Text of first message choice text."""
        if len(self.choices) > 0:
            return self.choices[0].message.text
        else:
            return ""

    @completion.setter
    def completion(self, completion: str) -> None:
        """Set the text of the first message choice.

        Args:
          completion (str): Text for first message.
        """
        if len(self.choices) > 0:
            self.choices[0].message.text = completion
        else:
            self.choices.append(ChatCompletionChoice(
                message = ChatMessageAssistant(content = completion),
                stop_reason="stop"
            ))

    @staticmethod
    def from_content(
        model: str,
        content: str,
        stop_reason: StopReason = "stop",
        error: str | None = None,
    ) -> "ModelOutput":
        """Convenient method to create ModelOutput from simple text content."""
        return ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content=content, source="generate"),
                    stop_reason=stop_reason,
                )
            ],
            error=error,
        )


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
            input (if a `str` is passed it is convereted
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
        """Default max_tokens for this Model API."""
        return None

    def max_connections(self) -> int:
        """Default max_connections for this Model API."""
        return DEFAULT_MAX_CONNECTIONS

    def connection_key(self) -> str:
        """Key that defines the scope for enforcement of max_connections."""
        return "default"

    def is_rate_limit(self, ex: BaseException) -> bool:
        """Check whether an exception should be considered a rate limit error."""
        return False

    def collapse_user_messages(self) -> bool:
        """Should consecutive user messages be collapsed into a single message."""
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
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
          input (str | list[ChatMessage]): Chat message
            input (if a `str` is passed it is convereted
            to a `ChatUserMessage`).
          tools (list[ToolInfo]): Tools available for the
            model to call.
          tool_choice (ToolChoice): Directives to the model
            as to which tools to prefer.
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
            input.insert(0, ChatMessageSystem(content=config.system_message))

        # see if we have a connection semaphore (we won't if we
        # are running outside of an eval()). this is how we enforce
        # concurrency limits (max_connections) for the model
        if using_concurrency():
            async with self._connection_concurrency(config):
                return await self._generate(input, tools, tool_choice, config)

        # no connection semaphore, just proceed straight ot the call
        else:
            return await self._generate(input, tools, tool_choice, config)

    async def _generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
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

            # optionally collapse *consecutive* user messages into one - some apis eg anthropic require this
            if self.api.collapse_user_messages():
                input = collapse_consecutive_user_messages(input)

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
            return await self.api.generate(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
            )

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
        """Get the appropiate connection semaphore for this model instance."""
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
    model famillies.

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
    **model_args: dict[str, Any],
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

    # split model into api name and model name if necessary
    api_name = None
    parts = model.split("/")
    if len(parts) > 1:
        api_name = parts[0]
        model = "/".join(parts[1:])

    # predicate to match model
    def match_model(info: RegistryInfo) -> bool:
        # strip package name (we use the 'api' as the namespace, we will
        # introduce package scoping if it proves necessary)
        if info.type == "modelapi":
            # model patterns for this provider
            models = info.metadata.get("models", [])

            # if there is an api_name explicitly specified that
            # matches the registered api then trust the model name
            # TODO: this is ugly, we need to clarify the relationship
            # and registraiton semantics of pkg -> provider -> model
            if (
                info.name == api_name
                or info.name.replace(f"{PKG_NAME}/", "") == api_name
            ):
                return True
            # otherwise check for a name match
            else:
                return len([name for name in models if name in model]) > 0
        else:
            return False

    # find a matching model type
    model_types = registry_find(match_model)
    if len(model_types) > 0:
        modelapi_type = cast(type[ModelAPI], model_types[0])
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


def user_message_reducer(
    messages: list[ChatMessage],
    message: ChatMessage,
) -> list[ChatMessage]:
    if (
        isinstance(message, ChatMessageUser)
        and len(messages) > 0
        and isinstance(messages[-1], ChatMessageUser)
    ):
        messages[-1] = combine_user_messages(messages[-1], message)
    else:
        messages.append(message)
    return messages


def combine_user_messages(a: ChatMessageUser, b: ChatMessageUser) -> ChatMessageUser:
    if isinstance(a.content, str) and isinstance(b.content, str):
        return ChatMessageUser(content=f"{a.content}\n{b.content}")
    elif isinstance(a.content, list) and isinstance(b.content, list):
        return ChatMessageUser(content=a.content + b.content)
    elif isinstance(a.content, str) and isinstance(b.content, list):
        return ChatMessageUser(content=b.content + [ContentText(text=a.content)])
    else:
        content: list[Content] = [ContentText(text=a.text)]
        content.extend(cast(list[Content], b.content))
        return ChatMessageUser(content=content)


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
