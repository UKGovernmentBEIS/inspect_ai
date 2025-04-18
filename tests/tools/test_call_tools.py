from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict, Union

import pytest
from pydantic import BaseModel

from inspect_ai.model._call_tools import call_tool
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


@tool
def complex_tool():
    async def complex_tool(
        text: str,
        count: int,
        ratio: float,
        active: bool,
        numbers: List[int],
        strings: Set[str],
        tags: Tuple[str, ...],
        mapping: Dict[str, int],
        optional_text: Optional[str],
        either: Union[int, str],
        td: MyTypedDict,
        dc: MyDataClass,
        pm: MyPydanticModel,
        timestamp: datetime,
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
            "numbers": numbers,
            "strings": strings,
            "tags": tags,
            "mapping": mapping,
            "optional_text": optional_text,
            "either": either,
            "td": td,
            "dc": {"value": dc.value, "flag": dc.flag},
            "pm": pm.dict(),
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
    result, messages, output, agent = await call_tool(
        [tool_def], message="", call=call, conversation=[]
    )
    assert result == 1
    assert messages == []
    assert output is None
    assert agent is None


@pytest.mark.asyncio
async def test_complex_tool_all_params():
    """Exercise every parameter type in one call."""
    args = {
        "text": "hello",
        "count": 10,
        "ratio": 0.75,
        "active": False,
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
    result, messages, output, agent = await call_tool(
        [tool_def], message="", call=call, conversation=[]
    )

    # primitives
    assert result["text"] == "hello"
    assert result["count"] == 10
    assert abs(result["ratio"] - 0.75) < 1e-9
    assert result["active"] is False

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
    assert result["timestamp"] == datetime(2025, 4, 17, 12, 0, 0)
    assert result["the_date"] == date(2025, 4, 17)
    assert result["the_time"] == time(12, 0, 0)
    assert result["anything"] == {"complex": ["structure", 123]}

    # no side‑effects or agent handoff
    assert messages == []
    assert output is None
    assert agent is None
