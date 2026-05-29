"""HTTP control server embedded in each running eval process.

Two flavours of lifecycle, both built on the same bind / serve /
cleanup core (:class:`_ControlServerBase`):

- :func:`control_server` — async context manager scoped to one
  ``eval()`` call. Runs uvicorn as a task on the caller's anyio loop.
  Used for standalone ``inspect eval`` invocations.
- :func:`control_server_for_eval_set` — sync context manager scoped
  to one ``eval_set()`` call. Runs uvicorn in a daemon thread with
  its own asyncio loop, so it outlives the multiple per-attempt
  ``eval()`` event loops created via tenacity retries.

The two are mutually exclusive within one process. When the eval-set
flavour is active, the per-eval flavour detects that (via a
thread-local marker) and yields ``None`` without binding — there's
only ever one socket per process.

Default-on with graceful degradation: bind failures (read-only
filesystem, restricted sandbox, etc.) log a warning and continue
without the surface — eval correctness never depends on the control
channel coming up. See design/control-channel.md "Implementation
notes" for the lifecycle / flag policy.

MVP scope: a single ``GET /evals`` read-only endpoint sufficient for
``inspect ctl ls``. Directives, sample-level endpoints, and event
subscription land in subsequent phases.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from logging import getLogger
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

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
# Outer-scope ownership marker
# ---------------------------------------------------------------------------
#
# When an eval-set has opened its own (threaded) control server,
# nested ``eval()`` calls within that set must NOT bind their own
# server — they'd collide on the PID-keyed paths. The thread-local
# flag below is set by :func:`control_server_for_eval_set` and
# inspected by :func:`control_server`.
#
# Thread-local (not module-global) so concurrent eval-sets in
# different threads stay isolated — not a likely use case but it
# costs nothing.

_outer_owner = threading.local()


def _outer_scope_owns_server() -> bool:
    return getattr(_outer_owner, "active", False)


def _set_outer_scope_owns_server(value: bool) -> None:
    _outer_owner.active = value


# ---------------------------------------------------------------------------
# Keep-alive support
# ---------------------------------------------------------------------------
#
# When an eval / eval-set is launched with ``keep_alive=True``, the
# process should stay running after the eval body completes so
# external agents can read state, request logs, and explicitly tear
# the process down. The per-process flag below is consulted by
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

    Called by the eval / eval-set entry points before the eval body
    runs, and cleared after the shutdown wait ends.
    """
    global _keep_alive_active
    _keep_alive_active = value


# ---------------------------------------------------------------------------
# Shared bind / serve / cleanup core
# ---------------------------------------------------------------------------


class _ControlServerBase:
    """Bind / serve / cleanup logic shared by both server lifecycle flavors.

    Subclasses provide the lifecycle driver — async context manager
    on the caller's loop (:class:`ControlServer`), or daemon thread
    with its own loop (:class:`ThreadedControlServer`). The base
    class owns all the uvicorn / filesystem / discovery details so
    those don't drift between flavors.
    """

    def __init__(self, payload_extra: dict[str, Any]) -> None:
        self._payload_extra = payload_extra
        self._started_at = time.time()
        self._socket_path: Path | None = None
        self._discovery_path: Path | None = None
        self._uvicorn_server: Any = None
        # Signaled by ``POST /shutdown``. Used by keep-alive to know
        # when the operator (or an agent) wants to release the
        # lingering process. ``threading.Event`` (not asyncio.Event)
        # so both the per-eval async waiter and the eval-set sync
        # waiter can listen on the same primitive.
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
            # Operator-requested release of a keep-alive process.
            # Setting the event unblocks waiters in eval/eval_set
            # (see :func:`wait_for_shutdown`). No-op if no caller is
            # actually waiting — the process just exits when the eval
            # body returns naturally.
            shutdown_event.set()
            return {"ok": True}

        return app

    async def _bind_and_publish(self) -> asyncio.Task[None]:
        """Bind uvicorn, wait for started, chmod, publish discovery file.

        Runs on the current event loop. Returns the serve task so the
        caller can either leave it running (per-eval async variant) or
        await it (threaded variant).
        """
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

        serve_task = asyncio.create_task(server.serve(), name="inspect-ctl-server")

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
                "socket_path": str(socket_path),
                "started_at": self._started_at,
                **self._payload_extra,
            },
        )

        return serve_task

    def _request_shutdown(self) -> None:
        """Flip uvicorn's ``should_exit`` flag.

        Cross-thread callers must run this on the worker loop via
        :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`.
        """
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True

    def _cleanup_files(self) -> None:
        """Remove the discovery JSON + AF_UNIX socket node. Best-effort."""
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


# ---------------------------------------------------------------------------
# Per-eval control server (async, runs on caller's loop)
# ---------------------------------------------------------------------------


