"""Tests for the transient-I/O retry layer in csv_dataset / json_dataset.

Mirrors the structure of tests/dataset/test_hf_dataset.py for the parallel
`hf_dataset` retry pattern introduced in PR #3836.

Two layers of coverage:

1. `_should_retry_dataset_io_error` — exception-classification unit tests
   that exercise the four HTTP-client backend shapes fsspec can dispatch to
   (built-in, aiohttp, requests, urllib).

2. `csv_dataset` / `json_dataset` integration — patches `file()` to raise a
   sequence of transient errors followed by a successful open, and asserts
   that the wrapper retries and ultimately succeeds (or, for the negative
   cases, that non-transient errors are raised on the first attempt).
"""

from __future__ import annotations

import urllib.error
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_helpers.utils import skip_if_no_package

from inspect_ai.dataset._sources._retry import (
    _call_with_dataset_retry,
    _should_retry_dataset_io_error,
)

# ---------------------------------------------------------------------------
# Predicate tests — _should_retry_dataset_io_error
# ---------------------------------------------------------------------------


def test_retry_connection_error():
    assert _should_retry_dataset_io_error(ConnectionError("reset")) is True


def test_retry_timeout_error():
    assert _should_retry_dataset_io_error(TimeoutError("slow")) is True


def test_no_retry_filenotfound():
    assert _should_retry_dataset_io_error(FileNotFoundError("/tmp/nope")) is False


def test_no_retry_permission_error():
    assert _should_retry_dataset_io_error(PermissionError("denied")) is False


def test_no_retry_value_error():
    assert _should_retry_dataset_io_error(ValueError("bad value")) is False


def test_no_retry_keyboard_interrupt():
    assert _should_retry_dataset_io_error(KeyboardInterrupt()) is False


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_retry_urllib_http_retryable_status(status: int):
    err = urllib.error.HTTPError(
        "https://example.com/data.csv", status, "err", None, None
    )
    assert _should_retry_dataset_io_error(err) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405])
def test_no_retry_urllib_http_client_error(status: int):
    err = urllib.error.HTTPError(
        "https://example.com/data.csv", status, "err", None, None
    )
    assert _should_retry_dataset_io_error(err) is False


def test_retry_urllib_urlerror_with_connection_reason():
    err = urllib.error.URLError(ConnectionError("network down"))
    assert _should_retry_dataset_io_error(err) is True


def test_no_retry_urllib_urlerror_with_unrelated_reason():
    err = urllib.error.URLError(ValueError("bad url shape"))
    assert _should_retry_dataset_io_error(err) is False


@skip_if_no_package("aiohttp")
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_retry_aiohttp_client_response_error(status: int):
    from aiohttp import ClientResponseError, RequestInfo
    from yarl import URL

    request_info = RequestInfo(
        url=URL("https://example.com/data.csv"),
        method="GET",
        headers={},  # type: ignore[arg-type]
        real_url=URL("https://example.com/data.csv"),
    )
    err = ClientResponseError(
        request_info=request_info, history=(), status=status, message="err"
    )
    assert _should_retry_dataset_io_error(err) is True


@skip_if_no_package("aiohttp")
def test_no_retry_aiohttp_client_response_error_404():
    from aiohttp import ClientResponseError, RequestInfo
    from yarl import URL

    request_info = RequestInfo(
        url=URL("https://example.com/data.csv"),
        method="GET",
        headers={},  # type: ignore[arg-type]
        real_url=URL("https://example.com/data.csv"),
    )
    err = ClientResponseError(
        request_info=request_info, history=(), status=404, message="err"
    )
    assert _should_retry_dataset_io_error(err) is False


@skip_if_no_package("aiohttp")
def test_retry_aiohttp_client_connection_error():
    from aiohttp import ClientConnectionError

    assert _should_retry_dataset_io_error(ClientConnectionError()) is True


@skip_if_no_package("requests")
def test_retry_requests_connection_error():
    from requests.exceptions import ConnectionError as RequestsConnectionError

    assert _should_retry_dataset_io_error(RequestsConnectionError("reset")) is True


@skip_if_no_package("requests")
def test_retry_requests_timeout():
    from requests.exceptions import Timeout

    assert _should_retry_dataset_io_error(Timeout("slow")) is True


@skip_if_no_package("requests")
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_retry_requests_http_error(status: int):
    from requests.exceptions import HTTPError

    response = SimpleNamespace(status_code=status)
    err = HTTPError("err")
    err.response = response  # type: ignore[assignment]
    assert _should_retry_dataset_io_error(err) is True


@skip_if_no_package("requests")
def test_no_retry_requests_http_error_404():
    from requests.exceptions import HTTPError

    response = SimpleNamespace(status_code=404)
    err = HTTPError("err")
    err.response = response  # type: ignore[assignment]
    assert _should_retry_dataset_io_error(err) is False


# ---------------------------------------------------------------------------
# Helper-level tests — _call_with_dataset_retry
# ---------------------------------------------------------------------------


