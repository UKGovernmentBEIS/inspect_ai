import builtins
import inspect
import json
import keyword
import re
from collections.abc import Iterable, Sequence
from typing import get_type_hints

from inspect_ai.tool._tool import Tool, ToolResult, ToolSource, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_description import ToolDescription, set_tool_description
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.util._json import JSONSchema, json_schema

_RUN_CODE_NAME = "run_code"
_DEFAULT_MAX_TOOL_CALLS = 100
_DEFAULT_MAX_DURATION_SECS = 30.0
_DEFAULT_MAX_MEMORY = 256 * 1024 * 1024
_RESERVED_PYTHON_NAMES = frozenset(dir(builtins)) | {_RUN_CODE_NAME}


@tool
def run_code(
    tools: Sequence[Tool | ToolDef],
    *,
    max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
    max_duration_secs: float = _DEFAULT_MAX_DURATION_SECS,
    max_memory: int = _DEFAULT_MAX_MEMORY,
) -> Tool:
    """Create a sandboxed Python tool that can call other Inspect tools.

    The returned tool executes model-authored Python with Pydantic Monty. Only
    the tools explicitly passed here are callable from the sandbox; host file,
    environment, network, and operating-system access are not exposed.

    Args:
        tools: Inspect tools to expose inside the code sandbox.
        max_tool_calls: Maximum wrapped-tool calls in one code invocation.
        max_duration_secs: Maximum Monty execution time for one invocation.
        max_memory: Maximum Monty heap size in bytes for one invocation.

    Returns:
        A ``run_code`` tool.
    """
    if max_tool_calls < 1:
        raise ValueError("max_tool_calls must be at least 1")
    if max_duration_secs <= 0:
        raise ValueError("max_duration_secs must be greater than 0")
    if max_memory <= 0:
        raise ValueError("max_memory must be greater than 0")

    callable_tools = _callable_tools(tools)
    description = _description(callable_tools, max_tool_calls)
    type_check_stubs = _type_check_stubs(callable_tools)

    async def execute(code: str) -> ToolResult:
        """Run Python code that can call the configured tools.

        Args:
            code: Python code to execute in the Monty sandbox.

        Returns:
            The final expression and any printed output.
        """
        try:
            from ._run_code_monty import execute_monty
        except ImportError as ex:
            if ex.name and ex.name.startswith("pydantic_monty"):
                raise ImportError(
                    "run_code requires the code-mode extra. Install it with "
                    "`pip install inspect-ai[code-mode]`."
                ) from ex
            raise

        return await execute_monty(
            code=code,
            tools=callable_tools,
            max_tool_calls=max_tool_calls,
            max_duration_secs=max_duration_secs,
            max_memory=max_memory,
            type_check_stubs=type_check_stubs,
        )

    tool_info = parse_tool_info(execute)
    set_tool_description(
        execute,
        ToolDescription(
            name=_RUN_CODE_NAME,
            description=description,
            parameters=tool_info.parameters,
        ),
    )
    return execute


def _callable_tools(tools: Sequence[Tool | ToolDef]) -> dict[str, ToolDef]:
    from inspect_ai.agent._handoff import AgentTool

    callable_tools: dict[str, ToolDef] = {}
    original_names: dict[str, str] = {}

    for candidate in tools:
        if isinstance(candidate, ToolSource):
            raise ValueError(
                "run_code requires a fixed sequence of Tool or ToolDef values; "
                "dynamic ToolSource values are not supported"
            )
        tool_def = candidate if isinstance(candidate, ToolDef) else ToolDef(candidate)
        if isinstance(tool_def.tool, AgentTool):
            raise ValueError(
                f"run_code cannot wrap agent handoff tool {tool_def.name!r}; "
                "handoffs must remain top-level tools"
            )

        python_name = _python_name(tool_def.name)
        if python_name in _RESERVED_PYTHON_NAMES:
            raise ValueError(
                f"tool {tool_def.name!r} maps to reserved Python name {python_name!r}"
            )
        if python_name in callable_tools:
            raise ValueError(
                f"tool names {original_names[python_name]!r} and {tool_def.name!r} "
                f"both map to Python identifier {python_name!r}"
            )

        callable_tools[python_name] = tool_def
        original_names[python_name] = tool_def.name

    if not callable_tools:
        raise ValueError("run_code requires at least one wrapped tool")
    return callable_tools


