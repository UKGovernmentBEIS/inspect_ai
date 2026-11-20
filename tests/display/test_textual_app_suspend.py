"""The full display suspends its terminal driver around sandbox setup and always resumes it."""

import contextlib
from typing import Any, Iterator

import anyio
import pytest

from inspect_ai._display.textual.app import TaskScreenApp, TextualTaskScreen
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


class _SetupFailed(Exception):
    pass


@pytest.mark.parametrize("end", ["normal", "error", "cancel"])
async def test_input_screen_during_setup_shares_the_suspension(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, end: str
) -> None:
    app, driver = _loaded_app(monkeypatch)
    screen = TextualTaskScreen[None](app)
    with anyio.CancelScope() as scope:
        with contextlib.suppress(_SetupFailed):
            with app.suspend_app():
                # another task's input screen opens and closes during setup
                with screen.input_screen(record_event=False):
                    pass
                assert driver.calls == ["suspend"]
                if end == "error":
                    raise _SetupFailed()
                elif end == "cancel":
                    scope.cancel()
                    await anyio.sleep_forever()
    assert scope.cancelled_caught == (end == "cancel")
    assert driver.calls == ["suspend", "resume"]


async def test_input_screen_open_when_setup_starts_shares_the_suspension(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, driver = _loaded_app(monkeypatch)
    screen = TextualTaskScreen[None](app)
    with contextlib.ExitStack() as setup:
        with screen.input_screen(record_event=False):
            setup.enter_context(app.suspend_app())
        # the input screen closed while setup is still running
        assert driver.calls == ["suspend"]
    assert driver.calls == ["suspend", "resume"]
