# Fix user parameter for bash_session and text_editor with root-only CLI

## Problem

Commit `95dd1e629` changed sandbox tool injection to `chmod 700` the CLI binary (root-only) and set `sandbox._tools_user = "root"`. This prevents the agent from executing the CLI directly. However, `bash_session(user="nobody")` and `text_editor(user="nobody")` pass `user` as a transport extra arg, which causes `sandbox.exec()` to run the CLI as that user — failing because the binary is root-only.

Two tests fail:
- `test_bash_session_non_root` — `bash_session(user="nobody")`
- `test_text_editor_user` — `text_editor(user="nobody")`

## Approach: per-tool fix following exec_remote pattern

`exec_remote` already handles this correctly:
1. Runs CLI as `sandbox._tools_user` (root) — line 288 of `exec_remote.py`
2. Passes the actual user inside RPC params — line 320-321 of `exec_remote.py`
3. Server extracts user from params and does setuid — `_job.py:_make_preexec()`

Apply the same pattern to bash_session and text_editor. No transport changes needed.

## Design

### Reserved RPC param: `_run_as_user`

Both tools pass user in RPC params as `_run_as_user`. This is stripped before Pydantic validation by the RPC dispatch layer and made available to handlers.

### Host-side tool changes

**`_bash_session.py`**: The tool needs access to the sandbox to get `_tools_user`. It already gets the sandbox via `_get_sandbox()`. Changes:
- Store sandbox reference when creating transport
- Pass `user=sandbox._tools_user` in transport extra args (instead of the tool's `user`)
- Include `_run_as_user=user` in RPC params for both `bash_session_new_session` and `bash_session` calls

**`_text_editor.py`**: Currently creates a fresh `SandboxJSONRPCTransport` per call. Changes:
- Get sandbox via `sandbox_with_injected_tools()`
- Pass `user=sandbox._tools_user` in transport extra args
- Include `_run_as_user=user` in RPC params

### CLI changes (in-process tools)

**`_cli/main.py`**: For in-process tools (like text_editor), the CLI process does file I/O directly. To run as a different user:
- In `_exec()`, parse the incoming JSON-RPC request
- Extract and remove `_run_as_user` from params
- If present, call `switch_user()` (setuid/setgid/initgroups) before dispatching
- Re-serialize the modified request (without `_run_as_user`) for dispatch

Since the CLI is short-lived (one invocation per request), in-process setuid is safe.

### CLI changes (remote tools)

For remote tools dispatched to the server:
- The `_run_as_user` field stays in the params and is forwarded to the server
- The server-side `with_validated_rpc_method_params()` strips `_run_as_user` before Pydantic validation and stores it in a `contextvars.ContextVar`
- RPC handlers that need it read from the contextvar

### Server-side bash_session changes

**`json_rpc_methods.py`**: `bash_session_new_session` reads `_run_as_user` from the contextvar and passes to controller. Also determines `can_switch_user = os.getuid() == 0`.

**`_controller.py`**: `new_session()` accepts `user` and `can_switch_user`, passes to `Session.create()`.

**`_session.py`**: `create()` accepts `user`, passes to `Process.create()`.

**`_process.py`**: `create()` accepts `user`, uses shared `make_preexec(user)` as `preexec_fn` for `asyncio.create_subprocess_exec`. Also sets `HOME` from `/etc/passwd` when switching user (matching exec_remote).

### Shared user-switching utility

**New file: `_util/user_switch.py`**

Extract from `_job.py`:
- `is_current_user(username) -> bool`
- `make_preexec(username) -> Callable` — preexec_fn for subprocess (setuid + OOM score)
- `switch_user(username) -> None` — in-process setuid for CLI use

`_job.py` imports from the shared module instead of defining locally. `_set_oom_score_adj` stays in `_job.py` or moves to the shared module too (it's useful in both contexts).

### Version bump

Bump `sandbox_tools_version.txt` from 13 to 14 (CLI binary behavior changed).

## Files to modify

1. `src/inspect_ai/tool/_tools/_bash_session.py` — use `_tools_user` for transport, pass user in RPC params
2. `src/inspect_ai/tool/_tools/_text_editor.py` — same pattern
3. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_cli/main.py` — extract `_run_as_user`, setuid for in-process tools
4. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/json_rpc_helpers.py` — strip `_run_as_user` before validation, store in contextvar
5. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_util/user_switch.py` — new shared module
6. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/_job.py` — use shared module
7. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/json_rpc_methods.py` — pass user to controller
8. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_controller.py` — accept user
9. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_session.py` — accept user
10. `src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_bash_session/_process.py` — setuid in subprocess
11. `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt` — bump to 14

## Verification

```sh
pytest tests/tools/sandbox_tools_utils/test_sandbox_tools.py -v --runslow
```

This runs both failing tests and existing passing tests to confirm no regressions.
