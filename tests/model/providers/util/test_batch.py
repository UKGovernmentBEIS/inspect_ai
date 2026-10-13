from __future__ import annotations

import functools
import json
import sys
import time

import anyio
import pytest
from tenacity import RetryError
from tenacity.wait import wait_none
from typing_extensions import TypedDict

from inspect_ai._util._async import tg_collect

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers.util.batch import (
    BatchCheckResult,
    Batcher,
    BatchRequest,
)
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.model._retry import model_retry_config


class FakeCompletionInfo(TypedDict):
    """Test-specific completion info for batch results."""

    result_uris: list[str]


class FakeBatcher(Batcher[str, FakeCompletionInfo]):
    """Test implementation of Batcher that simulates realistic behavior."""

    def __init__(
        self,
        *,
        config: BatchConfig | None = None,
        batch_completion_delay: float = 0.01,
        fail_batch_ids: set[str] | None = None,
        fail_request_ids: set[str] | None = None,
        handle_batch_error: Exception | None = None,
    ):
        """Initialize test batcher.

        Args:
            config: Batch configuration
            batch_completion_delay: How long batches take to "complete"
            fail_batch_ids: Set of batch IDs that should fail during processing
            fail_request_ids: Set of request custom_ids that should return errors
            handle_batch_error: Error to raise when handling batch results
        """
        super().__init__(
            config or BatchConfig(size=3, send_delay=0.01, tick=0.001),
            model_retry_config(
                "test",
                3,
                None,
                lambda e: True,
                lambda ex: None,
                lambda m, s: None,
                wait=wait_none(),
            ),
            max_batch_request_count=10,
            max_batch_size_mb=1,
        )
        self._batch_completion_delay = batch_completion_delay
        self._fail_batch_ids = fail_batch_ids or set()
        self._fail_request_ids = fail_request_ids or set()
        self._handle_batch_error = handle_batch_error

        # Track batches for simulation
        self._created_batches: dict[str, list[str]] = {}  # batch_id -> request_ids
        self._batch_creation_times: dict[str, float] = {}
        self._next_batch_id = 0

    async def _create_batch(self, batch_requests) -> str:
        """Simulate creating a batch in an external service."""
        batch_id = f"batch-{self._next_batch_id}"
        self._next_batch_id += 1

        # Simulate some creation delay
        await anyio.sleep(0.001)

        # Store batch info for later completion simulation
        self._created_batches[batch_id] = [req.custom_id for req in batch_requests]
        self._batch_creation_times[batch_id] = time.time()

        return batch_id

    async def _check_batch(self, batch) -> BatchCheckResult[FakeCompletionInfo]:
        """Simulate checking batch status."""
        batch_id = batch.id

        # Simulate check delay
        await anyio.sleep(0.001)

        # Check if batch should fail
        if batch_id in self._fail_batch_ids:
            raise Exception(f"Simulated batch failure for {batch_id}")

        creation_time = self._batch_creation_times.get(batch_id, time.time())

        # Check if batch is "complete" based on elapsed time
        if time.time() - creation_time >= self._batch_completion_delay:
            # Batch is complete
            request_count = len(self._created_batches[batch_id])
            return BatchCheckResult(
                completed_count=request_count,
                failed_count=0,
                created_at=int(creation_time),
                completion_info=FakeCompletionInfo(result_uris=[f"result-{batch_id}"]),
            )
        else:
            # Still processing
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=int(creation_time),
                completion_info=None,
            )

    async def _handle_batch_result(
        self, batch, completion_info: FakeCompletionInfo
    ) -> dict[str, str | Exception]:
        """Simulate processing batch results."""
        # Check for simulated handle error
        if self._handle_batch_error:
            raise self._handle_batch_error

        # Simulate processing delay
        await anyio.sleep(0.001)

        results: dict[str, str | Exception] = {}
        for request_id in self._created_batches[batch.id]:
            if request_id in self._fail_request_ids:
                results[request_id] = Exception(f"Simulated failure for {request_id}")
            else:
                results[request_id] = f"result-for-{request_id}"

        return results


