from typing import Protocol


class HumanAgentView(Protocol):
    async def show_cmd(self, cmd: str) -> None: ...
