from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict, Union

from pydantic import BaseModel, Field

from inspect_ai.tool._tool_info import (
    parse_docstring,
    parse_object,
    parse_tool_info,
    parse_type,
)
from inspect_ai.tool._tool_params import ToolParam


# Test helper functions
def test_parse_type():
    assert parse_type(int) == ToolParam(type="integer")
    assert parse_type(float) == ToolParam(type="number")
    assert parse_type(str) == ToolParam(type="string")
    assert parse_type(bool) == ToolParam(type="boolean")
    assert parse_type(Any) == ToolParam()
    assert parse_type(List[int]) == ToolParam(
        type="array", items=ToolParam(type="integer")
    )
    assert parse_type(Dict[str, int]) == ToolParam(
        type="object", additionalProperties=ToolParam(type="integer")
    )
    assert parse_type(Optional[str]) == ToolParam(
        anyOf=[ToolParam(type="string"), ToolParam()]
    )
    assert parse_type(Union[int, str]) == ToolParam(
        anyOf=[ToolParam(type="integer"), ToolParam(type="string")]
    )


def test_parse_object() -> None:
    @dataclass
    class TestDataclass:
        field1: int
        field2: str = "default"

    class TestPydantic(BaseModel):
        field1: int
        field2: str = Field(default="default")

    dataclass_result = parse_object(TestDataclass)
    assert dataclass_result.type == "object"
    assert dataclass_result.properties
    assert "field1" in dataclass_result.properties
    assert "field2" in dataclass_result.properties
    assert dataclass_result.required == ["field1"]

    pydantic_result = parse_object(TestPydantic)
    assert pydantic_result.type == "object"
    assert pydantic_result.properties
    assert "field1" in pydantic_result.properties
    assert "field2" in pydantic_result.properties
    assert pydantic_result.required == ["field1"]


def test_parse_docstring():
    docstring = """
    This is a test function.

    Args:
        param1 (int): An integer parameter
        param2 (str): A string parameter

    Returns:
        bool: A boolean result
    """

    result = parse_docstring(docstring, "param1")
    assert result == {"description": "An integer parameter", "docstring_type": "int"}

    result = parse_docstring(docstring, "param3")
    assert result == {}


# Main test cases
def test_simple_function():
    def simple_func(a: int, b: str = "default") -> bool:
        """
        A simple function.

        Args:
            a (int): An integer parameter
            b (str): A string parameter

        Returns:
            bool: A boolean result
        """
        return True

    info = parse_tool_info(simple_func)
    assert info.name == "simple_func"
    assert info.description == "A simple function."
    assert len(info.parameters.properties) == 2
    assert info.parameters.properties["a"].type == "integer"
    assert info.parameters.properties["b"].type == "string"
    assert info.parameters.properties["b"].default == "default"
    assert info.parameters.required == ["a"]


def test_complex_types():
    def complex_func(
        a: List[int], b: Dict[str, Any], c: Optional[Union[int, str]] = None
    ):
        """A function with complex types."""
        pass

    info = parse_tool_info(complex_func)
    assert info.parameters.properties["a"].type == "array"
    assert info.parameters.properties["a"].items.type == "integer"
    assert info.parameters.properties["b"].type == "object"
    assert info.parameters.properties["c"].anyOf is not None
    assert len(info.parameters.properties["c"].anyOf) == 3  # int, str, null


def test_dataclass_parameter() -> None:
    @dataclass
    class TestDataclass:
        field1: int
        field2: str = "default"

    def dataclass_func(data: TestDataclass):
        """A function with a dataclass parameter."""
        pass

    info = parse_tool_info(dataclass_func)
    assert info.parameters.properties["data"].type == "object"
    assert info.parameters.properties["data"].properties
    assert "field1" in info.parameters.properties["data"].properties
    assert "field2" in info.parameters.properties["data"].properties


