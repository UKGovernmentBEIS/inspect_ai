from re import Pattern

from .clock import StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .status import StatusCommand
from .submit import SubmitCommand


def human_agent_commands(answer: bool | Pattern[str]) -> list[HumanAgentCommand]:
    commands = [SubmitCommand(answer)] + [
        StatusCommand(),
        StartCommand(),
        StopCommand(),
    ]
    return commands + [InstructionsCommand(commands)]
