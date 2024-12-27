from inspect_ai.solver._task_state import TaskState

from .clock import StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .note import NoteCommand
from .score import ScoreCommand
from .status import StatusCommand
from .submit import SubmitCommand, ValidateCommand


def human_agent_commands(
    state: TaskState,
    answer: bool | str,
    intermediate_scoring: bool,
    record_session: bool,
) -> list[HumanAgentCommand]:
    # base submit and validate
    commands = [SubmitCommand(record_session), ValidateCommand(answer)]

    # optional intermediate scoring
    if intermediate_scoring:
        commands.append(ScoreCommand(state))

    # remaining commands
    commands.extend(
        [
            NoteCommand(),
            StatusCommand(),
            StartCommand(),
            StopCommand(),
        ]
    )

    # with instructions (letting it see the other commands)
    return commands + [InstructionsCommand(commands)]
