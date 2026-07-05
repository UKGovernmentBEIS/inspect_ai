"""Host-side tests for agent-bridge provider-error forwarding.

Covers the pieces that let the sandbox model proxy forward a provider error
instead of crashing: the `ModelGenerateError` wrapper (which preserves the
provider HTTP status), the `status_code_of` / `provider_error_payload`
extractors, and the `service.py` wrapper that turns an exception into a
`PROVIDER_ERROR_KEY` result.
"""

from __future__ import annotations

from typing import Any

import pytest

from inspect_ai._util.http import status_code_of
from inspect_ai._util.registry import _registry
from inspect_ai.agent._bridge._errors import (
    PROVIDER_ERROR_KEY,
    provider_error_payload,
)
from inspect_ai.agent._bridge.sandbox import service as bridge_service
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._model import ModelAPI, ModelGenerateError
from inspect_ai.model._registry import modelapi


class _ProviderError(Exception):
    """Stand-in for an SDK exception exposing a `.status_code`."""

    def __init__(self, message: str, status_code: int | None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------- status_code_of ----------


def test_status_code_of_reads_status_code_attr() -> None:
    assert status_code_of(_ProviderError("rate limited", 429)) == 429


def test_status_code_of_reads_code_attr() -> None:
    # google-genai APIError exposes the HTTP status as `.code`
    class _GoogleError(Exception):
        code = 503

    assert status_code_of(_GoogleError()) == 503


def test_status_code_of_reads_model_generate_error() -> None:
    ex = ModelGenerateError("debug", status_code=400)
    assert status_code_of(ex) == 400


def test_status_code_of_returns_none_when_absent() -> None:
    assert status_code_of(ValueError("boom")) is None
    # non-int attrs are ignored
    assert status_code_of(_ProviderError("x", 0)) == 0  # falsy-but-valid status


# ---------- ModelGenerateError ----------


def test_model_generate_error_is_runtime_error_and_carries_fields() -> None:
    ex = ModelGenerateError(
        "verbose debug message",
        status_code=400,
        provider_message="Could not process image",
    )
    assert isinstance(ex, RuntimeError)
    assert ex.status_code == 400
    assert ex.provider_message == "Could not process image"
    # the human-readable message stays the verbose debug string
    assert str(ex) == "verbose debug message"


# ---------- provider_error_payload ----------


def test_provider_error_payload_prefers_provider_message() -> None:
    ex = ModelGenerateError(
        "verbose debug", status_code=400, provider_message="clean provider message"
    )
    assert provider_error_payload(ex) == {
        "status": 400,
        "message": "clean provider message",
    }


def test_provider_error_payload_raw_sdk_exception() -> None:
    assert provider_error_payload(_ProviderError("rate limited", 429)) == {
        "status": 429,
        "message": "rate limited",
    }


def test_provider_error_payload_bare_exception() -> None:
    assert provider_error_payload(ValueError("boom")) == {
        "status": None,
        "message": "boom",
    }


# ---------- _forward_provider_errors (service.py) ----------


async def test_forward_provider_errors_passes_success_through() -> None:
    async def ok(json_data: dict[str, Any]) -> dict[str, Any]:
        return {"id": "x", "choices": []}

    wrapped = _forward_provider_errors(ok)
    assert await wrapped({}) == {"id": "x", "choices": []}


async def test_forward_provider_errors_returns_marker_on_exception() -> None:
    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise ModelGenerateError(
            "debug", status_code=503, provider_message="overloaded"
        )

    wrapped = _forward_provider_errors(boom)
    result = await wrapped({})
    assert result == {PROVIDER_ERROR_KEY: {"status": 503, "message": "overloaded"}}


async def test_forward_provider_errors_warns_on_non_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error with no recoverable status (likely our own bug) is logged."""
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("our own translation bug")

    result = await _forward_provider_errors(boom)({})
    assert result == {
        PROVIDER_ERROR_KEY: {"status": None, "message": "our own translation bug"}
    }
    assert len(warnings) == 1


async def test_forward_provider_errors_no_warn_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine provider error (carries a status) is forwarded without warning."""
    warnings: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        bridge_service.logger, "warning", lambda *a, **k: warnings.append((a, k))
    )

    async def boom(json_data: dict[str, Any]) -> dict[str, Any]:
        raise ModelGenerateError("debug", status_code=503, provider_message="x")

    result = await _forward_provider_errors(boom)({})
    assert result == {PROVIDER_ERROR_KEY: {"status": 503, "message": "x"}}
    assert warnings == []


# ---------- _model.py wrap path (end to end) ----------


class _ReturnsExceptionAPI(ModelAPI):
    """ModelAPI whose generate *returns* an exception (the wrapped `_model.py` path)."""

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
        self._status_code = model_args.get("status_code")
        self._message = model_args.get("message", "error")

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        return _ProviderError(self._message, self._status_code), None


async def test_model_generate_wraps_returned_exception_with_status() -> None:
    @modelapi(name="returnsexc")
    def returnsexc() -> type[ModelAPI]:
        return _ReturnsExceptionAPI

    try:
        model = get_model(
            "returnsexc/x", status_code=400, message="Could not process image"
        )
        with pytest.raises(ModelGenerateError) as excinfo:
            await model.generate(input="hello")
        assert excinfo.value.status_code == 400
        assert "Could not process image" in (excinfo.value.provider_message or "")
        # the original provider exception is chained as the cause
        assert excinfo.value.__cause__ is not None
    finally:
        del _registry["modelapi:returnsexc"]
