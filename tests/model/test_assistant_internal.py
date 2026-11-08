"""Tests for sample-scoped assistant-internal state.

Covers the `find_spec` caching in `init_sample_assistant_internal` (called
once per sample; `importlib.util.find_spec` walks importer paths at ~3 ms
per call, so availability is cached at module load) and the dump/restore
round-trip used by checkpoint backup/hydrate.
"""

from __future__ import annotations

import importlib
import json
import pickle
import time
from typing import Any, cast
from unittest.mock import patch

from pydantic import JsonValue

from inspect_ai._util._async import tg_collect
from inspect_ai.model import ChatCompletionChoice, ChatMessageAssistant, ModelOutput
from inspect_ai.model._assistant_internal import (
    dump_sample_assistant_internal,
    init_sample_assistant_internal,
)
from inspect_ai.tool import ToolCall


def test_init_sample_assistant_internal_does_not_call_find_spec() -> None:
    """Calling `init_sample_assistant_internal` must not invoke `find_spec`.

    The check happens at module load. Each per-sample invocation should be
    a cheap boolean check + (potentially) cached imports — no path walking.
    """
    call_count = 0
    original_find_spec = importlib.util.find_spec

    def tracking_find_spec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_find_spec(*args, **kwargs)

    with patch("importlib.util.find_spec", tracking_find_spec):
        for _ in range(50):
            init_sample_assistant_internal()

    assert call_count == 0, (
        f"`init_sample_assistant_internal` called find_spec {call_count} times; "
        f"package availability should be cached at module load"
    )


def test_init_sample_assistant_internal_is_fast() -> None:
    """100 calls must be effectively free.

    Without caching, each call costs ~3 ms × 2 lookups = ~6 ms, so 100
    calls would be ~600 ms. With caching, each call is a couple of bool
    checks + sys.modules lookups for the imports — sub-millisecond per call.
    """
    # Warm up sys.modules for the imports (matches steady-state behavior).
    init_sample_assistant_internal()

    t0 = time.perf_counter()
    for _ in range(100):
        init_sample_assistant_internal()
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.05, (
        f"100 calls to init_sample_assistant_internal took {elapsed * 1000:.0f}ms — "
        f"find_spec cache may not be active"
    )


# === dump / restore round-trip ==============================================


def test_dump_empty_returns_none() -> None:
    init_sample_assistant_internal()
    assert dump_sample_assistant_internal() is None


def test_openai_round_trip() -> None:
    from inspect_ai.model._openai_responses import assistant_internal

    init_sample_assistant_internal()
    internal = assistant_internal()
    internal.tool_calls["call_1"] = {
        "type": "function_call",
        "call_id": "call_1",
        "name": "bash",
        "arguments": '{"cmd": "ls"}',
    }
    internal.server_tool_uses["ws_1"] = {
        "type": "web_search_call",
        "id": "ws_1",
        "status": "completed",
        "action": {"type": "search", "query": "q"},
    }

    dump = dump_sample_assistant_internal()
    assert dump is not None
    restored_value = json.loads(json.dumps(dump))

    init_sample_assistant_internal()
    assert not assistant_internal().tool_calls
    init_sample_assistant_internal(restored_value)
    assert assistant_internal().tool_calls == internal.tool_calls
    assert assistant_internal().server_tool_uses == internal.server_tool_uses


def test_anthropic_round_trip() -> None:
    from inspect_ai.model._providers.anthropic import (
        _ServerToolSpan,
        assistant_internal,
    )

    init_sample_assistant_internal()
    internal = assistant_internal()
    internal.thinking_blocks["hash1"] = {
        "type": "thinking",
        "thinking": "hmm",
        "signature": "sig",
    }
    internal.tool_call_internal_names["tc_1"] = "internal_name"
    internal.tool_call_internal_names["tc_2"] = None
    internal.server_mcp_tool_uses["mcp_1"] = (
        {
            "type": "mcp_tool_use",
            "id": "mcp_1",
            "name": "n",
            "server_name": "s",
            "input": {},
        },
        {
            "type": "mcp_tool_result",
            "tool_use_id": "mcp_1",
            "is_error": False,
            "content": [],
        },
    )
    # one span shared between the message map and the index; one index-only
    shared = _ServerToolSpan(
        blocks=[
            {
                "type": "server_tool_use",
                "id": "stu_1",
                "name": "web_search",
                "input": {},
            }
        ],
        content_ids=["stu_1"],
        open_use_ids={"stu_1"},
    )
    index_only = _ServerToolSpan(content_ids=["stu_2"])
    internal.server_tool_spans["msg_1"] = [shared]
    internal.server_tool_span_index["stu_1"] = shared
    internal.server_tool_span_index["stu_2"] = index_only

    dump = dump_sample_assistant_internal()
    assert dump is not None
    restored_value = json.loads(json.dumps(dump))

    init_sample_assistant_internal()
    assert not assistant_internal().thinking_blocks
    init_sample_assistant_internal(restored_value)

    restored = assistant_internal()
    assert restored.thinking_blocks == internal.thinking_blocks
    assert restored.tool_call_internal_names == internal.tool_call_internal_names
    # JSON turns the (use, result) tuple into a list; restore rebuilds tuples
    assert restored.server_mcp_tool_uses == internal.server_mcp_tool_uses
    assert isinstance(restored.server_mcp_tool_uses["mcp_1"], tuple)
    assert restored.server_tool_spans["msg_1"][0] == shared
    assert restored.server_tool_span_index["stu_2"] == index_only
    # object identity between the message map and the index survived
    assert (
        restored.server_tool_span_index["stu_1"]
        is restored.server_tool_spans["msg_1"][0]
    )


