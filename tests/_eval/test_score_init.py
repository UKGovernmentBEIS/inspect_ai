"""Tests for score_async() self-initializing its runtime context."""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai._eval.score import score_async
from inspect_ai.log._file import read_eval_log_async
from inspect_ai.scorer import match

from .test_score import LOG_UNSCORED


@skip_if_no_openai_package
def test_score_self_initializes_in_fresh_process(tmp_path: pathlib.Path) -> None:
    """Public score_async() works from a plain Python process.

    A process that hasn't run an eval or the `inspect score` CLI has no
    platform/eval context, and users shouldn't need the private
    `platform_init()` / `init_eval_context()` pair to prepare one — this
    script deliberately uses only public imports. The model api key is
    provided solely via a `.env` in the working directory (and stripped
    from the environment), so the test fails unless `score_async()`
    established the runtime context (`.env` resolution in particular)
    itself. `match()` never calls the model, so a placeholder key is fine.
    """
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-placeholder\n")
    script = textwrap.dedent(
        f"""
        import anyio
        from inspect_ai import score_async
        from inspect_ai.log import read_eval_log
        from inspect_ai.scorer import match

        async def main() -> None:
            log = read_eval_log({str(LOG_UNSCORED)!r})
            scored = await score_async(
                log, match(), action="overwrite", model="openai/gpt-4o"
            )
            assert scored.results is not None
            assert [score.name for score in scored.results.scores] == ["match"]
            print("SCORED-OK")

        anyio.run(main)
        """
    )
    # strip the api key (it must come from .env) along with hook config a
    # plain fresh process wouldn't have (platform_init() enforces it)
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "OPENAI_API_KEY",
            "INSPECT_TELEMETRY",
            "INSPECT_API_KEY_OVERRIDE",
            "INSPECT_REQUIRED_HOOKS",
        )
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "SCORED-OK" in result.stdout


def _clear_hook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear hook config these tests may inherit from a dev machine.

    Hook initialization (run by self-init's platform_init() and by
    get_model()) raises if a configured hook provider isn't installed.
    """
    for var in (
        "INSPECT_TELEMETRY",
        "INSPECT_API_KEY_OVERRIDE",
        "INSPECT_REQUIRED_HOOKS",
    ):
        monkeypatch.delenv(var, raising=False)


async def test_score_async_self_initializes_eval_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._eval.context import _eval_context_active, have_eval_context

    _clear_hook_env(monkeypatch)
    token = _eval_context_active.set(False)
    try:
        log = await read_eval_log_async(LOG_UNSCORED)
        scored = await score_async(log, match(), model="mockllm/model")
        assert have_eval_context()
        assert scored.results is not None
    finally:
        _eval_context_active.reset(token)


async def test_score_async_skips_self_init_while_eval_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling-task score_async() must not reset a running eval's state."""
    import inspect_ai._eval.eval as eval_module
    from inspect_ai._eval.context import _eval_context_active, have_eval_context

    _clear_hook_env(monkeypatch)
    monkeypatch.setattr(eval_module, "_eval_async_running", True)
    token = _eval_context_active.set(False)
    try:
        log = await read_eval_log_async(LOG_UNSCORED)
        scored = await score_async(log, match(), model="mockllm/model")
        assert not have_eval_context()
        assert scored.results is not None
    finally:
        _eval_context_active.reset(token)


async def test_score_async_preserves_active_eval_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an eval context is already active (CLI / in-eval), don't re-init."""
    from inspect_ai._eval.context import init_eval_context
    from inspect_ai.approval._human.manager import human_approval_manager

    _clear_hook_env(monkeypatch)
    init_eval_context(None, None, None)
    manager = human_approval_manager()
    log = await read_eval_log_async(LOG_UNSCORED)
    await score_async(log, match(), model="mockllm/model")
    assert human_approval_manager() is manager
