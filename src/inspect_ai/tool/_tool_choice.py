from dataclasses import dataclass
from typing import Literal, Union


@dataclass
class ToolFunction:
    name: str
    """The name of the function to call."""


ToolChoice = Union[Literal["auto", "any", "none"], ToolFunction]
"""Specify which tool to call.

"auto" means the model decides; "any" means use at least one tool,
"none" means never call a tool; ToolFunction instructs the model
to call a specific function.
"""
