"""Sample-scoped lifecycle for provider "assistant internal" state.

Providers smuggle wire-level content that doesn't round-trip through
``ChatMessage`` (e.g. Anthropic thinking blocks and server tool spans,
OpenAI Responses tool call params) in per-provider context vars. This
module aggregates their per-sample lifecycle: fresh initialization at
sample start, JSON dump at checkpoint fire, and restore at checkpoint
resume.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from pydantic import JsonValue

if TYPE_CHECKING:
    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.tool._tool_call import ToolCall

# `importlib.util.find_spec` walks importer paths (~3 ms per call). Cache
# at module load — package installation can't change during a process
# lifetime, so the result is invariant. Without this, `init_sample_assistant_internal`
# (called once per sample) was costing ~3 s per 500 samples in profiling.
_HAS_OPENAI: bool = importlib.util.find_spec("openai") is not None
_HAS_ANTHROPIC: bool = importlib.util.find_spec("anthropic") is not None


def init_sample_assistant_internal(value: JsonValue | None = None) -> None:
    """Initialize (or restore) per-provider assistant-internal state.

    Called with no ``value`` at sample start to bind fresh per-sample
    instances. Called with a prior :func:`dump_sample_assistant_internal`
    result when resuming from a checkpoint; the restore mutates the
    current instances in place rather than rebinding the context vars —
    the instances were bound in the sample's root task, and an in-place
    update is visible to sibling tasks (e.g. scorers) where a rebind in
    the restoring task would not be.
    """
    assert value is None or isinstance(value, dict)
    if _HAS_OPENAI and (value is None or "openai" in value):
        try:
            from inspect_ai.model._openai_responses import (
                init_sample_openai_assistant_internal,
            )

            init_sample_openai_assistant_internal(
                value["openai"] if value is not None else None
            )
        except ImportError:
            pass

    if _HAS_ANTHROPIC and (value is None or "anthropic" in value):
        try:
            from inspect_ai.model._providers.anthropic import (
                init_sample_anthropic_assistant_internal,
            )

            init_sample_anthropic_assistant_internal(
                value["anthropic"] if value is not None else None
            )
        except ImportError:
            pass


def copy_assistant_internal(source_id: str, edited_id: str) -> None:
    """Record provider state kept under message `source_id` under its edit too."""
    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import copy_server_tool_state

            copy_server_tool_state(source_id, edited_id)
        except ImportError:
            pass


def has_pending_assistant_work(message_id: str) -> bool:
    """Whether provider state for work still running is kept under message `message_id`.

    Anthropic keeps a turn's server tool work that was still running when the
    turn ended (and the code execution container to resume it) under the
    message id: it has no content item to be found by.
    """
    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import has_pending_server_work

            return has_pending_server_work(message_id)
        except ImportError:
            pass
    return False


def dump_sample_assistant_internal() -> JsonValue | None:
    """Dump per-provider assistant-internal state as a JSON value.

    Providers with nothing recorded are omitted; returns ``None`` when no
    provider has anything to save (callers skip persistence entirely).
    Restored by passing the result to :func:`init_sample_assistant_internal`.
    """
    dump: dict[str, JsonValue] = {}
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import (
                dump_openai_assistant_internal,
            )

            if (value := dump_openai_assistant_internal()) is not None:
                dump["openai"] = value
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                dump_anthropic_assistant_internal,
            )

            if (value := dump_anthropic_assistant_internal()) is not None:
                dump["anthropic"] = value
        except ImportError:
            pass

    return dump or None


def hand_tool_call(call: ToolCall) -> None:
    """Hold the providers' replay state for `call` to the call as it is handed on.

    Only a Responses item carries a call's function and arguments: one for
    another function is dropped (`hand_openai_tool_call`), and one for the
    call's function replays with each message's arguments. A provider's other
    per-call state holds as it is; each provider replays it only with a call to
    the function it was recorded for (Anthropic's name and position,
    `_has_recorded_state`; Google's anchors, `gemini_anchor_fits`), derived
    for state recorded without one (`derive_recorded_functions`).
    """
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import hand_openai_tool_call

            hand_openai_tool_call(call)
        except ImportError:
            pass


def derive_recorded_functions(output: ModelOutput) -> ModelOutput:
    """`output` with the function of provider state its calls hold without one.

    State parsed before functions were recorded (a cache entry, or a
    checkpoint's Anthropic state, written by an earlier version) is for the
    calls holding it in the output as generated. Recorded before a filter can
    change the calls, a call changed to another function replays without it
    (Anthropic's name and position, Google's anchors). A copy when an anchor
    gets its function, so the output stays on the record as generated.
    """
    from inspect_ai.model._providers._google_reasoning import (
        gemini_anchors_with_functions,
    )

    choices = [
        choice.model_copy(
            update={"message": choice.message.model_copy(update={"content": derived})}
        )
        if (derived := gemini_anchors_with_functions(choice.message)) is not None
        else choice
        for choice in output.choices
    ]
    if any(new is not old for new, old in zip(choices, output.choices)):
        output = output.model_copy(update={"choices": choices})
    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                derive_anthropic_recorded_functions,
            )

            for choice in output.choices:
                derive_anthropic_recorded_functions(choice.message)
        except ImportError:
            pass
    return output


def forget_tool_call(call_id: str) -> None:
    """Drop the providers' replay state for `call_id`, so the call under it replays from itself."""
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import forget_openai_tool_call

            forget_openai_tool_call(call_id)
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                forget_anthropic_tool_call,
            )

            forget_anthropic_tool_call(call_id)
        except ImportError:
            pass
