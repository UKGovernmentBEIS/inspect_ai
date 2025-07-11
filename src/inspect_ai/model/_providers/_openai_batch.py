import functools
import json
import tempfile
import time
from itertools import chain
from typing import Any, Literal, TypedDict

import httpx
from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion
from tenacity import retry

from inspect_ai._util._async import tg_collect
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import (
    Batch,
    Batcher,
    BatchRequest,
)
from .util.hooks import HttpxHooks


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class OpenAIBatcher(Batcher[ChatCompletion, CompletedBatchInfo]):
    def __init__(
        self,
        client: AsyncOpenAI,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
    ):
        super().__init__(
            config=config,
            max_batch_request_count=50000,
            max_batch_size_mb=200,
        )
        self._client = client
        self._retry_config = retry_config

    async def _create_batch(self, batch: list[BatchRequest[ChatCompletion]]) -> str:
        @retry(**self._retry_config)
        async def _create() -> str:
            # TODO: support other endpoints
            endpoint: Literal["/v1/chat/completions"] = "/v1/chat/completions"
            extra_headers: dict[str, str] = {}
            with tempfile.NamedTemporaryFile(
                delete=True, suffix=".jsonl", mode="w+b"
            ) as temp_file:
                for request in batch:
                    extra_headers = request.request.pop("extra_headers", {})
                    request_id = extra_headers.pop(HttpxHooks.REQUEST_ID_HEADER, None)
                    if request_id is not None:
                        request.custom_id = request_id
                    temp_file.write(
                        json.dumps(
                            {
                                "custom_id": request.custom_id,
                                "method": "POST",
                                "url": endpoint,
                                "body": {
                                    k: v
                                    for k, v in request.request.items()
                                    if v is not NOT_GIVEN
                                },
                            },
                        ).encode()
                        + b"\n"
                    )
                temp_file.flush()
                temp_file.seek(0)

                batch_file = await self._client.files.create(
                    file=temp_file.file,
                    purpose="batch",
                    extra_headers=extra_headers or None,
                )

            batch_info = await self._client.batches.create(
                input_file_id=batch_file.id,
                completion_window="24h",
                endpoint=endpoint,
                extra_headers=extra_headers or None,
            )
            return batch_info.id

        return await _create()

    async def _check_batch(
        self, batch: Batch[ChatCompletion]
    ) -> tuple[int, int, int, (CompletedBatchInfo | None)]:
        batch_info = await self._client.batches.retrieve(batch.id)

        # TODO: Is it bogus to return 0, 0 when request_counts isn't available
        completed, failed = (
            (batch_info.request_counts.completed, batch_info.request_counts.failed)
            if batch_info.request_counts
            else (0, 0)
        )

        age = int(time.time() - batch_info.created_at) if batch_info.created_at else 0

        if batch_info.status not in {"completed", "failed", "cancelled", "expired"}:
            return (completed, failed, age, None)

        # The doc suggests that `output_file_id` will only be populated if the batch
        # as a whole reached the `completed` state. This means that if all but
        # one request in the batch completed, but ultimately the batch expired,
        # there will be no partial results returned.

        batch_file_ids = [
            file_id
            for file_id in [batch_info.output_file_id, batch_info.error_file_id]
            if file_id is not None
        ]

        return (
            completed,
            failed,
            age,
            {"result_uris": batch_file_ids} if batch_file_ids else None,
        )

    async def _handle_batch_result(
        self,
        batch: Batch[ChatCompletion],
        completion_info: CompletedBatchInfo,
    ) -> dict[str, ChatCompletion | Exception]:
        result_uris = completion_info["result_uris"]

        @retry(**self._retry_config)
        async def _results() -> list[dict[str, ChatCompletion | Exception]]:
            return await tg_collect(
                [
                    functools.partial(self._handle_batch_result_file, file_id)
                    for file_id in result_uris
                ]
            )

        return dict(
            chain.from_iterable(file_result.items() for file_result in await _results())
        )

    async def _handle_batch_result_file(
        self, file_id: str
    ) -> dict[str, ChatCompletion | Exception]:
        # TODO: Add error handling so that if one uri fails, the others can
        # still succeed
        results: dict[str, ChatCompletion | Exception] = {}
        batch_file = await self._client.files.content(file_id)
        for line in (await batch_file.aread()).decode().splitlines():
            result: dict[str, Any] = json.loads(line)
            request_id = result.pop("custom_id")
            if not request_id:
                raise ValueError(
                    f"Unable to find custom_id in batched request result. {result}"
                )

            # Store the result in the dictionary instead of sending to result_stream
            results[request_id] = (
                ChatCompletion.model_validate(result["response"]["body"])
                if (error := result.get("error")) is None
                else self._client._make_status_error_from_response(  # pyright: ignore[reportPrivateUsage]
                    httpx.Response(status_code=error["code"], text=error["message"])
                )
            )
        return results
