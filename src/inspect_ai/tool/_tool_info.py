import inspect
from dataclasses import is_dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from docstring_parser import Docstring, parse
from pydantic import BaseModel, Field

from ._tool_description import tool_description
from ._tool_params import JSONType, ToolParam, ToolParams


class ToolInfo(BaseModel):
    """Specification of a tool (JSON Schema compatible)

    If you are implementing a ModelAPI, most LLM libraries can
    be passed this object (dumped to a dict) directly as a function
    specification. For example, in the OpenAI provider:

    ```python
    ChatCompletionToolParam(
        type="function",
        function=tool.model_dump(exclude_none=True),
    )
    ```

    In some cases the field names don't match up exactly. In that case
    call `model_dump()` on the `parameters` field. For example, in the
    Anthropic provider:

    ```python
    ToolParam(
        name=tool.name,
        description=tool.description,
        input_schema=tool.parameters.model_dump(exclude_none=True),
    )
    ```
    """

    name: str
    """Name of tool."""
    description: str
    """Short description of tool."""
    parameters: ToolParams = Field(default_factory=ToolParams)
    """JSON Schema of tool parameters object."""


def parse_tool_info(func: Callable[..., Any]) -> ToolInfo:
    # tool may already have registry attributes w/ tool info
    description = tool_description(func)
    if (
        description.name
        and description.description
        and description.parameters is not None
    ):
        return ToolInfo(
            name=description.name,
            description=description.description,
            parameters=description.parameters,
        )

    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)
    parsed_docstring: Docstring | None = parse(docstring) if docstring else None

    info = ToolInfo(name=func.__name__, description="")

    for param_name, param in signature.parameters.items():
        tool_param = ToolParam()

        # Parse docstring
        docstring_info = parse_docstring(docstring, param_name)

        # Get type information from type annotations
        if param_name in type_hints:
            tool_param = parse_type(type_hints[param_name])
        # as a fallback try to parse it from the docstring
        # (this is minimally necessary for backwards compatiblity
        #  with tools gen1 type parsing, which only used docstrings)
        elif "docstring_type" in docstring_info:
            json_type = python_type_to_json_type(docstring_info["docstring_type"])
            if json_type and (json_type in get_args(JSONType)):
                tool_param = ToolParam(type=json_type)

        # Get default value
        if param.default is param.empty:
            info.parameters.required.append(param_name)
        else:
            tool_param.default = param.default

        # Add description from docstring
        if "description" in docstring_info:
            tool_param.description = docstring_info["description"]

        # append the tool param
        info.parameters.properties[param_name] = tool_param

    # Add function description if available
    if parsed_docstring:
        if parsed_docstring.description:
            info.description = parsed_docstring.description.strip()
        elif parsed_docstring.long_description:
            info.description = parsed_docstring.long_description.strip()
        elif parsed_docstring.short_description:
            info.description = parsed_docstring.short_description.strip()

        # Add examples if available
        if parsed_docstring.examples:
            examples = "\n\n".join(
                [(example.description or "") for example in parsed_docstring.examples]
            )
            info.description = f"{info.description}\n\nExamples\n\n{examples}"

    return info


def parse_type(type_hint: Type[Any]) -> ToolParam:
    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin is None:
        if type_hint is int:
            return ToolParam(type="integer")
        elif type_hint is float:
            return ToolParam(type="number")
        elif type_hint is str:
            return ToolParam(type="string")
        elif type_hint is bool:
            return ToolParam(type="boolean")
        elif (
            is_dataclass(type_hint)
            or is_typeddict(type_hint)
            or (isinstance(type_hint, type) and issubclass(type_hint, BaseModel))
        ):
            return parse_object(type_hint)
        else:
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


def parse_object(cls: Type[Any]) -> ToolParam:
    properties: Dict[str, ToolParam] = {}
    required: List[str] = []

    if is_dataclass(cls):
        fields = cls.__dataclass_fields__  # type: ignore
        for name, field in fields.items():
            properties[name] = parse_type(field.type)  # type: ignore
            if field.default == field.default_factory:
                required.append(name)
    elif isinstance(cls, type) and issubclass(cls, BaseModel):
        schema = cls.model_json_schema()
        for name, prop in schema.get("properties", {}).items():
            properties[name] = ToolParam(**prop)
        required = schema.get("required", [])
    elif is_typeddict(cls):
        annotations = get_type_hints(cls)
        for name, type_hint in annotations.items():
            properties[name] = parse_type(type_hint)
            if name in cls.__required_keys__:
                required.append(name)

    return ToolParam(
        type="object",
        properties=properties,
        required=required if required else None,
        additionalProperties=False,
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


def python_type_to_json_type(python_type: str) -> JSONType | None:
    match python_type:
        case "str":
            return "string"
        case "int":
            return "integer"
        case "float":
            return "number"
        case "bool":
            return "boolean"
        case "list":
            return "array"
        case "dict":
            return "object"
        case "None":
            return "null"
        case _:
            return None
