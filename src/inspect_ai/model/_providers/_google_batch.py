import time
from datetime import datetime, timezone
from typing import Any, TypeAlias

import pydantic
from google.genai import Client
from google.genai.types import (
    Content,
    CreateBatchJobConfig,
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    JobError,
    JobState,
    UploadFileConfig,
)
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import Batch, BatchCheckResult, BatchRequest
from .util.file_batcher import FileBatcher
from .util.hooks import HttpxHooks

# Just the result URI
CompletedBatchInfo: TypeAlias = str

# Fields that belong at the top level of GenerateContentRequest (not under generationConfig).
# Everything else from GenerateContentConfig is nested under generationConfig in the
# REST schema.
_REQUEST_TOP_LEVEL_FIELDS = {
    "safety_settings",
    "tools",
    "tool_config",
    "system_instruction",
    "cached_content",
}

# SDK-only fields that don't appear in the REST schema at all.
_SDK_ONLY_FIELDS = {
    "http_options",
    "automatic_function_calling",
    "should_return_http_response",
    "labels",
}


def batch_request_dict(
    config: GenerateContentConfig, contents: list[Content]
) -> dict[str, Any]:
    """Build a dict matching the REST GenerateContentRequest schema.

    The SDK's GenerateContentConfig flattens everything, but the batch JSONL
    format expects the REST shape where generation params (temperature, thinking_config,
    etc.) are nested under "generation_config".
    """
    # Route each field to its correct location in the REST schema. Unlisted fields
    # (thinking_config, temperature, etc.) go into generation_config
    # see _REQUEST_TOP_LEVEL_FIELDS.
    params = config.model_dump(exclude_none=True)
    top_level = {k: v for k, v in params.items() if k in _REQUEST_TOP_LEVEL_FIELDS}
    generation_config = {
        k: v
        for k, v in params.items()
        if k not in _REQUEST_TOP_LEVEL_FIELDS and k not in _SDK_ONLY_FIELDS
    }
    return {
        "contents": [c.model_dump(exclude_none=True) for c in contents],
        **top_level,
        **({"generation_config": generation_config} if generation_config else {}),
    }


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

    # FileBatcher overrides

    @override
    def _jsonl_line_for_request(
        self, request: BatchRequest[GenerateContentResponse], custom_id: str
    ) -> dict[str, pydantic.JsonValue]:
        return {
            "key": custom_id,
            "request": dict(request.request),
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
        return [completion_info]

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

    # Batcher overrides

    @override
    async def _check_batch(
        self, batch: Batch[GenerateContentResponse]
    ) -> BatchCheckResult[CompletedBatchInfo]:
        batch_job = await self._client.aio.batches.get(name=batch.id)

        created_at = int(
            (
                batch_job.create_time
                if batch_job.create_time
                else datetime.now(tz=timezone.utc)
            ).timestamp()
        )

        # Handle different job states
        if (
            batch_job.state == JobState.JOB_STATE_PENDING
            or batch_job.state == JobState.JOB_STATE_RUNNING
        ):
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=created_at,
                completion_info=None,
            )
        elif batch_job.state in (
            JobState.JOB_STATE_SUCCEEDED,
            JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
        ):
            assert batch_job.dest and batch_job.dest.file_name, "must find batch dest"
            return BatchCheckResult(
                completed_count=len(batch.requests),
                failed_count=0,  # Failed count will be determined during result parsing
                created_at=created_at,
                completion_info=batch_job.dest.file_name,
            )
        elif batch_job.state in (
            JobState.JOB_STATE_FAILED,
            JobState.JOB_STATE_CANCELLED,
            JobState.JOB_STATE_EXPIRED,
        ):
            return BatchCheckResult(
                completed_count=0,
                failed_count=len(batch.requests),
                created_at=created_at,
                completion_info=None,
            )
        else:
            # Unknown state - treat as pending
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=created_at,
                completion_info=None,
            )
