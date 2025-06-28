from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest
from anthropic import AsyncAnthropic
from anthropic.resources.messages.batches import AsyncBatches
from anthropic.resources.messages.messages import AsyncMessages
from anthropic.types import Message, TextBlock, Usage
from anthropic.types.messages import (
    MessageBatch,
    MessageBatchIndividualResponse,
    MessageBatchRequestCounts,
    MessageBatchSucceededResult,
    batch_create_params,
)
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai._util import eval_task_group
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelCall,
    ModelOutput,
    get_model,
)
from inspect_ai.model._generate_config import BatchConfig
from inspect_ai.model._providers._anthropic_batch import AnthropicBatcher
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.util.batch import BatchRequest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_api() -> None:
    model = get_model(
        "anthropic/claude-2.1",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1


@skip_if_no_anthropic
def test_anthropic_should_retry():
    import httpx
    from anthropic import APIStatusError

    # scaffold for should_retry
    model = get_model("anthropic/claude-3-5-sonnet-latest")
    response = httpx.Response(
        status_code=405, request=httpx.Request("GET", "https://example.com")
    )

    # check whether we handle overloaded_error correctly
    ex = APIStatusError(
        "error", response=response, body={"error": {"type": "overloaded_error"}}
    )
    assert model.api.should_retry(ex)

    # check whether we handle body not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body="error")
    model.api.should_retry(ex)

    # check whether we handle error not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body={"error": "error"})
    model.api.should_retry(ex)


@pytest.mark.anyio
# @skip_if_no_anthropic
async def test_anthropic_batch(mocker: MockerFixture):
    batch_tick = 0.01
    batch_max_send_delay = 1.0
    model_name = "claude-3-7-sonnet-20250219"
    max_tokens = 1000
    generate_config = GenerateConfig(
        batch=BatchConfig(size=10, send_delay=batch_max_send_delay, tick=batch_tick),
        max_tokens=max_tokens,
    )
    model = AnthropicAPI(model_name=model_name, api_key="test-key")
    batch_id = "test-batch-id"

    mock_messages_create = mocker.AsyncMock(
        spec=AsyncMessages.create,
        return_value=Message(
            id="test-id",
            type="message",
            model=model_name,
            role="assistant",
            content=[TextBlock(type="text", text="Hello, world!")],
            usage=Usage(
                input_tokens=10,
                output_tokens=10,
            ),
        ),
    )
    mocker.patch.object(AsyncMessages, "create", mock_messages_create)

    message_batch = MessageBatch(
        id=batch_id,
        processing_status="in_progress",
        request_counts=MessageBatchRequestCounts(
            processing=10,
            expired=0,
            canceled=0,
            errored=0,
            succeeded=0,
        ),
        created_at=datetime.datetime.now(datetime.timezone.utc),
        expires_at=(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        ),
        type="message_batch",
        results_url=None,
    )

    custom_ids: list[str] = []

    async def stub_batches_create(
        requests: list[batch_create_params.Request], **_kwargs: Any
    ):
        for request in requests:
            custom_ids.append(request["custom_id"])

        return message_batch

    mock_batches_create = mocker.AsyncMock(
        spec=AsyncBatches.create,
        side_effect=stub_batches_create,
    )
    mocker.patch.object(AsyncBatches, "create", mock_batches_create)

    mock_batches_retrieve = mocker.AsyncMock(
        spec=AsyncBatches.retrieve,
        return_value=message_batch.model_copy(
            update={
                "processing_status": "ended",
                "ended_at": (
                    datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(seconds=1)
                ),
                "request_counts": MessageBatchRequestCounts(
                    processing=0,
                    expired=0,
                    canceled=0,
                    errored=0,
                    succeeded=10,
                ),
                "results_url": f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results",
            }
        ),
    )
    mocker.patch.object(AsyncBatches, "retrieve", mock_batches_retrieve)

    async def stub_batches_results(message_batch_id: str):
        for idx_result, custom_id in enumerate(custom_ids):
            yield MessageBatchIndividualResponse(
                custom_id=custom_id,
                result=MessageBatchSucceededResult(
                    type="succeeded",
                    message=Message(
                        id=f"test-id-{idx_result}",
                        type="message",
                        model=model_name,
                        role="assistant",
                        content=[
                            TextBlock(type="text", text=f"Hello, world {idx_result}!")
                        ],
                        usage=Usage(input_tokens=10, output_tokens=10),
                    ),
                ),
            )

    mock_batches_results = mocker.AsyncMock(
        spec=AsyncBatches.results,
        side_effect=stub_batches_results,
    )
    mocker.patch.object(AsyncBatches, "results", mock_batches_results)

    generations: list[ModelOutput | tuple[ModelOutput | Exception, ModelCall]] = []

    async def generate(idx_call: int):
        generation = await model.generate(
            input=[ChatMessageUser(content=f"Hello, world {idx_call}!")],
            tools=[],
            tool_choice="auto",
            config=generate_config,
        )
        generations.append(generation)  # pyright: ignore[reportArgumentType]
        return generation

    async with anyio.create_task_group() as tg:
        mocker.patch.object(eval_task_group, "_eval_task_group", tg)
        try:
            with anyio.fail_after(2 * batch_max_send_delay):
                tg.start_soon(generate, 0)
                await anyio.sleep(2 * batch_tick)

                mock_messages_create.assert_not_awaited()

                assert model._batcher is not None  # pyright: ignore[reportPrivateUsage]
                assert model._batcher._inflight_batches == {}  # pyright: ignore[reportPrivateUsage]
                assert model._batcher._is_batch_worker_running  # pyright: ignore[reportPrivateUsage]
                assert (
                    model._batcher._next_batch and len(model._batcher._next_batch) == 1
                )  # pyright: ignore[reportPrivateUsage]

                mock_batches_create.assert_not_awaited()
                mock_batches_retrieve.assert_not_awaited()

                for idx_call in range(1, 10):
                    tg.start_soon(generate, idx_call)

                await anyio.sleep(2 * batch_tick)
        except Exception as error:
            tg.cancel_scope.cancel()
            raise error

    mock_messages_create.assert_not_awaited()
    mock_batches_create.assert_awaited_once()
    requests = mock_batches_create.call_args.kwargs["requests"]
    assert len(requests) == 10
    for idx_request, request in enumerate(requests):
        request = cast(batch_create_params.Request, request)
        assert "custom_id" in request
        request_params = request["params"]
        assert request_params["model"] == model_name
        assert request_params["messages"] == [
            {"role": "user", "content": f"Hello, world {idx_request}!"}
        ]
        assert request_params["max_tokens"] == max_tokens

    assert len(generations) == 10
    for idx_call, generation in enumerate(generations):
        assert isinstance(generation, tuple)
        assert len(generation) == 2
        generation_output, generation_call = generation
        assert isinstance(generation_output, ModelOutput)
        assert generation_output.model == model_name
        assert generation_output.completion == f"Hello, world {idx_call}!"

        assert isinstance(generation_call, ModelCall)

    assert model._batcher._inflight_batches == {}  # pyright: ignore[reportPrivateUsage]
    assert not model._batcher._next_batch  # pyright: ignore[reportPrivateUsage]

    await anyio.sleep(2 * batch_tick)

    assert not model._batcher._is_batch_worker_running  # pyright: ignore[reportPrivateUsage]


def test_batcher_get_request_failed_error(mocker: MockerFixture):
    batcher = AnthropicBatcher(
        client=AsyncAnthropic(api_key="test-key"),
        config=BatchConfig(size=10, send_delay=1.0, tick=0.01),
    )
    send_stream, _ = anyio.create_memory_object_stream[Message | Exception]()
    error = batcher._get_request_failed_error(  # pyright: ignore[reportPrivateUsage]
        BatchRequest[Message](
            request={"foo": "bar"},
            result_stream=send_stream,
            custom_id="test-id",
        )
    )

    assert isinstance(error, Exception)
