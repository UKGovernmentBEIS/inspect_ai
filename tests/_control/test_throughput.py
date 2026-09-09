"""Tests for the ``GET /models/throughput`` control endpoint.

Envelope shape, the empty-registry response, FastAPI type validation of
``window`` (malformed → 422 — strict unknown-param rejection deliberately
doesn't apply to GETs), and server-side clamping to the bucket horizon.
See design/model-throughput.md.
"""

import httpx
import pytest

from inspect_ai.model._model_output import ModelUsage
from inspect_ai.model._throughput import (
    HORIZON_SECONDS,
    init_model_throughput,
    record_generate,
    record_retry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    init_model_throughput()
    yield
    init_model_throughput()


def _app():
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_app())
    return httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def test_throughput_route_empty_registry() -> None:
    async with _client() as client:
        got = await client.get("/models/throughput")
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["models"] == []
        assert body["window_seconds"] == 60
        assert body["as_of"]


async def test_throughput_route_reports_models() -> None:
    record_generate(
        "test/m", ModelUsage(input_tokens=10, output_tokens=20, total_tokens=30)
    )
    record_retry("test/m", "rate_limit")
    async with _client() as client:
        got = await client.get("/models/throughput", params={"window": 30})
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["window_seconds"] == 30
        (row,) = body["models"]
        assert row["model"] == "test/m"
        assert 0 < row["window_seconds"] <= body["window_seconds"]
        assert row["output_tokens_per_second"] > 0
        assert row["retry_waits_active"] == 0
        assert row["cumulative"]["requests"] == 1
        assert row["cumulative"]["output_tokens"] == 20
        assert row["cumulative"]["retries"] == {"rate_limit": 1, "transient": 0}


async def test_throughput_route_window_validation_and_clamp() -> None:
    async with _client() as client:
        # malformed window → FastAPI type validation (not a silent default)
        bad = await client.get("/models/throughput", params={"window": "abc"})
        assert bad.status_code == 422
        # oversized window clamps to the bucket horizon
        clamped = await client.get("/models/throughput", params={"window": 999999})
        assert clamped.status_code == 200
        assert clamped.json()["window_seconds"] == HORIZON_SECONDS
        # GETs stay tolerant of unknown params (unlike strict mutations)
        tolerant = await client.get("/models/throughput", params={"zeta": 1})
        assert tolerant.status_code == 200
