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
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from typing import TYPE_CHECKING, cast

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


def generation_replay(
    calls: Sequence[ToolCall],
    openai: dict[str, JsonValue] | None = None,
    anthropic: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """A generation's per-call provider replay state, as its provider parsed it.

    Taken by the provider's parse from that parse's own values, and kept with
    the generation's output (`set_generation_assistant_internal`), so neither a
    later nor a concurrent response reusing a call ID can change it. `openai`
    holds each call's Responses item, `anthropic` each call's internal name and
    position; a provider keeping no per-call state passes neither. `calls`
    records each call as parsed (`_call_digest`), so a copy keeps the state
    only of calls left unchanged (`carry_generation_assistant_internal`).
    """
    replay: dict[str, JsonValue] = {
        "calls": {call.id: _call_digest(call) for call in calls}
    }
    if openai is not None:
        replay["openai"] = openai
    if anthropic is not None:
        replay["anthropic"] = anthropic
    return replay


def set_generation_assistant_internal(
    output: ModelOutput, replay: dict[str, JsonValue] | None
) -> ModelOutput:
    output._assistant_internal = replay
    return output


def default_generation_assistant_internal(output: ModelOutput) -> None:
    """Record that a generation whose provider kept no replay state needs none.

    For a freshly generated output: the providers that keep per-call state
    (OpenAI Responses, Anthropic) give it in their parse. An output without it
    whose call IDs a provider has recorded state under came from such a
    provider (rebuilt from its fields, e.g. through JSON), so its state is
    unknown and nothing is recorded.
    """
    calls = [
        call for choice in output.choices for call in choice.message.tool_calls or []
    ]
    if (
        generation_assistant_internal(output) is None
        and calls
        and not any(_has_parsed_call(call.id) for call in calls)
    ):
        output._assistant_internal = generation_replay(calls)


def _has_parsed_call(call_id: str) -> bool:
    if _HAS_OPENAI:
        try:
            from inspect_ai.model._openai_responses import has_parsed_tool_call

            if has_parsed_tool_call(call_id):
                return True
        except ImportError:
            pass

    if _HAS_ANTHROPIC:
        try:
            from inspect_ai.model._providers.anthropic import (
                has_parsed_tool_call as has_parsed_anthropic_tool_call,
            )

            if has_parsed_anthropic_tool_call(call_id):
                return True
        except ImportError:
            pass

    return False


def generation_assistant_internal(output: ModelOutput) -> dict[str, JsonValue] | None:
    """The replay state the output's generation was parsed with, if any.

    None for an output rebuilt from its fields, or cached by older versions.
    """
    try:
        return output._assistant_internal
    except TypeError:
        # an output cached before `ModelOutput` had private attributes
        return None


def carry_generation_assistant_internal(
    source: ModelOutput, target: ModelOutput
) -> None:
    """Give `target` the replay state `source` has for the calls it carries unchanged.

    For a copy rebuilt from `source`'s fields. A call whose function or arguments
    differ from those it was parsed with has no replay state in `target`, as the
    state would replay what the model generated rather than the call.
    """
    replay = generation_assistant_internal(source)
    if replay is None:
        return
    parsed = cast(dict[str, str], replay.get("calls", {}))
    kept = {
        call.id
        for choice in target.choices
        for call in choice.message.tool_calls or []
        if parsed.get(call.id) == _call_digest(call)
    }
    carried: dict[str, JsonValue] = {
        "calls": {id: digest for id, digest in parsed.items() if id in kept}
    }
    if "openai" in replay:
        items = cast(dict[str, JsonValue], replay["openai"])
        carried["openai"] = {id: item for id, item in items.items() if id in kept}
    if "anthropic" in replay:
        anthropic = cast(dict[str, dict[str, JsonValue]], replay["anthropic"])
        carried["anthropic"] = {
            key: {id: value for id, value in values.items() if id in kept}
            for key, values in anthropic.items()
        }
    target._assistant_internal = carried


def keeps_generation_call_id(replay: dict[str, JsonValue] | None, call_id: str) -> bool:
    """Whether the call may be handed on under the model's ID for it.

    Only when no provider can later replay another generation's state for it
    under that ID: its generation recorded state for it
    (`has_generation_call_state`), which is handed on under the ID, or came
    from a provider keeping none. A call without known state is handed on
    under a fresh ID.
    """
    if replay is None:
        return False
    return has_generation_call_state(replay, call_id) or not (
        "openai" in replay or "anthropic" in replay
    )


def has_generation_call_state(
    replay: dict[str, JsonValue] | None, call_id: str
) -> bool:
    """Whether a provider parse recorded replay state for the call."""
    if replay is None:
        return False
    if call_id in cast(dict[str, JsonValue], replay.get("openai", {})):
        return True
    anthropic = cast(dict[str, dict[str, JsonValue]], replay.get("anthropic", {}))
    return any(call_id in values for values in anthropic.values())


def has_generation_call_arguments(
    replay: dict[str, JsonValue] | None, call_id: str
) -> bool:
    """Whether the call's replay state carries its generated arguments.

    Such a call, handed on with other arguments, replays as generated under its
    own ID; under another ID (`alias_assistant_internal_call`) it replays as
    handed on. A Responses call's item carries its arguments.
    """
    return replay is not None and call_id in cast(
        dict[str, JsonValue], replay.get("openai", {})
    )


def _call_digest(call: ToolCall) -> str:
    # repr, as parsed arguments may hold values JSON can't order or encode (e.g.
    # YAML dates as keys); an unstable repr only drops the call's state
    return sha256(repr([call.function, call.type, call.arguments]).encode()).hexdigest()


def alias_assistant_internal_call(
    call_id: str,
    alias: str,
    replay: dict[str, JsonValue],
    bridge: dict[str, JsonValue],
    modified: ToolCall | None = None,
) -> None:
    """Record a tool call's per-call replay state under the ID it is handed on under.

    So the call replays to the model as it was generated (native call type,
    position among the turn's content), with the `modified` call's arguments
    when approval changed them. The state comes from `replay`, the state the
    call's generation was parsed with (`generation_assistant_internal`), never
    from what a provider has since recorded under `call_id`.

    Under the model's ID (`alias == call_id`) the state goes in `bridge`, the
    handing bridge's own state, replayed only while that bridge serves a
    request (`bridge_replay_scope`): a later generation, native or another
    bridge's, can reuse the ID, and replays what its provider records under it.
    Under a token the bridge minted, which no generation produces, it goes in
    the provider's state, so the call replays as handed wherever its
    conversation is continued.
    """
    if _HAS_OPENAI and "openai" in replay:
        try:
            from inspect_ai.model._openai_responses import alias_openai_tool_call

            alias_openai_tool_call(
                call_id,
                alias,
                replay["openai"],
                modified,
                _bridge_section(bridge, "openai") if alias == call_id else None,
            )
        except ImportError:
            pass

    if _HAS_ANTHROPIC and "anthropic" in replay:
        try:
            from inspect_ai.model._providers.anthropic import (
                alias_anthropic_tool_call,
            )

            alias_anthropic_tool_call(
                call_id,
                alias,
                replay["anthropic"],
                _bridge_section(bridge, "anthropic") if alias == call_id else None,
            )
        except ImportError:
            pass


def _bridge_section(bridge: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], bridge.setdefault(key, {}))


_bridge_replay: ContextVar[dict[str, JsonValue] | None] = ContextVar(
    "_bridge_replay", default=None
)


@contextmanager
def bridge_replay_scope(replay: dict[str, JsonValue]) -> Iterator[None]:
    """Replay the calls an agent bridge handed on with the state it recorded for them.

    For the enclosed requests the bridge serves; `replay` is the bridge's own
    state (`alias_assistant_internal_call`).
    """
    token = _bridge_replay.set(replay)
    try:
        yield
    finally:
        _bridge_replay.reset(token)


def bridge_replay() -> dict[str, JsonValue]:
    """The state of the bridge serving the current request, by provider (empty outside one)."""
    return _bridge_replay.get() or {}
