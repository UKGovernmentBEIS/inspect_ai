from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers.util.batch import (
    Batch,
    Batcher,
    BatchRequest,
    PendingBatch,
    _assess_intake_queue,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class FakeBatcher(Batcher[str, CompletedBatchInfo]):
    def __init__(
        self,
        mocker: MockerFixture,
        *,
        batch_check_counts: dict[str, int] | None = None,
        inflight_batches: dict[str, Batch[str]] | None = None,
        config: BatchConfig = BatchConfig(size=10, send_delay=1.0, tick=0.01),
    ):
        super().__init__(config, 1000, 100)
        if inflight_batches is not None:
            self._inflight_batches = inflight_batches
        self.mock_create_batch = mocker.AsyncMock(side_effect=self._stub_create_batch)
        self.mock_check_batch = mocker.AsyncMock(side_effect=self._stub_check_batch)
        self.mock_handle_batch_result = mocker.AsyncMock(
            side_effect=self._stub_handle_batch_result
        )
        self.mock_get_batch = mocker.AsyncMock()
        self._num_sent_batches = 0
        self._batch_check_counts = batch_check_counts or defaultdict(int)

    def _stub_create_batch(self, _: Batch[str]) -> str:
        batch_ids = [*self._batch_check_counts]
        num_sent_batches = self._num_sent_batches
        batch_id = (
            batch_ids[num_sent_batches]
            if num_sent_batches < len(batch_ids)
            else f"test-batch-{num_sent_batches}"
        )
        self._num_sent_batches += 1
        return batch_id

    async def _create_batch(self, batch: list[BatchRequest[str]]) -> str:
        return await self.mock_create_batch(batch)

    def _stub_check_batch(
        self, batch: Batch[str]
    ) -> tuple[int, int, int, (CompletedBatchInfo | None)]:
        self._batch_check_counts[batch.id] -= 1
        # Use a mock age of 42 seconds for testing
        age = 42
        if self._batch_check_counts[batch.id] > 0:
            return (665, 666, age, None)
        return (665, 666, age, {"result_uris": [f"result-uri-{batch.id}"]})

    async def _check_batch(
        self, batch: Batch[str]
    ) -> tuple[int, int, int, (CompletedBatchInfo | None)]:
        return await self.mock_check_batch(batch)

    async def _stub_handle_batch_result(
        self, batch: Batch[str], completion_info: CompletedBatchInfo
    ) -> dict[str, str | Exception]:
        result_uris = completion_info["result_uris"]

        request_uri = result_uris[0]
        if "failed" in batch.id or "failed" in request_uri:
            raise Exception("Request failed")

        results = {}
        for request in [*batch.requests.values()]:
            results[request.custom_id] = (
                Exception("Request failed")
                if "failed" in request.custom_id
                else request.custom_id
            )

        return results

    async def _handle_batch_result(
        self, batch: Batch[str], completion_info: CompletedBatchInfo
    ) -> dict[str, str | Exception]:
        return await self.mock_handle_batch_result(batch, completion_info)


@pytest.mark.parametrize(
    ("has_error", "expected_batch_id"),
    (
        (True, None),
        (False, "test-batch-0"),
    ),
)
async def test_batcher_wrapped_create_batch(
    mocker: MockerFixture, has_error: bool, expected_batch_id: str | None
):
    batcher = FakeBatcher(mocker)
    expected_error = Exception("Test error") if has_error else None
    if expected_error:
        batcher.mock_create_batch.side_effect = expected_error

    batch_requests = [
        BatchRequest[str](request={}, result_stream=mocker.AsyncMock())
        for _ in range(10)
    ]

    if has_error:
        # When there's an error, _wrapped_create_batch should raise the exception
        with pytest.raises(Exception, match="Test error"):
            await batcher._wrapped_create_batch(batch_requests)  # pyright: ignore[reportPrivateUsage]
    else:
        # When there's no error, _wrapped_create_batch should return the batch_id
        batch_id = await batcher._wrapped_create_batch(batch_requests)  # pyright: ignore[reportPrivateUsage]
        assert batch_id == expected_batch_id

    batcher.mock_create_batch.assert_awaited_once_with(batch_requests)
    for request in batch_requests:
        mock_send = cast(AsyncMock, request.result_stream.send)
        if expected_error:
            mock_send.assert_awaited_once_with(expected_error)
        else:
            mock_send.assert_not_awaited()


@pytest.mark.parametrize(
    (
        "check_call_result",
        "retry_count",
        "expected_completion_info",
        "expected_error",
        "expected_batch_removed",
    ),
    (
        pytest.param(
            (665, 666, 42, {"result_uris": ["result-uri-test-batch-0"]}),
            0,
            {"result_uris": ["result-uri-test-batch-0"]},
            None,
            False,
            id="success",
        ),
        pytest.param(
            Exception("Test error"),
            0,
            None,
            Exception("Test error"),
            False,
            id="error-retry",
        ),
        # Disabling this test until I do it without relying on testing internals
        # pytest.param(
        #     Exception("Test error"),
        #     2,
        #     None,
        #     Exception("Test error"),
        #     True,
        #     id="error-fail",
        # ),
    ),
)
async def test_batcher_wrapped_check_batch(
    mocker: MockerFixture,
    check_call_result: CompletedBatchInfo | None,
    retry_count: int,
    expected_completion_info: CompletedBatchInfo | None,
    expected_error: Exception | None,
    expected_batch_removed: bool,
):
    batch = Batch[str](
        id="test-batch-0",
        requests={
            f"request-{idx}": BatchRequest[str](
                custom_id=f"request-{idx}",
                request={},
                result_stream=mocker.AsyncMock(),
            )
            for idx in range(10)
        },
        consecutive_check_failure_count=retry_count,
    )
    batcher = FakeBatcher(mocker, inflight_batches={batch.id: batch})
    if isinstance(check_call_result, Exception):
        batcher.mock_check_batch.side_effect = check_call_result
    else:
        batcher.mock_check_batch.return_value = check_call_result

    result = await batcher._wrapped_check_batch(batch)  # pyright: ignore[reportPrivateUsage]
    completed, failed, age, completion_info = (
        (result[0], result[1], result[2], result[3]) if result else (0, 0, 0, None)
    )

    batcher.mock_check_batch.assert_awaited_once_with(batch)
    if expected_error:
        assert completion_info is None
    else:
        assert completion_info == expected_completion_info

    for request in batch.requests.values():
        mock_send = cast(AsyncMock, request.result_stream.send)
        if expected_batch_removed:
            mock_send.assert_awaited_once_with(check_call_result)
        else:
            mock_send.assert_not_awaited()

    if expected_batch_removed:
        assert batch.id not in batcher._inflight_batches  # pyright: ignore[reportPrivateUsage]
    else:
        assert batch.id in batcher._inflight_batches  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("has_error", "retry_count", "expected_send"),
    (
        pytest.param(False, 0, True, id="success"),
        pytest.param(False, 2, True, id="success-retried"),
        pytest.param(True, 0, False, id="error-retry"),
        pytest.param(True, 2, True, id="error-fail"),
    ),
)
async def test_batcher_wrapped_handle_batch_result(
    mocker: MockerFixture,
    has_error: bool,
    retry_count: int,
    expected_send: bool,
):
    requests = {
        f"request-{idx}": BatchRequest[str](
            request={}, result_stream=mocker.AsyncMock(), custom_id=f"request-{idx}"
        )
        for idx in range(10)
    }
    batch = Batch[str](
        id="test-batch-0",
        requests=requests,
        consecutive_check_failure_count=retry_count,
    )
    batcher = FakeBatcher(mocker, inflight_batches={batch.id: batch})
    completion_info = CompletedBatchInfo(result_uris=["result-uri-test-batch-0"])
    expected_error = Exception("Test error") if has_error else None
    if expected_error:
        batcher.mock_handle_batch_result.side_effect = expected_error

    await batcher._wrapped_handle_batch_result(batch, completion_info)  # pyright: ignore[reportPrivateUsage]

    batcher.mock_handle_batch_result.assert_awaited_once_with(batch, completion_info)
    for idx_request, request in enumerate(batch.requests.values()):
        mock_send = cast(AsyncMock, request.result_stream.send)
        if expected_send:
            mock_send.assert_awaited_once_with(expected_error or idx_request)
        else:
            mock_send.assert_not_awaited()

    assert batch.id in batcher._inflight_batches  # pyright: ignore[reportPrivateUsage]
    if expected_send:
        assert batch.requests == {}
    else:
        assert len(batch.requests) == 10