def test_helper_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    # Drive the helper through 2 transient failures + 1 success without
    # actually sleeping between attempts.
    # _call_with_dataset_retry constructs a tenacity Retrying with
    # `sleep=tenacity.nap.sleep` at call time, so patching the module
    # attribute directly is sufficient to short-circuit the wait.
    monkeypatch.setattr("tenacity.nap.sleep", lambda _: None)

    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError(f"attempt {calls['n']}")
        return "ok"

    # _MAX_TRIES_DEFAULT is 3; helper should reach attempt 3 and succeed.
    assert _call_with_dataset_retry(flaky) == "ok"
    assert calls["n"] == 3


def test_helper_non_transient_raises_immediately():
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        _call_with_dataset_retry(boom)
    # Predicate says no-retry → exactly one attempt.
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Integration — csv_dataset / json_dataset behavior end-to-end
# ---------------------------------------------------------------------------


_CSV_CONTENT = "input,target\nhello,world\nfoo,bar\n"
_JSON_CONTENT = '[{"input":"hello","target":"world"},{"input":"foo","target":"bar"}]'


class _FakeFileCM:
    """Context manager that yields a `StringIO` for the given text content."""

    def __init__(self, content: str):
        self._content = content
        self._buf: StringIO | None = None

    def __enter__(self) -> StringIO:
        self._buf = StringIO(self._content)
        return self._buf

    def __exit__(self, *exc: object) -> None:
        if self._buf is not None:
            self._buf.close()


def _make_flaky_file_factory(fails: int, content: str):
    """Build a flaky `file()` replacement.

    Returns a callable that raises ConnectionError `fails` times and then
    yields a context manager wrapping `content`.
    """
    calls = {"n": 0}

    def factory(*args, **kwargs) -> _FakeFileCM:
        calls["n"] += 1
        if calls["n"] <= fails:
            raise ConnectionError(f"simulated transient (call {calls['n']})")
        return _FakeFileCM(content)

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


def test_csv_dataset_retries_on_transient_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    from inspect_ai.dataset import csv_dataset

    # _call_with_dataset_retry constructs a tenacity Retrying with
    # `sleep=tenacity.nap.sleep` at call time, so patching the module
    # attribute directly is sufficient to short-circuit the wait.
    monkeypatch.setattr("tenacity.nap.sleep", lambda _: None)
    factory = _make_flaky_file_factory(fails=2, content=_CSV_CONTENT)

    with patch("inspect_ai.dataset._sources.csv.file", side_effect=factory):
        dataset = csv_dataset("https://example.com/data.csv")

    assert len(dataset) == 2
    assert dataset[0].input == "hello"
    assert dataset[0].target == "world"
    assert factory.calls["n"] == 3  # 2 transient + 1 success


def test_csv_dataset_does_not_retry_when_disabled(monkeypatch: pytest.MonkeyPatch):
    from inspect_ai.dataset import csv_dataset

    factory = _make_flaky_file_factory(fails=2, content=_CSV_CONTENT)

    with patch("inspect_ai.dataset._sources.csv.file", side_effect=factory):
        with pytest.raises(ConnectionError):
            csv_dataset("https://example.com/data.csv", retry=False)

    # retry=False → single attempt only.
    assert factory.calls["n"] == 1


def test_csv_dataset_does_not_retry_non_transient(monkeypatch: pytest.MonkeyPatch):
    from inspect_ai.dataset import csv_dataset

    calls = {"n": 0}

    def always_missing(*args, **kwargs) -> _FakeFileCM:
        calls["n"] += 1
        raise FileNotFoundError("/tmp/does/not/exist")

    with patch("inspect_ai.dataset._sources.csv.file", side_effect=always_missing):
        with pytest.raises(FileNotFoundError):
            csv_dataset("/tmp/does/not/exist")

    # FileNotFoundError is non-transient → single attempt even with retry=True.
    assert calls["n"] == 1


def test_json_dataset_retries_on_transient_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    from inspect_ai.dataset import json_dataset

    # _call_with_dataset_retry constructs a tenacity Retrying with
    # `sleep=tenacity.nap.sleep` at call time, so patching the module
    # attribute directly is sufficient to short-circuit the wait.
    monkeypatch.setattr("tenacity.nap.sleep", lambda _: None)
    factory = _make_flaky_file_factory(fails=2, content=_JSON_CONTENT)

    with patch("inspect_ai.dataset._sources.json.file", side_effect=factory):
        dataset = json_dataset("https://example.com/data.json")

    assert len(dataset) == 2
    assert dataset[0].input == "hello"
    assert dataset[1].target == "bar"
    assert factory.calls["n"] == 3


def test_json_dataset_does_not_retry_when_disabled():
    from inspect_ai.dataset import json_dataset

    factory = _make_flaky_file_factory(fails=2, content=_JSON_CONTENT)

    with patch("inspect_ai.dataset._sources.json.file", side_effect=factory):
        with pytest.raises(ConnectionError):
            json_dataset("https://example.com/data.json", retry=False)

    assert factory.calls["n"] == 1
