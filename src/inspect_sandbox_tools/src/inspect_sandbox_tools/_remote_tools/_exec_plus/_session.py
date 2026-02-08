from ..._util.exec_any.session import Session as ExecAnySession
from .some_types import ExecPlusPollResponse


class Session:
    @classmethod
    async def create(
        cls,
        cmd: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        initial_input: str | bytes | None = None,
    ) -> "Session":
        return cls(
            await ExecAnySession.create(cmd=cmd, env=env or {}, cwd=cwd),
            cmd=cmd,
            initial_input=initial_input,
        )

    def __init__(
        self,
        session: ExecAnySession,
        cmd: list[str],
        initial_input: str | bytes | None = None,
    ) -> None:
        self._session = session
        self._cmd = cmd
        self._initial_input = initial_input
        self._initial_input_sent = False
        self._completed = False
        self._exit_code: int | None = None

    async def poll(
        self, wait_for_output: int, idle_timeout: float
    ) -> ExecPlusPollResponse:
        # Send initial input on first poll if provided
        input_to_send = None
        if not self._initial_input_sent and self._initial_input:
            if isinstance(self._initial_input, str):
                input_to_send = self._initial_input
            else:
                input_to_send = self._initial_input.decode("utf-8", errors="replace")
            self._initial_input_sent = True

        stdout, stderr = await self._session.interact(
            input_to_send, wait_for_output, idle_timeout
        )

        return ExecPlusPollResponse(
            stdout=stdout or "",
            stderr=stderr or "",
            completed=self._completed,
            exit_code=self._exit_code or 0,
        )

    async def terminate(self, timeout: int = 30) -> None:
        await self._session.terminate(timeout)
        self._completed = True
