import pwd

from ..._util.common_types import ToolException
from ..._util.session_controller import SessionController
from ..._util.user_switch import is_current_user
from ._session import Session
from .tool_types import BashRestartResult, InteractResult

DEFAULT_SESSION_NAME = "BashSession"


class Controller(SessionController[Session]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(
        self, user: str | None = None, can_switch_user: bool = False
    ) -> str:
        if user is not None and is_current_user(user):
            user = None
        if user is not None and not can_switch_user:
            raise ToolException(
                f"Cannot switch to user {user!r}: server is not running as root"
            )
        if user is not None:
            try:
                pwd.getpwnam(user)
            except KeyError:
                raise RuntimeError(f"User {user!r} not found in /etc/passwd") from None
        return await self.create_new_session(
            DEFAULT_SESSION_NAME, lambda: Session.create(user=user)
        )

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
