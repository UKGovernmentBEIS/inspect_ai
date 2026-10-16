"""A ``SandboxEnvironment`` fake that runs ``exec`` on the host shell.

File APIs map to host paths and ``user="root"`` is ignored, so code whose
in-sandbox side is plain ``sh`` (tar, dd, find, comm, restic-as-a-binary)
executes for real against a temp dir — no Docker required. Framework
commands pin ``PATH`` to the system directories; the checkpoint
``conftest`` points that pin at :func:`sandbox_path`, whose ``tar``
writes what a Linux sandbox's tar writes (see :func:`linux_like_path`).
"""

from __future__ import annotations

import atexit
import functools
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Union, overload

from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult

_BSDTAR_SHIM = """#!/bin/sh
# bsdtar's default format adds PAX headers (nanosecond mtimes, extended
# attributes) and AppleDouble members that GNU and busybox tar never write;
# create archives the way a Linux sandbox's tar does.
case "$1" in
  -c*|c*|--create) exec {tar} --format gnutar --no-xattrs --no-mac-metadata "$@" ;;
esac
exec {tar} "$@"
"""


def linux_like_path(host_path: str, shim_dir: Path) -> str:
    """``host_path``, with a ``tar`` in ``shim_dir`` first when the host tar is bsdtar.

    A Linux sandbox's tar (GNU or busybox) writes plain ustar and GNU
    long headers. macOS ships bsdtar, whose default format adds a PAX
    header to any member with a nanosecond mtime or an extended
    attribute (every file on macOS carries ``com.apple.provenance``),
    which the restore-scope header scan refuses. When the ``tar`` on
    ``host_path`` reports itself as bsdtar, a shim that creates archives
    in GNU format without xattrs or AppleDouble members and passes every
    other invocation through is written to ``shim_dir``; otherwise
    ``host_path`` comes back unchanged and nothing is written.
    """
    tar = shutil.which("tar", path=host_path)
    if tar is None:
        return host_path
    version = subprocess.run([tar, "--version"], capture_output=True, text=True)
    if not version.stdout.startswith("bsdtar"):
        return host_path
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "tar"
    shim.write_text(_BSDTAR_SHIM.format(tar=shlex.quote(tar)))
    shim.chmod(0o755)
    return f"{shim_dir}{os.pathsep}{host_path}"


@functools.lru_cache(maxsize=None)
def sandbox_path() -> str:
    """The ``PATH`` the fake runs ``exec`` with: :func:`linux_like_path` over the host's.

    Built once per process. Tests that shim ``tar`` themselves should
    resolve the real one from this path, not the host's.
    """
    shim_dir = Path(tempfile.mkdtemp(prefix="inspect-linux-like-tar-"))
    atexit.register(shutil.rmtree, shim_dir, ignore_errors=True)
    return linux_like_path(os.environ.get("PATH", os.defpath), shim_dir)


class LocalShellSandbox(SandboxEnvironment):
    """Sandbox fake that executes ``exec`` on the host shell.

    A per-call ``env`` is layered over the inherited environment.
    """

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        input_bytes = input.encode() if isinstance(input, str) else input
        # COPYFILE_DISABLE keeps macOS bsdtar from adding AppleDouble ``._*``
        # members should a command reach it past the tar shim; a no-op
        # elsewhere.
        run_env = {
            **os.environ,
            "PATH": sandbox_path(),
            "COPYFILE_DISABLE": "1",
            **(env or {}),
        }
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            timeout=120,
            env=run_env,
            cwd=cwd,
        )
        return ExecResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout.decode(errors="replace"),
            stderr=proc.stderr.decode(errors="replace"),
        )

    async def write_file(self, file: str, contents: str | bytes) -> None:
        data = contents.encode() if isinstance(contents, str) else contents
        Path(file).write_bytes(data)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        if text:
            return Path(file).read_text()
        return Path(file).read_bytes()

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass
