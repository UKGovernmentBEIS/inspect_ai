"""The full display suspends its terminal driver around sandbox setup and always resumes it."""

import contextlib
from typing import Any, Iterator

import anyio
import pytest

from inspect_ai._display.textual.app import TaskScreenApp
from inspect_ai._util.error import PrerequisiteError


class _SuspendableDriver:
    """Records Textual's suspend/resume calls, as a terminal driver would."""

    can_suspend = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def suspend_application_mode(self) -> None:
        self.calls.append("suspend")

    def resume_application_mode(self) -> None:
        self.calls.append("resume")

    @contextlib.contextmanager
    def no_automatic_restart(self) -> Iterator[None]:
        yield


def _loaded_app(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _SuspendableDriver]:
    app: Any = TaskScreenApp()
    app._on_app_loaded = anyio.Event()
    app._on_app_loaded.set()
    driver = _SuspendableDriver()
    app._driver = driver
    monkeypatch.setattr(app, "refresh", lambda *args, **kwargs: None)
    return app, driver


async def test_suspended_app_resumes_after_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, driver = _loaded_app(monkeypatch)
    with app.suspend_app():
        pass
    assert driver.calls == ["suspend", "resume"]


async def test_suspended_app_resumes_when_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, driver = _loaded_app(monkeypatch)
    with pytest.raises(PrerequisiteError, match="build failed"):
        with app.suspend_app():
            raise PrerequisiteError("build failed")
    assert driver.calls == ["suspend", "resume"]

    # the next task's setup suspends and resumes again
    with app.suspend_app():
        pass
    assert driver.calls == ["suspend", "resume", "suspend", "resume"]


async def test_suspended_app_resumes_when_setup_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, driver = _loaded_app(monkeypatch)
    with anyio.CancelScope() as scope:
        with app.suspend_app():
            scope.cancel()
            await anyio.sleep_forever()
    assert scope.cancelled_caught
    assert driver.calls == ["suspend", "resume"]
