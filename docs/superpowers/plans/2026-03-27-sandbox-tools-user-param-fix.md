# Sandbox Tools User Parameter Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `bash_session(user=...)` and `text_editor(user=...)` to work with the root-only CLI binary by routing user-switching through RPC params instead of the transport layer.

**Architecture:** Follow the exec_remote pattern — each tool passes `sandbox._tools_user` as the CLI execution user (transport extra arg) and includes the actual target user in the RPC params. Server-side / CLI-side code performs setuid before running the actual operation.

**Tech Stack:** Python, Pydantic, asyncio, os/pwd (setuid)

---

### Task 1: Create shared user-switching utility

**Files:**
- Create: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/user_switch.py`

- [ ] **Step 1: Create the shared user_switch module**

```python
import os
import pwd
from collections.abc import Callable


def is_current_user(username: str) -> bool:
    """Check if the given username matches the current process user."""
    try:
        return pwd.getpwnam(username).pw_uid == os.getuid()
    except KeyError:
        return False


def set_oom_score_adj() -> None:
    """Set oom_score_adj to make this process the preferred OOM-kill target."""
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def switch_user(username: str) -> None:
    """Switch the current process to the given user via setuid/setgid/initgroups.

    This is irreversible and should only be used in short-lived CLI processes.
    Raises RuntimeError if the user doesn't exist or permission is denied.
    """
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        raise RuntimeError(f"User {username!r} not found in /etc/passwd")
    try:
        os.initgroups(username, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
    except OSError:
        raise RuntimeError(
            f"Permission denied switching to user {username!r} "
            "(process may lack CAP_SETUID/CAP_SETGID)"
        )


def make_preexec(username: str | None) -> Callable[[], None]:
    """Build a preexec_fn that sets OOM score and optionally switches user.

    Args:
        username: If provided, switch to this user via setuid/setgid/initgroups.
            Requires the current process to be running as root.
    """

    def _preexec() -> None:
        set_oom_score_adj()
        if username is not None:
            try:
                pw = pwd.getpwnam(username)
            except KeyError:
                os.write(
                    2,
                    f"sandbox-tools: user {username!r} not found in /etc/passwd\n".encode(),
                )
                os._exit(1)
            try:
                os.initgroups(username, pw.pw_gid)
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)
            except OSError:
                os.write(
                    2,
                    f"sandbox-tools: permission denied switching to user {username!r} (server may lack CAP_SETUID/CAP_SETGID)\n".encode(),
                )
                os._exit(1)

    return _preexec


def get_home_dir(username: str) -> str:
    """Get the home directory for a user from /etc/passwd, defaulting to '/'."""
    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError:
        return "/"
```

- [ ] **Step 2: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/user_switch.py
git commit -m "refactor: extract shared user-switching utility from exec_remote"
```

---

### Task 2: Update exec_remote Job to use shared utility

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_job.py`

- [ ] **Step 1: Replace local functions with shared imports**

Replace the imports and the three local functions (`_set_oom_score_adj`, `_is_current_user`, `_make_preexec`) with imports from the shared module. Keep the rest of the file unchanged.

Replace lines 1-82:

```python
import asyncio
import os
import pwd
import signal
from asyncio.subprocess import Process as AsyncIOProcess
from collections.abc import Callable
from typing import Literal, NamedTuple

from inspect_sandbox_tools._util.common_types import ToolException
from inspect_sandbox_tools._util.user_switch import (
    get_home_dir,
    is_current_user,
    make_preexec,
)

from ._acked_chunk_buffer import AckedChunkBuffer
from ._output_buffer import BoundedByteBuffer, DecodingBuffer
from .tool_types import PollResult


class OutputChunk(NamedTuple):
    """Sequence number and incremental stdout/stderr from a job operation."""

    seq: int
    stdout: str
    stderr: str


