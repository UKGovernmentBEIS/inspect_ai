from inspect_tool_support._remote_tools._bash_interactive._session import Session
from inspect_tool_support._remote_tools._bash_interactive.tool_types import (
    BashRestartResult,
    InteractResult,
)
from inspect_tool_support._util.session_controller import SessionController

DEFAULT_SESSION_NAME = "BashSession"


class BashInteractiveController(SessionController[Session]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(self) -> str:
        return await self.create_new_session(DEFAULT_SESSION_NAME, Session.create)

    async def interact(
        self, session_name: str, input_text: str | None, idle_timeout: int
    ) -> InteractResult:
        return await self.session_for_name(session_name).interact(
            input_text, idle_timeout
        )

    async def restart(self, session_name: str, timeout: int = 30) -> BashRestartResult:
        return await self.session_for_name(session_name).restart(timeout)
