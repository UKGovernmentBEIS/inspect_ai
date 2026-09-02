import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, NamedTuple, cast

import anyio
from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError
from pydantic_monty import (
    CollectString,
    ExternalException,
    ExternalReturnValue,
    ExternalSettledResult,
    FunctionSnapshot,
    FutureSnapshot,
    Monty,
    MontyComplete,
    MontyCrashedError,
    MontyRuntimeError,
    MontySyntaxError,
    MontyTypingError,
    NameLookupSnapshot,
    ResourceLimits,
)
from shortuuid import uuid

from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import (
    _tool_max_output,
    call_tool,
    tool_call_view,
    truncate_tool_output,
)
from inspect_ai.tool._tool import (
    ToolApprovalError,
    ToolError,
    ToolParsingError,
    ToolResult,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util import OutputLimitExceededError
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.events import SandboxTimeoutError

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup
else:
    from builtins import BaseExceptionGroup

MontyState = FunctionSnapshot | FutureSnapshot | NameLookupSnapshot | MontyComplete
Dispatch = Callable[[str, dict[str, Any]], Awaitable[Any]]
ContentResult = (
    ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument
)
_CONTENT_RESULT_ADAPTER: TypeAdapter[ContentResult | list[ContentResult]] = TypeAdapter(
    ContentResult | list[ContentResult]
)
_JSON_RESULT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Any)


class _RecoverableToolError(Exception):
    pass


class _ToolExecution(NamedTuple):
    result: ToolResult
    event_result: ToolResult
    truncated: tuple[int, int] | None = None


@dataclass
class _CallOutcome:
    done: anyio.Event = field(default_factory=anyio.Event)
    value: Any = None
    error: BaseException | None = None


@dataclass
class _PendingCall:
    event: anyio.Event = field(default_factory=anyio.Event)
    result: ExternalSettledResult | None = None
    fatal_error: BaseException | None = None

    async def wait(self) -> ExternalSettledResult:
        await self.event.wait()
        if self.fatal_error is not None:
            raise self.fatal_error
        if self.result is None:
            raise RuntimeError("Monty tool call completed without a result")
        return self.result


