from typing import IO, TypeAlias

import pydantic
from mistralai import Mistral
from mistralai.models import BatchJobOut
from mistralai.models.conversationresponse import ConversationResponse
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import Batch, BatchCheckResult, BatchRequest
from .util.file_batcher import FileBatcher

# Just the output file ID
CompletedBatchInfo: TypeAlias = str


class MistralBatcher(FileBatcher[ConversationResponse, CompletedBatchInfo]):
    def __init__(
        self,
        client: Mistral,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
        model_name: str,
    ):
        super().__init__(
            config=config,
            retry_config=retry_config,
            max_batch_request_count=1_000_000,  # 1M ongoing requests per workspace
            max_batch_size_mb=200,  # Conservative estimate
        )
        self._client = client
        self._model_name = model_name

    # FileBatcher overrides

    @override
    def _jsonl_line_for_request(
        self, request: BatchRequest[ConversationResponse], custom_id: str
    ) -> dict[str, pydantic.JsonValue]:
        # Request body should already have model set, but filter out non-batch params
        body = {
            k: v
            for k, v in request.request.items()
            if k not in ("http_headers", "stream")
        }
        return {
            "custom_id": custom_id,
            "body": body,
        }

    @override
    async def _upload_batch_file(
        self, temp_file: IO[bytes], extra_headers: dict[str, str]
    ) -> str:
        file_obj = await self._client.files.upload_async(
            file={
                "file_name": temp_file.name,
                "content": temp_file,
            },
            purpose="batch",
        )
        return file_obj.id

    @override
    async def _submit_batch_for_file(
        self, file_id: str, extra_headers: dict[str, str]
    ) -> str:
        batch_job = await self._client.batch.jobs.create_async(
            input_files=[file_id],
            model=self._model_name,
            endpoint="/v1/conversations",
        )
        return batch_job.id

    @override
    async def _download_result_file(self, file_id: str) -> bytes:
        response = await self._client.files.download_async(file_id=file_id)
        return response.read()

    @override
    def _parse_jsonl_line(
        self, line_data: dict[str, pydantic.JsonValue]
    ) -> tuple[str, ConversationResponse | Exception]:
        custom_id = line_data.get("custom_id", "")
        assert isinstance(custom_id, str), "custom_id must be a string"

        if not custom_id:
            raise ValueError(
                f"Unable to find custom_id in batched request result. {line_data}"
            )

        error = line_data.get("error")
        if error is not None:
            return custom_id, RuntimeError(str(error))

        response = line_data.get("response")
        if not isinstance(response, dict):
            return custom_id, RuntimeError(f"Invalid response format: {line_data}")

        status_code = response.get("status_code")
        if status_code != 200:
            body = response.get("body", {})
            message = body.get("message", str(body)) if isinstance(body, dict) else body
            return custom_id, RuntimeError(f"Request failed ({status_code}): {message}")

        body = response.get("body")
        if not isinstance(body, dict):
            return custom_id, RuntimeError(f"Invalid response body: {response}")

        return custom_id, ConversationResponse.model_validate(body)

    @override
    def _uris_from_completion_info(
        self, completion_info: CompletedBatchInfo
    ) -> list[str]:
        return [completion_info]

    # Batcher overrides

    @override
    async def _check_batch(
        self, batch: Batch[ConversationResponse]
    ) -> BatchCheckResult[CompletedBatchInfo]:
        batch_job: BatchJobOut = await self._client.batch.jobs.get_async(
            job_id=batch.id
        )

        # created_at is already a unix timestamp (int)
        created_at = batch_job.created_at or batch.created_at

        # Map Mistral batch statuses (status is a Literal string type)
        status = batch_job.status
        if status in ("QUEUED", "RUNNING"):
            return BatchCheckResult(
                completed_count=batch_job.succeeded_requests or 0,
                failed_count=batch_job.failed_requests or 0,
                created_at=created_at,
                completion_info=None,
            )
        elif status == "SUCCESS":
            output_file = batch_job.output_file
            if not output_file:
                raise RuntimeError(f"Batch {batch.id} succeeded but has no output file")
            return BatchCheckResult(
                completed_count=batch_job.succeeded_requests or len(batch.requests),
                failed_count=batch_job.failed_requests or 0,
                created_at=created_at,
                completion_info=output_file,
            )
        elif status in (
            "FAILED",
            "TIMEOUT_EXCEEDED",
            "CANCELLED",
            "CANCELLATION_REQUESTED",
        ):
            # Fail all requests in the batch
            error_msg = f"Batch {batch.id} ended with status: {status}"
            await self._resolve_inflight_batch(
                batch,
                {req_id: RuntimeError(error_msg) for req_id in batch.requests},
            )
            return BatchCheckResult(
                completed_count=0,
                failed_count=len(batch.requests),
                created_at=created_at,
                completion_info=None,
            )
        else:
            # Unknown status - treat as pending
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=created_at,
                completion_info=None,
            )
