from __future__ import annotations

import asyncio
import sys
import time
from typing import TypedDict

import anyio
import pytest
from tenacity import RetryError

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers.util.batch import (
    Batcher,
    BatchRequest,
)
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
            model_retry_config("test", 3, None, lambda e: True, lambda m, s: None),
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
        await asyncio.sleep(0.001)

        # Store batch info for later completion simulation
        self._created_batches[batch_id] = [req.custom_id for req in batch_requests]
        self._batch_creation_times[batch_id] = time.time()

        return batch_id

    async def _check_batch(
        self, batch
    ) -> tuple[int, int, int, FakeCompletionInfo | None]:
        """Simulate checking batch status."""
        batch_id = batch.id

        # Simulate check delay
        await asyncio.sleep(0.001)

        # Check if batch should fail
        if batch_id in self._fail_batch_ids:
            raise Exception(f"Simulated batch failure for {batch_id}")

        # Calculate age
        creation_time = self._batch_creation_times.get(batch_id, time.time())
        age = int(time.time() - creation_time)

        # Check if batch is "complete" based on elapsed time
        if time.time() - creation_time >= self._batch_completion_delay:
            # Batch is complete
            request_count = len(self._created_batches[batch_id])
            return (
                request_count,  # completed count
                0,  # failed count
                age,  # age in seconds
                FakeCompletionInfo(result_uris=[f"result-{batch_id}"]),
            )
        else:
            # Still processing
            return (0, 0, age, None)

    async def _handle_batch_result(
        self, batch, completion_info: FakeCompletionInfo
    ) -> dict[str, str | Exception]:
        """Simulate processing batch results."""
        # Check for simulated handle error
        if self._handle_batch_error:
            raise self._handle_batch_error

        # Simulate processing delay
        await asyncio.sleep(0.001)

        results: dict[str, str | Exception] = {}
        for request_id in self._created_batches[batch.id]:
            if request_id in self._fail_request_ids:
                results[request_id] = Exception(f"Simulated failure for {request_id}")
            else:
                results[request_id] = f"result-for-{request_id}"

        return results


