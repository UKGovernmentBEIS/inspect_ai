import inspect

from docstring_parser import Docstring, DocstringParam

from inspect_ai._util.docstring import parse_docstring
from inspect_ai._util.json import python_type_to_json_type
from inspect_ai._util.registry import registry_info
from inspect_ai.model import (
    ToolDef,
    ToolParam,
)
from inspect_ai.model._tool import TOOL_PARAMS, TOOL_PROMPT

from .tool import Tool


def tool_def(tool: Tool) -> ToolDef:
    tool_info = registry_info(tool)
    name = tool_info.name.split("/")[-1]
    docstring = tool_docstring(tool)

    # exclude built in tool params (as we will curry these
    # so the model doesn't need to know about them)
    metadata_params = list(tool_info.metadata.get(TOOL_PARAMS, {}).keys())
    params = [
        tool_param(param)
        for param in docstring.params
        if param.arg_name not in metadata_params
    ]
    return ToolDef(
        name=name,
        description=str(docstring.short_description),
        prompt=tool_info.metadata.get(TOOL_PROMPT, None),
        params=params,
        tool=tool,
    )


def tool_param(param: DocstringParam) -> ToolParam:
    return ToolParam(
        name=param.arg_name,
        type=python_type_to_json_type(param.type_name),
        description=str(param.description),
        optional=param.is_optional is True,
    )


def tool_docstring(tool: Tool) -> Docstring:
    docstring = parse_docstring(inspect.getdoc(tool))
    # We need tool and parameter descriptions to pass to the agent
    assert (
        docstring.short_description is not None
    ), "Tool must have a short description in the docstring"
    for param in list(inspect.signature(tool).parameters.keys()):
        assert param in [
            docstring_param.arg_name for docstring_param in docstring.params
        ], f"Parameter {param} must be documented in the docstring"
    assert [
        docstring_param.description != "" for docstring_param in docstring.params
    ], "All tool parameters must have a description"
    return docstring
