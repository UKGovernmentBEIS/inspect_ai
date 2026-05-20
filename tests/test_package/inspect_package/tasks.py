from inspect_ai import Task, task


@task
def implicit_sandbox_task() -> Task:
    return Task(sandbox="podman")


@task
def relative_sandbox_task() -> Task:
    return Task(sandbox=("podman", "podman.yaml"))
