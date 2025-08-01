import time
from typing import TypeAlias, cast

import httpx
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    AsyncAnthropicVertex,
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
from anthropic.types.messages import MessageBatchIndividualResponse
from anthropic.types.messages.batch_create_params import (
    Request as AnthropicBatchRequest,
)
from typing_extensions import override

from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._retry import ModelRetryConfig

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
        retry_config: ModelRetryConfig,
    ):
        super().__init__(
            config,
            retry_config,
            max_batch_request_count=100000,
            max_batch_size_mb=256,
        )
        self._client = client

    # Batcher overrides

    @override
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

        batch_info = await self._client.messages.batches.create(
            requests=requests,
            extra_headers=extra_headers or None,
        )
        return batch_info.id

    @override
    async def _check_batch(
        self, batch: Batch[Message]
    ) -> tuple[int, int, int, (CompletedBatchInfo | None)]:
        batch_info = await self._client.messages.batches.retrieve(batch.id)

        return (
            batch_info.request_counts.succeeded + batch_info.request_counts.canceled,
            batch_info.request_counts.expired + batch_info.request_counts.errored,
            (
                int(time.time() - batch_info.created_at.timestamp())
                if batch_info.created_at
                else 0
            ),
            # We don't need any extra completion info beyond the True since we
            # retrieve the results directly via the sdk given the batch id.
            True if batch_info.processing_status == "ended" else None,
        )

    @override
    async def _handle_batch_result(
        self,
        batch: Batch[Message],
        completion_info: CompletedBatchInfo,
    ) -> dict[str, Message | Exception]:
        return {
            individual_response.custom_id: _get_individual_result(individual_response)
            async for individual_response in await self._client.messages.batches.results(
                batch.id
            )
        }


def _get_individual_result(
    individual_response: MessageBatchIndividualResponse,
) -> Message | Exception:
    import anthropic

    if individual_response.result.type == "succeeded":
        return individual_response.result.message
    elif individual_response.result.type == "errored":
        # See anthropic._client.AsyncAnthropic._make_status_error
        message = individual_response.result.error.error.message
        error_class: type[anthropic.APIStatusError]
        match individual_response.result.error.error:
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
        return response
    elif individual_response.result.type == "canceled":
        return APIConnectionError(
            request=httpx.Request(
                method="POST",
                url="https://api.anthropic.com/v1/messages/batches",
            )
        )
    elif individual_response.result.type == "expired":
        return APITimeoutError(
            request=httpx.Request(
                method="POST",
                url="https://api.anthropic.com/v1/messages/batches",
            )
        )
    else:
        return TypeError(f"Unknown result type {individual_response.result.type}")
