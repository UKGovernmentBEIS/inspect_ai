# Plan: eliminate per-`exec` unpack via PyInstaller `--onedir`

## Context

The sandbox-tools executable is built as a PyInstaller `--onefile` binary wrapped in
StaticX. Every tool call goes through
`SandboxJSONRPCTransport.__call__` → `sandbox.exec([SANDBOX_CLI, "exec"], …)`
(`src/inspect_ai/util/_sandbox/_json_rpc_transport.py:60`), which spawns a fresh
process. On every spawn the binary pays **two self-extraction costs**: StaticX
unpacks its bundle to a temp dir, then the PyInstaller `--onefile` bootloader
extracts the entire Python distribution to a fresh `_MEIPASS` temp dir — even when
the process is just a thin JSON-RPC forwarder to the already-running daemon over the
Unix socket. For an agent making hundreds of `bash_session`/`text_editor` calls this
is a per-call latency tax on the hottest path in the system.

**Goal:** stop unpacking on every `exec`, with the smallest possible change and no
disturbance to the multi-user model.

**Approach:** switch the build from `--onefile` + StaticX to PyInstaller `--onedir`.
An onedir bundle is a directory that lives on disk in the container; the launcher
runs against the already-extracted `_internal/` tree, so **nothing unpacks per call**.
Per-`exec` cost drops from (StaticX unpack + onefile unpack + interpreter start) to
just (interpreter start). All tool code, the RPC layer, and both user-switching paths
are untouched.

**Portability scope:** dropping StaticX raises the runtime floor to the build libc.
Two variants are built per arch so both major libcs are covered:

- **glibc** (default): built on `python:3.10-slim-bullseye` (**glibc 2.31, ~2020**);
  runs on glibc Linux from ~2020 onward. Bundled into the wheel.
- **musl**: built on `python:3.10-alpine3.18` (**musl 1.2.4, ~2023**); runs on
  Alpine/musl from 3.18 onward (musl is backward-compatible, so it also runs on
  newer Alpine — e.g. the rolling `python:3-alpine` used by gdm_in_house_ctf).
  Uploaded to S3 only; fetched at runtime when a musl sandbox is detected.

Injection detects the sandbox libc (`recon._detect_libc`) and selects the matching
variant. Sub-2.31 glibc distros (Amazon Linux 2, RHEL/CentOS 7–8, Ubuntu 18.04,
Debian ≤10) remain out of scope; raise the glibc build base's age if one is needed.

## Key design decisions

- **Artifact filenames**: `inspect-sandbox-tools-{arch}[-musl]-v{N}[-dev]`. The glibc
  names are unchanged from the StaticX era; the musl variant adds a `-musl` token
  (`_build_config.py`). Contents change from an ELF to an (uncompressed) tar of the
  onedir tree. `scripts/pypi-release.py`, the CI artifact glob, and `pyproject.toml`'s
  `binaries/*` glob are content-agnostic and reference only the glibc names, so they
  bundle glibc-only with no change; `upload_to_s3.py` uploads all four (arch × libc).
- **Injection extracts a tree** instead of writing one file. Uses `tar` in the
  container (near-universal; new but mild runtime assumption). `SANDBOX_CLI` becomes
  the launcher path *inside* the extracted dir.
- **Multi-user is deliberately untouched.** The in-CLI `switch_user()` for in-process
  tools (`_cli/main.py:75-88`) and the daemon's `fork()`+`make_preexec(user)` for
  remote tools both remain exactly as-is. The only user-adjacent change is the
  injected-tree permissions (below), which preserve today's "hidden from the agent"
  property.
- **Daemon auto-restart keeps working for free.** The `exec` client is still the full
  Python CLI, so `_ensure_server_is_running()` (`_cli/main.py:111`) still lazily
  restarts a dead daemon. No host-side restart logic needed.

## Changes by area

### 0. Version bump — `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`
Bump `18` → `19`. The artifact filename is unchanged in *scheme* but its *contents*
change format (ELF → tar). A new version integer gives the new-format artifact
a fresh name (`inspect-sandbox-tools-{arch}-v19`) so a cached onefile binary in
`binaries/` or S3 can never be paired with the new tar-extracting injection logic.

### 1. Build — `src/inspect_ai/tool/_sandbox_tools_utils/_build_bundled_executable.py`
- `_build_executable`: replace `--onefile` with `--onedir`. Keep `--noupx`,
  `--optimize 2`, `--exclude-module …`, `--copy-metadata`, `--hidden-import psutil`,
  `--name`. PyInstaller now emits `dist/<name>/` (launcher + `_internal/`).
- Delete `_apply_staticx` and its call; replace the StaticX step with: **tar (uncompressed)
  the `dist/<name>/` tree to `output_path`** (the existing versioned filename). Preserve
  archived file permissions (launcher 0755, libs 0644, dirs 0755) so extraction needs
  no per-file chmod.
- `_verify_build`: drop the "fully static" ldd assertion; instead verify the launcher
  inside the tree runs and report glibc floor.

### 2. Build orchestration — `Dockerfile.pyinstaller`, `build_executable.py`
- `Dockerfile.pyinstaller`: remove the `staticx` install plus the `setuptools<82` /
  `--no-build-isolation` workaround that existed only for StaticX. Keep `pyinstaller`,
  `psutil`, `jsonrpcserver`, `pydantic`. Base stays bullseye. (`scons`/`patchelf` were
  StaticX deps — drop if unused after.)
