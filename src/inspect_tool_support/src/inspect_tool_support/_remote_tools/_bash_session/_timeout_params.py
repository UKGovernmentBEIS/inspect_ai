from dataclasses import dataclass
from typing import Literal


@dataclass
class InteractiveParams:
    first_data_timeout: int
    debounce: int
    interactive: Literal[True] = True


@dataclass
class NonInteractiveParams:
    timeout: int
    interactive: Literal[False] = False


TimeoutParams = InteractiveParams | NonInteractiveParams
