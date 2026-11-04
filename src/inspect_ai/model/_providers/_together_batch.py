from __future__ import annotations

import functools
import sys
from typing import IO, cast

from anyio import to_thread
from openai import AsyncOpenAI
from openai.types import Batch as OpenAIBatch
from openai.types.chat import ChatCompletion
from typing_extensions import TypedDict, override

from inspect_ai._util.dateutil import datetime_from_iso_format_safe
from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import has_required_version, verify_required_version
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
        MIN_VERSION = "2.0.0"

        try:
            from together import Together

            verify_required_version(FEATURE, PACKAGE, MIN_VERSION)
        except ImportError:
            raise pip_dependency_error(FEATURE, [PACKAGE])

        super().__init__(client, config, retry_config, ChatCompletion)
        # together uses different file upload method than openai
        # async client doesn't have .upload method implemented
        self._together_sync_client = Together(
            api_key=client.api_key, base_url=_together_sdk_base_url(client)
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
        from together import AsyncTogether

        # We make a new client every call so that we can pass variable
        # extra_headers in the request.
        client = AsyncTogether(
            api_key=self._openai_client.api_key,
            base_url=_together_sdk_base_url(self._openai_client),
            default_headers=extra_headers,
        )

        # Together only supports chat completions for batches (not the
        # Responses API), and TogetherBatcher is always constructed with the
        # default endpoint. Narrow the type so it matches the endpoint Literal
        # accepted by together's batches.create.
        assert self.endpoint == "/v1/chat/completions", (
            f"Together batch API does not support endpoint {self.endpoint}"
        )
        response = await client.batches.create(
            endpoint=self.endpoint, input_file_id=file_id
        )
        if response.job is not None:
            return str(response.job.id)
        else:
            raise RuntimeError(
                f"Unable to create batch: {response.warning or 'unknown error'}"
            )


def _together_sdk_base_url(client: AsyncOpenAI) -> str:
    """The base URL to give the Together SDK, derived from the OpenAI client's.

    The OpenAI client's base URL includes the API version
    (``https://api.together.xyz/v1/``). together 2.x joins it with relative
    paths (``files``), but together 3.x uses paths that already start with
    ``/v1`` (``/v1/files``), so on 3.x the version suffix must be removed or
    requests go to ``/v1/v1/...``. On 3.x a custom ``TOGETHER_BASE_URL`` should
    therefore end in ``/v1`` (as the default does); any other base URL is passed
    to the SDK unchanged.
    """
    base_url = str(client.base_url).rstrip("/")
    # "3.0.0-0" so that 3.0.0 pre-releases (rc, dev) count as 3.x
    if has_required_version("together", "3.0.0-0") and base_url.endswith("/v1"):
        base_url = base_url.removesuffix("/v1")
    return base_url


def _iso_to_unix(input: OpenAIBatch, field: str) -> int | None:
    """Convert an ISO date string field in input to unix time (seconds)."""
    value = getattr(input, field, None)
    return (
        None
        if value is None
        else int(
            datetime_from_iso_format_safe(
                cast(str, value).replace("Z", "+00:00")
            ).timestamp()
        )
    )
