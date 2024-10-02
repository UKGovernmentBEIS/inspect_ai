from utils import print_tool_output, print_no_tool_response_and_ask_for_next_action
from rich.panel import Panel
from rich.prompt import Prompt
from typing import Optional
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import (
    ChatMessageTool,
    ChatMessageUser,
    ChatMessageAssistant,
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
from inspect_ai.tool import Tool, bash, python
from inspect_ai.util import input_screen
from approvals import (
    get_approval,
    Approver,
    bash_allowlist_approver,
    human_approver,
    python_allowlist_approver,
    wrap_approvers
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
                tool_outputs = []
                for tool_call in output.message.tool_calls:
                    if approvers:
                        approved, reason = get_approval(approvers, tool_call, state)
                        if not approved:
                            # If not approved, add a message to inform the model
                            tool_outputs.append(ChatMessageTool(
                                tool_call_id=tool_call.id,
                                content=f"Command rejected by the approval system. Reason: {reason}"
                            ))
                            continue
                    
                    # Execute the approved tool call
                    single_tool_output = await call_tools(
                        ChatMessageAssistant(
                            content=output.message.content,
                            tool_calls=[tool_call]
                        ),
                        tools
                    )
                    tool_outputs.extend(single_tool_output)
                
                state.messages.extend(tool_outputs)
                print_tool_output(tool_outputs)
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
    This is the intervention mode where you set approvers on tool call level. We set bash to only allow ls command and escalate to human approver. For python we allow math, random, print, len, range, int, float, str, list, dict, set and escalate to human approver.
    """
    bash_allow_list_approver_func = bash_allowlist_approver(["ls"])
    human_approver_func = human_approver()
    
    # Create a Python allowlist approver
    python_approver_func = python_allowlist_approver(
        allowed_modules=['math', 'random'],
        allowed_functions=['print', 'len', 'range', 'int', 'float', 'str', 'list', 'dict', 'set'],
        disallowed_builtins={'eval', 'exec', 'compile', '__import__', 'open', 'input', 'globals', 'locals'},
        sensitive_modules={'os', 'sys', 'subprocess', 'socket', 'requests', 'multiprocessing'},
        allow_system_state_modification=False
    )
    
    bash_approvers = [bash_allow_list_approver_func, human_approver_func]
    python_approvers = [python_approver_func, human_approver_func]
    
    tools = [
        wrap_approvers(bash(), approvers=bash_approvers),
        wrap_approvers(python(), approvers=python_approvers)
    ]
    
    return Task(
        dataset=MemoryDataset([Sample(input="Unused in interactive mode")]),
        plan=[
            system_message(SYSTEM_PROMPT),
            get_user_prompt(),
            agent_loop(tools),
        ],
        sandbox="docker",
    )

@task
def agent_loop_intervention():
    """
    This is the intervention mode where you set approvers on agent level. We set human approver for all tool calls.
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
