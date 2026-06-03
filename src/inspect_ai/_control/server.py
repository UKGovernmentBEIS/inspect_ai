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

MVP scope: a single ``GET /evals`` read-only endpoint sufficient for
``inspect ctl ls`` plus a ``POST /shutdown`` route for keep-alive
release. Directives, sample-level endpoints, and event subscription
land in subsequent phases.
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

from inspect_ai._control.discovery import default_socket_path, discovery_dir
from inspect_ai._control.state import (
    current_eval_summaries,
    current_sample_summaries,
    sample_error_detail,
)
from inspect_ai._util.discovery import (
    prepare_discovery_dir,
    write_discovery_file,
)
from inspect_ai._util.sockets import lock_socket_file, prepare_socket_path

logger = getLogger(__name__)


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
        # Set by the ``POST /shutdown`` route and awaited by the
        # keep-alive park — both on this eval's loop, so a loop-native
        # ``anyio.Event`` can be awaited directly.
        self._shutdown_event = anyio.Event()

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    @property
    def shutdown_event(self) -> anyio.Event:
        """Set when ``POST /shutdown`` is received.

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
            return current_eval_summaries(started_at)

        @app.get("/evals/{eval_id}/samples")
        async def list_eval_samples(eval_id: str) -> list[dict[str, Any]]:
            return await current_sample_summaries(eval_id)

        @app.get("/evals/{eval_id}/samples/{sample_id}/{epoch}")
        async def get_sample_errors(eval_id: str, sample_id: str, epoch: int) -> Any:
            detail = await sample_error_detail(eval_id, sample_id, epoch)
            if detail is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"sample {sample_id} (epoch {epoch}) not found"},
                )
            return detail

        @app.post("/shutdown")
        async def shutdown() -> dict[str, bool]:
            shutdown_event.set()
            return {"ok": True}

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
        #      ctl` clients (and, under --keep-alive, the shutdown path that
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
                    self._serve_task.cancel()
                    try:
                        await self._serve_task
                    except (asyncio.CancelledError, Exception):
                        pass
                except (asyncio.CancelledError, Exception):
                    pass
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

    Default-on: pass ``enabled=False`` to skip the bind entirely (eg.
    via a future ``--no-ctl`` flag or ``INSPECT_CTL=false`` env var).

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
    """Block until the server receives ``POST /shutdown``.

    No-ops when ``server`` is ``None`` (bind failed; the eval ran
    without a control surface — nothing to wait on).
    """
    if server is None:
        return
    await server.shutdown_event.wait()
