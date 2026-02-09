# exec_remote Feature Plan

## Remaining Work Items

Items deferred from initial implementation, roughly in priority order:

- [ ] **`timeout_retry` option**: Retry logic on timeout, matching `exec()` behavior (up to 2 retries with progressively shorter timeouts). Only applies to awaitable mode (stream=False). Streaming mode cannot silently restart a stream the caller is consuming.
- [ ] **SIGKILL escalation test**: Test that `Job.kill()` escalates from SIGTERM to SIGKILL when a process traps SIGTERM. The server-side code handles this but it has no test coverage.
- [ ] **Integration tests with Docker sandbox**: End-to-end tests that run exec_remote through an actual Docker sandbox rather than mocked RPC.
- [ ] **Rename `_remote_tools` directory**: The name is misleading now that it contains `_exec_remote` (infrastructure, not a tool). Consider `_remote_services` or `_json_rpc_services`.
- [ ] **aiohttp `tcp_keepalive` noise on Unix sockets**: aiohttp 3.13.3 tries to set `SO_KEEPALIVE` on Unix socket connections, logging harmless but noisy ERROR-level messages on every request. Fix by switching from `run_app()` to `AppRunner`/`TCPSite` with `tcp_keepalive=False`, or suppressing the specific error.

---

## Overview

Add an `exec_remote` method to `SandboxEnvironment` for asynchronous execution of long-running commands. Unlike `exec` which blocks until completion, `exec_remote` starts the process immediately and provides streaming output via an async iterator - avoiding timeout and connectivity issues with long-running commands in K8s/Docker environments.

## Naming Convention

`exec_remote` is used consistently across all layers:

| Context | Example |
|---------|---------|
| **Host-side API** (SandboxEnvironment method) | `sandbox.exec_remote(["make", "build"])` |
| **Sandbox-side** (JSON-RPC methods) | `exec_remote_start`, `exec_remote_poll`, `exec_remote_kill` |
| **Sandbox-side** (package directory) | `_exec_remote/` |

## Decisions Made

