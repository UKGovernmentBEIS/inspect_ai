from ..._agent import AgentState
from .clock import StartCommand, StopCommand
from .command import HumanAgentCommand, HumanAgentCommandsFilter
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
    instructions: str | None,
    commands_filter: HumanAgentCommandsFilter | None = None,
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

    # let the caller swap/append commands before instructions is built
    if commands_filter is not None:
        commands = commands_filter(commands)
        if not any(command.name == "start" for command in commands):
            raise ValueError(
                "commands_filter removed the 'start' command: the human "
                "agent's login shell unconditionally runs `task start` to "
                "begin the task clock, and `task submit`/`task validate` "
                "refuse to complete while the clock has never started, so a "
                "command list without one named 'start' leaves the task "
                "permanently stuck. Retain a command named 'start' (a "
                "subclass of StartCommand, or your own with equivalent "
                "clock-start semantics)."
            )

    # with instructions (letting it see the other commands)
    return commands + [InstructionsCommand(commands, instructions)]
