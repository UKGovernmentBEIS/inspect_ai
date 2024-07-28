import inspect
from dataclasses import is_dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from docstring_parser import Docstring, parse
from pydantic import BaseModel, Field


class ToolParam(BaseModel):
    type: Literal[
        "string", "integer", "number", "boolean", "array", "object", "null"
    ] = Field(default="null")
    description: str | None = Field(default=None)
    default: Any = Field(default=None)
    items: Optional["ToolParam"] = Field(default=None)
    properties: dict[str, "ToolParam"] | None = Field(default=None)
    additionalProperties: Optional["ToolParam"] = Field(default=None)
    anyOf: list["ToolParam"] | None = Field(default=None)
    required: list[str] | None = Field(default=None)


class ToolParams(BaseModel):
    type: Literal["object"] = Field(default="object")
    properties: dict[str, ToolParam] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: ToolParams = Field(default_factory=ToolParams)


def parse_tool_info(func: Callable[..., Any]) -> ToolInfo:
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)
    parsed_docstring: Docstring | None = parse(docstring) if docstring else None

    info = ToolInfo(name=func.__name__, description="")

    for param_name, param in signature.parameters.items():
        tool_param = ToolParam()

        # Get type information from type annotations
        if param_name in type_hints:
            tool_param = parse_type(type_hints[param_name])

        # Get default value
        if param.default is param.empty:
            info.parameters.required.append(param_name)
        else:
            tool_param.default = param.default

        # Parse docstring for additional info
        docstring_info = parse_docstring(docstring, param_name)

        # Add description from docstring
        if "description" in docstring_info:
            tool_param.description = docstring_info["description"]

        # Only add docstring type if no type annotation is present
        if tool_param.type is None and "docstring_type" in docstring_info:
            tool_param.type = docstring_info["docstring_type"]

        # append the tool param
        info.parameters.properties[param_name] = tool_param

    # Add function description if available
    if parsed_docstring and parsed_docstring.short_description:
        info.description = parsed_docstring.short_description

    return info


def parse_type(type_hint: Type[Any]) -> ToolParam:
    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin is None:
        if type_hint == int:
            return ToolParam(type="integer")
        elif type_hint == float:
            return ToolParam(type="number")
        elif type_hint == str:
            return ToolParam(type="string")
        elif type_hint == bool:
            return ToolParam(type="boolean")
        elif is_dataclass(type_hint) or (
            isinstance(type_hint, type) and issubclass(type_hint, BaseModel)
        ):
            return parse_dataclass_or_pydantic(type_hint)
        elif type_hint == Any:
            return ToolParam()
    elif origin is list or origin is List:
        return ToolParam(
            type="array", items=parse_type(args[0]) if args else ToolParam()
        )
    elif origin is dict or origin is Dict:
        return ToolParam(
            type="object",
            additionalProperties=parse_type(args[1]) if len(args) > 1 else ToolParam(),
        )
    elif origin is Union:
        return ToolParam(anyOf=[parse_type(arg) for arg in args])
    elif origin is Optional:
        return ToolParam(anyOf=[parse_type(args[0]), ToolParam()])

    return ToolParam()  # Default case if we can't determine the type


def parse_dataclass_or_pydantic(cls: Type[Any]) -> ToolParam:
    properties: Dict[str, ToolParam] = {}
    required: List[str] = []

    if is_dataclass(cls):
        fields = cls.__dataclass_fields__  # type: ignore
        for name, field in fields.items():
            properties[name] = parse_type(field.type)
            if field.default == field.default_factory:
                required.append(name)
    elif isinstance(cls, type) and issubclass(cls, BaseModel):
        schema = cls.model_json_schema()
        for name, prop in schema.get("properties", {}).items():
            properties[name] = ToolParam(**prop)
        required = schema.get("required", [])

    return ToolParam(
        type="object", properties=properties, required=required if required else None
    )


def parse_docstring(docstring: str | None, param_name: str) -> Dict[str, str]:
    if not docstring:
        return {}

    parsed_docstring: Docstring = parse(docstring)

    for param in parsed_docstring.params:
        if param.arg_name == param_name:
            schema: Dict[str, str] = {"description": param.description or ""}

            if param.type_name:
                schema["docstring_type"] = param.type_name

            return schema

    return {}
