# ruff: noqa: F401 F403 F405

from inspect_ai._util.citation import (
    Citation,
    CitationBase,
    ContentCitation,
    DocumentCitation,
    UrlCitation,
)
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.deprecation import relocated_module_attribute

from ._cache import (
    CachePolicy,
    cache_clear,
    cache_list_expired,
    cache_path,
    cache_prune,
    cache_size,
)
from ._call_tools import ExecuteToolsResult, call_tools, execute_tools
from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageBase,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._conversation import ModelConversation
from ._generate_config import (
    GenerateConfig,
    GenerateConfigArgs,
    ResponseSchema,
)
from ._model import (
    Model,
    ModelAPI,
    ModelName,
    get_model,
)
from ._model_call import ModelCall
from ._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from ._providers.providers import *
from ._registry import modelapi
from ._trim import trim_messages

__all__ = [
    "GenerateConfig",
    "GenerateConfigArgs",
    "ResponseSchema",
    "CachePolicy",
    "ContentAudio",
    "ContentData",
    "ContentImage",
    "ContentReasoning",
    "ContentText",
    "ContentVideo",
    "Content",
    "ChatMessage",
    "ChatMessageBase",
    "ChatMessageSystem",
    "ChatMessageUser",
    "ChatMessageAssistant",
    "ChatMessageTool",
    "ChatCompletionChoice",
    "ModelCall",
    "ModelOutput",
    "ModelConversation",
    "Logprobs",
    "Logprob",
    "TopLogprob",
    "Model",
    "ModelAPI",
    "ModelName",
    "ModelUsage",
    "StopReason",
    "call_tools",
    "execute_tools",
    "ExecuteToolsResult",
    "trim_messages",
    "cache_clear",
    "cache_list_expired",
    "cache_path",
    "cache_prune",
    "cache_size",
    "get_model",
    "modelapi",
    "Citation",
    "CitationBase",
    "DocumentCitation",
    "ContentCitation",
    "UrlCitation",
]

_TOOL_MODULE_VERSION = "0.3.18"
_REMOVED_IN = "0.4"
relocated_module_attribute(
    "ToolCall", "inspect_ai.tool.ToolCall", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolChoice", "inspect_ai.tool.ToolChoice", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolFunction", "inspect_ai.tool.ToolFunction", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolParam", "inspect_ai.tool.ToolParam", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolInfo", "inspect_ai.tool.ToolInfo", _TOOL_MODULE_VERSION, _REMOVED_IN
)
