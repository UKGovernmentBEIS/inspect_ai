from inspect_ai.model import ModelOutput
from inspect_ai.util._sandbox import sandbox
from inspect_ai.util._sandbox.service import sandbox_service

from .._task_state import TaskState
from .commands.command import HumanAgentCommand
from .state import HumanAgentState
from .view import HumanAgentView


async def run_human_agent_service(
    state: TaskState, commands: list[HumanAgentCommand], view: HumanAgentView | None
) -> TaskState:
    # initialise agent state
    instructions = "\n\n".join([message.text for message in state.messages]).strip()
    agent_state = HumanAgentState(instructions=instructions)

    # extract service methods from commands
    methods = {
        command.name: command.service(agent_state)
        for command in commands
        if "service" in command.contexts
    }

    # callback to check if task is completed (use this to periodically
    # update the view with the current state)
    def task_is_completed() -> bool:
        if view:
            view.update_state(agent_state)
        return agent_state.answer is not None

    # run the service
    await sandbox_service(
        name="human_agent",
        methods=methods,
        until=task_is_completed,
        sandbox=sandbox(),
    )

    # set the answer if we have one
    if agent_state.answer is not None:
        state.output = ModelOutput.from_content("human_agent", agent_state.answer)

    # return state
    return state
