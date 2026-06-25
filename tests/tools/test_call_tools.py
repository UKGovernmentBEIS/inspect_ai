import datetime
from dataclasses import dataclass
from datetime import date, time, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import BaseModel
from typing_extensions import TypedDict

from inspect_ai._util.content import ContentDocument, ContentText
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool import tool
from inspect_ai.tool._tool import tool_result_content
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._sandbox import SandboxTimeoutError

# --- Helpers ---------------------------------------------------------------


def make_call(function_name, args):
    return ToolCall(
        id="test", function=function_name, arguments=args or {}, parse_error=None
    )


# --- Simple tool -------------------------------------------------


@tool
def incr():
    async def incr(x: int) -> int:
        """
        Increment an integer by 1.

        Args:
            x (int): The integer to increment.

        Returns:
            int: The incremented result.
        """
        return x + 1

    return incr


# --- Complex tool ----------------------------------------------


class MyTypedDict(TypedDict):
    count: int
    label: str


@dataclass
class MyDataClass:
    value: float
    flag: bool


class MyPydanticModel(BaseModel):
    name: str
    id: int


class MyEnum(str, Enum):
    ALPHA = "alpha"
    BRAVO = "bravo"


@tool
def complex_tool():
    async def complex_tool(
        text: str,
        count: int,
        ratio: float,
        active: bool,
        enum: MyEnum,
        literal: Literal["a", "b"],
        numbers: List[int],
        strings: Set[str],
        tags: Tuple[str, ...],
        mapping: Dict[str, int],
        optional_text: Optional[str],
        either: Union[int, str],
        td: MyTypedDict,
        dc: MyDataClass,
        pm: MyPydanticModel,
        timestamp: datetime.datetime,
        the_date: date,
        the_time: time,
        anything: Any,
    ) -> dict:
        """
        Echo back diverse parameters of various types.

        Args:
            text (str): A simple text string.
            count (int): An integer count.
            ratio (float): A floating-point ratio.
            active (bool): A boolean flag.
            enum (MyEnum): An enum value.
            literal (Literal['a', 'b']): A literal value.
            numbers (List[int]): A list of integers.
            strings (Set[str]): A set of strings.
            tags (Tuple[str, ...]): A tuple of strings.
            mapping (Dict[str, int]): A dict mapping strings to integers.
            optional_text (Optional[str]): An optional string value.
            either (Union[int, str]): A value that can be int or str.
            td (MyTypedDict): A TypedDict with 'count' and 'label'.
            dc (MyDataClass): A dataclass with 'value' and 'flag'.
            pm (MyPydanticModel): A Pydantic model with 'name' and 'id'.
            timestamp (datetime): A datetime object.
            the_date (date): A date object.
            the_time (time): A time object.
            anything (Any): Any arbitrary data.

        Returns:
            dict: A dictionary echoing all inputs.
        """
        return {
            "text": text,
            "count": count,
            "ratio": ratio,
            "active": active,
            "enum": enum.value,
            "literal": literal,
            "numbers": numbers,
            "strings": strings,
            "tags": tags,
            "mapping": mapping,
            "optional_text": optional_text,
            "either": either,
            "td": td,
            "dc": {"value": dc.value, "flag": dc.flag},
            "pm": pm.model_dump(),
            "timestamp": timestamp,
            "the_date": the_date,
            "the_time": the_time,
            "anything": anything,
        }

    return complex_tool


@tool
def document_tool():
    async def document_tool() -> ContentDocument:
        """Return a document tool result."""
        return ContentDocument(document="/path/to/report.pdf")

    return document_tool


@tool
def mixed_content_tool():
    async def mixed_content_tool() -> list[ContentText | ContentDocument]:
        """Return mixed structured content."""
        return [
            ContentText(text="Attached report"),
            ContentDocument(document="/path/to/report.pdf"),
        ]

    return mixed_content_tool


