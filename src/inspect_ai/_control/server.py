"""HTTP control server embedded in each running eval process.

Lifecycle matches one ``eval()`` call: the async context manager
:func:`control_server` runs uvicorn as a task on the eval's anyio
loop, lives for the duration of the eval body, and tears down on
exit. Used by both standalone ``inspect eval`` and ``inspect
eval-set`` (the latter via its single ``eval()`` call under
``retry_immediate=True``, which is the default).

Default-on with graceful degradation: bind failures (read-only
filesystem, restricted sandbox, etc.) log a warning and continue
without the surface — eval correctness never depends on the control
channel coming up. See ``design/control-channel.md`` "Implementation
notes" for the lifecycle / flag policy.

Current scope is the phase 1-2 read surface: ``GET /tasks`` (per-task
summaries), ``GET /evals/{id}/samples`` (sample listing, with an
``active_since`` recency delta), ``GET /evals/{id}/sample`` (error
detail), and ``GET /evals/{id}/sample/events`` (cursored transcript
pull) — plus ``POST /release`` / ``POST /keep`` for keep-alive control.
State-mutating directives (cancel / drain / requeue) and SSE push land
in phases 3-4.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator, NamedTuple

import anyio

from inspect_ai._control.buffer import flush_task_samples
from inspect_ai._control.discovery import default_socket_path, discovery_dir
from inspect_ai._control.events import sample_events
from inspect_ai._control.limits import (
    UnknownConcurrencyKeyError,
    process_limits,
    task_limits,
)
from inspect_ai._control.state import (
    current_eval_summaries,
    current_sample_summaries,
    sample_error_detail,
)
from inspect_ai._util.discovery import (
    prepare_discovery_dir,
    write_discovery_file,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.sockets import lock_socket_file, prepare_socket_path

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------


class CtlServerConfig(NamedTuple):
    """Resolved ``ctl_server`` configuration (see :func:`resolve_ctl_server`)."""

    enabled: bool
    """Whether the control server binds at all."""

    keep_alive: bool
    """Whether the process parks after the eval finishes."""


def resolve_ctl_server(value: bool | str | None) -> CtlServerConfig:
    """Resolve a ``ctl_server`` parameter value to a :class:`CtlServerConfig`.

    The ``ctl_server`` parameter on ``eval()`` / ``eval_set()`` (and the
    ``--ctl-server`` CLI flag) mirrors the ``--acp-server`` shape — one
    flag whose value selects the behaviour:

    - ``None`` / ``True`` — control server on (the default).
    - ``False`` — control server off.
    - ``"keep"`` — control server on, and the process parks after the eval
      finishes (until ``inspect ctl process release`` / ``POST /release``).

    The CLI spellings (``"true"`` / ``"yes"`` / ``"1"``, ``"false"`` /
    ``"no"`` / ``"0"``, case-insensitive) are accepted too, so programmatic
    callers can forward a flag or ``INSPECT_EVAL_CTL_SERVER`` env value
    verbatim. This function is the single source of truth for the value
    grammar — the ``--ctl-server`` click callback delegates here, so the CLI
    and the Python API cannot drift apart.

    Raises:
        PrerequisiteError: For any other value — an unknown string is more
            likely a typo of ``keep`` than an intentional choice, and
            silently treating it as ``True`` would drop the requested park.
    """
    if value is None or value is True:
        return CtlServerConfig(enabled=True, keep_alive=False)
    if value is False:
        return CtlServerConfig(enabled=False, keep_alive=False)
    if isinstance(value, str):
        lower = value.lower()
        if lower in ("true", "yes", "1"):
            return CtlServerConfig(enabled=True, keep_alive=False)
        if lower in ("false", "no", "0"):
            return CtlServerConfig(enabled=False, keep_alive=False)
        # `keep-alive` is still accepted as a legacy alias for `keep`.
        if lower in ("keep", "keep-alive"):
            return CtlServerConfig(enabled=True, keep_alive=True)
    raise PrerequisiteError(
        f"Unexpected ctl_server value '{value}' (expected true, false, or keep)."
    )


# ---------------------------------------------------------------------------
# Keep-alive intent
# ---------------------------------------------------------------------------

# Whether this process intends to park after the eval finishes. A single
# last-write-wins flag: set at launch (``--ctl-server=keep``) and toggled at
# runtime by ``POST /keep`` (``inspect ctl process keep`` -> on) and ``POST /release``
# (``inspect ctl process release`` -> off). Last-write-wins rather than "release is
# sticky" so that, while the eval is still running, keep -> release -> keep
# leaves the process in the keep state — each call simply overwrites the
# intent. Module-level (not per-ControlServer) because the eval-set park binds
# a FRESH server after the run's server has torn down — a per-server flag
# couldn't carry the intent across that boundary — and it's the single source
# of truth the ``/tasks`` endpoint reports as each task's keep-alive status.
# Reset at the outermost run boundary (``eval_async`` for standalone evals,
# ``eval_set`` for eval-sets).
_keep_alive = False


def request_keep_alive() -> None:
    """Latch keep-alive on — the process parks after the eval finishes."""
    global _keep_alive
    _keep_alive = True


def request_release() -> None:
    """Latch keep-alive off — the process exits when the eval finishes.

    The inverse of :func:`request_keep_alive`. Issued while the eval is still
    running it means "exit when done"; issued against a parked process it
    releases the park. A later :func:`request_keep_alive` overrides it
    (last-write-wins).
    """
    global _keep_alive
    _keep_alive = False


def keep_alive_intent() -> bool:
    """Whether this process will park after the eval finishes.

    The live value the ``/tasks`` endpoint reports per task and that the parks
    gate on — the latest of the launch flag, ``POST /keep``, and ``POST
    /release`` (last-write-wins).
    """
    return _keep_alive


def reset_keep_alive() -> None:
    """Clear the keep-alive intent (called at the outermost run boundary)."""
    global _keep_alive
    _keep_alive = False


# ---------------------------------------------------------------------------
# Control server
# ---------------------------------------------------------------------------


class ControlServer:
    """FastAPI control server for the live eval.

    One instance per ``eval()`` call. Runs uvicorn as an asyncio task
    on the caller's anyio loop; tears down when the enclosing
    ``async with`` exits.
    """

    def __init__(self, *, run_id: str) -> None:
        self._run_id = run_id
        self._started_at = time.time()
        self._socket_path: Path | None = None
        self._discovery_path: Path | None = None
        self._sock: Any = None
        self._uvicorn_server: Any = None
        self._serve_task: asyncio.Task[None] | None = None
        # Wakes the keep-alive park when ``POST /release`` clears the intent.
        # A condition (not a one-shot event) so the park can re-check the
        # intent and keep waiting after a keep that follows a release — both
        # the route and the park run on this eval's loop.
        self._park_cond = anyio.Condition()

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    async def wait_for_release(self) -> None:
        """Park until keep-alive intent is released.

        Blocks while :func:`keep_alive_intent` holds, re-checking it whenever
        ``POST /release`` wakes it (via :meth:`notify_park_change`). Returns
        immediately when the intent is already off. The loop tolerates a keep
        that re-set the intent on between the release's wake-up and this
        re-check (last-write-wins): it simply waits again.
        """
        async with self._park_cond:
            while keep_alive_intent():
                await self._park_cond.wait()

    async def notify_park_change(self) -> None:
        """Wake :meth:`wait_for_release` so it re-checks the keep-alive intent.

        Only ``POST /release`` needs this — the park exits on a transition to
        OFF, so a keep (which sets the intent ON) has nothing to wake.
        """
        async with self._park_cond:
            self._park_cond.notify_all()

    def _build_app(self) -> Any:
        """Build the FastAPI app.

        Imported lazily so module import doesn't pay the FastAPI cost
        when control is disabled.
        """
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI()
        started_at = self._started_at

        @app.exception_handler(Exception)
        async def on_error(request: Request, exc: Exception) -> JSONResponse:
            # Endpoint handlers let errors propagate; convert them here, at
            # the API boundary, into a structured response the client (CLI,
            # agent) can surface instead of a bare 500. The server log keeps
            # the full traceback.
            logger.warning(
                "Control endpoint %s failed", request.url.path, exc_info=True
            )
            return JSONResponse(
                status_code=500, content={"error": f"{type(exc).__name__}: {exc}"}
            )

        def _limits_below_one(*knobs: tuple[str, int | None]) -> JSONResponse | None:
            """400 for the first requested limit below 1, else None.

            Shared by both PATCH limits routes so the knob validation can't
            drift between them.
            """
            for label, value in knobs:
                if value is not None and value < 1:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"{label} must be >= 1 (got {value})"},
                    )
            return None

        def _key_pair_error(
            key: str | None, key_limit: int | None
        ) -> JSONResponse | None:
            """400 when only one of ``key`` / ``key_limit`` was provided.

            Shared by both PATCH limits routes. A bare ``key`` has no value to
            apply and a bare ``key_limit`` no target — either alone is a
            malformed request, not a read.
            """
            if (key is None) != (key_limit is None):
                return JSONResponse(
                    status_code=400,
                    content={"error": "key and key_limit must be provided together"},
                )
            return None

        # Folded per-task summaries (retry attempts of a task collapse into
        # one row keyed by task_id) — the wire behind `inspect ctl task list`
        # and the selector-resolution step of every other command.
        @app.get("/tasks")
        async def list_tasks() -> list[dict[str, Any]]:
            summaries = await current_eval_summaries(started_at)
            # Keep-alive is a process-level property, so every task this
            # process hosts shares it. Stamp each row with the live value
            # (which reflects a runtime `POST /keep` or `/release`, not just
            # the launch flag) so `inspect ctl task list` can report it.
            keep_alive = keep_alive_intent()
            for summary in summaries:
                summary["keep_alive"] = keep_alive
            return summaries

        @app.get("/evals/{eval_id}/samples")
        async def list_eval_samples(
            eval_id: str, active_since: float | None = None
        ) -> dict[str, Any]:
            # `active_since` (unix ts) is the recency delta: only samples that
            # started or updated since then. A filter, not a cursor. The
            # response is an `{as_of, samples}` envelope — `as_of` is stamped
            # BEFORE the listing is built, so a client feeding it back as the
            # next `active_since` can't miss changes that land mid-read.
            as_of = time.time()
            return {
                "as_of": as_of,
                "samples": await current_sample_summaries(eval_id, active_since),
            }

        # `sample_id` is a query parameter (not a path segment) here and on
        # `/sample/events`: sample ids are arbitrary strings and may contain
        # `/`, `?`, `#`, etc., which a path segment can't carry. A query param
        # is URL-encoded end to end.
        @app.get("/evals/{eval_id}/sample")
        async def get_sample_errors(
            eval_id: str, sample_id: str, epoch: int = 1
        ) -> Any:
            detail = await sample_error_detail(eval_id, sample_id, epoch)
            if detail is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"sample {sample_id} (epoch {epoch}) not found"},
                )
            return detail

        # Per-sample transcript events, cursored pull (phase 2). `type` is a
        # comma-separated event-type filter (`*` = all; omitted = high-signal
        # tier); `since` is an opaque cursor, `tail` an int, `full` a bool,
        # `since_time`/`until` a wall-clock window.
        @app.get("/evals/{eval_id}/sample/events")
        async def get_sample_events(
            eval_id: str,
            sample_id: str,
            epoch: int = 1,
            since: str | None = None,
            tail: int | None = None,
            type: str | None = None,
            full: bool = False,
            since_time: float | None = None,
            until: float | None = None,
        ) -> Any:
            # strip whitespace around the comma-separated members so natural
            # spellings like `--type "model, tool"` don't silently match
            # nothing
            types = (
                frozenset(t for t in (p.strip() for p in type.split(",")) if t)
                if type is not None
                else None
            )
            page = await sample_events(
                eval_id,
                sample_id,
                epoch,
                since=since,
                tail=tail,
                types=types,
                full=full,
                since_time=since_time,
                until=until,
            )
            if page is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"sample {sample_id} (epoch {epoch}) not found"},
                )
            return page

        # Flush the task's buffered completed samples to the (possibly remote,
        # eg. S3) log now, so they're readable without waiting for the flush
        # buffer to fill. Keyed by task_id (resolved to the latest attempt),
        # matching the CLI's `ctl task log-flush`. Idempotent — a flush with
        # nothing pending writes nothing and reports `flushed: 0`.
        @app.post("/tasks/{task_id}/log-flush")
        async def log_flush(task_id: str) -> Any:
            result = await flush_task_samples(task_id)
            if result is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"task {task_id} not found or not flushable"},
                )
            return result

        # Read the process-global concurrency limits (max_sandboxes /
        # max_connections) without naming an eval — the common case for viewing
        # or throttling a whole process. No max_samples (that's per-task; use
        # the /tasks/<task-id>/config routes for it).
        @app.get("/config")
        async def get_process_limits(model: str | None = None) -> Any:
            return await process_limits(model=model)

        # Retune the process-global limits. Omitting all set values makes this a
        # read, like GET. `model` filters the adaptive controllers (name start or
        # after a `/`); `key`/`key_limit` retune a named concurrency() registry
        # entry by exact name (400 for a name with no entry — named limits are
        # created lazily on first use). `dry_run=true` reports the intended
        # change without applying it. Never 404s — a process always exists.
        @app.patch("/config")
        async def patch_process_limits(
            max_sandboxes: int | None = None,
            max_connections: int | None = None,
            model: str | None = None,
            key: str | None = None,
            key_limit: int | None = None,
            dry_run: bool = False,
        ) -> Any:
            if error := _limits_below_one(
                ("max_sandboxes", max_sandboxes),
                ("max_connections", max_connections),
                ("key_limit", key_limit),
            ):
                return error
            if error := _key_pair_error(key, key_limit):
                return error
            try:
                return await process_limits(
                    max_sandboxes=max_sandboxes,
                    max_connections=max_connections,
                    model=model,
                    key=key,
                    key_limit=key_limit,
                    dry_run=dry_run,
                )
            except UnknownConcurrencyKeyError as exc:
                return JSONResponse(status_code=400, content={"error": str(exc)})

        # Read the task's retunable config (max_samples / max_sandboxes /
        # max_connections plus the log_buffer / log_shared buffer params).
        # Keyed by task_id — stable across retry attempts, matching the knobs'
        # own scope (max_samples and the buffer params are task-scoped; the
        # other knobs process-wide) — where a per-attempt eval id would go
        # stale on every retry. A pure read — the companion PATCH applies
        # changes. `model` filters the adaptive controllers shown.
        @app.get("/tasks/{task_id}/config")
        async def get_limits(task_id: str, model: str | None = None) -> Any:
            result = await task_limits(task_id, model=model)
            if result is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"task {task_id} not found"},
                )
            return result

        # Retune the task's config. All knobs are optional query params —
        # omitting all makes this a read, like GET. `dry_run=true` validates
        # and reports the intended change without applying it (the phase-3
        # agent-shape constraint). Idempotent: re-applying the same value is a
        # no-op. Returns the resulting config view (with any warnings for a
        # knob that isn't adjustable for this task).
        @app.patch("/tasks/{task_id}/config")
        async def patch_limits(
            task_id: str,
            max_samples: int | None = None,
            max_sandboxes: int | None = None,
            max_connections: int | None = None,
            model: str | None = None,
            key: str | None = None,
            key_limit: int | None = None,
            log_buffer: int | None = None,
            log_shared: int | None = None,
            dry_run: bool = False,
        ) -> Any:
            if error := _limits_below_one(
                ("max_samples", max_samples),
                ("max_sandboxes", max_sandboxes),
                ("max_connections", max_connections),
                ("key_limit", key_limit),
                ("log_buffer", log_buffer),
                ("log_shared", log_shared),
            ):
                return error
            if error := _key_pair_error(key, key_limit):
                return error
            try:
                result = await task_limits(
                    task_id,
                    max_samples=max_samples,
                    max_sandboxes=max_sandboxes,
                    max_connections=max_connections,
                    model=model,
                    key=key,
                    key_limit=key_limit,
                    log_buffer=log_buffer,
                    log_shared=log_shared,
                    dry_run=dry_run,
                )
            except UnknownConcurrencyKeyError as exc:
                return JSONResponse(status_code=400, content={"error": str(exc)})
            if result is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"task {task_id} not found"},
                )
            return result

        # Latches keep-alive OFF for the process (the inverse of /keep) and
        # wakes the park: a parked process exits, and a release received while
        # the eval is still running means "exit when done". Last-write-wins —
        # a later /keep overrides it. Named "release" rather than "shutdown"
        # because it does NOT cancel a running eval — that's a later-phase
        # directive.
        @app.post("/release")
        async def release() -> dict[str, bool]:
            # `changed` lets the client report applied vs the idempotent
            # already-in-that-state no-op (the agent output contract).
            changed = keep_alive_intent()
            request_release()
            await self.notify_park_change()
            return {"ok": True, "keep_alive": False, "changed": changed}

        # Latches keep-alive ON for the process (the inverse of /release): it
        # parks after the eval finishes instead of exiting, even if launched
        # without `--ctl-server=keep`. Effective any time before the eval
        # finishes. No park wake-up needed — the park only exits on a
        # transition to OFF, so setting the intent ON is all a keep must do
        # (a keep that follows a release just leaves the intent ON for the
        # park to honour).
        @app.post("/keep")
        async def keep() -> dict[str, bool]:
            changed = not keep_alive_intent()
            request_keep_alive()
            return {"ok": True, "keep_alive": True, "changed": changed}

        return app

    async def start(self) -> None:
        """Bind the AF_UNIX socket, write the discovery file, start serving."""
        import socket

        import uvicorn

        # Lock dir to 0700 + sweep stale entries.
        prepare_discovery_dir(discovery_dir())

        socket_path = default_socket_path(os.getpid())
        prepare_socket_path(socket_path)

        # Bind the listening socket ourselves and hand it to uvicorn
        # pre-bound (`serve(sockets=[...])`), rather than letting uvicorn
        # bind it asynchronously inside serve(). Two reasons:
        #   1. The bind is synchronous, so a failure (eg. a UDS
        #      PermissionError) raises *here* — before we publish the
        #      discovery file. We never advertise a `<pid>.json` pointing at
        #      a socket that isn't accepting, which would strand `inspect
        #      ctl` clients (and, under a keep-alive park, the shutdown path that
        #      releases the park). The raise propagates to `control_server`,
        #      which degrades to "no control surface".
        #   2. No readiness poll. A bound, listening socket already accepts
        #      connects (the OS holds them in the listen backlog) the moment
        #      we start serving, so the surface is reachable as soon as
        #      discovery is published — no need to wait on uvicorn's
        #      `started` flag. (Mirrors the ACP server, which awaits
        #      `asyncio.start_unix_server` directly.)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(socket_path))
            sock.listen()
        except BaseException:
            sock.close()
            raise
        self._sock = sock
        self._socket_path = socket_path
        lock_socket_file(socket_path)

        app = self._build_app()
        config = uvicorn.Config(
            app,
            log_config=None,
            log_level="warning",
            access_log=False,
            timeout_keep_alive=5,
        )
        server = uvicorn.Server(config)
        # Suppress uvicorn's signal handler installation — we're an
        # embedded server, not the main process, so SIGINT/SIGTERM
        # should not be intercepted here.
        server.install_signal_handlers = lambda: None  # type: ignore[attr-defined,method-assign]
        self._uvicorn_server = server
        self._serve_task = asyncio.create_task(
            server.serve(sockets=[sock]), name="inspect-ctl-server"
        )

        self._discovery_path = write_discovery_file(
            discovery_dir(),
            os.getpid(),
            {
                "pid": os.getpid(),
                "run_id": self._run_id,
                "socket_path": str(socket_path),
                "started_at": self._started_at,
            },
        )

    def _unlink_socket(self) -> None:
        if self._socket_path is not None:
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def stop(self) -> None:
        """Signal shutdown, await drain, remove discovery files."""
        try:
            if self._uvicorn_server is not None:
                self._uvicorn_server.should_exit = True
            if self._serve_task is not None and not self._serve_task.done():
                try:
                    await asyncio.wait_for(self._serve_task, timeout=5.0)
                except asyncio.TimeoutError:
                    # Didn't drain within the grace period — force-cancel and reap.
                    self._serve_task.cancel()
                    try:
                        await self._serve_task
                    except asyncio.CancelledError:
                        pass  # expected: we just cancelled it
                    except Exception:
                        logger.warning(
                            "Control server task raised while being cancelled "
                            "during shutdown",
                            exc_info=True,
                        )
                except asyncio.CancelledError:
                    # The eval's cancel scope is tearing down (eg. a Ctrl-C with
                    # samples in flight) — `wait_for` cancels and reaps the serve
                    # task, then propagates the cancellation. This is an expected
                    # teardown, not a server fault, so re-raise it to keep
                    # structured cancellation intact rather than logging a
                    # misleading "did not shut down cleanly" warning. The
                    # `finally` below still runs, so discovery/socket cleanup
                    # happens regardless.
                    raise
                except Exception:
                    # serve() raised (rather than draining cleanly or being
                    # cancelled) instead of shutting down — a genuine unclean
                    # shutdown. Best-effort teardown: log and fall through to the
                    # discovery/socket cleanup in `finally` rather than masking
                    # it silently.
                    logger.warning(
                        "Control server did not shut down cleanly", exc_info=True
                    )
        finally:
            if self._discovery_path is not None:
                try:
                    self._discovery_path.unlink(missing_ok=True)
                except OSError:
                    pass
            # uvicorn closes the sockets it was handed on shutdown; close
            # ours too in case serve() was cancelled before it got there
            # (double close is harmless).
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
            self._unlink_socket()


@asynccontextmanager
async def control_server(
    *,
    run_id: str,
    enabled: bool = True,
) -> AsyncIterator[ControlServer | None]:
    """Start (and stop) the control HTTP server for one eval run.

    Default-on: pass ``enabled=False`` to skip the bind entirely (the
    ``ctl_server=False`` / ``--ctl-server=false`` path).

    Bind failures are logged and swallowed — yields ``None`` and the
    eval runs without the control surface. Eval correctness never
    depends on the control channel coming up.
    """
    if not enabled:
        yield None
        return

    server = ControlServer(run_id=run_id)
    try:
        await server.start()
    except Exception as exc:
        logger.warning(
            "Control server failed to start (eval will run without "
            "control surface): %s",
            exc,
        )
        # start() may have partially succeeded — it binds the socket and
        # launches the uvicorn serve task BEFORE writing the discovery file, so
        # a later-stage failure (eg. the discovery write) leaves a running task
        # + live socket node behind. Tear that down rather than leak it. stop()
        # is None-safe at every partial stage.
        try:
            await server.stop()
        except Exception:
            logger.exception("Error cleaning up partially-started control server")
        yield None
        return

    try:
        yield server
    finally:
        try:
            await server.stop()
        except Exception:
            logger.exception("Error stopping control server")


# ---------------------------------------------------------------------------
# Keep-alive wait helper
# ---------------------------------------------------------------------------


async def wait_for_shutdown_async(server: ControlServer | None) -> None:
    """Park until keep-alive is released (``POST /release`` or intent off).

    Returns immediately when ``server`` is ``None`` (the bind failed and the
    eval ran without a control surface — nothing to wait on) or when the
    keep-alive intent is already off. Otherwise delegates to
    :meth:`ControlServer.wait_for_release`.
    """
    if server is None:
        return
    await server.wait_for_release()
