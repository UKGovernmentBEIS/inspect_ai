from typing import Any, Iterator
from unittest.mock import patch

import anyio
import pytest

from inspect_ai._util._async import tg_collect
from inspect_ai._util.registry import _registry
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import (
    set_active_model_event_call,
    track_active_model_event,
)
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelRequestId,
    active_model_event_id,
    get_model,
    modelapi,
    record_response_headers,
)
from inspect_ai.model._providers.util.hooks import HttpHooks
from inspect_ai.model._response_headers import (
    ResponseHeaders,
    track_response_headers,
)


def test_set_active_model_event_call_notifies_transcript():
    """set_active_model_event_call notifies transcript when call is recorded."""
    transcript = Transcript()
    init_transcript(transcript)

    event = ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test", choices=[]),
    )

    with patch.object(transcript, "_event_updated") as mock_updated:
        with track_active_model_event(event):
            call = set_active_model_event_call(request={"model": "test"})

        mock_updated.assert_called_once_with(event)

    assert event.call is call


def _model_event() -> ModelEvent:
    return ModelEvent(
        model="test",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="test", choices=[]),
    )


def test_request_ids_recorded_for_each_http_attempt():
    """A retried attempt's request id is kept alongside the final attempt's."""
    hooks = HttpHooks()
    request_id = hooks._start_request()
    event = _model_event()

    with (
        track_active_model_event(event),
        patch("inspect_ai.model._providers.util.hooks.report_http_retry"),
    ):
        hooks.update_request_time(request_id)
        hooks.record_response(request_id, 429, {"x-request-id": "req_first"})
        hooks.update_request_time(request_id)
        hooks.record_response(request_id, 200, {"x-request-id": "req_second"})

    assert event.request_ids == [
        ModelRequestId(id="req_first", header="x-request-id", status=429),
        ModelRequestId(id="req_second", header="x-request-id", status=200),
    ]


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"x-request-id": "req_openai"}, [("req_openai", "x-request-id")]),
        ({"request-id": "req_anthropic"}, [("req_anthropic", "request-id")]),
        ({"x-amzn-requestid": "aws-request"}, [("aws-request", "x-amzn-requestid")]),
        ({"X-Request-ID": "req_mixed_case"}, [("req_mixed_case", "x-request-id")]),
        (
            {"x-amzn-RequestId": "gateway-request", "x-request-id": "req_upstream"},
            [("req_upstream", "x-request-id"), ("gateway-request", "x-amzn-requestid")],
        ),
        (
            {
                "mistral-correlation-id": "mistral-req",
                "x-kong-request-id": "mistral-req",
            },
            [("mistral-req", "mistral-correlation-id")],
        ),
    ],
)
def test_request_ids_read_from_response_headers(
    headers: dict[str, str], expected: list[tuple[str, str]]
) -> None:
    hooks = HttpHooks()
    request_id = hooks._start_request()
    event = _model_event()

    with track_active_model_event(event):
        hooks.record_response(request_id, 200, headers)

    assert event.request_ids == [
        ModelRequestId(id=id, header=header, status=200) for id, header in expected
    ]


def test_response_without_request_id_header_records_nothing():
    hooks = HttpHooks()
    request_id = hooks._start_request()
    event = _model_event()

    with track_active_model_event(event):
        hooks.record_response(request_id, 200, {"content-type": "application/json"})
        hooks.record_response(request_id, 200, None)

    assert event.request_ids is None


def test_request_ids_recorded_only_for_registered_requests():
    """Responses to requests without a registered Inspect request id are ignored."""
    hooks = HttpHooks()
    event = _model_event()

    with track_active_model_event(event):
        hooks.record_response(None, 200, {"x-request-id": "req_untracked"})
        hooks.record_response("unregistered", 200, {"x-request-id": "req_unknown"})

    assert event.request_ids is None


def test_request_ids_ignored_without_active_model_event():
    hooks = HttpHooks()
    request_id = hooks._start_request()

    hooks.record_response(request_id, 200, {"x-request-id": "req_no_event"})

    assert hooks._requests[request_id].last_status == 200


