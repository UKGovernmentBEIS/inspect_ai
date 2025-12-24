import contextlib
import inspect
from contextvars import ContextVar
from logging import getLogger
from typing import Any, AsyncIterator
from uuid import uuid4

logger = getLogger(__name__)


@contextlib.asynccontextmanager
async def span(name: str, *, type: str | None = None) -> AsyncIterator[None]:
    """Context manager for establishing a transcript span.

    When OpenTelemetry integration is enabled (via `configure_opentelemetry()`),
    this also creates an active OpenTelemetry span for distributed tracing. The
    OpenTelemetry span will propagate trace context to external services via
    HTTP headers.

    Args:
        name (str): Step name.
        type (str | None): Optional span type.
    """
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
    from inspect_ai.log._transcript import (
        track_store_changes,
        transcript,
    )

    # generate inspect_ai span id
    id = uuid4().hex

    # capture parent id
    parent_id = _current_span_id.get()

    # set new current span (reset at the end)
    token = _current_span_id.set(id)

    # optionally create active OpenTelemetry span
    otel_span = None
    otel_context_token = None
    if _get_otel_enabled():
        otel_tracer = _get_otel_tracer()
        if otel_tracer:
            try:
                # import OpenTelemetry only when needed (optional dependency)
                from opentelemetry import context, trace

                # start span (will inherit trace_id from parent context if set)
                otel_span = otel_tracer.start_span(name)

                # link inspect_ai span id to OpenTelemetry span
                otel_span.set_attribute("inspect.span_id", id)
                otel_span.set_attribute("inspect.type", type or name)
                if parent_id:
                    otel_span.set_attribute("inspect.parent_id", parent_id)

                # make this span active in OpenTelemetry context
                # (enables automatic trace propagation in HTTP requests)
                # Note: If we're already within an otel_trace_context, this span
                # will automatically inherit the trace_id and appear as a child
                otel_context_token = context.attach(
                    trace.set_span_in_context(otel_span)
                )

            except Exception as e:
                logger.debug(f"Failed to create OpenTelemetry span: {e}")

    # run the span
    exception_occurred = False
    try:
        # emit inspect_ai span begin event
        transcript()._event(
            SpanBeginEvent(
                id=id,
                parent_id=parent_id,
                type=type or name,
                name=name,
            )
        )

        # run span w/ store change events
        with track_store_changes():
            try:
                yield
            except Exception as ex:
                # record exception on OpenTelemetry span
                exception_occurred = True
                if otel_span:
                    try:
                        from opentelemetry.trace import Status, StatusCode

                        # record the exception with full details
                        otel_span.record_exception(ex)

                        # set span status to ERROR
                        otel_span.set_status(
                            Status(StatusCode.ERROR, description=str(ex))
                        )
                    except Exception as e:
                        logger.debug(f"Failed to record exception on OTel span: {e}")

                # re-raise the exception to maintain normal flow
                raise

    finally:
        # emit inspect_ai span end event
        transcript()._event(SpanEndEvent(id=id))

        # end OpenTelemetry span if created
        if otel_span:
            try:
                # if no exception occurred, mark span as OK
                if not exception_occurred:
                    from opentelemetry.trace import Status, StatusCode

                    otel_span.set_status(Status(StatusCode.OK))

                otel_span.end()
            except Exception as e:
                logger.debug(f"Failed to end OpenTelemetry span: {e}")

        # detach OpenTelemetry context
        if otel_context_token is not None:
            try:
                from opentelemetry import context

                context.detach(otel_context_token)
            except Exception as e:
                logger.debug(f"Failed to detach OpenTelemetry context: {e}")

        # reset inspect_ai span context
        try:
            _current_span_id.reset(token)
        except ValueError:
            frame = inspect.stack()[1]
            caller = f"{frame.function}() [{frame.filename}:{frame.lineno}]"
            logger.warning(f"Exiting span created in another context: {caller}")


def current_span_id() -> str | None:
    """Get the current inspect_ai span ID.

    Returns:
        The current span ID, or None if not within a span.
    """
    return _current_span_id.get()


# Context variable for inspect_ai span tracking
_current_span_id: ContextVar[str | None] = ContextVar("_current_span_id", default=None)


def _get_otel_enabled() -> bool:
    """Check if OpenTelemetry integration is enabled."""
    try:
        from inspect_ai.telemetry._otel import _otel_enabled

        return _otel_enabled.get()
    except ImportError:
        return False


def _get_otel_tracer() -> Any:
    """Get the configured OpenTelemetry tracer."""
    try:
        from inspect_ai.telemetry._otel import _otel_tracer

        return _otel_tracer.get()
    except ImportError:
        return None