_BACKPRESSURE_BUFFER_SIZE = 100 * 1024 * 1024  # 100 MiB
_MAX_POLL_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MiB per poll response
```

Then update the `Job.create` method references:
- `_is_current_user(user)` → `is_current_user(user)`
- `_make_preexec(user)` → `make_preexec(user)`
- The `pwd.getpwnam(user).pw_dir` block (lines 138-141) → `get_home_dir(user)`

The updated `Job.create` (only the parts that change):

```python
    @classmethod
    async def create(
        cls,
        command: str,
        input: str | None = None,
        stdin_open: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        user: str | None = None,
        can_switch_user: bool = False,
    ) -> "Job":
        """Create and start a new Job for the given command.
        ...
        """
        # If the requested user matches the current process user, no setuid needed
        if user is not None and is_current_user(user):
            user = None
        if user is not None and not can_switch_user:
            raise ToolException(
                f"Cannot switch to user {user!r}: server is not running as root"
            )

        # Use stdin=PIPE if we have input to send or if stdin should stay open
        stdin = asyncio.subprocess.PIPE if (input is not None or stdin_open) else None

        # Merge additional env vars with current environment if provided.
        # When switching user, set HOME from /etc/passwd to match docker exec --user.
        subprocess_env: dict[str, str] | None = {**os.environ, **env} if env else None
        if user is not None:
            if subprocess_env is None:
                subprocess_env = {**os.environ}
            subprocess_env["HOME"] = get_home_dir(user)

        process = await asyncio.create_subprocess_shell(
            command,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=subprocess_env,
            cwd=cwd,
            preexec_fn=make_preexec(user),
        )
        # ... rest unchanged
```

- [ ] **Step 2: Run existing exec_remote tests to check for regressions**

Run: `uv run pytest tests/tools/sandbox_tools_utils/test_sandbox_tools.py::test_bash_session_root -v --runslow`
Expected: PASS (this test doesn't use `user=` so is unaffected by our change)

- [ ] **Step 3: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_job.py
git commit -m "refactor: use shared user_switch module in exec_remote Job"
```

---

### Task 3: Add user support to server-side bash_session

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/tool_types.py`
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/json_rpc_methods.py`
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_controller.py`
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_session.py`
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_process.py`

- [ ] **Step 1: Add NewSessionParams to tool_types.py**

Add a new params model at the end of the file (before the type aliases):

```python
class NewSessionParams(BaseModel):
    """Parameters for bash_session_new_session."""

    user: str | None = None
    """User to run the bash session as (requires server running as root)."""
    model_config = {"extra": "forbid"}
```

- [ ] **Step 2: Update Process.create() to accept user and do setuid**

Replace the full `_process.py` contents of the `Process.create` method:

```python
import asyncio
import os
import pwd
import re
from asyncio.subprocess import Process as AsyncIOProcess

from ..._util.pseudo_terminal import PseudoTerminal, PseudoTerminalIO
from ..._util.timeout_event import TimeoutEvent
from ..._util.user_switch import get_home_dir, make_preexec
from .tool_types import InteractResult


class Process:
    @classmethod
    async def create(cls, user: str | None = None) -> "Process":
        pty = await PseudoTerminal.create()

        # When switching user, set HOME from /etc/passwd to match docker exec --user.
        env = {**os.environ, "TERM": "dumb"}
        if user is not None:
            env["HOME"] = get_home_dir(user)

        return cls(
            await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-i",
                stdin=pty.subprocess_fd,
                stdout=pty.subprocess_fd,
                stderr=pty.subprocess_fd,
                env=env,
                start_new_session=True,
                preexec_fn=make_preexec(user),
            ),
            pty,
        )
```

The rest of `_process.py` (from `__init__` onwards) stays unchanged.

- [ ] **Step 3: Update Session.create() to accept and forward user**

In `_session.py`, change:

```python
class Session:
    @classmethod
    async def create(cls, user: str | None = None) -> "Session":
        return cls(await Process.create(user=user))
```

And in the `restart` method, pass user so restarted sessions keep the same user:

```python
    def __init__(self, process: Process, user: str | None = None) -> None:
        self._process = process
        self._user = user

    @classmethod
    async def create(cls, user: str | None = None) -> "Session":
        return cls(await Process.create(user=user), user=user)

    async def restart(self, timeout: int = 30) -> BashRestartResult:
        _, new_process = await asyncio.gather(
            self._process.terminate(timeout=timeout),
            Process.create(user=self._user),
        )
        self._process = new_process
        return "shell restarted successfully"
```

- [ ] **Step 4: Update Controller.new_session() to accept and forward user**

In `_controller.py`:

```python
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
        # If the requested user matches the current process user, no setuid needed
        if user is not None and is_current_user(user):
            user = None
        if user is not None and not can_switch_user:
            raise ToolException(
                f"Cannot switch to user {user!r}: server is not running as root"
            )
        return await self.create_new_session(
            DEFAULT_SESSION_NAME, lambda: Session.create(user=user)
        )