@dataclass
class _MontyExecutor:
    dispatch: Dispatch
    valid_names: set[str]
    sequential_names: set[str]
    max_tool_calls: int
    _calls: int = field(default=0, init=False)
    _pending: dict[int, _PendingCall] = field(default_factory=dict, init=False)
    _pre_resolved: dict[int, ExternalSettledResult] = field(
        default_factory=dict, init=False
    )
    _task_group: anyio.abc.TaskGroup | None = field(default=None, init=False)

    async def run(self, state: MontyState) -> MontyComplete:
        try:
            async with anyio.create_task_group() as task_group:
                self._task_group = task_group
                try:
                    while not isinstance(state, MontyComplete):
                        if isinstance(state, NameLookupSnapshot):
                            state = await _offload_state(state.resume)
                        elif isinstance(state, FunctionSnapshot):
                            state = await self._handle_function(state)
                        else:
                            state = await self._resolve_futures(state)
                finally:
                    task_group.cancel_scope.cancel()
                    self._task_group = None
        except Exception as ex:
            error = inner_exception(ex)
            raise error.with_traceback(error.__traceback__)
        return cast(MontyComplete, state)

    async def _handle_function(self, snapshot: FunctionSnapshot) -> MontyState:
        if snapshot.is_os_function:
            return await _offload_state(snapshot.resume_auto)
        if snapshot.function_name not in self.valid_names:
            return await _offload_state(
                snapshot.resume,
                ExternalException(
                    exception=NameError(f"Unknown function: {snapshot.function_name}")
                ),
            )
        if snapshot.args:
            return await _offload_state(
                snapshot.resume,
                ExternalException(
                    exception=TypeError(
                        f"{snapshot.function_name}() only accepts keyword arguments"
                    )
                ),
            )
        if not self._reserve_call():
            return await _offload_state(
                snapshot.resume,
                ExternalException(
                    exception=RuntimeError(
                        f"run_code allows at most {self.max_tool_calls} wrapped-tool "
                        "calls per invocation"
                    )
                ),
            )

        if snapshot.function_name in self.sequential_names:
            self._pre_resolved.update(await self._await_pending(list(self._pending)))
            self._pre_resolved[snapshot.call_id] = await self._settled_call(
                snapshot.function_name, snapshot.kwargs
            )
            return await _offload_state(snapshot.resume, {"future": ...})

        pending = _PendingCall()
        self._pending[snapshot.call_id] = pending
        if self._task_group is None:
            raise RuntimeError("Monty executor task group is not active")
        self._task_group.start_soon(
            self._run_pending,
            pending,
            snapshot.function_name,
            snapshot.kwargs,
        )
        return await _offload_state(snapshot.resume, {"future": ...})

    async def _resolve_futures(self, snapshot: FutureSnapshot) -> MontyState:
        results: dict[int, ExternalSettledResult] = {}
        unresolved: list[int] = []
        for call_id in snapshot.pending_call_ids:
            if call_id in self._pre_resolved:
                results[call_id] = self._pre_resolved.pop(call_id)
            else:
                unresolved.append(call_id)
        results.update(await self._await_pending(unresolved))
        return await _offload_state(snapshot.resume, results)

    async def _await_pending(
        self, call_ids: list[int]
    ) -> dict[int, ExternalSettledResult]:
        results: dict[int, ExternalSettledResult] = {}

        async def resolve(call_id: int, pending: _PendingCall) -> None:
            results[call_id] = await pending.wait()

        try:
            async with anyio.create_task_group() as task_group:
                for call_id in call_ids:
                    task_group.start_soon(resolve, call_id, self._pending.pop(call_id))
        except BaseException as ex:
            if isinstance(ex, Exception):
                error = inner_exception(ex)
                raise error.with_traceback(error.__traceback__)
            raise
        return results

    async def _run_pending(
        self,
        pending: _PendingCall,
        name: str,
        kwargs: dict[str, Any],
    ) -> None:
        try:
            pending.result = await self._settled_call(name, kwargs)
        except BaseException as ex:
            pending.fatal_error = ex
        finally:
            pending.event.set()

    async def _settled_call(
        self, name: str, kwargs: dict[str, Any]
    ) -> ExternalSettledResult:
        try:
            result = await self.dispatch(name, kwargs)
        except _RecoverableToolError as ex:
            return ExternalException(exception=RuntimeError(str(ex)))
        return ExternalReturnValue(return_value=result)

    def _reserve_call(self) -> bool:
        if self._calls >= self.max_tool_calls:
            return False
        self._calls += 1
        return True


async def execute_monty(
    *,
    code: str,
    tools: dict[str, ToolDef],
    max_tool_calls: int,
    max_duration_secs: float,
    max_memory: int,
    type_check_stubs: str,
) -> ToolResult:
    """Execute a Monty snippet and dispatch its external function calls."""

    async def dispatch(name: str, kwargs: dict[str, Any]) -> Any:
        return await _execute_inner_tool(
            code, tools[name], kwargs, list(tools.values())
        )

    capture = CollectString()
    limits = cast(
        ResourceLimits,
        {"max_duration_secs": max_duration_secs, "max_memory": max_memory},
    )
    try:
        async with _MontyBridge(
            limits=limits, type_check_stubs=type_check_stubs
        ) as session:
            state = await session.feed_start(code, capture)
            complete = await _MontyExecutor(
                dispatch=dispatch,
                valid_names=set(tools),
                sequential_names={
                    name for name, tool_def in tools.items() if not tool_def.parallel
                },
                max_tool_calls=max_tool_calls,
            ).run(state)
    except MontySyntaxError as ex:
        raise ToolError(
            f"Syntax error in code:\n{_with_print(capture, ex.display())}"
        ) from ex
    except MontyTypingError as ex:
        raise ToolError(
            f"Type error in code:\n{_with_print(capture, ex.display())}"
        ) from ex
    except MontyRuntimeError as ex:
        raise ToolError(
            f"Runtime error in code:\n{_with_print(capture, ex.display())}"
        ) from ex
    except MontyCrashedError as ex:
        raise ToolError("The code exhausted or crashed its Monty sandbox.") from ex
    except BaseException as ex:
        if _is_sandbox_panic(ex):
            raise ToolError("The Monty sandbox crashed while running the code.") from ex
        raise

    return _tool_result(complete.output, capture.output)


