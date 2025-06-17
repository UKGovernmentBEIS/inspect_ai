import dataclasses
import time
import uuid
from abc import abstractmethod
from logging import getLogger
from typing import Any, Generic, TypeVar

import anyio
import anyio.abc

from inspect_ai._util.eval_task_group import eval_task_group
from inspect_ai.model._generate_config import GenerateConfig

logger = getLogger(__name__)

ResponseT = TypeVar("ResponseT")


@dataclasses.dataclass
class BatchRequest(Generic[ResponseT]):
    request: dict[str, Any]
    result_stream: anyio.abc.ObjectSendStream[ResponseT | Exception]
    custom_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))


@dataclasses.dataclass
class Batch(Generic[ResponseT]):
    id: str
    requests: dict[str, BatchRequest[ResponseT]]
    status: str | None


@dataclasses.dataclass
class CompletedBatch(Batch[ResponseT]):
    result_uris: list[str]


class Batcher(Generic[ResponseT]):
    def __init__(self, config: GenerateConfig) -> None:
        self.config = config
        self._queue: list[BatchRequest[ResponseT]] = []
        self.queue_timeout: float | None = None
        self._inflight_batches: dict[str, Batch[ResponseT]] = {}
        self._task_group: anyio.abc.TaskGroup | None = None

    async def generate(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ResponseT:
        send_stream, receive_stream = anyio.create_memory_object_stream[
            ResponseT | Exception
        ](1)
        batch_request = BatchRequest[ResponseT](
            request=request, result_stream=send_stream
        )
        self._queue.append(batch_request)
        self.queue_timeout = min(
            time.time()
            + (config.batch_max_send_delay or self.config.batch_max_send_delay or 60),
            self.queue_timeout or float("inf"),
        )

        if self._task_group is None:
            self._task_group = eval_task_group()
            self._task_group.start_soon(self._batch_worker)

        result = await receive_stream.receive()
        if isinstance(result, Exception):
            raise result
        return result

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

        self._task_group = None

    async def _check_inflight_batches(self) -> None:
        async with anyio.create_task_group() as tg:
            for batch in self._inflight_batches.values():
                tg.start_soon(self._check_inflight_batch, batch)

    async def _check_inflight_batch(self, batch: Batch[ResponseT]) -> None:
        batch = await self._check_batch(batch)
        if not isinstance(batch, CompletedBatch):
            self._inflight_batches[batch.id] = batch
            return

        async with anyio.create_task_group() as tg:
            for idx_result_uri in range(len(batch.result_uris)):
                tg.start_soon(
                    self._handle_batch_result,
                    batch,
                    idx_result_uri,
                )

        del self._inflight_batches[batch.id]
        # Send exceptions to any remaining streams that weren't handled
        await self._fail_all_requests(list(batch.requests.values()))

    async def _send_batch(self) -> None:
        batch_requests = self._queue
        self._queue = []

        batch_id = await self._create_batch(batch_requests)
        self._inflight_batches[batch_id] = Batch(
            id=batch_id,
            requests={request.custom_id: request for request in batch_requests},
            status=None,
        )

    async def _fail_all_requests(
        self, batch_requests: list[BatchRequest[ResponseT]]
    ) -> None:
        for request in batch_requests:
            try:
                await request.result_stream.send(
                    await self._get_request_failed_error(request)
                )
            except anyio.BrokenResourceError:
                # TODO: VERIFY Stream already closed, ignore
                pass

    @abstractmethod
    async def _create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        pass

    @abstractmethod
    async def _check_batch(self, batch: Batch[ResponseT]) -> Batch[ResponseT]:
        pass

    @abstractmethod
    async def _handle_batch_result(
        self,
        batch: CompletedBatch[ResponseT],
        idx_result_uri: int,
    ) -> None:
        pass

    @abstractmethod
    def _get_request_failed_error(self, request: BatchRequest[ResponseT]) -> Exception:
        pass
