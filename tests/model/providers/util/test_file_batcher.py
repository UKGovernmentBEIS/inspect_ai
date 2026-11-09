from __future__ import annotations

import anyio
import pytest
from anyio.abc import ObjectReceiveStream
from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel, JsonValue

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._openai import openai_should_retry
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.model._providers.util.batch import Batch, BatchCheckResult, BatchRequest
from inspect_ai.model._providers.util.file_batcher import FileBatcher
from inspect_ai.model._retry import model_retry_config


def _retry_config():
    return model_retry_config(
        "test", 1, None, lambda _: True, lambda _: None, lambda _, __: None
    )


class _Result(BaseModel):
    value: str


class _FileBatcher(FileBatcher[_Result, dict[str, list[str]]]):
    async def _check_batch(
        self, batch: Batch[_Result]
    ) -> BatchCheckResult[dict[str, list[str]]]:
        raise NotImplementedError

    async def _download_result_file(self, file_uri: str) -> bytes:
        return b'{"custom_id":"ok","response":{"value":"done"}}\n{"custom_id":"bad"}\n'

    def _parse_jsonl_line(self, line_data):
        if line_data["custom_id"] == "bad":
            raise ValueError("malformed result")
        return line_data["custom_id"], _Result.model_validate(line_data["response"])

    def _jsonl_line_for_request(self, request, custom_id):
        return {}

    async def _upload_batch_file(self, temp_file, extra_headers):
        return "file"

    async def _submit_batch_for_file(self, file_id, extra_headers):
        return "batch"

    def _uris_from_completion_info(self, completion_info):
        return completion_info["result_uris"]


@pytest.mark.anyio
async def test_file_batcher_keeps_other_rows_when_one_row_is_malformed():
    batcher = _FileBatcher(BatchConfig(), _retry_config(), 10, 1)

    results = await batcher._parse_result_file("results")

    assert results["ok"] == _Result(value="done")
    assert isinstance(results["bad"], ValueError)


@pytest.mark.anyio
async def test_file_batcher_uses_key_when_malformed_row_has_no_custom_id():
    class _KeyFileBatcher(_FileBatcher):
        async def _download_result_file(self, file_uri: str) -> bytes:
            return b'{"key":"bad","response":{}}\n'

    batcher = _KeyFileBatcher(BatchConfig(), _retry_config(), 10, 1)

    results = await batcher._parse_result_file("results")

    assert isinstance(results["bad"], KeyError)


@pytest.mark.anyio
async def test_unidentified_row_completes_missing_request() -> None:
    class _UnidentifiedBatcher(_FileBatcher):
        async def _download_result_file(self, file_uri: str) -> bytes:
            return b'{"custom_id":"ok","response":{"value":"done"}}\n{"noid":1}\n'

    batcher = _UnidentifiedBatcher(BatchConfig(), _retry_config(), 10, 1)
    requests: dict[str, BatchRequest[_Result]] = {}
    receivers: dict[str, ObjectReceiveStream[_Result | Exception]] = {}
    for request_id in ("ok", "missing"):
        send, receive = anyio.create_memory_object_stream[_Result | Exception](1)
        requests[request_id] = BatchRequest(
            request={}, result_stream=send, custom_id=request_id
        )
        receivers[request_id] = receive
    batch = Batch(id="batch", requests=requests)
    batcher._inflight_batches[batch.id] = batch

    await batcher._wrapped_handle_batch_result(batch, {"result_uris": ["results"]})

    with anyio.fail_after(1):
        assert await receivers["ok"].receive() == _Result(value="done")
        assert isinstance(await receivers["missing"].receive(), RuntimeError)
    assert batch.id not in batcher._inflight_batches


@pytest.mark.parametrize(
    "row,status",
    [
        ({"custom_id": "req", "error": {"code": "429", "message": "rate limit"}}, 429),
        (
            {
                "custom_id": "req",
                "error": None,
                "response": {
                    "status_code": 503,
                    "body": {"error": {"message": "unavailable"}},
                },
            },
            503,
        ),
    ],
)
def test_openai_batch_status_errors_are_retryable(
    row: dict[str, JsonValue], status: int
) -> None:
    batcher = OpenAIBatcher(
        AsyncOpenAI(api_key="test"), BatchConfig(), _retry_config(), _Result
    )
    request_id, result = batcher._parse_jsonl_line(row)
    assert request_id == "req"
    assert isinstance(result, APIStatusError)
    assert result.status_code == status
    assert result.response.request.method == "POST"
    assert openai_should_retry(result)


def test_openai_batch_non_numeric_error_code() -> None:
    batcher = OpenAIBatcher(
        AsyncOpenAI(api_key="test"), BatchConfig(), _retry_config(), _Result
    )
    request_id, result = batcher._parse_jsonl_line(
        {"custom_id": "req", "error": {"code": "batch_expired", "message": "expired"}}
    )
    assert request_id == "req"
    assert isinstance(result, RuntimeError)
    assert "batch_expired" in str(result)
    assert "expired" in str(result)
