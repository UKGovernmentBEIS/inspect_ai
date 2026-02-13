# Retry Log Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich retry log messages with task, sample, epoch, and model context so concurrent runs are debuggable.

**Architecture:** Two shared helper functions in `_util/retry.py` (`sample_context_prefix` and `retry_error_summary`) power three integration points: inspect's model retry logger, inspect's httpx retry logger, and a `logging.Filter` on the `openai` SDK logger. All read context from the existing `sample_active()` ContextVar.

**Tech Stack:** Python `logging.Filter`, `tenacity.RetryCallState`, existing `ActiveSample` ContextVar from `inspect_ai.log._samples`.

**Design doc:** `design/retry-log-enrichment.md`

---

### Task 1: `sample_context_prefix()` helper

**Files:**
- Modify: `src/inspect_ai/_util/retry.py`
- Create: `tests/util/test_retry_logging.py`

**Step 1: Write the failing tests**

```python
# tests/util/test_retry_logging.py
"""Tests for retry log enrichment helpers."""

from unittest.mock import MagicMock, patch

from inspect_ai._util.retry import sample_context_prefix


def _make_mock_sample(
    *,
    uuid: str = "Abc12xY",
    task: str = "mmlu",
    sample_id: int | str | None = 42,
    epoch: int = 1,
    model: str = "openai/gpt-4o",
) -> MagicMock:
    """Create a mock ActiveSample with the given fields."""
    active = MagicMock()
    active.id = uuid
    active.task = task
    active.sample.id = sample_id
    active.epoch = epoch
    active.model = model
    return active


class TestSampleContextPrefix:
    def test_returns_prefix_with_active_sample(self) -> None:
        mock = _make_mock_sample()
        with patch("inspect_ai._util.retry.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/42/1 openai/gpt-4o] "

    def test_returns_empty_string_when_no_active_sample(self) -> None:
        with patch("inspect_ai._util.retry.sample_active", return_value=None):
            result = sample_context_prefix()
        assert result == ""

    def test_handles_string_sample_id(self) -> None:
        mock = _make_mock_sample(sample_id="q_123")
        with patch("inspect_ai._util.retry.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/q_123/1 openai/gpt-4o] "

    def test_handles_none_sample_id(self) -> None:
        mock = _make_mock_sample(sample_id=None)
        with patch("inspect_ai._util.retry.sample_active", return_value=mock):
            result = sample_context_prefix()
        assert result == "[Abc12xY mmlu/None/1 openai/gpt-4o] "
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestSampleContextPrefix -v`
Expected: FAIL with `ImportError` — `sample_context_prefix` doesn't exist yet.

**Step 3: Write minimal implementation**

Add to `src/inspect_ai/_util/retry.py` (after the existing code at line 17):

```python
def sample_context_prefix() -> str:
    """Build a compact context prefix from the active sample.

    Returns a string like "[Abc12xY mmlu/42/1 openai/gpt-4o] " or "" if
    no sample is active.
    """
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        return ""
    return (
        f"[{active.id} {active.task}/{active.sample.id}/{active.epoch} "
        f"{active.model}] "
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestSampleContextPrefix -v`
Expected: PASS (all 4 tests)

**Step 5: Lint**

Run: `ruff check --fix src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py && ruff format src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py`

**Step 6: Commit**

```
git add src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py
git commit -m "feat: add sample_context_prefix() for retry log enrichment"
```

---

### Task 2: `retry_error_summary()` helper

**Files:**
- Modify: `src/inspect_ai/_util/retry.py`
- Modify: `tests/util/test_retry_logging.py`

**Step 1: Write the failing tests**

Append to `tests/util/test_retry_logging.py`:

