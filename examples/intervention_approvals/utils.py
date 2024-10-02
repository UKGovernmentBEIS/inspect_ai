from rich.console import Group, RenderableType
from inspect_ai.model._chat_message import ChatMessageAssistant
from rich.markdown import Markdown
from inspect_ai.tool import ToolCall
from inspect_ai.model import ChatMessageTool, ModelOutput
from inspect_ai.solver import TaskState
from inspect_ai.util import input_screen
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from typing import Optional, List

def format_tool_call_output(output: list[ChatMessageTool]) -> list[RenderableType]:
    output_renderables: list[RenderableType] = []
    for i, tool_output in enumerate(output):
        panel_contents = []
        if tool_output.content != "":
            panel_contents.append(Panel.fit(str(tool_output.content), title="Contents"))
        if tool_output.error:
            error_message = (
                tool_output.error.message
                if tool_output.error.message
                else "error executing command"
            )
            panel_contents.append(
                Panel.fit(error_message, title=f"Error ({tool_output.error.type})")
            )

        output_renderables.append(
            Panel.fit(
                Group(*panel_contents, fit=True),
                title=f"Tool Output #{i} (ID: {tool_output.tool_call_id})",
            )
        )

    return output_renderables

def print_tool_output(output: list[ChatMessageTool]) -> None:
    with input_screen() as console:
        console.print(
            Panel.fit(
                Group(*format_tool_call_output(output), fit=True), title="Tool Output"
            )
        )

def print_no_tool_response_and_ask_for_next_action(output: ModelOutput) -> str:
    with input_screen() as console:
        console.print(
            Panel.fit(
                Markdown(str(output.message.content)),
                title="Model Response",
                subtitle="No tool calls were generated.",
            )
        )

    return Prompt.ask(
        """[🖥️] The agent returned no tool calls.
Please type a message to send to the agent, type nothing and hit enter to force another generation, or type 'exit' to end the conversation.
""",
        default="",
    )
    
    

def get_tool_calls_from_state(state: TaskState) -> Optional[List[ToolCall]]:
    """
    Safely extract tool calls from the last message in the state.
    """
    if not state.messages:
        return None
    last_message = state.messages[-1]
    if isinstance(last_message, ChatMessageAssistant):
        return last_message.tool_calls
    return None


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