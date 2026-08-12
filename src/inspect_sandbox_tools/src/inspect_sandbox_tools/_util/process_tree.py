import asyncio
import os
import signal
import time
from asyncio.subprocess import Process as AsyncIOProcess
from collections.abc import Iterable

import psutil


async def terminate_process_tree(
    process: AsyncIOProcess,
    timeout: float = 30,
    *,
    process_group: bool = False,
    known_descendants: Iterable[psutil.Process] = (),
) -> None:
    """Terminate a subprocess, known/discoverable descendants, and optional group members."""
    pid = getattr(process, "pid", None)
    if pid is None:
        await _terminate_without_pid(process, timeout)
        return

    root: psutil.Process | None = None
    if process.returncode is None:
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            pass
    descendants = _merge_processes(
        _live_processes(known_descendants),
        _merge_processes(
            _children(root) if root is not None else [],
            process_group_members(pid, exclude_pid=pid) if process_group else [],
        ),
    )

    deadline = asyncio.get_running_loop().time() + timeout
    for child in reversed(descendants):
        _terminate(child)
    if process_group:
        _signal_process_group(pid, signal.SIGTERM)
    if root is not None:
        _terminate(root)

    cancellation: asyncio.CancelledError | None = None
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            descendants = await _force_terminate(
                process, descendants, root, pid, process_group
            )

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        alive = await _wait_for_processes(descendants, timeout=remaining)
    except asyncio.CancelledError as ex:
        cancellation = ex
        descendants = await _force_terminate(
            process, descendants, root, pid, process_group
        )
        alive = await _wait_for_processes(descendants, timeout=5)

    if alive:
        pids = ", ".join(str(child.pid) for child in alive)
        raise RuntimeError(f"Processes did not exit after SIGKILL: {pids}")
    if cancellation is not None:
        raise cancellation


async def _terminate_without_pid(process: AsyncIOProcess, timeout: float) -> None:
    cancellation: asyncio.CancelledError | None = None
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        process.kill()
        await process.wait()
    except asyncio.CancelledError as ex:
        cancellation = ex
        process.kill()
        await process.wait()
    except ProcessLookupError:
        pass
    if cancellation is not None:
        raise cancellation


async def _force_terminate(
    process: AsyncIOProcess,
    descendants: list[psutil.Process],
    root: psutil.Process | None,
    process_group: int,
    include_process_group: bool,
) -> list[psutil.Process]:
    descendants = _refresh_processes(
        descendants, root, process_group, include_process_group
    )
    for child in reversed(descendants):
        _kill(child)
    if include_process_group:
        _signal_process_group(process_group, signal.SIGKILL)
    if root is not None:
        _kill(root)
    await process.wait()
    return descendants


async def _wait_for_processes(
    processes: list[psutil.Process], *, timeout: float, force_terminated: bool = False
) -> list[psutil.Process]:
    deadline = time.monotonic() + timeout
    alive = _live_processes(processes)
    while alive:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _, pending = await asyncio.to_thread(
            psutil.wait_procs, alive, timeout=min(remaining, 0.1)
        )
        alive = _live_processes(pending)
    if alive and not force_terminated:
        for process in alive:
            _kill(process)
        return await _wait_for_processes(alive, timeout=5, force_terminated=True)
    return alive


def _children(process: psutil.Process) -> list[psutil.Process]:
    try:
        return process.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def _live_processes(processes: Iterable[psutil.Process]) -> list[psutil.Process]:
    live: list[psutil.Process] = []
    for process in processes:
        try:
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                live.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    return live


def _merge_processes(
    existing: list[psutil.Process], discovered: list[psutil.Process]
) -> list[psutil.Process]:
    processes = {process.pid: process for process in existing}
    for process in discovered:
        processes.setdefault(process.pid, process)
    return list(processes.values())


def _refresh_processes(
    existing: list[psutil.Process],
    root: psutil.Process | None,
    process_group: int,
    include_process_group: bool,
) -> list[psutil.Process]:
    return _merge_processes(
        existing,
        _merge_processes(
            _children(root) if root is not None else [],
            process_group_members(process_group, exclude_pid=process_group)
            if include_process_group
            else [],
        ),
    )


def process_group_members(
    process_group: int, *, exclude_pid: int | None = None
) -> list[psutil.Process]:
    members: list[psutil.Process] = []
    for process in psutil.process_iter():
        if process.pid == exclude_pid:
            continue
        try:
            if os.getpgid(process.pid) == process_group:
                members.append(process)
        except (ProcessLookupError, PermissionError):
            pass
    return members


def _signal_process_group(process_group: int, sig: signal.Signals) -> None:
    try:
        os.killpg(process_group, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate(process: psutil.Process) -> None:
    try:
        process.terminate()
    except psutil.NoSuchProcess:
        pass


def _kill(process: psutil.Process) -> None:
    try:
        process.kill()
    except psutil.NoSuchProcess:
        pass