```python
from unittest.mock import MagicMock

from inspect_ai._util.retry import retry_error_summary


def _make_retry_state(exception: BaseException | None = None) -> MagicMock:
    """Create a mock RetryCallState with the given exception."""
    state = MagicMock()
    if exception is not None:
        state.outcome.exception.return_value = exception
    else:
        state.outcome = None
    return state


class TestRetryErrorSummary:
    def test_with_status_code_and_error_code(self) -> None:
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        ex.code = "rate_limit_exceeded"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 429 rate_limit_exceeded]"

    def test_with_status_code_only(self) -> None:
        ex = Exception("server error")
        ex.status_code = 503  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 503]"

    def test_with_error_code_only(self) -> None:
        ex = Exception("bad")
        ex.code = "server_error"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception server_error]"

    def test_with_status_on_response_object(self) -> None:
        """Some SDKs put status_code on ex.response, not ex directly."""
        ex = Exception("error")
        response = MagicMock()
        response.status_code = 502
        ex.response = response  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [Exception 502]"

    def test_plain_exception(self) -> None:
        ex = ConnectionError("refused")
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [ConnectionError]"

    def test_no_outcome(self) -> None:
        state = _make_retry_state(exception=None)
        assert retry_error_summary(state) == ""

    def test_outcome_with_no_exception(self) -> None:
        state = MagicMock()
        state.outcome.exception.return_value = None
        assert retry_error_summary(state) == ""

    def test_uses_specific_exception_class_name(self) -> None:
        """Verify we get 'TimeoutError' not 'Exception'."""
        ex = TimeoutError("timed out")
        state = _make_retry_state(ex)
        assert retry_error_summary(state) == " [TimeoutError]"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestRetryErrorSummary -v`
Expected: FAIL with `ImportError` — `retry_error_summary` doesn't exist yet.

**Step 3: Write minimal implementation**

Add to `src/inspect_ai/_util/retry.py` (after `sample_context_prefix`):

```python
def retry_error_summary(retry_state: "RetryCallState") -> str:
    """Build a compact error summary from a tenacity RetryCallState.

    Returns a string like " [RateLimitError 429 rate_limit_exceeded]" or ""
    if no exception is available. Never includes full error messages (could
    leak prompt content or API keys).
    """
    from tenacity import RetryCallState

    if retry_state.outcome is None:
        return ""
    ex = retry_state.outcome.exception()
    if ex is None:
        return ""

    type_name = type(ex).__name__

    # HTTP status code — on the exception itself or on ex.response
    status: int | None = getattr(ex, "status_code", None)
    if status is None:
        response = getattr(ex, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)

    # API error code (e.g. "rate_limit_exceeded", "server_error")
    code: str | None = getattr(ex, "code", None)

    parts = [type_name]
    if status is not None:
        parts.append(str(status))
    if code is not None:
        parts.append(code)
    return f" [{' '.join(parts)}]"
```

Also add the `TYPE_CHECKING` import at the top of `src/inspect_ai/_util/retry.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tenacity import RetryCallState
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestRetryErrorSummary -v`
Expected: PASS (all 8 tests)

**Step 5: Lint**

Run: `ruff check --fix src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py && ruff format src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py`

**Step 6: Commit**

```
git add src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py
git commit -m "feat: add retry_error_summary() for retry log enrichment"
```

---

### Task 3: Enrich `log_model_retry()`

**Files:**
- Modify: `src/inspect_ai/model/_model.py:1803-1807`
- Modify: `tests/util/test_retry_logging.py`

**Step 1: Write the failing test**

Append to `tests/util/test_retry_logging.py`:

```python
import logging

from inspect_ai._util.constants import HTTP


class TestLogModelRetry:
    def test_includes_sample_context_and_error_summary(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai.model._model import log_model_retry

        mock_sample = _make_mock_sample()
        ex = Exception("rate limited")
        ex.status_code = 429  # type: ignore[attr-defined]
        ex.code = "rate_limit_exceeded"  # type: ignore[attr-defined]
        state = _make_retry_state(ex)
        state.attempt_number = 2
        state.upcoming_sleep = 6.0

        with (
            caplog.at_level(HTTP),
            patch("inspect_ai._util.retry.sample_active", return_value=mock_sample),
        ):
            log_model_retry("openai/gpt-4o", state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "openai/gpt-4o retry 2" in msg
        assert "[Exception 429 rate_limit_exceeded]" in msg

    def test_no_sample_context_when_inactive(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai.model._model import log_model_retry

        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 1
        state.upcoming_sleep = 3.0

        with (
            caplog.at_level(HTTP),
            patch("inspect_ai._util.retry.sample_active", return_value=None),
        ):
            log_model_retry("openai/gpt-4o", state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert msg.startswith("-> openai/gpt-4o retry 1")
        assert "[ConnectionError]" in msg
```

