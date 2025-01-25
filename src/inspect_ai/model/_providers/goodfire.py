import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, TypedDict, Union, cast, Literal, get_args
from typing_extensions import override
from functools import partial

import goodfire
import httpx
from goodfire import AsyncClient
from goodfire.api.chat.interfaces import ChatMessage as GoodfireChatMessage
from goodfire.variants.variants import SUPPORTED_MODELS, Variant
from goodfire.api.chat.client import ChatAPI, ChatCompletion
from goodfire.api.features.client import FeaturesAPI

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.content import Content, ContentText
from inspect_ai.tool import ToolChoice, ToolInfo

from .._model_call import ModelCall
from .._model import ModelAPI
from .._model_output import (
    ModelOutput,
    ModelUsage,
    ChatCompletionChoice,
    StopReason,
)
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
DEFAULT_BASE_URL = "https://api.goodfire.ai"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 1.0  # Standard sampling temperature (baseline)
DEFAULT_TOP_P = 1.0  # No nucleus sampling truncation (baseline)
DEFAULT_MAX_CONNECTIONS = 10
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 60.0

# Note: We don't need MODEL_MAP since Goodfire maintains SUPPORTED_MODELS

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
    
    Known limitations:
    - No finish_reason in responses
    - Limited role support (system/user/assistant only)
    - Tool messages converted to user messages
    """
    
    client: AsyncClient
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
            **model_args: Additional arguments passed to goodfire.AsyncClient
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

        # Get API key from environment if not provided
        if not self.api_key:
            self.api_key = os.environ.get(GOODFIRE_API_KEY)
        if not self.api_key:
            raise environment_prerequisite_error("Goodfire", GOODFIRE_API_KEY)

        # Validate model name against supported models
        supported_models = list(get_args(SUPPORTED_MODELS))
        if self.model_name not in supported_models:
            raise ValueError(f"Model {self.model_name} not supported. Supported models: {supported_models}")

        # Initialize client with remaining model args
        base_url_val = model_base_url(base_url, "GOODFIRE_BASE_URL")
        assert isinstance(base_url_val, str) or base_url_val is None

        self.client = AsyncClient(
            api_key=self.api_key,
            base_url=base_url_val or DEFAULT_BASE_URL,
            **self.model_args,
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

        return cast(GoodfireChatMessage, {
            "role": role,
            "content": content,
        })

    def handle_error(self, ex: Exception) -> ModelOutput | Exception:
        """Handle API errors and convert to appropriate outputs."""
        error_msg = str(ex).lower()
        
        # Handle context window overflows
        if "context length" in error_msg or "max tokens" in error_msg:
            return ModelOutput.from_content(
                model=self.model_name,
                content=str(ex),
                stop_reason="model_length",
                error=error_msg,
            )
        # Handle content policy refusals
        elif "content policy" in error_msg or "refused" in error_msg:
            return ModelOutput.from_content(
                model=self.model_name,
                content=str(ex),
                stop_reason="content_filter", 
                error=error_msg,
            )
        return ex

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        """Check if exception is due to rate limiting."""
        error_msg = str(ex).lower()
        return "429" in error_msg or "rate limit" in error_msg

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
        
        # Base parameters
        params = {
            "model": self.model_name,
            "messages": messages,
            "max_completion_tokens": int(config.max_tokens) if config.max_tokens else DEFAULT_MAX_TOKENS,
            "temperature": float(config.temperature) if config.temperature else DEFAULT_TEMPERATURE,
            "top_p": float(config.top_p) if config.top_p else DEFAULT_TOP_P,
            "stream": False,
        }
        
        # Add any additional model_args
        params.update(self.model_args)

        try:
            # Use native async client
            response = await self.client.chat.completions.create(**params)
            response_dict = response.model_dump()

            output = ModelOutput(
                model=self.model_name,
                choices=[ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=response_dict["choices"][0]["message"]["content"]
                    ),
                    stop_reason="stop"
                )],
                usage=ModelUsage(**response_dict["usage"]) if "usage" in response_dict else None
            )
            
            model_call = ModelCall.create(
                request=params,
                response=response_dict
            )
            
            return (output, model_call)
            
        except Exception as ex:
            result = self.handle_error(ex)
            model_call = ModelCall.create(
                request=params,
                response={}  # Empty response for error case
            )
            return (result, model_call) if isinstance(result, ModelOutput) else (ex, model_call)

    @property
    def name(self) -> str:
        """Get provider name."""
        return "goodfire"