# --- Positive tests -------------------------------------------------------
async def test_incr_simple_positive():
    """Calling incr(0) should return 1."""
    tool_def = ToolDef(incr())
    call = make_call("incr", {"x": 0})

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].content == "1"


async def test_complex_tool_all_params():
    """Exercise every parameter type in one call."""
    args = {
        "text": "hello",
        "count": 10,
        "ratio": 0.75,
        "active": False,
        "enum": "alpha",
        "literal": "a",
        "numbers": [5, 10, 15],
        "strings": ["a", "b", "c"],
        "tags": ["x", "y", "z"],
        "mapping": {"a": 1, "b": 2},
        "optional_text": "opt",
        "either": 123,
        "td": {"count": 1, "label": "one"},
        "dc": {"value": 2.5, "flag": True},
        "pm": {"name": "test", "id": 42},
        "timestamp": "2025-04-17T12:00:00",
        "the_date": "2025-04-17",
        "the_time": "12:00:00",
        "anything": {"complex": ["structure", 123]},
    }
    tool_def = ToolDef(complex_tool())
    call = make_call("complex_tool", args)

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)

    result = eval(messages[-1].content)

    # primitives
    assert result["text"] == "hello"
    assert result["count"] == 10
    assert abs(result["ratio"] - 0.75) < 1e-9
    assert result["active"] is False

    # enum/literal
    assert result["enum"] == "alpha"
    assert result["literal"] == "a"

    # collections
    assert result["numbers"] == [5, 10, 15]
    assert result["strings"] == {"a", "b", "c"}
    assert result["tags"] == ("x", "y", "z")
    assert result["mapping"] == {"a": 1, "b": 2}

    # Optional and Union
    assert result["optional_text"] == "opt"
    assert result["either"] == 123

    # TypedDict, dataclass, Pydantic
    assert result["td"] == {"count": 1, "label": "one"}
    assert result["dc"] == {"value": 2.5, "flag": True}
    assert result["pm"] == {"name": "test", "id": 42}

    # date/time/any
    assert result["timestamp"] == datetime.datetime(
        2025, 4, 17, 12, 0, 0, 0, timezone.utc
    )
    assert result["the_date"] == date(2025, 4, 17)
    assert result["the_time"] == time(12, 0, 0)
    assert result["anything"] == {"complex": ["structure", 123]}


def test_tool_result_content_preserves_documents():
    """tool_result_content preserves document content blocks."""
    document = ContentDocument(document="/path/to/report.pdf")

    assert tool_result_content([document]) == [document]


async def test_document_tool_result_preserved_as_structured_content():
    """execute_tools preserves a document tool result as structured content."""
    tool_def = ToolDef(document_tool())
    call = make_call("document_tool", {})

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].content == [ContentDocument(document="/path/to/report.pdf")]


async def test_mixed_tool_result_preserved_as_structured_content():
    """execute_tools preserves mixed text and document tool results."""
    tool_def = ToolDef(mixed_content_tool())
    call = make_call("mixed_content_tool", {})

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].content == [
        ContentText(text="Attached report"),
        ContentDocument(document="/path/to/report.pdf"),
    ]


@tool
def search_with_default_none():
    async def search(query: str, filters: dict = None) -> str:  # type: ignore[assignment]
        """Search with optional filters.

        Args:
            query: the query string.
            filters: optional filters dict.
        """
        return f"q={query} filters={filters}"

    return search


async def test_default_none_param_not_required():
    """Param with default=None (non-Optional annotation) is not required."""
    tool_def = ToolDef(search_with_default_none())

    # schema generation already treats `filters` as optional
    assert "filters" not in tool_def.parameters.required

    # model omits `filters` -- should succeed, not raise ToolParsingError
    call = make_call("search_with_default_none", {"query": "cats"})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None, f"unexpected tool error: {messages[-1].error}"
    assert messages[-1].content == "q=cats filters=None"


