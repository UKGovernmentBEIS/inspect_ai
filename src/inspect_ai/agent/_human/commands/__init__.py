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
        if not any(
            command.name == "start"
            and "cli" in command.contexts
            and "service" in command.contexts
            for command in commands
        ):
            raise ValueError(
                "commands_filter removed the 'start' command (or left it "
                "without both 'cli' and 'service' in its contexts): the "
                "human agent's login shell unconditionally runs `task "
                "start` to begin the task clock, which reaches the CLI "
                "dispatch installed in `task.py` (built from commands with "
                "'cli' in `contexts`) and calls it over the sandbox service "
                "RPC handled by `run_human_agent_service` (built from "
                "commands with 'service' in `contexts`) -- a 'start' "
                "missing either context leaves that call unable to flip "
                "`HumanAgentState.running`, and `task submit`/`task "
                "validate` refuse to complete while the clock has never "
                "started, so the task is permanently stuck. Retain a "
                "command named 'start' with both 'cli' and 'service' in "
                "its contexts (a subclass of StartCommand, or your own "
                "with equivalent clock-start semantics)."
            )

    # with instructions (letting it see the other commands)
    return commands + [InstructionsCommand(commands, instructions)]