def test_pydantic_parameter() -> None:
    class TestPydantic(BaseModel):
        field1: int
        field2: str = Field(default="default")

    def pydantic_func(data: TestPydantic):
        """A function with a Pydantic parameter."""
        pass

    info = parse_tool_info(pydantic_func)
    assert info.parameters.properties["data"].type == "object"
    assert info.parameters.properties["data"].properties
    assert "field1" in info.parameters.properties["data"].properties
    assert "field2" in info.parameters.properties["data"].properties


def test_nested_types():
    def nested_func(a: List[Dict[str, Union[int, str]]]):
        """A function with nested types."""
        pass

    info = parse_tool_info(nested_func)
    assert info.parameters.properties["a"].type == "array"
    assert info.parameters.properties["a"].items.type == "object"
    assert info.parameters.properties["a"].items.additionalProperties.anyOf is not None


def test_no_type_hints():
    def no_hints(a, b="default"):
        """
        A function without type hints.

        Args:
            a: First parameter
            b: Second parameter
        """
        pass

    info = parse_tool_info(no_hints)
    assert "a" in info.parameters.properties
    assert "b" in info.parameters.properties
    assert info.parameters.properties["b"].default == "default"


def test_no_docstring():
    def no_docstring(a: int, b: str):
        pass

    info = parse_tool_info(no_docstring)
    assert info.description == ""
    assert "a" in info.parameters.properties
    assert "b" in info.parameters.properties


def test_custom_objects():
    class CustomObject:
        pass

    def custom_func(obj: CustomObject):
        """A function with a custom object parameter."""
        pass

    info = parse_tool_info(custom_func)
    assert "obj" in info.parameters.properties


def test_function_with_args_kwargs():
    def func_with_args_kwargs(*args: int, **kwargs: str):
        """A function with *args and **kwargs."""
        pass

    info = parse_tool_info(func_with_args_kwargs)
    assert "args" in info.parameters.properties
    assert "kwargs" in info.parameters.properties


def test_list_of_dicts():
    def func_with_list_of_dicts(data: List[Dict[str, int]]):
        """A function with a list of dictionaries parameter."""
        pass

    info = parse_tool_info(func_with_list_of_dicts)
    assert info.parameters.properties["data"].type == "array"
    assert info.parameters.properties["data"].items.type == "object"
    assert (
        info.parameters.properties["data"].items.additionalProperties.type == "integer"
    )


def test_list_of_dataclasses() -> None:
    @dataclass
    class Item:
        name: str
        value: int

    def func_with_list_of_dataclasses(items: List[Item]):
        """A function with a list of dataclasses parameter."""
        pass

    info = parse_tool_info(func_with_list_of_dataclasses)
    assert info.parameters.properties["items"].type == "array"
    assert info.parameters.properties["items"].items
    assert info.parameters.properties["items"].items.type == "object"
    assert info.parameters.properties["items"].items.properties
    assert "name" in info.parameters.properties["items"].items.properties
    assert "value" in info.parameters.properties["items"].items.properties
    assert info.parameters.properties["items"].items.properties["name"].type == "string"
    assert (
        info.parameters.properties["items"].items.properties["value"].type == "integer"
    )


def test_list_of_pydantic_models() -> None:
    class Product(BaseModel):
        id: int
        name: str
        price: float

    def func_with_list_of_pydantic_models(products: List[Product]):
        """A function with a list of Pydantic models parameter."""
        pass

    info = parse_tool_info(func_with_list_of_pydantic_models)
    assert info.parameters.properties["products"].type == "array"
    assert info.parameters.properties["products"].items
    assert info.parameters.properties["products"].items.type == "object"
    assert info.parameters.properties["products"].items.properties
    assert "id" in info.parameters.properties["products"].items.properties
    assert "name" in info.parameters.properties["products"].items.properties
    assert "price" in info.parameters.properties["products"].items.properties
    assert (
        info.parameters.properties["products"].items.properties["id"].type == "integer"
    )
    assert (
        info.parameters.properties["products"].items.properties["name"].type == "string"
    )
    assert (
        info.parameters.properties["products"].items.properties["price"].type
        == "number"
    )