Add `import pytest` to the top of the test file if not already present.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestLogModelRetry -v`
Expected: FAIL — existing `log_model_retry` doesn't include context prefix or error summary.

**Step 3: Update `log_model_retry`**

Replace lines 1803–1807 in `src/inspect_ai/model/_model.py`:

```python
def log_model_retry(model_name: str, retry_state: RetryCallState) -> None:
    from inspect_ai._util.retry import retry_error_summary, sample_context_prefix

    prefix = sample_context_prefix()
    error = retry_error_summary(retry_state)
    logger.log(
        HTTP,
        f"{prefix}-> {model_name} retry {retry_state.attempt_number} "
        f"(retrying in {retry_state.upcoming_sleep:,.0f} seconds){error}",
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestLogModelRetry -v`
Expected: PASS (both tests)

**Step 5: Lint**

Run: `ruff check --fix src/inspect_ai/model/_model.py && ruff format src/inspect_ai/model/_model.py`

**Step 6: Commit**

```
git add src/inspect_ai/model/_model.py tests/util/test_retry_logging.py
git commit -m "feat: enrich log_model_retry with sample context and error summary"
```

---

### Task 4: Enrich `log_httpx_retry_attempt()`

**Files:**
- Modify: `src/inspect_ai/_util/httpx.py:37-44`
- Modify: `tests/util/test_retry_logging.py`

**Step 1: Write the failing test**

Append to `tests/util/test_retry_logging.py`:

```python
class TestLogHttpxRetryAttempt:
    def test_includes_sample_context(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai._util.httpx import log_httpx_retry_attempt

        mock_sample = _make_mock_sample()
        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 1
        state.upcoming_sleep = 3.0

        log_fn = log_httpx_retry_attempt("https://api.example.com/search")
        with (
            caplog.at_level(HTTP),
            patch("inspect_ai._util.retry.sample_active", return_value=mock_sample),
        ):
            log_fn(state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in msg
        assert "https://api.example.com/search connection retry 1" in msg

    def test_no_prefix_when_no_sample(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from inspect_ai._util.httpx import log_httpx_retry_attempt

        state = _make_retry_state(ConnectionError("refused"))
        state.attempt_number = 2
        state.upcoming_sleep = 6.0

        log_fn = log_httpx_retry_attempt("https://api.example.com/search")
        with (
            caplog.at_level(HTTP),
            patch("inspect_ai._util.retry.sample_active", return_value=None),
        ):
            log_fn(state)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert msg.startswith("https://api.example.com/search connection retry 2")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestLogHttpxRetryAttempt -v`
Expected: FAIL — existing `log_httpx_retry_attempt` doesn't include prefix.

**Step 3: Update `log_httpx_retry_attempt`**

Replace lines 37–44 in `src/inspect_ai/_util/httpx.py`:

```python
def log_httpx_retry_attempt(context: str) -> Callable[[RetryCallState], None]:
    def log_attempt(retry_state: RetryCallState) -> None:
        from inspect_ai._util.retry import sample_context_prefix

        prefix = sample_context_prefix()
        logger.log(
            HTTP,
            f"{prefix}{context} connection retry {retry_state.attempt_number} (retrying in {retry_state.upcoming_sleep:,.0f} seconds)",
        )

    return log_attempt
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestLogHttpxRetryAttempt -v`
Expected: PASS (both tests)

**Step 5: Lint**

Run: `ruff check --fix src/inspect_ai/_util/httpx.py && ruff format src/inspect_ai/_util/httpx.py`

**Step 6: Commit**

```
git add src/inspect_ai/_util/httpx.py tests/util/test_retry_logging.py
git commit -m "feat: enrich log_httpx_retry_attempt with sample context"
```

---

### Task 5: `SampleContextFilter` for SDK loggers

**Files:**
- Modify: `src/inspect_ai/_util/retry.py`
- Modify: `tests/util/test_retry_logging.py`

**Step 1: Write the failing tests**

Append to `tests/util/test_retry_logging.py`:

```python
from inspect_ai._util.retry import SampleContextFilter


class TestSampleContextFilter:
    def test_enriches_record_with_active_sample(self) -> None:
        mock_sample = _make_mock_sample()
        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to /responses in 0.4 seconds",
            args=None,
            exc_info=None,
        )
        with patch("inspect_ai._util.retry.sample_active", return_value=mock_sample):
            result = filt.filter(record)

        assert result is True
        assert record.getMessage().startswith("[Abc12xY mmlu/42/1 openai/gpt-4o]")
        assert "Retrying request to /responses" in record.getMessage()
        # Structured fields for JSON formatters
        assert record.sample_uuid == "Abc12xY"  # type: ignore[attr-defined]
        assert record.sample_task == "mmlu"  # type: ignore[attr-defined]
        assert record.sample_id == 42  # type: ignore[attr-defined]
        assert record.sample_epoch == 1  # type: ignore[attr-defined]
        assert record.sample_model == "openai/gpt-4o"  # type: ignore[attr-defined]

    def test_passes_through_when_no_active_sample(self) -> None:
        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to /responses in 0.4 seconds",
            args=None,
            exc_info=None,
        )
        with patch("inspect_ai._util.retry.sample_active", return_value=None):
            result = filt.filter(record)

        assert result is True
        assert record.getMessage() == "Retrying request to /responses in 0.4 seconds"
        assert not hasattr(record, "sample_uuid")

    def test_handles_format_args_in_msg(self) -> None:
        """The OpenAI SDK uses % formatting: log.info('Retrying request to %s in %f seconds', url, timeout)"""
        mock_sample = _make_mock_sample()
        filt = SampleContextFilter()
        record = logging.LogRecord(
            name="openai._base_client",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Retrying request to %s in %f seconds",
            args=("/responses", 0.396765),
            exc_info=None,
        )
        with patch("inspect_ai._util.retry.sample_active", return_value=mock_sample):
            result = filt.filter(record)

        assert result is True
        # The prefix should be prepended to the msg template.
        # When getMessage() resolves args, the full message should contain both.
        full_msg = record.getMessage()
        assert "[Abc12xY mmlu/42/1 openai/gpt-4o]" in full_msg
        assert "/responses" in full_msg
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestSampleContextFilter -v`
Expected: FAIL with `ImportError` — `SampleContextFilter` doesn't exist yet.

**Step 3: Write the implementation**

Add to `src/inspect_ai/_util/retry.py`:

```python
import logging


class SampleContextFilter(logging.Filter):
    """Logging filter that enriches log records with active sample context.

    Prepends a compact prefix to record.msg for plain text formatters and
    sets structured attributes on the record for JSON/structured formatters.
    Passes records through unchanged when no active sample exists.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from inspect_ai.log._samples import sample_active

        active = sample_active()
        if active is not None:
            prefix = (
                f"[{active.id} {active.task}/{active.sample.id}/{active.epoch} "
                f"{active.model}] "
            )
            record.msg = f"{prefix}{record.msg}"
            # Structured fields for JSON/structured formatters
            record.sample_uuid = active.id  # type: ignore[attr-defined]
            record.sample_task = active.task  # type: ignore[attr-defined]
            record.sample_id = active.sample.id  # type: ignore[attr-defined]
            record.sample_epoch = active.epoch  # type: ignore[attr-defined]
            record.sample_model = active.model  # type: ignore[attr-defined]
        return True
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestSampleContextFilter -v`
Expected: PASS (all 3 tests)

**Step 5: Lint**

Run: `ruff check --fix src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py && ruff format src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py`

**Step 6: Commit**

```
git add src/inspect_ai/_util/retry.py tests/util/test_retry_logging.py
git commit -m "feat: add SampleContextFilter for enriching SDK retry logs"
```

---

### Task 6: Install the filter at eval startup

**Files:**
- Modify: `src/inspect_ai/_util/retry.py`
- Modify: `src/inspect_ai/_eval/context.py:28-38`
- Modify: `tests/util/test_retry_logging.py`

**Step 1: Write the failing test**

Append to `tests/util/test_retry_logging.py`:

```python
from inspect_ai._util.retry import install_sample_context_logging


class TestInstallSampleContextLogging:
    def test_installs_filter_on_openai_logger(self) -> None:
        openai_logger = logging.getLogger("openai")
        original_filters = list(openai_logger.filters)

        install_sample_context_logging()

        new_filters = [
            f for f in openai_logger.filters if f not in original_filters
        ]
        assert len(new_filters) == 1
        assert isinstance(new_filters[0], SampleContextFilter)

        # Cleanup: remove the filter so other tests aren't affected
        openai_logger.removeFilter(new_filters[0])

    def test_is_idempotent(self) -> None:
        """Calling install twice should not add duplicate filters."""
        openai_logger = logging.getLogger("openai")
        original_count = len(
            [f for f in openai_logger.filters if isinstance(f, SampleContextFilter)]
        )

        install_sample_context_logging()
        install_sample_context_logging()

        new_count = len(
            [f for f in openai_logger.filters if isinstance(f, SampleContextFilter)]
        )
        assert new_count == original_count + 1  # only one added despite two calls

        # Cleanup
        for f in openai_logger.filters:
            if isinstance(f, SampleContextFilter):
                openai_logger.removeFilter(f)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/util/test_retry_logging.py::TestInstallSampleContextLogging -v`
Expected: FAIL with `ImportError` — `install_sample_context_logging` doesn't exist yet.

**Step 3: Add `install_sample_context_logging` to `retry.py`**

Add to `src/inspect_ai/_util/retry.py`:

```python
_sample_context_logging_installed = False


def install_sample_context_logging() -> None:
    """Install SampleContextFilter on SDK loggers.

    Attaches the filter to the ``openai`` logger so that retry messages
    emitted by the OpenAI SDK are enriched with active sample context.
    Safe to call multiple times — installs at most once.
    """
    global _sample_context_logging_installed
    if _sample_context_logging_installed:
        return
    _sample_context_logging_installed = True

    logging.getLogger("openai").addFilter(SampleContextFilter())
```

**Step 4: Wire it into eval startup**

Modify `src/inspect_ai/_eval/context.py`. Add import and call in `init_eval_context` (line 28–38):

```python
def init_eval_context(
    log_level: str | None,
    log_level_transcript: str | None = None,
    max_subprocesses: int | None = None,
    task_group: TaskGroup | None = None,
) -> None:
    init_runtime_context(max_subprocesses)
    init_logger(log_level, log_level_transcript)
    init_active_samples()
    init_human_approval_manager()
    set_background_task_group(task_group)
    install_sample_context_logging()
```

Add the import at the top of `context.py`:

```python
from inspect_ai._util.retry import install_sample_context_logging
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/util/test_retry_logging.py::TestInstallSampleContextLogging -v`
Expected: PASS (both tests)

**Step 6: Run all retry logging tests together**

Run: `pytest tests/util/test_retry_logging.py -v`
Expected: All tests PASS

**Step 7: Lint**

Run: `ruff check --fix src/inspect_ai/_util/retry.py src/inspect_ai/_eval/context.py tests/util/test_retry_logging.py && ruff format src/inspect_ai/_util/retry.py src/inspect_ai/_eval/context.py tests/util/test_retry_logging.py`

**Step 8: Commit**

```
git add src/inspect_ai/_util/retry.py src/inspect_ai/_eval/context.py tests/util/test_retry_logging.py
git commit -m "feat: install SampleContextFilter on openai logger at eval startup"
```

---

### Task 7: Full regression check

**Step 1: Type check**

Run: `mypy --exclude tests/test_package src tests`
Expected: No new errors introduced.

**Step 2: Lint**

Run: `ruff check src/inspect_ai/_util/retry.py src/inspect_ai/_util/httpx.py src/inspect_ai/model/_model.py src/inspect_ai/_eval/context.py tests/util/test_retry_logging.py`
Expected: Clean

**Step 3: Run full test suite for affected modules**

Run: `pytest tests/util/test_retry_logging.py tests/test_retry.py tests/test_retry_on_error.py -v`
Expected: All PASS

**Step 4: Commit (if any lint/type fixes were needed)**

```
git add -u
git commit -m "fix: address lint/type issues from retry log enrichment"
```
