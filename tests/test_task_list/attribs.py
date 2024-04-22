from inspect_ai import Task, task


@task(light=True, type="bio")
def attribs():
    return Task([])