- `build_executable.py`: no structural change; it just passes the filename through.

### 3. Injection — `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py`
- `_inject_container_tools_code`: replace the single `write_file(SANDBOX_CLI, …)` +
  `chmod` with: stream the tar into the container and extract it via
  `sandbox.exec(["tar", "xf", "-", "-C", <install_dir>], input=tar_bytes)`, then
  protect it. Use **basic flags only and an uncompressed tar** (`tar xf -`, no `z`, no
  GNU-isms) for maximum BusyBox compatibility. On a nonzero extract result, raise
  `SandboxInjectionError` with a clear message. Reuse the existing root-vs-nonroot logic:
  - root available → `chmod 700` the **containing dir** as root (hides the whole tree
    from the agent; root, the `_tools_user`, still runs the launcher), set
    `sandbox._tools_user = "root"`.
  - else → leave extracted perms (owned by the sandbox user, launcher already +x).
- `start-server` invocation (`sandbox.py:118`) and the model-proxy invocation
  (`agent/_bridge/sandbox/bridge.py:161`) are unchanged — they target `SANDBOX_CLI`,
  which now resolves to the launcher.
- `_open_executable` / `_open_executable_for_arch` / `_download_from_s3`: unchanged —
  they open the versioned filename and hand back bytes; the bytes are now a tar that
  the injector extracts.

### 4. CLI path constant — `src/inspect_ai/util/_sandbox/_cli.py`
- `SANDBOX_CLI` changes from a file path to the launcher inside the extracted dir,
  e.g. `/var/tmp/.<hash>/tools/inspect-sandbox-tools`. Keep the dot-prefixed hidden
  parent dir rationale documented there. `sandbox_file_detector(SANDBOX_CLI)` still
  works as the injection sentinel (launcher presence).

### 5. Runtime CLI — `src/inspect_sandbox_tools/.../_cli/main.py`
- `_ensure_server_is_running`: remove the `STATICX_PROG_PATH` branch. Under onedir
  frozen, `sys.executable` is the stable launcher, so spawn `[sys.executable, "server"]`
  unconditionally (no self-deleting temp problem). This is the only staticx-specific
  code here.

### 6. Runtime daemon — `src/inspect_sandbox_tools/.../_cli/server.py`  (verify, likely keep)
- The `LD_LIBRARY_PATH_ORIG` / `_MEIPASS` guard (lines 22-27) is about preventing the
  bundle's lib dir from leaking into spawned children. **`sys._MEIPASS` and the
  bootloader LD_LIBRARY_PATH behavior still exist under onedir**, so this guard most
  likely must be **kept** (only the restored value differs). Verify empirically before
  touching; do not remove without confirming children (exec_remote/bash/MCP) don't
  inherit the bundle lib path.

### 7. Distro validation — `validate_distros.py`
- `test_distro`: the artifact is now a tar, not a runnable file. Mount it,
  `tar xf` into a temp dir in the container, then run `<dir>/inspect-sandbox-tools
  healthcheck`. The distro list (all ≥ 2.31) is unchanged and should stay green.

## Optional follow-up (Phase 2): trim the `exec` import cost

Onedir removes the unpack but the `exec` process still imports `aiohttp` (via
`_cli.server`) and `pydantic` (via `load_tools`'s static tool imports) at module load.
For the common remote-tool path the process only forwards bytes to the socket. Trim by:
- lazy-importing `proxy` and `server` inside their `match args.command` branches in
  `main.py`;
- classifying in-process vs remote methods via a static `frozenset` of method names so
  the remote `exec` path forwards to the socket without importing any tool controller.

Estimated effect: ~200–400ms → ~50–150ms per `exec`. Separable; ship Phase 1 first.

## What stays unchanged (no edits)
`scripts/pypi-release.py`, `.github/workflows/build_sandbox_tools.yml` (artifact glob),
`pyproject.toml` (`binaries/*`) — all reference only the glibc names, so the wheel
bundles glibc-only automatically. All tool controllers / RPC methods, `user_switch.py`,
and both user-switching paths are untouched.

## Verification

1. **Build (local, arm64 to match host):**
   `python src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py --arch arm64`
   → confirm `binaries/inspect-sandbox-tools-arm64-v<N>-dev` is a tar of the
   onedir tree.
2. **Distro check:** `python -m inspect_ai.tool._sandbox_tools_utils.validate_distros`
   → all listed distros (≥ 2.31) pass `healthcheck` after extract.
3. **No per-call unpack:** inject into a docker sandbox; run repeated `text_editor` +
   `bash_session` calls; confirm **no new `/tmp/_MEI*` dirs per call** (today there is
   one per call) and measure end-to-end latency drop vs. `main`.
4. **Multi-user intact:** run a tool as a non-root user
   (`text_editor` with a `user=` / `bash_session` with `user=`); confirm setuid still
   works and the agent (non-root) cannot read the injected tree.
5. **Integration tests:**
   `pytest tests/tools/test_inspect_container_tools.py --runslow --local-inspect-tools`
6. **Daemon restart:** kill the daemon mid-eval; confirm the next tool call transparently
   restarts it via `_ensure_server_is_running()`.

## Wrap-up
Once the changes are implemented and verification passes, commit, push to the
`pyinstaller` branch, and open a **draft** PR against `main`.

## Open questions
- Keep Phase 2 (import trim) in scope, or ship onedir-only first and measure?
- Confirm `server.py` `LD_LIBRARY_PATH` guard behavior under onedir before any edit
  there (verification item, not assumed).
