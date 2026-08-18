"""Persistence tests for ``EvalConfig.acp_server``.

The field round-trips through Pydantic serialization and is read back
by ``eval_retry`` (via ``eval_log.eval.config.acp_server``) so that
``inspect eval-retry`` reproduces the original transport setting
without the user re-passing ``--acp-server``.
"""

import pytest

from inspect_ai.log._log import EvalConfig


@pytest.mark.parametrize(
    "value",
    [
        True,
        12345,
        "/tmp/custom.sock",
        None,
    ],
)
def test_acp_server_round_trips_through_json(value: bool | int | str | None) -> None:
    """Every supported ``acp_server`` value survives JSON serialize/deserialize."""
    config = EvalConfig(acp_server=value)
    raw = config.model_dump_json()
    restored = EvalConfig.model_validate_json(raw)
    assert restored.acp_server == value


def test_acp_server_defaults_to_none() -> None:
    """Constructing EvalConfig without acp_server gives None (disabled)."""
    assert EvalConfig().acp_server is None


def test_old_log_without_acp_server_loads_cleanly() -> None:
    """An EvalConfig dict from before the field existed deserializes as None.

    Pydantic v2 with ``default=None`` on the field tolerates the missing
    key silently — this protects ``eval-retry`` against KeyError when
    replaying logs written before Phase 8 landed.
    """
    legacy_dict = {
        "max_samples": 10,
        "log_samples": True,
        # no acp_server key
    }
    restored = EvalConfig.model_validate(legacy_dict)
    assert restored.acp_server is None


def test_retry_override_pattern_with_logged_value() -> None:
    """When acp_server is in the log and user passes None, the log wins.

    Mirrors ``eval_retry_async``'s replay pattern: the retry-time
    explicit value takes precedence, else fall back to the persisted
    log value.
    """
    logged = EvalConfig(acp_server=12345)
    retry_param: bool | int | str | None = None
    resolved = retry_param if retry_param is not None else logged.acp_server
    assert resolved == 12345


def test_retry_override_pattern_with_explicit_override() -> None:
    """When the user passes a new value to retry, it wins over the log."""
    logged = EvalConfig(acp_server=12345)
    retry_param: bool | int | str | None = "/tmp/different.sock"
    resolved = retry_param if retry_param is not None else logged.acp_server
    assert resolved == "/tmp/different.sock"


def test_retry_override_pattern_when_log_has_none() -> None:
    """When neither the log nor the retry override has a value, result is None."""
    logged = EvalConfig(acp_server=None)
    retry_param: bool | int | str | None = None
    resolved = retry_param if retry_param is not None else logged.acp_server
    assert resolved is None
