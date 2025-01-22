import asyncio
import logging
from typing import Any, Dict, List, Optional, TypedDict, Union, cast, Literal, get_args
from typing_extensions import override
import os
from functools import partial

import goodfire
from goodfire.api.client import Client as GoodfireClient
from goodfire.api.chat.interfaces import ChatMessage as GoodfireChatMessage
from goodfire.variants.variants import SUPPORTED_MODELS, Variant
from goodfire.api.chat.client import ChatAPI, ChatCompletion
from goodfire.api.features.client import FeaturesAPI

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version
from inspect_ai._util.content import Content, ContentText
from inspect_ai.tool import ToolChoice, ToolInfo

from inspect_ai.model._model import ModelAPI
from inspect_ai.model._model_output import ModelOutput, ModelUsage, ChatCompletionChoice
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._call_tools import Tool
from inspect_ai.model._providers.util import environment_prerequisite_error, model_base_url

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
    "meta-llama/Meta-Llama-3.1-8B-Instruct": "meta-llama/Meta-Llama-3.1-8B-Instruct",
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
    
    client: GoodfireClient
    model_name: str
    model_args: Dict[str, Any]
    variant: Variant

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        """Initialize the Goodfire API provider.
        
        Args:
            model_name: Name of the model to use
            base_url: Optional custom API base URL
            api_key: Optional API key (will check env vars if not provided)
            api_key_vars: Additional env vars to check for API key
            config: Generation config options
            **model_args: Additional arguments passed to goodfire.Client
        """
        # Initialize instance variables
        self.model_name = model_name
        self.model_args = model_args

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GOODFIRE_API_KEY],
            config=config,
            **model_args,
        )

        verify_required_version("Goodfire API", "goodfire", MIN_VERSION)

        # Get API key from environment if not provided
        if not self.api_key:
            self.api_key = os.environ.get(GOODFIRE_API_KEY)
        if not self.api_key:
            raise environment_prerequisite_error("Goodfire", GOODFIRE_API_KEY)

        # Format and validate model name
        if not model_name.startswith("meta-llama/"):
            self.model_name = f"meta-llama/{model_name}"

        supported_models = list(get_args(SUPPORTED_MODELS))
        if self.model_name not in supported_models:
            raise ValueError(f"Model {self.model_name} not supported. Supported models: {supported_models}")

        # Initialize client with remaining model args
        base_url_val = model_base_url(base_url, "GOODFIRE_BASE_URL")
        assert isinstance(base_url_val, str) or base_url_val is None
        self.client = GoodfireClient(
            api_key=self.api_key,
            base_url=base_url_val or DEFAULT_BASE_URL,
            **self.model_args,
        )

        # Initialize variant with specified name if provided
        variant_model = MODEL_MAP.get(self.model_name, "meta-llama/Meta-Llama-3.1-8B-Instruct")
        if variant_model not in get_args(SUPPORTED_MODELS):
            raise ValueError(f"Variant {variant_model} not supported. Supported variants: {list(get_args(SUPPORTED_MODELS))}")
        # NOTE: There's a type mismatch between Goodfire's runtime behavior and type hints
        # The docs show direct string usage: variant = goodfire.Variant("meta-llama/Meta-Llama-3-8B-Instruct")
        # But the type hints expect a Literal. We validate the model name above, so this is safe at runtime.
        # TODO: Consider creating an issue in Goodfire's repo about this type mismatch
        self.variant = Variant(variant_model)  # type: ignore

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

        return cast(GoodfireChatMessage, {
            "role": role,
            "content": content,
        })

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        """Check if exception is due to rate limiting."""
        return "rate_limit" in str(ex).lower()

    @override
    def connection_key(self) -> str:
        """Return key for connection pooling."""
        return f"goodfire:{self.api_key}"

    @override
    def max_tokens(self) -> int | None:
        """Return maximum tokens supported by model."""
        return DEFAULT_MAX_TOKENS

    @override
    def collapse_user_messages(self) -> bool:
        """Whether to collapse consecutive user messages."""
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        """Whether to collapse consecutive assistant messages."""
        return True

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
        response = self.client.chat.completions.create(**params)  # type: ignore[arg-type]
        response_dict = response.model_dump()

        # Create output with choices
        output = ModelOutput(
            model=self.model_name,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=response_dict["choices"][0]["message"]["content"]
                    ),
                    stop_reason="stop",  # Goodfire doesn't provide finish_reason
                )
            ],
        )

        # Add usage statistics if available
        if "usage" in response_dict:
            output.usage = ModelUsage(
                input_tokens=response_dict["usage"]["prompt_tokens"],
                output_tokens=response_dict["usage"]["completion_tokens"],
                total_tokens=response_dict["usage"]["total_tokens"],
            )

        return output

    @property
    def name(self) -> str:
        """Get provider name."""
        return "goodfire"

# Remove duplicate registration since it's handled in providers.py 