class TestBatcher:
    """Integration tests for Batcher that test end-to-end behavior."""

    async def _run_with_task_group(self, test_func):
        """Helper to run test logic within a TaskGroup context."""
        from inspect_ai._util.background import set_background_task_group

        async with anyio.create_task_group() as tg:
            set_background_task_group(tg)
            try:
                await test_func()
            finally:
                set_background_task_group(None)

    async def test_successful_single_request(self):
        """Test that a single request gets processed successfully."""

        async def test_logic():
            batcher = FakeBatcher()

            # Make a request
            result = await batcher.generate_for_request(request={"prompt": "test"})

            # Should get back a successful result
            assert result.startswith("result-for-")

        await self._run_with_task_group(test_logic)

    async def test_successful_batch_processing(self):
        """Test that multiple requests get batched and processed together."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(size=3, send_delay=0.01, tick=0.001)
            )

            # Make multiple requests concurrently
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(5)
                ]
            )

            # All requests should succeed
            assert len(results) == 5
            for result in results:
                assert result.startswith("result-for-")

        await self._run_with_task_group(test_logic)

    async def test_batch_worker_runs_outside_the_requesting_model_event(self):
        """Batch-level API calls must not be attributed to the request that started the worker."""
        from inspect_ai.event._model import ModelEvent
        from inspect_ai.log._samples import (
            has_active_model_event,
            track_active_model_event,
        )
        from inspect_ai.model import GenerateConfig, ModelOutput

        worker_saw_model_event: list[bool] = []

        class RecordingBatcher(FakeBatcher):
            async def _create_batch(self, batch_requests) -> str:
                worker_saw_model_event.append(has_active_model_event())
                return await super()._create_batch(batch_requests)

        async def test_logic():
            batcher = RecordingBatcher()
            event = ModelEvent(
                model="test",
                input=[],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(model="test", choices=[]),
            )
            with track_active_model_event(event):
                result = await batcher.generate_for_request({"prompt": "test"})

            assert result.startswith("result-for-")
            assert worker_saw_model_event == [False]

        await self._run_with_task_group(test_logic)

    async def test_batch_creation_failure(self):
        """Test handling of batch creation failures."""

        async def test_logic():
            batcher = FakeBatcher()

            # Override _create_batch to always fail
            async def failing_create_batch(_batch_requests):
                raise Exception("Batch creation failed")

            batcher._create_batch = failing_create_batch

            # Request should fail with the creation error wrapped in RetryError
            with pytest.raises(RetryError):
                await batcher.generate_for_request({"prompt": "test"})

        # Run the test within task group context, expecting ExceptionGroup
        try:
            await self._run_with_task_group(test_logic)
        except ExceptionGroup as eg:
            # Should contain a RetryError wrapped in the ExceptionGroup
            exceptions = eg.exceptions
            assert len(exceptions) >= 1
            assert any(isinstance(exc, RetryError) for exc in exceptions)
        except RetryError:
            # Direct RetryError is also acceptable
            pass

    async def test_batch_check_failure_retry(self):
        """Test that batch check failures are retried appropriately."""

        async def test_logic():
            # Create batcher that fails batch checks initially
            batcher = FakeBatcher(fail_batch_ids={"batch-0"})

            result = None

            async with anyio.create_task_group() as tg:

                async def run_request() -> None:
                    nonlocal result
                    result = await batcher.generate_for_request({"prompt": "test"})

                tg.start_soon(run_request)

                # Let it fail a few times
                await anyio.sleep(0.01)

                # Remove the failure condition
                batcher._fail_batch_ids.clear()

            # Request should eventually succeed
            assert result is not None
            assert result.startswith("result-for-")

        await self._run_with_task_group(test_logic)

    async def test_batch_result_handling_failure(self):
        """Test handling of failures during batch result processing."""

        async def test_logic():
            handle_error = Exception("Result handling failed")
            batcher = FakeBatcher(handle_batch_error=handle_error)

            # Request should fail with the handling error wrapped in RetryError
            with pytest.raises(RetryError):
                await batcher.generate_for_request({"prompt": "test"})

        await self._run_with_task_group(test_logic)

    async def test_batch_size_limits(self):
        """Test that batch minimum size controls when batches are sent."""

        async def test_logic():
            # Test with minimum batch size of 3 and a longer delay
            # This should send a batch when it reaches 3 requests, not wait for the delay
            batcher = FakeBatcher(
                config=BatchConfig(size=3, send_delay=0.1, tick=0.001)
            )

            # Send exactly 3 requests - should trigger batch send due to minimum size being reached
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(3)
                ]
            )

            # All should complete successfully
            assert len(results) == 3

            # Should have created exactly one batch with all 3 requests
            assert len(batcher._created_batches) == 1
            batch_id = next(iter(batcher._created_batches.keys()))
            assert len(batcher._created_batches[batch_id]) == 3

        await self._run_with_task_group(test_logic)

    async def test_batch_timeout_behavior(self):
        """Test that batches are sent after timeout even if not full."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=10, send_delay=0.01, tick=0.001
                )  # Large size, short timeout
            )

            # Send fewer requests than batch size
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(3)
                ]
            )

            # Should complete due to timeout, not batch size
            assert len(results) == 3
            assert len(batcher._created_batches) == 1

        await self._run_with_task_group(test_logic)

    async def test_concurrent_batches(self):
        """Test that multiple batches can be processed concurrently."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1, max_size=2, send_delay=0.01, tick=0.001, max_batches=3
                ),
                batch_completion_delay=0.02,  # Longer delay to ensure overlap
            )

            # Send many requests to force multiple concurrent batches
            # With max_size=2, 8 requests will require at least 4 batches
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(8)
                ]
            )
            assert len(results) == 8

            # Should have created multiple batches due to max_size=2 limit
            assert (
                len(batcher._created_batches) >= 4
            )  # 8 requests / 2 max per batch = 4 batches

            # Verify that no batch exceeds the max_size limit
            for _, request_ids in batcher._created_batches.items():
                assert len(request_ids) <= 2

        await self._run_with_task_group(test_logic)

    async def test_high_concurrency_stress(self):
        """Stress test with many concurrent requests."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(size=5, send_delay=0.01, tick=0.001),
                batch_completion_delay=0.02,
            )

            # Create many concurrent requests
            num_requests = 20

            # All should complete successfully
            start_time = time.time()
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"stress-test-{i}"}
                    )
                    for i in range(num_requests)
                ]
            )
            elapsed = time.time() - start_time

            assert len(results) == num_requests
            for result in results:
                assert result.startswith("result-for-")

            # Should be reasonably fast due to batching
            assert elapsed < 2.0  # Generous upper bound

            # Should have created fewer batches than requests for efficiency
            # With size=5 (min) and max_batch_request_count=10, 50 requests should create at most 10 batches
            # (if all batches had exactly 5 requests) but more likely around 5-6 batches
            assert len(batcher._created_batches) <= num_requests // 5
            # But should have created more than 1 batch to demonstrate batching is working
            assert len(batcher._created_batches) > 1

        await self._run_with_task_group(test_logic)

    async def test_what_wrapped_handle_batch_result_was_testing(self):
        """Test better approach to what test_batcher_wrapped_handle_batch_result was testing.

        Instead of testing the private _wrapped_handle_batch_result method directly,
        we test the observable behavior: do requests get the right results when
        batches complete successfully or fail during result handling?
        """

        async def test_logic():
            # Test 1: Successful batch result handling
            batcher = FakeBatcher(
                config=BatchConfig(size=2, send_delay=0.01, tick=0.001),
                batch_completion_delay=0.01,
            )

            # Make requests that should succeed
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"test-success-{i}"}
                    )
                    for i in range(3)
                ]
            )

            # All requests should get successful results
            assert len(results) == 3
            for result in results:
                assert result.startswith("result-for-")

            # Test 2: Batch result handling failure should fail all requests in that batch
            batcher_fail = FakeBatcher(
                config=BatchConfig(size=3, send_delay=0.01, tick=0.001),
                handle_batch_error=Exception("Batch result handling failed"),
            )

            # All requests in the failing batch should get the error wrapped in RetryError
            with pytest.raises(RetryError):
                await batcher_fail.generate_for_request({"prompt": "test-fail"})

            # Test 3: Individual request failures within a successful batch
            batcher_mixed = FakeBatcher(
                config=BatchConfig(size=3, send_delay=0.01, tick=0.001),
                fail_request_ids={"fail-me"},  # One specific request will fail
            )

            # Create requests with specific custom IDs to control failures
            send_streams = []
            receive_streams = []

            for i, custom_id in enumerate(["success-1", "fail-me", "success-2"]):
                send_stream, receive_stream = anyio.create_memory_object_stream[
                    str | Exception
                ](1)
                request = BatchRequest[str](
                    request={"prompt": f"test-{i}"},
                    result_stream=send_stream,
                    custom_id=custom_id,
                )
                batcher_mixed._intake_queue.append(request)
                send_streams.append(send_stream)
                receive_streams.append(receive_stream)

            # Start the batch worker and collect results concurrently
            collected_results = []

            async with anyio.create_task_group() as tg:
                tg.start_soon(batcher_mixed._batch_worker)

                # Collect results
                for receive_stream in receive_streams:
                    try:
                        result = await receive_stream.receive()
                        if isinstance(result, Exception):
                            collected_results.append(f"ERROR: {result}")
                        else:
                            collected_results.append(result)
                    except Exception as e:
                        collected_results.append(f"EXCEPTION: {e}")

                tg.cancel_scope.cancel()

            # Verify that the right request failed and others succeeded
            assert len(collected_results) == 3
            assert collected_results[0].startswith("result-for-success-1")  # Success
            assert (
                "ERROR:" in collected_results[1] and "fail-me" in collected_results[1]
            )  # Failed
            assert collected_results[2].startswith("result-for-success-2")  # Success

        await self._run_with_task_group(test_logic)

    async def test_maximum_batch_size_limits(self):
        """Test that maximum batch size limits force multiple batches."""

        async def test_logic():
            # Use BatchConfig.max_size to limit batches to 2 requests each
            batcher = FakeBatcher(
                config=BatchConfig(size=1, max_size=2, send_delay=0.01, tick=0.001)
            )

            # Send more requests than the maximum batch size
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(5)
                ]
            )

            # All should complete successfully
            assert len(results) == 5

            # Should have created multiple batches due to max_size limit
            assert (
                len(batcher._created_batches) >= 3
            )  # 5 requests / 2 max per batch = 3 batches

            # Verify that no batch has more than 2 requests
            for _, request_ids in batcher._created_batches.items():
                assert len(request_ids) <= 2

        await self._run_with_task_group(test_logic)

    async def test_batch_timeout_with_insufficient_requests(self):
        """Test that batches are sent after timeout even when below minimum size."""

        async def test_logic():
            # Set a high minimum size (5) but send fewer requests (2)
            # The batch should be sent after the send_delay timeout
            batcher = FakeBatcher(
                config=BatchConfig(size=5, send_delay=0.02, tick=0.001)
            )

            # Send fewer requests than minimum batch size
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(2)
                ]
            )

            # Should complete due to timeout, not minimum size
            assert len(results) == 2

            # Should have created exactly one batch with only 2 requests (below minimum)
            assert len(batcher._created_batches) == 1
            batch_id = next(iter(batcher._created_batches.keys()))
            assert len(batcher._created_batches[batch_id]) == 2

        await self._run_with_task_group(test_logic)

    async def test_batch_config_interaction(self):
        """Test the interaction between size (min), max_size (max), and send_delay."""

        async def test_logic():
            # Test scenario: min_size=3, max_size=5, send_delay=0.02
            # Send 4 requests: should send immediately since 4 >= 3 (min_size)
            batcher = FakeBatcher(
                config=BatchConfig(size=3, max_size=5, send_delay=0.02, tick=0.001)
            )

            # Send 4 requests (between min and max)
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"test-{i}"})
                    for i in range(4)
                ]
            )

            # Should complete immediately (since 4 >= 3 min_size)
            assert len(results) == 4

            # Should have created exactly one batch with all 4 requests
            assert len(batcher._created_batches) == 1
            batch_id = next(iter(batcher._created_batches.keys()))
            assert len(batcher._created_batches[batch_id]) == 4

            # Now test max_size enforcement - send 6 requests to exceed max_size=5
            batcher2 = FakeBatcher(
                config=BatchConfig(size=2, max_size=5, send_delay=0.02, tick=0.001)
            )

            results2 = await tg_collect(
                [
                    lambda i=i: batcher2.generate_for_request({"prompt": f"test2-{i}"})
                    for i in range(6)
                ]
            )
            assert len(results2) == 6

            # Should have created at least 2 batches (6 requests can't fit in max_size=5)
            assert len(batcher2._created_batches) >= 2

            # Verify no batch exceeds max_size=5
            for batch_id, request_ids in batcher2._created_batches.items():
                assert len(request_ids) <= 5

        await self._run_with_task_group(test_logic)

    async def test_max_consecutive_check_failures(self):
        """Test that batches fail after max consecutive check failures."""

        async def test_logic():
            # Create a batcher with a low max_consecutive_check_failures value
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.001,
                    max_consecutive_check_failures=3,
                ),
                fail_batch_ids={"batch-0"},  # First batch will always fail
            )

            # Start a request that will be in the failing batch
            exc_raised = None

            async with anyio.create_task_group() as tg:

                async def run_request() -> None:
                    nonlocal exc_raised
                    try:
                        await batcher.generate_for_request({"prompt": "test"})
                    except Exception as e:
                        exc_raised = e

                tg.start_soon(run_request)

            # Wait for the batch to fail after the configured number of failures
            assert exc_raised is not None
            assert "Simulated batch failure for batch-0" in str(exc_raised)

            # Verify the batch was indeed removed from inflight batches
            assert len(batcher._inflight_batches) == 0

        await self._run_with_task_group(test_logic)

    async def test_max_consecutive_check_failures_with_default_value(self):
        """Test that default max consecutive check failures value is used when not specified."""

        async def test_logic():
            # Create batcher without specifying max_consecutive_check_failures
            batcher = FakeBatcher(
                config=BatchConfig(size=1, send_delay=0.01, tick=0.001)
            )

            # Verify that the default value is used
            assert batcher._max_consecutive_check_failures == 1000

        await self._run_with_task_group(test_logic)

    async def test_max_consecutive_check_failures_with_custom_value(self):
        """Test that custom max consecutive check failures value is used when specified."""

        async def test_logic():
            custom_max_failures = 5
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.001,
                    max_consecutive_check_failures=custom_max_failures,
                )
            )

            # Verify that the custom value is used
            assert batcher._max_consecutive_check_failures == custom_max_failures

        await self._run_with_task_group(test_logic)

    async def test_consecutive_check_failures_reset_on_success(self):
        """Test that consecutive check failure count resets on successful check."""

        async def test_logic():
            # Create a batcher that will fail initially then succeed
            # Use a high failure ceiling so a slow test runner can't push the
            # batch into permanent failure before the failure condition is
            # cleared below.
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.001,
                    max_consecutive_check_failures=10_000,
                ),
                fail_batch_ids={"batch-0"},
            )

            result = None

            async with anyio.create_task_group() as tg:

                async def run_request() -> None:
                    nonlocal result
                    result = await batcher.generate_for_request({"prompt": "test"})

                tg.start_soon(run_request)

                # Wait until the batch has recorded at least one check failure
                # (a fixed sleep races with the batch worker on slow runners)
                with anyio.fail_after(10):
                    while not (
                        failed := [
                            batch
                            for batch in batcher._inflight_batches.values()
                            if batch.consecutive_check_failure_count > 0
                        ]
                    ):
                        await anyio.sleep(0.001)

                # Remove the failure condition to allow success
                batcher._fail_batch_ids.clear()

            # The request should eventually succeed
            assert result is not None
            assert result.startswith("result-for-")

            # The successful check reset the failure count before completion
            assert failed[0].consecutive_check_failure_count == 0

        await self._run_with_task_group(test_logic)

    async def test_boundary_extremely_large_requests(self):
        """Test handling of requests that are close to byte size limits."""

        async def test_logic():
            # Set a small byte limit to test boundary conditions
            batcher = FakeBatcher(
                config=BatchConfig(size=1, send_delay=0.01, tick=0.001)
            )
            # Override the max batch size to be small for testing
            batcher._max_batch_size_bytes = 1000  # 1KB limit

            # Create a request that's close to but under the limit
            large_data = "x" * 800  # Should fit
            result = await batcher.generate_for_request({"large_payload": large_data})
            assert result.startswith("result-for-")

            # Verify exactly one batch was created
            assert len(batcher._created_batches) == 1

        await self._run_with_task_group(test_logic)

    async def test_config_max_batch_request_count_smaller_than_max_size(self):
        """Test when constructor max_batch_request_count is smaller than config.max_size."""

        async def test_logic():
            # Constructor param should take precedence and limit the effective max_size
            batcher = FakeBatcher(
                config=BatchConfig(size=1, max_size=10, send_delay=0.01, tick=0.001),
                # This should override the config.max_size
            )
            batcher._max_batch_request_count = (
                3  # Override to be smaller than config.max_size
            )

            # Send more requests than the effective limit
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"constrained-{i}"}
                    )
                    for i in range(8)
                ]
            )
            assert len(results) == 8

            # Should have created batches with at most 3 requests each
            for _, request_ids in batcher._created_batches.items():
                assert len(request_ids) <= 3

        await self._run_with_task_group(test_logic)

    async def test_config_max_size_smaller_than_size(self):
        """Test invalid config where max_size < size (should handle gracefully)."""

        async def test_logic():
            # This creates a contradictory configuration
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=5,  # Minimum size
                    max_size=3,  # Maximum size smaller than minimum - invalid!
                    send_delay=0.01,
                    tick=0.001,
                )
            )

            # Should still work - implementation should handle this gracefully
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"invalid-config-{i}"}
                    )
                    for i in range(4)
                ]
            )
            assert len(results) == 4

            # Should respect the smaller max_size limit
            for _, request_ids in batcher._created_batches.items():
                assert len(request_ids) <= 3

        await self._run_with_task_group(test_logic)

    async def test_config_byte_limit_vs_count_limit_interaction(self):
        """Test interaction between byte size limits and count limits."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=2,  # Min 2 requests
                    max_size=10,  # Max 10 requests
                    send_delay=0.01,
                    tick=0.001,
                )
            )

            # Set a very small byte limit that should be hit before count limit
            batcher._max_batch_size_bytes = 200

            # Create requests that will hit byte limit before count limit
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"data": f"medium-sized-request-{i:03d}-{'x' * 20}"}
                    )
                    for i in range(8)
                ]
            )
            assert len(results) == 8

            # Should have created multiple batches due to byte limit, not count limit
            assert len(batcher._created_batches) > 1

            # Each batch should have fewer than max_size requests due to byte constraints
            for _, request_ids in batcher._created_batches.items():
                assert len(request_ids) < 10  # Hit byte limit before count limit

        await self._run_with_task_group(test_logic)

    async def test_config_tick_faster_than_send_delay(self):
        """Test when tick interval is faster than send_delay."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=5,  # High minimum size
                    send_delay=0.02,  # 20ms delay
                    tick=0.001,  # 1ms tick - much faster than send_delay
                )
            )

            # Send fewer requests than minimum size
            start_time = time.time()
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"fast-tick-{i}"}
                    )
                    for i in range(3)
                ]
            )
            elapsed = time.time() - start_time

            assert len(results) == 3

            # Should complete after send_delay timeout, not wait for minimum size
            # Should be close to send_delay time (0.02s), not much longer
            assert 0.01 < elapsed < 0.1  # Some tolerance for timing

        await self._run_with_task_group(test_logic)

    async def test_config_tick_slower_than_batch_completion(self):
        """Test when tick interval is slower than batch completion time."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.02,  # 20ms tick - slower than batch completion
                ),
                batch_completion_delay=0.005,  # Batches complete in 5ms
            )

            # Send requests that should complete between ticks
            start_time = time.time()
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"slow-tick-{i}"}
                    )
                    for i in range(3)
                ]
            )
            elapsed = time.time() - start_time

            assert len(results) == 3

            # Should still complete reasonably quickly despite slow tick
            # May take a few tick cycles to detect completion
            assert elapsed < 1.0  # Should complete within reasonable time

        await self._run_with_task_group(test_logic)

    async def test_config_max_batches_with_high_concurrency(self):
        """Test max_batches limit with high request concurrency."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    max_size=2,  # Small batches
                    send_delay=0.01,
                    tick=0.001,
                    max_batches=2,  # Only 2 concurrent batches allowed
                ),
                batch_completion_delay=0.02,  # Longer completion time
            )

            # Send many requests that would normally create more batches
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"limited-{i}"})
                    for i in range(10)
                ]
            )
            assert len(results) == 10

            # Should have created more batches than max_batches due to queuing
            # But at any given time, only max_batches should be in flight
            total_batches = len(batcher._created_batches)
            assert total_batches >= 2  # At least some batches were created

        await self._run_with_task_group(test_logic)

    async def test_config_zero_values_interaction(self):
        """Test behavior with zero/minimal values in configuration."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=0,  # Zero minimum size - should use default
                    max_size=1,  # Minimal max size
                    send_delay=0,  # Zero delay - immediate send
                    tick=0.001,  # Very fast tick
                    max_batches=1,  # Only one batch at a time
                )
            )

            # Send multiple requests
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"zero-config-{i}"}
                    )
                    for i in range(3)
                ]
            )
            assert len(results) == 3

            # Should handle zero values gracefully
            assert len(batcher._created_batches) >= 1

        await self._run_with_task_group(test_logic)

    async def test_config_extreme_values_interaction(self):
        """Test behavior with extreme configuration values."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    max_size=1000,  # Very large max size
                    send_delay=1.0,  # Moderate delay
                    tick=0.001,  # Very fast tick
                    max_batches=100,  # Many concurrent batches
                )
            )

            # Send a moderate number of requests
            # Should complete quickly despite long send_delay due to reaching minimum size
            start_time = time.time()
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request({"prompt": f"extreme-{i}"})
                    for i in range(5)
                ]
            )
            elapsed = time.time() - start_time

            assert len(results) == 5

            # Should complete much faster than send_delay since we meet minimum size
            assert elapsed < 0.5  # Much less than the 1s send_delay

        await self._run_with_task_group(test_logic)

    async def test_config_send_delay_vs_tick_precision(self):
        """Test precision issues when send_delay and tick are very close."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=10,  # High minimum size
                    send_delay=0.01,  # 10ms delay
                    tick=0.009,  # 9ms tick - very close to send_delay
                )
            )

            # Send fewer requests than minimum size
            start_time = time.time()
            results = await tg_collect(
                [
                    lambda i=i: batcher.generate_for_request(
                        {"prompt": f"precision-{i}"}
                    )
                    for i in range(3)
                ]
            )
            elapsed = time.time() - start_time

            assert len(results) == 3

            # Should timeout properly despite close timing values. The lower
            # bound is the real check (the batch is under `size`, so it can only
            # be sent once `send_delay` elapses); the upper bound is deliberately
            # generous because the nominal path is ~31ms under trio and a loaded
            # CI runner can stretch each 9ms tick several-fold. It still catches
            # a regression to the 15s DEFAULT_SEND_DELAY/DEFAULT_BATCH_TICK.
            assert 0.005 < elapsed < 1.0

        await self._run_with_task_group(test_logic)

    async def test_config_max_consecutive_failures_with_timing(self):
        """Test max_consecutive_check_failures interaction with tick timing."""

        async def test_logic():
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.005,  # 5ms tick
                    max_consecutive_check_failures=2,  # Low failure tolerance
                ),
                fail_batch_ids={"batch-0"},
            )

            # Start a request that will fail
            exc_raised = None

            start_time = time.time()
            async with anyio.create_task_group() as tg:

                async def run_request() -> None:
                    nonlocal exc_raised
                    try:
                        await batcher.generate_for_request({"prompt": "timing-failure"})
                    except Exception as e:
                        exc_raised = e

                tg.start_soon(run_request)

            elapsed = time.time() - start_time

            # Should fail after configured number of failures
            assert exc_raised is not None

            # Should fail relatively quickly based on tick timing
            assert elapsed < 0.5  # Should fail within reasonable time

        await self._run_with_task_group(test_logic)


class HeaderRecordingBatcher(FakeBatcher):
    """FakeBatcher that records each created batch's requests and headers."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.created: list[tuple[list[str], dict[str, str], float]] = []

    async def _create_batch(self, batch_requests) -> str:
        headers = {
            k: v
            for k, v in (batch_requests[0].request.get("extra_headers") or {}).items()
            if k != HttpxHooks.REQUEST_ID_HEADER
        }
        self.created.append(
            ([req.request["prompt"] for req in batch_requests], headers, time.time())
        )
        return await super()._create_batch(batch_requests)


