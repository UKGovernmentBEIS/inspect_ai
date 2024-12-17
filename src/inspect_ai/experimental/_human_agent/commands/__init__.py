from .clock import StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .note import NoteCommand
from .status import StatusCommand
from .submit import SubmitCommand


def human_agent_commands(answer: bool | str) -> list[HumanAgentCommand]:
    commands = [
        SubmitCommand(answer),
        NoteCommand(),
        StatusCommand(),
        StartCommand(),
        StopCommand(),
    ]
    return commands + [InstructionsCommand(commands)]
