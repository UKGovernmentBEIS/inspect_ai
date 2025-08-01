import time
from typing import IO, Any, Generic, Literal, TypedDict, TypeVar

import httpx
import pydantic
from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types import Batch as OpenAIBatch
from openai.types.batch import Errors as OpenAIErrors
from openai.types.batch_error import BatchError
from pydantic import BaseModel
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import (
    Batch,
    BatchRequest,
)
from .util.file_batcher import FileBatcher


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


ResponseT = TypeVar("ResponseT", bound=BaseModel)


class OpenAIBatcher(FileBatcher[ResponseT, CompletedBatchInfo], Generic[ResponseT]):
    def __init__(
        self,
        client: AsyncOpenAI,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
        response_cls: type[ResponseT],
        endpoint: Literal[
            "/v1/chat/completions", "/v1/responses"
        ] = "/v1/chat/completions",
    ):
        super().__init__(
            config=config,
            retry_config=retry_config,
            max_batch_request_count=50000,
            max_batch_size_mb=200,
        )
        self._response_cls = response_cls
        # Members below are considered protected and fair game for derived classes
        self._openai_client = client
        self.endpoint = endpoint

    # FileBatcher overrides

    @override
    def _jsonl_line_for_request(
        self, request: BatchRequest[ResponseT], custom_id: str
    ) -> dict[str, pydantic.JsonValue]:
        """Format request as OpenAI JSONL entry."""
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": self.endpoint,
            "body": {k: v for k, v in request.request.items() if v is not NOT_GIVEN},
        }

    @override
    def _uris_from_completion_info(
        self, completion_info: CompletedBatchInfo
    ) -> list[str]:
        """Extract result file URIs from OpenAI completion info."""
        return completion_info["result_uris"]

    @override
    async def _upload_batch_file(
        self,
        temp_file: IO[bytes],
        extra_headers: dict[str, str],
    ) -> str:
        """
        Uploads a batch file to the Together API.

        This method is can be overridden in derived classes to provide provider-specific
        file upload logic for batch processing.

        Args:
            temp_file: A file-like object containing the batch data to upload.
            extra_headers: Additional headers to include in the upload request.

        Returns:
            The ID of the uploaded file as a string.
        """
        file_object = await self._openai_client.files.create(
            file=temp_file,
            purpose="batch",
            extra_headers=extra_headers or None,
        )
        return file_object.id

    @override
    async def _submit_batch_for_file(
        self,
        file_id: str,
        extra_headers: dict[str, str],
    ) -> str:
        """
        Creates a batch job using the OpenAI API.

        Args:
            file_id: The ID of the uploaded batch file.
            extra_headers: Additional headers to include in the batch creation request.

        Returns:
            The ID of the created batch job as a string.

        Raises:
            ValueError: If batch creation fails or the response is invalid.
        """
        return (
            await self._openai_client.batches.create(
                input_file_id=file_id,
                completion_window="24h",
                endpoint=self.endpoint,
                extra_headers=extra_headers or None,
            )
        ).id

    @override
    async def _download_result_file(self, file_id: str) -> bytes:
        """Download result file content from OpenAI."""
        batch_file = await self._openai_client.files.content(file_id)
        return await batch_file.aread()

    @override
    def _parse_jsonl_line(
        self, line_data: dict[str, pydantic.JsonValue]
    ) -> tuple[str, ResponseT | Exception]:
        """Parse a single JSONL result line from OpenAI."""
        # Make a copy to avoid mutating the original
        result: dict[str, Any] = line_data.copy()
        request_id = result.pop("custom_id", "")
        if not request_id:
            raise ValueError(
                f"Unable to find custom_id in batched request result. {result}"
            )

        if (error := result.get("error")) is None:
            response_body = result["response"]["body"]
            return request_id, self._response_cls.model_validate(response_body)
        else:
            return request_id, (
                self._openai_client._make_status_error_from_response(  # pyright: ignore[reportPrivateUsage]
                    httpx.Response(status_code=error["code"], text=error["message"])
                )
            )

    # Batcher overrides

    @override
    async def _check_batch(
        self, batch: Batch[ResponseT]
    ) -> tuple[int, int, int, (CompletedBatchInfo | None)]:
        batch_info = self._adapt_batch_info(
            await self._openai_client.batches.retrieve(batch.id)
        )

        # If the entire batch was rejected, OpenAI doesn't populate `request_counts`.
        # Instead, the `.errors` object is set in the batch info.
        if batch_info.status == "failed":
            await self._resolve_inflight_batch(
                batch, self._results_from_rejection(batch, batch_info.errors)
            )
            return (0, 0, 0, None)

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

    # Protected - subclasses can override

    def _adapt_batch_info(self, input: OpenAIBatch) -> OpenAIBatch:
        # Some OpenAI "compatible" providers don't return data that properly
        # conforms to this. Provide a hook point to fixup that data.
        return input

    # Private gunk

    def _results_from_rejection(
        self, batch: Batch[ResponseT], errors: OpenAIErrors | None
    ) -> dict[str, ResponseT | Exception]:
        """Create error results for a rejected batch.

        On the happy path, errors.data will contain a list that is the same size as
        batch.requests. In that case, we map each batch.request.id to the corresponding
        error in errors.data.

        If errors is None, errors.data is None, or the lengths don't match, we create
        a single generic exception for all request IDs.
        """
        request_ids = list(batch.requests.keys())

        # Happy path: errors and errors.data exist and match request count
        if (
            errors is not None
            and errors.data is not None
            and len(errors.data) == len(request_ids)
        ):
            return {
                request_id: _batch_error_to_exception(error)
                for request_id, error in zip(request_ids, errors.data)
            }

        exception = RuntimeError(
            "Batch rejected: error information could not be determined"
        )

        return {request_id: exception for request_id in request_ids}


def _batch_error_to_exception(error: BatchError) -> Exception:
    """Convert a BatchError to an Exception."""
    message = error.message or "Batch request failed"
    if error.code:
        message = f"[{error.code}] {message}"
    if error.param:
        message = f"{message} (param: {error.param})"
    return RuntimeError(message)
