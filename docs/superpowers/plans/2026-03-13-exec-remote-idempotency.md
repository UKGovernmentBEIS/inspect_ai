# Idempotent exec_remote RPCs Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add request_id-based idempotency and response caching to all exec_remote RPCs so that retries of lost responses don't cause duplicate side effects.

**Architecture:** Client generates a `shortuuid` request_id for every retryable RPC. Server caches the last response per job and deduplicates start requests via a separate map. `_start()` and `write_stdin()` become safely retryable.

**Tech Stack:** shortuuid (already a project dependency), pydantic, tenacity

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/tool_types.py` | Add `request_id` field to all param types |
| Modify | `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_controller.py` | Add dedup map, response cache, `_cleanup_job()` helper |
| Modify | `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/json_rpc_methods.py` | Pass `request_id` to controller methods |
| Modify | `src/inspect_ai/util/_sandbox/exec_remote.py` | Generate `request_id` in `_rpc()`, enable retry on `_start()` and `write_stdin()` |
| Modify | `src/inspect_sandbox_tools/tests/test_exec_remote_controller.py` | Add server-side idempotency tests |
| Modify | `tests/util/sandbox/test_exec_remote.py` | Add host-side request_id injection tests |

---

## Chunk 1: Server-side changes

### Task 1: Add `request_id` to all param types

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/tool_types.py`

- [ ] **Step 1: Add `request_id: str | None = None` to `SubmitParams`**

In `tool_types.py`, add the field to `SubmitParams` before `model_config`:

```python
class SubmitParams(BaseModel):
    """Parameters for exec_remote_start."""

    request_id: str | None = None
    command: str
    input: str | None = None
    """Standard input to send to the command (as a string)."""
    stdin_open: bool = False
    """If True, keep stdin open after writing initial input for later writes."""
    env: dict[str, str] | None = None
    """Additional environment variables (merged with the current environment)."""
    cwd: str | None = None
    """Working directory for command execution."""
    model_config = {"extra": "forbid"}
```

- [ ] **Step 2: Add `request_id: str | None = None` to `PollParams`, `KillParams`, `WriteStdinParams`, `CloseStdinParams`**

Add `request_id: str | None = None` as the first field (after docstring, before existing fields) in each of:

