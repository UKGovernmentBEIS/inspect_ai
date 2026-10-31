from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
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

    client = MagicMock()
    client._make_status_error_from_response.side_effect = lambda response: response
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
    assert getattr(error, "status_code", None) == 503
