import json
from typing import Any

import pytest
from acp.schema import ElicitationSchema

from inspect_ai.tool import ToolError, ask_user
from inspect_ai.tool._tool_def import tool_def_fields
from inspect_ai.util import InputResult
from inspect_ai.util._input import request as request_module


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }


async def test_accepted_returns_json_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = {"name": "alice", "age": 30}

    async def fake_request_input(
        *, message: str, schema: ElicitationSchema, metadata: Any = None
    ) -> InputResult:
        return InputResult(outcome="accepted", content=content)

    monkeypatch.setattr(request_module, "request_input", fake_request_input)
    # The tool imports request_input by name from inspect_ai.util, so
    # patch that binding too.
    import inspect_ai.tool._tools._ask_user as ask_user_module

    monkeypatch.setattr(ask_user_module, "request_input", fake_request_input)

    tool = ask_user()
    result = await tool("Who are you?", _schema())
    assert isinstance(result, str)
    assert json.loads(result) == content


async def test_declined_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request_input(*, message, schema, metadata=None):
        return InputResult(outcome="declined")

    import inspect_ai.tool._tools._ask_user as ask_user_module

    monkeypatch.setattr(ask_user_module, "request_input", fake_request_input)

    tool = ask_user()
    with pytest.raises(ToolError) as exc_info:
        await tool("Who are you?", _schema())
    assert "declined" in exc_info.value.message.lower()


async def test_cancelled_raises_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request_input(*, message, schema, metadata=None):
        return InputResult(outcome="cancelled")

    import inspect_ai.tool._tools._ask_user as ask_user_module

    monkeypatch.setattr(ask_user_module, "request_input", fake_request_input)

    tool = ask_user()
    with pytest.raises(ToolError) as exc_info:
        await tool("Who are you?", _schema())
    assert "cancel" in exc_info.value.message.lower()


async def test_schema_dict_is_validated_into_elicitation_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The model supplies a dict; the orchestrator receives a typed
    # ElicitationSchema with the same shape (validation reconstructs).
    captured: dict[str, Any] = {}

    async def fake_request_input(*, message, schema, metadata=None):
        captured["message"] = message
        captured["schema"] = schema
        return InputResult(outcome="accepted", content={"name": "x"})

    import inspect_ai.tool._tools._ask_user as ask_user_module

    monkeypatch.setattr(ask_user_module, "request_input", fake_request_input)

    tool = ask_user()
    await tool("hi", _schema())

    assert captured["message"] == "hi"
    assert isinstance(captured["schema"], ElicitationSchema)
    assert captured["schema"].properties is not None
    assert "name" in captured["schema"].properties


async def test_uppercase_types_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Some providers (Gemini) emit uppercase `type` names. The tool should
    # lowercase them before pydantic validation.
    captured: dict[str, Any] = {}

    async def fake_request_input(*, message, schema, metadata=None):
        captured["schema"] = schema
        return InputResult(outcome="accepted", content={"name": "x"})

    import inspect_ai.tool._tools._ask_user as ask_user_module

    monkeypatch.setattr(ask_user_module, "request_input", fake_request_input)

    uppercase = {
        "type": "OBJECT",
        "properties": {"name": {"type": "STRING"}},
        "required": ["name"],
    }
    tool = ask_user()
    await tool("hi", uppercase)

    assert isinstance(captured["schema"], ElicitationSchema)


async def test_invalid_schema_raises_tool_error() -> None:
    # The model supplies a malformed schema dict — pydantic validation
    # should fail and produce a ToolError the model can self-correct from.
    tool = ask_user()
    with pytest.raises(ToolError) as exc_info:
        await tool("hi", {"type": "object", "properties": {"x": {"type": "bogus"}}})
    assert "invalid schema" in exc_info.value.message.lower()


def test_tool_def_fields_expose_message_and_schema_params() -> None:
    # Guards against accidental loss of the typed-arg surface: the model needs
    # to see both `message` and `schema` with the right shapes.
    fields = tool_def_fields(ask_user())
    assert fields.name == "ask_user"
    assert fields.description.strip(), "tool description must be non-empty"
    params = fields.parameters.properties
    assert "message" in params, "message param missing"
    assert "schema" in params, "schema param missing"
    assert params["message"].type == "string"
    assert params["schema"].type == "object"


def test_tool_surface_size_reduced() -> None:
    # Regression: the whole point of dict[str, Any] over typed ElicitationSchema
    # is to shrink the cached prompt surface. The parameters JSON for an
    # untyped dict should be tiny (< 1 kB) — much smaller than the ~5.5 kB
    # we'd ship if `schema` were typed.
    fields = tool_def_fields(ask_user())
    params_json = json.dumps(fields.parameters.model_dump(exclude_none=True))
    assert len(params_json) < 1000, (
        f"parameters JSON is {len(params_json)} bytes; if this regressed "
        "past 1 kB the typed-schema bloat has likely returned."
    )
