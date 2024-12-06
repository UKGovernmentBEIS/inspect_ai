import asyncio
from textwrap import dedent

import pytest

from inspect_ai import Task, eval
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import ExecResult, sandbox, sandbox_service


@pytest.mark.slow
def test_sandbox_service():
    log = eval(Task(solver=math_service()), model="mockllm/model", sandbox="docker")[0]
    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.store.get("result") == 8


@solver
def math_service() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # generate a script that will exercise the service and copy it to the sandbox
        run_script = "run.py"
        run_script_code = dedent("""
        import asyncio

        async def run():
            # wait for service to come up
            import os
            service_dir = "/tmp/inspect-sandbox-services/math_service"
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
        for task in asyncio.as_completed(
            [sandbox().exec(["python3", run_script]), run_math_service(state)]
        ):
            result = await task
            if isinstance(result, ExecResult) and not result.success:
                print(f"Error running script '{run_script}': {result.stderr}")
                break

        return state

    return solve


async def run_math_service(state: TaskState) -> None:
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
    )
