from inspect_ai.agent._human.commands.clock import clock_action_event
from inspect_ai.model import ModelOutput
from inspect_ai.util._sandbox import sandbox
from inspect_ai.util._sandbox.service import sandbox_service

from .._agent import AgentState
from .commands.command import HumanAgentCommand
from .commands.tool import ToolCommand
from .state import HumanAgentState
from .view import HumanAgentView


async def run_human_agent_service(
    user: str | None,
    state: AgentState,
    commands: list[HumanAgentCommand],
    view: HumanAgentView | None,
) -> AgentState:
    # initialise agent state
    instructions = "\n\n".join([message.text for message in state.messages]).strip()
    agent_state = HumanAgentState(instructions=instructions)

    # record that clock is stopped
    clock_action_event("stop", agent_state)

    # extract service methods from commands
    methods = {
        command.name: command.service(agent_state)
        for command in commands
        if "service" in command.contexts
    }

    # an unexpected tool exception fails the sample (as on the model path);
    # the tool command holds it because the sandbox service doesn't let
    # service-method exceptions propagate
    tool_command = next((c for c in commands if isinstance(c, ToolCommand)), None)

    def tool_failure() -> Exception | None:
        return tool_command.failure if tool_command is not None else None

    # callback to check if task is completed (use this to periodically
    # update the view with the current state)
    def task_is_completed() -> bool:
        if view:
            view.update_state(agent_state)
        return agent_state.answer is not None or tool_failure() is not None

    # run the service
    await sandbox_service(
        name="human_agent",
        methods=methods,
        until=task_is_completed,
        sandbox=sandbox(),
        user=user,
    )

    # the service has stopped (and answered in-flight calls); fail the sample
    failure = tool_failure()
    if failure is not None:
        raise failure

    # set the answer if we have one
    if agent_state.answer is not None:
        state.output = ModelOutput.from_content("human_agent", agent_state.answer)

    # return state
    return state
