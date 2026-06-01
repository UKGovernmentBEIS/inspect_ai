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
    """Records exec calls and replays a queue of ExecResults.

    Only implements the subset of SandboxEnvironment SandboxService uses
    (the .exec() method). Cast to SandboxEnvironment at the call site.
    """

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
    """Name-squat detection raises PrerequisiteError.

    If the service dir already exists but is owned by another user
    (a name-squat), start() must fail fast with PrerequisiteError rather
    than silently using the squatted dir.
    """
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # 1. mkdir -p + chmod 1777 SERVICES_DIR (best-effort)
            FakeExecResult(),  # 2. mkdir -p <service_dir>
            FakeExecResult(
                success=False, returncode=1
            ),  # 3. test -O <service_dir> -> not owned
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

    # Verify the calls were the three _ensure_service_dir steps and nothing further
    # (start() must bail before touching the rpc dirs).
    issued = [call["cmd"] for call in fake.calls]
    assert len(issued) == 3, f"expected 3 exec calls, got {len(issued)}: {issued}"
    assert issued[0][:2] == ["sh", "-c"]
    assert "chmod 1777" in issued[0][2]
    assert SERVICES_DIR in issued[0][2]
    assert issued[1] == ["mkdir", "-p", f"{SERVICES_DIR}/squatted"]
    assert issued[2] == ["test", "-O", f"{SERVICES_DIR}/squatted"]
    # The chmod/mkdir step for the shared parent runs without a user
    # restriction (so it executes as the sandbox default, typically root).
    # The per-service mkdir and squat-check run as the service user.
    assert fake.calls[0]["user"] is None
    assert fake.calls[1]["user"] == "agent"
    assert fake.calls[2]["user"] == "agent"


async def test_ensure_service_dir_checks_root_service_dir_when_instance_set() -> None:
    """With instance set, both <name>/<instance> and <name> are ownership-checked.

    The <name> parent is the squattable surface when multiple instances of
    a service share it, so both paths must be verified.
    """
    fake = FakeSandboxEnvironment(
        results=[
            FakeExecResult(),  # 1. mkdir -p + chmod 1777 SERVICES_DIR
            FakeExecResult(),  # 2. mkdir -p <name>/<instance>
            FakeExecResult(),  # 3. test -O <name>/<instance> -> owned
            FakeExecResult(
                success=False, returncode=1
            ),  # 4. test -O <name> -> squatted
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
    # The error names the <name> parent (the squatted dir), not the leaf.
    assert f"{SERVICES_DIR}/multi" in msg
    assert f"{SERVICES_DIR}/multi/inst1" not in msg

    issued = [call["cmd"] for call in fake.calls]
    assert len(issued) == 4, f"expected 4 exec calls, got {len(issued)}: {issued}"
    assert issued[1] == ["mkdir", "-p", f"{SERVICES_DIR}/multi/inst1"]
    # Squat check checks the leaf first, then the <name> parent.
    assert issued[2] == ["test", "-O", f"{SERVICES_DIR}/multi/inst1"]
    assert issued[3] == ["test", "-O", f"{SERVICES_DIR}/multi"]


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_nonroot_after_root_setup() -> None:
    """Nonroot service starts after root pre-created SERVICES_DIR as 0755.

    When /var/tmp/sandbox-services is pre-created root-owned and 0755
    (the state a root setup sandbox_service leaves behind), a subsequent
    nonroot sandbox_service must still be able to start. Without the fix,
    the second service's _create_rpc_dir mkdir fails with Permission denied.
    """
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
        # Simulate a prior root setup service: create SERVICES_DIR
        # root-owned, mode 0755 — the exact pre-state the fix must
        # tolerate.
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
        # run the math service in the background as nonroot
        background(run_math_service, state, "nonroot")

        # run the client script as nonroot
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
