"""OpenTelemetry integration implementation."""

import contextlib
import os
from contextvars import ContextVar
from logging import getLogger
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from opentelemetry.context import Context
    from opentelemetry.trace import Tracer

logger = getLogger(__name__)


def configure_opentelemetry(
    *,
    enabled: bool = True,
    service_name: str | None = None,
    exporter: str | None = None,
    endpoint: str | None = None,
    tracer: "Tracer | None" = None,
) -> None:
    """Configure OpenTelemetry integration for distributed tracing.

    When enabled, inspect_ai spans will create active OpenTelemetry spans that
    propagate trace context to external services via HTTP headers. This enables
    end-to-end distributed tracing across inspect_ai evaluations and external
    APIs (model providers, tools, etc.).

    Args:
        enabled: Enable or disable OpenTelemetry integration.
        service_name: Service name for traces. Defaults to "inspect_ai" or
            the value of OTEL_SERVICE_NAME environment variable.
        exporter: Exporter type. Supported values:
            - "console": Console output (for debugging)
            - "otlp": OTLP gRPC exporter (default)
            - "jaeger": Jaeger exporter
            If None, uses "otlp".
        endpoint: Exporter endpoint URL. Defaults to "http://localhost:4317"
            or the value of OTEL_EXPORTER_OTLP_ENDPOINT environment variable.
        tracer: Custom OpenTelemetry Tracer instance. If provided, overrides
            service_name, exporter, and endpoint parameters.

    Examples:
        Basic OTLP export to localhost:
        ```python
        from inspect_ai.telemetry import configure_opentelemetry

        configure_opentelemetry(
            enabled=True,
            service_name="my-evaluation",
        )
        ```

        Export to custom Jaeger instance:
        ```python
        configure_opentelemetry(
            enabled=True,
            service_name="my-evaluation",
            exporter="jaeger",
        )
        ```

        Use custom tracer:
        ```python
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        # ... configure provider ...

        configure_opentelemetry(
            enabled=True,
            tracer=provider.get_tracer("inspect_ai"),
        )
        ```

        Configure via environment variables:
        ```bash
        export OTEL_SERVICE_NAME="my-evaluation"
        export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317"
        ```
        ```python
        # Auto-detects from environment
        configure_opentelemetry(enabled=True)
        ```
    """
    if not enabled:
        _otel_enabled.set(False)
        _otel_tracer.set(None)
        logger.info("OpenTelemetry integration disabled")
        return

    # Auto-configure from environment variables if not provided
    if service_name is None:
        service_name = os.getenv("OTEL_SERVICE_NAME", "inspect_ai")

    if endpoint is None:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    if exporter is None:
        exporter = "otlp"

    # Use provided tracer or create one
    if tracer is None:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Create resource with service name
            resource = Resource(attributes={SERVICE_NAME: service_name})

            # Create provider with resource
            provider = TracerProvider(resource=resource)

            # Configure exporter based on type
            if exporter == "console":
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                processor = BatchSpanProcessor(ConsoleSpanExporter())
                provider.add_span_processor(processor)
                logger.info(
                    f"OpenTelemetry configured with console exporter (service: {service_name})"
                )

            elif exporter == "otlp":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
                    OTLPSpanExporter,
                )

                otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
                processor = BatchSpanProcessor(otlp_exporter)
                provider.add_span_processor(processor)
                logger.info(
                    f"OpenTelemetry configured with OTLP exporter (service: {service_name}, endpoint: {endpoint})"
                )

            elif exporter == "jaeger":
                from opentelemetry.exporter.jaeger.thrift import (  # type: ignore[import-not-found]
                    JaegerExporter,
                )

                jaeger_exporter = JaegerExporter(
                    agent_host_name="localhost",
                    agent_port=6831,
                )
                processor = BatchSpanProcessor(jaeger_exporter)
                provider.add_span_processor(processor)
                logger.info(
                    f"OpenTelemetry configured with Jaeger exporter (service: {service_name})"
                )

            else:
                raise ValueError(
                    f"Unsupported exporter type: {exporter}. "
                    f"Supported types: console, otlp, jaeger"
                )

            # Set as global provider
            trace.set_tracer_provider(provider)
            tracer = provider.get_tracer(service_name)

        except ImportError as e:
            logger.error(
                f"Failed to import OpenTelemetry dependencies: {e}. "
                f"Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
            )
            _otel_enabled.set(False)
            _otel_tracer.set(None)
            return
        except Exception as e:
            logger.error(f"Failed to configure OpenTelemetry: {e}")
            _otel_enabled.set(False)
            _otel_tracer.set(None)
            return

    # Store configuration in context variables
    _otel_enabled.set(True)
    _otel_tracer.set(tracer)
    logger.info(f"OpenTelemetry integration enabled (service: {service_name})")


