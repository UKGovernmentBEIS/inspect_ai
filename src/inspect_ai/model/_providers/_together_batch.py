from __future__ import annotations

import functools
import sys
from typing import IO, Any, Literal, TypedDict, cast

from anyio import to_thread
from openai import AsyncOpenAI
from typing_extensions import override

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers._openai_batch import OpenAIBatcher
from inspect_ai.model._retry import ModelRetryConfig


class CompletedBatchInfo(TypedDict):
    result_uris: list[str]


class TogetherBatcher(OpenAIBatcher):
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

        super().__init__(client, config, retry_config)
        # together uses different file upload method than openai
        # async client doesn't have .upload method implemented
        self._together_client = Together(
            api_key=client.api_key, base_url=str(client.base_url)
        )

    @override
    async def _upload_batch_file(
        self, temp_file: IO[bytes], extra_headers: dict[str, str]
    ) -> str:
        # The Together.ai sdk client decided that everyone would want a progress
        # indicator in the console via tqdm. Doing this on another thread induces
        # Python's multiprocessing resource management code. This code requires a
        # valid fd at stderr. Textual, which inspect uses for its rending during
        # an eval, redirects stderr to something that has -1 for its fd. This
        # causes the to_thread call to fail.
        # To work around that, we temporarily move back to the original stderr
        # for the duration of the upload.
        old_stderr = sys.stderr
        sys.stderr = sys.__stderr__
        try:
            response = await to_thread.run_sync(
                functools.partial(
                    self._together_client.files.upload, purpose="batch-api"
                ),
                temp_file.name,
            )
        finally:
            sys.stderr = old_stderr
        return str(response.id)

    @override
    async def _create_xxx_batch(
        self,
        file_id: str,
        endpoint: Literal["/v1/chat/completions"],
        extra_headers: dict[str, str],
    ) -> str:
        response = await self._client.batches.create(
            input_file_id=file_id,
            completion_window="24h",
            endpoint=endpoint,
            extra_headers=extra_headers or None,
        )
        if response.id:
            return response.id

        if not hasattr(response, "job"):
            raise ValueError("Batch creation failed")

        job_info = cast(dict[str, Any], response.job)  # pyright: ignore[reportUnknownMemberType,reportAttributeAccessIssue]
        if "id" in job_info:
            return str(job_info["id"])

        raise ValueError("Batch creation failed")
