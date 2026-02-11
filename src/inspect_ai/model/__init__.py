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
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    ContentVideo,
)
from inspect_ai._util.deprecation import relocated_module_attribute

from ._anthropic_convert import messages_from_anthropic, model_output_from_anthropic
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
from ._compaction import (
    Compact,
    CompactionAuto,
    CompactionEdit,
    CompactionNative,
    CompactionStrategy,
    CompactionSummary,
    CompactionTrim,
    compaction,
)
from ._conversation import ModelConversation
from ._generate_config import (
    BatchConfig,
    GenerateConfig,
    GenerateConfigArgs,
    ResponseSchema,
)
from ._google_convert import messages_from_google, model_output_from_google
from ._message_ids import stable_message_ids
from ._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelAPI,
    ModelName,
    get_model,
)
from ._model_call import ModelCall
from ._model_config import ModelConfig
from ._model_data.model_data import ModelCost, ModelInfo
from ._model_info import get_model_info, set_model_cost, set_model_info
from ._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
    TopLogprob,
)
from ._openai_convert import (
    messages_from_openai,
    messages_from_openai_responses,
    messages_to_openai,
    model_output_from_openai,
    model_output_from_openai_responses,
)
from ._prompt import user_prompt
from ._providers.providers import *
from ._registry import modelapi
from ._trim import trim_messages

__all__ = [
    "BatchConfig",
    "GenerateConfig",
    "GenerateConfigArgs",
    "GenerateFilter",
    "GenerateInput",
    "ResponseSchema",
    "CachePolicy",
    "ContentAudio",
    "ContentData",
    "ContentToolUse",
    "ContentImage",
    "ContentReasoning",
    "ContentText",
    "ContentVideo",
    "ContentDocument",
    "ContentDocument",
    "Content",
    "ChatMessage",
    "ChatMessageBase",
    "ChatMessageSystem",
    "ChatMessageUser",
    "ChatMessageAssistant",
    "ChatMessageTool",
    "ChatCompletionChoice",
    "messages_from_openai",
    "messages_from_openai_responses",
    "messages_from_anthropic",
    "messages_from_google",
    "model_output_from_openai",
    "model_output_from_openai_responses",
    "model_output_from_anthropic",
    "model_output_from_google",
    "messages_to_openai",
    "stable_message_ids",
    "ModelCall",
    "ModelCost",
    "ModelOutput",
    "ModelConversation",
    "compaction",
    "Compact",
    "CompactionStrategy",
    "CompactionAuto",
    "CompactionEdit",
    "CompactionSummary",
    "CompactionTrim",
    "CompactionNative",
    "Logprobs",
    "Logprob",
    "TopLogprob",
    "Model",
    "ModelAPI",
    "ModelName",
    "ModelConfig",
    "ModelUsage",
    "StopReason",
    "call_tools",
    "execute_tools",
    "ExecuteToolsResult",
    "trim_messages",
    "user_prompt",
    "cache_clear",
    "cache_list_expired",
    "cache_path",
    "cache_prune",
    "cache_size",
    "get_model",
    "get_model_info",
    "set_model_cost",
    "set_model_info",
    "ModelInfo",
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
