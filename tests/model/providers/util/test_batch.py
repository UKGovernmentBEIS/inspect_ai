from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, TypedDict, cast
from unittest.mock import AsyncMock

import pytest

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.util.batch import (
    Batch,
    Batcher,
    BatchRequest,
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
        config: GenerateConfig = GenerateConfig(
            batch_size=10,
            batch_max_send_delay=1.0,
            batch_tick=0.01,
        ),
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

    def _stub_check_batch(self, batch: Batch[str]) -> CompletedBatchInfo | None:
        self._batch_check_counts[batch.id] -= 1
        if self._batch_check_counts[batch.id] > 0:
            return None
        return {"result_uris": [f"result-uri-{batch.id}"]}

    async def _check_batch(self, batch: Batch[str]) -> CompletedBatchInfo | None:
        return await self.mock_check_batch(batch)

    async def _stub_handle_batch_result(
        self, batch: Batch[str], completion_info: CompletedBatchInfo
    ) -> None:
        result_uris = completion_info["result_uris"]

        request_uri = result_uris[0]
        if "failed" in batch.id or "failed" in request_uri:
            raise Exception("Request failed")

        for request in [*batch.requests.values()]:
            await request.result_stream.send(
                Exception("Request failed")
                if "failed" in request.custom_id
                else request.custom_id
            )
            del batch.requests[request.custom_id]

    async def _handle_batch_result(
        self, batch: Batch[str], completion_info: CompletedBatchInfo
    ) -> None:
        return await self.mock_handle_batch_result(batch, completion_info)

    def _get_request_failed_error(self, _: BatchRequest[str]) -> Exception:
        return Exception("Test error")


@pytest.mark.parametrize(
    ("has_error", "expected_batch_id"),
    (
        (True, None),
        (False, "test-batch-0"),
    ),
)
async def test_batcher_safe_create_batch(
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

    batch_id = await batcher._safe_create_batch(batch_requests)  # pyright: ignore[reportPrivateUsage]
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
            None,
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
        pytest.param(
            Exception("Test error"),
            2,
            None,
            Exception("Test error"),
            True,
            id="error-fail",
        ),
    ),
)
async def test_batcher_safe_check_batch(
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
        retry_count=retry_count,
    )
    batcher = FakeBatcher(mocker, inflight_batches={batch.id: batch})
    if isinstance(check_call_result, Exception):
        batcher.mock_check_batch.side_effect = check_call_result
    else:
        batcher.mock_check_batch.return_value = check_call_result

    completion_info = await batcher._safe_check_batch(batch)  # pyright: ignore[reportPrivateUsage]

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
async def test_batcher_safe_handle_batch_result(
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
        retry_count=retry_count,
    )
    batcher = FakeBatcher(mocker, inflight_batches={batch.id: batch})
    completion_info = CompletedBatchInfo(result_uris=["result-uri-test-batch-0"])
    expected_error = Exception("Test error") if has_error else None
    if expected_error:
        batcher.mock_handle_batch_result.side_effect = expected_error

    await batcher._safe_handle_batch_result(batch, completion_info)  # pyright: ignore[reportPrivateUsage]

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
