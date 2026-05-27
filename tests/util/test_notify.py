"""Tests for `inspect_ai.util.notify` and the Apprise plumbing."""

import time
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import notify
from inspect_ai.util._notify import (
    NOTIFY_TIMEOUT_SECONDS,
    active_apprise,
    apprise_scope,
    build_apprise,
)

# -- notify() is a no-op when no Apprise instance is installed ------------


async def test_notify_no_op_without_apprise_scope() -> None:
    """notify() returns silently when no Apprise instance is active."""
    # Default scope (no apprise_scope wrapper) has no Apprise installed.
    with apprise_scope(None):
        # Should complete without raising even if `apprise` is uninstalled.
        await notify("hello")


# -- notify() dispatches via the installed Apprise instance ---------------


async def test_notify_dispatches_to_apprise_when_active() -> None:
    fake = MagicMock()
    fake.notify = MagicMock(return_value=True)

    with apprise_scope(fake):
        await notify("hello", title="Greeting")

    fake.notify.assert_called_once()
    kwargs = fake.notify.call_args.kwargs
    assert kwargs.get("body") == "hello"
    assert kwargs.get("title") == "Greeting"


async def test_notify_defaults_title_outside_sample_scope() -> None:
    """Outside an active sample, default title falls back to `Inspect Agent`."""
    fake = MagicMock()
    fake.notify = MagicMock(return_value=True)

    with apprise_scope(fake):
        await notify("hello")

    kwargs = fake.notify.call_args.kwargs
    assert kwargs.get("title") == "Inspect Agent"
    # No sample → body is the unmodified message.
    assert kwargs.get("body") == "hello"


async def test_notify_default_title_uses_sample_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside an active sample: title names the task, body appends sample/epoch."""
    fake_active = MagicMock()
    fake_active.task = "my_task"
    fake_active.sample = MagicMock()
    fake_active.sample.id = "s42"
    fake_active.epoch = 3

    from inspect_ai.log import _samples as samples_module

    monkeypatch.setattr(samples_module, "sample_active", lambda: fake_active)

    fake_apprise = MagicMock()
    fake_apprise.notify = MagicMock(return_value=True)
    with apprise_scope(fake_apprise):
        await notify("hello")

    kwargs = fake_apprise.notify.call_args.kwargs
    assert kwargs.get("title") == "Inspect Agent: my_task"
    # Body starts with the `sample:` triage line; the message follows.
    assert kwargs.get("body") == "sample: s42/3\n\nhello"


# -- build_apprise resolution --------------------------------------------


def test_build_apprise_none_returns_none() -> None:
    assert build_apprise(None) is None


def test_build_apprise_false_returns_none() -> None:
    assert build_apprise(False) is None


def test_build_apprise_true_without_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notification=True with INSPECT_EVAL_NOTIFICATION unset raises a clear error."""
    monkeypatch.delenv("INSPECT_EVAL_NOTIFICATION", raising=False)

    with pytest.raises(PrerequisiteError) as exc_info:
        build_apprise(True)

    msg = str(exc_info.value.message)
    assert "INSPECT_EVAL_NOTIFICATION" in msg


def test_build_apprise_true_with_empty_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty/whitespace env var is treated as unset."""
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", "   ")

    with pytest.raises(PrerequisiteError) as exc_info:
        build_apprise(True)

    msg = str(exc_info.value.message)
    assert "INSPECT_EVAL_NOTIFICATION" in msg


def test_build_apprise_missing_import_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """When apprise is not installed, build_apprise raises a clear error."""
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", "slack://...")

    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "apprise":
            raise ImportError("No module named 'apprise'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(PrerequisiteError) as exc_info:
        build_apprise(True)

    msg = str(exc_info.value.message)
    assert "apprise" in msg.lower()


def test_build_apprise_true_env_var_single_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notification=True with a single URL in the env var routes through as a URL."""
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", "slack://tok/Bot/#chan")
    fake_module = MagicMock()
    fake_instance = MagicMock()
    fake_module.Apprise = MagicMock(return_value=fake_instance)
    fake_module.AppriseConfig = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "apprise", fake_module)

    result = build_apprise(True)

    assert result is fake_instance
    fake_instance.add.assert_called_once_with("slack://tok/Bot/#chan")
    fake_module.AppriseConfig.assert_not_called()