def _headers_request(prompt: str, **headers: str) -> dict[str, object]:
    return {
        "prompt": prompt,
        "extra_headers": {HttpxHooks.REQUEST_ID_HEADER: f"rid-{prompt}"} | headers,
    }


async def _run_in_background_group(test_func) -> None:
    from inspect_ai._util.background import set_background_task_group

    async with anyio.create_task_group() as tg:
        set_background_task_group(tg)
        try:
            await test_func()
        finally:
            set_background_task_group(None)


async def test_batcher_separates_requests_with_different_headers() -> None:
    async def test_logic() -> None:
        batcher = HeaderRecordingBatcher(
            config=BatchConfig(size=10, send_delay=0.02, tick=0.001)
        )
        await tg_collect(
            [
                lambda: batcher.generate_for_request(
                    _headers_request("a1", **{"x-org": "a"})
                ),
                lambda: batcher.generate_for_request(
                    _headers_request("b1", **{"x-org": "b"})
                ),
                lambda: batcher.generate_for_request(
                    _headers_request("a2", **{"x-org": "a"})
                ),
            ]
        )
        batches = sorted(
            (sorted(prompts), headers) for prompts, headers, _ in batcher.created
        )
        assert batches == [
            (["a1", "a2"], {"x-org": "a"}),
            (["b1"], {"x-org": "b"}),
        ]

    await _run_in_background_group(test_logic)