```

Note: `create_new_session` takes a factory callable. Check the signature:

The current call is `Session.create` (an unbound classmethod). We need to change it to a lambda that passes user. Let me check `SessionController.create_new_session`:

```python
# In session_controller.py, create_new_session likely takes a callable that returns a session
```

- [ ] **Step 5: Check SessionController.create_new_session signature**

Read `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/session_controller.py` to verify the factory signature. The current call is:

```python
await self.create_new_session(DEFAULT_SESSION_NAME, Session.create)
```

Where `Session.create` is `async def create(cls) -> "Session"`. The factory is a zero-arg async callable. With the user parameter, we pass a lambda:

```python
await self.create_new_session(
    DEFAULT_SESSION_NAME, lambda: Session.create(user=user)
)
```

This works because `Session.create(user=user)` returns a coroutine, and `create_new_session` awaits the factory result.

- [ ] **Step 6: Update json_rpc_methods.py to extract user and pass to controller**

```python
import os

from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .tool_types import (
    BashParams,
    BashRestartResult,
    InteractParams,
    InteractResult,
    NewSessionParams,
    NewSessionResult,
    RestartParams,
)

controller = Controller()
_can_switch_user = os.getuid() == 0


@validated_json_rpc_method(NewSessionParams)
async def bash_session_new_session(params: NewSessionParams) -> NewSessionResult:
    return NewSessionResult(
        session_name=await controller.new_session(
            user=params.user, can_switch_user=_can_switch_user
        )
    )


@validated_json_rpc_method(BashParams)
async def bash_session(
    params: BashParams,
) -> InteractResult | BashRestartResult:
    match params.root:
        case InteractParams(
            session_name=session_name,
            input=input_text,
            wait_for_output=wait_for_output,
            idle_timeout=idle_timeout,
        ):
            return await controller.interact(
                session_name, input_text, wait_for_output, idle_timeout
            )
        case RestartParams(session_name=session_name):
            return await controller.restart(session_name)
```

- [ ] **Step 7: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/
git commit -m "feat: add user-switching support to server-side bash_session via setuid"
```

---

### Task 4: Add user support to CLI for in-process tools (text_editor)

**Files:**
- Modify: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_cli/main.py`

- [ ] **Step 1: Update `_exec()` to handle `_run_as_user` param**

The `_exec` function needs to:
1. Parse the request JSON
2. Extract and remove `_run_as_user` from params
3. For in-process tools: call `switch_user()` before dispatching
4. For remote tools: leave `_run_as_user` in params (server handles it via its own param models)

Wait — for remote tools (bash_session), we're passing `user` as a proper field in `NewSessionParams`. So the host-side tool will put it in params as `user`, not `_run_as_user`. The server validates it via Pydantic. No stripping needed.

For in-process tools (text_editor), we need a way to pass the user. The text_editor Pydantic models don't have a `user` field and we don't want to add one (it's not a text_editor concern). So for in-process tools, we use `_run_as_user` as a reserved param that the CLI strips before dispatching.

Update `_exec()` in `main.py`:

```python
import json

# ... existing imports ...
from inspect_sandbox_tools._util.user_switch import switch_user


