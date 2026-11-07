from __future__ import annotations

import anyio
import pytest
from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._openai import openai_classify_retry
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.model._providers.util.batch import Batch, BatchRequest
from inspect_ai.model._providers.util.file_batcher import FileBatcher
from inspect_ai.model._retry import model_retry_config


def _retry_config():
    return model_retry_config(
        "test", 1, None, lambda _: True, lambda _: None, lambda _, __: None
    )


class _Result(BaseModel):
    value: str


class _FileBatcher(FileBatcher[_Result, dict[str, list[str]]]):
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


def test_openai_batcher_recognizes_error_embedded_in_response_body():
    from openai.types.chat import ChatCompletion

    client = AsyncOpenAI(api_key="test")
    batcher = OpenAIBatcher(client, BatchConfig(), _retry_config(), ChatCompletion)

    request_id, error = batcher._parse_jsonl_line(
        {
            "custom_id": "req-1",
            "response": {
                "status_code": 503,
                "body": {"error": {"code": "overloaded", "message": "overloaded"}},
            },
        }
    )

    assert request_id == "req-1"
    assert isinstance(error, APIStatusError)
    assert error.status_code == 503
    assert error.request.method == "POST"
    assert openai_classify_retry(error) is not None


def test_openai_batcher_recognizes_error_in_error_field() -> None:
    from openai.types.chat import ChatCompletion

    client = AsyncOpenAI(api_key="test")
    batcher = OpenAIBatcher(client, BatchConfig(), _retry_config(), ChatCompletion)

    request_id, error = batcher._parse_jsonl_line(
        {
            "custom_id": "req-2",
            "error": {"code": "batch_expired", "message": "expired"},
        }
    )

    assert request_id == "req-2"
    assert isinstance(error, RuntimeError)
    assert "batch_expired" in str(error)
    assert "expired" in str(error)


@pytest.mark.anyio
async def test_unidentified_rows_do_not_discard_results_or_leave_requests_pending():
    class _BrokenRowsBatcher(_FileBatcher):
        async def _download_result_file(self, file_uri: str) -> bytes:
            return (
                '{"custom_id":"ok","response":{"value":"a\u2029b"}}\n'
                '{"custom_id":"missing"\n'
                '{"response":{}}\n'
            ).encode()

    batcher = _BrokenRowsBatcher(BatchConfig(), _retry_config(), 10, 1)
    streams = {
        key: anyio.create_memory_object_stream[_Result | Exception](1)
        for key in ("ok", "missing")
    }
    batch = Batch(
        id="batch",
        requests={
            key: BatchRequest(request={}, result_stream=streams[key][0], custom_id=key)
            for key in ("ok", "missing")
        },
    )

    results = await batcher._handle_batch_result(batch, {"result_uris": ["file"]})

    assert results["ok"] == _Result(value="a\u2029b")
    assert isinstance(results["missing"], RuntimeError)
    batcher._inflight_batches[batch.id] = batch
    await batcher._resolve_inflight_batch(batch, results)
    assert await streams["ok"][1].receive() == _Result(value="a\u2029b")
    assert isinstance(await streams["missing"][1].receive(), RuntimeError)
    for send, receive in streams.values():
        await send.aclose()
        await receive.aclose()