class TestAssessIntakeQueue:
    def create_batch_request(
        self, request_data: dict, custom_id: str | None = None
    ) -> BatchRequest[str]:
        return BatchRequest[str](
            request=request_data,
            result_stream=MagicMock(),
            custom_id=custom_id or f"req-{id(request_data)}",
        )

    @pytest.mark.parametrize(
        (
            "existing_count",
            "available_size",
            "intake_count",
            "min_count",
            "max_count",
            "timeout_offset",
            "expected_add_count",
            "expected_should_send",
            "description",
        ),
        [
            # Basic scenarios
            pytest.param(
                0, 1000, 0, 5, 10, 10, 0, False, "empty intake queue", id="empty-intake"
            ),
            pytest.param(
                10,
                1000,
                1,
                5,
                10,
                10,
                0,
                True,
                "batch already full by count",
                id="full-by-count",
            ),
            pytest.param(
                1,
                0,
                1,
                5,
                10,
                10,
                0,
                True,
                "batch already full by size",
                id="full-by-size",
            ),
            # Count limit scenarios
            pytest.param(
                1, 10000, 15, 5, 10, 10, 9, True, "hit count limit", id="count-limit"
            ),
            # Minimum requirement scenarios
            pytest.param(
                3,
                1000,
                3,
                5,
                10,
                10,
                3,
                True,
                "meet minimum requirement",
                id="meet-minimum",
            ),
            pytest.param(
                1,
                1000,
                1,
                5,
                10,
                10,
                1,
                False,
                "below minimum requirement",
                id="below-minimum",
            ),
            pytest.param(
                5,
                1000,
                0,
                5,
                10,
                10,
                0,
                True,
                "exact minimum count",
                id="exact-minimum",
            ),
            # Timeout scenarios
            pytest.param(
                1,
                1000,
                1,
                5,
                10,
                -1,
                1,
                True,
                "timeout triggers send",
                id="timeout-trigger",
            ),
            pytest.param(
                5,
                1000,
                0,
                10,
                5,
                -1,
                0,
                True,
                "timeout with no requests added",
                id="timeout-no-add",
            ),
            # Empty batch scenarios
            pytest.param(
                0,
                1000,
                0,
                1,
                10,
                -1,
                0,
                False,
                "no requests despite timeout should not send",
                id="no-requests-timeout",
            ),
            # Size limit scenarios - removed oversized request test as it should raise an error
        ],
    )
    def test_batch_assessment_scenarios(
        self,
        existing_count: int,
        available_size: int,
        intake_count: int,
        min_count: int,
        max_count: int,
        timeout_offset: int,
        expected_add_count: int,
        expected_should_send: bool,
        description: str,
    ):
        # Setup existing requests
        existing_requests = [
            self.create_batch_request({"data": f"existing-{i}"})
            for i in range(existing_count)
        ]

        # Setup pending batch
        timeout = time.time() + timeout_offset
        pending_batch = PendingBatch(
            timeout=timeout,
            available_size=available_size,
            requests=existing_requests,
        )

        # Setup intake queue
        intake_queue = [
            self.create_batch_request({"data": f"new-{i}"}) for i in range(intake_count)
        ]

        # Execute
        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=min_count,
            max_request_count=max_count,
        )

        # Assert
        add_count, new_available_size, should_send = result
        assert add_count == expected_add_count, (
            f"Expected add_count {expected_add_count}, got {add_count} for {description}"
        )
        assert should_send == expected_should_send, (
            f"Expected should_send {expected_should_send}, got {should_send} for {description}"
        )
        assert isinstance(new_available_size, int), (
            f"new_available_size should be int for {description}"
        )
        assert new_available_size >= 0, (
            f"new_available_size should be >= 0 for {description}"
        )

    def test_oversized_request_raises_error(self):
        """Test that an oversized request in an empty batch raises an error."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=50, requests=[]
        )

        # Create a request that's too large for the available size
        large_data = "x" * 100  # Much larger than available size
        intake_queue = [
            self.create_batch_request({"large_data": large_data}),
            self.create_batch_request({"small": "data"}),
        ]

        # Should raise an exception when the first request can't fit in an empty batch
        with pytest.raises(Exception, match="exceeds maximum"):
            _assess_intake_queue(
                intake_queue=intake_queue,
                batch=pending_batch,
                min_request_count=5,
                max_request_count=10,
            )

    def test_add_requests_until_size_limit(self):
        """Test adding requests until hitting size limit."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10,
            available_size=100,  # Small size limit
            requests=[],
        )

        # Create requests that will consume exactly the available size
        # Each small request uses about 13 bytes: {"small":1} = 13 chars
        intake_queue = [
            self.create_batch_request({"small": i})
            for i in range(20)  # More than can fit by size
        ]

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=5,
            max_request_count=50,
        )

        add_count, _, should_send = result
        assert add_count > 0
        assert add_count < 20  # Couldn't fit all requests
        assert should_send is True  # Batch is full by size

    def test_mixed_size_requests(self):
        """Test with requests of varying sizes."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=100, requests=[]
        )

        intake_queue = (
            [
                self.create_batch_request({"small": i})
                for i in range(5)  # Small requests
            ]
            + [
                self.create_batch_request({"large": "x" * 50})  # One large request
            ]
            + [
                self.create_batch_request({"more_small": i})
                for i in range(3)  # More small
            ]
        )

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=3,
            max_request_count=20,
        )

        add_count, _, should_send = result
        # Should add small requests until size limit hit
        assert add_count >= 3  # At least some requests added
        assert should_send is True  # Should meet minimum or hit size limit

    def test_return_format(self):
        """Test that return format matches specification."""
        pending_batch = PendingBatch(
            timeout=time.time() + 10, available_size=1000, requests=[]
        )

        intake_queue = [self.create_batch_request({"data": "test"})]

        result = _assess_intake_queue(
            intake_queue=intake_queue,
            batch=pending_batch,
            min_request_count=5,
            max_request_count=10,
        )

        # Should return tuple[int, int, bool]
        assert isinstance(result, tuple)
        assert len(result) == 3

        add_count, new_available_size, should_send = result
        assert isinstance(add_count, int)
        assert isinstance(new_available_size, int)
        assert isinstance(should_send, bool)
        assert add_count >= 0
        assert new_available_size >= 0
