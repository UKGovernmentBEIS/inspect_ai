from unittest.mock import patch

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import (
    set_active_model_event_call,
    track_active_model_event,
)
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig, ModelOutput, ModelRequestId
from inspect_ai.model._providers.util.hooks import HttpHooks


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
