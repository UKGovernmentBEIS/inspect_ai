from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
from test_helpers.utils import skip_if_no_grok

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    BatchConfig,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers._grok_batch import GrokBatcher
from inspect_ai.model._providers.util.batch import Batch, BatchRequest
from inspect_ai.model._retry import model_retry_config
from inspect_ai.scorer import includes


@skip_if_no_grok
async def test_grok_api() -> None:
    """Smoke test a basic Grok completion request."""
    model = get_model(
        "grok/grok-3-mini",
        config=GenerateConfig(
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


class _AlarmTimeout(Exception):
    """Raised when the smoke test alarm times out."""

    pass


def _alarm_handler(_signum: int, _frame: object) -> None:
    """Signal handler that converts SIGALRM into _AlarmTimeout."""
    raise _AlarmTimeout


@skip_if_no_grok
def test_grok_batch_submission_smoke() -> None:
    """Batch submission should not be rejected immediately by Grok provider."""
    import signal

    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(4)
    try:
        eval(
            Task(
                dataset=[Sample(input="What is 2+2?", target="4")],
                scorer=includes(),
            ),
            model="grok/grok-3-mini",
            batch=BatchConfig(size=1, send_delay=0, tick=0.1),
            fail_on_error=True,
        )
    except _AlarmTimeout:
        pass  # submission succeeded, batch just didn't complete
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _make_grok_batcher_and_batch(
    *,
    num_pending: int,
    num_success: int,
    num_error: int,
    num_cancelled: int,
) -> tuple[GrokBatcher, Batch[object]]:
    """Create a mocked batcher and single-request batch for status tests."""
    client = MagicMock()
    client.batch.get = AsyncMock(
        return_value=SimpleNamespace(
            state=SimpleNamespace(
                num_pending=num_pending,
                num_success=num_success,
                num_error=num_error,
                num_cancelled=num_cancelled,
            ),
            create_time=SimpleNamespace(seconds=1234),
        )
    )

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    send_stream = MagicMock()
    req: BatchRequest[object] = BatchRequest(
        request={},
        result_stream=send_stream,
        custom_id="req-1",
    )

    return batcher, Batch(id="batch-123", requests={"req-1": req})


@pytest.mark.parametrize(
    "num_pending,num_success,num_error,num_cancelled,expect_completed,expect_failed,expect_completion",
    [
        pytest.param(2, 0, 0, 0, 0, 0, False, id="pending"),
        pytest.param(0, 2, 0, 0, 2, 0, True, id="all-success"),
        pytest.param(0, 1, 2, 3, 1, 5, True, id="terminal-mixed"),
    ],
)
async def test_grok_check_batch_terminal_states(
    num_pending: int,
    num_success: int,
    num_error: int,
    num_cancelled: int,
    expect_completed: int,
    expect_failed: int,
    expect_completion: bool,
) -> None:
    """Map xAI batch counters to inspect batch completion semantics."""
    batcher, batch = _make_grok_batcher_and_batch(
        num_pending=num_pending,
        num_success=num_success,
        num_error=num_error,
        num_cancelled=num_cancelled,
    )

    result = await batcher._check_batch(batch)
    assert result.completed_count == expect_completed
    assert result.failed_count == expect_failed
    assert (result.completion_info is not None) == expect_completion


async def test_grok_failed_batch_items_preserve_grpc_error_semantics() -> None:
    """Preserve grpc status codes when batch items fail."""
    client = MagicMock()
    client.batch.list_batch_results = AsyncMock(
        return_value=SimpleNamespace(
            results=[
                SimpleNamespace(
                    batch_request_id="req-1",
                    is_success=False,
                    error_message="permission denied",
                    proto=SimpleNamespace(
                        error=SimpleNamespace(
                            code=grpc.StatusCode.PERMISSION_DENIED.value[0]
                        )
                    ),
                )
            ],
            pagination_token=None,
        )
    )

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    send_stream = MagicMock()
    req: BatchRequest[object] = BatchRequest(
        request={},
        result_stream=send_stream,
        custom_id="req-1",
    )
    batch = Batch(id="batch-123", requests={"req-1": req})

    results = await batcher._handle_batch_result(batch, True)
    error = results["req-1"]
    assert isinstance(error, grpc.RpcError)
    assert error.code() == grpc.StatusCode.PERMISSION_DENIED


async def test_grok_create_batch_parses_json_schema_response_format() -> None:
    """Rehydrate dict response_format into protobuf before chat.create."""
    schema = '{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'
    client = MagicMock()
    client.chat.create = MagicMock(return_value=MagicMock())
    client.batch.create = AsyncMock(return_value=SimpleNamespace(batch_id="batch-123"))
    client.batch.add = AsyncMock()

    batcher = GrokBatcher(
        client=client,
        config=BatchConfig(),
        retry_config=model_retry_config(
            "test", 3, None, lambda e: True, lambda ex: None, lambda m, s: None
        ),
    )

    request: BatchRequest[object] = BatchRequest(
        request={
            "model": "grok-3-mini",
            "messages": [],
            "tools": [],
            "response_format": {
                "formatType": "FORMAT_TYPE_JSON_SCHEMA",
                "schema": schema,
            },
        },
        result_stream=MagicMock(),
        custom_id="req-1",
    )

    await batcher._create_batch([request])
    create_kwargs = client.chat.create.call_args.kwargs
    response_format = create_kwargs["response_format"]
    assert not isinstance(response_format, dict)
    assert response_format.schema == schema
