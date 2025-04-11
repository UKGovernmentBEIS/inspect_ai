from pathlib import Path
from textwrap import dedent

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox
from inspect_ai.util._sandbox.service import sandbox_service


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize("user", ["root", "nonroot", None])
def test_sandbox_service(user: str | None):
    log = eval(
        Task(solver=math_service(user)),
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
def math_service(user: str | None) -> Solver:
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
        await sandbox().write_file(run_script, run_script_code)

        # run the script and the math service
        async with anyio.create_task_group() as tg:

            async def run_service_script() -> None:
                script_error = ""
                try:
                    result = await sandbox().exec(["python3", run_script], user=user)
                    if not result.success:
                        script_error = (
                            f"Error running script '{run_script}': {result.stderr}"
                        )
                except Exception as e:
                    script_error = f"Exception in script: {str(e)}"
                if script_error:
                    print(script_error)
                    tg.cancel_scope.cancel()

            tg.start_soon(run_math_service, state, user)
            tg.start_soon(run_service_script)

        return state

    return solve


async def run_math_service(state: TaskState, user: str | None) -> None:
    finished = False

    async def add(x: int, y: int) -> int:
        return x + y

    async def subtract(x: int, y: int) -> int:
        return x - y

    async def finish(result: int) -> None:
        nonlocal finished
        finished = True
        state.store.set("result", result)

    await sandbox_service(
        name="math_service",
        methods=[add, subtract, finish],
        until=lambda: finished,
        sandbox=sandbox(),
        user=user,
    )
