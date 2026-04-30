import inspect
import warnings
from typing import Sequence, cast

from typing_extensions import TypeIs

from inspect_ai.agent._bridge.types import AgentBridge, _message_signature
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig, active_generate_config
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelGenerateFilter,
    active_model,
    get_model,
    model_roles,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo, parse_tool_info
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    _normalize_config,
)

_filter_type_cache: dict[int, bool] = {}


def _is_model_filter(fn: GenerateFilter) -> TypeIs[ModelGenerateFilter]:
    """True when *fn* accepts a ``Model`` as its first parameter (new-style).

    Returns ``False`` for legacy filters whose first parameter is ``str``.
    Caches per object id so ``inspect.signature`` is called at most once.
    Emits a deprecation warning the first time a legacy filter is detected.
    """
    key = id(fn)
    result = _filter_type_cache.get(key)
    if result is None:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
        first = next(iter(sig.parameters.values()), None)
        if first is not None and first.annotation is str:
            result = False
            warnings.warn(
                "GenerateFilter with 'str' as the first parameter is "
                "deprecated. Update your filter to accept a 'Model' "
                "instance instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        else:
            result = True
        _filter_type_cache[key] = result
    return result


async def bridge_generate(
    bridge: AgentBridge,
    model: Model,
    input: list[ChatMessage],
    tools: Sequence[ToolInfo | Tool],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> tuple[ModelOutput, ChatMessageUser | None]:
    """Generate model output through the agent bridge.

    If a filter is configured, it will be called on each attempt (including retries).
    The filter can either return a ModelOutput directly or modify the generation inputs.
    Refusals (stop_reason="content_filter") from either the filter or model will trigger
    retries up to bridge.retry_refusals times, with inputs reset to original values for
    each retry to ensure clean state.
    """
    # get compaction function and run compaction once before retry loop
    compact = bridge.compaction(tools, model)
    if compact is not None:
        input_messages, c_message = await compact.compact_input(input)
    else:
        input_messages = input
        c_message = None

    # Store original inputs for potential retries (using compacted input)
    original_input = input_messages
    original_tools = tools
    original_tool_choice = tool_choice
    original_config = config

    refusals = 0
    while True:
        # Reset to original inputs for each retry
        input_messages = original_input
        tools = original_tools
        tool_choice = original_tool_choice
        config = original_config

        # Apply filter if we have it (can either return output or alternate inputs)
        output: ModelOutput | None = None
        if bridge.filter:
            tool_info = [
                parse_tool_info(tool) if not isinstance(tool, ToolInfo) else tool
                for tool in tools
            ]
            if _is_model_filter(bridge.filter):
                result = await bridge.filter(
                    model, input_messages, tool_info, tool_choice, config
                )
            else:
                result = await bridge.filter(
                    model.name, input_messages, tool_info, tool_choice, config
                )
            if isinstance(result, ModelOutput):
                output = result
            elif isinstance(result, GenerateInput):
                # Update the inputs that will be used for generation
                input_messages, tools, tool_choice, config = result

        # Run the generation if the filter didn't
        if output is None:
            output = await model.generate(
                input=input_messages,
                tool_choice=tool_choice,
                tools=tools,
                config=config,
            )

        # Update the compaction baseline with the actual input token
        # count from the generate call (most accurate source of truth)
        if compact is not None:
            compact.record_output(output)

        # Check for refusal and retry if needed
        if (
            output.stop_reason == "content_filter"
            and bridge.retry_refusals is not None
            and refusals < bridge.retry_refusals
        ):
            refusals += 1
        else:
            # Register the canonical output ids so a later turn can map a
            # harness-echoed copy of this message back to them.
            bridge._register_output_message(output.message)
            return output, c_message


def resolve_generate_config(
    model: Model, bridge_config: GenerateConfig
) -> GenerateConfig:
    # give config built into the model instance priority over
    # bridged agent default
    config = bridge_config.merge(model.config)

    # apply active model config if appropriate
    is_active_model = model == active_model()
    if is_active_model:
        config = config.merge(active_generate_config())

    return config


def resolve_inspect_model(
    model_name: str,
    model_aliases: dict[str, str | Model] | None = None,
    fallback_model: str | None = None,
) -> Model:
    if model_aliases and model_name in model_aliases:
        return get_model(model_aliases[model_name])

    if fallback_model is not None:
        if model_name != "inspect" or not fallback_model.startswith("inspect/"):
            model_name = fallback_model

    if model_name == "inspect":
        return get_model()

    model_name = model_name.removeprefix("inspect/")
    if model_name in model_roles():
        return get_model(role=model_name)
    return get_model(model_name)


def resolve_web_search_providers(
    providers: WebSearchProviders | None,
) -> WebSearchProviders:
    if providers is None:
        providers = internal_web_search_providers()
    return cast(WebSearchProviders, _normalize_config(providers))


def internal_web_search_providers() -> WebSearchProviders:
    return WebSearchProviders(
        openai=True, anthropic=True, grok=True, gemini=True, perplexity=True
    )


def default_code_execution_providers() -> CodeExecutionProviders:
    return CodeExecutionProviders(
        openai={}, anthropic=True, google=True, grok=True, python={}
    )


def apply_message_ids(bridge: AgentBridge, messages: list[ChatMessage]) -> None:
    """Assign stable ids to ``messages`` for one bridge turn.

    Two distinct restorations happen here:

    1. Each message gets an ``id`` chosen by content signature. The lookup
       table is populated by previous calls to ``apply_message_ids`` and by
       ``bridge._register_output_message`` after each generation, so an
       output emitted in turn N is recognized when echoed back as input in
       turn N+1.
    2. ``ToolCall.id`` values on assistant messages are remapped from the
       harness's reformatted version back to the original inspect id (Gemini
       reformats every ``tool_call.id`` on round trip, so the inbound message
       carries something like ``call_search_abc12345`` where the original
       output had whatever id ``model.generate()`` minted). Any
       ``ChatMessageTool.tool_call_id`` referencing a renamed call is
       rewritten in lockstep so the assistant ↔ tool linkage stays intact.
    """
    # snapshot the inbound tool_call ids so we can build a remap for tool messages
    inbound_tool_call_ids: dict[int, list[str]] = {
        idx: [tc.id for tc in m.tool_calls]
        for idx, m in enumerate(messages)
        if isinstance(m, ChatMessageAssistant) and m.tool_calls
    }

    # clear ids so we can apply new ones
    for message in messages:
        message.id = None

    tool_call_remap: dict[str, str] = {}

    for idx, message in enumerate(messages):
        signature = _message_signature(message)
        message.id = bridge._id_for_message_signature(signature, messages)

        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            for tc_idx, tool_call in enumerate(message.tool_calls):
                inbound_id = inbound_tool_call_ids[idx][tc_idx]
                registered_id = bridge._tool_call_ids.get((signature, tc_idx))
                if registered_id is None:
                    # first sighting: remember the inbound id as canonical so
                    # we stay stable even when content originated outside this
                    # bridge (e.g. pre-populated agent state).
                    if inbound_id:
                        bridge._tool_call_ids[(signature, tc_idx)] = inbound_id
                    continue
                if inbound_id and inbound_id != registered_id:
                    tool_call_remap[inbound_id] = registered_id
                    tool_call.id = registered_id

        elif (
            isinstance(message, ChatMessageTool)
            and message.tool_call_id is not None
            and message.tool_call_id in tool_call_remap
        ):
            message.tool_call_id = tool_call_remap[message.tool_call_id]
