from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

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
from inspect_ai.tool import Tool, ToolCall, bash, python
from inspect_ai.util import input_screen


def format_human_readable_tool_calls(
    tool_calls: list[ToolCall],
) -> list[RenderableType]:
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


def print_tool_response_and_get_authorization(output: ModelOutput) -> bool:
    renderables: list[RenderableType] = []
    if output.message.content != "":
        renderables.append(
            Panel.fit(Markdown(str(output.message.content)), title="Textual Response")
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
            "Do you FULLY understand these tool calls and approve their execution? (y/n): \n"
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
def agent_loop(tools: list[Tool]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        while True:
            output = await model.generate(state.messages, tools)
            state.output = output
            state.messages.append(output.message)

            if output.message.tool_calls:
                authorization = print_tool_response_and_get_authorization(output)
                if not authorization:
                    # Exit out of the evaluation
                    break

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
def intervention():
    tools = [bash(), python()]
    return Task(
        dataset=MemoryDataset([Sample(input="Unused in interactive mode")]),
        plan=[
            system_message(SYSTEM_PROMPT),
            get_user_prompt(),
            agent_loop(tools),
        ],
        sandbox="docker",
    )