def test_nested_list_of_dicts():
    def func_with_nested_list_of_dicts(data: List[List[Dict[str, Union[int, str]]]]):
        """A function with a nested list of dictionaries parameter."""
        pass

    info = parse_tool_info(func_with_nested_list_of_dicts)
    assert info.parameters.properties["data"].type == "array"
    assert info.parameters.properties["data"].items.type == "array"
    assert info.parameters.properties["data"].items.items.type == "object"
    assert (
        info.parameters.properties["data"].items.items.additionalProperties.anyOf
        is not None
    )
    assert (
        len(info.parameters.properties["data"].items.items.additionalProperties.anyOf)
        == 2
    )


def test_dict_with_list_of_pydantic_models() -> None:
    class User(BaseModel):
        id: int
        name: str

    def func_with_dict_list_pydantic(data: Dict[str, List[User]]):
        """A function with a dictionary containing lists of Pydantic models."""
        pass

    info = parse_tool_info(func_with_dict_list_pydantic)
    assert info.parameters.properties["data"].type == "object"
    assert isinstance(
        info.parameters.properties["data"].additionalProperties, ToolParam
    )

    assert info.parameters.properties["data"].additionalProperties.type == "array"
    assert info.parameters.properties["data"].additionalProperties.items
    assert (
        info.parameters.properties["data"].additionalProperties.items.type == "object"
    )
    assert info.parameters.properties["data"].additionalProperties.items.properties
    assert (
        "id" in info.parameters.properties["data"].additionalProperties.items.properties
    )
    assert (
        "name"
        in info.parameters.properties["data"].additionalProperties.items.properties
    )


def test_simple_typeddict() -> None:
    class SimpleDict(TypedDict):
        name: str
        age: int

    def example_function(data: SimpleDict) -> None:
        pass

    tool_info = parse_tool_info(example_function)

    assert tool_info.name == "example_function"
    assert tool_info.parameters.type == "object"
    assert len(tool_info.parameters.properties) == 1

    data_param = tool_info.parameters.properties["data"]
    assert data_param.type == "object"
    assert data_param.properties
    assert len(data_param.properties) == 2
    assert data_param.properties["name"].type == "string"
    assert data_param.properties["age"].type == "integer"
    assert data_param.required
    assert set(data_param.required) == {"name", "age"}


def test_nested_typeddict() -> None:
    class Address(TypedDict):
        street: str
        city: str

    class Person(TypedDict):
        name: str
        address: Address

    def example_function(person: Person) -> None:
        pass

    tool_info = parse_tool_info(example_function)

    person_param = tool_info.parameters.properties["person"]
    assert person_param.type == "object"
    assert person_param.properties
    assert len(person_param.properties) == 2

    address_prop = person_param.properties["address"]
    assert address_prop.type == "object"
    assert address_prop.properties
    assert len(address_prop.properties) == 2
    assert address_prop.properties["street"].type == "string"
    assert address_prop.properties["city"].type == "string"


def test_optional_fields() -> None:
    class OptionalDict(TypedDict, total=False):
        name: str
        age: Optional[int]

    def example_function(data: OptionalDict) -> None:
        pass

    tool_info = parse_tool_info(example_function)

    data_param = tool_info.parameters.properties["data"]
    assert data_param.type == "object"
    assert data_param.properties
    assert len(data_param.properties) == 2
    assert not data_param.required  # No required fields

    age_prop = data_param.properties["age"]
    assert age_prop.anyOf
    assert len(age_prop.anyOf) == 2
    assert any(prop.type == "integer" for prop in age_prop.anyOf)
    assert any(prop.type == "null" for prop in age_prop.anyOf)
