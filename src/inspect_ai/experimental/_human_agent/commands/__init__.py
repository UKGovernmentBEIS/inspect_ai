from .clock import ClockCommand, StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .submit import SubmitCommand


def human_agent_commands() -> list[HumanAgentCommand]:
    commands = [
        SubmitCommand(),
        ClockCommand(),
        StartCommand(),
        StopCommand(),
    ]
    return commands + [InstructionsCommand(commands)]
