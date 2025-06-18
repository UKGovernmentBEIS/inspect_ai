import dataclasses
import functools
import time
import uuid
from abc import abstractmethod
from logging import getLogger
from typing import Any, Generic, TypeVar

import anyio
import anyio.abc

from inspect_ai._util._async import tg_collect
from inspect_ai._util.eval_task_group import eval_task_group
from inspect_ai.model._generate_config import GenerateConfig

logger = getLogger(__name__)

ResponseT = TypeVar("ResponseT")

# TODO:
# - [] Stop mutating across modules. Become more functional. Return new model
# objects instead. e.g. _handle_batch_result should not mutate the batch that was passed to it.
# - [x] Write wrappers around calls to abstract methods to localize try/catch'es error handling.
# - [] Implement error handling strategy for all calls - see TODO's below


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
        self._is_batch_worker_running: bool = False

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

        if not self._is_batch_worker_running:
            self._is_batch_worker_running = True
            eval_task_group().start_soon(self._batch_worker)

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

        self._is_batch_worker_running = False

    async def _check_inflight_batches(self) -> None:
        await tg_collect(
            [
                functools.partial(self._check_inflight_batch, batch)
                for batch in self._inflight_batches.values()
            ]
        )

    async def _check_inflight_batch(self, batch: Batch[ResponseT]) -> None:
        check_result = await self._safe_check_batch(batch)
        if not check_result:
            return

        # TODO: Stop mutating the input
        batch = check_result
        if not isinstance(batch, CompletedBatch):
            self._inflight_batches[batch.id] = batch
            return

        # TODO: This code relies on a hidden side-effect of _check_batch which
        # mutates the batch that was passed to this function. See TODO below
        await tg_collect(
            [
                functools.partial(self._safe_handle_batch_result, batch, idx_result_uri)
                for idx_result_uri in range(len(batch.result_uris))
            ]
        )

        del self._inflight_batches[batch.id]
        # Send exceptions to any remaining streams that weren't handled
        await self._fail_all_requests(list(batch.requests.values()))

    async def _send_batch(self) -> None:
        batch_requests = self._queue
        self._queue = []

        batch_id = await self._safe_create_batch(batch_requests)
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
                    self._get_request_failed_error(request)
                )
            except anyio.BrokenResourceError:
                # TODO: VERIFY Stream already closed, ignore
                pass

    # These _safe_* methods are intended to wrap the abstract methods with the appropriate
    # error handling logic consistent with the batch algorithm. This allows the
    # code above to not worry about try/catch'ing the abstract methods.
    # Any exception that escapes a _safe_* method should be considered a coding
    # error and bring down the eval.

    async def _safe_create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        try:
            return await self._create_batch(batch)
        except Exception as e:
            # TODO: Fail all requests with this error
            print(f"Error creating batch: {e}")
            raise

    async def _safe_check_batch(
        self, batch: Batch[ResponseT]
    ) -> Batch[ResponseT] | None:
        try:
            return await self._check_batch(batch)
        except Exception as e:
            # TODO: Logging
            print(f"Error checking batch: {e}")
            return None

    async def _safe_handle_batch_result(
        self,
        batch: CompletedBatch[ResponseT],
        idx_result_uri: int,
    ) -> None:
        try:
            await self._handle_batch_result(batch, idx_result_uri)
        except Exception as e:
            # TODO: Fail all requests with this error
            logger.error(f"Error handling batch result: {e}")
            raise

    @abstractmethod
    async def _create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        pass

    @abstractmethod
    # TODO: I would propose that we break out a type for BatchResult that includes
    # status and result_uris. This concrete method should return one of those
    # rather than mutating the data held by this base class. Functional code
    # like that is easier to reason about.
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
    # Must not let any exceptions escape. Any exception that does escape is a
    # coding error and will bring down the eval.
    def _get_request_failed_error(self, request: BatchRequest[ResponseT]) -> Exception:
        pass
