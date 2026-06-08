import inspect
import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Sequence, cast

from typing_extensions import TypeIs

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig, active_generate_config
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelGenerateFilter,
    active_model,
    get_model,
    model_roles,
    use_model_event_sink,
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

# Generation-tuning fields a scaffold may set on a bridged request that describe
# *how* the underlying model generates. These are the Inspect model's province
# (the scaffold computes them for its assumed --model, not the model actually
# serving the request), so by default the bridge drops them and lets the model
# config / provider defaults govern generation. Structural fields the scaffold
# legitimately controls (system_message, stop_seqs, response_schema,
# parallel_tool_calls, seed, extra_body/headers) are deliberately NOT listed here.
_GENERATION_PARAM_FIELDS: tuple[str, ...] = (
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "num_choices",
    "logprobs",
    "top_logprobs",
    "prompt_logprobs",
    "logit_bias",
    "reasoning_effort",
    "reasoning_tokens",
    "reasoning_summary",
)


def clear_generation_params(config: GenerateConfig) -> None:
    """Clear generation-tuning params from a bridged request config (in place).

    Used when a bridge is configured not to forward client generation parameters
    (the default): the dropped fields then fall back to the resolved Inspect model
    config and provider defaults during ``resolve_generate_config``.
    """
    for field in _GENERATION_PARAM_FIELDS:
        setattr(config, field, None)


_bridge_model_generate: ContextVar[bool] = ContextVar(
    "_bridge_model_generate", default=False
)


@contextmanager
def bridge_model_generate() -> Iterator[None]:
    """Mark the enclosed block as a bridged model generation.

    Installed by `bridge_generate` around its `model.generate()` call so that
    consumers can recognise `ModelEvent`s originating from a bridged agent.
    """
    token = _bridge_model_generate.set(True)
    try:
        yield
    finally:
        _bridge_model_generate.reset(token)


def in_bridge_model_generate() -> bool:
    """Is the current model generation routed through the agent bridge?

    `True` while inside `bridge_generate`'s call to `model.generate()`. Because
    transcript subscriber callbacks fire synchronously in the emitting task's
    context, this is reliably `True` when a bridged `ModelEvent` is observed by
    a subscriber (e.g. the ACP live router) and `False` for ordinary
    react-style generation.

    Bridged scaffolds run their own tool calls, so no `ToolEvent` is ever
    emitted for them — tool calls live only on
    `ModelEvent.output.message.tool_calls`. Consumers that render tool calls use
    this to decide whether they must synthesize tool-call cards from the
    `ModelEvent` (rather than wait for a `ToolEvent` that will never arrive).

    Covers every bridge configuration: in-process `agent_bridge()` and
    `sandbox_agent_bridge()`, with or without a `ModelEventSink`, since all
    route through `bridge_generate`.
    """
    return _bridge_model_generate.get()


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


def _restore_operator_message_source(
    bridge: AgentBridge, input: list[ChatMessage]
) -> None:
    """Restore ``source="operator"`` on operator messages re-entering via a bridge.

    A bridged scaffold (claude_code, codex, …) round-trips operator
    interventions through its own conversation store (e.g. Claude Code's
    ``--resume``), so an operator message comes back as a plain
    ``ChatMessageUser`` (``source=None``) — losing the provenance the ACP
    transport stamped at submit time. Re-stamp it here, at the single bridge
    generate chokepoint shared by every bridged agent. ``input`` is the same
    list the caller records as the ``ModelEvent`` input and tracks into
    ``state.messages``, and messages are mutated in place, so the restored
    source persists in both the events and the final messages (and the ACP
    TUI's operator-keyed rendering + queued-echo reconciliation then work
    without further special-casing).

    Scoped recognition (no global ledger): a message is recognized ONCE, the
    first time it re-enters — matched against the transport's small set of
    submitted-but-not-yet-seen operator messages, which is consumed on match.
    Thereafter the source is carried forward from the bridge's own tracked
    conversation (``bridge.state.messages``), bounded by the live conversation
    and pruned with compaction. No match leaves the message untouched.
    """
    # Local import to avoid a load-order cycle (_acp imports from _bridge).
    from inspect_ai.agent._acp.transport import current_acp_transport

    # Operator messages already established in the tracked conversation, keyed by
    # whole-text. Carry-forward deliberately matches the FULL ``.text`` (not the
    # per-block candidates ``consume_operator_message`` uses): Claude Code keeps
    # a user turn's representation stable once it is history (reminder / skills
    # blocks included), so the same operator message re-enters every later turn
    # with an identical, distinctive whole text. Matching per-block here instead
    # would risk a false positive — the shared reminder / skills blocks also
    # appear on the dataset task message, which must NOT be stamped operator.
    known_operator_text = {
        message.text.strip()
        for message in bridge.state.messages
        if isinstance(message, ChatMessageUser) and message.source == "operator"
    }
    transport = current_acp_transport()
    for message in input:
        if not isinstance(message, ChatMessageUser) or message.source == "operator":
            continue
        # ``consume_operator_message`` first so a still-pending entry is always
        # cleared; fall back to carry-forward for messages already in state.
        if (
            transport.consume_operator_message(message)
            or message.text.strip() in known_operator_text
        ):
            message.source = "operator"


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
    # restore operator provenance lost to a bridged scaffold's round-trip
    # (e.g. claude_code --resume re-emits an operator message as a plain
    # user message). Done before compaction/recording so the restored
    # source persists in both the ModelEvent input and state.messages.
    _restore_operator_message_source(bridge, input)

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

        # Run the generation if the filter didn't. If the bridge has a
        # model_event_sink installed, route ModelEvent emissions through it
        # (instead of going straight to the transcript) so the caller can
        # control when / under which span events appear.
        if output is None:
            with bridge_model_generate(), use_model_event_sink(bridge.model_event_sink):
                output = await model.generate(
                    input=input_messages,
                    tool_choice=tool_choice,
                    tools=tools,
                    config=config,
                )

        # Update the compaction baseline with the actual input token
        # count from the generate call (most accurate source of truth)
        if compact is not None:
            await compact.record_output(input_messages, output)

        # Check for refusal and retry if needed
        if (
            output.stop_reason == "content_filter"
            and bridge.retry_refusals is not None
            and refusals < bridge.retry_refusals
        ):
            refusals += 1
        else:
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
    # clear the ids so we can apply new ones
    for message in messages:
        message.id = None

    # allocate ids based on message content (re-applying the same id for the same
    # content, but also ensuring that if an id is already used we generate a new one)
    for message in messages:
        message.id = bridge._id_for_message(message, messages)
