from inspect_ai._util._async import run_coroutine


def scan() -> None:
    run_coroutine(scan_async())


async def scan_async() -> None:
    pass
