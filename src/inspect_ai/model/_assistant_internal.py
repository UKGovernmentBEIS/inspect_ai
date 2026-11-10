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
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from typing import TYPE_CHECKING, NamedTuple, cast

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


def generation_replay(
    calls: Sequence[ToolCall],
    openai: Sequence[JsonValue | None] | None = None,
    anthropic: Sequence[JsonValue | None] | None = None,
) -> dict[str, JsonValue]:
    """A generation's per-call provider replay state, as its provider parsed it.

    Taken by the provider's parse from that parse's own values, and kept with
    the generation's output (`set_generation_assistant_internal`), so neither a
    later nor a concurrent response reusing a call ID can change it. `openai`
    holds each call's Responses item, `anthropic` each call's internal name and
    position (`{"name": ..., "position": ...}`), in call order, with None for a
    call the parse recorded nothing for. A provider keeping no per-call state
    passes neither.

    The state is kept by call ID, with the call as parsed (`_call_digest`), so a
    copy keeps the state only of the calls it carries
    (`carry_generation_assistant_internal`). An ID several of the generation's
    calls share keeps no state (None), so no call can replay another's
    (`shared_call_ids`).
    """
    providers = {"openai": openai, "anthropic": anthropic}
    shared = _repeated_ids(calls)
    states: dict[str, JsonValue] = {}
    for index, call in enumerate(calls):
        if call.id in shared:
            states[call.id] = None
            continue
        state: dict[str, JsonValue] = {
            "function": call.function,
            "type": call.type,
            "digest": _call_digest(call),
        }
        for provider, values in providers.items():
            if values is not None and values[index] is not None:
                state[provider] = values[index]
        states[call.id] = state
    return {
        "calls": states,
        "providers": [
            provider for provider, values in providers.items() if values is not None
        ],
    }


