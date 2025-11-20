"""Tests for OpenTelemetry integration."""

import pytest

from inspect_ai.telemetry import configure_opentelemetry, get_tracer, is_otel_enabled


def test_telemetry_disabled_by_default() -> None:
    """Test that OpenTelemetry is disabled by default."""
    assert not is_otel_enabled()
    assert get_tracer() is None


def test_telemetry_can_be_disabled() -> None:
    """Test that OpenTelemetry can be explicitly disabled."""
    configure_opentelemetry(enabled=False)
    assert not is_otel_enabled()
    assert get_tracer() is None


@pytest.mark.skipif(
    True,
    reason="OpenTelemetry dependencies not required for core tests",
)
def test_telemetry_configuration() -> None:
    """Test OpenTelemetry configuration with console exporter."""
    configure_opentelemetry(
        enabled=True,
        service_name="test-service",
        exporter="console",
    )

    assert is_otel_enabled()
    tracer = get_tracer()
    assert tracer is not None
