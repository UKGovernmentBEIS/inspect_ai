from inspect_ai._util.deprecation import relocated_module_attribute

from ._critique import self_critique
from ._multiple_choice import multiple_choice
from ._plan import Plan, plan
from ._prompt import (
    chain_of_thought,
    prompt_template,
    system_message,
)
from ._solver import Generate, Solver, generate, solver
from ._task_state import Choice, Choices, TaskState
from ._tools._execute import bash, python
from ._tools._use_tools import use_tools
from ._tools._web_search import web_search

__all__ = [
    "generate",
    "prompt_template",
    "chain_of_thought",
    "multiple_choice",
    "system_message",
    "self_critique",
    "use_tools",
    "bash",
    "python",
    "web_search",
    "plan",
    "Plan",
    "Solver",
    "solver",
    "Choice",
    "Choices",
    "TaskState",
    "Generate",
]


_TOOL_MODULE_VERSION = "0.3.18"
_REMOVED_IN = "0.4"
relocated_module_attribute(
    "Tool", "inspect_ai.tool.Tool", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolEnvironment",
    "inspect_ai.tool.ToolEnvironment",
    _TOOL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolEnvironments",
    "inspect_ai.tool.ToolEnvironments",
    _TOOL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolEnvironmentSpec",
    "inspect_ai.tool.ToolEnvironmentSpec",
    _TOOL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolError", "inspect_ai.tool.ToolError", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "ToolResult", "inspect_ai.tool.ToolResult", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "tool", "inspect_ai.tool.tool", _TOOL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "tool_environment",
    "inspect_ai.tool.tool_environment",
    _TOOL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "toolenv", "inspect_ai.tool.toolenv", _TOOL_MODULE_VERSION, _REMOVED_IN
)
