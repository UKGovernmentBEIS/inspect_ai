"""Unit tests for the control-channel per-sample store helpers.

The per-key projection and the key filter are pure functions, exercised
directly. The end-to-end `sample_store` (live `TaskState` vs terminal
recorder/log source, key filtering, projection tiers) is exercised by
monkeypatching the two sources the way `test_messages.py` does.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.store import _filter_keys, _project, sample_store
from inspect_ai.util._store import Store

# --- projection -----------------------------------------------------------


def test_project_metadata_types_size_and_len() -> None:
    out = _project({"a": 1, "b": 2}, content=False)
    assert out["type"] == "object"
    assert out["len"] == 2
    # bytes of compact JSON
    assert out["size"] == len('{"a":1,"b":2}')
    assert "value" not in out

    assert _project("hello", content=False) == {
        "type": "string",
        "size": len('"hello"'),
        "len": 5,
    }
    # non-ASCII text counts real UTF-8 bytes, not the \uXXXX escape length
    assert _project("日本語", content=False)["size"] == len('"日本語"'.encode())

    assert _project([1, 2, 3], content=False)["type"] == "array"
    assert _project([1, 2, 3], content=False)["len"] == 3
    # scalars carry no length hint
    assert "len" not in _project(1.5, content=False)
    assert _project(1.5, content=False)["type"] == "number"
    # bool before int: a Python bool is an int
    assert _project(True, content=False)["type"] == "boolean"
    assert _project(None, content=False)["type"] == "null"


def test_project_content_adds_truncated_preview() -> None:
    out = _project("x" * 1000, content=True)
    assert len(out["value"]) < 1000
    assert out["value"].endswith("…")
    # the metadata fields still report the untruncated value
    assert out["len"] == 1000

    # non-strings preview as their JSON serialization
    out = _project({"phase": "search"}, content=True)
    assert "phase" in out["value"] and "search" in out["value"]


# --- key filtering ----------------------------------------------------------


def test_filter_keys_exact_prefix_and_missing() -> None:
    raw = {"phase": 1, "AgentState:notes": "n", "AgentState:steps": 3, "other": 0}
    selected, missing = _filter_keys(raw, ["phase", "AgentState:*", "nope"])
    # selection keeps store order; the exact miss is reported, prefixes never
    assert list(selected) == ["phase", "AgentState:notes", "AgentState:steps"]
    assert missing == ["nope"]

    # a key matched by several patterns appears once; repeats deduplicate
    selected, missing = _filter_keys(raw, ["phase", "phase", "phas*", "nope", "nope"])
    assert list(selected) == ["phase"]
    assert missing == ["nope"]


# --- running source (live TaskState) --------------------------------------


def _fake_running_sample(store: Store, *, completed: bool = False) -> Any:
    """A minimal stand-in for an in-flight ``ActiveSample`` carrying a state."""
    return SimpleNamespace(
        eval_id="e1",
        epoch=1,
        sample=SimpleNamespace(id=1),
        live_state=SimpleNamespace(store=store),
        completed=object() if completed else None,
    )


async def test_running_sample_serves_live_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod

    store = Store({"phase": "search", "attempts": 2})
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(store)]
    )

    page = await sample_store("e1", "1", 1)
    assert page is not None
    assert page["status"] == "running"
    assert page["count"] == 2
    assert set(page["store"]) == {"phase", "attempts"}
    # metadata tier: no values, no `missing` without a key filter
    assert "value" not in page["store"]["phase"]
    assert "missing" not in page

    # mid-run mutation is visible on the next poll (a snapshot, not a cache)
    store.set("best_score", 0.7)
    page = await sample_store("e1", "1", 1)
    assert page is not None
    assert page["count"] == 3
    assert "best_score" in page["store"]

    # a just-finished sample still lingering in active_samples is "completed"
    monkeypatch.setattr(
        samples_mod,
        "active_samples",
        lambda: [_fake_running_sample(store, completed=True)],
    )
    page = await sample_store("e1", "1", 1)
    assert page is not None
    assert page["status"] == "completed"


async def test_running_sample_key_filter_and_projection_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod

    store = Store(
        {"phase": "search", "AgentState:notes": "so far…", "blob": "x" * 4096}
    )
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(store)]
    )

    # exact + prefix selection; count stays the whole store's key count
    page = await sample_store("e1", "1", 1, keys=["phase", "AgentState:*", "gone"])
    assert page is not None
    assert page["count"] == 3
    assert set(page["store"]) == {"phase", "AgentState:notes"}
    assert page["missing"] == ["gone"]

    # --content adds the truncated preview
    page = await sample_store("e1", "1", 1, keys=["phase"], content=True)
    assert page is not None
    assert page["store"]["phase"]["value"] == "search"

    # --full returns the raw values
    page = await sample_store("e1", "1", 1, keys=["phase"], full=True)
    assert page is not None
    assert page["store"] == {"phase": "search"}


async def test_non_serializable_value_falls_back_to_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-JSON-serializable store value serializes as null (like the log)."""
    import inspect_ai.log._samples as samples_mod

    class Opaque:
        pass

    store = Store({"opaque": Opaque(), "plain": 1})
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(store)]
    )

    page = await sample_store("e1", "1", 1, full=True)
    assert page is not None
    assert page["store"] == {"opaque": None, "plain": 1}

    page = await sample_store("e1", "1", 1)
    assert page is not None
    assert page["store"]["opaque"]["type"] == "null"


