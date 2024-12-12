from typing import Protocol

from .state import HumanAgentState


class HumanAgentView(Protocol):
    def update_state(self, state: HumanAgentState) -> None: ...