async def test_batcher_requests_differing_only_in_request_id_share_a_batch() -> None:
    async def test_logic() -> None:
        batcher = HeaderRecordingBatcher(
            config=BatchConfig(size=3, send_delay=0.02, tick=0.001)
        )
        await tg_collect(
            [
                functools.partial(
                    batcher.generate_for_request,
                    _headers_request(f"p{i}", **{"x-org": "a"}),
                )
                for i in range(3)
            ]
        )
        assert len(batcher.created) == 1
        prompts, headers, _ = batcher.created[0]
        assert sorted(prompts) == ["p0", "p1", "p2"]
        assert headers == {"x-org": "a"}

    await _run_in_background_group(test_logic)


async def test_batcher_lone_header_set_sent_after_send_delay() -> None:
    """A request with unique headers does not wait for its own batch to fill."""
    send_delay = 0.05

    async def test_logic() -> None:
        batcher = HeaderRecordingBatcher(
            config=BatchConfig(size=10, send_delay=send_delay, tick=0.001)
        )
        start = time.time()
        await tg_collect(
            [
                functools.partial(
                    batcher.generate_for_request,
                    _headers_request(f"a{i}", **{"x-org": "a"}),
                )
                for i in range(10)
            ]
            + [
                lambda: batcher.generate_for_request(
                    _headers_request("b", **{"x-org": "b"})
                )
            ]
        )
        assert len(batcher.created) == 2
        (a_prompts, _, _), (b_prompts, _, b_created) = batcher.created
        assert len(a_prompts) == 10
        assert b_prompts == ["b"]
        assert b_created - start < send_delay + 0.5

    await _run_in_background_group(test_logic)


