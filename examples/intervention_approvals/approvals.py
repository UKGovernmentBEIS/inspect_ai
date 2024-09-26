from typing import Protocol, Optional, Literal
from pydantic import BaseModel
from rich.panel import Panel
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.prompt import Confirm, Prompt
from inspect_ai.util import input_screen
from inspect_ai.solver._task_state import sample_state
from inspect_ai.solver import TaskState
from inspect_ai.model import ModelOutput
from inspect_ai.tool import ToolCall
import sys
import shlex

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

def allow_list_approver(allowed_commands: list[str], allow_sudo: bool = False, command_specific_rules: Optional[dict[str, list[str]]] = None) -> Approver:
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

def print_approval_message(tool_call: ToolCall, reason: str):
    """
    Print an approval message for a tool call.

    Args:
        tool_call (ToolCall): The approved tool call.
        reason (str): The reason for approval.
    """
    with input_screen() as console:
        console.print(Panel.fit(
            f"Tool call approved:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
            title="Tool Execution",
            subtitle="Approved"
        ))

def print_rejection_message(tool_call: ToolCall, reason: str):
    """
    Print a rejection message for a tool call.

    Args:
        tool_call (ToolCall): The rejected tool call.
        reason (str): The reason for rejection.
    """
    with input_screen() as console:
        console.print(Panel.fit(
            f"Tool call rejected:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
            title="Tool Execution",
            subtitle="Rejected"
        ))

def print_escalation_message(tool_call: ToolCall, reason: str):
    """
    Print an escalation message for a tool call.

    Args:
        tool_call (ToolCall): The escalated tool call.
        reason (str): The reason for escalation.
    """
    with input_screen() as console:
        console.print(Panel.fit(
            f"Tool call escalated:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
            title="Tool Execution",
            subtitle="Escalated"
        ))

def print_termination_message(reason: str):
    """
    Print a termination message.

    Args:
        reason (str): The reason for termination.
    """
    with input_screen() as console:
        console.print(Panel.fit(
            f"Execution terminated.\nReason: {reason}",
            title="Execution Terminated",
            subtitle="System Shutdown"
        ))
            
def print_tool_response_and_get_authorization(output: ModelOutput) -> bool:
    """
    Print the model's response and tool calls, and ask for user authorization.

    Args:
        output (ModelOutput): The model's output containing the response and tool calls.

    Returns:
        bool: True if the user authorizes the execution, False otherwise.
    """
    renderables: list[RenderableType] = []
    if output.message.content != "":
        renderables.append(
            Panel.fit(
                Markdown(str(output.message.content)), title="Textual Response"
            )
        )

    renderables.append(
        Panel.fit(
            Group(
                *format_human_readable_tool_calls(output.message.tool_calls or []),
                fit=True,
            ),
            title="Tool Calls",
        )
    )
    with input_screen() as console:
        console.print(Panel.fit(Group(*renderables, fit=True), title="Model Response"))

        return Confirm.ask(
            "Do you FULLY understand these tool calls and approve their execution?"
        )

def format_human_readable_tool_calls(tool_calls: list[ToolCall]) -> list[RenderableType]:
    """
    Format tool calls into human-readable renderable objects.

    Args:
        tool_calls (list[ToolCall]): List of tool calls to format.

    Returns:
        list[RenderableType]: A list of renderable objects representing the formatted tool calls.
    """
    output_renderables: list[RenderableType] = []
    for i, tool_call in enumerate(tool_calls):
        panel_contents = []
        for i, (argument, value) in enumerate(tool_call.arguments.items()):
            argument_contents = []
            match (tool_call.function, argument):
                case ("python", "code"):
                    argument_contents.append(
                        Syntax(
                            value,
                            "python",
                            theme="monokai",
                            line_numbers=True,
                        )
                    )
                case ("bash", "cmd"):
                    argument_contents.append(Syntax(value, "bash", theme="monokai"))
                case _:
                    argument_contents.append(value)
            panel_contents.append(
                Panel.fit(
                    Group(*argument_contents, fit=True),
                    title=f"Argument #{i}: [bold]{argument}[/bold]",
                )
            )
        if tool_call.parse_error is not None:
            output_renderables.append(f"Parse error: {tool_call.parse_error}")
        output_renderables.append(
            Panel.fit(
                Group(*panel_contents, fit=True),
                title=f"Tool Call #{i}: [bold]{tool_call.function}[/bold]",
            )
        )
    return output_renderables