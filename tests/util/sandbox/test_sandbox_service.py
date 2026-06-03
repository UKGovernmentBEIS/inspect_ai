from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox
from inspect_ai.util._background import background
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.service import (
    SERVICES_DIR,
    SandboxService,
    sandbox_service,
)
from inspect_ai.util._subprocess import ExecResult


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "user, handle_requests",
    [("root", True), ("nonroot", True), (None, True), (None, False)],
)
def test_sandbox_service(user: str | None, handle_requests: bool):
    log = eval(
        Task(solver=math_service(user, handle_requests)),
        model="mockllm/model",
        sandbox=(
            "docker",
            str(Path(__file__).parent / "compose.sandbox-service.yaml"),
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.store.get("result") == 8


@solver
def math_service(user: str | None, handle_requests: bool) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # generate a script that will exercise the service and copy it to the sandbox
        run_script = "run.py"
        run_script_code = dedent("""
        import asyncio

        async def run():
            # wait for service to come up
            import os
            service_dir = "/var/tmp/sandbox-services/math_service"
            while not os.path.exists(f"{service_dir}/math_service.py"):
                await asyncio.sleep(0.1)

            # import service
            import sys
            sys.path.append(service_dir)
            from math_service import call_math_service, call_math_service_async

            # call service
            result = await call_math_service_async("add", x=10, y=5)
            result = call_math_service("subtract", x=result, y=7)
            await call_math_service_async("finish", result=result)

        asyncio.run(run())
        """)
        # run the math service in the background
        background(run_math_service, state, user)

        # run a script in the sandbox that talks to the service
        await sandbox().write_file(run_script, run_script_code)
        script_error = ""
        try:
            result = await sandbox().exec(["python3", run_script], user=user)
            if not result.success:
                script_error = f"Error running script '{run_script}': {result.stderr}"
        except Exception as e:
            script_error = f"Exception in script: {str(e)}"
        if script_error:
            print(script_error)

        return state

    return solve


async def run_math_service(
    state: TaskState, user: str | None, handle_requests: bool = True
) -> None:
    finished = False

    async def add(x: int, y: int) -> int:
        return x + y

    async def subtract(x: int, y: int) -> int:
        return x - y

    async def finish(result: int) -> None:
        nonlocal finished
        finished = True
        state.store.set("result", result)

    if handle_requests:
        await sandbox_service(
            name="math_service",
            methods=[add, subtract, finish],
            until=lambda: finished,
            sandbox=sandbox(),
            user=user,
        )
    else:
        handle_service_requests = await sandbox_service(
            name="math_service",
            methods=[add, subtract, finish],
            until=lambda: finished,
            sandbox=sandbox(),
            user=user,
            handle_requests=False,
        )
        while not finished:
            await handle_service_requests()
            await anyio.sleep(0.1)


@dataclass
class FakeExecResult:
    success: bool = True
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class FakeSandboxEnvironment:
    """Stub sandbox env that records exec calls and replays canned results."""

    results: list[FakeExecResult] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.calls.append({"cmd": cmd, "user": user})
        if self.results:
            return cast(ExecResult[str], self.results.pop(0))
        return cast(ExecResult[str], FakeExecResult())


async def test_ensure_service_dir_raises_when_dir_not_owned() -> None:
    """A name-squat (alien-owned service dir) raises PrerequisiteError."""
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # chmod 1777 SERVICES_DIR
            FakeExecResult(),  # mkdir <service_dir>
            FakeExecResult(success=False, returncode=1),  # test -O -> not owned
        ],
    )
    service = SandboxService(
        name="squatted",
        sandbox=cast(SandboxEnvironment, fake),
        user="agent",
    )

    with pytest.raises(PrerequisiteError) as excinfo:
        await service.start()

    msg = str(excinfo.value)
    assert "squatted" in msg
    assert "agent" in msg
    assert f"{SERVICES_DIR}/squatted" in msg

    issued = [call["cmd"] for call in fake.calls]
    assert len(issued) == 3, f"expected 3 exec calls, got {len(issued)}: {issued}"
    assert issued[0][:2] == ["sh", "-c"]
    assert "chmod 1777" in issued[0][2]
    assert SERVICES_DIR in issued[0][2]
    assert issued[1] == ["mkdir", "-p", f"{SERVICES_DIR}/squatted"]
    assert issued[2] == ["test", "-O", f"{SERVICES_DIR}/squatted"]
    # Parent chmod runs as the sandbox default (no user restriction);
    # per-service mkdir + squat-check run as the service user.
    assert fake.calls[0]["user"] is None
    assert fake.calls[1]["user"] == "agent"
    assert fake.calls[2]["user"] == "agent"


