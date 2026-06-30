"""Apprise-backed notifications for human-in-the-loop interactions."""

from __future__ import annotations

import contextlib
import functools
import logging
import os
from collections.abc import Iterator
from contextvars import ContextVar
from typing import TYPE_CHECKING

import anyio

from inspect_ai._util.error import PrerequisiteError, pip_dependency_error

logger = logging.getLogger(__name__)

# Bounded wait for an Apprise backend (HTTP webhook, SMTP, etc.) to accept
# the notification. Shorter than any plausible human reaction time so the
# operator-facing prompt never waits noticeably on a stuck notifier.
NOTIFY_TIMEOUT_SECONDS = 5.0

if TYPE_CHECKING:
    import apprise  # type: ignore[import-not-found,import-untyped]


_active_apprise: ContextVar["apprise.Apprise | None"] = ContextVar(
    "_active_apprise", default=None
)


def active_apprise() -> "apprise.Apprise | None":
    """The Apprise instance installed for the current eval scope, or `None`."""
    return _active_apprise.get()


def init_apprise(instance: "apprise.Apprise | None") -> None:
    """Install an Apprise instance for the current eval scope.

    Directly sets the backing ContextVar so nested scopes inherit the
    installation; use `apprise_scope()` for narrower (scoped, unwinding)
    overrides — primarily in tests.
    """
    _active_apprise.set(instance)


@contextlib.contextmanager
def apprise_scope(instance: "apprise.Apprise | None") -> Iterator[None]:
    """Scoped override of the active Apprise instance (mainly for tests)."""
    token = _active_apprise.set(instance)
    try:
        yield
    finally:
        _active_apprise.reset(token)


NOTIFICATION_ENV_VAR = "INSPECT_EVAL_NOTIFICATION"


def build_apprise(config: bool | str | None) -> "apprise.Apprise | None":
    """Build an `Apprise` instance for the eval's notification config.

    Notification URLs frequently carry secrets (Slack tokens, Twilio auth
    tokens, generic webhook bearer tokens). To keep those secrets out of
    source code, shell history, process listings, and eval logs, this
    builder accepts only references — never URL values:

    Args:
        config:
            - `True`: read URL(s) from the `INSPECT_EVAL_NOTIFICATION` env
              var. The env-var value can be a single Apprise URL, a
              comma-separated list of URLs, or a path to an Apprise
              YAML/text config file. Unset/empty env var raises.
            - `str`: must be a path to an existing Apprise YAML/text config
              file. Strings that aren't existing files (including URLs)
              are rejected with a hint to use the env var instead.
            - `None`: notifications disabled.

    Returns:
        Configured `Apprise` instance, or `None` when `config` is `None`.

    Raises:
        PrerequisiteError: when `apprise` is not installed, when `True` is
            passed but the env var is unset/empty, or when a non-file
            string is passed.
    """
    if config is None or config is False:
        return None

    if config is True:
        raw = os.environ.get(NOTIFICATION_ENV_VAR, "").strip()
        if not raw:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: notification=True requires the "
                f"[bold]{NOTIFICATION_ENV_VAR}[/bold] environment variable "
                "to be set (a single Apprise URL, a comma-separated list of "
                "URLs, or a path to an Apprise config file)."
            )
        try:
            import apprise  # type: ignore[import-not-found,import-untyped]
        except ImportError:
            raise pip_dependency_error("notifications", ["apprise"]) from None

        instance = apprise.Apprise()
        if os.path.isfile(raw):
            cfg = apprise.AppriseConfig()
            cfg.add(raw)
            instance.add(cfg)
        else:
            urls = [u.strip() for u in raw.split(",") if u.strip()]
            for url in urls:
                instance.add(url)
        return instance

    # `config` is a string — must be a path to an existing file.
    if not os.path.isfile(config):
        raise PrerequisiteError(
            f"[bold]ERROR[/bold]: notification={config!r} is not an existing "
            "file. Notification URLs must be supplied via the "
            f"[bold]{NOTIFICATION_ENV_VAR}[/bold] environment variable "
            "(with `notification=True`) so that they never end up in source "
            "code, shell history, or eval logs. If you intended a config "
            "file, check the path."
        )

    try:
        import apprise  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        raise pip_dependency_error("notifications", ["apprise"]) from None

    instance = apprise.Apprise()
    cfg = apprise.AppriseConfig()
    cfg.add(config)
    instance.add(cfg)
    return instance


async def notify(message: str, title: str | None = None) -> None:
    """Send a notification via the active Apprise instance (best-effort).

    No-op when no Apprise instance is installed for the current eval scope.
    When `title` is omitted, the title and body are composed from the active
    sample context: title becomes `Inspect Agent: <task>` and the body starts
    with a `sample: <sample_id>/<epoch>` line followed by the message.
    Outside an active sample, the title is just `Inspect Agent` and the body
    is the unmodified message.

    Best-effort by contract: a misbehaving Apprise backend (slow HTTP, network
    blackhole, plugin exception) must not delay or break the actual operator
    prompt that follows this call. Dispatch is bounded by
    `NOTIFY_TIMEOUT_SECONDS`; any exception is logged at warning and swallowed.

    Apprise's sync API is dispatched on a worker thread so this works under
    both asyncio and trio backends.

    Args:
        message: The notification body.
        title: Optional title. Pass `None` to use the default `Inspect Agent`
            framing with sample context prepended to the body.
    """
    instance = active_apprise()
    if instance is None:
        return

    if title is None:
        title, message = _default_title_and_body(message)

    try:
        with anyio.move_on_after(NOTIFY_TIMEOUT_SECONDS):
            await anyio.to_thread.run_sync(
                functools.partial(instance.notify, body=message, title=title),
                abandon_on_cancel=True,
            )
    except Exception as exc:
        logger.warning("Notification dispatch failed: %s", exc)


def _default_title_and_body(message: str) -> tuple[str, str]:
    # Deferred import to avoid pulling log machinery at module-load time.
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return "Inspect Agent", message
    sid = active.sample.id if active.sample.id is not None else "?"
    return f"Inspect Agent: {active.task}", f"sample: {sid}/{active.epoch}\n\n{message}"
