import contextlib
import inspect
import shlex
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Literal, Type, Union, overload

from pydantic import JsonValue
from pydantic_core import to_jsonable_python
from typing_extensions import override

from inspect_ai._util.text import truncate_lines, truncate_string_to_bytes
from inspect_ai._util.working import sandbox_exec_work, untracked_sandbox_execs
from inspect_ai.util._subprocess import ExecResult

from .environment import (
    ST,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxUserUnsupportedError,
)
from .limits import OutputLimitExceededError, SandboxEnvironmentLimits


class SandboxTimeoutError(TimeoutError):
    """Raised when a sandbox operation times out."""

    def __init__(self, message: str, truncated_output: str | None = None) -> None:
        super().__init__(message)
        self.truncated_output = truncated_output
        """Partial command output captured before the timeout, if available."""


class SandboxEnvironmentProxy(SandboxEnvironment):
    def __init__(self, sandbox: SandboxEnvironment) -> None:
        super().__init__()
        self._sandbox = sandbox

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        from inspect_ai.event._sandbox import SandboxEvent
        from inspect_ai.log._transcript import transcript

        # started
        timestamp = datetime.now(timezone.utc)

        # check how many parameters the target sandbox method has
        # (if only 7 then don't send concurrency param)
        sig = inspect.signature(self._sandbox.exec)
        params: dict[str, Any] = dict(
            cmd=cmd,
            input=input,
            cwd=cwd,
            env=env or {},
            user=user,
            timeout=timeout,
            timeout_retry=timeout_retry,
        )
        if len(sig.parameters) == 8:
            params["concurrency"] = concurrency

        # make call
        try:
            with sandbox_exec_work():
                result = await self._sandbox.exec(**params)
        except TimeoutError as ex:
            raise SandboxTimeoutError(
                str(ex), truncated_output=getattr(ex, "truncated_output", None)
            ) from ex

        # yield event
        options: dict[str, JsonValue] = {}
        if cwd:
            options["cwd"] = cwd
        if env:
            options["env"] = to_jsonable_python(env)
        if user:
            options["user"] = user
        if timeout is not None:
            options["timeout"] = timeout
        if timeout_retry is not True:
            options["timeout_retry"] = timeout_retry

        if self._events_enabled():
            transcript()._event(
                SandboxEvent(
                    timestamp=timestamp,
                    action="exec",
                    cmd=" ".join([shlex.quote(c) for c in cmd]),
                    input=content_display(input) if input is not None else None,
                    options=options,
                    result=result.returncode,
                    output=content_display(
                        f"{result.stderr}\n\n{result.stdout}"
                        if result.stderr
                        else result.stdout
                    ),
                    completed=datetime.now(timezone.utc),
                )
            )

        # verify output size
        SandboxEnvironmentProxy.verify_exec_result_size(result)

        # return result
        return result

    @staticmethod
    def verify_exec_result_size(exec_result: ExecResult[str]) -> None:
        """Verify the size of the output streams in an ``ExecResult``.

        Raises:
            OutputLimitExceededError: If an output stream exceeds the limit.
        """
        limit = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE
        stdout_truncated = truncate_string_to_bytes(exec_result.stdout, limit)
        stderr_truncated = truncate_string_to_bytes(exec_result.stderr, limit)
        if not stdout_truncated and not stderr_truncated:
            return
        stdout = stdout_truncated.output if stdout_truncated else exec_result.stdout
        stderr = stderr_truncated.output if stderr_truncated else exec_result.stderr
        raise OutputLimitExceededError(
            limit_str=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR,
            truncated_output=f"{stdout}{stderr}",
        )

    @override
    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        from inspect_ai.event._sandbox import SandboxEvent
        from inspect_ai.log._transcript import transcript

        timestamp = datetime.now(timezone.utc)
        params = self._file_user_params("write_file", user)

        # make call
        try:
            await self._sandbox.write_file(file, contents, **params)
        except TimeoutError as ex:
            raise SandboxTimeoutError(str(ex)) from ex

        # yield event
        if self._events_enabled():
            transcript()._event(
                SandboxEvent(
                    timestamp=timestamp,
                    action="write_file",
                    options=params or None,
                    file=file,
                    input=content_display(contents),
                    completed=datetime.now(timezone.utc),
                )
            )

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    @override
    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> Union[str | bytes]:
        from inspect_ai.event._sandbox import SandboxEvent
        from inspect_ai.log._transcript import transcript

        timestamp = datetime.now(timezone.utc)
        params = self._file_user_params("read_file", user)

        # make call
        try:
            if text is True:
                output: str | bytes = await self._sandbox.read_file(
                    file, True, **params
                )
            else:
                output = await self._sandbox.read_file(file, False, **params)
        except TimeoutError as ex:
            raise SandboxTimeoutError(str(ex)) from ex

        # yield event
        if self._events_enabled():
            transcript()._event(
                SandboxEvent(
                    timestamp=timestamp,
                    action="read_file",
                    options=params or None,
                    file=file,
                    output=content_display(output),
                    completed=datetime.now(timezone.utc),
                )
            )

        # return result
        return output

    @override
    def _supports_file_user(
        self, operation: Literal["read_file", "write_file"]
    ) -> bool:
        return self._sandbox._supports_file_user(operation)

    def _file_user_params(
        self, operation: Literal["read_file", "write_file"], user: str | None
    ) -> dict[str, Any]:
        if user is None:
            return {}
        if not self._supports_file_user(operation):
            raise SandboxUserUnsupportedError(
                f"{type(self._sandbox).__name__}.{operation} does not support "
                f"user={user!r}. Update the sandbox provider to support file users."
            )
        return {"user": user}

    @override
    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        params: dict[str, Any] = {"user": user} if user is not None else {}
        return await self._sandbox.connection(**params)

    @override
    def as_type(self, sandbox_cls: Type[ST]) -> ST:
        if isinstance(self._sandbox, sandbox_cls):
            return self._sandbox
        else:
            raise TypeError(
                f"Expected instance of {sandbox_cls.__name__}, got {type(self._sandbox).__name__}"
            )

    @override
    def default_polling_interval(self) -> float:
        return self._sandbox.default_polling_interval()

    def _events_enabled(self) -> bool:
        return self not in _no_events_proxies.get()

    @contextlib.contextmanager
    def no_events(self) -> Iterator[None]:
        """Record no events for calls made inside the block.

        Applies to the current task and tasks it starts inside the block;
        other tasks using this sandbox still record theirs.
        """
        token = _no_events_proxies.set(_no_events_proxies.get() | {self})
        try:
            with untracked_sandbox_execs():
                yield
        finally:
            _no_events_proxies.reset(token)

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


# proxies inside `no_events()` in the current context
_no_events_proxies: ContextVar[frozenset[SandboxEnvironmentProxy]] = ContextVar(
    "sandbox_no_events_proxies", default=frozenset()
)


def without_sandbox_events(
    sandbox: SandboxEnvironment,
) -> contextlib.AbstractContextManager[None]:
    """Suppress transcript events for commands run on ``sandbox`` inside the block.

    Only the event-recording proxy that wraps sample sandboxes emits events; any
    other sandbox object (a provider used directly, or a test fake) needs nothing.
    """
    if isinstance(sandbox, SandboxEnvironmentProxy):
        return sandbox.no_events()
    return contextlib.nullcontext()


def content_display(content: str | bytes) -> str:
    if isinstance(content, str):
        content, truncated = truncate_lines(content, 20)
        if truncated:
            content = f"{content}\n\nOutput truncated ({truncated} additional lines)"
        return content
    else:
        return f"binary ({pretty_size(len(content))})"


def pretty_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"

    return f"{size / (1024 * 1024):.2f} MB"
