from typing import Generic, TypeVar

import anyio

T = TypeVar("T")


class Future(Generic[T]):
    def __init__(self) -> None:
        self._result: T | None = None
        self._ex: Exception | None = None
        self._event = anyio.Event()

    def set_result(self, result: T) -> None:
        self._result = result
        self._event.set()

    def set_exception(self, ex: Exception) -> None:
        self._ex = ex
        self._event.set()

    async def result(self) -> T:
        await self._event.wait()
        if self._result is not None:
            return self._result
        elif self._ex is not None:
            raise self._ex
        else:
            raise RuntimeError("Future completed without a result or error")

    @staticmethod
    def set_future_result(future: "Future[T]", result: T) -> None:
        future.set_result(result)

    @staticmethod
    def set_future_exception(future: "Future[T]", error: Exception) -> None:
        future.set_exception(error)