def test_build_apprise_true_env_var_comma_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notification=True with a comma-separated list adds each URL."""
    monkeypatch.setenv(
        "INSPECT_EVAL_NOTIFICATION", "slack://abc, macosx:// , discord://xyz"
    )
    fake_module = MagicMock()
    fake_instance = MagicMock()
    fake_module.Apprise = MagicMock(return_value=fake_instance)
    monkeypatch.setitem(__import__("sys").modules, "apprise", fake_module)

    result = build_apprise(True)

    assert result is fake_instance
    add_calls = [c.args[0] for c in fake_instance.add.call_args_list]
    assert add_calls == ["slack://abc", "macosx://", "discord://xyz"]


def test_build_apprise_true_env_var_pointing_at_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """When env var is a path to an existing file, build via AppriseConfig."""
    cfg_path = tmp_path / "apprise.yml"
    cfg_path.write_text("urls:\n  - macosx://\n")
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", str(cfg_path))

    fake_module = MagicMock()
    fake_instance = MagicMock()
    fake_config = MagicMock()
    fake_module.Apprise = MagicMock(return_value=fake_instance)
    fake_module.AppriseConfig = MagicMock(return_value=fake_config)
    monkeypatch.setitem(__import__("sys").modules, "apprise", fake_module)

    result = build_apprise(True)

    assert result is fake_instance
    fake_config.add.assert_called_once_with(str(cfg_path))
    fake_instance.add.assert_called_once_with(fake_config)


def test_build_apprise_path_string_uses_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A string pointing at an existing file is treated as an Apprise config file."""
    fake_module = MagicMock()
    fake_instance = MagicMock()
    fake_config = MagicMock()
    fake_module.Apprise = MagicMock(return_value=fake_instance)
    fake_module.AppriseConfig = MagicMock(return_value=fake_config)
    monkeypatch.setitem(__import__("sys").modules, "apprise", fake_module)

    cfg_path = tmp_path / "apprise.yml"
    cfg_path.write_text("urls:\n  - macosx://\n")

    result = build_apprise(str(cfg_path))

    assert result is fake_instance
    fake_config.add.assert_called_once_with(str(cfg_path))
    fake_instance.add.assert_called_once_with(fake_config)


def test_build_apprise_non_file_string_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A string that's not an existing file is rejected (no URL leakage via API)."""
    with pytest.raises(PrerequisiteError) as exc_info:
        build_apprise("slack://tok/Bot/#chan")

    msg = str(exc_info.value.message)
    assert "INSPECT_EVAL_NOTIFICATION" in msg


def test_build_apprise_nonexistent_path_string_raises() -> None:
    """A string that looks like a path but doesn't exist is also rejected."""
    with pytest.raises(PrerequisiteError) as exc_info:
        build_apprise("/this/path/does/not/exist.yml")

    msg = str(exc_info.value.message)
    assert "not an existing file" in msg


# -- notify() is best-effort: bounded + swallows backend errors ----------


async def test_notify_swallows_backend_exception() -> None:
    """A misbehaving Apprise backend must not propagate into the caller.

    Without exception isolation, `request_input()` / approval would crash
    before showing the operator the prompt.
    """
    fake = MagicMock()
    fake.notify = MagicMock(side_effect=RuntimeError("boom"))

    # Should not raise — must be caught and logged.
    with apprise_scope(fake):
        await notify("hello")

    fake.notify.assert_called_once()


async def test_notify_bounded_when_backend_hangs() -> None:
    """A hanging Apprise backend returns within `NOTIFY_TIMEOUT_SECONDS`.

    Uses a real thread-blocking `time.sleep` (not anyio.sleep) so the cap
    must be enforced via `anyio.move_on_after` around `run_sync`, not via
    cooperative cancellation inside the worker.
    """

    def hang(*args: Any, **kwargs: Any) -> bool:
        time.sleep(NOTIFY_TIMEOUT_SECONDS * 4)
        return True

    fake = MagicMock()
    fake.notify = MagicMock(side_effect=hang)

    start = time.monotonic()
    with apprise_scope(fake):
        with anyio.fail_after(NOTIFY_TIMEOUT_SECONDS + 2.0):
            await notify("hello")
    elapsed = time.monotonic() - start

    # We expect ~NOTIFY_TIMEOUT_SECONDS; allow generous slack for CI jitter.
    assert elapsed < NOTIFY_TIMEOUT_SECONDS + 2.0