```python
class PollParams(BaseModel):
    """Parameters for exec_remote_poll."""

    request_id: str | None = None
    pid: int
    model_config = {"extra": "forbid"}


class KillParams(BaseModel):
    """Parameters for exec_remote_kill."""

    request_id: str | None = None
    pid: int
    model_config = {"extra": "forbid"}


class WriteStdinParams(BaseModel):
    """Parameters for exec_remote_write_stdin."""

    request_id: str | None = None
    pid: int
    data: str
    model_config = {"extra": "forbid"}


class CloseStdinParams(BaseModel):
    """Parameters for exec_remote_close_stdin."""

    request_id: str | None = None
    pid: int
    model_config = {"extra": "forbid"}
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py -v`
Expected: All existing tests PASS (they don't send `request_id`, so `None` default keeps behavior identical).

- [ ] **Step 4: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/tool_types.py
git commit -m "feat(exec_remote): add optional request_id to all RPC param types"
```

---

### Task 2: Add response cache and start dedup to Controller

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_controller.py`
- Test: `src/inspect_sandbox_tools/tests/test_exec_remote_controller.py`

- [ ] **Step 1: Write failing tests for start dedup**

Add to `test_exec_remote_controller.py`:

```python
class TestControllerStartDedup:
    """Verify that submit() with the same request_id returns the same PID."""

    @pytest.mark.asyncio
    async def test_duplicate_start_returns_same_pid(self) -> None:
        controller = Controller()

        # First submit creates a job
        job = MagicMock()
        job.pid = 100
        job.cleanup = AsyncMock()

        with patch.object(Job, "create", new_callable=AsyncMock, return_value=job):
            pid1 = await controller.submit("echo hi", request_id="req-abc")
            pid2 = await controller.submit("echo hi", request_id="req-abc")

        assert pid1 == pid2 == 100
        # Job.create should only be called once
        Job.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_request_ids_create_different_jobs(self) -> None:
        controller = Controller()

        job1 = MagicMock()
        job1.pid = 100
        job1.cleanup = AsyncMock()
        job2 = MagicMock()
        job2.pid = 200
        job2.cleanup = AsyncMock()

        with patch.object(
            Job, "create", new_callable=AsyncMock, side_effect=[job1, job2]
        ):
            pid1 = await controller.submit("echo 1", request_id="req-1")
            pid2 = await controller.submit("echo 2", request_id="req-2")

        assert pid1 == 100
        assert pid2 == 200

    @pytest.mark.asyncio
    async def test_no_request_id_skips_dedup(self) -> None:
        controller = Controller()

        job1 = MagicMock()
        job1.pid = 100
        job1.cleanup = AsyncMock()
        job2 = MagicMock()
        job2.pid = 200
        job2.cleanup = AsyncMock()

        with patch.object(
            Job, "create", new_callable=AsyncMock, side_effect=[job1, job2]
        ):
            pid1 = await controller.submit("echo hi")
            pid2 = await controller.submit("echo hi")

        assert pid1 == 100
        assert pid2 == 200
```

Add the needed import at the top of the test file:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from inspect_sandbox_tools._remote_tools._exec_remote._job import Job
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py::TestControllerStartDedup -v`
Expected: FAIL (submit() doesn't accept `request_id` yet).

- [ ] **Step 3: Write failing tests for response cache on poll**

Add to `test_exec_remote_controller.py`:

```python
class TestControllerResponseCache:
    """Verify response caching for retried RPCs."""

    @pytest.mark.asyncio
    async def test_poll_cache_returns_same_response(self) -> None:
        """Retrying poll with same request_id returns cached response."""
        controller = Controller()
        pid = 42

        completed_result = PollResult(
            state="completed", exit_code=0, stdout="hello", stderr=""
        )

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.poll = AsyncMock(return_value=completed_result)

        controller._jobs[pid] = job

        # First poll executes and caches
        result1 = await controller.poll(pid, request_id="poll-1")
        # Second poll with same request_id returns cache
        result2 = await controller.poll(pid, request_id="poll-1")

        assert result1 == result2
        assert result1.stdout == "hello"
        # job.poll should only be called once
        job.poll.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_poll_cache_miss_on_different_request_id(self) -> None:
        """Different request_id executes fresh poll."""
        controller = Controller()
        pid = 42

        running1 = PollResult(state="running", stdout="out1", stderr="")
        running2 = PollResult(state="running", stdout="out2", stderr="")

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.poll = AsyncMock(side_effect=[running1, running2])

        controller._jobs[pid] = job

        result1 = await controller.poll(pid, request_id="poll-1")
        result2 = await controller.poll(pid, request_id="poll-2")

        assert result1.stdout == "out1"
        assert result2.stdout == "out2"
        assert job.poll.await_count == 2

    @pytest.mark.asyncio
    async def test_terminal_poll_cached_after_cleanup(self) -> None:
        """Terminal poll response is still available after job cleanup."""
        controller = Controller()
        pid = 42

        completed = PollResult(
            state="completed", exit_code=0, stdout="done", stderr=""
        )

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.poll = AsyncMock(return_value=completed)

        controller._jobs[pid] = job

        result1 = await controller.poll(pid, request_id="poll-term")
        # Job is cleaned up now
        assert pid not in controller._jobs
        # Retry still returns cached response
        result2 = await controller.poll(pid, request_id="poll-term")
        assert result2.stdout == "done"
        assert result2.state == "completed"

    @pytest.mark.asyncio
    async def test_no_request_id_skips_cache(self) -> None:
        """Without request_id, every call executes fresh."""
        controller = Controller()
        pid = 42

        running1 = PollResult(state="running", stdout="out1", stderr="")
        running2 = PollResult(state="running", stdout="out2", stderr="")

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.poll = AsyncMock(side_effect=[running1, running2])

        controller._jobs[pid] = job

        result1 = await controller.poll(pid)
        result2 = await controller.poll(pid)

        assert result1.stdout == "out1"
        assert result2.stdout == "out2"

    @pytest.mark.asyncio
    async def test_kill_cache_returns_same_response(self) -> None:
        """Retrying kill with same request_id returns cached response."""
        controller = Controller()
        pid = 42

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.kill = AsyncMock(return_value=("killed-out", "killed-err"))

        controller._jobs[pid] = job

        result1 = await controller.kill(pid, request_id="kill-1")
        # Job cleaned up, but cache persists
        assert pid not in controller._jobs
        result2 = await controller.kill(pid, request_id="kill-1")

        assert result1.stdout == "killed-out"
        assert result2.stdout == "killed-out"
        job.kill.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_stdin_cache(self) -> None:
        """Retrying write_stdin with same request_id returns cached response."""
        controller = Controller()
        pid = 42

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.write_stdin = AsyncMock(return_value=("ws-out", ""))

        controller._jobs[pid] = job

        result1 = await controller.write_stdin(pid, "data", request_id="ws-1")
        result2 = await controller.write_stdin(pid, "data", request_id="ws-1")

        assert result1.stdout == "ws-out"
        assert result2.stdout == "ws-out"
        job.write_stdin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_stdin_cache(self) -> None:
        """Retrying close_stdin with same request_id returns cached response."""
        controller = Controller()
        pid = 42

        job = MagicMock()
        job.pid = pid
        job.cleanup = AsyncMock()
        job.close_stdin = AsyncMock(return_value=("cs-out", ""))

        controller._jobs[pid] = job

        result1 = await controller.close_stdin(pid, request_id="cs-1")
        result2 = await controller.close_stdin(pid, request_id="cs-1")

        assert result1.stdout == "cs-out"
        assert result2.stdout == "cs-out"
        job.close_stdin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pid_reuse_overwrites_stale_cache(self) -> None:
        """When a PID is reused by a new job, fresh request_ids don't match stale cache."""
        controller = Controller()
        pid = 42

        # First job completes, leaving a stale _last_response entry
        job1 = MagicMock()
        job1.pid = pid
        job1.cleanup = AsyncMock()
        job1.poll = AsyncMock(
            return_value=PollResult(
                state="completed", exit_code=0, stdout="old", stderr=""
            )
        )
        controller._jobs[pid] = job1
        await controller.poll(pid, request_id="old-req")
        assert pid not in controller._jobs  # cleaned up

        # New job reuses the same PID
        job2 = MagicMock()
        job2.pid = pid
        job2.cleanup = AsyncMock()
        job2.poll = AsyncMock(
            return_value=PollResult(
                state="running", stdout="new", stderr=""
            )
        )
        controller._jobs[pid] = job2

        # Fresh request_id should NOT match stale cache
        result = await controller.poll(pid, request_id="new-req")
        assert result.stdout == "new"
        assert result.state == "running"
        job2.poll.assert_awaited_once()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py::TestControllerResponseCache -v`
Expected: FAIL (methods don't accept `request_id` yet).

- [ ] **Step 5: Implement Controller changes**

Replace the entire `_controller.py` with:

```python
from inspect_sandbox_tools._util.common_types import ToolException

from ._job import Job
from .tool_types import CloseStdinResult, KillResult, PollResult, WriteStdinResult


class Controller:
    """Simple job registry keyed by PID.

    Unlike bash_session's SessionController, exec_remote uses PIDs as natural
    unique identifiers - no session naming or multiplexing needed.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        # Start dedup: request_id -> pid (prevents duplicate process spawning)
        self._start_request_ids: dict[str, int] = {}
        self._pid_to_start_request_id: dict[int, str] = {}
        # Response cache: pid -> (request_id, response)
        # Only the last response per job is cached. This is safe because the
        # host sends RPCs sequentially per process (never concurrent).
        self._last_response: dict[int, tuple[str, object]] = {}

    async def submit(
        self,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        request_id: str | None = None,
    ) -> int:
        """Create a new job and return its PID.

        If request_id is provided and matches a previous submit, returns
        the existing PID without creating a new process.
        """
        if request_id and request_id in self._start_request_ids:
            return self._start_request_ids[request_id]

        job = await Job.create(
            command, input=input, stdin_open=stdin_open, env=env, cwd=cwd
        )
        self._jobs[job.pid] = job
        if request_id:
            self._start_request_ids[request_id] = job.pid
            self._pid_to_start_request_id[job.pid] = request_id
        return job.pid

    async def poll(
        self, pid: int, request_id: str | None = None
    ) -> PollResult:
        """Get job state and incremental output. Auto-cleanup on terminal state."""
        if request_id and pid in self._last_response:
            cached_rid, cached_response = self._last_response[pid]
            if cached_rid == request_id:
                return cached_response  # type: ignore[return-value]

        job = self._get_job(pid)
        result = await job.poll()

        if request_id:
            self._last_response[pid] = (request_id, result)

        # Auto-cleanup after terminal state. Use pop (inside _cleanup_job)
        # to avoid KeyError if a concurrent kill() already removed the job.
        if result.state in ("completed", "killed"):
            await self._cleanup_job(pid)

        return result

    async def kill(
        self, pid: int, request_id: str | None = None
    ) -> KillResult:
        """Terminate a running job and return any remaining buffered output."""
        if request_id and pid in self._last_response:
            cached_rid, cached_response = self._last_response[pid]
            if cached_rid == request_id:
                return cached_response  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.kill()
        result = KillResult(stdout=stdout, stderr=stderr)

        if request_id:
            self._last_response[pid] = (request_id, result)

        # Use pop (inside _cleanup_job) to avoid KeyError if a concurrent
        # poll() already removed the job between our await and here.
        await self._cleanup_job(pid)
        return result

    async def write_stdin(
        self, pid: int, data: str, request_id: str | None = None
    ) -> WriteStdinResult:
        """Write data to stdin of a running job and return buffered output."""
        if request_id and pid in self._last_response:
            cached_rid, cached_response = self._last_response[pid]
            if cached_rid == request_id:
                return cached_response  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.write_stdin(data)
        result = WriteStdinResult(stdout=stdout, stderr=stderr)

        if request_id:
            self._last_response[pid] = (request_id, result)

        return result

    async def close_stdin(
        self, pid: int, request_id: str | None = None
    ) -> CloseStdinResult:
        """Close stdin of a running job and return buffered output."""
        if request_id and pid in self._last_response:
            cached_rid, cached_response = self._last_response[pid]
            if cached_rid == request_id:
                return cached_response  # type: ignore[return-value]

        job = self._get_job(pid)
        stdout, stderr = await job.close_stdin()
        result = CloseStdinResult(stdout=stdout, stderr=stderr)

        if request_id:
            self._last_response[pid] = (request_id, result)

        return result

    def _get_job(self, pid: int) -> Job:
        """Get job by PID or raise error."""
        job = self._jobs.get(pid)
        if job is None:
            raise ToolException(f"No job found with pid {pid}")
        return job

    async def _cleanup_job(self, pid: int) -> None:
        """Remove job from registry and clean up start dedup map.

        Note: _last_response[pid] is intentionally kept so retries of the
        terminal poll/kill can still get the cached response.
        """
        job = self._jobs.pop(pid, None)
        if job is not None:
            await job.cleanup()
        rid = self._pid_to_start_request_id.pop(pid, None)
        if rid:
            self._start_request_ids.pop(rid, None)
```

- [ ] **Step 6: Run all controller tests**

Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_controller.py src/inspect_sandbox_tools/tests/test_exec_remote_controller.py
git commit -m "feat(exec_remote): add start dedup and response caching to Controller"
```

---

### Task 3: Pass `request_id` through JSON-RPC methods

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/json_rpc_methods.py`

- [ ] **Step 1: Add `request_id=params.request_id` to all controller calls**

Update `json_rpc_methods.py`:

```python
from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .tool_types import (
    CloseStdinParams,
    CloseStdinResult,
    KillParams,
    KillResult,
    PollParams,
    PollResult,
    SubmitParams,
    SubmitResult,
    WriteStdinParams,
    WriteStdinResult,
)

controller = Controller()


@validated_json_rpc_method(SubmitParams)
async def exec_remote_start(params: SubmitParams) -> SubmitResult:
    """Submit a command for async execution. Returns the PID."""
    pid = await controller.submit(
        params.command,
        input=params.input,
        stdin_open=params.stdin_open,
        env=params.env,
        cwd=params.cwd,
        request_id=params.request_id,
    )
    return SubmitResult(pid=pid)


@validated_json_rpc_method(PollParams)
async def exec_remote_poll(params: PollParams) -> PollResult:
    """Poll job state and get incremental output."""
    return await controller.poll(params.pid, request_id=params.request_id)


@validated_json_rpc_method(KillParams)
async def exec_remote_kill(params: KillParams) -> KillResult:
    """Kill a running job."""
    return await controller.kill(params.pid, request_id=params.request_id)


@validated_json_rpc_method(WriteStdinParams)
async def exec_remote_write_stdin(params: WriteStdinParams) -> WriteStdinResult:
    """Write data to stdin of a running job."""
    return await controller.write_stdin(
        params.pid, params.data, request_id=params.request_id
    )


@validated_json_rpc_method(CloseStdinParams)
async def exec_remote_close_stdin(params: CloseStdinParams) -> CloseStdinResult:
    """Close stdin of a running job to signal EOF."""
    return await controller.close_stdin(params.pid, request_id=params.request_id)
```

- [ ] **Step 2: Run all controller tests to verify no regressions**

Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/json_rpc_methods.py
git commit -m "feat(exec_remote): pass request_id through JSON-RPC methods to controller"
```

---

## Chunk 2: Host-side changes

### Task 4: Generate `request_id` in `_rpc()` and enable retry on `_start()` and `write_stdin()`

**Files:**
- Modify: `src/inspect_ai/util/_sandbox/exec_remote.py`
- Test: `tests/util/sandbox/test_exec_remote.py`

- [ ] **Step 1: Write failing test for request_id injection**

Add these imports to the top of `tests/util/sandbox/test_exec_remote.py` (alongside existing imports):

```python
from inspect_ai.util._sandbox.exec_remote import (
    _StartResult,
    _PollResult,
)
```

Add the test class at the end of the file (before `TestRpcRetry`):

```python
class TestRequestIdInjection:
    """Verify that _rpc() injects request_id when retry_policy is set."""

    async def test_request_id_added_when_retry_policy_set(self) -> None:
        """When retry_policy is provided, params should include a request_id."""
        sandbox = _make_sandbox_mock([_poll_response(state="running")])
        proc = ExecRemoteProcess(
            sandbox, ["echo", "hi"], ExecRemoteCommonOptions(), 5.0
        )

        captured_params: dict[str, object] = {}

        async def capture_params(**kwargs: Any) -> Any:
            captured_params.update(kwargs.get("params", {}))
            return _PollResult(state="running", stdout="", stderr="")

        with patch(f"{_RETRY_MOD}.exec_model_request", side_effect=capture_params):
            with patch(f"{_RETRY_MOD}.POLL_RETRY", _NO_WAIT_POLL):
                await proc._rpc(
                    "exec_remote_poll",
                    {"pid": 1},
                    _PollResult,
                    retry_policy=POLL_RETRY,
                )

        assert "request_id" in captured_params
        assert isinstance(captured_params["request_id"], str)
        assert len(captured_params["request_id"]) > 0

    async def test_no_request_id_without_retry_policy(self) -> None:
        """When no retry_policy, params should NOT include request_id."""
        sandbox = _make_sandbox_mock([_start_response()])
        proc = ExecRemoteProcess(
            sandbox, ["echo", "hi"], ExecRemoteCommonOptions(), 5.0
        )

        captured_params: dict[str, object] = {}

        async def capture_params(**kwargs: Any) -> Any:
            captured_params.update(kwargs.get("params", {}))
            return _StartResult(pid=1)

        with patch(f"{_RETRY_MOD}.exec_model_request", side_effect=capture_params):
            await proc._rpc(
                "exec_remote_start",
                {"command": "echo hi"},
                _StartResult,
            )

        assert "request_id" not in captured_params

    async def test_request_id_is_unique_per_call(self) -> None:
        """Each _rpc() call should generate a fresh request_id."""
        sandbox = _make_sandbox_mock([
            _poll_response(state="running"),
            _poll_response(state="running"),
        ])
        proc = ExecRemoteProcess(
            sandbox, ["echo", "hi"], ExecRemoteCommonOptions(), 5.0
        )

        request_ids: list[str] = []

        async def capture_request_id(**kwargs: Any) -> Any:
            params = kwargs.get("params", {})
            if "request_id" in params:
                request_ids.append(params["request_id"])
            return _PollResult(state="running", stdout="", stderr="")

        with patch(f"{_RETRY_MOD}.exec_model_request", side_effect=capture_request_id):
            with patch(f"{_RETRY_MOD}.POLL_RETRY", _NO_WAIT_POLL):
                await proc._rpc(
                    "exec_remote_poll",
                    {"pid": 1},
                    _PollResult,
                    retry_policy=POLL_RETRY,
                )
                await proc._rpc(
                    "exec_remote_poll",
                    {"pid": 1},
                    _PollResult,
                    retry_policy=POLL_RETRY,
                )

        assert len(request_ids) == 2
        assert request_ids[0] != request_ids[1]
```

Note: The test file uses `_RETRY_MOD = "inspect_ai.util._sandbox.exec_remote"` which is both the retry constants module and the module containing `exec_model_request`. Use `_RETRY_MOD` for all patches.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/util/sandbox/test_exec_remote.py::TestRequestIdInjection -v`
Expected: FAIL (`request_id` not in captured params).

- [ ] **Step 3: Write failing tests for `_start()` and `write_stdin()` retry**

The existing `_make_flaky_sandbox` helper always succeeds on call 1 (designed for start-then-fail patterns). For testing start/write_stdin retry, we need a custom mock where the *first* call fails. Add to `tests/util/sandbox/test_exec_remote.py`:

```python
def _make_initially_flaky_sandbox(
    fail_count: int, success_response: str
) -> tuple[AsyncMock, list[int]]:
    """Create a sandbox that fails `fail_count` times, then succeeds.

    Unlike _make_flaky_sandbox, this fails from the very first call
    (no guaranteed-success first call). Used for testing retry on _start()
    and write_stdin().
    """
    call_counts = [0]

    async def fake_exec(*args: Any, **kwargs: Any) -> ExecResult[str]:
        call_counts[0] += 1
        if call_counts[0] <= fail_count:
            raise ConnectionError("WebSocket connection lost")
        return ExecResult(
            success=True, returncode=0, stdout=success_response, stderr=""
        )

    sandbox = AsyncMock()
    sandbox.default_polling_interval.return_value = 5
    sandbox.no_events = _no_events_context
    sandbox.exec = AsyncMock(side_effect=fake_exec)
    return sandbox, call_counts


class TestStartRetry:
    """Verify that _start() retries transient failures."""

    async def test_start_retries_on_failure(self) -> None:
        sandbox, calls = _make_initially_flaky_sandbox(
            fail_count=2, success_response=_start_response(pid=42)
        )
        proc = ExecRemoteProcess(
            sandbox,
            ["echo", "hi"],
            ExecRemoteCommonOptions(),
            5.0,
        )
        with patch(f"{_RETRY_MOD}.CLEANUP_RETRY", _NO_WAIT_CLEANUP):
            await proc._start()

        assert proc._pid == 42
        assert calls[0] == 3  # 2 failures + 1 success


class TestWriteStdinRetry:
    """Verify that write_stdin() retries transient failures."""

    async def test_write_stdin_retries_on_failure(self) -> None:
        sandbox, calls = _make_initially_flaky_sandbox(
            fail_count=2,
            success_response=_write_stdin_response(),
        )
        proc = ExecRemoteProcess(
            sandbox,
            ["cat"],
            ExecRemoteStreamingOptions(stdin_open=True),
            5.0,
        )
        proc._pid = 42  # Skip _start(), pretend already started

        with patch(f"{_RETRY_MOD}.CLEANUP_RETRY", _NO_WAIT_CLEANUP):
            await proc.write_stdin("hello\n")

        assert calls[0] == 3  # 2 failures + 1 success
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/util/sandbox/test_exec_remote.py::TestStartRetry tests/util/sandbox/test_exec_remote.py::TestWriteStdinRetry -v`
Expected: FAIL (start and write_stdin don't retry — exceptions propagate on first failure).

- [ ] **Step 7: Implement `_rpc()` request_id injection**

In `exec_remote.py`, modify the `_rpc()` method to inject `request_id` when `retry_policy` is set:

```python
async def _rpc(
    self,
    method: str,
    params: dict[str, object],
    result_type: type[T],
    retry_policy: RetryPolicy | None = None,
) -> T:
    """Make an RPC call to the sandbox.

    Args:
        method: JSON-RPC method name.
        params: JSON-RPC parameters.
        result_type: Pydantic model to parse the result into.
        retry_policy: If provided, retries transient failures with
            exponential backoff. Also injects a request_id for
            server-side idempotency.
    """
    if retry_policy is not None:
        import shortuuid

        params = {**params, "request_id": shortuuid.uuid()}

    async def call() -> T:
        return await exec_model_request(
            method=method,
            params=params,
            result_type=result_type,
            transport=self._transport,
            error_mapper=GenericJSONRPCErrorMapper,
            timeout=RPC_TIMEOUT,
            user=self._options.user,
            concurrency=self._options.concurrency,
        )

    if retry_policy is None:
        return await call()

    retrying = retry(
        wait=retry_policy.wait,
        stop=retry_policy.stop,
        retry=retry_if_exception(lambda e: isinstance(e, Exception)),
        before_sleep=_log_retry(method),
    )
    return await retrying(call)()
```

- [ ] **Step 8: Enable retry on `_start()`**

In `exec_remote.py`, modify `_start()` to pass `retry_policy=CLEANUP_RETRY`:

```python
async def _start(self) -> None:
    """Submit the job to the sandbox."""
    # Build params, converting bytes input to string if needed
    params: dict[str, object] = {"command": shlex.join(self._cmd)}
    if self._options.input is not None:
        if isinstance(self._options.input, bytes):
            params["input"] = self._options.input.decode("utf-8")
        else:
            params["input"] = self._options.input
    if (
        isinstance(self._options, ExecRemoteStreamingOptions)
        and self._options.stdin_open
    ):
        params["stdin_open"] = True
    if self._options.env:
        params["env"] = self._options.env
    if self._options.cwd:
        params["cwd"] = self._options.cwd

    result = await self._rpc(
        "exec_remote_start", params, _StartResult, retry_policy=CLEANUP_RETRY
    )
    self._pid = result.pid
```

- [ ] **Step 9: Enable retry on `write_stdin()`**

In `exec_remote.py`, modify `write_stdin()` to pass `retry_policy=CLEANUP_RETRY`:

```python
result = await self._rpc(
    "exec_remote_write_stdin",
    {"pid": self._pid, "data": data},
    _WriteStdinResult,
    retry_policy=CLEANUP_RETRY,
)
```

- [ ] **Step 10: Run all test classes**

Run: `pytest tests/util/sandbox/test_exec_remote.py -v`
Expected: ALL PASS

- [ ] **Step 11: Run linting and type checking**

Run: `uv run ruff check --fix src/inspect_ai/util/_sandbox/exec_remote.py src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`
Run: `uv run ruff format src/inspect_ai/util/_sandbox/exec_remote.py src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`

- [ ] **Step 12: Commit**

```bash
git add src/inspect_ai/util/_sandbox/exec_remote.py tests/util/sandbox/test_exec_remote.py
git commit -m "feat(exec_remote): inject request_id in _rpc(), enable retry on _start() and write_stdin()"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run all exec_remote tests end-to-end**

Run: `pytest tests/util/sandbox/test_exec_remote.py -v`
Run: `cd src/inspect_sandbox_tools && uv run pytest tests/test_exec_remote_controller.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run linting and type checking on all changed files**

Run: `uv run ruff check src/inspect_ai/util/_sandbox/exec_remote.py src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`
Run: `uv run ruff format --check src/inspect_ai/util/_sandbox/exec_remote.py src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`

Expected: Clean output, no issues.
