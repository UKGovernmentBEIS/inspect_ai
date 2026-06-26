from dataclasses import dataclass
from typing import Literal


@dataclass
class OrderBy:
    column: str
    direction: Literal["ASC", "DESC"]
