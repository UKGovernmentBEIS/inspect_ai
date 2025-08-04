# type: ignore

# NOTE: We need to type: ignore above because Goodfire has pinned all
# of its dependencies to exact versions, which means that when we
# install it in CI it breaks other packages (e.g. mistralai, google-genai)
# we have a PR to resolve this here: https://github.com/goodfire-ai/goodfire-sdk/pull/8

import os
from typing import Any, List, Literal, get_args

from goodfire import AsyncClient
from goodfire.api.chat.interfaces import ChatMessage as GoodfireChatMessage
from goodfire.api.exceptions import (
    InvalidRequestException,
    RateLimitException,
    ServerErrorException,
)
from goodfire.variants.variants import SUPPORTED_MODELS, Variant
from typing_extensions import override

from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from .util import environment_prerequisite_error, model_base_url

# Constants
GOODFIRE_API_KEY = "GOODFIRE_API_KEY"
DEFAULT_BASE_URL = "https://api.goodfire.ai"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 1.0  # Standard sampling temperature (baseline)
DEFAULT_TOP_P = 1.0  # No nucleus sampling truncation (baseline)


class GoodfireAPI(ModelAPI):
    """Goodfire API provider.

    This provider implements the Goodfire API for LLM inference. It supports:
    - Chat completions with standard message formats
    - Basic parameter controls (temperature, top_p, etc.)
    - Usage statistics tracking
    - Stop reason handling

    Does not currently support:
    - Tool calls
    - Feature analysis
    - Streaming responses

    Known limitations:
    - Limited role support (system/user/assistant only)
    - Tool messages converted to user messages
    """

    client: AsyncClient
    variant: Variant
    model_args: dict[str, Any]

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        """Initialize the Goodfire API provider.

        Args:
            model_name: Name of the model to use
            base_url: Optional custom API base URL
            api_key: Optional API key (will check env vars if not provided)
            config: Generation config options
            **model_args: Additional arguments passed to the API
        """
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOODFIRE_API_KEY],
            config=config,
        )

        # resolve api_key
        if not self.api_key:
            self.api_key = os.environ.get(GOODFIRE_API_KEY)
            if not self.api_key:
                raise environment_prerequisite_error("Goodfire", GOODFIRE_API_KEY)

        # Validate model name against supported models
        supported_models = list(get_args(SUPPORTED_MODELS))
        if self.model_name not in supported_models:
            raise ValueError(
                f"Model {self.model_name} not supported. Supported models: {supported_models}"
            )

        # Initialize client with minimal configuration
        base_url_val = model_base_url(base_url, "GOODFIRE_BASE_URL")
        assert isinstance(base_url_val, str) or base_url_val is None

        # Store model args for use in generate
        self.model_args = model_args

        self.client = AsyncClient(
            api_key=self.api_key,
            base_url=base_url_val or DEFAULT_BASE_URL,
        )

        # Initialize variant directly with model name
        self.variant = Variant(self.model_name)  # type: ignore

    def _to_goodfire_message(self, message: ChatMessage) -> GoodfireChatMessage:
        """Convert an Inspect message to a Goodfire message format.

        Args:
            message: The message to convert

        Returns:
            The converted message in Goodfire format

        Raises:
            ValueError: If the message type is unknown
        """
        role: Literal["system", "user", "assistant"] = "user"
        if isinstance(message, ChatMessageSystem):
            role = "system"
        elif isinstance(message, ChatMessageUser):
            role = "user"
        elif isinstance(message, ChatMessageAssistant):
            role = "assistant"
        elif isinstance(message, ChatMessageTool):
            role = "user"  # Convert tool messages to user messages
        else:
            raise ValueError(f"Unknown message type: {type(message)}")

        content = str(message.content)
        if isinstance(message, ChatMessageTool):
            content = f"Tool {message.function}: {content}"

        return GoodfireChatMessage(role=role, content=content)

    def handle_error(self, ex: Exception) -> ModelOutput | Exception:
        """Handle only errors that need special treatment for retry logic or model limits."""
        # Handle token/context length errors
        if isinstance(ex, InvalidRequestException):
            error_msg = str(ex).lower()
            if "context length" in error_msg or "max tokens" in error_msg:
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=str(ex),
                    stop_reason="model_length",
                    error=error_msg,
                )

        # Let all other errors propagate
        return ex

    @override
    def should_retry(self, ex: Exception) -> bool:
        """Check if exception is due to rate limiting."""
        return isinstance(ex, RateLimitException | ServerErrorException)

    @override
    def connection_key(self) -> str:
        """Return key for connection pooling."""
        return f"goodfire:{self.api_key}"

    @override
    def max_tokens(self) -> int | None:
        """Return maximum tokens supported by model."""
        return DEFAULT_MAX_TOKENS  # Let Goodfire's Variant handle model-specific limits

    async def generate(
        self,
        input: List[ChatMessage],
        tools: List[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
        *,
        cache: bool = True,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        """Generate output from the model."""
        # Convert messages and prepare request params
        messages = [self._to_goodfire_message(msg) for msg in input]
        # Build request parameters with type hints
        params: dict[str, Any] = {
            "model": self.variant.base_model,  # Use base_model instead of stringifying the Variant
            "messages": messages,
            "max_completion_tokens": int(config.max_tokens)
            if config.max_tokens
            else DEFAULT_MAX_TOKENS,
            "stream": False,
        }

        # Add generation parameters from config if not in model_args
        if "temperature" not in self.model_args and config.temperature is not None:
            params["temperature"] = float(config.temperature)
        elif "temperature" not in self.model_args:
            params["temperature"] = DEFAULT_TEMPERATURE

        if "top_p" not in self.model_args and config.top_p is not None:
            params["top_p"] = float(config.top_p)
        elif "top_p" not in self.model_args:
            params["top_p"] = DEFAULT_TOP_P

        # Add any additional model args (highest priority)
        api_params = {
            k: v
            for k, v in self.model_args.items()
            if k not in ["api_key", "base_url", "model_args"]
        }
        params.update(api_params)

        try:
            # Use native async client
            response = await self.client.chat.completions.create(**params)
            response_dict = response.model_dump()

            output = ModelOutput(
                model=self.model_name,
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            content=response_dict["choices"][0]["message"]["content"],
                            model=self.model_name,
                        ),
                        stop_reason="stop",
                    )
                ],
                usage=ModelUsage(**response_dict["usage"])
                if "usage" in response_dict
                else None,
            )
            model_call = ModelCall.create(request=params, response=response_dict)
            return (output, model_call)
        except Exception as ex:
            result = self.handle_error(ex)
            model_call = ModelCall.create(
                request=params,
                response={},  # Empty response for error case
            )
            return (result, model_call)

    @property
    def name(self) -> str:
        """Get provider name."""
        return "goodfire"