# -- apprise_scope contextvar plumbing ------------------------------------


def test_apprise_scope_installs_and_unwinds() -> None:
    fake = MagicMock()
    assert active_apprise() is None
    with apprise_scope(fake):
        assert active_apprise() is fake
    assert active_apprise() is None


# -- EvalConfig.notification only stores the indirection, never the URL ---
#
# Notification URLs (Slack tokens, Twilio auth tokens, webhook bearer
# tokens) live inside the constructed `apprise.Apprise` instance that
# `init_apprise` holds in a ContextVar. They must NEVER reach
# `EvalConfig.notification`, since that field is serialized into every
# eval log. The CLI layer enforces this by rejecting URL strings via
# `_notification_callback` + `allow_from_autoenv=False`; the API layer
# enforces it because `build_apprise` reads URLs from the env var
# (when `notification=True`) without mutating the caller's argument,
# and rejects URL strings passed directly. These tests pin the
# guarantee at the EvalConfig serialization boundary so a future
# refactor that, say, "helpfully" resolves `True` to the env-var
# content before stashing it on the config would fail loudly.


def test_eval_config_notification_true_does_not_leak_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`EvalConfig(notification=True)` serializes as `True`, not the env URL.

    Even with `INSPECT_EVAL_NOTIFICATION` set to a Slack URL, the
    config — and therefore the eval log — stores only the literal
    `True` indirection. The URL stays inside the Apprise instance
    `build_apprise(True)` constructs.
    """
    from inspect_ai.log._log import EvalConfig

    secret_url = "slack://T0/B0/abc-def-ghi"
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", secret_url)

    config = EvalConfig(notification=True)
    serialized = config.model_dump_json()

    assert '"notification":true' in serialized
    assert secret_url not in serialized
    # And the typed accessor returns the literal True too.
    assert config.notification is True


def test_eval_config_notification_path_string_roundtrips() -> None:
    """A file-path notification config string roundtrips unchanged."""
    from inspect_ai.log._log import EvalConfig

    config = EvalConfig(notification="/etc/inspect/apprise.yml")
    serialized = config.model_dump_json()

    assert '"notification":"/etc/inspect/apprise.yml"' in serialized
    # Roundtrip through Pydantic.
    restored = EvalConfig.model_validate_json(serialized)
    assert restored.notification == "/etc/inspect/apprise.yml"


def test_eval_config_notification_default_is_none() -> None:
    """No `notification` argument → field is `None` (default-disabled)."""
    from inspect_ai.log._log import EvalConfig

    config = EvalConfig()
    assert config.notification is None


def test_eval_config_old_log_without_notification_field_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eval log written before this field existed loads with `notification=None`.

    Pydantic backward-compat: a config JSON missing `notification`
    must validate (default `None`) so older logs still load under
    `eval-retry`. Without this guarantee, the `notification: bool |
    str | None = Field(default=None)` addition would silently break
    log loading.
    """
    from inspect_ai.log._log import EvalConfig

    # An EvalConfig from a pre-feature log won't carry the field at all.
    legacy = EvalConfig.model_validate({})
    assert legacy.notification is None


def test_build_apprise_does_not_mutate_or_return_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_apprise(True)` reads the env URL but doesn't surface it back.

    The returned object is the `apprise.Apprise` instance — the
    caller (`init_apprise`) installs it into a ContextVar, never
    onto `EvalConfig`. This is the actual mechanism that keeps the
    URL out of the log.
    """
    pytest.importorskip("apprise")

    # Generic webhook URL — avoids Apprise emitting an "invalid token"
    # warning that would otherwise pollute the captured-log output for
    # a test that has nothing to do with token validation.
    secret_url = "json://example.com/notify"
    monkeypatch.setenv("INSPECT_EVAL_NOTIFICATION", secret_url)

    result = build_apprise(True)

    # The return type is an Apprise instance (or None) — never the URL string.
    assert result is not None
    assert not isinstance(result, (bool, str))