def _python_name(name: str) -> str:
    python_name = re.sub(r"\W", "_", name)
    if not python_name or python_name[0].isdigit():
        python_name = f"_{python_name}"
    if keyword.iskeyword(python_name):
        python_name = f"{python_name}_"
    return python_name


def _description(tools: dict[str, ToolDef], max_tool_calls: int) -> str:
    lines = [
        "Write and run Python code in a sandboxed Pydantic Monty environment.",
        "",
        "The sandbox has no host filesystem, environment, network, or OS access. "
        "Third-party packages are unavailable. Supported standard-library modules "
        "include `asyncio`, `json`, `re`, `math`, and `datetime`.",
        "All wrapped tools are async and accept keyword-only arguments. Await every "
        "call; independent calls marked parallel-safe may be passed to "
        "`asyncio.gather`.",
        "The final expression is returned automatically. Use `print()` only for "
        "supplementary output. Each run_code call starts with fresh interpreter state.",
        "",
        f"At most {max_tool_calls} wrapped-tool calls are allowed in this invocation.",
        "",
        "Available functions:",
    ]
    for python_name, tool_def in tools.items():
        signature = _tool_signature(python_name, tool_def)
        schema = json.dumps(
            tool_def.parameters.model_dump(exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        original = (
            "" if python_name == tool_def.name else f" (Inspect tool `{tool_def.name}`)"
        )
        lines.extend(
            [
                f"- `{signature}`{original}: {tool_def.description}",
                "  Execution: "
                + (
                    "parallel-safe"
                    if tool_def.parallel
                    else "serial (acts as a barrier)"
                ),
                f"  Parameters: `{schema}`",
            ]
        )
    return "\n".join(lines)


def _type_check_stubs(tools: dict[str, ToolDef]) -> str:
    signatures = [
        _tool_signature(name, tool_def, body="raise NotImplementedError()")
        for name, tool_def in tools.items()
    ]
    return "\n\n".join(["from typing import Any, Literal", *signatures])


def _tool_signature(name: str, tool_def: ToolDef, body: str = "...") -> str:
    properties = tool_def.parameters.properties
    if all(
        param.isidentifier() and not keyword.iskeyword(param) for param in properties
    ):
        required = set(tool_def.parameters.required)
        parameters = [
            f"{param}: {_schema_type(schema)}" + ("" if param in required else " = ...")
            for param, schema in properties.items()
        ]
        rendered_parameters = ", ".join(["*", *parameters]) if parameters else ""
    else:
        rendered_parameters = "**kwargs: Any"
    return_type = _schema_type(_return_schema(tool_def))
    return f"async def {name}({rendered_parameters}) -> {return_type}: {body}"


def _return_schema(tool_def: ToolDef) -> JSONSchema:
    target = (
        tool_def.tool
        if inspect.isfunction(tool_def.tool) or inspect.ismethod(tool_def.tool)
        else type(tool_def.tool).__call__
    )
    try:
        annotation = get_type_hints(target).get("return", inspect.Signature.empty)
    except (NameError, TypeError):
        annotation = inspect.Signature.empty
    if annotation is inspect.Signature.empty:
        return JSONSchema()
    return json_schema(annotation)


def _schema_type(schema: JSONSchema) -> str:
    if schema.enum and all(
        item is None or isinstance(item, str | int | float | bool)
        for item in schema.enum
    ):
        values = ", ".join(repr(item) for item in schema.enum)
        return f"Literal[{values}]"
    if schema.anyOf:
        return _union_type(_schema_type(item) for item in schema.anyOf)
    if isinstance(schema.type, list):
        return _union_type(_schema_type(JSONSchema(type=item)) for item in schema.type)
    if schema.type == "string":
        return "str"
    if schema.type == "integer":
        return "int"
    if schema.type == "number":
        return "float"
    if schema.type == "boolean":
        return "bool"
    if schema.type == "array":
        return f"list[{_schema_type(schema.items or JSONSchema())}]"
    if schema.type == "object":
        value_schema = (
            schema.additionalProperties
            if isinstance(schema.additionalProperties, JSONSchema)
            else JSONSchema()
        )
        return f"dict[str, {_schema_type(value_schema)}]"
    if schema.type == "null":
        return "None"
    return "Any"


def _union_type(types: Iterable[str]) -> str:
    unique = list(dict.fromkeys(types))
    return " | ".join(unique) if unique else "Any"
