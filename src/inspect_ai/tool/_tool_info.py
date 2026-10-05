import inspect
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    get_args,
    get_type_hints,
)

from inspect_ai.util._json import JSONType, json_schema

from ._tool_params import ToolParam

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._tool_info import INTERNAL_TOOL_TYPE as INTERNAL_TOOL_TYPE
from inspect_ai.core._tool_info import ToolInfo as ToolInfo
from inspect_ai.core._tool_info import internal_tool_type as internal_tool_type
from inspect_ai.core._tool_params import ToolParams as ToolParams

# End of backward-compatible re-exports.

if TYPE_CHECKING:
    from docstring_parser import Docstring

# Cache for parse_tool_info results, keyed on function id.
# We store (func, ToolInfo) tuples so the strong reference to func prevents
# id reuse while the entry exists, and we can validate identity on lookup.
_tool_info_cache: dict[int, tuple[Any, "ToolInfo"]] = {}


def parse_tool_info(func: Callable[..., Any]) -> ToolInfo:
    return _parse_tool_info_shared(func).model_copy(deep=True)


def _described_tool_info(func: Callable[..., Any]) -> ToolInfo | None:
    # tool may already have registry attributes w/ tool info — these can be
    # updated at any time via set_tool_description / tool_with, so always
    # check them fresh (no caching for this path).
    from ._tool_description import tool_description

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
    return None


def _parse_tool_info_shared(func: Callable[..., Any]) -> ToolInfo:
    described = _described_tool_info(func)
    if described is not None:
        return described

    # check cache for the expensive reflection/docstring work
    func_id = id(func)
    cached = _tool_info_cache.get(func_id)
    if cached is not None and cached[0] is func:
        return cached[1]

    # get_type_hints requires a function, method, module, or class
    # For callable instances (objects with __call__),
    # resolve type hints from the __call__ method instead.
    if inspect.isfunction(func) or inspect.ismethod(func):
        type_hints = get_type_hints(func)
        func_name = func.__name__
    else:
        type_hints = get_type_hints(type(func).__call__)
        func_name = type(func).__name__

    from docstring_parser import parse

    signature = inspect.signature(func)
    docstring = inspect.getdoc(func)
    parsed_docstring: Docstring | None = parse(docstring) if docstring else None

    # build a lookup of docstring param info (parse once, not per-parameter)
    docstring_params: dict[str, Dict[str, str]] = {}
    if parsed_docstring:
        for ds_param in parsed_docstring.params:
            schema: Dict[str, str] = {"description": ds_param.description or ""}
            if ds_param.type_name:
                schema["docstring_type"] = ds_param.type_name
            docstring_params[ds_param.arg_name] = schema

    info = ToolInfo(name=func_name, description="")

    for param_name, param in signature.parameters.items():
        tool_param = ToolParam()

        # Look up docstring info from pre-built dict
        docstring_info = docstring_params.get(param_name, {})

        # Get type information from type annotations
        if param_name in type_hints:
            tool_param = json_schema(type_hints[param_name])
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

    _tool_info_cache[func_id] = (func, info)
    return info


def parse_docstring(docstring: str | None, param_name: str) -> Dict[str, str]:
    if not docstring:
        return {}

    from docstring_parser import parse

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
