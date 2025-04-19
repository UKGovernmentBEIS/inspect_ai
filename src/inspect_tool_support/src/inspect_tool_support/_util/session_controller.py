import threading
from typing import Awaitable, Callable, Generic, TypeVar

SessionT = TypeVar("SessionT", bound=object)


class SessionController(Generic[SessionT]):
    """SessionController provides shared code for stateful tools to implement isolation between inspect subtask sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionT] = {}

    async def create_new_session(
        self, default_name: str, session_factory: Callable[[], Awaitable[SessionT]]
    ) -> str:
        with self._lock:
            current_count = len(self._sessions)
            name = (
                default_name
                if current_count == 0
                else f"{default_name}_{current_count}"
            )
            self._sessions[name] = await session_factory()
            return name

    def session_for_name(self, session_name: str) -> SessionT:
        return self._sessions[session_name]