- **stdout/stderr**: Separate streams (not combined like bash_session's PTY)
- **Job cleanup**: Auto-cleanup after `poll` returns a terminal status (completed/failed/killed)
- **Server restarts**: Jobs do not survive server restarts (in-memory storage)
- **Client-side Tool**: Not needed - this is server-side/CLI only
- **Process lifecycle**: `exec_remote()` **immediately starts** the process - it's "hot" from creation
- **Streaming only**: `ExecRemoteProcess` is async-iterable only (no await support) - keeps API simple
- **`kill()` semantics**: Calling `kill()` indicates the caller is uninterested in output or exit code. Any buffered data is discarded. If the caller wants output from a process that may have already completed, they should `poll()` instead.

---

## Execution Contexts

This feature spans three distinct execution contexts:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INSPECT_AI PROCESS (host machine)                                          │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Code: src/inspect_ai/util/_sandbox/                                        │
│  - SandboxEnvironment.exec_remote() method                                        │
│  - ExecRemoteProcess class (dual-mode handle)                                    │
│  - Event types (StdoutChunk, StderrChunk, Completed)                        │
│  - Polling loop that calls sandbox.exec() to invoke CLI                     │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ sandbox.exec("inspect_sandbox_tools exec_remote ...")
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SANDBOX CONTAINER                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  CLI LAYER (stateless, short-lived process)                           │  │
│  │  ─────────────────────────────────────────────────────────────────────│  │
│  │  Code: src/inspect_sandbox_tools/.../cli/main.py                      │  │
│  │  - Parses: exec_remote submit|poll|kill                                │  │
│  │  - Forwards JSON-RPC request to server via Unix socket                │  │
│  │  - Returns JSON-RPC response to stdout                                │  │
│  │  - Starts server if not running                                       │  │
│  │  - Lifetime: single request/response, then exits                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│                                  │ Unix socket JSON-RPC                     │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  SERVER LAYER (stateful, long-running process)                        │  │
│  │  ─────────────────────────────────────────────────────────────────────│  │
│  │  Code: src/inspect_sandbox_tools/.../_remote_tools/_exec_remote/       │  │
│  │  - JSON-RPC methods: exec_remote_start, exec_remote_poll, exec_remote_kill│
│  │  - Controller: manages Job instances, thread-safe job registry        │  │
│  │  - Job: wraps asyncio subprocess, background stdout/stderr readers    │  │
│  │  - Lifetime: persists across CLI invocations, holds job state         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Context Summary

| Context | Location | Lifetime | State | Responsibilities |
|---------|----------|----------|-------|------------------|
| **inspect_ai process** | Host machine | Eval duration | Transient | API surface, polling orchestration, event streaming |
| **CLI layer** | Sandbox container | Single request | Stateless | Parse commands, route to server, return response |
| **Server layer** | Sandbox container | Long-running | Stateful | Job lifecycle, subprocess management, output buffering |

---

## Part 1: Server Layer (Stateful, in Sandbox)

**Location**: `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`

This code runs inside the sandbox container as part of the long-running `inspect_sandbox_tools` server process. It maintains state (running jobs, output buffers) across multiple CLI invocations.

### API

Three JSON-RPC methods exposed by the server:

| JSON-RPC Method | Input | Output |
|-----------------|-------|--------|
| `exec_remote_start` | command (string) | pid (int) |
| `exec_remote_poll` | pid | state, exit_code?, stdout, stderr |
| `exec_remote_kill` | pid | success/failure |

### Poll Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `state` | string | Job lifecycle state: `running`, `completed`, or `killed` |
| `exit_code` | int \| None | Process exit code. Only present when state is `completed`. |
| `stdout` | string | Standard output since last poll (incremental) |
| `stderr` | string | Standard error since last poll (incremental) |

### State Values
- `running` - job is still executing
- `completed` - job finished (check `exit_code` for success/failure: 0 = success, non-zero = failure)
- `killed` - job was terminated via kill command

### Cleanup Behavior
Job is automatically removed from the controller after a `poll` call returns a terminal state (`completed` or `killed`). Subsequent polls for that pid will return an error.

### Components

All files below are in `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`:

1. **JSON-RPC Methods** (`json_rpc_methods.py`)
   - `exec_remote_start(command)` → pid
   - `exec_remote_poll(pid)` → {state, exit_code?, stdout, stderr}
   - `exec_remote_kill(pid)` → success message
   - Uses `@validated_json_rpc_method` decorator (shared with bash_session)

2. **Controller** (`_controller.py`)
   - Simple `dict[int, Job]` registry keyed by PID
   - `submit(command) → pid`: create Job, store by pid
   - `poll(pid) → result`: get output, cleanup if terminal
   - `kill(pid)`: terminate job
   - No `SessionController` - PIDs are natural unique identifiers

3. **Job** (`_job.py`)
   - Wraps `asyncio.create_subprocess_shell` with separate PIPE for stdout/stderr
   - Background read tasks accumulate output into buffers
   - `poll()` returns and clears incremental output
   - `kill()` terminates subprocess gracefully then forcefully

4. **Types** (`tool_types.py`)
   - Pydantic models for request/response validation

### Files to Create (Server Layer)

```
src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/
├── __init__.py
├── json_rpc_methods.py    # JSON-RPC handlers
├── _controller.py         # Job registry (simple dict keyed by PID)
├── _job.py                # Subprocess wrapper with background readers
└── tool_types.py          # Pydantic models
```

### Files to Modify (Server Layer)

- `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/load_tools.py` - register exec_remote methods

### Code Sharing Recommendation

**Summary**: ~20% direct reuse, ~30% pattern reuse, ~50% new code.

#### Reuse Directly (no changes needed)

| Component | File | How to Use |
|-----------|------|------------|
| `@validated_json_rpc_method` | `_util/json_rpc_helpers.py` | Decorate JSON-RPC handlers identically |
| `load_tools` registry | `_util/load_tools.py` | Add `"exec_remote": exec_remote_methods` entry |

#### Follow Same Patterns (new code, same architecture)

| Pattern | bash_session Example | exec_remote Equivalent |
|---------|---------------------|----------------------|
| JSON-RPC method structure | `bash_session_new_session`, `bash_session` | `exec_remote_start`, `exec_remote_poll`, `exec_remote_kill` |
| Background read task | `_read_loop()` in `Process` | Two read loops (stdout + stderr) in `Job` |
| Graceful termination | terminate → kill sequence | Same pattern |
| Pydantic tool_types.py | `BashParams`, `InteractResult`, etc. | `SubmitParams`, `PollResult`, etc. |

#### Do NOT Reuse (different requirements)

| Component | Why |
|-----------|-----|
| `SessionController` | exec_remote uses PIDs as natural unique identifiers, no session naming needed |
| `PseudoTerminal` | exec_remote uses separate pipes, not PTY |
| `AsyncDecodedStreamReader` | PTY-specific; pipes don't need incremental UTF-8 decoding |
| `Process` class | Tied to PTY I/O, interactive bash, single combined stream |
| `Session` class | Has restart capability exec_remote doesn't need |
| `TimeoutEvent` | Server-driven adaptive waits; exec_remote uses client-driven polling |
| `strip_control_characters()` | PTY produces ANSI escapes; pipes produce clean output |

---

## Part 2: CLI Layer (Stateless, in Sandbox)

**No new CLI code needed.** The existing `exec` subcommand already handles JSON-RPC dispatch for any method, including exec_remote methods. The host-side code constructs JSON-RPC requests and passes them via the existing path.

### CLI Usage

```bash
# Submit a new job (returns pid)
inspect_sandbox_tools exec '{"jsonrpc": "2.0", "method": "exec_remote_start", "params": {"command": "long-running-command"}, "id": 1}'

# Poll job status and get incremental output
inspect_sandbox_tools exec '{"jsonrpc": "2.0", "method": "exec_remote_poll", "params": {"pid": 12345}, "id": 1}'

# Kill a running job
inspect_sandbox_tools exec '{"jsonrpc": "2.0", "method": "exec_remote_kill", "params": {"pid": 12345}, "id": 1}'
```

### Data Flow

```
Host calls:  sandbox.exec(["inspect_sandbox_tools", "exec", '{"jsonrpc": "2.0", "method": "exec_remote_start", ...}'])
                │
                ▼
CLI process:   Parse JSON-RPC → route to server via Unix socket
                                                                │
                                                                ▼
Server:        exec_remote_start() → Controller.submit() → Job.create()
                                                                │
                ◄───────────────────────────────────────────────┘
CLI process:   Print JSON response → exit
                │
                ▼
Host receives: {"result": {"pid": 12345}}
```

### Files to Modify (CLI Layer)

None - the existing `exec` subcommand handles this.

---

## Part 3: inspect_ai Process (Host Machine)

**Location**: `src/inspect_ai/util/_sandbox/`

This code runs in the main inspect_ai process on the host machine. It provides the Python API that solvers and tools use, and orchestrates polling to stream events back to the caller.

### Event Types

```python
from dataclasses import dataclass
from typing import Union

@dataclass
class StdoutChunk:
    """A chunk of stdout data from the running process."""
    data: str

@dataclass
class StderrChunk:
    """A chunk of stderr data from the running process."""
    data: str

@dataclass
class Completed:
    """Process completed (successfully or with error)."""
    exit_code: int
    stdout: str  # Full accumulated stdout
    stderr: str  # Full accumulated stderr

    @property
    def success(self) -> bool:
        return self.exit_code == 0

ExecRemoteEvent = Union[StdoutChunk, StderrChunk, Completed]
```

### Return Type

```python
class ExecRemoteProcess:
    """Handle to a running exec_remote process.

    The process starts immediately when exec_remote() is called - it's "hot" from creation.

    Usage patterns:

    1. Streaming: iterate over events
       proc = sandbox.exec_remote(["cmd"])
       async for event in proc.events:
           match event:
               case StdoutChunk(data=data): print(data)
               case Completed(exit_code=code): print(f"Done: {code}")

    2. Fire-and-forget with explicit kill:
       proxy = sandbox.exec_remote(["./proxy"])  # starts immediately
       # ... do other work ...
       await proxy.kill()  # terminate when done
    """

    events: AsyncIterator[ExecRemoteEvent]
    """Async iterator over events as they arrive."""

    async def kill(self) -> None:
        """Terminate the process."""
        ...
```

### Method Signature

```python
# In SandboxEnvironment ABC

def exec_remote(
    self,
    cmd: list[str],
    options: ExecRemoteOptions | None = None,
) -> ExecRemoteProcess:
    """Start a long-running command and return a handle to it.

    The process starts immediately when this method is called.
    Unlike exec(), exec_remote does not block waiting for completion.

    Args:
        cmd: Command and arguments to execute.
        options: Execution options (see ExecRemoteOptions).

    Returns:
        ExecRemoteProcess handle with:
        - events: AsyncIterator for streaming output
        - kill(): method to terminate the process
    """
```

Note: `exec_remote()` is a regular method (not async) that returns `ExecRemoteProcess`. The process is started synchronously via a blocking `exec()` call to submit the job. This allows fire-and-forget patterns without an initial await.

### Options Object

```python
@dataclass
class ExecRemoteOptions:
    """Options for exec_remote() command execution."""

    input: str | bytes | None = None
    """Standard input to send to the command."""

    cwd: str | None = None
    """Working directory for command execution."""

    env: dict[str, str] | None = None
    """Additional environment variables."""

    user: str | None = None
    """User to run the command as."""

    timeout: int | None = None
    """Maximum execution time in seconds."""

    poll_interval: float | None = None
    """Interval between poll requests (defaults to 0.5 seconds)."""
```

### Implementation Details

The `ExecRemoteProcess` class internally:
1. Calls `sandbox.exec(["inspect_sandbox_tools", "exec_remote", "submit", cmd])` to start the job
2. Stores the returned `pid`
3. `events` iterator polls via `sandbox.exec(["inspect_sandbox_tools", "exec_remote", "poll", pid])`
4. Yields `StdoutChunk`/`StderrChunk` events for incremental output
5. Yields `Completed` event when poll returns terminal state
6. `kill()` calls `sandbox.exec(["inspect_sandbox_tools", "exec_remote", "kill", pid])`

### Files to Modify (inspect_ai)

1. **environment.py** (`src/inspect_ai/util/_sandbox/environment.py`)
   - Add `ExecRemoteOptions` dataclass
   - Add event types: `StdoutChunk`, `StderrChunk`, `Completed`
   - Add `ExecRemoteEvent` type alias
   - Add `ExecRemoteProcess` class
   - Add `exec_remote()` method to `SandboxEnvironment` ABC

2. **__init__.py** (`src/inspect_ai/util/_sandbox/__init__.py`)
   - Export: `ExecRemoteOptions`, `ExecRemoteProcess`, `ExecRemoteEvent`, `StdoutChunk`, `StderrChunk`, `Completed`

---

## Usage Examples

### Streaming Output

```python
proc = sandbox.exec_remote(["pytest", "-v"])
async for event in proc.events:
    match event:
        case StdoutChunk(data=data):
            print(data, end="", flush=True)
        case StderrChunk(data=data):
            print(data, end="", file=sys.stderr, flush=True)
        case Completed(exit_code=code):
            print(f"\nTests finished with code {code}")
```

### Fire-and-Forget with Kill

```python
# Start proxy immediately (no await needed to start)
proxy = sandbox.exec_remote(["./model-proxy"])

# Run agent, streaming output
async for event in sandbox.exec_remote(["claude-code", "--task", task]):
    match event:
        case StdoutChunk(data=data):
            print(data, end="", flush=True)
        case Completed(exit_code=code):
            print(f"\nAgent finished with code {code}")

# Clean up proxy
await proxy.kill()
```

---

## Implementation Checklist

### Phase 1: Server Layer (Sandbox - Stateful) ✅ COMPLETE
- [x] Create `_exec_remote/` package structure
- [x] Define Pydantic models in `tool_types.py`
- [x] Implement `Job` class with subprocess management
- [x] Implement `Controller` (simple dict registry)
- [x] Implement JSON-RPC methods
- [x] Register in `load_tools.py`

### Phase 2: CLI Layer (Sandbox - Stateless) ✅ NOT NEEDED
- [x] No new CLI code required - existing `exec` subcommand handles JSON-RPC dispatch for exec_remote methods

### Phase 3: inspect_ai Process (Host) ✅ COMPLETE
- [x] Add event dataclasses (`StdoutChunk`, `StderrChunk`, `Completed`)
- [x] Add `ExecRemoteOptions` dataclass
- [x] Add `ExecRemoteProcess` class (async-iterable only)
- [x] Add `exec_remote()` method to SandboxEnvironment ABC
- [x] Export new types from public API

### Phase 4: Refactor model_proxy to use exec_remote ✅ COMPLETE

**Motivation**: The model_proxy is a long-running HTTP server that can run for an extremely long time (the duration of an agent task). The current approach uses a blocking `sandbox.exec()` call which has timeout/connectivity issues in K8s/Docker environments. Using exec_remote provides proper lifecycle management for this long-running process.

**Architecture Overview**:

```
Host (bridge.py)                          Sandbox
─────────────────                         ───────
sandbox_agent_bridge()
  │
  ├─ sandbox.exec_remote([SANDBOX_TOOLS_CLI, "model_proxy"])
  │     │
  │     └─► exec_remote_start ──────────► Job spawns: inspect_sandbox_tools model_proxy
  │                                           │
  │                                           ▼
  │                                       model_proxy_server runs
  │                                       (HTTP server on port 13131)
  │
  ├─ yield bridge  ◄─────────────────────► Agent makes API calls to proxy
  │
  └─ await proxy.kill()
        │
        └─► exec_remote_kill ────────────► Job terminates proxy process
```

**Key Insight**: The proxy server code lives in `src/inspect_ai/agent/_bridge/sandbox/proxy.py` and is a self-contained async HTTP server with no inspect_ai dependencies. It can be run as a script:
```python
if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 13131
    asyncio.run(run_model_proxy_server(port=port_arg))
```

**Build System Finding**:

The proxy code (`inspect_sandbox_tools._agent_bridge.proxy`) is **already bundled** in the staticx executable because `main.py` imports it:
```python
from inspect_sandbox_tools._agent_bridge.proxy import run_model_proxy_server
```

PyInstaller traces all imports from the entry point (`main.py`) and includes them in the bundle. This means:
- The proxy code is already available inside the sandbox (within the `inspect_sandbox_tools` executable)
- We cannot use `python proxy.py` because the staticx bundle is a Python-less environment - there's no standalone Python interpreter, only the embedded one inside the bundle
- The only way to execute Python code in the sandbox is through the bundled executable's CLI subcommands or JSON-RPC methods
- Since the proxy needs to run as a **separate long-running process** (not just a method call within the existing server), we must use a CLI subcommand

**Approach: Keep `model_proxy` subcommand, invoke via exec_remote**

Keep the existing `model_proxy` CLI subcommand and invoke it via exec_remote for proper lifecycle management:
- Host-side calls: `sandbox.exec_remote([SANDBOX_TOOLS_CLI, "model_proxy"])`
- exec_remote sends `exec_remote_start` to spawn the proxy as a managed subprocess
- Proxy runs until `exec_remote_kill` terminates it

**Implementation Tasks**:

1. **Update host-side bridge.py**
   - [x] Change `run_model_proxy()` to use `sandbox.exec_remote()` instead of blocking `sandbox.exec()`
   - [x] Command: `[SANDBOX_TOOLS_CLI, "model_proxy"]`
   - [x] Pass environment variables via `ExecRemoteOptions(env={...})`
   - [x] Store `ExecRemoteProcess` handle on the bridge for cleanup

2. **Update lifecycle management**
   - [x] Call `await proxy.kill()` in the finally block when bridge context exits
   - [x] Keep task group cancellation (still needed for model service cleanup)
   - [x] Handle case where proxy exits unexpectedly (via `_monitor_proxy` task)

3. **Error handling**
   - [x] If proxy fails to start, the Completed event will have non-zero exit_code (detected by monitor)
   - [x] stderr from proxy is captured and logged on failure

**JSON-RPC Flow**:

When `sandbox.exec_remote([SANDBOX_TOOLS_CLI, "model_proxy"])` is called:

```json
{
  "jsonrpc": "2.0",
  "method": "exec_remote_start",
  "params": {
    "command": "BRIDGE_MODEL_SERVICE_PORT='13131' BRIDGE_MODEL_SERVICE_INSTANCE='proxy_abc123' /path/to/inspect_sandbox_tools model_proxy"
  },
  "id": 1
}
```

The exec_remote controller spawns the `model_proxy` subcommand as a subprocess, and it runs indefinitely until killed via `exec_remote_kill`.

### Phase 5: Add exec_remote overload for simple await use case ✅ COMPLETE

**Motivation**: Many use cases for exec_remote don't need streaming output - they just want to run a command asynchronously without blocking the entire sandbox connection. For these cases, having to iterate through `events` and handle `StdoutChunk`/`StderrChunk`/`Completed` is unnecessarily complex.

**Design**: Add an overload to `exec_remote()` that returns `ExecResult[str]` directly (same type as `exec()`):

```python
# Streaming mode (existing) - returns ExecRemoteProcess
proc = sandbox.exec_remote(["pytest", "-v"])
async for event in proc.events:
    ...

# Simple await mode (new) - returns ExecResult[str]
result = await sandbox.exec_remote(["pytest", "-v"], stream=False)
if result.success:
    print(result.stdout)
```

**Implementation**:

1. **Add overloads to `SandboxEnvironment.exec_remote()`**
   - [x] Overload 1: `exec_remote(cmd, options, stream=True) -> ExecRemoteProcess` (default, existing behavior)
   - [x] Overload 2: `exec_remote(cmd, options, stream=False) -> Awaitable[ExecResult[str]]`
   - [x] Implementation dispatches based on `stream` parameter

2. **Update `ExecRemoteOptions`**
   - [x] No changes needed - same options work for both modes

3. **Implementation for non-streaming mode**
   - [x] `_create_exec_remote_awaitable()` returns a coroutine
   - [x] `_exec_remote_await_impl()` submits job, polls until completion, accumulates output
   - [x] Returns `ExecResult[str]` when process completes

4. **Exports**
   - [x] No new types needed - reuses existing `ExecResult[str]`

**Files modified**:
- `src/inspect_ai/util/_sandbox/exec_remote.py`: Added `_build_shell_command()`, `_create_exec_remote_awaitable()`, `_exec_remote_await_impl()`
- `src/inspect_ai/util/_sandbox/environment.py`: Added overloads to `exec_remote()` method

### Phase 6: Testing
- [ ] Unit tests for Job class (server layer)
- [ ] Unit tests for Controller (server layer)
- [ ] Unit tests for ExecRemoteProcess (mock CLI calls)
- [ ] Test iteration yields correct event sequence
- [ ] Test timeout handling
- [ ] Test kill functionality
- [ ] Integration test with actual sandbox

---

## Comparison: bash_session vs exec_remote

### Fundamental Difference: Tool vs Infrastructure

**bash_session is a Tool** - It's exposed to models/agents as a callable tool. The model can invoke `bash_session` to run commands in a persistent shell. This means:
- Has tool registration and schema
- Appears in tool listings
- Model decides when to call it
- Part of the agent's action space

**exec_remote is NOT a Tool** - It's infrastructure for solver/evaluation code. The `exec_remote()` method is called by Python code running in the inspect_ai process, not by models. This means:
- No tool registration or schema
- Not visible to models
- Solver/tool implementation code calls it directly
- Similar to `sandbox.exec()` - a programmatic API, not an agent action

### I/O Model: PTY vs Separate Pipes

**bash_session uses a PTY (pseudo-terminal)**

A PTY emulates a real terminal device. bash_session creates a PTY pair and attaches bash's stdin/stdout/stderr all to the same PTY file descriptor:

```python
# bash_session's approach
pty = await PseudoTerminal.create()
process = await asyncio.create_subprocess_exec(
    "/bin/bash", "-i",
    stdin=pty.subprocess_fd,
    stdout=pty.subprocess_fd,   # Same fd
    stderr=pty.subprocess_fd,   # Same fd
)
```

Implications of PTY:
- **Combined streams**: stdout and stderr are interleaved in arrival order (like a real terminal)
- **Interactive shell**: Bash runs in interactive mode (`-i`), loading `.bashrc`, enabling job control
- **Line buffering**: PTY provides proper line buffering for interactive use
- **Terminal features**: Supports terminal escape sequences, though bash_session strips them
- **Complexity**: Requires PTY management, terminal attribute configuration, echo disabling
- **Use case**: Persistent shell sessions where the model sends multiple commands over time

**exec_remote uses separate pipes**

exec_remote creates the subprocess with independent pipes for stdout and stderr:

```python
# exec_remote's approach
process = await asyncio.create_subprocess_shell(
    command,
    stdout=asyncio.subprocess.PIPE,  # Separate pipe
    stderr=asyncio.subprocess.PIPE,  # Separate pipe
)
```

Implications of separate pipes:
- **Distinct streams**: stdout and stderr are captured independently, can be processed/displayed separately
- **Non-interactive shell**: No `.bashrc`, no job control, simpler environment
- **Block buffering**: Pipes use block buffering by default (programs may buffer output until exit)
- **Simpler implementation**: No PTY setup, just standard subprocess pipes
- **Ordering caveat**: Cannot reconstruct exact interleaving of stdout/stderr (each has its own buffer)
- **Use case**: Running a single command and streaming its output back to the caller

### Comparison Table

| Aspect | bash_session | exec_remote / exec_remote |
|--------|--------------|------------|
| **Type** | Tool (model-callable) | Infrastructure (code-callable) |
| **Purpose** | Persistent interactive shell | One-shot command execution |
| **Session lifecycle** | Long-lived, survives calls | Single command, auto-cleanup |
| **I/O model** | PTY (combined stdout/stderr) | Separate pipes (distinct streams) |
| **Shell mode** | Interactive (`bash -i`) | Non-interactive (`sh -c`) |
| **Buffering** | Line buffered (PTY) | Block buffered (pipes) |
| **Output delivery** | Accumulated, cleared after interact | Incremental per poll |
| **Stream separation** | No (interleaved) | Yes (stdout/stderr independent) |
| **Restart capability** | Yes | No (kill and submit new) |

### Shared Infrastructure

Despite these differences, both features share underlying infrastructure in the sandbox tools server:

| Component | Used By | Notes |
|-----------|---------|-------|
| `@validated_json_rpc_method` | Both | Same decorator for JSON-RPC registration |
| JSON-RPC server | Both | Same aiohttp server process |
| Unix socket communication | Both | Same IPC mechanism |
| CLI dispatch pattern | Both | Same routing in `main.py` |

### What exec_remote Does NOT Share

| Component | Why Not Shared |
|-----------|----------------|
| `SessionController` | exec_remote uses PIDs as natural unique identifiers, no session naming needed |
| `PseudoTerminal` | exec_remote uses pipes, not PTY |
| `AsyncDecodedStreamReader` | PTY-specific UTF-8 handling not needed |
| `Process` class | Deeply tied to PTY I/O and interactive bash |
| `Session` class | Has restart capability exec_remote doesn't need |
| `TimeoutEvent` | bash_session's adaptive wait; exec_remote uses client-driven polling |
| `strip_control_characters()` | PTY produces ANSI escapes; pipes don't |

---

## Open Questions

- [ ] **Output buffering strategy**: Currently planned as incremental (data since last poll). Should we also support a mode that buffers all output? Or is that just "await the process"?

## Future Cleanup

- [ ] **Rename `_remote_tools` directory**: The name `_remote_tools` is misleading now that it contains `_exec_remote`, which is infrastructure rather than a tool. Consider renaming to `_remote_services` or `_json_rpc_services` to better reflect that it contains both tools (like `bash_session`) and infrastructure (like `exec_remote`). Add a TODO comment in the code when creating the `_exec_remote` directory.

- [ ] **Replace `ToolException` usage**: `exec_remote` uses `ToolException` for error handling, but since exec_remote isn't a tool, this is semantically incorrect. Consider creating a more general exception type (e.g., `ServiceException` or `JsonRpcException`) or using a standard exception type.

- [ ] **aiohttp `tcp_keepalive` noise on Unix sockets**: aiohttp 3.13.3 tries to set `SO_KEEPALIVE` on every incoming Unix socket connection (`tcp_helpers.py:tcp_keepalive`), which is invalid for Unix domain sockets and throws `OSError: [Errno 22] Invalid argument`. The error is harmless — requests still succeed with 200 — but it spams ERROR-level logs on every single request, making the server log useless for debugging real issues. This is a pre-existing issue (not introduced by exec_remote) that affects all JSON-RPC methods (bash_session, exec_remote, etc.). Fix: switch from `run_app()` to `AppRunner`/`TCPSite` with `tcp_keepalive=False`, or suppress the specific error. Not a merge blocker, but worth cleaning up to keep server logs readable.

- [x] **Process group handling for kill()**: `Job.create()` now uses `start_new_session=True` so the subprocess becomes its own process group leader. `kill()` uses `os.killpg()` to send SIGTERM/SIGKILL to the entire process group, ensuring child processes (e.g., jest workers) are also terminated.

- [x] **Output limit support for exec_remote**: Implemented host-side output limiting in `exec_remote_awaitable()` using `_CircularStringBuffer`, consistent with how `exec()` handles it. Each output stream (stdout/stderr) is capped at 10 MiB (`SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE`). When output exceeds the limit, only the most recent bytes are kept. No server-side changes needed since the caller polls regularly and clears buffers.

## Missing Options from `exec()`

The goal is to support all the same options that `SandboxEnvironment.exec()` supports. The following are not yet implemented in `ExecRemoteOptions`:

- [x] **`input: str | bytes | None`** - Standard input to send to the command.
  - Server-side: `SubmitParams` accepts optional `input` string parameter
  - `Job.create()` opens stdin pipe when input is provided, writes and closes it
  - Host-side: `ExecRemoteOptions.input` accepts `str | bytes | None`, bytes are decoded to UTF-8
  - Input is written all at once before the command runs (not streaming)

- [ ] **`timeout: int | None`** - Maximum execution time in seconds.
  - Can be implemented client-side with `asyncio.timeout()` around the polling loop
  - On timeout expiration, call `kill()` to terminate the process
  - Should raise `TimeoutError` (consistent with `exec()` behavior)
  - Consider interaction with `timeout_retry`

- [ ] **`timeout_retry: bool`** - Whether to retry on timeout (default `True` in `exec()`).
  - In `exec()`, this retries the entire command on timeout
  - For exec_remote streaming, retry semantics are unclear - would need to restart from scratch
  - For exec_remote awaitable mode, could implement similar retry logic
  - May not make sense for streaming use case - consider omitting or documenting differently

- [ ] **`concurrency: bool`** - Whether to allow concurrent execution (default `True` in `exec()`).
  - In `exec()`, this controls whether multiple exec calls can run simultaneously
  - For exec_remote, need to decide: does this apply per-sandbox or globally?
  - May require coordination with existing concurrency control mechanisms

---

## Verification

1. **Unit test**: Mock sandbox.exec() calls, verify streaming behavior
2. **Integration test**: Run actual long-running command in Docker sandbox
3. **Manual test**:
   ```python
   sandbox = await get_sandbox()

   # Test streaming
   proc = sandbox.exec_remote(["bash", "-c", "for i in 1 2 3; do echo $i; sleep 1; done"])
   async for event in proc.events:
       print(f"Event: {event}")

   # Test fire-and-forget with kill
   proxy = sandbox.exec_remote(["sleep", "999"])
   await asyncio.sleep(1)
   await proxy.kill()
   print("Proxy killed")
   ```

4. **Easy test command via JSON-RPC**: An infinite counter that prints an increasing integer every 1.5 seconds is useful for verifying streaming, incremental poll delivery, and kill behavior. It's slow enough to observe polling across multiple cycles.

   Run these from a shell. Each pipes a JSON-RPC payload via stdin to the CLI.

   ```bash
   # Submit the counter (returns a pid)
   echo '{"jsonrpc":"2.0","method":"exec_remote_start","params":{"command":"i=0; while true; do echo $((i++)); sleep 1.5; done"},"id":1}' \
     | python -m inspect_sandbox_tools._cli.main exec

   # Poll for incremental output (repeat to see increasing numbers)
   echo '{"jsonrpc":"2.0","method":"exec_remote_poll","params":{"pid":<PID>},"id":2}' \
     | python -m inspect_sandbox_tools._cli.main exec

   # Kill when done
   echo '{"jsonrpc":"2.0","method":"exec_remote_kill","params":{"pid":<PID>},"id":3}' \
     | python -m inspect_sandbox_tools._cli.main exec
   # Verify the process is running
   ps -p <PID>

   # Kill the process directly (if needed, e.g. server not responding)
   kill <PID>

   # List all running sandbox tools servers
   pgrep -af "inspect_sandbox_tools._cli.main server"

   # Kill all running servers (useful after test runs that leak server processes)
   pkill -f "inspect_sandbox_tools._cli.main server"
   ```

   This confirms that:
   - `exec_remote_start` starts the job and returns a pid
   - `exec_remote_poll` returns incremental stdout with incrementing values (not duplicated across polls)
   - `exec_remote_kill` cleanly terminates the process
