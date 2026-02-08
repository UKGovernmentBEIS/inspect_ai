from ..._util.session_controller import SessionController
from ._session import Session
from .some_types import ExecPlusPollResponse

DEFAULT_SESSION_NAME = "ExecPlusSession"


class Controller(SessionController[Session]):
    async def new_session(
        self,
        cmd: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        initial_input: str | bytes | None = None,
    ) -> str:
        async def session_factory() -> Session:
            return await Session.create(
                cmd=cmd, env=env, cwd=cwd, initial_input=initial_input
            )

        return await self.create_new_session(DEFAULT_SESSION_NAME, session_factory)

    async def poll(
        self, session_name: str, wait_for_output: int, idle_timeout: float
    ) -> ExecPlusPollResponse:
        return await self.session_for_name(session_name).poll(
            wait_for_output, idle_timeout
        )
