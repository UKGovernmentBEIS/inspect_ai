from ..._agent import AgentState
from .clock import StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .note import NoteCommand
from .score import ScoreCommand
from .status import StatusCommand
from .submit import QuitCommand, SubmitCommand, ValidateCommand


def human_agent_commands(
    state: AgentState,
    answer: bool | str,
    intermediate_scoring: bool,
    record_session: bool,
) -> list[HumanAgentCommand]:
    # base submit, validate, and quit
    commands = [
        SubmitCommand(record_session),
        ValidateCommand(answer),
        QuitCommand(record_session),
    ]

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
