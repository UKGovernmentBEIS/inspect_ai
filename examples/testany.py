import asyncio

import anyio


async def parent_task():
    child_tasks = [child_task(i) for i in range(1, 6)]
    try:
        await asyncio.gather(*child_tasks)
    except asyncio.CancelledError:
        print("parent cancelled")


async def child_task(id: int):
    try:
        print(f"child_task: {id}")
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        print(f"cancelled : {id}")


async def cancel_task_in(task: asyncio.Task, seconds: int) -> None:
    await asyncio.sleep(seconds)
    task.cancel()
    await task


async def run_asyncio():
    print("asycnio")

    task = asyncio.create_task(parent_task())
    await asyncio.gather(task, cancel_task_in(task, 2))


async def anyio_parent_task():
    async with anyio.create_task_group() as tg:
        for i in range(1, 6):
            tg.start_soon(anyio_child_task, i)
        try:
            # In anyio, parent just waits for task group completion
            await anyio.sleep_forever()  # Will be interrupted by cancellation
        except anyio.get_cancelled_exc_class():
            print("parent cancelled")


async def anyio_child_task(id: int):
    try:
        print(f"child_task: {id}")
        await anyio.sleep(5)
    except anyio.get_cancelled_exc_class():
        print(f"cancelled : {id}")


async def run_anyio():
    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:
            tg.start_soon(parent_task)

            # Cancel after 2 seconds
            await anyio.sleep(2)
            scope.cancel()


if __name__ == "__main__":
    # asyncio.run(run_asyncio())
    anyio.run(run_anyio)
