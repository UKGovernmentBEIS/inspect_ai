from ..._util.session_controller import SessionController
from ._session import Session
from .tool_types import BashRestartResult, InteractResult

DEFAULT_SESSION_NAME = "BashSession"


class Controller(SessionController[Session]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(self) -> str:
        return await self.create_new_session(DEFAULT_SESSION_NAME, Session.create)

    async def interact(
        self,
        session_name: str,
        input_text: str | None,
        wait_for_output: int,
        idle_timeout: float,
    ) -> InteractResult:
        return await self.session_for_name(session_name).interact(
            input_text, wait_for_output, idle_timeout
        )

    async def restart(self, session_name: str, timeout: int = 30) -> BashRestartResult:
        return await self.session_for_name(session_name).restart(timeout)
