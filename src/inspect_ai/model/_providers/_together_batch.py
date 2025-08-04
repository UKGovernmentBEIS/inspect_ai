from __future__ import annotations

import datetime
import functools
import sys
from typing import IO, TypedDict, cast

from anyio import to_thread
from openai import AsyncOpenAI
from openai.types import Batch as OpenAIBatch
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.model._retry import ModelRetryConfig


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class TogetherBatcher(OpenAIBatcher[ChatCompletion]):
    def __init__(
        self,
        client: AsyncOpenAI,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
    ):
        FEATURE = "Together Batch API"
        PACKAGE = "together"
        MIN_VERSION = "1.5.13"

        try:
            from together import Together  # type: ignore

            verify_required_version(FEATURE, PACKAGE, MIN_VERSION)
        except ImportError:
            raise pip_dependency_error(FEATURE, [PACKAGE])

        super().__init__(client, config, retry_config, ChatCompletion)
        # together uses different file upload method than openai
        # async client doesn't have .upload method implemented
        self._together_sync_client = Together(
            api_key=client.api_key, base_url=str(client.base_url)
        )

    # OpenAIBatcher overrides

    @override
    def _adapt_batch_info(self, input: OpenAIBatch) -> OpenAIBatch:
        # Together.ai's response for polling batches is NOT compatible with
        # OpenAI. In order to share the OpenAI base class, we need to coerce
        # the Together.ai response into a valid OpenAI one.
        return OpenAIBatch.model_validate(
            {
                **input.model_dump(exclude_none=True, warnings=False),
                "completion_window": "24h",
                "object": "batch",
                "status": str(input.status).lower(),
                **{
                    field: _iso_to_unix(input, field)
                    for field in [
                        "created_at",
                        "cancelled_at",
                        "cancelling_at",
                        "completed_at",
                        "expired_at",
                        "expires_at",
                        "failed_at",
                        "finalizing_at",
                        "in_progress_at",
                    ]
                },
            }
        )

    # FileBatcher overrides

    @override
    async def _upload_batch_file(
        self, temp_file: IO[bytes], extra_headers: dict[str, str]
    ) -> str:
        # The Together.AI SDK client decided that everyone would want a progress
        # indicator in the console. They do that with tqdm. The tqdm package is
        # sophisticated and has proper locking/race condition avoidance code.
        # This locking code leverages ResourceTracker to be properly multiprocessing
        # safe. ResourceTracker requires a stderr to have a valid fd. Textual, which
        # inspect uses for its console TUI, redirects stderr to something that has
        # -1 for its fd causing ResourceTracker to throw failing the to_thread call.
        #
        # To work around this, we temporarily move back to the original stderr
        # for the duration of the upload.
        old_stderr = sys.stderr
        sys.stderr = sys.__stderr__
        try:
            response = await to_thread.run_sync(
                functools.partial(
                    self._together_sync_client.files.upload, purpose="batch-api"
                ),
                temp_file.name,
            )
        finally:
            sys.stderr = old_stderr
        return str(response.id)

    @override
    async def _submit_batch_for_file(
        self,
        file_id: str,
        extra_headers: dict[str, str],
    ) -> str:
        from together import AsyncTogether  # type: ignore

        # We make a new client every call so that we can pass variable
        # extra_headers in the request.
        client = AsyncTogether(
            api_key=self._openai_client.api_key,
            base_url=str(self._openai_client.base_url),
            supplied_headers=extra_headers,
        )

        return str((await client.batches.create_batch(file_id, self.endpoint)).id)


def _iso_to_unix(input: OpenAIBatch, field: str) -> int | None:
    """Convert an ISO date string field in input to unix time (seconds)."""
    value = getattr(input, field, None)
    return (
        None
        if value is None
        else int(
            datetime.datetime.fromisoformat(
                cast(str, value).replace("Z", "+00:00")
            ).timestamp()
        )
    )
