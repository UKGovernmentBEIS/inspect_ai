from typing import Any, Protocol, Optional, Literal, Set
from pydantic import BaseModel
from rich.panel import Panel
from rich.prompt import  Prompt
import sys
import shlex
import ast
from typing import Optional, List, cast
from functools import wraps
from utils import print_approval_message, print_escalation_message, print_rejection_message, print_termination_message, get_tool_calls_from_state
from inspect_ai.tool import Tool, ToolResult
from inspect_ai.util import input_screen
from inspect_ai.solver._task_state import sample_state
from inspect_ai.solver import TaskState
from inspect_ai.tool import ToolCall


class Approval(BaseModel):
    decision: Literal["approve", "reject", "escalate", "terminate"]
    explanation: str

class Approver(Protocol):
    """
    Protocol for approvers.
    """
    def __call__(self, tool_call: ToolCall, state: Optional[TaskState] = None) -> Approval:
        """
        Approve or reject a tool call.

        Args:
            tool_call (ToolCall): The tool call to be approved.
            state (Optional[TaskState]): The current task state, if available.

        Returns:
            Approval: An Approval object containing the decision and explanation.
        """
        ...

def bash_allowlist_approver(allowed_commands: list[str], allow_sudo: bool = False, command_specific_rules: Optional[dict[str, list[str]]] = None) -> Approver:
    """
    Create an approver that checks if a bash command is in an allowed list.

    Args:
        allowed_commands (List[str]): List of allowed bash commands.
        allow_sudo (bool, optional): Whether to allow sudo commands. Defaults to False.
        command_specific_rules (Optional[Dict[str, List[str]]], optional): Dictionary of command-specific rules. Defaults to None.

    Returns:
        Approver: A function that approves or rejects bash commands based on the allowed list and rules.
    """
    allowed_commands_set = set(allowed_commands)
    command_specific_rules = command_specific_rules or {}
    dangerous_chars = ['&', '|', ';', '>', '<', '`', '$', '(', ')']

    def approve(tool_call: ToolCall, state: Optional[TaskState] = None) -> Approval:
        if tool_call.function != "bash":
            return Approval(decision="escalate", explanation=f"AllowListApprover only handles bash commands, got {tool_call.function}")

        command = tool_call.arguments.get("cmd", "").strip()
        if not command:
            return Approval(decision="reject", explanation="Empty command")

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return Approval(decision="reject", explanation=f"Invalid command syntax: {str(e)}")

        if any(char in command for char in dangerous_chars):
            return Approval(decision="reject", explanation=f"Command contains potentially dangerous characters: {', '.join(char for char in dangerous_chars if char in command)}")

        base_command = tokens[0]
        
        # Handle sudo
        if base_command == "sudo":
            if not allow_sudo:
                return Approval(decision="reject", explanation="sudo is not allowed")
            if len(tokens) < 2:
                return Approval(decision="reject", explanation="Invalid sudo command")
            base_command = tokens[1]
            tokens = tokens[1:]

        if base_command not in allowed_commands_set:
            return Approval(decision="escalate", explanation=f"Command '{base_command}' is not in the allowed list. Allowed commands: {', '.join(allowed_commands_set)}")

        # Check command-specific rules
        if base_command in command_specific_rules:
            allowed_subcommands = command_specific_rules[base_command]
            if len(tokens) > 1 and tokens[1] not in allowed_subcommands:
                return Approval(decision="escalate", explanation=f"{base_command} subcommand '{tokens[1]}' is not allowed. Allowed subcommands: {', '.join(allowed_subcommands)}")

        return Approval(decision="approve", explanation=f"Command '{command}' is approved.")

    return approve