@tool
def perm_error_tool():
    async def execute() -> str:
        """Raise PermissionError with a custom message (no errno/filename)."""
        raise PermissionError("Sandbox policy: write to /etc denied")

    return execute


@tool
def fnf_error_tool():
    async def execute() -> str:
        """Raise FileNotFoundError with a custom message (no filename)."""
        raise FileNotFoundError("Workspace file 'config.yaml' missing")

    return execute


@tool
def sandbox_timeout_tool():
    async def execute() -> str:
        """Raise SandboxTimeoutError with partial output."""
        raise SandboxTimeoutError(
            "exec timed out", truncated_output="partial output before timeout"
        )

    return execute


async def test_oserror_custom_message_preserved():
    """OSError subclasses raised with a bare message surface that message.

    PermissionError/FileNotFoundError constructed with a single string arg
    have .strerror/.filename == None; the model must still see the message,
    not the literal 'None'.
    """
    # PermissionError
    tool_def = ToolDef(perm_error_tool())
    call = make_call("perm_error_tool", {})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is not None
    assert messages[-1].error.type == "permission"
    assert "None" not in messages[-1].error.message
    assert "Sandbox policy: write to /etc denied" in messages[-1].error.message

    # FileNotFoundError
    tool_def = ToolDef(fnf_error_tool())
    call = make_call("fnf_error_tool", {})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is not None
    assert messages[-1].error.type == "file_not_found"
    assert "None" not in messages[-1].error.message
    assert "Workspace file 'config.yaml' missing" in messages[-1].error.message


async def test_sandbox_timeout_partial_output_returned_as_tool_result():
    """SandboxTimeoutError partial output is returned with a timeout tool error."""
    tool_def = ToolDef(sandbox_timeout_tool())
    call = make_call("sandbox_timeout_tool", {})

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].content == "partial output before timeout"
    assert messages[-1].error is not None
    assert messages[-1].error.type == "timeout"
    assert messages[-1].error.message == "Command timed out before completing."


@tool
def mixed_content_and_str_tool():
    async def execute() -> list:
        """Return a list mixing Content and a raw str."""
        return [ContentText(text="header"), "RAW STRING"]

    return execute


async def test_mixed_content_and_str_list_does_not_crash():
    """Mixed Content/non-Content list result falls back to str coercion.

    Only homogeneous Content lists are passed through as structured content;
    a heterogeneous list must not crash the sample with a ValidationError.
    """
    tool_def = ToolDef(mixed_content_and_str_tool())
    call = make_call("mixed_content_and_str_tool", {})

    # previously this raised an unhandled pydantic ValidationError when
    # building the ToolEvent (outside the tool-error try/except)
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None
    # mixed list falls through to str() coercion rather than being treated
    # as list[Content]
    assert isinstance(messages[-1].content, str)
    assert "RAW STRING" in messages[-1].content


async def test_tool_event_message_id_for_multiple_calls():
    """Each ToolEvent.message_id references its own ChatMessageTool."""
    transcript = Transcript()
    init_transcript(transcript)

    tool_def = ToolDef(incr())
    calls = [
        ToolCall(id="call-1", function="incr", arguments={"x": 1}, parse_error=None),
        ToolCall(id="call-2", function="incr", arguments={"x": 2}, parse_error=None),
        ToolCall(id="call-3", function="incr", arguments={"x": 3}, parse_error=None),
    ]

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=calls)], [tool_def]
    )

    tool_messages = [m for m in messages if isinstance(m, ChatMessageTool)]
    tool_events = [e for e in transcript.events if isinstance(e, ToolEvent)]
    assert len(tool_messages) == 3
    assert len(tool_events) == 3

    for tool_message, tool_event in zip(tool_messages, tool_events):
        assert tool_event.id == tool_message.tool_call_id
        assert tool_event.message_id == tool_message.id

    # ensure each event has a distinct message_id (regression: previously
    # every event pointed at the first ChatMessageTool)
    assert len({e.message_id for e in tool_events}) == 3