async def test_batcher_sends_oldest_ready_header_set_first() -> None:
    """When batch slots are scarce, one header set cannot take every slot."""
    batcher = HeaderRecordingBatcher(
        config=BatchConfig(
            size=1, max_size=1, send_delay=0.01, tick=0.001, max_batches=1
        ),
        batch_completion_delay=0.02,
    )
    # queue the requests directly so their arrival order is fixed
    receive_streams = []
    for prompt, org in [("a1", "a"), ("a2", "a"), ("b1", "b"), ("a3", "a")]:
        send_stream, receive_stream = anyio.create_memory_object_stream[
            str | Exception
        ](1)
        batcher._intake_queue.append(
            BatchRequest[str](
                request=_headers_request(prompt, **{"x-org": org}),
                result_stream=send_stream,
            )
        )
        receive_streams.append(receive_stream)

    async with anyio.create_task_group() as tg:
        tg.start_soon(batcher._batch_worker)
        for receive_stream in receive_streams:
            assert isinstance(await receive_stream.receive(), str)

    assert [prompts for prompts, _, _ in batcher.created] == [
        ["a1"],
        ["b1"],
        ["a2"],
        ["a3"],
    ]


async def test_batcher_drops_header_sets_once_sent() -> None:
    """Header sets that have been sent leave no pending state behind."""

    async def test_logic() -> None:
        batcher = HeaderRecordingBatcher(
            config=BatchConfig(size=1, send_delay=0.01, tick=0.001)
        )
        await tg_collect(
            [
                functools.partial(
                    batcher.generate_for_request,
                    _headers_request(f"p{i}", **{"x-routing": str(i)}),
                )
                for i in range(50)
            ]
        )
        assert len(batcher.created) == 50
        assert batcher._next_batches == {}

    await _run_in_background_group(test_logic)


