from inspect_ai import Task, task
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@task
def implicit_sandbox_task() -> Task:
    return Task(sandbox="podman")


@task
def relative_sandbox_task() -> Task:
    return Task(sandbox=("podman", "podman.yaml"))


@solver
def docker_marker_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        result = await sandbox().exec(["sh", "-lc", "cat /package_marker"])
        state.store.set("package_marker", result.stdout.strip())
        if not result.success:
            raise RuntimeError(result.stderr)
        return state

    return solve


@task
def docker_implicit_task() -> Task:
    return Task(solver=docker_marker_solver(), sandbox="docker")
