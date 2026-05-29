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
import threading
import time
from contextlib import asynccontextmanager
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator

from inspect_ai._control.discovery import default_socket_path, discovery_dir
from inspect_ai._control.state import current_eval_summaries
from inspect_ai._util.discovery import (
    DISCOVERY_FILE_MODE,
    prepare_discovery_dir,
    write_discovery_file,
)

# Socket file permissions: owner-only read/write. Mirrors
# DISCOVERY_FILE_MODE for the .json — same threat model (defence in
# depth against a misconfigured / world-traversable parent directory).
SOCKET_FILE_MODE = DISCOVERY_FILE_MODE

# How long to wait for uvicorn to report ``started`` after creating
# the serve task. 5s at 50ms tick — comfortably over typical startup.
_READY_TICK_SECONDS = 0.05
_READY_TICK_COUNT = 100

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Keep-alive support
# ---------------------------------------------------------------------------
#
# When an eval / eval-set is launched with ``keep_alive=True``, the
# process should stay running after the eval body completes so
# external agents can read state, request logs, and explicitly tear
# the process down. The process-level flag below is consulted by
# ``task_run.py`` to skip its ``unregister_eval`` call so EvalState
# entries persist and stay visible via ``inspect ctl ls``.

_keep_alive_active = False


def keep_alive_active() -> bool:
    """Return whether keep-alive mode is currently in effect.

    Consumed by ``task_run.py``'s teardown logic to decide whether to
    unregister an eval's :class:`EvalState` at task end (skipped under
    keep-alive so the eval stays visible in ``inspect ctl ls``).
    """
    return _keep_alive_active


def set_keep_alive_active(value: bool) -> None:
    """Set the process-level keep-alive flag.

    Called by the eval entry point before the eval body runs, and
    cleared after the shutdown wait ends.
    """
    global _keep_alive_active
    _keep_alive_active = value


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
        self._uvicorn_server: Any = None
        self._serve_task: asyncio.Task[None] | None = None
        # Signaled by ``POST /shutdown``. Used by keep-alive to know
        # when the operator (or an agent) wants the lingering process
        # to exit. ``threading.Event`` so :func:`wait_for_shutdown_async`
        # can park on it via ``anyio.to_thread.run_sync`` without
        # blocking the eval loop.
        self._shutdown_event = threading.Event()

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    @property
    def shutdown_event(self) -> threading.Event:
        """Set when ``POST /shutdown`` is received.

        Keep-alive callers block on this event to know when the
        operator wants the process to exit.
        """
        return self._shutdown_event

    def _build_app(self) -> Any:
        """Build the FastAPI app.

        Imported lazily so module import doesn't pay the FastAPI cost
        when control is disabled.
        """
        from fastapi import FastAPI

        app = FastAPI()
        started_at = self._started_at
        shutdown_event = self._shutdown_event

        @app.get("/evals")
        async def list_evals() -> list[dict[str, Any]]:
            return current_eval_summaries(started_at)

        @app.post("/shutdown")
        async def shutdown() -> dict[str, bool]:
            shutdown_event.set()
            return {"ok": True}

        return app

    async def start(self) -> None:
        """Bind the AF_UNIX socket, write the discovery file, start serving."""
        import uvicorn

        # Lock dir to 0700 + sweep stale entries.
        prepare_discovery_dir(discovery_dir())

        socket_path = default_socket_path(os.getpid())
        if socket_path.exists() or socket_path.is_symlink():
            try:
                socket_path.unlink(missing_ok=True)
            except OSError:
                pass

        app = self._build_app()
        config = uvicorn.Config(
            app,
            uds=str(socket_path),
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

        self._socket_path = socket_path
        self._uvicorn_server = server
        self._serve_task = asyncio.create_task(
            server.serve(), name="inspect-ctl-server"
        )

        # Wait until uvicorn reports started so the discovery file is
        # only published after the socket is actually accepting.
        for _ in range(_READY_TICK_COUNT):
            if server.started:
                break
            await asyncio.sleep(_READY_TICK_SECONDS)

        # Lock the socket file to owner-only. Defence-in-depth: the
        # parent dir is already 0700, but if it's ever loosened (or
        # the user's home is world-traversable) the socket itself
        # remains unreachable. Some filesystems ignore chmod; that's
        # acceptable — same fallback behavior as the directory chmod
        # in prepare_discovery_dir.
        try:
            socket_path.chmod(SOCKET_FILE_MODE)
        except OSError:
            pass

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
            if self._socket_path is not None:
                try:
                    self._socket_path.unlink(missing_ok=True)
                except OSError:
                    pass


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

    Bridges the threading.Event to the caller's async loop via a
    worker thread so we don't pin the event loop in a blocking wait.
    Ctrl+C (KeyboardInterrupt) propagates naturally — the eval's
    ``async with`` / ``finally`` cleanup runs on the way out.
    """
    if server is None:
        return
    import anyio

    await anyio.to_thread.run_sync(
        server.shutdown_event.wait,
        abandon_on_cancel=True,
    )