@dataclass
class _MontyBridge:
    """Run Monty's synchronous IPC off the AnyIO event-loop thread."""

    limits: ResourceLimits
    type_check_stubs: str
    _pool: Monty | None = field(default=None, init=False)
    _checkout: Any = field(default=None, init=False)
    _session: Any = field(default=None, init=False)
    _worker_pid: int | None = field(default=None, init=False)

    async def __aenter__(self) -> "_MontyBridge":
        try:
            self._pool = Monty(min_processes=1, max_processes=1)
            await _offload_cleanup(self._pool.__enter__)
            self._checkout = self._pool.checkout(
                limits=self.limits,
                type_check=True,
                type_check_stubs=self.type_check_stubs,
            )
            self._session = await _offload_cleanup(self._checkout.__enter__)
            self._worker_pid = cast(int, self._session.worker_pid)
            return self
        except BaseException as ex:
            await self.__aexit__(type(ex), ex, ex.__traceback__)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        cancelled = _contains_cancellation(exc)
        with anyio.CancelScope(shield=True):
            if cancelled and self._worker_pid is not None:
                try:
                    os.kill(self._worker_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

            cleanup_error: Exception | None = None
            if self._checkout is not None:
                try:
                    await _offload_cleanup(
                        self._checkout.__exit__, exc_type, exc, traceback
                    )
                except Exception as cleanup_ex:
                    cleanup_error = cleanup_ex
            if self._pool is not None:
                try:
                    await _offload_cleanup(
                        self._pool.__exit__, exc_type, exc, traceback
                    )
                except Exception as cleanup_ex:
                    cleanup_error = cleanup_error or cleanup_ex
            if cleanup_error is not None and exc is None:
                raise cleanup_error

    async def feed_start(self, code: str, capture: CollectString) -> MontyState:
        if self._session is None:
            raise RuntimeError("Monty session is not active")
        return cast(
            MontyState,
            await _offload(
                partial(self._session.feed_start, code, print_callback=capture)
            ),
        )


async def _offload(function: Callable[..., Any], *args: Any) -> Any:
    return await anyio.to_thread.run_sync(
        partial(function, *args), abandon_on_cancel=True
    )


async def _offload_state(function: Callable[..., Any], *args: Any) -> MontyState:
    return cast(MontyState, await _offload(function, *args))


async def _offload_cleanup(function: Callable[..., Any], *args: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *args))


