from re import Pattern

from .clock import clock_commands
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .submit import SubmitCommand


def human_agent_commands(answer: bool | Pattern[str]) -> list[HumanAgentCommand]:
    commands = [SubmitCommand(answer)] + clock_commands()
    return commands + [InstructionsCommand(commands)]
