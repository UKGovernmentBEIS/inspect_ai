from typing import Any, Protocol

from textual.containers import Container


class InputPanel(Container):
    class Host(Protocol):
        def set_title(self, title: str) -> None: ...
        def activate(self) -> None: ...
        def deactivate(self) -> None: ...
        def close(self) -> None: ...

    def __init__(self, host: Host) -> None:
        super().__init__(classes="task-input-panel")
        self._host = host

    async def __aenter__(self) -> "InputPanel":
        self.activate()
        return self

    async def __aexit__(
        self,
        *execinfo: Any,
    ) -> None:
        self.close()

    def set_title(self, title: str) -> None:
        self._host.set_title(title)

    def activate(self) -> None:
        self._host.activate()

    def deactivate(self) -> None:
        self._host.deactivate()

    def close(self) -> None:
        self._host.close()

    def update(self) -> None:
        """Update method (called periodically e.g. once every second)"""
        pass