async def _execute_inner_tool(
    code: str,
    tool_def: ToolDef,
    arguments: dict[str, Any],
    tool_defs: list[ToolDef],
) -> Any:
    call = ToolCall(
        id=f"run_code_{uuid()}", function=tool_def.name, arguments=arguments
    )
    call.view = tool_call_view(call, tool_defs)
    event = ToolEvent(
        id=call.id,
        function=call.function,
        arguments=call.arguments,
        view=call.view,
        pending=True,
    )
    waiting_start = sample_waiting_time()
    active = sample_active()
    history = list(active.live_state.messages) if active and active.live_state else []

    def finish(
        execution: _ToolExecution,
        *,
        error: ToolCallError | None = None,
        failed: bool | None,
        agent_span_id: str | None = None,
    ) -> None:
        _finish_event(
            event,
            execution,
            error=error,
            failed=failed,
            agent_span_id=agent_span_id,
            waiting_time=sample_waiting_time() - waiting_start,
        )

    try:
        outcome = _CallOutcome()

        async def invoke() -> None:
            try:
                outcome.value = await call_tool(tool_defs, code, call, event, history)
            except BaseException as ex:
                outcome.error = ex
            finally:
                outcome.done.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(invoke)
            event._set_cancel_fn(task_group.cancel_scope.cancel)
            await outcome.done.wait()

        if event.cancelled:
            execution = _ToolExecution(result="", event_result="")
            error = ToolCallError("timeout", "Command timed out before completing.")
            finish(execution, error=error, failed=None)
            transcript().info(f"Tool call '{tool_def.name}' was cancelled by operator.")
            raise _RecoverableToolError(error.message)
        if outcome.error is not None:
            raise outcome.error

        result, messages, output, agent, agent_span_id = cast(
            tuple[ToolResult, list[Any], Any, str | None, str | None], outcome.value
        )
        if messages or output is not None or agent is not None:
            raise RuntimeError(
                f"tool {tool_def.name!r} returned an agent handoff, which run_code "
                "does not support"
            )
        execution = _limit_result(tool_def, result, tool_defs)
    except TerminateSampleError:
        finish(_ToolExecution(result="", event_result=""), failed=True)
        raise
    except _RecoverableToolError:
        raise
    except BaseException as ex:
        if not isinstance(ex, Exception):
            finish(
                _ToolExecution(result="", event_result=""),
                error=ToolCallError("cancelled", "Wrapped tool call was cancelled."),
                failed=True,
            )
            raise
        mapped = _recoverable_error(ex)
        if mapped is None:
            finish(
                _ToolExecution(result="", event_result=""),
                failed=True,
            )
            raise
        execution, error = mapped
        finish(execution, error=error, failed=None)
        raise _RecoverableToolError(error.message) from ex
    else:
        finish(
            execution,
            failed=None,
            agent_span_id=agent_span_id,
        )
        return _monty_value(execution.result)


def _limit_result(
    tool_def: ToolDef, result: ToolResult, tool_defs: list[ToolDef]
) -> _ToolExecution:
    if isinstance(
        result,
        ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
    ):
        return _ToolExecution(result=result, event_result=[result])
    if isinstance(result, list):
        return _ToolExecution(result=result, event_result=result)

    event_result = str(result)
    truncated = truncate_tool_output(
        tool_def.name,
        event_result,
        _tool_max_output(tool_defs, tool_def.name, None),
    )
    if truncated is None:
        return _ToolExecution(result=result, event_result=event_result)
    return _ToolExecution(
        result=truncated.output,
        event_result=truncated.output,
        truncated=(truncated.raw_bytes, truncated.truncated_bytes),
    )


