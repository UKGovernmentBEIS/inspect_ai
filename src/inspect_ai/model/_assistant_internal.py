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


def has_assistant_internal_call_arguments(call_id: str) -> bool:
    """Whether a provider replays the call's generated arguments from its own state.

    Such a call, handed on with other arguments, replays as generated under its
    own ID; under another ID (`alias_assistant_internal_call`) it replays as
    handed on. The OpenAI Responses provider replays a call's cached item.
    """
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import has_openai_tool_call

            return has_openai_tool_call(call_id)
        except ImportError:
            pass
    return False


def record_generation_assistant_internal(output: ModelOutput) -> None:
    """Keep the per-call replay state the providers recorded for this output's calls with it.

    Called as the generation returns, before any other response can reuse its
    call IDs. A model output cache hit returns the output with this state, so
    the agent bridge hands its calls on as generated
    (`alias_assistant_internal_call`), whatever has since been recorded under
    their IDs.
    """
    call_ids = [
        call.id for choice in output.choices for call in choice.message.tool_calls or []
    ]
    if not call_ids:
        return
    recorded: dict[str, JsonValue] = {}
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import recorded_openai_tool_calls

            if (value := recorded_openai_tool_calls(call_ids)) is not None:
                recorded["openai"] = value
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                recorded_anthropic_tool_calls,
            )

            if (value := recorded_anthropic_tool_calls(call_ids)) is not None:
                recorded["anthropic"] = value
        except ImportError:
            pass

    output._assistant_internal = recorded or None


def generation_assistant_internal(output: ModelOutput) -> dict[str, JsonValue] | None:
    """The replay state recorded with this output, if any."""
    try:
        return output._assistant_internal
    except TypeError:
        # an output cached before `ModelOutput` had private attributes
        return None


def alias_assistant_internal_call(
    call_id: str,
    alias: str,
    modified: ToolCall | None = None,
    generation: dict[str, JsonValue] | None = None,
) -> None:
    """Record a tool call's per-call replay state under the ID it is handed on under.

    So the call replays to the model as it was generated (native call type,
    position among the turn's content), with the `modified` call's arguments
    when approval changed them. The state comes from `generation`, what the
    call's output recorded (`generation_assistant_internal`); for an output
    that recorded none, from what the provider last recorded under `call_id`. The
    state recorded under `alias` (which may be `call_id`) is replayed in
    preference to what the provider records under `call_id`, which a later
    response reusing that ID replaces.
    """
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import alias_openai_tool_call

            alias_openai_tool_call(
                call_id,
                alias,
                modified,
                generation.get("openai", {}) if generation is not None else None,
            )
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                alias_anthropic_tool_call,
            )

            alias_anthropic_tool_call(
                call_id,
                alias,
                generation.get("anthropic", {}) if generation is not None else None,
            )
        except ImportError:
            pass