def _repeated_ids(calls: Sequence[ToolCall]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for call in calls:
        (repeated if call.id in seen else seen).add(call.id)
    return repeated


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

    None for an output rebuilt from its fields, or cached by older versions
    (including those without the parsed calls' functions, or keeping a state per
    call occurrence).
    """
    replay = _output_replay(output)
    if (
        replay is None
        or not isinstance(replay.get("providers"), list)
        or not isinstance(calls := replay.get("calls"), dict)
        or not all(state is None or isinstance(state, dict) for state in calls.values())
    ):
        return None
    return replay


def _output_replay(output: ModelOutput) -> dict[str, JsonValue] | None:
    try:
        return output._assistant_internal
    except TypeError:
        # an output cached before `ModelOutput` had private attributes
        return None


def shared_call_ids(output: ModelOutput) -> set[str]:
    """The call IDs that several of the output's calls, or its generation's, share.

    Calls sharing an ID within a turn replay with no per-call state, as the
    state recorded under the ID can't be told apart by call. Inspect's
    providers don't produce such calls (OpenAI and Anthropic IDs are unique,
    and Google's missing IDs are filled in uniquely), so replay of them is not
    guaranteed, only that no call carries another's state. Includes the IDs
    recorded as shared in an output derived from one that shared them
    (`share_call_ids`).
    """
    calls = [
        call for choice in output.choices for call in choice.message.tool_calls or []
    ]
    replay = generation_assistant_internal(output)
    parsed = cast(dict[str, JsonValue], replay["calls"]) if replay else {}
    return (
        _repeated_ids(calls)
        | {call_id for call_id, state in parsed.items() if state is None}
        | _recorded_shared(_output_replay(output))
    )


def share_call_ids(output: ModelOutput, call_ids: Iterable[str]) -> None:
    """Record that those of `call_ids` `output`'s calls carry are shared in it.

    For an output derived from one whose calls shared these IDs, where that no
    longer shows (e.g. a response filter kept one of the calls). Recorded apart
    from the generation's replay state, so it holds when that state is unknown
    (`generation_assistant_internal`), and gives no call any state. An ID no
    call carries is not recorded: a Google reasoning anchor naming it is not
    ambiguous, and one may be kept to hold its message's signatures in place.
    """
    carried = {
        call.id for choice in output.choices for call in choice.message.tool_calls or []
    }
    shared = set(call_ids) & carried
    if not shared:
        return
    replay = dict(_output_replay(output) or {})
    replay["shared"] = cast(list[JsonValue], sorted(shared | _recorded_shared(replay)))
    output._assistant_internal = replay


def _recorded_shared(replay: dict[str, JsonValue] | None) -> set[str]:
    shared = replay.get("shared") if replay is not None else None
    if not isinstance(shared, list):
        return set()
    return {call_id for call_id in shared if isinstance(call_id, str)}


class GenerationCallState(NamedTuple):
    """A call's replay state, as its generation's provider parsed it."""

    openai: JsonValue | None
    """The call's Responses item."""

    anthropic: JsonValue | None
    """The call's internal name and position."""

    edited: bool
    """Whether the call is handed on with other arguments than it was parsed with
    (a request or response filter, or approval, changed them; `_handed_edited`)."""

    @property
    def recorded(self) -> bool:
        """Whether a provider recorded state for the call."""
        return self.openai is not None or self.anthropic is not None

    @property
    def carries_arguments(self) -> bool:
        """Whether the state carries the call's generated arguments.

        Such a call, handed on with other arguments, replays as generated under
        its own ID; under another ID (`alias_assistant_internal_call`) it
        replays as handed on. A Responses call's item carries its arguments.
        """
        return self.openai is not None


def generation_call_states(
    replay: dict[str, JsonValue] | None, calls: Sequence[ToolCall]
) -> list[GenerationCallState | None]:
    """Each of a generation's calls' replay state (`generation_replay`), in call order.

    A call from a provider keeping no per-call state gets an empty state. A
    call's state is None (unknown) when `replay` is None, when the generation
    parsed no such call, when its provider recorded nothing for it (a Responses
    call without an item ID), when its ID is shared (`shared_call_ids`), or
    when it is not the call parsed under its ID with at most its arguments
    changed (`_handed_edited`). So an output reaching the bridge by any path
    (a request filter's generation or substitute, a response filter, approval)
    is checked against what its generation parsed.
    """
    parsed = cast(
        dict[str, dict[str, JsonValue] | None],
        replay.get("calls", {}) if replay is not None else {},
    )
    providers = cast(list[str], replay.get("providers", [])) if replay else []
    shared = _repeated_ids(calls) | _recorded_shared(replay)
    states: list[GenerationCallState | None] = []
    for call in calls:
        state = parsed.get(call.id)
        edited = _handed_edited(state, call) if state is not None else None
        if (
            call.id in shared
            or state is None
            or edited is None
            or any(key not in state for key in providers)
        ):
            states.append(None)
        else:
            states.append(
                GenerationCallState(state.get("openai"), state.get("anthropic"), edited)
            )
    return states


def _handed_edited(state: dict[str, JsonValue], call: ToolCall) -> bool | None:
    """Whether `call` is handed on edited from the call parsed with `state`.

    False for the call as parsed. True for the call with other arguments and its
    function and type: it keeps the state and is handed on like an approval
    `modify`, in its native form with its own arguments
    (`alias_assistant_internal_call`). None for any other call (another
    function or type), which keeps no state and replays from the call itself.
    """
    if state.get("digest") == _call_digest(call):
        return False
    if state.get("function") == call.function and state.get("type") == call.type:
        return True
    return None


def carry_generation_assistant_internal(
    source: ModelOutput, target: ModelOutput
) -> None:
    """Give `target` the replay state of the calls of `source` it carries.

    For an output rebuilt from `source` (e.g. by a response filter). A call
    `target` carries keeps the state of the call parsed under its ID if it is
    that call, or that call with other arguments (`_handed_edited`, which
    `generation_call_states` applies again when the state is used). Any other
    call has no state in `target`, and an ID shared in `source` or `target`
    stays shared (`shared_call_ids`).
    """
    replay = generation_assistant_internal(source)
    if replay is None:
        share_call_ids(target, _recorded_shared(_output_replay(source)))
        return
    parsed = cast(dict[str, dict[str, JsonValue] | None], replay["calls"])
    calls = [
        call for choice in target.choices for call in choice.message.tool_calls or []
    ]
    shared = _repeated_ids(calls)
    carried: dict[str, JsonValue] = {}
    for call in calls:
        if call.id in shared or (call.id in parsed and parsed[call.id] is None):
            carried[call.id] = None
        elif (state := parsed.get(call.id)) is None:
            continue
        elif _handed_edited(state, call) is not None:
            carried[call.id] = state
    target._assistant_internal = {"calls": carried, "providers": replay["providers"]}
    share_call_ids(target, _recorded_shared(replay))


def _call_digest(call: ToolCall) -> str:
    # repr, as parsed arguments may hold values JSON can't order or encode (e.g.
    # YAML dates as keys); an unstable repr only drops the call's state
    return sha256(repr([call.function, call.type, call.arguments]).encode()).hexdigest()


def alias_assistant_internal_call(
    call_id: str,
    alias: str,
    state: GenerationCallState,
    bridge: dict[str, JsonValue],
    modified: ToolCall | None = None,
) -> None:
    """Record a tool call's per-call replay state under the ID it is handed on under.

    So the call replays to the model as it was generated (native call type,
    position among the turn's content), with the `modified` call's arguments
    when approval or a response filter changed them. The state is the one the
    call's generation was parsed with (`generation_call_states`), never what a
    provider has since recorded under `call_id`.

    Under the model's ID (`alias == call_id`) the state goes in `bridge`, the
    handing bridge's own state, replayed only while that bridge serves a
    request (`bridge_replay_scope`): a later generation, native or another
    bridge's, can reuse the ID, and replays what its provider records under it.
    Under a token the bridge minted, which no generation produces, it goes in
    the provider's state, so the call replays as handed wherever its
    conversation is continued.
    """
    if _HAS_OPENAI and state.openai is not None:
        try:
            from inspect_ai.model._openai_responses import alias_openai_tool_call

            alias_openai_tool_call(
                call_id,
                alias,
                state.openai,
                modified,
                _bridge_section(bridge, "openai") if alias == call_id else None,
            )
        except ImportError:
            pass

    if _HAS_ANTHROPIC and state.anthropic is not None:
        try:
            from inspect_ai.model._providers.anthropic import (
                alias_anthropic_tool_call,
            )

            alias_anthropic_tool_call(
                alias,
                state.anthropic,
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
