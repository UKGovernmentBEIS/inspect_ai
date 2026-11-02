import asyncio
import secrets
from typing import Awaitable, Callable, Generic, TypeVar

SessionT = TypeVar("SessionT", bound=object)


class SessionController(Generic[SessionT]):
    """SessionController provides shared code for stateful tools to implement isolation between inspect subtask sessions."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionT] = {}

    async def create_new_session(
        self,
        default_name: str,
        session_factory: Callable[[], Awaitable[SessionT]],
        unique: bool = False,
    ) -> str:
        """Create a session and return its name.

        Names are counted (`default_name`, `default_name_1`, ...) unless `unique`,
        which adds a random 128-bit suffix that no other server will issue.

        Creations run one at a time, so a counted name is never issued twice. The
        lock is an asyncio lock: the server handles requests concurrently on one
        event loop, and a creation waiting for it must not block that loop.
        """
        async with self._lock:
            current_count = len(self._sessions)
            if unique:
                name = f"{default_name}_{secrets.token_hex(16)}"
            else:
                name = (
                    default_name
                    if current_count == 0
                    else f"{default_name}_{current_count}"
                )
            self._sessions[name] = await session_factory()
            return name

    def session_for_name(self, session_name: str) -> SessionT:
        return self._sessions[session_name]
