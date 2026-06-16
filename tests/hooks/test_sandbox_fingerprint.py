from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import inspect_ai.hooks._startup as hooks_startup_module
from inspect_ai._util.environ import environ_var
from inspect_ai._util.registry import registry_info
from inspect_ai.hooks._hooks import SampleStart, get_all_hooks
from inspect_ai.hooks._sandbox_fingerprint._hook import SandboxFingerprintHook
from inspect_ai.hooks._sandbox_fingerprint._probes import (
    ProbeContext,
    fingerprint_probe,
    register_fingerprint_probe,
)
from inspect_ai.util._sandbox.context import (
    init_sample_sandbox_fingerprint,
    sample_sandbox_fingerprint,
    sandbox_environments_context_var,
)
from inspect_ai.util._sandbox.environment import SandboxConnection, SandboxFingerprint
from inspect_ai.util._subprocess import ExecResult


def _mock_sandbox(
    *, container: str | None = "ctr", exec_outputs: dict[str, str] | None = None
) -> MagicMock:
    outputs = exec_outputs or {
        "cat": 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"',
        "uname": "6.8.0-test",
        "pip": '[{"name": "requests", "version": "2.31.0"}, '
        '{"name": "numpy", "version": "1.26.0"}]',
    }

    async def fake_exec(cmd: list[str], **kwargs: Any) -> ExecResult[str]:
        return ExecResult(
            success=True, returncode=0, stdout=outputs.get(cmd[0], ""), stderr=""
        )

    sandbox = MagicMock()
    sandbox.exec = AsyncMock(side_effect=fake_exec)
    connection = (
        SandboxConnection(type="docker", command="x", container=container)
        if container is not None
        else None
    )
    sandbox.connection = AsyncMock(return_value=connection)
    return sandbox


def _sample_start() -> SampleStart:
    return SampleStart(
        eval_set_id=None,
        run_id="r",
        eval_id="e",
        sample_id="s",
        summary=MagicMock(),
    )


async def _drive(hook: SandboxFingerprintHook, environments: dict[str, Any]) -> None:
    sandbox_environments_context_var.set(environments)
    init_sample_sandbox_fingerprint()
    await hook.on_sample_start(_sample_start())


def _fingerprints() -> dict[str, SandboxFingerprint]:
    fingerprints = sample_sandbox_fingerprint()
    assert fingerprints is not None
    return fingerprints


async def test_records_fingerprint_from_exec_probes() -> None:
    await _drive(SandboxFingerprintHook(), {"default": _mock_sandbox()})

    fingerprints = sample_sandbox_fingerprint()
    assert fingerprints is not None
    fingerprint = fingerprints["default"]
    assert isinstance(fingerprint, SandboxFingerprint)
    assert fingerprint.type == "docker"
    assert fingerprint.os == "Debian GNU/Linux 12 (bookworm)"
    assert fingerprint.kernel == "6.8.0-test"
    assert fingerprint.packages == {"requests": "2.31.0", "numpy": "1.26.0"}


async def test_packages_empty_dict_when_pip_returns_no_packages() -> None:
    sandbox = _mock_sandbox(
        exec_outputs={
            "cat": 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"',
            "uname": "6.8.0-test",
            "pip": "[]",
        }
    )
    await _drive(SandboxFingerprintHook(), {"default": sandbox})
    assert _fingerprints()["default"].packages == {}


async def test_degrades_when_connection_unavailable() -> None:
    await _drive(SandboxFingerprintHook(), {"default": _mock_sandbox(container=None)})

    fingerprint = _fingerprints()["default"]
    assert fingerprint.image_id is None
    assert fingerprint.os == "Debian GNU/Linux 12 (bookworm)"


async def test_never_raises_when_probes_fail() -> None:
    sandbox = MagicMock()
    sandbox.exec = AsyncMock(side_effect=RuntimeError("boom"))
    sandbox.connection = AsyncMock(side_effect=ConnectionError("down"))

    await _drive(SandboxFingerprintHook(), {"default": sandbox})

    fingerprint = _fingerprints()["default"]
    assert fingerprint.os is None
    assert fingerprint.image_id is None
    assert fingerprint.packages is None


async def test_no_environments_records_nothing() -> None:
    sandbox_environments_context_var.set({})
    init_sample_sandbox_fingerprint()
    await SandboxFingerprintHook().on_sample_start(_sample_start())
    assert sample_sandbox_fingerprint() is None


def test_enabled_honors_opt_out() -> None:
    hook = SandboxFingerprintHook()
    assert hook.enabled() is True
    with environ_var("INSPECT_DISABLE_SANDBOX_FINGERPRINT", "1"):
        assert hook.enabled() is False


async def test_custom_probe_lands_in_metadata() -> None:
    async def custom(context: ProbeContext) -> dict[str, Any]:
        return {"metadata": {"custom_key": "custom_value"}}

    register_fingerprint_probe("custom_test", custom)
    try:
        await _drive(SandboxFingerprintHook(), {"default": _mock_sandbox()})
        fingerprint = _fingerprints()["default"]
        assert fingerprint.metadata["custom_key"] == "custom_value"
    finally:
        from inspect_ai.hooks._sandbox_fingerprint import _probes

        _probes._PROBES.pop("custom_test", None)


def test_probe_decorator_overrides_same_name() -> None:
    from inspect_ai.hooks._sandbox_fingerprint import _probes

    original = _probes._PROBES.get("os")
    try:

        @fingerprint_probe("os")
        async def replacement(context: ProbeContext) -> dict[str, Any]:
            return {"os": "Replaced"}

        assert _probes._PROBES["os"] is replacement
    finally:
        if original is not None:
            _probes._PROBES["os"] = original


@pytest.fixture(autouse=True)
def reset_hooks() -> None:
    hooks_startup_module._registry_hooks_loaded = False


def test_hook_auto_registers_and_enabled() -> None:
    hooks_startup_module._load_registry_hooks()
    names = {registry_info(h).name for h in get_all_hooks()}
    assert "inspect_ai/sandbox_fingerprint" in names
    hook = next(
        h
        for h in get_all_hooks()
        if registry_info(h).name == "inspect_ai/sandbox_fingerprint"
    )
    assert hook.enabled() is True
