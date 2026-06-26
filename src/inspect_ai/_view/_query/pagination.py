from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Pagination:
    limit: int
    cursor: dict[str, Any] | None
    direction: Literal["forward", "backward"]