async def test_batcher_send_delay_runs_from_last_batch_sent() -> None:
    """A request arriving after `send_delay` has passed since the last batch is sent at once."""
    send_delay = 0.5

    async def test_logic() -> None:
        batcher = HeaderRecordingBatcher(
            config=BatchConfig(size=10, send_delay=send_delay, tick=0.001)
        )
        await batcher.generate_for_request(_headers_request("first", **{"x-org": "a"}))
        await anyio.sleep(send_delay)

        start = time.time()
        await batcher.generate_for_request(_headers_request("second", **{"x-org": "a"}))
        assert len(batcher.created) == 2
        assert batcher.created[1][2] - start < send_delay / 2

    await _run_in_background_group(test_logic)


def _send_stream() -> anyio.abc.ObjectSendStream[str | Exception]:
    send_stream, _ = anyio.create_memory_object_stream[str | Exception](1)
    return send_stream


def test_pop_batch_headers_moves_request_id_to_custom_id() -> None:
    from inspect_ai.model._providers.util.batch import pop_batch_headers

    batch = [
        BatchRequest[str](
            request=_headers_request(name, **{"x-org": "a"}),
            result_stream=_send_stream(),
        )
        for name in ["one", "two"]
    ]
    assert pop_batch_headers(batch) == {"x-org": "a"}
    assert [request.custom_id for request in batch] == ["rid-one", "rid-two"]
    assert all("extra_headers" not in request.request for request in batch)

    # a retried submission gets the same headers
    assert pop_batch_headers(batch) == {"x-org": "a"}
    assert [request.custom_id for request in batch] == ["rid-one", "rid-two"]


