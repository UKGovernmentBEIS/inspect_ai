import inspect
import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from logging import getLogger
from typing import Iterator, Sequence, cast

from typing_extensions import TypeIs

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentVideo,
)
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.url import is_data_uri
from inspect_ai.agent._bridge._approval import (
    MAX_CONSECUTIVE_REJECTIONS,
    apply_bridge_tool_approval,
    terminate_for_repeated_rejections,
)
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.types import AgentBridge, message_json_hash
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
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_util import tool_to_tool_info
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
    "effort",
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


def _operator_message_key(message: ChatMessageUser) -> str:
    """Content key for an operator user message (identity- and source-independent).

    Hashes the message with ``id`` and ``source`` cleared so the key depends only
    on the content the scaffold replays identically across turns — independent of
    the per-instance ``id`` and of whether the source has been restored yet. Uses
    the same ``message_json_hash`` the bridge uses elsewhere.
    """
    keyed = message.model_copy(update={"id": None, "source": None})
    return message_json_hash(to_json_str_safe(keyed))


def _restore_operator_message_source(
    bridge: AgentBridge, input: list[ChatMessage]
) -> None:
    """Restore ``source="operator"`` on operator messages re-entering via a bridge.

    A bridged scaffold (claude_code, codex, …) round-trips operator interventions
    through its own conversation store, so an operator message comes back as a
    plain ``ChatMessageUser`` (``source=None``) — losing the provenance the ACP
    transport stamped at submit time. We restore it here, at the single
    ``bridge_generate`` chokepoint shared by every bridged agent, mutating the
    messages in place so the restored source persists in BOTH the recorded
    ``ModelEvent`` input and ``bridge.state.messages`` (and thus the eval log and
    the ACP TUI).

    The signal is entirely on the ``bridge`` object — the only thing reliably
    threaded into ``bridge_generate`` for both in-process and sandbox bridges. The
    scaffold calls :meth:`AgentBridge.note_operator_message` when it injects an
    operator message (incrementing ``_pending_operator``); we never reach into the
    ACP transport or the agent channel.

    Two parts:

    - **First recognition** (positional): when an injection is pending, the
      operator turn is the LATEST user message (queued sends coalesce into one).
      Stamp it, record its content key, and consume all pending. Positional
      recognition is robust to the scaffold reformatting the content on re-emit
      (multiblock / coalescing / whitespace) — we never match the originally
      submitted text.
    - **Carry-forward** (re-recognition): the round-trip drops ``source`` every
      turn, and the final logged conversation is taken from a later turn where the
      operator sits mid-history. So on every turn we re-stamp any user message
      whose content key was recorded. This keys on the bridge's own stable
      content hash (reconstructed-to-reconstructed, stable because the scaffold
      replays a past turn identically) — the same content-stability the bridge's
      id allocation already relies on. Skipped (no hashing) when no operator has
      ever been seen.
    """
    # carry-forward: re-stamp previously-recognized operators
    if bridge._operator_keys:
        for message in input:
            if (
                isinstance(message, ChatMessageUser)
                and message.source != "operator"
                and _operator_message_key(message) in bridge._operator_keys
            ):
                message.source = "operator"

    # first recognition: stamp the latest user message and consume all pending.
    # Stop at the latest user message regardless of its source: if carry-forward
    # already stamped it (operator re-sent identical content), there is nothing
    # new to stamp — falling through to an earlier turn would wrongly stamp the
    # task.
    if bridge._pending_operator > 0:
        for message in reversed(input):
            if isinstance(message, ChatMessageUser):
                if message.source != "operator":
                    bridge._operator_keys.add(_operator_message_key(message))
                    message.source = "operator"
                break
        bridge._pending_operator = 0


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

    Tool calls in the output are approved before it is handed back to the scaffold. A
    rejected call is not edited out of the response — instead the model is told it was
    rejected and generation is retried, so the scaffold sees only the replacement (see
    `_approval.apply_bridge_tool_approval`).
    """
    # restore operator provenance lost to a bridged scaffold's round-trip (e.g.
    # claude_code re-emits an operator message as a plain user message). Done
    # before compaction/recording so the restored source persists in both the
    # ModelEvent input and state.messages (and thus the eval log).
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
    rejections = 0
    while True:
        # Reset to original inputs for each retry
        input_messages = original_input
        tools = original_tools
        tool_choice = original_tool_choice
        config = original_config

        # Apply filter if we have it (can either return output or alternate inputs)
        output: ModelOutput | None = None
        if bridge.filter:
            # tool_to_tool_info (via ToolDef) preserves `options` — including
            # the INTERNAL_TOOL_TYPE marker — so the filter sees the same
            # ToolInfo the model provider would. parse_tool_info re-derives
            # from the function signature and drops options.
            tool_info = [
                tool_to_tool_info(tool) if not isinstance(tool, ToolInfo) else tool
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
            continue

        # Approve the tool calls the scaffold is about to run. A rejection comes back
        # as the messages to replay to the model (the rejected call plus a result for
        # every call in the response) so it can propose something else; the scaffold
        # never sees the rejected response.
        reviewed = await apply_bridge_tool_approval(bridge, output, input_messages)
        if reviewed.rejection is None:
            return reviewed.output, c_message

        rejections += 1
        if rejections >= MAX_CONSECUTIVE_REJECTIONS:
            terminate_for_repeated_rejections(bridge, rejections)

        # accumulate onto original_input (rather than input_messages) since that is
        # what the top of the loop resets to, and any filter rewrite is per-attempt
        original_input = original_input + reviewed.rejection


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


logger = getLogger(__name__)


def withheld_bridge_tool(tool_type: str) -> None:
    """Drop a client-declared tool this bridge does not grant.

    Dropping rather than erroring keeps the rest of the request serviceable. The
    warning is what makes the omission diagnosable: an absent tool is otherwise
    indistinguishable from the model simply choosing not to call it.
    """
    warn_once(
        logger,
        f"The bridged agent declared a '{tool_type}' tool, which this bridge does "
        "not grant; it has been withheld from the model. Grant it via the "
        "corresponding agent_bridge() option if the evaluation intends it.",
    )
    return None


def relax_tool_choice_for_withheld(
    tool_choice: ToolChoice | None, tools: Sequence[ToolInfo | Tool]
) -> ToolChoice | None:
    """Fall back to "auto" when `tool_choice` names a tool this bridge withheld.

    Forcing a tool that isn't in the list makes the model layer purge *every* tool
    for the turn, so one withheld capability would take the agent's own function
    tools down with it.
    """
    if not isinstance(tool_choice, ToolFunction):
        return tool_choice
    names = {
        (tool.name if isinstance(tool, ToolInfo) else tool_to_tool_info(tool).name)
        for tool in tools
    }
    return tool_choice if tool_choice.name in names else "auto"


def resolve_bridge_web_search(
    providers: WebSearchProviders | bool | None,
    *,
    default_grant: bool,
) -> WebSearchProviders | None:
    """Resolve a bridge `web_search` option, returning `None` to withhold it.

    `None` defers to the bridge's own posture. A config that leaves no provider
    enabled also withholds: otherwise "turn every provider off" would still serve
    search through whichever provider the config neglected to name.

    Note an *empty* config is the opposite of an all-`False` one — it enables the
    default provider set, and callers rely on that to grant without pinning a list.
    """
    if providers is None:
        providers = default_grant
    if providers is False:
        return None
    if providers is True:
        providers = internal_web_search_providers()
    return cast(WebSearchProviders, _normalize_config(providers)) or None


def resolve_bridge_code_execution(
    providers: CodeExecutionProviders | bool | None,
    *,
    default_grant: bool,
) -> CodeExecutionProviders | None:
    """Resolve a bridge `code_execution` option, returning `None` to withhold it."""
    if providers is None:
        providers = default_grant
    if providers is False:
        return None
    if providers is True:
        return default_code_execution_providers()
    return providers


def _bridge_media_uri(content: Content) -> str | None:
    match content:
        case ContentImage():
            return content.image
        case ContentDocument():
            return content.document
        case ContentAudio():
            return content.audio
        case ContentVideo():
            return content.video
        case _:
            return None


def validate_bridge_media(bridge: AgentBridge, messages: Sequence[ChatMessage]) -> None:
    """Reject inbound media the host would dereference on the agent's behalf.

    Media content carries a URI that gets resolved outside the sandbox: an http(s)
    URL is fetched by the Inspect process (or by the provider), and anything else
    is read from the host filesystem via fsspec. For a sandboxed agent that is a
    confused deputy — it turns an ordinary model request into an arbitrary read
    performed by a process the sandbox is not supposed to reach. Only inline
    `data:` URIs are accepted there.

    In-process bridges are exempt: that scaffold already runs with the host's
    filesystem and network, so there is no boundary here to defend.
    """
    if bridge.allow_remote_media:
        return
    for message in messages:
        if isinstance(message.content, str):
            continue
        for content in message.content:
            uri = _bridge_media_uri(content)
            if uri is not None and not is_data_uri(uri):
                raise BridgePolicyError(
                    f"Bridged {content.type} content must be an inline 'data:' URI; "
                    f"the agent bridge will not dereference {uri[:80]!r}."
                )


def apply_message_ids(bridge: AgentBridge, messages: list[ChatMessage]) -> None:
    # clear the ids so we can apply new ones
    for message in messages:
        message.id = None

    # allocate ids based on message content (re-applying the same id for the same
    # content, but also ensuring that if an id is already used we generate a new one)
    for message in messages:
        message.id = bridge._id_for_message(message, messages)
