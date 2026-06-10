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

Current scope is the phase 1-2 read surface: ``GET /evals`` (per-task
summaries), ``GET /evals/{id}/samples`` (sample listing, with an
``active_since`` recency delta), ``GET /evals/{id}/sample`` (error
detail), and ``GET /evals/{id}/sample/events`` (cursored transcript
pull) — plus ``POST /release`` for keep-alive release. State-mutating
directives (cancel / drain / requeue) and SSE push land in phases 3-4.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
from pydantic import BaseModel

from inspect_ai._control.discovery import default_socket_path, discovery_dir
from inspect_ai._control.events import sample_events
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


class AddTaskRequest(BaseModel):
    """Body of ``POST /evals`` — a task spec to add to the running eval.

    Module-level (not nested in the route) so FastAPI can resolve the body
    annotation when the module uses ``from __future__ import annotations``.
    """

    task: str
    task_args: dict[str, Any] | str | None = None
    model: str | None = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------


def resolve_ctl_server(value: bool | str | None) -> tuple[bool, bool]:
    """Resolve a ``ctl_server`` parameter value to ``(enabled, keep_alive)``.

    The ``ctl_server`` parameter on ``eval()`` / ``eval_set()`` (and the
    ``--ctl-server`` CLI flag) mirrors the ``--acp-server`` shape — one
    flag whose value selects the behaviour:

    - ``None`` / ``True`` — control server on (the default).
    - ``False`` — control server off.
    - ``"keep-alive"`` — control server on, and the process parks after
      the eval finishes (until ``inspect ctl release`` / ``POST /release``).

    The CLI spellings (``"true"`` / ``"yes"`` / ``"1"``, ``"false"`` /
    ``"no"`` / ``"0"``, case-insensitive) are accepted too, so programmatic
    callers can forward a flag or ``INSPECT_EVAL_CTL_SERVER`` env value
    verbatim. This function is the single source of truth for the value
    grammar — the ``--ctl-server`` click callback delegates here, so the CLI
    and the Python API cannot drift apart.

    Raises:
        PrerequisiteError: For any other value — an unknown string is more
            likely a typo of ``keep-alive`` than an intentional choice, and
            silently treating it as ``True`` would drop the requested park.
    """
    if value is None or value is True:
        return True, False
    if value is False:
        return False, False
    if isinstance(value, str):
        lower = value.lower()
        if lower in ("true", "yes", "1"):
            return True, False
        if lower in ("false", "no", "0"):
            return False, False
        if lower == "keep-alive":
            return True, True
    raise PrerequisiteError(
        f"Unexpected ctl_server value '{value}' (expected true, false, or keep-alive)."
    )


# ---------------------------------------------------------------------------
# Release latch
# ---------------------------------------------------------------------------

# Whether ``POST /release`` has been received during this run. Release is a
# process-level latch, not a park-only signal: a release issued while the
# eval is still running means "exit when done", so a later keep-alive park
# must be skipped rather than ignoring the request. Module-level (rather
# than per-ControlServer) because the eval-set park binds a FRESH server
# after the run's server has torn down — a per-server event can't carry the
# request across that boundary. Reset at the outermost run boundary
# (``eval_async`` for standalone evals, ``eval_set`` for eval-sets).
_release_requested = False


def request_release() -> None:
    """Latch a release request for this run (see ``_release_requested``)."""
    global _release_requested
    _release_requested = True


def release_requested() -> bool:
    """Whether a release has been requested during this run."""
    return _release_requested


def reset_release_requested() -> None:
    """Clear the release latch (called at the outermost run boundary)."""
    global _release_requested
    _release_requested = False


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
        # Set by the ``POST /release`` route and awaited by the
        # keep-alive park — both on this eval's loop, so a loop-native
        # ``anyio.Event`` can be awaited directly.
        self._shutdown_event = anyio.Event()

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    @property
    def shutdown_event(self) -> anyio.Event:
        """Set when ``POST /release`` is received.

        Keep-alive callers await this event to know when the operator
        wants the process to exit.
        """
        return self._shutdown_event

    def _build_app(self) -> Any:
        """Build the FastAPI app.

        Imported lazily so module import doesn't pay the FastAPI cost
        when control is disabled.
        """
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI()
        started_at = self._started_at
        shutdown_event = self._shutdown_event

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

        @app.get("/evals")
        async def list_evals() -> list[dict[str, Any]]:
            return await current_eval_summaries(started_at)

        @app.get("/evals/{eval_id}/samples")
        async def list_eval_samples(
            eval_id: str, active_since: float | None = None
        ) -> list[dict[str, Any]]:
            # `active_since` (unix ts) is the recency delta: only samples that
            # started or updated since then. A filter, not a cursor.
            return await current_sample_summaries(eval_id, active_since)

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

        # Releases a keep-alive park (sets the shutdown event the park
        # awaits); the process then exits. Release LATCHES: received while
        # the eval is still running, it means "exit when done" — a later
        # keep-alive park is skipped (see the release latch above). Named
        # "release" rather than "shutdown" because it does NOT cancel a
        # running eval — that's a later-phase directive.
        @app.post("/release")
        async def release() -> dict[str, bool]:
            request_release()
            shutdown_event.set()
            return {"ok": True}

        # Add a task to the running eval (phase 3). Submits a task spec that
        # runs in this process under the same run_id and appears as a new
        # sibling eval in `ls`. Only honored for an addable run (launched
        # `--ctl-server=keep-alive`) — otherwise 409. A spec that can't be resolved
        # (unknown task / bad args) is a 400. `dry_run` validates + reports
        # without starting work. (`AddTaskRequest` is module-level so FastAPI
        # can resolve the body annotation under `from __future__ import
        # annotations`.)
        @app.post("/evals")
        async def add_eval(body: AddTaskRequest) -> Any:
            from inspect_ai._control.run_control import add_task

            try:
                report = add_task(
                    body.task, body.task_args, body.model, dry_run=body.dry_run
                )
            except ValueError as ex:
                return JSONResponse(status_code=400, content={"error": str(ex)})
            if report is None:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "This eval is not accepting added tasks "
                        "(launch it with --ctl-server=keep-alive)."
                    },
                )
            return report

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
                except (asyncio.CancelledError, Exception):
                    # serve() failed (or was cancelled) instead of draining
                    # cleanly. Best-effort teardown: log and fall through to the
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
    """Block until the server receives ``POST /release``.

    Returns immediately when a release was already latched during the run
    (release means "exit when done", even when it arrives before the park)
    and when ``server`` is ``None`` (bind failed; the eval ran without a
    control surface — nothing to wait on).
    """
    if server is None or release_requested():
        return
    await server.shutdown_event.wait()