def test_pop_batch_headers_excludes_request_id_in_any_case() -> None:
    from inspect_ai.model._providers.util.batch import pop_batch_headers

    caller_only = BatchRequest[str](
        request={"prompt": "one", "extra_headers": {"X-IRID": "caller", "x-org": "a"}},
        result_stream=_send_stream(),
    )
    generated_id = caller_only.custom_id
    both = BatchRequest[str](
        request={
            "prompt": "two",
            "extra_headers": {
                HttpxHooks.REQUEST_ID_HEADER: "generated",
                "X-IRID": "caller",
                "x-org": "a",
            },
        },
        result_stream=_send_stream(),
    )
    assert caller_only.headers == both.headers == {"x-org": "a"}

    assert pop_batch_headers([caller_only, both]) == {"x-org": "a"}
    assert caller_only.custom_id == generated_id
    assert both.custom_id == "generated"


def test_pop_batch_headers_rejects_mixed_headers() -> None:
    from inspect_ai.model._providers.util.batch import pop_batch_headers

    batch = [
        BatchRequest[str](
            request=_headers_request("one", **{"x-org": "a"}),
            result_stream=_send_stream(),
        ),
        BatchRequest[str](
            request=_headers_request("two", **{"x-org": "b"}),
            result_stream=_send_stream(),
        ),
    ]
    with pytest.raises(ValueError, match="same headers"):
        pop_batch_headers(batch)


