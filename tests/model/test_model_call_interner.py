import contextvars
from typing import Any

from pydantic import JsonValue

from inspect_ai.model._model_call import (
    ModelCall,
    _call_interner,
    _walk_json_value,
    init_call_interner,
)
from inspect_ai.model._openai import openai_media_filter

IMAGE = "data:image/png;base64," + "A" * (300 * 1024)


def _requests(turns: int) -> list[dict[str, Any]]:
    """Growing requests rebuilt from scratch each turn, as providers do."""
    history: list[dict[str, Any]] = [{"role": "system", "content": "sys"}]
    requests = []
    for i in range(turns):
        history.append({"role": "user", "content": f"turn {i}", "n": i})
        if i % 3 == 0:
            history.append(
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": IMAGE}}],
                }
            )
        requests.append(
            {"model": "m", "temperature": 1, "messages": [dict(m) for m in history]}
        )
    return requests


def _in_fresh_context(fn: Any) -> Any:
    return contextvars.copy_context().run(fn)


def test_interned_calls_match_uninterned_and_share_objects() -> None:
    def run() -> list[ModelCall]:
        init_call_interner()
        return [
            ModelCall.create(r, None, filter=openai_media_filter) for r in _requests(8)
        ]

    interned: list[ModelCall] = _in_fresh_context(run)
    for call, request in zip(interned, _requests(8)):
        expected = _walk_json_value(None, request, openai_media_filter)
        assert call.request == expected

    first = interned[-2].request["messages"]
    last = interned[-1].request["messages"]
    assert isinstance(first, list) and isinstance(last, list)
    assert all(x is y for x, y in zip(first, last))
    assert IMAGE not in str(last)


def test_calls_without_interner_are_independent() -> None:
    def run() -> list[ModelCall]:
        _call_interner.set(None)
        return [ModelCall.create(r, None) for r in _requests(3)]

    calls: list[ModelCall] = _in_fresh_context(run)
    a, b = calls[-2].request["messages"], calls[-1].request["messages"]
    assert isinstance(a, list) and isinstance(b, list)
    assert a[0] == b[0] and a[0] is not b[0]


def test_interner_keeps_json_distinct_values_apart() -> None:
    def run() -> tuple[ModelCall, ModelCall]:
        init_call_interner()
        first = ModelCall.create({"messages": [{"role": "user", "n": 1}]}, None)
        second = ModelCall.create(
            {"messages": [{"role": "user", "n": 1.0}, {"role": "user"}]}, None
        )
        return first, second

    first, second = _in_fresh_context(run)
    msgs: JsonValue = second.request["messages"]
    assert isinstance(msgs, list) and isinstance(msgs[0], dict)
    assert type(msgs[0]["n"]) is float
    assert msgs[0] is not first.request["messages"][0]