class ControlServer(_ControlServerBase):
    """Control server with one-``eval()``-call lifetime.

    Runs uvicorn as a task on the caller's anyio loop. When the
    enclosing ``async with`` exits, we flip ``should_exit`` and await
    the serve task to drain.
    """

    def __init__(self, *, run_id: str) -> None:
        super().__init__(payload_extra={"run_id": run_id})
        self._run_id = run_id
        self._serve_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Bind + publish; leave serve task running."""
        self._serve_task = await self._bind_and_publish()

    async def stop(self) -> None:
        """Signal shutdown, await drain, remove discovery files."""
        try:
            self._request_shutdown()
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
            self._cleanup_files()


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

    Also yields ``None`` (without binding) when an outer scope —
    typically :func:`control_server_for_eval_set` for an eval-set
    spanning retries — has already opened a control server in this
    process. The PID-keyed socket path can only host one server at a
    time.
    """
    if not enabled:
        yield None
        return

    if _outer_scope_owns_server():
        # Outer (eval-set) scope owns the socket; bind nothing.
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
# Eval-set-scoped control server (threaded, own loop)
# ---------------------------------------------------------------------------


class ThreadedControlServer(_ControlServerBase):
    """Control server with eval-set lifetime.

    Runs uvicorn in a daemon thread with its own asyncio event loop.
    Outlives the multiple per-attempt ``eval()`` calls inside an
    eval-set, each of which spins up its own anyio loop and would
    otherwise tear the per-eval server down between attempts.

    Lifecycle is sync (:meth:`start` / :meth:`stop`) so it composes
    with eval-set's synchronous body + tenacity retries without
    forcing the caller to be async.
    """

    def __init__(self, *, eval_set_id: str | None = None) -> None:
        super().__init__(payload_extra={"eval_set_id": eval_set_id})
        self._eval_set_id = eval_set_id
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_lifecycle())
        except BaseException as exc:
            self._error = exc
            # Unblock the spawning thread even on failure so start()
            # raises rather than hanging.
            self._ready.set()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _async_lifecycle(self) -> None:
        serve_task = await self._bind_and_publish()
        # Signal the spawning thread before blocking on serve.
        self._ready.set()
        await serve_task

    def start(self) -> None:
        """Spawn the worker thread and wait until the server is bound."""
        self._thread = threading.Thread(
            target=self._thread_main,
            name="inspect-ctl-server",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            raise RuntimeError("Control server didn't become ready within 10s")
        if self._error is not None:
            raise RuntimeError(
                f"Control server thread failed: {self._error!r}"
            ) from self._error

    def stop(self) -> None:
        """Signal shutdown across the thread boundary, join, cleanup."""
        try:
            if self._uvicorn_server is not None and self._loop is not None:
                # Flip should_exit on the worker thread's loop (we
                # can't touch the uvicorn server state from this
                # thread directly).
                try:
                    self._loop.call_soon_threadsafe(self._request_shutdown)
                except RuntimeError:
                    # Loop already closed — worker thread already exited.
                    pass
            if self._thread is not None:
                self._thread.join(timeout=10.0)
        finally:
            self._cleanup_files()


@contextmanager
def control_server_for_eval_set(
    *,
    eval_set_id: str | None = None,
    enabled: bool = True,
) -> Iterator[ThreadedControlServer | None]:
    """Sync context manager: control server scoped to one eval-set.

    Opens a daemon-thread uvicorn server before the eval-set body
    runs (including all tenacity retries), tears it down on exit.
    Sets the outer-scope marker so nested per-eval ``control_server``
    invocations skip their own bind.

    Default-on with graceful degradation: bind failures log a warning
    and yield ``None`` (the eval-set runs normally; only the control
    surface is missing).
    """
    if not enabled:
        yield None
        return

    server = ThreadedControlServer(eval_set_id=eval_set_id)
    try:
        server.start()
    except Exception as exc:
        logger.warning(
            "Control server (eval-set) failed to start (eval-set will "
            "run without control surface): %s",
            exc,
        )
        yield None
        return

    # Mark the outer scope as owning the server BEFORE yielding so any
    # nested eval() that opens control_server() detects it and skips.
    _set_outer_scope_owns_server(True)
    try:
        yield server
    finally:
        _set_outer_scope_owns_server(False)
        with contextlib.suppress(Exception):
            server.stop()


# ---------------------------------------------------------------------------
# Keep-alive wait helpers
# ---------------------------------------------------------------------------


def wait_for_shutdown_sync(server: _ControlServerBase | None) -> None:
    """Block (sync) until the server receives ``POST /shutdown``.

    No-ops when ``server`` is ``None`` (bind failed; the eval ran
    without a control surface — nothing to wait on). Used by
    :func:`eval_set` for keep-alive mode.

    Ctrl+C (KeyboardInterrupt) is *not* caught here — letting it
    propagate runs the surrounding ``with`` / ``finally`` cleanup
    (clear EvalStates, stop server, unlink files) on the way out,
    which is exactly the teardown we want. Suppressing it would just
    hide the signal from any outer code that might care.
    """
    if server is None:
        return
    server.shutdown_event.wait()


async def wait_for_shutdown_async(server: _ControlServerBase | None) -> None:
    """Block (async) until the server receives ``POST /shutdown``.

    Bridges the threading.Event to the caller's async loop via a
    worker thread so we don't pin the event loop in a blocking wait.
    Ctrl+C handling: same as :func:`wait_for_shutdown_sync` — let it
    propagate so the eval-set / eval teardown runs naturally.
    """
    if server is None:
        return
    import anyio

    await anyio.to_thread.run_sync(
        server.shutdown_event.wait,
        abandon_on_cancel=True,
    )
