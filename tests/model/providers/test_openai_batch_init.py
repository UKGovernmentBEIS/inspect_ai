from __future__ import annotations

import json
from typing import IO, TYPE_CHECKING, Any

import anyio
import httpx
import pytest
from openai.resources.batches import AsyncBatches
from openai.resources.chat.completions import AsyncCompletions
from openai.resources.files import AsyncFiles
from openai.types import Batch, FileObject
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelCall, ModelOutput
from inspect_ai.model._providers.openai import OpenAIAPI

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.anyio
async def test_openai_batch(mocker: MockerFixture):
    """Test that OpenAI provider can be initialized with batch parameters."""
    batch_tick = 0.01
    model = OpenAIAPI(
        model_name="gpt-3.5-turbo",
        api_key="test-key",
        config=GenerateConfig(
            batch_size=10,
            batch_max_send_delay=1.0,
            batch_tick=batch_tick,
        ),
    )
    input_file_id = "test-file-id"
    output_file_id = "test-output-file-id"
    error_file_id = None
    batch_id = "test-batch-id"
    model_name = "gpt-4o-mini"

    mock_completions_create = mocker.AsyncMock(
        spec=AsyncCompletions.create,
        return_value=ChatCompletion(
            id="test-id",
            object="chat.completion",
            created=1718239200,
            model=model_name,
            choices=[],
        ),
    )
    mocker.patch.object(AsyncCompletions, "create", mock_completions_create)

    input_file_contents = b""

    async def stub_files_create(file: IO[bytes], **_kwargs: Any):
        nonlocal input_file_contents
        input_file_contents = file.read()

        return FileObject(
            id=input_file_id,
            object="file",
            created_at=1718239200,
            filename="test-filename",
            purpose="batch",
            bytes=10,
            status="processed",
        )

    mock_files_create = mocker.AsyncMock(
        spec=AsyncFiles.create,
        side_effect=stub_files_create,
    )
    mocker.patch.object(AsyncFiles, "create", mock_files_create)

    mock_batches_create = mocker.AsyncMock(
        spec=AsyncBatches.create,
        return_value=Batch(
            id=batch_id,
            completion_window="24h",
            created_at=1718239200,
            endpoint="/v1/chat/completions",
            input_file_id=input_file_id,
            object="batch",
            status="in_progress",
        ),
    )
    mocker.patch.object(AsyncBatches, "create", mock_batches_create)

    file_content_response = None

    async def stub_batches_retrieve(batch_id: str):
        nonlocal file_content_response
        requests = next(iter(model._batch_inflight.values()))
        file_content_response = httpx.Response(
            status_code=200,
            text="\n".join(
                [
                    json.dumps(
                        {
                            "id": f"test-id-{idx_request}",
                            "custom_id": custom_id,
                            "response": {
                                "status_code": 200,
                                "request_id": str(idx_request),
                                "body": ChatCompletion(
                                    id=f"chatcmpt-{idx_request}",
                                    object="chat.completion",
                                    created=1718239200,
                                    model=model_name,
                                    choices=[
                                        Choice(
                                            message=ChatCompletionMessage(
                                                role="assistant",
                                                content=f"Hello, world {idx_request}!",
                                            ),
                                            index=0,
                                            finish_reason="stop",
                                        )
                                    ],
                                ).model_dump(),
                            },
                        }
                    )
                    for idx_request, custom_id in enumerate(requests)
                ]
            ),
        )

        return Batch(
            id=batch_id,
            completion_window="24h",
            created_at=1718239200,
            endpoint="/v1/chat/completions",
            input_file_id=input_file_id,
            object="batch",
            status="completed",
            output_file_id=output_file_id,
            error_file_id=error_file_id,
        )

    mock_batches_retrieve = mocker.AsyncMock(
        spec=AsyncBatches.retrieve,
        side_effect=stub_batches_retrieve,
    )
    mocker.patch.object(AsyncBatches, "retrieve", mock_batches_retrieve)

    mock_files_content = mocker.AsyncMock(
        spec=AsyncFiles.content,
        side_effect=lambda *_args, **_kwargs: file_content_response,
    )
    mocker.patch.object(AsyncFiles, "content", mock_files_content)

    assert len(model._batch_queue) == 0  # pyright: ignore[reportPrivateUsage]
    assert model._batch_worker_task is None  # pyright: ignore[reportPrivateUsage]
    assert model._batch_inflight == {}  # pyright: ignore[reportPrivateUsage]

    generations: list[tuple[ModelOutput, ModelCall]] = []

    async def generate(idx_call: int):
        generation = await model.generate(
            input=[ChatMessageUser(content=f"Hello, world {idx_call}!")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
        generations.append(generation)
        return generation

    async with anyio.create_task_group() as tg:
        tg.start_soon(generate, 0)
        await anyio.sleep(2 * batch_tick)

        mock_completions_create.assert_not_awaited()

        assert len(model._batch_queue) == 1  # pyright: ignore[reportPrivateUsage]
        assert model._batch_inflight == {}  # pyright: ignore[reportPrivateUsage]
        assert model._batch_worker_task is not None  # pyright: ignore[reportPrivateUsage]

        mock_files_create.assert_not_awaited()
        mock_batches_create.assert_not_awaited()

        for idx_call in range(1, 10):
            tg.start_soon(generate, idx_call)

        await anyio.sleep(2 * batch_tick)

        mock_completions_create.assert_not_awaited()
        mock_files_create.assert_awaited_once()
        assert mock_files_create.call_args_list[0].kwargs["purpose"] == "batch"

        mock_batches_create.assert_awaited_once()
        assert (
            mock_batches_create.call_args_list[0].kwargs["input_file_id"]
            == input_file_id
        )
        assert (
            mock_batches_create.call_args_list[0].kwargs["completion_window"] == "24h"
        )
        assert (
            mock_batches_create.call_args_list[0].kwargs["endpoint"]
            == "/v1/chat/completions"
        )

        assert len(input_file_contents) > 0
        batch_content = [
            json.loads(line) for line in input_file_contents.decode().splitlines()
        ]
        assert len(batch_content) == 10
        assert (
            batch_content
            == [
                {
                    "custom_id": mocker.ANY,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"Hello, world {idx_call}!",
                            }
                        ],
                    },
                }
            ]
            for idx_call in range(10)
        )

    assert len(generations) == 10
    for idx_call, generation in enumerate(generations):
        assert isinstance(generation, tuple)
        assert len(generation) == 2
        generation_output, generation_call = generation
        assert isinstance(generation_output, ModelOutput)
        assert generation_output.model == model_name
        assert generation_output.completion == f"Hello, world {idx_call}!"

        assert isinstance(generation_call, ModelCall)

    assert model._batch_inflight == {}  # pyright: ignore[reportPrivateUsage]
    assert len(model._batch_queue) == 0  # pyright: ignore[reportPrivateUsage]

    await anyio.sleep(2 * batch_tick)

    assert model._batch_worker_task is None  # pyright: ignore[reportPrivateUsage]
