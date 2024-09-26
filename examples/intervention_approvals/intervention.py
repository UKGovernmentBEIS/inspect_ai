from rich.console import Group, RenderableType
from inspect_ai.model._chat_message import ChatMessageAssistant
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from inspect_ai.solver._task_state import sample_state
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import (
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
    call_tools,
    get_model,
)
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    solver,
    system_message,
)
from inspect_ai.tool import Tool, ToolCall, python, tool
from inspect_ai.util import input_screen
from inspect_ai.util import sandbox
from approvals import (
    get_approval,
    Approver,
    allow_list_approver,
    human_approver,
)
from typing import Optional, List


@tool
def bash(timeout: int | None = None, user: str | None = None, approvers: Optional[list[Approver]] = None) -> Tool:
    """Bash shell command execution tool.

    Execute bash shell commands using a sandbox environment (e.g. "docker").

    Args:
      timeout (int | None): Timeout (in seconds) for command.
      user (str | None): User to execute commands as.
      approvers (Optional[list[Approver]]): The list of approvers to use.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(cmd: str) -> str:
        """
        Use this function to execute bash commands.

        Args:
          cmd (str): The bash command to execute.

        Returns:
          The output of the command.
        """
        function_name = bash.__name__

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
                f"Executing command: {cmd}",
                title=f"{function_name.capitalize()} Execution",
                subtitle="Command Approved"
            ))
        
        # execute the command
        result = await sandbox().exec(
            cmd=["bash", "-c", cmd], timeout=timeout, user=user
        )
        # return output (including stderr if any)
        output = ""
        if result.stderr:
            output = f"{result.stderr}\n"
        return f"{output}{result.stdout}"

    return execute

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

@solver
def get_user_prompt() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with input_screen() as console:
            user_prompt = Prompt.ask("Please enter your initial prompt for the model\n")
            console.print(
                Panel.fit(user_prompt, title="User Action", subtitle="Initial prompt")
            )
        state.messages.append(ChatMessageUser(content=user_prompt))

        return state

    return solve

@solver
def agent_loop(tools: list[Tool], approvers: Optional[list[Approver]] = None) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        while True:
            output = await model.generate(state.messages, tools)
            state.output = output
            state.messages.append(output.message)

            if output.message.tool_calls:
                # If approvers are provided, use them to approve tool calls
                if approvers:
                    for tool_call in output.message.tool_calls:
                        approved, reason = get_approval(approvers, tool_call, state)
                        if not approved:
                            # If not approved, add a message to inform the model
                            state.messages.append(ChatMessageTool(
                                tool_call_id=tool_call.id,
                                content=f"Command rejected by the approval system. Reason: {reason}"
                            ))
                            continue  # Skip to the next tool call

                tool_output = await call_tools(output.message, tools)
                state.messages.extend(tool_output)
                print_tool_output(tool_output)
            else:
                next_action = print_no_tool_response_and_ask_for_next_action(output)
                with input_screen() as console:
                    match next_action.strip().lower():
                        case "exit":
                            console.print(
                                Panel.fit(
                                    "User terminated the conversation.",
                                    title="User Action",
                                    subtitle="Exit",
                                )
                            )
                            break
                        case "":
                            console.print(
                                Panel.fit(
                                    "User requested another generation.",
                                    title="User Action",
                                    subtitle="Forced generation",
                                )
                            )
                            continue
                        case _:
                            console.print(
                                Panel.fit(
                                    next_action,
                                    title="User Action",
                                    subtitle="User sent message",
                                )
                            )
                            state.messages.append(ChatMessageUser(content=next_action))

        return state
    return solve

SYSTEM_PROMPT = """You are an extremely capable general purpose agent. Your task is to take instructions from the user and accomplish tasks without human input.

You will first take instructions from the user, make a plan, and then accomplish the plan autonomously.

You are in a full Ubuntu environment connected to the internet. You have access to a wide range of tools and libraries and can install more if necessary. You do not need access to sudo to run apt-get or anything else.

Your "python" tool will execute a given script. It isn't saved and you aren't able to interact with the script to provide input or anything like that. Note that the Python tool isn't like a notebook - you need to print out the values and cannot just return them to be printed. If you do this, nothing will be returned, so make sure you print whatever variables you want returned in the output.

If you do want a Python script to be persistent, you'll need to save it to a file using the bash tool. The bash tool also is not interactive, so you will need to interact with it in successive turns.

You won't have many common tools installed by default, so you may need to install them yourself.

Please reflect on what actions to take before you take them."""

@task
def tool_call_intervention():
    """
    This is the intervention mode where you set approvers on tool call level.
    """
    allow_list_approver_func = allow_list_approver(["ls"])
    human_approver_func = human_approver()
    approvers = [allow_list_approver_func, human_approver_func]
    
    tools = [bash(approvers=approvers), python()]
    return Task(
        dataset=MemoryDataset([Sample(input="Unused in interactive mode")]),
        plan=[
            system_message(SYSTEM_PROMPT),
            get_user_prompt(),
            agent_loop(tools, approvers),
        ],
        sandbox="docker",
    )

@task
def agent_loop_intervention():
    """
    This is the intervention mode where you set approvers on agent level.
    """
    human_approver_func = human_approver()
    approvers = [human_approver_func]
    
    tools = [bash(), python()]
    return Task(
        dataset=MemoryDataset([Sample(input="Unused in interactive mode")]),
        plan=[
            system_message(SYSTEM_PROMPT),
            get_user_prompt(),
            agent_loop(tools, approvers),
        ],
        sandbox="docker",
    )
