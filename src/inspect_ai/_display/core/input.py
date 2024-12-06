from typing import Any, Protocol

from textual.containers import Container


class InputPanel(Container):
    class Host(Protocol):
        def activate(self) -> None: ...
        def close(self) -> None: ...

    def __init__(self, host: Host) -> None:
        super().__init__(classes="task-input-panel")
        self.host = host

    async def __aenter__(self) -> "InputPanel":
        self.host.activate()
        return self

    async def __aexit__(
        self,
        *execinfo: Any,
    ) -> None:
        self.host.close()

    def activate(self) -> None:
        self.host.activate()

    def close(self) -> None:
        self.host.close()

    def update(self) -> None:
        """Update method (called periodically e.g. once every second)"""
        pass