def test_response_headers_recorded_are_the_latest_attempts():
    """A model call's response headers are those of its latest HTTP attempt."""
    hooks = HttpHooks()
    request_id = hooks._start_request()
    headers = ResponseHeaders()

    with (
        track_response_headers(headers),
        patch("inspect_ai.model._providers.util.hooks.report_http_retry"),
    ):
        hooks.update_request_time(request_id)
        hooks.record_response(request_id, 503, {"X-First": "a"})
        hooks.update_request_time(request_id)
        hooks.record_response(request_id, 200, {"X-Second": "b"})

    assert headers.latest == {"x-second": "b"}
    # a response outside a tracked model call is not kept
    hooks.record_response(request_id, 200, {"x-third": "c"})
    assert headers.latest == {"x-second": "b"}


def test_provider_can_record_its_own_response_headers():
    """A provider without the HTTP hooks records headers through the public function."""
    headers = ResponseHeaders()

    with track_response_headers(headers):
        record_response_headers({"X-From-My-Sdk": "a"})

    assert headers.latest == {"x-from-my-sdk": "a"}


def test_response_to_an_untracked_request_is_not_kept():
    """A provider's side request, which carries no request id, leaves the reply's headers alone."""
    hooks = HttpHooks()
    request_id = hooks._start_request()
    headers = ResponseHeaders()

    with track_response_headers(headers):
        hooks.record_response(request_id, 200, {"X-Reply": "a"})
        hooks.record_response(None, 200, {"X-Side-Request": "b"})
        hooks.record_response("not-a-tracked-id", 200, {"X-Side-Request": "c"})

    assert headers.latest == {"x-reply": "a"}


class _TransientError(Exception):
    pass


class _EventIdAPI(ModelAPI):
    """Records `active_model_event_id()` inside each `generate()`, by input text."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[],
            config=config,
        )
        self.fail_first: bool = model_args.get("fail_first", False)
        self.concurrent: int = model_args.get("concurrent", 1)
        self.seen: list[tuple[str, str | None]] = []
        self.in_child_task: list[str | None] = []
        self._arrived = 0
        self._all_arrived = anyio.Event()

    async def generate(
        self, input: list[ChatMessage], *args: Any, **kwargs: Any
    ) -> ModelOutput:
        # hold every call until all are in flight together
        self._arrived += 1
        if self._arrived >= self.concurrent:
            self._all_arrived.set()
        await self._all_arrived.wait()

        self.seen.append((input[-1].text, active_model_event_id()))

        async def child() -> None:
            self.in_child_task.append(active_model_event_id())

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)

        if self.fail_first and len(self.seen) == 1:
            raise _TransientError()
        return ModelOutput.from_content(self.model_name, "ok")

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, _TransientError)


@pytest.fixture
def event_id_api() -> Iterator[None]:
    @modelapi(name="eventidstub")
    def eventidstub() -> type[ModelAPI]:
        return _EventIdAPI

    try:
        yield
    finally:
        del _registry["modelapi:eventidstub"]


def _model_events() -> list[ModelEvent]:
    return [e for e in transcript().events if isinstance(e, ModelEvent)]


@pytest.mark.usefixtures("event_id_api")
async def test_active_model_event_id_is_the_calls_event() -> None:
    init_transcript(Transcript())
    model = get_model("eventidstub/model", memoize=False)
    api = model.api
    assert isinstance(api, _EventIdAPI)

    assert active_model_event_id() is None
    await model.generate("hello")
    assert active_model_event_id() is None

    [event] = _model_events()
    assert event.uuid is not None
    assert api.seen == [("hello", event.uuid)]
    # a task started inside the call sees the same id
    assert api.in_child_task == [event.uuid]


@pytest.mark.usefixtures("event_id_api")
async def test_active_model_event_id_is_new_for_each_retry() -> None:
    init_transcript(Transcript())
    model = get_model("eventidstub/model", memoize=False, fail_first=True)
    api = model.api
    assert isinstance(api, _EventIdAPI)

    await model.generate("hello", config=GenerateConfig(max_retries=1))

    failed, succeeded = _model_events()
    assert failed.error is not None and succeeded.error is None
    assert failed.uuid != succeeded.uuid
    assert [event_id for _, event_id in api.seen] == [failed.uuid, succeeded.uuid]


@pytest.mark.usefixtures("event_id_api")
async def test_active_model_event_id_in_concurrent_calls() -> None:
    init_transcript(Transcript())
    model = get_model("eventidstub/model", memoize=False, concurrent=2)
    api = model.api
    assert isinstance(api, _EventIdAPI)

    await tg_collect(
        [lambda: model.generate("first"), lambda: model.generate("second")]
    )

    events = {event.input[-1].text: event.uuid for event in _model_events()}
    assert len(set(events.values())) == 2
    assert dict(api.seen) == events