@pytest.mark.asyncio
class TestBatcher:
    """Integration tests for Batcher that test end-to-end behavior."""

    async def _run_with_task_group(self, test_func):
        """Helper to run test logic within a TaskGroup context."""
        from inspect_ai._util.eval_task_group import init_eval_task_group

        async with anyio.create_task_group() as tg:
            init_eval_task_group(tg)
            try:
                await test_func()
            finally:
                init_eval_task_group(None)

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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(5)
            ]

            results = await asyncio.gather(*tasks)

            # All requests should succeed
            assert len(results) == 5
            for result in results:
                assert result.startswith("result-for-")

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

            # Start a request
            task = asyncio.create_task(batcher.generate_for_request({"prompt": "test"}))

            # Let it fail a few times
            await asyncio.sleep(0.01)

            # Remove the failure condition
            batcher._fail_batch_ids.clear()

            # Request should eventually succeed
            result = await task
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(3)
            ]

            # All should complete successfully
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(3)
            ]

            # Should complete due to timeout, not batch size
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(8)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"stress-test-{i}"})
                for i in range(num_requests)
            ]

            # All should complete successfully
            start_time = time.time()
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-success-{i}"})
                for i in range(3)
            ]

            results = await asyncio.gather(*tasks)

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

            # Start the batch worker
            worker_task = asyncio.create_task(batcher_mixed._batch_worker())

            # Collect results
            results = []
            for receive_stream in receive_streams:
                try:
                    result = await receive_stream.receive()
                    if isinstance(result, Exception):
                        results.append(f"ERROR: {result}")
                    else:
                        results.append(result)
                except Exception as e:
                    results.append(f"EXCEPTION: {e}")

            await worker_task

            # Verify that the right request failed and others succeeded
            assert len(results) == 3
            assert results[0].startswith("result-for-success-1")  # Success
            assert "ERROR:" in results[1] and "fail-me" in results[1]  # Failed
            assert results[2].startswith("result-for-success-2")  # Success

        await self._run_with_task_group(test_logic)

    async def test_maximum_batch_size_limits(self):
        """Test that maximum batch size limits force multiple batches."""

        async def test_logic():
            # Use BatchConfig.max_size to limit batches to 2 requests each
            batcher = FakeBatcher(
                config=BatchConfig(size=1, max_size=2, send_delay=0.01, tick=0.001)
            )

            # Send more requests than the maximum batch size
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(5)
            ]

            # All should complete successfully
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(2)
            ]

            # Should complete due to timeout, not minimum size
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"test-{i}"}) for i in range(4)
            ]

            # Should complete immediately (since 4 >= 3 min_size)
            results = await asyncio.gather(*tasks)
            assert len(results) == 4

            # Should have created exactly one batch with all 4 requests
            assert len(batcher._created_batches) == 1
            batch_id = next(iter(batcher._created_batches.keys()))
            assert len(batcher._created_batches[batch_id]) == 4

            # Now test max_size enforcement - send 6 requests to exceed max_size=5
            batcher2 = FakeBatcher(
                config=BatchConfig(size=2, max_size=5, send_delay=0.02, tick=0.001)
            )

            tasks2 = [
                batcher2.generate_for_request({"prompt": f"test2-{i}"})
                for i in range(6)
            ]

            results2 = await asyncio.gather(*tasks2)
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
            task = asyncio.create_task(batcher.generate_for_request({"prompt": "test"}))

            # Wait for the batch to fail after the configured number of failures
            with pytest.raises(Exception, match="Simulated batch failure for batch-0"):
                await task

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
            batcher = FakeBatcher(
                config=BatchConfig(
                    size=1,
                    send_delay=0.01,
                    tick=0.001,
                    max_consecutive_check_failures=5,
                ),
                fail_batch_ids={"batch-0"},
            )

            # Start a request
            task = asyncio.create_task(batcher.generate_for_request({"prompt": "test"}))

            # Let it fail a few times
            await asyncio.sleep(0.01)

            # Get the batch and verify it has some failures
            batch = next(iter(batcher._inflight_batches.values()))
            assert batch.consecutive_check_failure_count > 0

            # Remove the failure condition to allow success
            batcher._fail_batch_ids.clear()

            # The request should eventually succeed
            result = await task
            assert result.startswith("result-for-")

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
            tasks = [
                batcher.generate_for_request({"prompt": f"constrained-{i}"})
                for i in range(8)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"invalid-config-{i}"})
                for i in range(4)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request(
                    {"data": f"medium-sized-request-{i:03d}-{'x' * 20}"}
                )
                for i in range(8)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"fast-tick-{i}"})
                for i in range(3)
            ]

            start_time = time.time()
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"slow-tick-{i}"})
                for i in range(3)
            ]

            start_time = time.time()
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"limited-{i}"})
                for i in range(10)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"zero-config-{i}"})
                for i in range(3)
            ]

            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"extreme-{i}"})
                for i in range(5)
            ]

            # Should complete quickly despite long send_delay due to reaching minimum size
            start_time = time.time()
            results = await asyncio.gather(*tasks)
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
            tasks = [
                batcher.generate_for_request({"prompt": f"precision-{i}"})
                for i in range(3)
            ]

            start_time = time.time()
            results = await asyncio.gather(*tasks)
            elapsed = time.time() - start_time

            assert len(results) == 3

            # Should timeout properly despite close timing values
            assert 0.005 < elapsed < 0.05  # Should be close to send_delay timing

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
            task = asyncio.create_task(
                batcher.generate_for_request({"prompt": "timing-failure"})
            )

            # Should fail after 2 failures * ~20ms tick = ~40ms + some overhead
            start_time = time.time()
            with pytest.raises(Exception):
                await task
            elapsed = time.time() - start_time

            # Should fail relatively quickly based on tick timing
            assert elapsed < 0.5  # Should fail within reasonable time

        await self._run_with_task_group(test_logic)
