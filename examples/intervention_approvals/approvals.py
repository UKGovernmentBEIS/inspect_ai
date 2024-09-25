from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from rich.panel import Panel
from rich.console import Console, Group, RenderableType
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

class ApprovalDecision(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    TERMINATE = "terminate"

class Approver(ABC):
    @abstractmethod
    def approve(self, tool_call: ToolCall, state: Optional[TaskState] = None) -> Tuple[ApprovalDecision, str]:
        pass

class AllowListApprover(Approver):
    def __init__(self, allowed_commands: List[str], allow_sudo: bool = False, command_specific_rules: Optional[Dict[str, List[str]]] = None):
        self.allowed_commands = set(allowed_commands)
        self.allow_sudo = allow_sudo
        self.command_specific_rules = command_specific_rules or {}
        self.dangerous_chars = ['&', '|', ';', '>', '<', '`', '$', '(', ')']

    def approve(self, tool_call: ToolCall, state: Optional[TaskState] = None) -> Tuple[ApprovalDecision, str]:
        if tool_call.function != "bash":
            return ApprovalDecision.ESCALATE, f"AllowListApprover only handles bash commands, got {tool_call.function}"

        command = tool_call.arguments.get("cmd", "").strip()
        if not command:
            return ApprovalDecision.REJECT, "Empty command"

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return ApprovalDecision.REJECT, f"Invalid command syntax: {str(e)}"

        if any(char in command for char in self.dangerous_chars):
            return ApprovalDecision.REJECT, f"Command contains potentially dangerous characters: {', '.join(char for char in self.dangerous_chars if char in command)}"

        base_command = tokens[0]
        
        # Handle sudo
        if base_command == "sudo":
            if not self.allow_sudo:
                return ApprovalDecision.REJECT, "sudo is not allowed"
            if len(tokens) < 2:
                return ApprovalDecision.REJECT, "Invalid sudo command"
            base_command = tokens[1]
            tokens = tokens[1:]

        if base_command not in self.allowed_commands:
            return ApprovalDecision.ESCALATE, f"Command '{base_command}' is not in the allowed list. Allowed commands: {', '.join(self.allowed_commands)}"

        # Check command-specific rules
        if base_command in self.command_specific_rules:
            allowed_subcommands = self.command_specific_rules[base_command]
            if len(tokens) > 1 and tokens[1] not in allowed_subcommands:
                return ApprovalDecision.ESCALATE, f"{base_command} subcommand '{tokens[1]}' is not allowed. Allowed subcommands: {', '.join(allowed_subcommands)}"

        return ApprovalDecision.APPROVE, f"Command '{command}' is approved."

class HumanApprover(Approver):
    def approve(self, tool_call: ToolCall, state: Optional[TaskState] = None) -> Tuple[ApprovalDecision, str]:
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
            return ApprovalDecision.APPROVE, "Approved by human approver."
        elif decision == 'r':
            return ApprovalDecision.REJECT, "Rejected by human approver."
        elif decision == 'e':
            return ApprovalDecision.ESCALATE, "Escalated by human approver."
        elif decision == 't':
            return ApprovalDecision.TERMINATE, "Terminated by human approver."
        return ApprovalDecision.ESCALATE, "Invalid input from human approver, escalating."

class ApprovalManager:
    def __init__(self, approvers: List[Approver]):
        self.approvers = approvers

    def get_approval(self, tool_call: ToolCall) -> Tuple[bool, str]:
        state = sample_state()
        for approver in self.approvers:
            decision, message = approver.approve(tool_call, state)
            if decision == ApprovalDecision.APPROVE:
                self.print_approval_message(tool_call, message)
                return True, message
            elif decision == ApprovalDecision.REJECT:
                self.print_rejection_message(tool_call, message)
                # Continue to the next approver instead of returning
            elif decision == ApprovalDecision.TERMINATE:
                self.print_termination_message(message)
                sys.exit(1)
            elif decision == ApprovalDecision.ESCALATE:
                self.print_escalation_message(tool_call, message)
            # If REJECT or ESCALATE, continue to the next approver
        
        # If we've gone through all approvers without an APPROVE decision, treat it as a rejection
        final_message = "Rejected: No approver approved the tool call"
        self.print_rejection_message(tool_call, final_message)
        return False, final_message

    def print_approval_message(self, tool_call: ToolCall, reason: str):
        with input_screen() as console:
            console.print(Panel.fit(
                f"Tool call approved:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
                title="Tool Execution",
                subtitle="Approved"
            ))

    def print_rejection_message(self, tool_call: ToolCall, reason: str):
        with input_screen() as console:
            console.print(Panel.fit(
                f"Tool call rejected:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
                title="Tool Execution",
                subtitle="Rejected"
            ))

    def print_escalation_message(self, tool_call: ToolCall, reason: str):
        with input_screen() as console:
            console.print(Panel.fit(
                f"Tool call escalated:\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {reason}",
                title="Tool Execution",
                subtitle="Escalated"
            ))

    def print_termination_message(self, reason: str):
        with input_screen() as console:
            console.print(Panel.fit(
                f"Execution terminated.\nReason: {reason}",
                title="Execution Terminated",
                subtitle="System Shutdown"
            ))
            
    def print_tool_response_and_get_authorization(self, output: ModelOutput) -> bool:
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
                    *self.format_human_readable_tool_calls(output.message.tool_calls or []),
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

    @staticmethod
    def format_human_readable_tool_calls(tool_calls: list[ToolCall]) -> list[RenderableType]:
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