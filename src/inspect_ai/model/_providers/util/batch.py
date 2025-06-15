import asyncio
import dataclasses
import time
import uuid
from abc import abstractmethod
from collections import deque
from logging import getLogger
from typing import Any, Generic, TypeVar

import anyio

from inspect_ai.model._generate_config import GenerateConfig

logger = getLogger(__name__)

T = TypeVar("T")


@dataclasses.dataclass
class BatchRequest(Generic[T]):
    request: dict[str, Any]
    future: asyncio.Future[T] = dataclasses.field(default_factory=asyncio.Future)
    custom_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))


@dataclasses.dataclass
class BatchResult:
    id: str
    status: str
    result_uris: list[str]


class Batcher(Generic[T]):
    def __init__(self, config: GenerateConfig) -> None:
        self.config = config
        self._queue: deque[BatchRequest[T]] = deque()
        self.queue_timeout: float | None = None
        self._inflight_batches: dict[str, dict[str, asyncio.Future[T]]] = {}
        self._worker_task: asyncio.Task[None] | None = None

    async def generate(self, request: dict[str, Any], config: GenerateConfig) -> T:
        batch_request = BatchRequest[T](request=request)
        self._queue.append(batch_request)
        self.queue_timeout = min(
            time.time()
            + (config.batch_max_send_delay or self.config.batch_max_send_delay or 60),
            self.queue_timeout or float("inf"),
        )

        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._batch_worker())

        return await batch_request.future

    async def _batch_worker(self) -> None:
        assert self.config.batch_size is not None
        assert self.queue_timeout is not None

        while self._inflight_batches or len(self._queue):
            if self._inflight_batches:
                await self._check_inflight_batches()

            num_queued = len(self._queue)
            if num_queued and (
                num_queued >= self.config.batch_size or time.time() > self.queue_timeout
            ):
                await self._send_batch()

            await anyio.sleep(self.config.batch_tick)

        self._worker_task = None

    async def _check_inflight_batches(self) -> None:
        try:
            async with anyio.create_task_group() as tg:
                for batch_id in self._inflight_batches:
                    tg.start_soon(self._check_inflight_batch, batch_id)
        except Exception as e:
            logger.error(f"Error checking batch inflight: {e}")

    async def _check_inflight_batch(self, batch_id: str) -> None:
        batch_results = await self._check_batch(batch_id)

        if not batch_results.result_uris:
            return

        batch = self._inflight_batches.pop(batch_id)
        async with anyio.create_task_group() as tg:
            for idx_result_uri in range(len(batch_results.result_uris)):
                tg.start_soon(
                    self._handle_batch_result, batch_results, idx_result_uri, batch
                )

        for request_id, request_future in batch.items():
            request_future.set_exception(
                RuntimeError(
                    f"Request {request_id} failed, batch {batch_id} in status {batch_results.status}"
                )
            )

    async def _send_batch(self) -> None:
        batch = self._queue
        self._queue = deque()

        try:
            batch_id = await self._create_batch(batch)
        except Exception as e:
            logger.error(f"Error sending batch: {e}")
            # TODO: implement retry logic?
            return

        self._inflight_batches[batch_id] = {
            request.custom_id: request.future for request in batch
        }

    @abstractmethod
    async def _create_batch(self, batch: deque[BatchRequest[T]]) -> str:
        pass

    @abstractmethod
    async def _check_batch(self, batch_id: str) -> BatchResult:
        pass

    @abstractmethod
    async def _handle_batch_result(
        self,
        batch_result: BatchResult,
        idx_result_uri: int,
        batch: dict[str, asyncio.Future[T]],
    ) -> None:
        pass
