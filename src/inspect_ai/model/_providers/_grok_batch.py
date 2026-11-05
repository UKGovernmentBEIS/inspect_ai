import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import anyio
import grpc
from google.protobuf.json_format import ParseDict
from typing_extensions import override

# xai_sdk currently ships without `py.typed`, so mypy reports these as untyped imports.
from xai_sdk import AsyncClient  # type: ignore
from xai_sdk.batch import BatchResult  # type: ignore
from xai_sdk.chat import BaseChat, Response, chat_pb2  # type: ignore

from inspect_ai._util.notgiven import sanitize_notgiven
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

from .util.batch import Batch, BatchCheckResult, Batcher, BatchRequest

CompletedBatchInfo = bool
# xAI docs note batches above this size may be throttled.
XAI_DOC_MAX_BATCH_REQUEST_COUNT = 1_000_000
# xAI docs publish a per-request payload contract of 25MB.
# This is not the observed gRPC add transport ceiling; we avoid that by
# submitting one request per add call below.
XAI_DOC_MAX_REQUEST_PAYLOAD_BYTES = 25 * 1024 * 1024
GRPC_STATUS_BY_CODE = {status.value[0]: status for status in grpc.StatusCode}


class GrokBatcher(Batcher[Response, CompletedBatchInfo]):
    def __init__(
        self,
        client: AsyncClient,
        config: BatchConfig,
        retry_config: ModelRetryConfig,
    ):
        super().__init__(
            config=config,
            retry_config=retry_config,
            # xAI docs: very large batches (>1,000,000 requests) may be throttled.
            # https://docs.x.ai/developers/advanced-api-usage/batch-api
            max_batch_request_count=XAI_DOC_MAX_BATCH_REQUEST_COUNT,
            # Framework-level aggregate queue guardrail (not an xAI hard limit).
            max_batch_size_mb=200,
        )
        self._client = client
        # Batch API calls running on each client, so a replaced client is
        # closed only once nothing uses it.
        self._client_users: dict[AsyncClient, int] = {}

    async def replace_client(self, client: AsyncClient) -> None:
        """Send later batch API calls on `client`.

        A credential refresh needs a new client, since an xAI client fixes its
        API key when it is built. Calls already running keep the old client,
        which is closed when the last of them ends.
        """
        old_client = self._client
        self._client = client
        if old_client not in self._client_users:
            await _close_client(old_client)

    @asynccontextmanager
    async def _use_client(self) -> AsyncIterator[AsyncClient]:
        """The current client, for one RPC.

        Hold it for a single call only, so the next call after a credential
        refresh uses the new client.
        """
        client = self._client
        self._client_users[client] = self._client_users.get(client, 0) + 1
        try:
            yield client
        finally:
            self._client_users[client] -= 1
            if self._client_users[client] == 0:
                del self._client_users[client]
                if client is not self._client:
                    await _close_client(client)

    @override
    async def _create_batch(self, batch_requests: list[BatchRequest[Response]]) -> str:
        requests: list[BaseChat] = []
        for batch_request in batch_requests:
            request_size_bytes = len(
                json.dumps(
                    sanitize_notgiven(batch_request.request),
                    separators=(",", ":"),
                )
            )
            if request_size_bytes > XAI_DOC_MAX_REQUEST_PAYLOAD_BYTES:
                raise ValueError(
                    f"Batch request {batch_request.custom_id} exceeds xAI's 25MB payload limit "
                    + f"({request_size_bytes} bytes)."
                )

            # BatchRequest.request is dict-shaped (used by shared batching logic);
            # rehydrate provider fields back to protobufs before chat.create().
            request = dict(batch_request.request)
            request["messages"] = [
                ParseDict(message, chat_pb2.Message())
                for message in request.get("messages", [])
            ]
            request["tools"] = [
                ParseDict(tool, chat_pb2.Tool()) for tool in request.get("tools", [])
            ]

            tool_choice = request.get("tool_choice")
            if isinstance(tool_choice, dict):
                request["tool_choice"] = ParseDict(tool_choice, chat_pb2.ToolChoice())
            response_format = request.get("response_format")
            if isinstance(response_format, dict):
                # Preserve structured-output schema in batch mode by restoring
                # the typed ResponseFormat expected by the xAI SDK.
                request["response_format"] = ParseDict(
                    response_format, chat_pb2.ResponseFormat()
                )

            request["batch_request_id"] = batch_request.custom_id
            requests.append(self._client.chat.create(**request))

        async with self._use_client() as client:
            batch = await client.batch.create(
                batch_name=f"inspect_batch_{int(time.time())}"
            )
        # Add requests one-by-one to avoid large gRPC payloads in a single add call.
        # Observed gRPC transport caps (~4MB decode / ~20MB send on packed add)
        # are empirical, not documented API contract.
        for request in requests:
            async with self._use_client() as client:
                await client.batch.add(
                    batch_id=batch.batch_id,
                    batch_requests=[request],
                )
        return cast(str, batch.batch_id)

    @override
    async def _check_batch(
        self, batch: Batch[Response]
    ) -> BatchCheckResult[CompletedBatchInfo]:
        async with self._use_client() as client:
            info = await client.batch.get(batch.id)
        state = info.state
        created_at = (
            int(info.create_time.seconds) if info.create_time else int(time.time())
        )
        completed_count = state.num_success
        failed_count = state.num_error + state.num_cancelled
        terminal_count = completed_count + failed_count
        is_terminal = (
            state.num_pending == 0
            and state.num_requests > 0
            and terminal_count == state.num_requests
        )

        return BatchCheckResult(
            completed_count=completed_count,
            failed_count=failed_count,
            created_at=created_at,
            completion_info=True if is_terminal else None,
        )

    @override
    async def _handle_batch_result(
        self,
        batch: Batch[Response],
        _completion_info: CompletedBatchInfo,
    ) -> dict[str, Response | Exception]:
        """Fetch and map xAI batch results from list_batch_results pages.

        xAI returns per-request results directly from the batch API rather than
        downloadable JSONL result files, so this provider handles paging and
        request-id mapping here instead of using FileBatcher.
        """
        results: dict[str, Response | Exception] = {}
        pagination_token: str | None = None

        while True:
            async with self._use_client() as client:
                result_page = await client.batch.list_batch_results(
                    batch_id=batch.id,
                    pagination_token=pagination_token,
                )

            for result in result_page.results:
                if result.batch_request_id not in batch.requests:
                    continue
                if result.is_success:
                    results[result.batch_request_id] = result.response
                else:
                    results[result.batch_request_id] = _batch_result_error(result)

            pagination_token = result_page.pagination_token
            if not pagination_token:
                break

        for request_id in batch.requests:
            if request_id not in results:
                results[request_id] = RuntimeError(
                    f"No result found for batch request id '{request_id}'"
                )

        return results


async def _close_client(client: AsyncClient) -> None:
    # shielded so a cancelled caller cannot leave the client's channels open
    with anyio.CancelScope(shield=True):
        await client.close()


def _batch_result_error(result: BatchResult) -> grpc.RpcError:
    error_status = getattr(getattr(result, "proto", None), "error", None)
    code_number = int(getattr(error_status, "code", grpc.StatusCode.UNKNOWN.value[0]))
    status_code = GRPC_STATUS_BY_CODE.get(code_number, grpc.StatusCode.UNKNOWN)
    return _BatchRpcError(
        status_code=status_code,
        message=result.error_message or "Batch request failed",
    )


class _BatchRpcError(grpc.RpcError):
    def __init__(self, status_code: grpc.StatusCode, message: str):
        self._status_code = status_code
        self._message = message

    @override
    def code(self) -> grpc.StatusCode:
        return self._status_code

    @override
    def details(self) -> str:
        return self._message
