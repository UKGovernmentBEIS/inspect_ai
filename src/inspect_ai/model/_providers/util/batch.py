import dataclasses
import functools
import json
import sys
import time
import uuid
from abc import abstractmethod
from typing import Any, Generic, TypeVar

import anyio
import anyio.abc
from tenacity import RetryCallState, retry

from inspect_ai._util._async import run_in_background, tg_collect
from inspect_ai._util.constants import DEFAULT_BATCH_SIZE, DEFAULT_MAX_CONNECTIONS
from inspect_ai._util.format import format_progress_time
from inspect_ai._util.notgiven import sanitize_notgiven
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .batch_log import log_batch

DEFAULT_BATCH_TICK = 15
DEFAULT_SEND_DELAY = DEFAULT_BATCH_TICK
DEFAULT_MAX_BATCHES = 50
DEFAULT_MAX_CONSECUTIVE_CHECK_FAILURES = 1000

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
    consecutive_check_failure_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    age: int = 0


@dataclasses.dataclass
class PendingBatch(Generic[ResponseT]):
    timeout: float
    available_size: int
    requests: list[BatchRequest[ResponseT]] = dataclasses.field(default_factory=list)


class Batcher(Generic[ResponseT, CompletedBatchInfoT]):
    def __init__(
        self,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
        max_batch_request_count: int,
        max_batch_size_mb: int,
    ) -> None:
        self._max_batch_request_count = min(
            max_batch_request_count, config.max_size or sys.maxsize
        )
        self._max_batch_size_bytes = max_batch_size_mb * 1024 * 1024
        self._min_batch_request_count = config.size or DEFAULT_BATCH_SIZE
        self._send_delay = config.send_delay or DEFAULT_SEND_DELAY
        self._tick = config.tick or DEFAULT_BATCH_TICK
        self._max_batches = config.max_batches or DEFAULT_MAX_BATCHES
        self._max_consecutive_check_failures = (
            config.max_consecutive_check_failures
            or DEFAULT_MAX_CONSECUTIVE_CHECK_FAILURES
        )
        self._retry_config = retry_config
        self._intake_queue: list[BatchRequest[ResponseT]] = []
        self._next_batch: PendingBatch[ResponseT] | None = None
        self._inflight_batches: dict[str, Batch[ResponseT]] = {}
        self._is_batch_worker_running: bool = False

    async def generate_for_request(
        self,
        request: dict[str, Any],
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
        from inspect_ai.log._transcript import Transcript, init_transcript

        init_transcript(Transcript())

        while (
            self._inflight_batches
            or self._intake_queue
            or (self._next_batch.requests if self._next_batch else False)
        ):
            await self._check_inflight_batches()

            while await self._process_intake_queue():
                pass

            await anyio.sleep(self._tick)

        self._is_batch_worker_running = False

    async def _check_inflight_batches(self) -> None:
        if self._inflight_batches:
            batches = list(self._inflight_batches.values())
            # Poll batches in chunks to prevent overwhelming the async runtime
            # and HTTP stack connection limits when _max_batches is large (e.g. 1,000+)
            # TODO: Consider adding a new BatchConfig value rather than relying on
            # DEFAULT_MAX_CONNECTIONS
            for i in range(0, len(batches), DEFAULT_MAX_CONNECTIONS):
                await tg_collect(
                    [
                        functools.partial(self._check_inflight_batch, batch)
                        for batch in batches[i : i + DEFAULT_MAX_CONNECTIONS]
                    ]
                )

        self._print_aggregate_status()

    def _print_aggregate_status(self) -> None:
        total, completed, failed, total_age, max_age = functools.reduce(
            _batch_stats_reducer,
            self._inflight_batches.values(),
            (0, 0, 0, 0, 0),
        )
        if total:
            avg_age = (
                total_age // len(self._inflight_batches)
                if self._inflight_batches
                else 0
            )
            log_batch(
                f"Current batches: {len(self._inflight_batches)}, "
                f"requests (pending/completed/failed requests): {total - completed - failed}/{completed}/{failed}, "
                f"batch age (avg/max): {format_progress_time(avg_age, False)}/{format_progress_time(max_age, False)}"
            )

    async def _check_inflight_batch(self, batch: Batch[ResponseT]) -> None:
        check_result = await self._wrapped_check_batch(batch)
        if not check_result:
            return

        batch.completed_count = check_result[0]
        batch.failed_count = check_result[1]
        batch.age = check_result[2]

        if (info := check_result[3]) is not None:
            await self._wrapped_handle_batch_result(batch, info)

    async def _fail_and_cleanup_inflight_batch(
        self,
        description: str,
        batch: Batch[ResponseT],
        error: Exception,
    ) -> None:
        await self._fail_all_requests(
            f"Batch {batch.id} failed ({description}), failing all {len(batch.requests)} requests in batch",
            list(batch.requests.values()),
            error,
        )
        del self._inflight_batches[batch.id]

    async def _fail_all_requests(
        self,
        message: str,
        batch_requests: list[BatchRequest[ResponseT]],
        error: Exception,
    ) -> None:
        log_batch(message)
        for request in batch_requests:
            try:
                await request.result_stream.send(error)
            except anyio.BrokenResourceError:
                # Stream closed (client disconnected/completed) - continue
                # notifying remaining requests
                pass

    async def _process_intake_queue(self) -> bool:
        """Process intake queue and send next batch if conditions are met."""
        if self._next_batch is None:
            self._next_batch = PendingBatch(
                time.time() + self._send_delay,
                int(self._max_batch_size_bytes * 0.95),
            )

        add_count, new_avail, should_send = _assess_intake_queue(
            self._intake_queue,
            self._next_batch,
            self._min_batch_request_count,
            self._max_batch_request_count,
        )

        if add_count:
            self._next_batch = PendingBatch(
                self._next_batch.timeout,
                new_avail,
                self._next_batch.requests + self._intake_queue[:add_count],
            )
            self._intake_queue = self._intake_queue[add_count:]

        if should_send and len(self._inflight_batches) < self._max_batches:
            batch_requests = self._next_batch.requests
            self._next_batch = None

            batch_id = await self._wrapped_create_batch(batch_requests)

            self._inflight_batches[batch_id] = Batch(
                id=batch_id,
                requests={request.custom_id: request for request in batch_requests},
            )
            return True

        return False

    # These _wrapped_* methods are intended to wrap the abstract methods with the
    # appropriate error handling logic consistent with the batch algorithm. This
    # allows the code above to not worry about try/catch'ing the abstract methods.
    # Any exception that escapes a _wrapped_* method will bring down the eval.

    async def _wrapped_create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        @retry(**_with_retry_logging(self._retry_config, "_create_batch"))
        async def _create() -> str:
            return await self._create_batch(batch)

        try:
            result = await _create()
            log_batch(f"Created batch {result} with {len(batch)} requests")
            return result
        except Exception as e:
            await self._fail_all_requests(
                f"Error creating batch, failing all {len(batch)} requests in batch. Error: {e}",
                batch,
                e,
            )
            raise

    async def _wrapped_check_batch(
        self, batch: Batch[ResponseT]
    ) -> tuple[int, int, int, (CompletedBatchInfoT | None)] | None:
        try:
            result = await self._check_batch(batch)
            batch.consecutive_check_failure_count = 0
            return result
        except Exception as e:
            batch.consecutive_check_failure_count += 1
            log_batch(
                f"Error {batch.consecutive_check_failure_count} checking batch {batch.id}. Error: {e}"
            )
            if (
                batch.consecutive_check_failure_count
                >= self._max_consecutive_check_failures
            ):
                await self._fail_and_cleanup_inflight_batch(
                    f"{self._max_consecutive_check_failures} consecutive check failures",
                    batch,
                    e,
                )
            return None

    async def _wrapped_handle_batch_result(
        self,
        batch: Batch[ResponseT],
        completion_info: CompletedBatchInfoT,
    ) -> None:
        @retry(
            **_with_retry_logging(
                self._retry_config, f"_handle_batch_result({batch.id})"
            )
        )
        async def _handle() -> dict[str, ResponseT | Exception]:
            return await self._handle_batch_result(batch, completion_info)

        try:
            log_batch(f"Batch {batch.id} completed")
            await self._resolve_inflight_batch(batch, await _handle())
        except Exception as e:
            await self._fail_and_cleanup_inflight_batch("obtaining results", batch, e)

    async def _resolve_inflight_batch(
        self, batch: Batch[ResponseT], results: dict[str, ResponseT | Exception]
    ) -> None:
        """
        Resolve a batch by sending results to each request and cleaning up inflight state.

        This method iterates over the results dictionary, sends each response or exception
        to the corresponding request's result stream, and removes the batch from the inflight
        batches. It is called internally by the batcher after handling batch results, but
        it is also safe and intended for use by derived classes if they need to manually
        resolve a batch with results.

        Args:
            batch: The batch to resolve.
            results: A dictionary mapping request IDs to their responses or exceptions.

        Notes:
            - Derived class instances may call this method directly if custom batch resolution
              logic is required.
            - This method does not raise exceptions for missing request IDs, but will log if
              the number of results does not match the number of requests.
        """
        # TODO: We don't have any evidence that this actually happens. I
        # think we should just get rid of the code.
        if len(results) != len(batch.requests):
            log_batch(
                f"Attempting to resolve {batch.id} with {len(results)} results, expected {len(batch.requests)}",
            )

        # This function needs its own try/catch since in some cases derived classes
        # call it, and we need to ensure exceptions do not escape
        try:
            for request_id, response in results.items():
                await batch.requests[request_id].result_stream.send(response)
        except Exception as e:
            await self._fail_and_cleanup_inflight_batch("sending results", batch, e)
        finally:
            del self._inflight_batches[batch.id]

    @abstractmethod
    async def _create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        """Create a new batch.

        This method should submit the batch requests to the model and return a
        unique identifier for the created batch. The base class automatically
        handles retries for transient failures using the configured retry policy.

        Args:
            batch: List of batch requests to be processed together.

        Returns:
            A unique string identifier for the created batch.

        Raises:
            Exception: If batch creation fails permanently after all retry attempts.
        """
        pass

    @abstractmethod
    async def _check_batch(
        self, batch: Batch[ResponseT]
    ) -> tuple[int, int, int, (CompletedBatchInfoT | None)]:
        """Check the status of a batch.

        This method should query the model to determine the current status of the
        batch and return information about its progress.

        Args:
            batch: The batch to check status for.

        Returns:
            A tuple containing:
            - Number of completed requests (int)
            - Number of failed requests (int)
            - Age of the batch in seconds (int)
            - Completion info if batch is complete, None otherwise (CompletedBatchInfoT | None)

        Raises:
            Exception: If checking batch status fails. The caller will handle
                consecutive failures and may eventually fail the batch.
        """
        pass

    @abstractmethod
    async def _handle_batch_result(
        self,
        batch: Batch[ResponseT],
        completion_info: CompletedBatchInfoT,
    ) -> dict[str, ResponseT | Exception]:
        """Process the results of a completed batch.

        This method should retrieve and process the results from a completed batch,
        mapping each request to its corresponding response or error. The base class
        automatically handles retries for transient failures using the configured
        retry policy.

        Args:
            batch: The completed batch to process.
            completion_info: Provider-specific completion information returned
                by _check_batch when the batch completed.

        Returns:
            A dictionary mapping request custom_ids to their responses or exceptions.
            Each value is either a successful response (ResponseT) or an Exception
            if that specific request failed.

        Raises:
            Exception: If processing the batch results fails permanently after all
                retry attempts. This will cause all requests in the batch to fail
                with this exception.
        """
        pass


def _assess_intake_queue(
    intake_queue: list[BatchRequest[ResponseT]],
    batch: PendingBatch[ResponseT],
    min_request_count: int,
    max_request_count: int,
) -> tuple[int, int, bool]:
    """Assess the intake queue and determine what should be done with the current batch.

    This function determines two things:

    1. How many (if any) requests from the `intake_queue` can be added to `batch`.
       This is constrained by `batch.available_size` and `max_batch_request_count`
       - neither of which can be exceeded.

    2. Whether the resulting/post-add batch should be sent now or not. This will
       be `True` if the post-add batch is:
       - full - either request count or bytes
       - has at least `min_batch_request_count` requests
       - has waited until `batch.timeout` to send the batch

    At a high level, the algorithm endeavors to add as many requests as possible
    from the `intake_queue` to the `batch`, while respecting all constraints.

    Args:
        intake_queue: List of batch requests waiting to be processed
        batch: Current batch being assembled
        min_request_count: Minimum number of requests before sending
        max_request_count: Maximum number of requests allowed in a batch

    Returns:
        A tuple of (add_count, new_available_size, should_send) where:
        - add_count: Number of requests to add from intake_queue to pending_batch
        - new_available_size: Remaining available size in bytes after adding requests
        - should_send: Whether the batch should be sent now
    """
    add_count = 0
    current_count = len(batch.requests)
    available_count = max_request_count - current_count
    available_size = batch.available_size
    batch_full = available_count <= 0 or available_size <= 0

    for request in intake_queue:
        if batch_full:
            break

        request_size = len(
            json.dumps(sanitize_notgiven(request.request), separators=(",", ":"))
        )

        if request_size > available_size:
            if current_count + add_count == 0:
                raise ValueError(
                    f"Single request size {request_size} exceeds maximum size {available_size}."
                )
            batch_full = True
        else:
            # Request fits, add it
            add_count += 1
            available_size -= request_size
            available_count -= 1
            batch_full = available_count <= 0

    should_send = (
        batch_full
        or ((new_count := current_count + add_count) >= min_request_count)
        or (time.time() > batch.timeout and new_count > 0)
    )

    return add_count, available_size, should_send


def _batch_stats_reducer(
    acc: tuple[int, int, int, int, int], batch: Batch[ResponseT]
) -> tuple[int, int, int, int, int]:
    total_requests, completed_requests, failed_requests, total_age, max_age = acc
    return (
        total_requests + len(batch.requests),
        completed_requests + batch.completed_count,
        failed_requests + batch.failed_count,
        total_age + batch.age,
        max(max_age, batch.age),
    )


def _log_retry(operation: str, retry_state: RetryCallState) -> None:
    log_batch(
        f"-> Batch {operation} last outcome: {retry_state.outcome} retry {retry_state.attempt_number} (retrying in {retry_state.upcoming_sleep:,.0f} seconds)"
    )


def _with_retry_logging(config: ModelRetryConfig, operation: str) -> ModelRetryConfig:
    tweaked_retry_config: ModelRetryConfig = config.copy()
    tweaked_retry_config["before_sleep"] = functools.partial(_log_retry, operation)
    return tweaked_retry_config
