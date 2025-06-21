import dataclasses
import functools
import time
import uuid
from abc import abstractmethod
from logging import getLogger
from typing import Any, Generic, TypeVar

import anyio
import anyio.abc

from inspect_ai._util._async import run_in_background, tg_collect
from inspect_ai.model._generate_config import GenerateConfig

logger = getLogger(__name__)

ResponseT = TypeVar("ResponseT")
CompletedBatchInfoT = TypeVar("CompletedBatchInfoT")

# TODO:
# - [x] One more pass removing dependency on eval_task_group. This code needs to
#       work when running outside of an eval context - like in a notebook.
# - [x] Stop mutating across modules. Become more functional. Return new model
# objects instead. e.g. _handle_batch_result should not mutate the batch that was passed to it.
# - [x] Write wrappers around calls to abstract methods to localize try/catch'es error handling.
# - [] Implement error handling strategy for all calls - see TODO's below
#   - [] _fail_all_requests needs to be enhanced to support sending a specific error to the futures.
# - [] Review test - in particular, their need for mocking anyio


@dataclasses.dataclass
class BatchRequest(Generic[ResponseT]):
    """This is a single request that is part of a batch."""

    request: dict[str, Any]
    result_stream: anyio.abc.ObjectSendStream[ResponseT | Exception]
    custom_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))


"""
This is model provider specific info that represents the completed result of a batch

It gets returned by the `_check_batch` method and passed to `_handle_batch_result`.

Not all model providers need this
"""


@dataclasses.dataclass
class Batch(Generic[ResponseT]):
    id: str
    requests: dict[str, BatchRequest[ResponseT]]
    retry_count: int = 0


class Batcher(Generic[ResponseT, CompletedBatchInfoT]):
    def __init__(self, config: GenerateConfig) -> None:
        self.config = config
        self._queue: list[BatchRequest[ResponseT]] = []
        self.queue_timeout: float | None = None
        self._inflight_batches: dict[str, Batch[ResponseT]] = {}
        self._is_batch_worker_running: bool = False

    # TODO: Think through generate's config argument vs self.config - particularly wrt memoization
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
            run_in_background(self._batch_worker)

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
        completed_info = await self._safe_check_batch(batch)
        if completed_info is None:
            return

        await self._safe_handle_batch_result(batch, completed_info)

        del self._inflight_batches[batch.id]
        # Send exceptions to any remaining streams that weren't handled
        await self._fail_all_requests(list(batch.requests.values()))

    async def _send_batch(self) -> None:
        batch_requests = self._queue
        self._queue = []

        batch_id = await self._safe_create_batch(batch_requests)
        if batch_id is None:
            return

        self._inflight_batches[batch_id] = Batch(
            id=batch_id,
            requests={request.custom_id: request for request in batch_requests},
        )

    async def _fail_all_requests(
        self,
        batch_requests: list[BatchRequest[ResponseT]],
        error: Exception | None = None,
    ) -> None:
        for request in batch_requests:
            try:
                await request.result_stream.send(
                    error or self._get_request_failed_error(request)
                )
            except anyio.BrokenResourceError:
                # TODO: VERIFY Stream already closed, ignore
                pass

    # These _safe_* methods are intended to wrap the abstract methods with the appropriate
    # error handling logic consistent with the batch algorithm. This allows the
    # code above to not worry about try/catch'ing the abstract methods.
    # Any exception that escapes a _safe_* method should be considered a coding
    # error and bring down the eval.

    async def _safe_create_batch(
        self, batch: list[BatchRequest[ResponseT]]
    ) -> str | None:
        try:
            return await self._create_batch(batch)
        except Exception as e:
            logger.error(
                f"Error creating batch, failing all {len(batch)} requests in batch",
                exc_info=e,
            )
            await self._fail_all_requests(batch, e)
            return None

    async def _safe_check_batch(
        self, batch: Batch[ResponseT]
    ) -> CompletedBatchInfoT | None:
        try:
            result = await self._check_batch(batch)
            batch.retry_count = 0
            return result
        except Exception as e:
            logger.error(f"Error checking batch {batch.id}", exc_info=e)
            batch.retry_count += 1
            if batch.retry_count >= 3:
                logger.error(
                    f"Batch {batch.id} failed after 3 retries, failing all {len(batch.requests)} requests in batch",
                )
                await self._fail_all_requests([*batch.requests.values()], e)
                del self._inflight_batches[batch.id]

    async def _safe_handle_batch_result(
        self,
        batch: Batch[ResponseT],
        completion_info: CompletedBatchInfoT,
    ) -> None:
        try:
            await self._handle_batch_result(batch, completion_info)
            batch.retry_count = 0
        except Exception as e:
            logger.error(
                f"Error handling batch {batch.id} result {completion_info}",
                exc_info=e,
            )
            batch.retry_count += 1
            if batch.retry_count >= 3:
                logger.error(
                    f"Batch {batch.id} failed after 3 retries, failing all {len(batch.requests)} requests in batch",
                )
                await self._fail_all_requests([*batch.requests.values()], e)
                batch.requests = {}

    @abstractmethod
    async def _create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        pass

    @abstractmethod
    async def _check_batch(self, batch: Batch[ResponseT]) -> CompletedBatchInfoT | None:
        pass

    @abstractmethod
    async def _handle_batch_result(
        self,
        batch: Batch[ResponseT],
        completion_info: CompletedBatchInfoT,
    ) -> None:
        pass

    @abstractmethod
    # Must not let any exceptions escape. Any exception that does escape is a
    # coding error and will bring down the eval.
    def _get_request_failed_error(self, request: BatchRequest[ResponseT]) -> Exception:
        pass
