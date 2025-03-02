from typing import Generic, TypeVar

import anyio

T = TypeVar("T")


class Future(Generic[T]):
    def __init__(self) -> None:
        self._result: T | None = None
        self._ex: BaseException | None = None
        self._event = anyio.Event()

    def set_result(self, result: T) -> None:
        self._result = result
        self._event.set()

    def set_exception(self, ex: BaseException) -> None:
        self._ex = ex
        self._event.set()

    async def wait(self) -> T:
        await self._event.wait()
        if self._result is not None:
            return self._result
        elif self._ex is not None:
            raise self._ex
        else:
            raise RuntimeError("Future completed without a result or error")

    @staticmethod
    def set_result_from_thread(future: "Future[T]", result: T) -> None:
        anyio.from_thread.run_sync(Future._set_thread_safe, future, result)

    @staticmethod
    def set_exception_from_thread(future: "Future[T]", error: BaseException) -> None:
        anyio.from_thread.run_sync(Future._set_exception_thread_safe, future, error)

    @staticmethod
    def _set_thread_safe(future: "Future[T]", result: T) -> None:
        future.set_result(result)

    @staticmethod
    def _set_exception_thread_safe(future: "Future[T]", error: BaseException) -> None:
        future.set_exception(error)
