from inspect_ai import Task, task


@task
def empty_task() -> Task:
    return Task()
