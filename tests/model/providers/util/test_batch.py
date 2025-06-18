from __future__ import annotations

import contextlib
from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict

import pytest

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.util.batch import (
    Batch,
    Batcher,
    BatchRequest,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture, MockType


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class FakeBatcher(Batcher[int, CompletedBatchInfo]):
    def __init__(
        self,
        mocker: MockerFixture,
        batch_check_counts: dict[str, int] | None = None,
        config: GenerateConfig = GenerateConfig(
            batch_size=10,
            batch_max_send_delay=1.0,
            batch_tick=0.01,
        ),
    ):
        self.mock_create_batch = mocker.AsyncMock(side_effect=self._stub_create_batch)
        self.mock_check_batch = mocker.AsyncMock(side_effect=self._stub_check_batch)
        self.mock_handle_batch_result = mocker.AsyncMock(
            side_effect=self._stub_handle_batch_result
        )
        self.mock_get_batch = mocker.AsyncMock()
        self._num_sent_batches = 0
        self._batch_check_counts = batch_check_counts or defaultdict(int)
        super().__init__(config)

    def _stub_create_batch(self, batch: Batch[int]) -> str:
        batch_ids = [*self._batch_check_counts]
        num_sent_batches = self._num_sent_batches
        batch_id = (
            batch_ids[num_sent_batches]
            if num_sent_batches < len(batch_ids)
            else f"test-batch-{num_sent_batches}"
        )
        self._num_sent_batches += 1
        return batch_id

    async def _create_batch(self, batch: list[BatchRequest[int]]) -> str:
        return await self.mock_create_batch(batch)

    def _stub_check_batch(self, batch: Batch[int]) -> CompletedBatchInfo | None:
        self._batch_check_counts[batch.id] -= 1
        if self._batch_check_counts[batch.id] > 0:
            return None
        return {"result_uris": [f"result-uri-{batch.id}"]}

    async def _check_batch(self, batch: Batch[int]) -> CompletedBatchInfo | None:
        return await self.mock_check_batch(batch)

    async def _stub_handle_batch_result(
        self, batch: Batch[int], completion_info: CompletedBatchInfo
    ) -> None:
        result_uris = completion_info["result_uris"]

        request_uri = result_uris[0]
        if "failed" in batch.id or "failed" in request_uri:
            raise Exception("Request failed")

        for idx_request, request in enumerate(batch.requests.values()):
            await request.result_stream.send(
                Exception("Request failed")
                if "failed" in request.custom_id
                else idx_request
            )

    async def _handle_batch_result(
        self, batch: Batch[int], completion_info: CompletedBatchInfo
    ) -> None:
        return await self.mock_handle_batch_result(batch, completion_info)

    def _get_request_failed_error(self, request: BatchRequest[int]) -> Exception:
        return Exception("Test error")


@pytest.mark.parametrize(
    "has_error",
    (True, False),
)
async def test_batcher_safe_create_batch(mocker: MockerFixture, has_error: bool):
    batcher = FakeBatcher(mocker)
    expected_error = Exception("Test error") if has_error else None
    if expected_error:
        batcher.mock_create_batch.side_effect = expected_error

    batch_requests = [
        BatchRequest[int](request={}, result_stream=mocker.AsyncMock())
        for _ in range(10)
    ]

    with (
        pytest.raises(type(expected_error))
        if expected_error
        else contextlib.nullcontext()
    ):
        batch_id = await batcher._safe_create_batch(batch_requests)  # pyright: ignore[reportPrivateUsage]
        assert batch_id == "test-batch-0"

    batcher.mock_create_batch.assert_awaited_once_with(batch_requests)
    for request in batch_requests:
        mock_send: MockType = request.result_stream.send
        if expected_error:
            mock_send.assert_awaited_once_with(expected_error)
        else:
            mock_send.assert_not_awaited()


@pytest.mark.parametrize(
    ("check_call_result", "expected_completion_info", "expected_error"),
    (
        (None, {"result_uris": ["result-uri-test-batch-0"]}, None),
        (
            Exception("Test error"),
            None,
            Exception("Test error"),
        ),
    ),
)
async def test_batcher_safe_check_batch(
    mocker: MockerFixture,
    check_call_result: CompletedBatchInfo | None,
    expected_completion_info: CompletedBatchInfo | None,
    expected_error: Exception | None,
):
    batcher = FakeBatcher(mocker)
    if isinstance(check_call_result, Exception):
        batcher.mock_check_batch.side_effect = check_call_result
    else:
        batcher.mock_check_batch.return_value = check_call_result

    batch = Batch[int](
        id="test-batch-0",
        requests={
            f"request-{idx}": BatchRequest[int](
                request={}, result_stream=mocker.AsyncMock()
            )
            for idx in range(10)
        },
    )
    completion_info = await batcher._safe_check_batch(batch)  # pyright: ignore[reportPrivateUsage]

    batcher.mock_check_batch.assert_awaited_once_with(batch)
    if expected_error:
        assert completion_info is None
    else:
        assert completion_info == expected_completion_info

    for request in batch.requests.values():
        mock_send: MockType = request.result_stream.send
        mock_send.assert_not_awaited()


@pytest.mark.parametrize(
    ("has_error"),
    (True, False),
)
async def test_batcher_safe_handle_batch_result(
    mocker: MockerFixture,
    has_error: bool,
):
    batcher = FakeBatcher(mocker)
    expected_error = Exception("Test error") if has_error else None
    if expected_error:
        batcher.mock_handle_batch_result.side_effect = expected_error

    batch = Batch[int](
        id="test-batch-0",
        requests={
            f"request-{idx}": BatchRequest[int](
                request={}, result_stream=mocker.AsyncMock()
            )
            for idx in range(10)
        },
    )

    with (
        pytest.raises(type(expected_error))
        if expected_error
        else contextlib.nullcontext()
    ):
        await batcher._safe_handle_batch_result(  # pyright: ignore[reportPrivateUsage]
            batch, {"result_uris": ["result-uri-test-batch-0"]}
        )

    batcher.mock_handle_batch_result.assert_awaited_once_with(
        batch, {"result_uris": ["result-uri-test-batch-0"]}
    )
    for idx_request, request in enumerate(batch.requests.values()):
        mock_send: MockType = request.result_stream.send
        if expected_error:
            mock_send.assert_awaited_once_with(expected_error)
        else:
            mock_send.assert_awaited_once_with(idx_request)
