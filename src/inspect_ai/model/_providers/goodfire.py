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

logger = logging.getLogger(__name__)

GOODFIRE_API_KEY = "GOODFIRE_API_KEY"

class GoodfireAPI(ModelAPI):
    """Goodfire API provider."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
        **kwargs: Any,
    ) -> None:
        """Initialize the Goodfire API provider."""
        # Get API key from environment if not provided
        api_key = api_key or os.environ.get(GOODFIRE_API_KEY, None)
        if api_key is None:
            raise ValueError("API key is required for Goodfire.")

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=api_key_vars,
            config=config,
            **kwargs,
        )

        # Set api and name attributes for registry info
        self.api = self
        self.name = "goodfire"

        # Format model name to include meta-llama prefix if needed
        if not model_name.startswith("meta-llama/"):
            model_name = f"meta-llama/{model_name}"

        # Validate model name
        supported_models = list(get_args(SUPPORTED_MODELS))
        if model_name not in supported_models:
            raise ValueError(f"Model {model_name} not supported. Supported models: {supported_models}")

        # Initialize client
        self.client = goodfire.Client(api_key=api_key)
        self.model_name = model_name
        self.variant = Variant(model_name)

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
          input (List[ChatMessage]): Chat message input.
          tools (List[ToolInfo]): Tools available for the model to call.
          tool_choice (ToolChoice): Directives to the model as to which tools to prefer.
          config (GenerateConfig): Model configuration.
          cache (bool): Whether to use caching. Defaults to True.

        Returns:
           ModelOutput: The model's output.
        """
        completions = self.client.chat.completions
        response = completions.create(  # type: ignore
            model=self.model_name,
            messages=[self._to_goodfire_message(msg) for msg in input],
            max_completion_tokens=int(config.max_tokens) if config.max_tokens is not None else 100,
            temperature=float(config.temperature) if config.temperature is not None else 0.7,
            top_p=float(config.top_p) if config.top_p is not None else 0.95,
            stream=False,
        )
        response_dict = response.model_dump()

        output = ModelOutput.from_content(
            model=self.model_name,
            content=response_dict["choices"][0]["message"]["content"],
            stop_reason="stop",
        )

        if "usage" in response_dict:
            output.usage = ModelUsage(
                input_tokens=response_dict["usage"]["prompt_tokens"],
                output_tokens=response_dict["usage"]["completion_tokens"],
                total_tokens=response_dict["usage"]["total_tokens"],
            )

        return output

    def _to_goodfire_message(self, message: ChatMessage) -> GoodfireChatMessage:
        """Convert an Inspect message to a Goodfire message."""
        role: Literal["system", "user", "assistant"] = "user"  # Default to user
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

    def max_tokens(self) -> Optional[int]:
        """Return maximum tokens supported by model."""
        return None

    def max_connections(self) -> int:
        """Return maximum concurrent connections."""
        return 10  # Adjust based on Goodfire's rate limits

    def connection_key(self) -> str:
        """Return key for connection pooling."""
        return f"goodfire:{self.model_name}"

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