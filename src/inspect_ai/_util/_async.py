import asyncio
from typing import Any


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if asyncio.iscoroutinefunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return asyncio.iscoroutinefunction(func_or_cls.__call__)
    return False