async def test_restore_in_child_task_visible_to_siblings() -> None:
    """Restore mutates the current instances in place (no ContextVar rebind).

    The checkpoint hydrate path restores from the solver's task; in-place
    mutation is what makes the restored state visible to sibling tasks
    (e.g. scorers) that inherited the instances bound at sample start.
    """
    from inspect_ai.model._providers.anthropic import assistant_internal

    init_sample_assistant_internal()

    value: JsonValue = {
        "anthropic": {
            "thinking_blocks": {
                "h": {"type": "thinking", "thinking": "t", "signature": "s"}
            }
        }
    }

    async def restore() -> None:
        init_sample_assistant_internal(value)

    await tg_collect([restore])
    assert "h" in assistant_internal().thinking_blocks


def test_an_output_cached_before_private_attributes_records_no_replay_state() -> None:
    from inspect_ai.model import ModelOutput
    from inspect_ai.model._assistant_internal import generation_assistant_internal

    output = ModelOutput()
    # how pydantic unpickles a model pickled before it had private attributes
    object.__setattr__(output, "__pydantic_private__", None)
    assert generation_assistant_internal(output) is None


async def test_a_responses_parse_keeps_its_own_replay_state_with_its_output() -> None:
    from openai.types.responses import Response, ResponseFunctionToolCall

    from inspect_ai.model import model_output_from_openai_responses
    from inspect_ai.model._assistant_internal import (
        generation_assistant_internal,
        has_generation_call_state,
    )
    from inspect_ai.model._openai_responses import assistant_internal

    init_sample_assistant_internal()

    def call(item_id: str | None, call_id: str) -> ResponseFunctionToolCall:
        return ResponseFunctionToolCall(
            id=item_id,
            type="function_call",
            call_id=call_id,
            name="read_file",
            arguments="{}",
        )

    output = await model_output_from_openai_responses(
        Response.model_validate(
            {
                "id": "resp_1",
                "created_at": 0,
                "model": "gpt-5",
                "object": "response",
                "output": [call("fc_1", "call_item"), call(None, "call_itemless")],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            }
        )
    )
    replay = generation_assistant_internal(output)
    # a later parse replacing the provider's state leaves the output's own
    assistant_internal().tool_calls["call_item"] = cast(Any, {"type": "other"})
    assistant_internal().tool_calls["call_itemless"] = cast(Any, {"type": "other"})

    assert has_generation_call_state(replay, "call_item")
    assert not has_generation_call_state(replay, "call_itemless")
    assert generation_assistant_internal(pickle.loads(pickle.dumps(output))) == replay
    assert generation_assistant_internal(output.model_copy(deep=True)) == replay
    rebuilt = ModelOutput.model_validate(output.model_dump())
    assert generation_assistant_internal(rebuilt) is None
    # the replay state is not part of the output's value
    assert rebuilt == output


def test_a_copy_keeps_the_replay_state_of_the_calls_it_leaves_unchanged() -> None:
    from inspect_ai.model._assistant_internal import (
        carry_generation_assistant_internal,
        generation_assistant_internal,
        generation_replay,
        has_generation_call_state,
        set_generation_assistant_internal,
    )

    calls = [
        ToolCall(id="kept", function="read_file", arguments={"path": "a"}),
        ToolCall(id="edited", function="read_file", arguments={"path": "b"}),
    ]
    output = set_generation_assistant_internal(
        ModelOutput(
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="", tool_calls=calls),
                    stop_reason="tool_calls",
                )
            ]
        ),
        generation_replay(
            calls,
            openai={call.id: {"type": "function_call"} for call in calls},
            anthropic={
                "names": {call.id: None for call in calls},
                "positions": {call.id: 0 for call in calls},
            },
        ),
    )
    copy = ModelOutput.model_validate(output.model_dump())
    assert copy.message.tool_calls
    copy.message.tool_calls[1].arguments = {"path": "c"}

    carry_generation_assistant_internal(output, copy)

    replay = generation_assistant_internal(copy)
    assert has_generation_call_state(replay, "kept")
    assert not has_generation_call_state(replay, "edited")
    original = cast(dict[str, Any], generation_assistant_internal(output))
    assert replay == {
        "calls": {"kept": original["calls"]["kept"]},
        "openai": {"kept": {"type": "function_call"}},
        "anthropic": {"names": {"kept": None}, "positions": {"kept": 0}},
    }


def _calling(call_id: str) -> ModelOutput:
    return ModelOutput(
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="",
                    tool_calls=[ToolCall(id=call_id, function="f", arguments={})],
                )
            )
        ]
    )


def test_a_fresh_output_without_replay_state_needs_none_unless_a_provider_kept_some() -> (
    None
):
    from inspect_ai.model._assistant_internal import (
        default_generation_assistant_internal,
        generation_assistant_internal,
        keeps_generation_call_id,
    )
    from inspect_ai.model._openai_responses import assistant_internal
    from inspect_ai.model._providers.anthropic import (
        assistant_internal as anthropic_internal,
    )

    init_sample_assistant_internal()
    assistant_internal().tool_calls["call_responses"] = {
        "type": "function_call",
        "call_id": "call_responses",
        "name": "f",
        "arguments": "{}",
    }
    anthropic_internal().client_tool_call_positions["toolu_1"] = 0

    for call_id, stateless in [
        ("call_stateless", True),
        ("call_responses", False),
        ("toolu_1", False),
    ]:
        output = _calling(call_id)
        default_generation_assistant_internal(output)
        replay = generation_assistant_internal(output)
        assert (replay is not None) == stateless
        assert keeps_generation_call_id(replay, call_id) == stateless