def get_tracer() -> "Tracer | None":
    """Get the currently configured OpenTelemetry tracer.

    Returns:
        The configured Tracer instance, or None if OpenTelemetry
        integration is not enabled.
    """
    return _otel_tracer.get()


def is_otel_enabled() -> bool:
    """Check if OpenTelemetry integration is enabled.

    Returns:
        True if OpenTelemetry integration is enabled, False otherwise.
    """
    return _otel_enabled.get()


# Context variables for OpenTelemetry configuration
_otel_enabled: ContextVar[bool] = ContextVar("_otel_enabled", default=False)
_otel_tracer: ContextVar["Tracer | None"] = ContextVar("_otel_tracer", default=None)
_otel_trace_context: ContextVar["Context | None"] = ContextVar(
    "_otel_trace_context", default=None
)


@contextlib.asynccontextmanager
async def otel_trace_context(name: str) -> AsyncIterator[None]:
    """Establish a root OpenTelemetry trace context.

    This creates a root span that establishes a trace ID. All subsequent
    spans created within this context will share the same trace ID,
    creating a unified trace in observability tools like Jaeger.

    Typically used to wrap sample execution so that all spans within a
    sample (solvers, scorers, tools, etc.) appear under one trace.

    Args:
        name: Name for the root span (e.g., "sample-1", "evaluation").

    Example:
        ```python
        from inspect_ai.telemetry import otel_trace_context
        from inspect_ai.util import span

        async with otel_trace_context("sample-1"):
            # All spans here share the same trace_id
            async with span("solver"):
                async with span("tool_call"):
                    pass
        ```
    """
    if not _otel_enabled.get():
        yield
        return

    otel_tracer = _otel_tracer.get()
    if not otel_tracer:
        yield
        return

    try:
        from opentelemetry import context, trace
        from opentelemetry.trace import Status, StatusCode

        # Start a root span that establishes the trace context
        root_span = otel_tracer.start_span(name)
        root_span.set_attribute("inspect.root", True)
        root_span.set_attribute("inspect.trace_name", name)

        # Set this span as the current context
        otel_context = trace.set_span_in_context(root_span)
        token = context.attach(otel_context)

        # Store in context variable for child spans to access
        ctx_token = _otel_trace_context.set(otel_context)

        exception_occurred = False
        try:
            yield
        except Exception as ex:
            # Record exception on the root span
            exception_occurred = True
            try:
                root_span.record_exception(ex)
                root_span.set_status(Status(StatusCode.ERROR, description=str(ex)))
            except Exception as e:
                logger.debug(f"Failed to record exception on root span: {e}")
            raise
        finally:
            # Set status to OK if no exception occurred
            if not exception_occurred:
                try:
                    root_span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.debug(f"Failed to set span status: {e}")

            # End the root span
            root_span.end()

            # Restore previous context
            _otel_trace_context.reset(ctx_token)
            context.detach(token)

    except Exception as e:
        logger.debug(f"Failed to establish OTel trace context: {e}")
        yield


def get_otel_trace_context() -> "Context | None":
    """Get the current OpenTelemetry trace context.

    Returns:
        The active trace context, or None if not established.
    """
    return _otel_trace_context.get()
