from typing import TypeAlias, cast

import httpx
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    AsyncAnthropicVertex,
    InternalServerError,
)
from anthropic.types import (
    APIErrorObject,
    AuthenticationError,
    BillingError,
    GatewayTimeoutError,
    InvalidRequestError,
    Message,
    NotFoundError,
    OverloadedError,
    RateLimitError,
)
from anthropic.types import (
    PermissionError as AnthropicPermissionError,
)
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import (
    Request as AnthropicBatchRequest,
)

from inspect_ai.model._generate_config import BatchConfig

from .util.batch import (
    Batch,
    Batcher,
    BatchRequest,
)
from .util.hooks import HttpxHooks

CompletedBatchInfo: TypeAlias = bool


class AnthropicBatcher(Batcher[Message, CompletedBatchInfo]):
    def __init__(
        self,
        client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex,
        config: BatchConfig,
    ):
        super().__init__(
            config,
            max_batch_request_count=100000,
            max_batch_size_mb=256,
        )
        self.client = client

    async def _create_batch(self, batch: list[BatchRequest[Message]]) -> str:
        requests: list[AnthropicBatchRequest] = []
        extra_headers: dict[str, str] = {}
        for request in batch:
            extra_headers = request.request.pop("extra_headers", {})
            request_id = extra_headers.pop(HttpxHooks.REQUEST_ID_HEADER, None)
            if request_id is not None:
                request.custom_id = request_id
            requests.append(
                AnthropicBatchRequest(
                    custom_id=request.custom_id,
                    params=cast(MessageCreateParamsNonStreaming, request.request),
                )
            )

        batch_info = await self.client.messages.batches.create(
            requests=requests,
            extra_headers=extra_headers or None,
        )
        return batch_info.id

    async def _check_batch(self, batch: Batch[Message]) -> CompletedBatchInfo | None:
        batch_info = await self.client.messages.batches.retrieve(batch.id)

        # We don't need any extra completion info beyond the True since we
        # retrieve the results directly via the sdk given the batch id.
        return True if batch_info.processing_status == "ended" else None

    async def _handle_batch_result(
        self,
        batch: Batch[Message],
        completion_info: CompletedBatchInfo,
    ) -> None:
        import anthropic

        async for result in await self.client.messages.batches.results(batch.id):
            custom_id = result.custom_id
            batch_request = batch.requests.pop(custom_id)

            response: Message | Exception
            match result.result.type:
                case "succeeded":
                    response = result.result.message
                case "errored":
                    # See anthropic._client.AsyncAnthropic._make_status_error
                    message = result.result.error.error.message
                    error_class: type[anthropic.APIStatusError]
                    match result.result.error.error:
                        case InvalidRequestError():
                            error_class = anthropic.BadRequestError
                        case AuthenticationError():
                            error_class = anthropic.AuthenticationError
                        case BillingError():
                            error_class = anthropic.PermissionDeniedError
                        case AnthropicPermissionError():
                            error_class = anthropic.PermissionDeniedError
                        case NotFoundError():
                            error_class = anthropic.NotFoundError
                        case RateLimitError():
                            error_class = anthropic.RateLimitError
                        case GatewayTimeoutError():
                            error_class = anthropic.InternalServerError
                        case APIErrorObject():
                            error_class = anthropic.APIStatusError
                        case OverloadedError():
                            error_class = anthropic.InternalServerError
                    response = error_class(
                        message=message,
                        response=httpx.Response(status_code=500, text=message),
                        body=None,
                    )
                    response.response.status_code = response.status_code
                case "canceled":
                    response = APIConnectionError(
                        request=httpx.Request(
                            method="POST",
                            url="https://api.anthropic.com/v1/messages/batches",
                        )
                    )
                case "expired":
                    response = APITimeoutError(
                        request=httpx.Request(
                            method="POST",
                            url="https://api.anthropic.com/v1/messages/batches",
                        )
                    )

            await batch_request.result_stream.send(response)

    def _get_request_failed_error(self, request: BatchRequest[Message]) -> Exception:
        return InternalServerError(
            message="Request failed",
            response=httpx.Response(
                status_code=500,
                text="Request failed",
                request=httpx.Request(
                    method="POST",
                    url="https://api.anthropic.com/v1/messages/batches",
                ),
            ),
            body=None,
        )
