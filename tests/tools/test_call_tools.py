import datetime
from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, TypedDict, Union

import pytest
from pydantic import BaseModel

from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool import tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_def import ToolDef

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


# --- Positive tests -------------------------------------------------------


@pytest.mark.asyncio
async def test_incr_simple_positive():
    """Calling incr(0) should return 1."""
    tool_def = ToolDef(incr())
    call = make_call("incr", {"x": 0})

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [tool_def]
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].content == "1"


@pytest.mark.asyncio
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
    assert result["timestamp"] == datetime.datetime(2025, 4, 17, 12, 0, 0)
    assert result["the_date"] == date(2025, 4, 17)
    assert result["the_time"] == time(12, 0, 0)
    assert result["anything"] == {"complex": ["structure", 123]}
