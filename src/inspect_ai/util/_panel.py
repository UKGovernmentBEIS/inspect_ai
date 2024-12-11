from typing import Any, Protocol, TypeVar

from textual.containers import Container


class InputPanel(Container):
    DEFAULT_CLASSES = "task-input-panel"

    class Host(Protocol):
        def set_title(self, title: str) -> None: ...
        def activate(self) -> None: ...
        def deactivate(self) -> None: ...
        def close(self) -> None: ...

    def __init__(self, title: str, host: Host) -> None:
        super().__init__()
        self._title = title
        self._host = host

    async def __aenter__(self) -> "InputPanel":
        self.activate()
        return self

    async def __aexit__(
        self,
        *execinfo: Any,
    ) -> None:
        self.close()

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, title: str) -> None:
        self._title = title
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


TP = TypeVar("TP", bound=InputPanel)


async def input_panel(title: str, panel: type[TP]) -> TP:
    """Create an input panel in the task display.

    There can only be a single instance of an InputPanel with a given
    'title' running at once. Therefore, if the panel doesn't exist it
    is created, otherwise a reference to the existing panel is returned.

    Examples:
        Create/activate an input panel (the panel will remain after
        the scope exits -- see below for open/close semantics)

        ```python
        panel = await input_panel("Custom", CustomPanel)
        panel.activate()
        ```

        Activate and close an input panel using a context manager:

        ```python
        async with await input_panel("Custom", CustomPanel) as panel:
            ...
        ```

    Args:
       title (str): Input panel title.
       panel (type[TP]): Type of panel widget (must derive from `InputPanel`)

    Returns:
       InputPanel: Instance of widget running in the task display.

    Raises:
       NotImplementedError: If Inspect is not running in display='full' model.
    """
    from inspect_ai._display.core.active import task_screen

    return await task_screen().input_panel(title, panel)