async def _exec(request: str | None) -> None:
    in_process_tools = load_tools("inspect_sandbox_tools._in_process_tools")

    request_json_str = request or sys.stdin.read().strip()
    tool_name = JSONRPCIncoming.model_validate_json(request_json_str).method
    assert isinstance(tool_name, str)

    # Extract _run_as_user for in-process tools (text_editor etc.)
    # The CLI does setuid before dispatching since it's a short-lived process.
    if tool_name in in_process_tools:
        request_data = json.loads(request_json_str)
        run_as_user = None
        if isinstance(request_data.get("params"), dict):
            run_as_user = request_data["params"].pop("_run_as_user", None)
        if run_as_user is not None:
            # Re-serialize without _run_as_user before dispatching
            request_json_str = json.dumps(request_data)
            switch_user(run_as_user)

    print(
        await (
            _dispatch_local_method
            if tool_name in in_process_tools
            else _dispatch_remote_method
        )(request_json_str)
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/inspect_sandbox_tools/src/inspect_sandbox_tools/_cli/main.py
git commit -m "feat: add user-switching for in-process tools via _run_as_user param"
```

---

### Task 5: Update host-side bash_session to use `_tools_user` and pass user in RPC params

**Files:**
- Modify: `src/inspect_ai/tool/_tools/_bash_session.py`

- [ ] **Step 1: Update the `execute` function**

Change both RPC calls to use `sandbox._tools_user` for transport and pass `user` in RPC params.

In the `execute` function (lines 196-238), make these changes:

1. Replace line 207 `params={}` with `params={"user": user} if user else {}` for `bash_session_new_session`
2. Replace line 212 `user=user` with `user=sandbox._tools_user` for `bash_session_new_session`
3. Replace line 237 `user=user` with `user=sandbox._tools_user` for `bash_session`

The full updated execute function (only the two RPC call blocks change):

```python
        if not store.session_id:
            try:
                store.session_id = (
                    await exec_model_request(
                        method="bash_session_new_session",
                        params={"user": user} if user else {},
                        result_type=NewSessionResult,
                        transport=transport,
                        error_mapper=SandboxToolsErrorMapper,
                        timeout=TRANSPORT_TIMEOUT,
                        user=sandbox._tools_user,
                    )
                ).session_name
            except TimeoutError:
                raise RuntimeError("Timed out creating new session")

        # ... timing and action_specific unchanged ...

        result = await exec_scalar_request(
            method="bash_session",
            params={"session_name": store.session_id, **(action_specific[action])},
            result_type=str,
            transport=transport,
            error_mapper=SandboxToolsErrorMapper,
            timeout=timeout,
            user=sandbox._tools_user,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/inspect_ai/tool/_tools/_bash_session.py
git commit -m "fix: bash_session runs CLI as _tools_user, passes user in RPC params"
```

---

### Task 6: Update host-side text_editor to use `_tools_user` and pass user in RPC params

**Files:**
- Modify: `src/inspect_ai/tool/_tools/_text_editor.py`

- [ ] **Step 1: Update the `execute` function**

Change the RPC call to use `sandbox._tools_user` for transport and include `_run_as_user` in params.

In the `execute` function (lines 110-131):

```python
        sandbox = await sandbox_with_injected_tools()

        # re-wire insert_text => new_str
        if command == "insert" and new_str is None and insert_text is not None:
            new_str = insert_text

        # Create a dictionary of the parameters
        params = {
            k: v
            for k, v in locals().items()
            if k in inspect.signature(execute).parameters
        }

        # Pass user via reserved param for CLI-side setuid (in-process tool)
        if user is not None:
            params["_run_as_user"] = user

        return await exec_scalar_request(
            method="text_editor",
            params=params,
            result_type=TextEditorResult,
            transport=SandboxJSONRPCTransport(sandbox, SANDBOX_CLI),
            error_mapper=SandboxToolsErrorMapper,
            timeout=timeout,
            user=sandbox._tools_user,
        )
```

Note: `user` is captured by the closure from the outer `text_editor()` function, so it's available inside `execute`.

- [ ] **Step 2: Commit**

```bash
git add src/inspect_ai/tool/_tools/_text_editor.py
git commit -m "fix: text_editor runs CLI as _tools_user, passes user via _run_as_user param"
```

---

### Task 7: Bump sandbox tools version

**Files:**
- Modify: `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`

- [ ] **Step 1: Bump version from 13 to 14**

```
14
```

- [ ] **Step 2: Commit**

```bash
git add src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt
git commit -m "chore: bump sandbox tools version to 14"
```

---

### Task 8: Run failing tests to verify the fix

**Files:** (no changes — verification only)

- [ ] **Step 1: Run the two originally failing tests**

Run: `uv run pytest tests/tools/sandbox_tools_utils/test_sandbox_tools.py::test_bash_session_non_root tests/tools/sandbox_tools_utils/test_sandbox_tools.py::test_text_editor_user -v --runslow`

Expected: Both PASS

- [ ] **Step 2: Run the full sandbox tools test suite for regressions**

Run: `uv run pytest tests/tools/sandbox_tools_utils/test_sandbox_tools.py -v --runslow`

Expected: All tests PASS

- [ ] **Step 3: Run linting and type checks**

Run: `uv run ruff check src/inspect_ai/tool/_tools/_bash_session.py src/inspect_ai/tool/_tools/_text_editor.py src/inspect_sandbox_tools/src/inspect_sandbox_tools/`

Expected: No errors
