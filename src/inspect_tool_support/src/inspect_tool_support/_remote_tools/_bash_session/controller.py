from inspect_tool_support._remote_tools._bash_session.bash_session import BashSession
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
    BashRestartResult,
)
from inspect_tool_support._util._session_controller import SessionController

DEFAULT_SESSION_NAME = "BashSession"


class BashSessionController(SessionController[BashSession]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(self) -> str:
        return await self.create_new_session(DEFAULT_SESSION_NAME, BashSession.create)

    async def execute_command(
        self, session_name: str, command: str, timeout: int = 30
    ) -> BashCommandResult:
        return await self.session_for_name(session_name).execute_command(
            command, timeout
        )

    async def restart(self, session_name: str, timeout: int = 30) -> BashRestartResult:
        return await self.session_for_name(session_name).restart(timeout)
