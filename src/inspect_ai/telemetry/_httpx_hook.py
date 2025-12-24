"""HttpX hooks for OpenTelemetry trace context propagation."""

from logging import getLogger

import httpx

logger = getLogger(__name__)


class OTelHttpxHook:
    """HttpX event hook for injecting OpenTelemetry trace context into HTTP requests.

    This hook automatically injects W3C Trace Context headers (traceparent, tracestate)
    into outgoing HTTP requests when an active OpenTelemetry span exists. This enables
    distributed tracing across service boundaries.

    The hook is registered on httpx.AsyncClient's request event and will be called
    for every outgoing request.

    Example:
        ```python
        import httpx
        from inspect_ai.telemetry import configure_opentelemetry
        from inspect_ai.telemetry._httpx_hook import OTelHttpxHook

        # Configure OTel
        configure_opentelemetry(enabled=True)

        # Create client and register hook
        client = httpx.AsyncClient()
        OTelHttpxHook(client)

        # Requests will now include trace context headers
        await client.get("https://api.example.com")
        ```
    """

    def __init__(self, client: httpx.AsyncClient):
        """Initialize the hook and register it with the httpx client.

        Args:
            client: The httpx.AsyncClient to attach the hook to.
        """
        # Register our hook alongside any existing hooks
        client.event_hooks["request"].append(self.request_hook)
        logger.debug("Registered OTel httpx hook for trace context propagation")

    async def request_hook(self, request: httpx.Request) -> None:
        """Inject OpenTelemetry trace context into HTTP request headers.

        This hook is called automatically by httpx for each request. It checks
        if there's an active OpenTelemetry span, and if so, injects the trace
        context into the request headers using W3C Trace Context format.

        Args:
            request: The httpx.Request being prepared for sending.
        """
        try:
            from opentelemetry import trace
            from opentelemetry.propagate import inject

            # Get current active OpenTelemetry span
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                # Inject W3C Trace Context headers into request
                # This adds traceparent (required) and tracestate (optional, vendor-specific)
                carrier = dict(request.headers)
                inject(carrier)

                # Update request headers with injected trace context
                for key, value in carrier.items():
                    if key.lower() not in request.headers:
                        request.headers[key] = value

                logger.debug(
                    f"Injected OTel trace context into request: {request.method} {request.url}"
                )

        except ImportError:
            # OpenTelemetry not installed, skip (logged once at module level)
            pass
        except Exception as e:
            # Don't fail requests due to tracing issues
            logger.debug(f"Failed to inject OpenTelemetry context: {e}")


def register_otel_hook(client: httpx.AsyncClient) -> None:
    """Register OpenTelemetry trace propagation hook on an httpx client.

    This is a convenience function that creates and registers an OTelHttpxHook
    on the given client. It's safe to call even if OpenTelemetry is not enabled
    or not installed - the hook will simply be a no-op in those cases.

    Args:
        client: The httpx.AsyncClient to attach the hook to.

    Example:
        ```python
        import httpx
        from inspect_ai.telemetry._httpx_hook import register_otel_hook

        client = httpx.AsyncClient()
        register_otel_hook(client)
        ```
    """
    OTelHttpxHook(client)
