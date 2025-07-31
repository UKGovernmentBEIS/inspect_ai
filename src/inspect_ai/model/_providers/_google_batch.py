import time
from typing import Any, TypedDict

import pydantic
from google.genai import Client
from google.genai.types import (
    CreateBatchJobConfig,
    GenerateContentResponse,
    HttpOptions,
    JobError,
    JobState,
    UploadFileConfig,
)
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import Batch, BatchRequest
from .util.file_batcher import FileBatcher
from .util.hooks import HttpxHooks


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class GoogleBatcher(FileBatcher[GenerateContentResponse, CompletedBatchInfo]):
    def __init__(
        self,
        client: Client,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
        model_name: str,
    ):
        super().__init__(
            config=config,
            retry_config=retry_config,
            max_batch_request_count=50000,  # Not actually specified in the doc afaik
            max_batch_size_mb=2000,  # 2GB file size limit
        )
        self._client = client
        self._model_name = model_name

    @override
    def _jsonl_line_for_request(
        self, request: BatchRequest[GenerateContentResponse], custom_id: str
    ) -> dict[str, pydantic.JsonValue]:
        return {
            "key": custom_id,
            "request": {
                **{
                    k: v
                    for k, v in request.request.items()
                    if k not in ("http_options", "thinking_config")
                }
            },
        }

    @override
    async def _upload_batch_file(
        self, temp_file: Any, extra_headers: dict[str, str]
    ) -> str:
        file_obj = await self._client.aio.files.upload(
            file=temp_file.name,
            config=UploadFileConfig(
                display_name=f"batch_requests_{int(time.time())}",
                mime_type="application/jsonl",
            ),
        )
        return file_obj.name or ""

    @override
    async def _submit_batch_for_file(
        self, file_id: str, extra_headers: dict[str, str]
    ) -> str:
        # Extract request ID for batch job display name if available
        request_id = extra_headers.get(HttpxHooks.REQUEST_ID_HEADER, "")
        display_name = (
            f"batch_job_{request_id}" if request_id else f"batch_job_{int(time.time())}"
        )

        config = CreateBatchJobConfig(
            display_name=display_name,
            http_options=HttpOptions(headers=extra_headers or None),
        )

        batch_job = await self._client.aio.batches.create(
            model=self._model_name,
            src=file_id,
            config=config,
        )
        return batch_job.name or ""

    @override
    async def _check_batch(
        self, batch: Batch[GenerateContentResponse]
    ) -> tuple[int, int, int, CompletedBatchInfo | None]:
        batch_job = await self._client.aio.batches.get(name=batch.id)

        # Calculate age
        age = (
            int((time.time() - batch_job.create_time.timestamp()))
            if batch_job.create_time
            else 0
        )

        # Handle different job states
        if (
            batch_job.state == JobState.JOB_STATE_PENDING
            or batch_job.state == JobState.JOB_STATE_RUNNING
        ):
            return (0, 0, age, None)
        elif batch_job.state == JobState.JOB_STATE_SUCCEEDED:
            # For successful jobs, we need to determine completed/failed counts
            # Google doesn't provide these directly, so we'll parse the result file
            result_uris = []
            if batch_job.dest and batch_job.dest.file_name:
                # Add the destination URI - the exact attribute may vary
                # This is a simplified implementation
                result_uris.append(batch_job.dest.file_name)

            return (
                len(batch.requests),  # Assume all completed if job succeeded
                0,  # Failed count will be determined during result parsing
                age,
                {"result_uris": result_uris} if result_uris else None,
            )
        elif batch_job.state in [
            JobState.JOB_STATE_FAILED,
            JobState.JOB_STATE_CANCELLED,
        ]:
            # Job failed or was cancelled - all requests failed
            return (0, len(batch.requests), age, None)
        else:
            # Unknown state - treat as pending
            return (0, 0, age, None)

    @override
    async def _download_result_file(self, file_uri: str) -> bytes:
        return await self._client.aio.files.download(file=file_uri)

    @override
    def _parse_jsonl_line(
        self, line_data: dict[str, pydantic.JsonValue]
    ) -> tuple[str, GenerateContentResponse | Exception]:
        key = line_data["key"]
        assert isinstance(key, str), "key must be a string"
        if "error" in line_data:
            error_data = JobError.model_validate(line_data["error"])
            return (
                key,
                RuntimeError(f"{error_data.message} (code: {error_data.code})"),
            )
        else:
            return key, GenerateContentResponse.model_validate(line_data["response"])

    @override
    def _uris_from_completion_info(
        self, completion_info: CompletedBatchInfo
    ) -> list[str]:
        return completion_info["result_uris"]
