from typing import Any
from unittest.mock import MagicMock

import pytest
from google.genai.types import FunctionCall
from test_helpers.utils import skip_if_no_google

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.event import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ChatMessage, ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._providers._google_computer_use import (
    _parse_gemini_action,
    gemini_action_from_tool_call,
    tool_call_from_gemini_computer_action,
)
from inspect_ai.model._providers.google import content as google_content
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tools._computer._computer import computer

PNG_DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def test_click_at_bidirectional():
    args = {"action": "left_click", "coordinate": [683, 384]}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "click_at"
    assert abs(action_args["x"] - 500) <= 1
    assert abs(action_args["y"] - 500) <= 1

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_hover_at_bidirectional():
    args = {"action": "mouse_move", "coordinate": [273, 307]}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "hover_at"
    assert abs(action_args["x"] - 200) <= 1
    assert abs(action_args["y"] - 400) <= 1

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_type_text_at_bidirectional():
    args = {
        "action": "type",
        "text": "hello world",
        "coordinate": [507, 361],
        "press_enter": True,
        "clear_before_typing": True,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "type_text_at"
    assert action_args["text"] == "hello world"
    assert abs(action_args["x"] - 371) <= 1
    assert abs(action_args["y"] - 470) <= 1
    assert action_args["press_enter"] is True
    assert action_args["clear_before_typing"] is True

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_type_text_at_press_enter_false():
    function_call = FunctionCall(
        name="type_text_at",
        args={"text": "hello world", "press_enter": False},
    )
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.arguments["action"] == "type"
    assert parsed.arguments["press_enter"] is False


def test_type_text_at_default_press_enter():
    function_call = FunctionCall(
        name="type_text_at",
        args={"text": "hello world"},
    )
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.arguments["action"] == "type"
    assert parsed.arguments["press_enter"] is True


def test_type_text_at_default_clear_before_typing():
    function_call = FunctionCall(
        name="type_text_at",
        args={"text": "hello world"},
    )
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.arguments["clear_before_typing"] is True


def test_type_text_at_clear_before_typing_false():
    function_call = FunctionCall(
        name="type_text_at",
        args={"text": "hello world", "clear_before_typing": False},
    )
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.arguments["clear_before_typing"] is False


def test_type_without_clear_before_typing_sends_false():
    """Gemini defaults to clearing, so a type call without it must say False."""
    tool_call = ToolCall(
        id="test",
        function="computer",
        arguments={"action": "type", "text": "hello", "coordinate": [10, 10]},
    )
    _, action_args = gemini_action_from_tool_call(tool_call)

    assert action_args["clear_before_typing"] is False


def test_key_combination_bidirectional():
    args = {"action": "key", "text": "ctrl+c"}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "key_combination"
    assert action_args["keys"] == "control+c"

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_key_combination_enter():
    function_call = FunctionCall(name="key_combination", args={"keys": "enter"})
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.arguments["action"] == "key"
    assert parsed.arguments["text"] == "Return"


def test_scroll_document_bidirectional():
    args = {
        "action": "scroll",
        "scroll_direction": "down",
        "scroll_amount": 3,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "scroll_document"
    assert action_args["direction"] == "down"

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_scroll_document_up():
    args = {
        "action": "scroll",
        "scroll_direction": "up",
        "scroll_amount": 3,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "scroll_document"
    assert action_args["direction"] == "up"


def test_scroll_document_left():
    args = {
        "action": "scroll",
        "scroll_direction": "left",
        "scroll_amount": 3,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "scroll_document"
    assert action_args["direction"] == "left"


def test_scroll_document_right():
    args = {
        "action": "scroll",
        "scroll_direction": "right",
        "scroll_amount": 3,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "scroll_document"
    assert action_args["direction"] == "right"


def test_scroll_at_bidirectional():
    args = {
        "action": "scroll",
        "coordinate": [683, 384],
        "scroll_direction": "up",
        "scroll_amount": 4,
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "scroll_at"
    assert abs(action_args["x"] - 500) <= 1
    assert abs(action_args["y"] - 500) <= 1
    assert action_args["direction"] == "up"
    assert action_args["magnitude"] == 400

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_drag_and_drop_bidirectional():
    args = {
        "action": "left_click_drag",
        "start_coordinate": [137, 154],
        "coordinate": [1093, 461],
    }
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "drag_and_drop"
    assert abs(action_args["x"] - 100) <= 1
    assert abs(action_args["y"] - 200) <= 1
    assert abs(action_args["destination_x"] - 800) <= 1
    assert abs(action_args["destination_y"] - 600) <= 1

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_navigate_bidirectional():
    args = {"action": "navigate", "text": "https://example.com"}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "navigate"
    assert action_args["url"] == "https://example.com"

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_open_web_browser_bidirectional():
    args = {"action": "open_web_browser"}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "open_web_browser"
    assert action_args == {}

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == args


def test_wait_bidirectional():
    args = {"action": "wait"}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "wait_5_seconds"
    assert action_args == {}

    function_call = FunctionCall(name=action_name, args=action_args)
    parsed = tool_call_from_gemini_computer_action(function_call)
    assert parsed.arguments == {"action": "wait", "duration": 5}


def test_go_back():
    function_call = FunctionCall(name="go_back", args={})
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.function == "computer"
    assert parsed.arguments["action"] == "key"
    assert parsed.arguments["text"] == "alt+Left"


def test_go_forward():
    function_call = FunctionCall(name="go_forward", args={})
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.function == "computer"
    assert parsed.arguments["action"] == "key"
    assert parsed.arguments["text"] == "alt+Right"


def test_search():
    function_call = FunctionCall(name="search", args={"query": "inspect ai framework"})
    parsed = tool_call_from_gemini_computer_action(function_call)

    assert parsed.function == "computer"
    assert parsed.arguments["action"] == "navigate"
    assert parsed.arguments["text"] == "inspect ai framework"


def test_unknown_gemini_action_defaults_to_screenshot():
    parsed = _parse_gemini_action("unknown_action", {})
    assert parsed == {"action": "screenshot"}


def test_unknown_inspect_action_defaults_to_wait():
    args = {"action": "screenshot"}
    tool_call = ToolCall(id="test", function="computer", arguments=args)
    action_name, action_args = gemini_action_from_tool_call(tool_call)

    assert action_name == "wait_5_seconds"
    assert action_args == {}


def test_scroll_at_default_magnitude():
    parsed = _parse_gemini_action(
        "scroll_at", {"x": 500, "y": 500, "direction": "down"}
    )
    assert parsed["action"] == "scroll"
    # Default magnitude is 800, so scroll_amount = 800 // 100 = 8
    assert parsed["scroll_amount"] == 8


# Calls in the argument schemas of Google's legacy computer-use actions. Each
# coordinate maps to a screen pixel and back to itself.
GEMINI_COMPUTER_CALLS: list[tuple[str, dict[str, object]]] = [
    ("open_web_browser", {}),
    ("wait_5_seconds", {}),
    ("go_back", {}),
    ("go_forward", {}),
    ("search", {}),
    ("search", {"query": "inspect ai framework"}),
    ("navigate", {"url": "https://example.com"}),
    ("click_at", {"x": 500, "y": 500}),
    ("hover_at", {"x": 200, "y": 250}),
    (
        "type_text_at",
        {
            "x": 500,
            "y": 500,
            "text": "hello",
            "press_enter": True,
            "clear_before_typing": True,
        },
    ),
    (
        "type_text_at",
        {
            "x": 500,
            "y": 500,
            "text": "hello",
            "press_enter": False,
            "clear_before_typing": False,
        },
    ),
    ("key_combination", {"keys": "control+c"}),
    ("key_combination", {"keys": "enter"}),
    ("scroll_document", {"direction": "down"}),
    ("scroll_at", {"x": 500, "y": 500, "direction": "up", "magnitude": 400}),
    (
        "drag_and_drop",
        {"x": 100, "y": 250, "destination_x": 800, "destination_y": 500},
    ),
]


async def _replay(tool_call: ToolCall) -> FunctionCall:
    content = await google_content(
        MagicMock(),
        ChatMessageAssistant(content="", tool_calls=[tool_call]),
    )
    assert content.parts is not None
    function_calls = [p.function_call for p in content.parts if p.function_call]
    assert len(function_calls) == 1
    return function_calls[0]


@pytest.mark.parametrize(
    "name,args",
    GEMINI_COMPUTER_CALLS,
    ids=[f"{name}-{i}" for i, (name, _) in enumerate(GEMINI_COMPUTER_CALLS)],
)
async def test_unmodified_gemini_computer_call_replays_as_sent(
    name: str, args: dict[str, object]
) -> None:
    tool_call = tool_call_from_gemini_computer_action(
        FunctionCall(name=name, args=args)
    )

    replayed = await _replay(tool_call)

    assert replayed.id == tool_call.id
    assert replayed.name == name
    assert replayed.args == args


# type_text_at calls that leave out press_enter or clear_before_typing. Parsing
# fills in Gemini's defaults, so replay sends the same values explicitly.
TYPE_TEXT_AT_OMITTED_DEFAULTS: list[tuple[dict[str, object], dict[str, object]]] = [
    (
        {"x": 500, "y": 500, "text": "hello", "press_enter": True},
        {"press_enter": True, "clear_before_typing": True},
    ),
    (
        {"x": 500, "y": 500, "text": "hello", "press_enter": False},
        {"press_enter": False, "clear_before_typing": True},
    ),
    (
        {"x": 500, "y": 500, "text": "hello"},
        {"press_enter": True, "clear_before_typing": True},
    ),
]


@pytest.mark.parametrize(
    "args,flags",
    TYPE_TEXT_AT_OMITTED_DEFAULTS,
    ids=["press_enter-true", "press_enter-false", "no-flags"],
)
async def test_gemini_type_text_at_replays_omitted_defaults_explicitly(
    args: dict[str, object], flags: dict[str, object]
) -> None:
    tool_call = tool_call_from_gemini_computer_action(
        FunctionCall(name="type_text_at", args=args)
    )

    replayed = await _replay(tool_call)

    assert tool_call.arguments["clear_before_typing"] is True
    assert replayed.id == tool_call.id
    assert replayed.name == "type_text_at"
    assert replayed.args == {**args, **flags}


# Alias calls edited into another action, which no longer match the alias.
EDITED_ALIAS_CALLS: list[tuple[str, dict[str, object], dict[str, object]]] = [
    ("go_back", {"action": "key", "text": "ctrl+c"}, {"keys": "control+c"}),
    ("go_forward", {"action": "key", "text": "alt+Left"}, {"keys": "alt+left"}),
    (
        "search",
        {"action": "left_click", "coordinate": [683, 384]},
        {"x": 500, "y": 500},
    ),
]


def _parsed_alias_call(name: str) -> ToolCall:
    args = {"query": "inspect ai framework"} if name == "search" else {}
    return tool_call_from_gemini_computer_action(FunctionCall(name=name, args=args))


@pytest.mark.parametrize(
    "name,edited,expected",
    EDITED_ALIAS_CALLS,
    ids=["go_back-key", "go_forward-key", "search-click"],
)
async def test_gemini_alias_call_edited_into_another_action_uses_its_conversion(
    name: str, edited: dict[str, object], expected: dict[str, object]
) -> None:
    tool_call = _parsed_alias_call(name)
    tool_call.arguments = edited

    replayed = await _replay(tool_call)

    assert replayed.name == name
    assert replayed.args == expected == gemini_action_from_tool_call(tool_call)[1]


async def test_gemini_search_call_with_edited_text_replays_it_as_the_query() -> None:
    tool_call = _parsed_alias_call("search")
    tool_call.arguments = {"action": "navigate", "text": "https://allowed.example"}

    replayed = await _replay(tool_call)

    assert replayed.name == "search"
    assert replayed.args == {"query": "https://allowed.example"}


async def test_gemini_computer_call_and_result_use_the_same_name() -> None:
    tool_call = tool_call_from_gemini_computer_action(
        FunctionCall(name="search", args={})
    )

    replayed = await _replay(tool_call)
    result = await google_content(
        MagicMock(),
        ChatMessageTool(content="ok", tool_call_id=tool_call.id, function="computer"),
    )

    assert result.parts is not None
    function_response = result.parts[0].function_response
    assert function_response is not None
    assert function_response.name == replayed.name == "search"


LIVE_ALIAS_PROMPTS = {
    "go_back": "The browser is already open and showing the second page of a site; "
    "you navigated there from the first page. Go back to the previous page.",
    "go_forward": "The browser is already open. You just went back from the second "
    "page of a site to the first page. Go forward to the second page again.",
    "search": "The browser is already open. Go to the search engine so you can "
    "start a web search.",
}


# requests are recorded with snake_case keys and responses with camelCase keys
def _function_calls(contents: Any, name: str) -> list[tuple[Any, str | None]]:
    calls: list[tuple[Any, str | None]] = []
    for content in contents:
        for part in content.get("parts") or []:
            call = part.get("function_call") or part.get("functionCall") or {}
            if call.get("name") == name:
                signature = part.get("thought_signature", part.get("thoughtSignature"))
                if isinstance(signature, str) and signature.startswith("attachment://"):
                    signature = transcript().attachments[
                        signature.removeprefix("attachment://")
                    ]
                calls.append((call.get("args") or {}, signature))
    return calls


@skip_if_no_google
@pytest.mark.parametrize("action", list(LIVE_ALIAS_PROMPTS))
async def test_live_gemini_alias_call_replays_as_sent_and_continues(
    action: str,
) -> None:
    init_transcript(Transcript())
    model = get_model(
        "google/gemini-3-flash-preview",
        config=GenerateConfig(max_retries=2, timeout=120),
    )
    screenshot = ContentImage(image=PNG_DATA_URI)
    messages: list[ChatMessage] = [
        ChatMessageUser(
            content=[ContentText(text=LIVE_ALIAS_PROMPTS[action]), screenshot]
        )
    ]
    # the model may open the browser before taking the requested action
    for _ in range(3):
        output = await model.generate(messages, tools=[computer()])
        calls = output.message.tool_calls or []
        messages.append(output.message)
        messages.extend(
            ChatMessageTool(
                content=[ContentText(text="done"), screenshot],
                tool_call_id=call.id,
                function="computer",
            )
            for call in calls
        )
        if any(call.id.startswith(f"{action}_") for call in calls):
            break
    else:
        pytest.fail(f"{model.name} did not call {action}")
    await model.generate(messages, tools=[computer()])

    events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert [e.error for e in events] == [None] * len(events)
    assert events[-2].call is not None and events[-1].call is not None
    response: Any = events[-2].call.response
    [(sent_args, sent_signature)] = _function_calls(
        [response["candidates"][0]["content"]], action
    )
    [replayed] = _function_calls(events[-1].call.request["contents"], action)
    assert sent_signature
    assert replayed == (sent_args, sent_signature)