async def test_missing_sample_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._samples as samples_mod

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    async def no_sample(*args: Any, **kwargs: Any) -> Any:
        return None

    monkeypatch.setattr(state_mod, "_full_sample", no_sample)

    assert await sample_store("e1", "nope", 1) is None


# --- terminal source (recorder / log) -------------------------------------


async def test_terminal_sample_serves_logged_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(
        id="s1",
        epoch=1,
        input="question",
        target="answer",
        store={"phase": "done", "attempts": 3},
    )

    excluded: list[Any] = []

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        excluded.append(exclude_fields)
        return sample if str(id) == "s1" and epoch == 1 else None

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_store("e1", "s1", 1, keys=["phase"], content=True)
        assert page is not None
        assert page["status"] == "completed"
        assert page["count"] == 2
        assert page["store"]["phase"]["value"] == "done"
        # heavy unconsumed fields are excluded from the read (error_retries
        # can carry full retry transcripts); `store` and the identity/error
        # fields the envelope needs are not
        assert excluded == [
            {"messages", "events", "attachments", "output", "error_retries"}
        ]
    finally:
        clear_all_eval_states()


async def test_terminal_pre_flush_store_serializes_raw_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-flush recorder sample holds raw Python store values.

    `create_eval_sample` copies `state.store` verbatim, so a terminal read
    during the pre-flush window must run values through the same
    serialization the log gets — never return them raw.
    """
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    class Opaque:
        pass

    # the raw object stands in for a pre-flush in-memory sample (the store
    # field is dict[str, Any], so nothing serializes it until read time)
    sample = EvalSample(
        id="s1", epoch=1, input="q", target="t", store={"opaque": Opaque(), "plain": 1}
    )

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_store("e1", "s1", 1, full=True)
        assert page is not None
        assert page["store"] == {"opaque": None, "plain": 1}
    finally:
        clear_all_eval_states()


async def test_terminal_source_resolved_once_across_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling a terminal sample's store parses the sample once, not per poll."""
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(id="s1", epoch=1, input="q", target="t", store={"k": 1})
    reads = [0]

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        reads[0] += 1
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page1 = await sample_store("e1", "s1", 1)
        page2 = await sample_store("e1", "s1", 1, keys=["k"], full=True)
        assert page1 is not None and page2 is not None
        assert page2["store"] == {"k": 1}
        assert reads[0] == 1

        # the run-boundary registry clear also drops the cached source
        clear_all_eval_states()
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        assert await sample_store("e1", "s1", 1) is not None
        assert reads[0] == 2
    finally:
        clear_all_eval_states()


async def test_running_attempt_invalidates_other_endpoints_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observing a retry on the store endpoint drops the sibling caches too."""
    import inspect_ai._control.messages as messages_mod
    import inspect_ai._control.store as store_mod
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.messages import MessagesSource

    key = ("e1", "1", 1)
    messages_mod._terminal_sources.put(
        key, MessagesSource(messages=[], status="completed")
    )

    running = _fake_running_sample(Store({"k": 1}))
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [running])
    assert await sample_store("e1", "1", 1) is not None

    assert messages_mod._terminal_sources.get(key) is None
    assert store_mod._terminal_sources.get(key) is None


async def test_terminal_errored_sample_reports_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log import EvalError, EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(
        id="s1",
        epoch=1,
        input="q",
        target="t",
        store={"k": 1},
        error=EvalError(message="boom", traceback="", traceback_ansi=""),
    )

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_store("e1", "s1", 1)
        assert page is not None
        assert page["status"] == "error"
    finally:
        clear_all_eval_states()
