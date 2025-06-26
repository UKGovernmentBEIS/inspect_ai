import functools
import json
import tempfile
from typing import Any, Literal, TypedDict

import httpx
from openai import (
    AsyncOpenAI,
    InternalServerError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion

from inspect_ai._util._async import tg_collect
from inspect_ai.model._generate_config import BatchConfig

from .util.batch import (
    Batch,
    Batcher,
    BatchRequest,
)
from .util.hooks import HttpxHooks


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class OpenAIBatcher(Batcher[ChatCompletion, CompletedBatchInfo]):
    def __init__(self, client: AsyncOpenAI, config: BatchConfig):
        super().__init__(
            config=config,
            max_batch_request_count=50000,
            max_batch_size_mb=200,
        )
        self.client = client

    async def _create_batch(self, batch: list[BatchRequest[ChatCompletion]]) -> str:
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

            batch_file = await self.client.files.create(
                file=temp_file.file,
                purpose="batch",
                extra_headers=extra_headers or None,
            )
        batch_info = await self.client.batches.create(
            input_file_id=batch_file.id,
            completion_window="24h",
            endpoint=endpoint,
            extra_headers=extra_headers or None,
        )
        return batch_info.id

    async def _check_batch(
        self, batch: Batch[ChatCompletion]
    ) -> CompletedBatchInfo | None:
        batch_info = await self.client.batches.retrieve(batch.id)

        if batch_info.status not in {"completed", "failed", "cancelled", "expired"}:
            return None

        # The doc suggests that `output_file_id` will only be populated if the batch
        # as a whole reached the `completed` state. This means that if all but
        # one request in the batch completed, but ultimately the batch expired,
        # there will be no partial results returned.

        batch_file_ids = [
            file_id
            for file_id in [batch_info.output_file_id, batch_info.error_file_id]
            if file_id is not None
        ]

        return {"result_uris": batch_file_ids} if batch_file_ids else None

    async def _handle_batch_result(
        self,
        batch: Batch[ChatCompletion],
        completion_info: CompletedBatchInfo,
    ) -> None:
        result_uris = completion_info["result_uris"]

        await tg_collect(
            [
                functools.partial(self._handle_batch_result_file, batch, file_id)
                for file_id in result_uris
            ]
        )

    async def _handle_batch_result_file(
        self,
        batch: Batch[ChatCompletion],
        file_id: str,
    ) -> None:
        # TODO: Add error handling so that if one uri fails, the others can
        # still succeed
        batch_file = await self.client.files.content(file_id)
        for line in (await batch_file.aread()).decode().splitlines():
            result: dict[str, Any] = json.loads(line)
            request_id = result.pop("custom_id")
            if not request_id:
                # TODO: Does this happen? Seems like a coding error if it does.
                # either ours or openai's
                #
                continue

            batch_request = batch.requests.pop(request_id)
            await batch_request.result_stream.send(
                ChatCompletion.model_validate(result["response"]["body"])
                if (error := result.get("error")) is None
                else self.client._make_status_error_from_response(  # pyright: ignore[reportPrivateUsage]
                    httpx.Response(status_code=error["code"], text=error["message"])
                )
            )

    def _get_request_failed_error(
        self, request: BatchRequest[ChatCompletion]
    ) -> Exception:
        return InternalServerError(
            message="Request failed",
            response=httpx.Response(status_code=500, text="Request failed"),
            body=None,
        )