def _recoverable_error(
    ex: Exception,
) -> tuple[_ToolExecution, ToolCallError] | None:
    if isinstance(ex, SandboxTimeoutError):
        output = ex.truncated_output or ""
        execution = _ToolExecution(result=output, event_result=output)
        return execution, ToolCallError(
            "timeout", "Command timed out before completing."
        )
    if isinstance(ex, TimeoutError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "timeout", "Command timed out before completing."
        )
    if isinstance(ex, UnicodeDecodeError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "unicode_decode", f"Error decoding bytes to {ex.encoding}: {ex.reason}"
        )
    if isinstance(ex, ValueError) and "embedded null byte" in str(ex):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "parsing",
            "An argument to the wrapped tool contained an embedded null byte.",
        )
    if isinstance(ex, SandboxUnavailableError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "sandbox_unavailable", str(ex)
        )
    if isinstance(ex, PermissionError):
        message = f"{ex.strerror or str(ex)}."
        if isinstance(ex.filename, str):
            message = f"{message} Filename '{ex.filename}'."
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "permission", message
        )
    if isinstance(ex, FileNotFoundError):
        message = (
            f"File '{ex.filename}' was not found."
            if isinstance(ex.filename, str)
            else ex.strerror or str(ex)
        )
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "file_not_found", message
        )
    if isinstance(ex, IsADirectoryError):
        message = f"{ex.strerror or str(ex)}."
        if isinstance(ex.filename, str):
            message = f"{message} Filename '{ex.filename}'."
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "is_a_directory", message
        )
    if isinstance(ex, OutputLimitExceededError):
        output = ex.truncated_output or ""
        return _ToolExecution(result=output, event_result=output), ToolCallError(
            "limit", f"The tool exceeded its output limit of {ex.limit_str}."
        )
    if isinstance(ex, LimitExceededError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "limit", f"The tool exceeded its {ex.type} limit of {ex.limit_str}."
        )
    if isinstance(ex, ToolParsingError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "parsing", ex.message
        )
    if isinstance(ex, ToolApprovalError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "approval", ex.message
        )
    if isinstance(ex, ToolError):
        return _ToolExecution(result="", event_result=""), ToolCallError(
            "unknown", ex.message
        )
    return None


def _finish_event(
    event: ToolEvent,
    execution: _ToolExecution,
    *,
    error: ToolCallError | None = None,
    failed: bool | None,
    agent_span_id: str | None = None,
    waiting_time: float,
) -> None:
    event._set_result(
        result=execution.event_result,
        truncated=execution.truncated,
        error=error,
        waiting_time=waiting_time,
        agent=None,
        failed=failed,
        message_id=None,
        agent_span_id=agent_span_id,
    )
    if event not in transcript().events:
        transcript()._event(event)
    else:
        transcript()._event_updated(event)


def _monty_value(result: ToolResult) -> Any:
    if isinstance(result, list):
        return [item.model_dump(mode="json", exclude_none=True) for item in result]
    if isinstance(
        result,
        ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
    ):
        return result.model_dump(mode="json", exclude_none=True)
    return result


def _tool_result(result: Any, printed: str) -> ToolResult:
    content = _content_result(result)
    if printed and content is not None:
        prefix = ContentText(text=printed)
        return [prefix, *content] if isinstance(content, list) else [prefix, content]
    if content is not None:
        return content
    if not printed and isinstance(result, str | int | float | bool):
        return result
    if not printed and result is None:
        return "{}"
    if printed and result is None:
        return printed
    payload = {"output": printed, "result": result} if printed else result
    try:
        return _JSON_RESULT_ADAPTER.dump_json(payload).decode()
    except (PydanticSerializationError, UnicodeDecodeError, ValueError) as ex:
        raise ToolError(
            f"The code returned a value that cannot be serialized: {ex}"
        ) from ex


def _content_result(result: Any) -> ContentResult | list[ContentResult] | None:
    if not isinstance(result, dict | list):
        return None
    try:
        return _CONTENT_RESULT_ADAPTER.validate_python(result)
    except ValidationError:
        return None


def _with_print(capture: CollectString, error: str) -> str:
    printed = capture.output.rstrip("\n")
    if not printed:
        return error
    return f"[stdout before error]\n{printed}\n[/stdout before error]\n{error}"


def _is_sandbox_panic(ex: BaseException) -> bool:
    """Identify a Rust panic surfaced by pyo3 without importing its module."""
    if type(ex).__name__ == "PanicException":
        return True
    if isinstance(ex, BaseExceptionGroup):
        return any(_is_sandbox_panic(child) for child in ex.exceptions)
    return False


def _contains_cancellation(ex: BaseException | None) -> bool:
    if ex is None:
        return False
    if isinstance(ex, anyio.get_cancelled_exc_class()):
        return True
    if isinstance(ex, BaseExceptionGroup):
        return any(_contains_cancellation(child) for child in ex.exceptions)
    return False
