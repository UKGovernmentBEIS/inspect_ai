import dataclasses
import json
import time
from datetime import datetime, timezone

from google.genai import Client
from google.genai.types import (
    BatchJob,
    Content,
    ContentUnion,
    CreateBatchJobConfig,
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    InlinedRequest,
    InlinedResponse,
    JobState,
)
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import Batch, BatchCheckResult, Batcher, BatchRequest
from .util.hooks import HttpxHooks


@dataclasses.dataclass
class GoogleBatchRequest:
    """Request payload for Google batch — carries SDK types directly."""

    contents: list[Content]
    config: GenerateContentConfig


class GoogleBatcher(Batcher[GoogleBatchRequest, GenerateContentResponse, BatchJob]):
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
            max_batch_request_count=50000,
            max_batch_size_mb=2000,
        )
        self._client = client
        self._model_name = model_name

    # Batcher overrides

    @override
    def _estimate_request_size(self, request: GoogleBatchRequest) -> int:
        dumped = {
            "contents": [c.model_dump(exclude_none=True) for c in request.contents],
            **request.config.model_dump(exclude_none=True),
        }
        return len(json.dumps(dumped, separators=(",", ":")))

    @override
    async def _create_batch(
        self, batch: list[BatchRequest[GoogleBatchRequest, GenerateContentResponse]]
    ) -> str:
        inline_requests: list[InlinedRequest] = []
        extra_headers: dict[str, str] = {}

        for request in batch:
            # Extract headers and request ID from config's http_options
            config = request.request.config
            if config.http_options and config.http_options.headers:
                extra_headers = dict(config.http_options.headers)
                request_id = extra_headers.pop(HttpxHooks.REQUEST_ID_HEADER, None)
                if request_id is not None:
                    request.custom_id = request_id

            # Strip http_options before passing to InlinedRequest
            config_for_batch = config.model_copy(update={"http_options": None})

            inline_requests.append(
                InlinedRequest(
                    # Copy to widen list[Content] → list[ContentUnion] (list invariance)
                    contents=list[ContentUnion](request.request.contents),
                    config=config_for_batch,
                )
            )

        request_id = extra_headers.get(HttpxHooks.REQUEST_ID_HEADER, "")
        display_name = (
            f"batch_job_{request_id}" if request_id else f"batch_job_{int(time.time())}"
        )

        batch_job = await self._client.aio.batches.create(
            model=self._model_name,
            src=inline_requests,
            config=CreateBatchJobConfig(
                display_name=display_name,
                http_options=HttpOptions(headers=extra_headers or None),
            ),
        )
        return batch_job.name or ""

    @override
    async def _check_batch(
        self, batch: Batch[GoogleBatchRequest, GenerateContentResponse]
    ) -> BatchCheckResult[BatchJob]:
        batch_job = await self._client.aio.batches.get(name=batch.id)

        created_at = int(
            (
                batch_job.create_time
                if batch_job.create_time
                else datetime.now(tz=timezone.utc)
            ).timestamp()
        )

        if batch_job.state in (
            JobState.JOB_STATE_PENDING,
            JobState.JOB_STATE_RUNNING,
        ):
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=created_at,
                completion_info=None,
            )
        elif batch_job.state == JobState.JOB_STATE_SUCCEEDED:
            return BatchCheckResult(
                completed_count=len(batch.requests),
                failed_count=0,
                created_at=created_at,
                completion_info=batch_job,
            )
        elif batch_job.state in (
            JobState.JOB_STATE_FAILED,
            JobState.JOB_STATE_CANCELLED,
        ):
            return BatchCheckResult(
                completed_count=0,
                failed_count=len(batch.requests),
                created_at=created_at,
                completion_info=None,
            )
        else:
            return BatchCheckResult(
                completed_count=0,
                failed_count=0,
                created_at=created_at,
                completion_info=None,
            )

    @override
    async def _handle_batch_result(
        self,
        batch: Batch[GoogleBatchRequest, GenerateContentResponse],
        completion_info: BatchJob,
    ) -> dict[str, GenerateContentResponse | Exception]:
        assert completion_info.dest, "completed batch must have dest"
        inlined_responses = completion_info.dest.inlined_responses
        assert inlined_responses is not None, "inline batch must have inlined_responses"

        # Responses are positionally ordered matching input requests.
        # Python dicts preserve insertion order, so batch.requests.keys()
        # gives custom_ids in the same order as _create_batch input.
        custom_ids = list(batch.requests.keys())
        assert len(custom_ids) == len(inlined_responses), (
            f"expected {len(custom_ids)} responses, got {len(inlined_responses)}"
        )

        return {
            custom_id: _parse_inlined_response(response)
            for custom_id, response in zip(custom_ids, inlined_responses)
        }


def _parse_inlined_response(
    response: InlinedResponse,
) -> GenerateContentResponse | Exception:
    if response.error:
        error = response.error
        return RuntimeError(f"{error.message} (code: {error.code})")
    assert response.response is not None, "inlined response must have response or error"
    return response.response
