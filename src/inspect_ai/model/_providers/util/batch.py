import dataclasses
import functools
import json
import time
import uuid
from abc import abstractmethod
from collections import deque
from logging import getLogger
from typing import Any, Generic, TypeVar

import anyio
import anyio.abc

from inspect_ai._util._async import run_in_background, tg_collect
from inspect_ai._util.constants import DEFAULT_BATCH_SIZE
from inspect_ai._util.notgiven import sanitize_notgiven
from inspect_ai.model._generate_config import BatchConfig, GenerateConfig

DEFAULT_BATCH_TICK = 15
DEFAULT_SEND_DELAY = DEFAULT_BATCH_TICK
DEFAULT_MAX_BATCHES = 50

logger = getLogger(__name__)

ResponseT = TypeVar("ResponseT")
CompletedBatchInfoT = TypeVar("CompletedBatchInfoT")
"""
This is model provider specific info that represents the completed result of a batch

It gets returned by the `_check_batch` method and passed to `_handle_batch_result`.

Not all model providers need this
"""


@dataclasses.dataclass
class BatchRequest(Generic[ResponseT]):
    """This is a single request that is part of a batch."""

    request: dict[str, Any]
    result_stream: anyio.abc.ObjectSendStream[ResponseT | Exception]
    custom_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))


@dataclasses.dataclass
class Batch(Generic[ResponseT]):
    id: str
    requests: dict[str, BatchRequest[ResponseT]]
    retry_count: int = 0


class Batcher(Generic[ResponseT, CompletedBatchInfoT]):
    def __init__(
        self,
        config: BatchConfig,
        max_batch_request_count: int,
        max_batch_size_mb: int,
    ) -> None:
        # self.config = config
        self.max_batch_request_count = max_batch_request_count
        self.max_batch_size_bytes = max_batch_size_mb * 1024 * 1024
        self._batch_size = config.size or DEFAULT_BATCH_SIZE
        self._send_delay = config.send_delay or DEFAULT_SEND_DELAY
        self._tick = config.tick or DEFAULT_BATCH_TICK
        self._max_batches = config.max_batches or DEFAULT_MAX_BATCHES
        self._intake_queue: deque[BatchRequest[ResponseT]] = deque()
        self._next_batch: list[BatchRequest[ResponseT]] | None = None
        self.next_batch_timeout: float | None = None
        self._next_batch_aggregate_size: int | None = None
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
        self._intake_queue.append(batch_request)

        if not self._is_batch_worker_running:
            self._is_batch_worker_running = True
            run_in_background(self._batch_worker)

        result = await receive_stream.receive()
        if isinstance(result, Exception):
            raise result
        return result

    async def _batch_worker(self) -> None:
        while self._inflight_batches or self._intake_queue or self._next_batch:
            await self._check_inflight_batches()

            self._process_intake_queue()

            await self._maybe_send_next_batch()

            await anyio.sleep(self._tick)

        self._is_batch_worker_running = False

    async def _check_inflight_batches(self) -> None:
        if self._inflight_batches:
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

    def _process_intake_queue(self) -> None:
        """Move requests from intake queue to next batch if they fit."""
        if not self._intake_queue:
            return

        # Initialize next batch if it doesn't exist
        if self._next_batch is None:
            self._next_batch = []
            self._next_batch_aggregate_size = None
            self.next_batch_timeout = time.time() + self._send_delay

        # Process intake queue, moving requests that fit into next batch
        while self._intake_queue:
            request = self._intake_queue[0]  # Peek at the first request
            new_size = self._does_request_fit_in_batch(
                request, self._next_batch, self._next_batch_aggregate_size
            )
            if new_size is not None:
                # Remove from intake queue and add to next batch
                request = self._intake_queue.popleft()
                self._next_batch.append(request)
                self._next_batch_aggregate_size = new_size
            else:
                # Stop processing once we find a request that doesn't fit
                break

    async def _maybe_send_next_batch(self) -> None:
        if (
            not self._next_batch
            or len(self._inflight_batches) >= self._max_batches
            or (
                len(self._next_batch) < self._batch_size
                and not (
                    self.next_batch_timeout and time.time() > self.next_batch_timeout
                )
            )
        ):
            return

        # All conditions are met. Send it

        batch_requests = self._next_batch
        self._next_batch = None
        self._next_batch_aggregate_size = None
        self.next_batch_timeout = None

        batch_id = await self._safe_create_batch(batch_requests)
        if batch_id is None:
            return

        self._inflight_batches[batch_id] = Batch(
            id=batch_id,
            requests={request.custom_id: request for request in batch_requests},
        )

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
            return None

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

    def _does_request_fit_in_batch(
        self,
        request: BatchRequest[ResponseT],
        batch: list[BatchRequest[ResponseT]],
        current_size: int | None,
    ) -> int | None:
        """
        Check if a request fits in the batch and return new aggregate size if it does.

        Args:
            request: The request to check
            batch: The current batch of requests
            current_size: The current size of the requests

        Returns:
            None if the request does NOT fit (no capacity), otherwise the new size
            of the requests assuming the request is added to the batch
        """
        if len(batch) >= self.max_batch_request_count:
            return None

        if current_size is None:
            current_size = sum(
                len(json.dumps(sanitize_notgiven(req.request))) for req in batch
            )

        new_size = current_size + len(json.dumps(sanitize_notgiven(request.request)))

        # Leave 5% buffer
        return new_size if new_size < self.max_batch_size_bytes * 0.95 else None

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
