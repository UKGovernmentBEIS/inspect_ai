import asyncio
import pwd

from ..._util.common_types import ServerErrorCode, ToolException
from ..._util.session_controller import SessionController
from ..._util.user_switch import RunAs, switch_target
from ._session import Session
from .tool_types import BashRestartResult, InteractResult

DEFAULT_SESSION_NAME = "BashSession"


class SessionNotFoundError(ToolException):
    """A request for a bound shell this server does not have."""

    code = ServerErrorCode.SESSION_NOT_FOUND


class SessionOwnerError(ToolException):
    """A request whose owner is not the user the shell is bound to."""

    code = ServerErrorCode.SESSION_OWNER


class Controller(SessionController[Session]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(
        self,
        user: str | RunAs | None = None,
        can_switch_user: bool = False,
        bind: bool = False,
    ) -> str:
        """Create a shell running as `user`, and return its name.

        A bound shell (`bind`) records `user` as its owner and gets a name that no
        other server issues, so a request for it never reaches another shell after
        the server is replaced.
        """
        if bind and not isinstance(user, str):
            raise ToolException("A bound shell needs a username as its user")
        owner = user if bind else None
        user = switch_target(user, can_switch_user)
        if isinstance(user, str):
            try:
                pwd.getpwnam(user)
            except KeyError:
                raise RuntimeError(f"User {user!r} not found in /etc/passwd") from None
        return await self.create_new_session(
            DEFAULT_SESSION_NAME,
            lambda: Session.create(user=user, owner=owner),
            unique=bind,
        )

    async def interact(
        self,
        session_name: str,
        owner: str | None,
        input_text: str | None,
        wait_for_output: int,
        idle_timeout: float,
        max_output_bytes: int | None,
    ) -> InteractResult:
        return await self._owned_session(session_name, owner).interact(
            input_text, wait_for_output, idle_timeout, max_output_bytes
        )

    async def restart(
        self, session_name: str, owner: str | None, timeout: int = 30
    ) -> BashRestartResult:
        return await self._owned_session(session_name, owner).restart(timeout)

    def _owned_session(self, session_name: str, owner: str | None) -> Session:
        """The shell named `session_name`, if `owner` is the user it is bound to.

        A request with an owner is for a bound shell: if this server does not have
        it (the server was replaced, or this is another sandbox), it is refused
        rather than looked up as an unbound shell.
        """
        if owner is not None and session_name not in self._sessions:
            raise SessionNotFoundError(
                f"This server has no bash session {session_name!r} for {owner!r}"
            )
        session = self.session_for_name(session_name)
        if session.owner != owner:
            raise SessionOwnerError(
                f"Bash session {session_name!r} is bound to "
                f"{session.owner!r}, not {owner!r}"
            )
        return session

    async def shutdown(self) -> None:
        """Terminate every bash session owned by this server."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()

        results = await asyncio.gather(
            *(session.shutdown(timeout=30) for session in sessions),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise RuntimeError("; ".join(str(error) for error in errors))
