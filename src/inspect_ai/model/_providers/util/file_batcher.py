import functools
import json
import tempfile
from abc import abstractmethod
from typing import IO, TypeVar

import pydantic
from typing_extensions import override

from inspect_ai._util._async import tg_collect
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .batch import Batch, Batcher, BatchRequest

ResponseT = TypeVar("ResponseT")
CompletedBatchInfoT = TypeVar("CompletedBatchInfoT")


class FileBatcher(Batcher[ResponseT, CompletedBatchInfoT]):
    """Base class for batchers that use file-based batch processing.

    This class provides common functionality for batch implementations that:
    1. Create JSONL files from batch requests
    2. Upload files to provider APIs
    3. Submit batch jobs using uploaded files
    4. Parse JSONL result files

    Providers need to implement the abstract methods to customize:
    - JSONL entry formatting
    - File upload mechanics
    - Batch job submission
    - Result file parsing
    """

    def __init__(
        self,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
        max_batch_request_count: int,
        max_batch_size_mb: int,
    ) -> None:
        super().__init__(
            config=config,
            retry_config=retry_config,
            max_batch_request_count=max_batch_request_count,
            max_batch_size_mb=max_batch_size_mb,
        )

    # Batcher overrides

    @override
    async def _create_batch(self, batch: list[BatchRequest[ResponseT]]) -> str:
        """Create a batch by generating JSONL file and submitting to provider."""
        extra_headers: dict[str, str] = {}

        with tempfile.NamedTemporaryFile(
            delete=True, suffix=".jsonl", mode="w+b"
        ) as temp_file:
            for request in batch:
                # Extract common metadata (headers, request IDs)
                extra_headers, custom_id = self._process_request_metadata(
                    request, extra_headers
                )

                # Format as provider-specific JSONL entry
                jsonl_entry = self._jsonl_line_for_request(request, custom_id)

                # Write to file
                temp_file.write(json.dumps(jsonl_entry).encode() + b"\n")

            temp_file.flush()
            temp_file.seek(0)

            # Upload file and submit batch
            file_id = await self._upload_batch_file(temp_file.file, extra_headers)
            return await self._submit_batch_for_file(file_id, extra_headers)

    @override
    async def _handle_batch_result(
        self,
        batch: Batch[ResponseT],
        completion_info: CompletedBatchInfoT,
    ) -> dict[str, ResponseT | Exception]:
        """Handle batch results by processing all result files."""
        result_uris = self._uris_from_completion_info(completion_info)

        # Process all result files in parallel
        results = await tg_collect(
            [
                functools.partial(self._parse_result_file, file_id)
                for file_id in result_uris
            ]
        )

        # Combine results from all files
        combined_results: dict[str, ResponseT | Exception] = {}
        for file_result in results:
            combined_results.update(file_result)

        return combined_results

    # Abstract methods for provider-specific behavior

    @abstractmethod
    def _jsonl_line_for_request(
        self, request: BatchRequest[ResponseT], custom_id: str
    ) -> dict[str, pydantic.JsonValue]:
        """Format a request as a provider-specific JSONL entry.

        Args:
            request: The batch request to format
            custom_id: The custom ID for this request

        Returns:
            Dictionary that will be JSON-serialized as one line in the JSONL file
        """
        pass

    @abstractmethod
    async def _upload_batch_file(
        self, temp_file: IO[bytes], extra_headers: dict[str, str]
    ) -> str:
        """Upload the JSONL file to the provider.

        Args:
            temp_file: File-like object containing the JSONL data
            extra_headers: Headers to include in upload request

        Returns:
            File ID from the provider
        """
        pass

    @abstractmethod
    async def _submit_batch_for_file(
        self, file_id: str, extra_headers: dict[str, str]
    ) -> str:
        """Submit a batch job using the uploaded file.

        Args:
            file_id: ID of the uploaded file
            extra_headers: Headers to include in batch creation request

        Returns:
            Batch job ID from the provider
        """
        pass

    @abstractmethod
    async def _download_result_file(self, file_uri: str) -> bytes:
        """Download result file content as bytes.

        Args:
            file_uri: URI/ID of the result file to download

        Returns:
            File content as bytes
        """
        pass

    @abstractmethod
    def _parse_jsonl_line(
        self, line_data: dict[str, pydantic.JsonValue]
    ) -> tuple[str, ResponseT | Exception]:
        """Parse a single JSONL result line.

        Args:
            line_data: Parsed JSON data from one line

        Returns:
            Tuple of (request_id, response_or_exception)
        """
        pass

    @abstractmethod
    def _uris_from_completion_info(
        self, completion_info: CompletedBatchInfoT
    ) -> list[str]:
        """Extract result file URIs from completion info.

        Args:
            completion_info: Provider-specific completion information

        Returns:
            List of file IDs/URIs to process
        """
        pass

    # Private gunk

    def _process_request_metadata(
        self, request: BatchRequest[ResponseT], existing_headers: dict[str, str]
    ) -> tuple[dict[str, str], str]:
        """Extract headers and custom_id from request, updating existing headers."""
        from .hooks import HttpxHooks

        extra_headers = request.request.pop("extra_headers", {})
        # Merge with any existing headers
        merged_headers = existing_headers | extra_headers

        request_id = extra_headers.pop(HttpxHooks.REQUEST_ID_HEADER, None)
        if request_id is not None:
            request.custom_id = request_id

        return merged_headers, request.custom_id

    async def _parse_result_file(
        self, file_uri: str
    ) -> dict[str, ResponseT | Exception]:
        """Parse a result file from the provider.

        Args:
            file_uri: URI/ID of the result file to parse

        Returns:
            Dictionary mapping request IDs to their responses or exceptions
        """
        return {
            request_id: response_or_exception
            for line in (await self._download_result_file(file_uri))
            .decode()
            .splitlines()
            if line.strip()
            for request_id, response_or_exception in [
                self._parse_jsonl_line(json.loads(line))
            ]
            if request_id
        }
