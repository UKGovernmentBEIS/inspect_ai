"""OpenTelemetry integration for distributed tracing."""

from ._otel import (
    configure_opentelemetry,
    get_otel_trace_context,
    get_tracer,
    is_otel_enabled,
    otel_trace_context,
)

__all__ = [
    "configure_opentelemetry",
    "get_tracer",
    "is_otel_enabled",
    "otel_trace_context",
    "get_otel_trace_context",
]
