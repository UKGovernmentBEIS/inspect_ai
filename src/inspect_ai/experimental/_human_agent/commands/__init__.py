from .clock import ClockCommand, StartCommand, StopCommand
from .command import HumanAgentCommand
from .instructions import InstructionsCommand
from .submit import SubmitCommand


def human_agent_commands(_intermediate_scoring: bool) -> list[HumanAgentCommand]:
    return [
        ClockCommand(),
        StartCommand(),
        StopCommand(),
        InstructionsCommand(),
        SubmitCommand(),
    ]
