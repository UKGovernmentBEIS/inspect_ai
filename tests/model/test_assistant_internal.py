"""Tests for sample-scoped assistant-internal state.

Covers the `find_spec` caching in `init_sample_assistant_internal` (called
once per sample; `importlib.util.find_spec` walks importer paths at ~3 ms
per call, so availability is cached at module load) and the dump/restore
round-trip used by checkpoint backup/hydrate.
"""

from __future__ import annotations

import importlib
import json
import time
from unittest.mock import patch

from pydantic import JsonValue

from inspect_ai._util._async import tg_collect
from inspect_ai.model._assistant_internal import (
    dump_sample_assistant_internal,
    init_sample_assistant_internal,
)


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