async def test_ensure_service_dir_checks_root_service_dir_when_instance_set() -> None:
    """With instance set, both <name>/<instance> and <name> are ownership-checked."""
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # chmod 1777 SERVICES_DIR
            FakeExecResult(),  # mkdir <name>/<instance>
            FakeExecResult(),  # test -O <name>/<instance> -> owned
            FakeExecResult(success=False, returncode=1),  # test -O <name> -> squatted
        ],
    )
    service = SandboxService(
        name="multi",
        sandbox=cast(SandboxEnvironment, fake),
        user="agent",
        instance="inst1",
    )

    with pytest.raises(PrerequisiteError) as excinfo:
        await service.start()

    msg = str(excinfo.value)
    assert "multi" in msg
    assert "agent" in msg
    # Error names the squatted <name>, not the leaf instance dir.
    assert f"{SERVICES_DIR}/multi" in msg
    assert f"{SERVICES_DIR}/multi/inst1" not in msg

    issued = [call["cmd"] for call in fake.calls]
    assert len(issued) == 4, f"expected 4 exec calls, got {len(issued)}: {issued}"
    assert issued[1] == ["mkdir", "-p", f"{SERVICES_DIR}/multi/inst1"]
    assert issued[2] == ["test", "-O", f"{SERVICES_DIR}/multi/inst1"]
    assert issued[3] == ["test", "-O", f"{SERVICES_DIR}/multi"]


async def test_ensure_service_dir_raises_prereq_when_parent_unwritable() -> None:
    """Surface PrerequisiteError when mkdir fails because the parent is unwritable."""
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # chmod SERVICES_DIR
            FakeExecResult(  # mkdir <service_dir> fails
                success=False, returncode=1, stderr="mkdir: Permission denied"
            ),
            FakeExecResult(success=False, returncode=1),  # test -w <parent> -> no
        ],
    )
    service = SandboxService(
        name="blocked",
        sandbox=cast(SandboxEnvironment, fake),
        user="agent",
    )

    with pytest.raises(PrerequisiteError) as excinfo:
        await service.start()

    msg = str(excinfo.value)
    assert "blocked" in msg
    assert "agent" in msg
    # The parent of /var/tmp/sandbox-services/blocked is SERVICES_DIR
    # itself — that's what the error must point at.
    assert f"parent directory '{SERVICES_DIR}'" in msg

    issued = [call["cmd"] for call in fake.calls]
    assert len(issued) == 3, f"expected 3 exec calls, got {len(issued)}: {issued}"
    assert issued[2] == ["test", "-w", SERVICES_DIR]


async def test_ensure_service_dir_raises_runtime_when_parent_writable_but_mkdir_fails() -> (
    None
):
    """Surface RuntimeError (not a squat) when mkdir fails but the parent is writable."""
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # chmod SERVICES_DIR
            FakeExecResult(  # mkdir <service_dir> fails (ENOSPC)
                success=False, returncode=1, stderr="mkdir: No space left on device"
            ),
            FakeExecResult(),  # test -w <parent> -> writable
        ],
    )
    service = SandboxService(
        name="diskfull",
        sandbox=cast(SandboxEnvironment, fake),
        user="agent",
    )

    with pytest.raises(RuntimeError, match="No space left on device") as excinfo:
        await service.start()

    assert not isinstance(excinfo.value, PrerequisiteError)
    assert "diskfull" in str(excinfo.value)


@pytest.mark.parametrize("bad_instance", ["", ".", "..", "../etc", "foo/bar"])
def test_sandbox_service_rejects_invalid_instance(bad_instance: str) -> None:
    """Invalid instance values (path traversal, collapse-to-noninstanced) are rejected."""
    fake = FakeSandboxEnvironment()
    with pytest.raises(ValueError, match="invalid instance"):
        SandboxService(
            name="x",
            sandbox=cast(SandboxEnvironment, fake),
            user="agent",
            instance=bad_instance,
        )


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_nonroot_after_root_setup() -> None:
    """A nonroot service must start even when SERVICES_DIR was pre-created root-owned 0755."""
    log = eval(
        Task(solver=math_service_after_root_setup()),
        model="mockllm/model",
        sandbox=(
            "docker",
            str(Path(__file__).parent / "compose.sandbox-service.yaml"),
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.store.get("result") == 8


@solver
def math_service_after_root_setup() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Simulate a prior root setup sandbox_service having left
        # SERVICES_DIR root-owned 0755 — the failing pre-state.
        prep = await sandbox().exec(
            [
                "sh",
                "-c",
                "mkdir -p /var/tmp/sandbox-services && "
                "chmod 0755 /var/tmp/sandbox-services && "
                "chown root:root /var/tmp/sandbox-services",
            ],
            user="root",
        )
        assert prep.success, f"prep failed: {prep.stderr}"

        # Reuse the math service flow, this time as nonroot.
        run_script = "run.py"
        run_script_code = dedent("""
        import asyncio

        async def run():
            import os
            service_dir = "/var/tmp/sandbox-services/math_service"
            while not os.path.exists(f"{service_dir}/math_service.py"):
                await asyncio.sleep(0.1)

            import sys
            sys.path.append(service_dir)
            from math_service import call_math_service, call_math_service_async

            result = await call_math_service_async("add", x=10, y=5)
            result = call_math_service("subtract", x=result, y=7)
            await call_math_service_async("finish", result=result)

        asyncio.run(run())
        """)
        background(run_math_service, state, "nonroot")

        await sandbox().write_file(run_script, run_script_code)
        script_error = ""
        try:
            result = await sandbox().exec(["python3", run_script], user="nonroot")
            if not result.success:
                script_error = f"Error running script '{run_script}': {result.stderr}"
        except Exception as e:
            script_error = f"Exception in script: {str(e)}"
        if script_error:
            print(script_error)

        return state

    return solve
