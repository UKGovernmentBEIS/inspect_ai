import logging
from typing import Any, Dict, List, Optional, TypedDict, Union, cast, Literal, get_args
from typing_extensions import TypeAlias
import os

import goodfire
from goodfire.api.chat.interfaces import ChatMessage as GoodfireChatMessage
from goodfire.variants.variants import SUPPORTED_MODELS, Variant
from goodfire.api.chat.client import ChatAPI, ChatCompletion
from goodfire.api.features.client import FeaturesAPI

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version
from inspect_ai._util.content import Content, ContentText
from inspect_ai.tool import ToolChoice, ToolInfo

from .._model import ModelAPI
from .._model_output import ModelOutput, ModelUsage
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._call_tools import Tool
from .util import environment_prerequisite_error, model_base_url

logger = logging.getLogger(__name__)

# Constants
GOODFIRE_API_KEY = "GOODFIRE_API_KEY"
MIN_VERSION = "0.2.5"
DEFAULT_BASE_URL = "https://api.goodfire.ai"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_CONNECTIONS = 10

# Supported model mapping
MODEL_MAP = {
    "meta-llama/Meta-Llama-3-8B-Instruct": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct": "meta-llama/Llama-3.3-70B-Instruct",
}

class GoodfireAPI(ModelAPI):
    """Goodfire API provider.
    
    This provider implements the Goodfire API for LLM inference. It supports:
    - Chat completions with standard message formats
    - Basic parameter controls (temperature, top_p, etc.)
    - Usage statistics tracking
    
    Does not currently support:
    - Tool calls
    - Feature analysis
    - Streaming responses
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
        **kwargs: Any,
    ) -> None:
        """Initialize the Goodfire API provider.
        
        Args:
            model_name: Name of the model to use
            base_url: Optional custom API base URL
            api_key: Optional API key (will check env vars if not provided)
            api_key_vars: Additional env vars to check for API key
            config: Generation config options
        """
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOODFIRE_API_KEY],
            config=config,
            **kwargs,
        )

        verify_required_version("Goodfire API", "goodfire", MIN_VERSION)

        # Get API key from environment if not provided
        if not self.api_key:
            self.api_key = os.environ.get(GOODFIRE_API_KEY)
        if not self.api_key:
            raise environment_prerequisite_error("Goodfire", GOODFIRE_API_KEY)

        # Format and validate model name
        if not model_name.startswith("meta-llama/"):
            model_name = f"meta-llama/{model_name}"

        supported_models = list(get_args(SUPPORTED_MODELS))
        if model_name not in supported_models:
            raise ValueError(f"Model {model_name} not supported. Supported models: {supported_models}")

        # Initialize client
        base_url_val = model_base_url(base_url, "GOODFIRE_BASE_URL") 
        assert isinstance(base_url_val, str) or base_url_val is None
        self.client = goodfire.Client(
            api_key=self.api_key,
            base_url=base_url_val or DEFAULT_BASE_URL,
        )
        self.model_name = model_name

        # Initialize variant
        variant_model = MODEL_MAP.get(model_name, "meta-llama/Meta-Llama-3.1-8B-Instruct")
        self.variant = Variant(variant_model)

        # Feature analysis not yet supported
        self.feature_analysis = False
        self.feature_threshold = 0.5

    async def generate(
        self,
        input: List[ChatMessage],
        tools: List[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
        *,
        cache: bool = True,
    ) -> ModelOutput:
        """Generate output from the model.

        Args:
            input: List of chat messages for the conversation
            tools: Available tools (not currently supported)
            tool_choice: Tool selection directive (not currently supported) 
            config: Generation parameters
            cache: Whether to use response caching

        Returns:
            ModelOutput containing the generated response and usage statistics
        """
        try:
            # Convert messages and prepare request params
            messages = [self._to_goodfire_message(msg) for msg in input]
            params = {
                "model": self.model_name,
                "messages": messages,
                "max_completion_tokens": int(config.max_tokens) if config.max_tokens is not None else DEFAULT_MAX_TOKENS,
                "temperature": float(config.temperature) if config.temperature is not None else DEFAULT_TEMPERATURE,
                "top_p": float(config.top_p) if config.top_p is not None else DEFAULT_TOP_P,
                "stream": False,
            }

            # Make API request and convert response to dict
            response = self.client.chat.completions.create(**params)  # type: ignore
            response_dict = response.model_dump()

            # Create output with main content
            output = ModelOutput.from_content(
                model=self.model_name,
                content=response_dict["choices"][0]["message"]["content"],
                stop_reason="stop",  # Goodfire doesn't provide finish_reason
            )

            # Add usage statistics if available
            if "usage" in response_dict:
                output.usage = ModelUsage(
                    input_tokens=response_dict["usage"]["prompt_tokens"],
                    output_tokens=response_dict["usage"]["completion_tokens"],
                    total_tokens=response_dict["usage"]["total_tokens"],
                )

            return output

        except Exception as e:
            logger.error(f"Error in generate: {str(e)}", exc_info=True)
            raise

    def _to_goodfire_message(self, message: ChatMessage) -> GoodfireChatMessage:
        """Convert an Inspect message to a Goodfire message format.
        
        Special handling:
        - Tool messages are converted to user messages (not yet supported)
        - Tool call info is preserved in the message content for future compatibility
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

        return cast(GoodfireChatMessage, {
            "role": role,
            "content": content,
        })

    @property
    def name(self) -> str:
        """Get provider name."""
        return "goodfire"

    def max_tokens(self) -> Optional[int]:
        """Return maximum tokens supported by model."""
        return DEFAULT_MAX_TOKENS

    def max_connections(self) -> int:
        """Return maximum concurrent connections."""
        return DEFAULT_MAX_CONNECTIONS

    def connection_key(self) -> str:
        """Return key for connection pooling."""
        return f"goodfire:{self.api_key}"

    def is_rate_limit(self, ex: BaseException) -> bool:
        """Check if exception is due to rate limiting."""
        return "rate_limit" in str(ex).lower()

    def collapse_user_messages(self) -> bool:
        """Whether to collapse consecutive user messages."""
        return True

    def collapse_assistant_messages(self) -> bool:
        """Whether to collapse consecutive assistant messages."""
        return True

    def tools_required(self) -> bool:
        """Whether tools are required."""
        return False

    def tool_result_images(self) -> bool:
        """Whether tool results can contain images."""
        return False

# Remove duplicate registration since it's handled in providers.py 