async def test_openai_file_batcher_sends_each_header_set_separately() -> None:
    """The file batcher sends one batch per header set, without the request id."""
    from unittest.mock import AsyncMock, MagicMock

    from openai.types.chat import ChatCompletion

    from inspect_ai.model._providers._openai_batch import OpenAIBatcher

    class CompletingOpenAIBatcher(OpenAIBatcher[ChatCompletion]):
        """Completes each batch at once, answering each request with its id."""

        async def _check_batch(self, batch):
            return BatchCheckResult(
                completed_count=len(batch.requests),
                failed_count=0,
                created_at=int(time.time()),
                completion_info={"result_uris": []},
            )

        async def _handle_batch_result(self, batch, completion_info):
            return {custom_id: custom_id for custom_id in batch.requests}

    uploaded: list[tuple[list[str], dict[str, str]]] = []

    async def files_create(file, purpose, extra_headers):
        custom_ids = [
            json.loads(line)["custom_id"] for line in file.read().splitlines()
        ]
        uploaded.append((sorted(custom_ids), extra_headers))
        return MagicMock(id=f"file-{len(uploaded)}")

    client = MagicMock()
    client.files.create = AsyncMock(side_effect=files_create)
    client.batches.create = AsyncMock(
        side_effect=[MagicMock(id="batch-1"), MagicMock(id="batch-2")]
    )
    batcher = CompletingOpenAIBatcher(
        client,
        BatchConfig(size=10, send_delay=0.02, tick=0.001),
        model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
        ChatCompletion,
    )

    async def test_logic() -> None:
        results = await tg_collect(
            [
                lambda: batcher.generate_for_request(
                    _headers_request("a1", **{"x-org": "a"})
                ),
                lambda: batcher.generate_for_request(
                    _headers_request("b1", **{"x-org": "b"})
                ),
                lambda: batcher.generate_for_request(
                    _headers_request("a2", **{"x-org": "a"})
                ),
            ]
        )
        assert [str(result) for result in results] == ["rid-a1", "rid-b1", "rid-a2"]

    await _run_in_background_group(test_logic)

    assert sorted(uploaded, key=str) == [
        (["rid-a1", "rid-a2"], {"x-org": "a"}),
        (["rid-b1"], {"x-org": "b"}),
    ]
    create_headers = [
        call.kwargs["extra_headers"] for call in client.batches.create.call_args_list
    ]
    assert sorted(create_headers, key=str) == [{"x-org": "a"}, {"x-org": "b"}]