def python_allowlist_approver(
    allowed_modules: List[str],
    allowed_functions: List[str],
    disallowed_builtins: Optional[Set[str]] = None,
    sensitive_modules: Optional[Set[str]] = None,
    allow_system_state_modification: bool = False
    ) -> Approver:
    """
    Create an approver that checks if Python code uses only allowed modules and functions,
    and applies additional safety checks.

    Args:
        allowed_modules (List[str]): List of allowed Python modules.
        allowed_functions (List[str]): List of allowed built-in functions.
        disallowed_builtins (Optional[Set[str]]): Set of disallowed built-in functions.
        sensitive_modules (Optional[Set[str]]): Set of sensitive modules to be blocked.
        allow_system_state_modification (bool): Whether to allow modification of system state.

    Returns:
        Approver: A function that approves or rejects Python code based on the allowed list and rules.
    """
    allowed_modules_set = set(allowed_modules)
    allowed_functions_set = set(allowed_functions)
    disallowed_builtins = disallowed_builtins or {'eval', 'exec', 'compile', '__import__', 'open', 'input'}
    sensitive_modules = sensitive_modules or {'os', 'sys', 'subprocess', 'socket', 'requests'}

    def approve(tool_call: ToolCall, state: Optional[TaskState] = None) -> Approval:
        if tool_call.function != "python":
            return Approval(decision="escalate", explanation=f"PythonAllowListApprover only handles Python code, got {tool_call.function}")

        code = tool_call.arguments.get("code", "").strip()
        if not code:
            return Approval(decision="reject", explanation="Empty code")

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return Approval(decision="reject", explanation=f"Invalid Python syntax: {str(e)}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in allowed_modules_set:
                        return Approval(decision="escalate", explanation=f"Module '{alias.name}' is not in the allowed list. Allowed modules: {', '.join(allowed_modules_set)}")
                    if alias.name in sensitive_modules:
                        return Approval(decision="escalate", explanation=f"Module '{alias.name}' is considered sensitive and not allowed.")
            elif isinstance(node, ast.ImportFrom):
                if node.module not in allowed_modules_set:
                    return Approval(decision="escalate", explanation=f"Module '{node.module}' is not in the allowed list. Allowed modules: {', '.join(allowed_modules_set)}")
                if node.module in sensitive_modules:
                    return Approval(decision="escalate", explanation=f"Module '{node.module}' is considered sensitive and not allowed.")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id not in allowed_functions_set:
                        return Approval(decision="escalate", explanation=f"Function '{node.func.id}' is not in the allowed list. Allowed functions: {', '.join(allowed_functions_set)}")
                    if node.func.id in disallowed_builtins:
                        return Approval(decision="escalate", explanation=f"Built-in function '{node.func.id}' is not allowed for security reasons.")
            
            if not allow_system_state_modification:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr.startswith('__'):
                            return Approval(decision="escalate", explanation="Modification of system state (dunder attributes) is not allowed.")

        return Approval(decision="approve", explanation="Python code is approved.")

    return approve


def human_approver() -> Approver:
    """
    Create an approver that prompts a human user for approval decisions.

    Returns:
        Approver: A function that prompts a human user for approval of a tool call.
    """
    def approve(tool_call: ToolCall, state: Optional[TaskState] = None) -> Approval:
        with input_screen() as console:
            console.print(Panel.fit(
                f"Tool: {tool_call.function}\nArguments: {tool_call.arguments}",
                title="Approval Request",
                subtitle="Current State"
            ))
            
            if state:
                console.print(Panel.fit(
                    str(state),
                    title="Task State"
                ))
            
            decision = Prompt.ask(
                "[bold]Approve (y), Reject (r), Escalate (e), or Terminate (t)?[/bold]",
                choices=["y", "r", "e", "t"],
                default="e"
            )
        
        if decision == 'y':
            return Approval(decision="approve", explanation="Approved by human approver.")
        elif decision == 'r':
            return Approval(decision="reject", explanation="Rejected by human approver.")
        elif decision == 'e':
            return Approval(decision="escalate", explanation="Escalated by human approver.")
        elif decision == 't':
            return Approval(decision="terminate", explanation="Terminated by human approver.")
        return Approval(decision="escalate", explanation="Invalid input from human approver, escalating.")

    return approve

def get_approval(approvers: list[Approver], tool_call: ToolCall, state: Optional[TaskState] = None) -> tuple[bool, str]:
    """
    Get approval for a tool call using the list of approvers.

    Args:
        approvers (List[Approver]): A list of approvers to use in the approval process.
        tool_call (ToolCall): The tool call to be approved.
        state (Optional[TaskState]): The current task state, if available.

    Returns:
        Tuple[bool, str]: A tuple containing a boolean indicating approval status and a message explaining the decision.
    """
    state = state or sample_state()
    for approver in approvers:
        approval = approver(tool_call, state)
        if approval.decision == "approve":
            print_approval_message(tool_call, approval.explanation)
            return True, approval.explanation
        elif approval.decision == "reject":
            print_rejection_message(tool_call, approval.explanation)
        elif approval.decision == "terminate":
            print_termination_message(approval.explanation)
            sys.exit(1)
        elif approval.decision == "escalate":
            print_escalation_message(tool_call, approval.explanation)
    
    final_message = "Rejected: No approver approved the tool call"
    print_rejection_message(tool_call, final_message)
    return False, final_message


def wrap_approvers(tool: Tool, approvers: Optional[List[Approver]] = None) -> Tool:
    """
    Wrap a tool with approvers to add an approval process before execution.

    This function takes a tool and a list of approvers, and returns a new tool that
    includes an approval process. The wrapped tool will check for approval before
    executing the original tool's functionality.

    Args:
        tool (Tool): The original tool to be wrapped.
        approvers (Optional[List[Approver]]): A list of approver functions to be applied.

    Returns:
        Tool: A new tool that includes the approval process.
    """
    @wraps(tool)
    async def wrapped_tool(*args: Any, **kwargs: Any) -> ToolResult:
        
        if hasattr(tool, '__qualname__'):
            qualname = tool.__qualname__
            function_name = qualname.split('.')[0]
        else:
            function_name = getattr(tool, "__name__")

        if approvers:
            state = sample_state()
            if state is None:
                return "Error: No state found."
            
            tool_calls = get_tool_calls_from_state(state)
            if tool_calls is None:
                return "Error: No tool calls found in the current state."

            # Find the corresponding tool call
            tool_call = next((tc for tc in tool_calls if tc.function == function_name), None)
            
            if tool_call:
                approved, reason = get_approval(approvers, tool_call, state)
            else:
                return f"Error: No {function_name} tool call found in the current state."
            
            if not approved:
                return f"Command rejected by the approval system. Reason: {reason}"
        
        with input_screen() as console:
            console.print(Panel.fit(
                f"Executing command: {args[0] if args else kwargs.get('cmd', 'Unknown command')}",
                title=f"{function_name.capitalize()} Execution",
                subtitle="Command Approved"
            ))
        
        return await tool(*args, **kwargs)

    return cast(Tool, wrapped_tool)
