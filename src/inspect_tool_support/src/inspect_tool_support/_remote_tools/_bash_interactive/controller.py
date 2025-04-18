from inspect_tool_support._remote_tools._bash_interactive._session import Session
from inspect_tool_support._remote_tools._bash_interactive.tool_types import (
    BashInputResult,
    BashRestartResult,
)
from inspect_tool_support._util._session_controller import SessionController

DEFAULT_SESSION_NAME = "BashSession"


class BashInteractiveController(SessionController[Session]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(self) -> str:
        return await self.create_new_session(DEFAULT_SESSION_NAME, Session.create)

    async def execute_input(
        self, session_name: str, command: str, timeout: int = 30
    ) -> BashInputResult:
        return await self.session_for_name(session_name).execute_input(command, timeout)

    async def restart(self, session_name: str, timeout: int = 30) -> BashRestartResult:
        return await self.session_for_name(session_name).restart(timeout)
