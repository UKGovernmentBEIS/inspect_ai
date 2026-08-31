import contextlib
import faulthandler
import importlib.util
import inspect
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback
import uuid
import warnings
from collections.abc import Iterator
from types import FrameType
from typing import TYPE_CHECKING, TextIO

import boto3
import pytest
from moto.server import ThreadedMotoServer

if TYPE_CHECKING:
    from test_helpers.chunked_corpus import ChunkedCorpus

sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))


# ---------------------------------------------------------------------------
# Automatically mark every async test function with @pytest.mark.anyio so
# it runs under both asyncio and trio backends.  We use a hookwrapper
# because its setup phase executes *before* the anyio plugin's tryfirst
# pytest_pycollect_makeitem hook, which is the point where anyio looks for
# the marker.  A conftest-level ``pytestmark`` would be too late (applied
# after collection).
#
# Trio variants are skipped by default.  Use --runtrio in a *separate*
# pytest invocation to run only the trio variants (asyncio variants and
# sync tests are skipped in that run).  This avoids cross-backend
# contamination from global asyncio state (locks, etc.).
# Use @skip_if_trio (from test_helpers.utils) for tests that can never
# run under trio (e.g. they hit asyncio-only production code paths).
# ---------------------------------------------------------------------------
@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makeitem(collector, name, obj):
    """Auto-apply @pytest.mark.anyio to every async test function."""
    if inspect.iscoroutinefunction(obj) or inspect.isasyncgenfunction(obj):
        pytest.mark.anyio(obj)
    yield


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--runapi", action="store_true", default=False, help="run API tests"
    )
    parser.addoption(
        "--runflaky", action="store_true", default=False, help="run flaky tests"
    )
    parser.addoption(
        "--runtrio",
        action="store_true",
        default=False,
        help="run ONLY trio backend variants of async tests (use in a separate invocation)",
    )
    parser.addoption(
        "--local-inspect-tools",
        action="store_true",
        default=False,
        help="If set, run inspect tools from local source instead of pulling from Docker Hub",
    )


@pytest.fixture(scope="session")
def local_inspect_tools(request):
    return request.config.getoption("--local-inspect-tools")


# Chunked-format corpora (large-samples effort): converted once per
# session; imports are function-local so conftest stays light for runs
# that never request them.


@pytest.fixture(scope="session")
def chunked_corpus(tmp_path_factory: pytest.TempPathFactory) -> "ChunkedCorpus":
    """Chunked conversions of every test `.eval` log (default chunk size).

    Realistic writer-policy corpus: most samples fit a single chunk.
    """
    from test_helpers.chunked_corpus import build_chunked_corpus

    from inspect_ai.log._recorders.chunked.format import DEFAULT_CHUNK_SIZE

    return build_chunked_corpus(
        tmp_path_factory.mktemp("chunked_corpus"), DEFAULT_CHUNK_SIZE
    )


@pytest.fixture(scope="session")
def chunked_corpus_small_chunks(
    tmp_path_factory: pytest.TempPathFactory,
) -> "ChunkedCorpus":
    """Chunked conversions with a tiny chunk size (multi-chunk samples)."""
    from test_helpers.chunked_corpus import (
        CORPUS_SMALL_CHUNK_SIZE,
        build_chunked_corpus,
    )

    return build_chunked_corpus(
        tmp_path_factory.mktemp("chunked_corpus_small"), CORPUS_SMALL_CHUNK_SIZE
    )


class _DedupeRecordsFilter(logging.Filter):
    """Pass each LogRecord object through the handler at most once.

    Needed because the ``caplog`` override below attaches caplog's handler to
    the ``inspect_ai`` logger *in addition to* pytest's own attachment at the
    root logger. While ``inspect_ai.propagate`` is still True (fresh process),
    a record would otherwise hit the same handler twice and double up
    ``caplog.records``. Dedupe is by object identity; holding the record in
    the set keeps it alive so its identity can't be recycled mid-test.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[logging.LogRecord] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        if record in self._seen:
            return False
        self._seen.add(record)
        return True


@pytest.fixture
def caplog(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Override the built-in ``caplog`` so it reliably captures inspect_ai records.

    The first ``eval()`` in a process calls ``init_logger()``, which sets
    ``propagate = False`` on the ``inspect_ai`` logger and never restores it
    (the memoized handler guard in ``_util/logger.py`` skips reconfiguration
    thereafter). From then on, ``inspect_ai.*`` records never reach the root
    logger that stock ``caplog`` listens at, so any test asserting on them via
    ``caplog`` is order-dependent: positive assertions flake, negative ones
    pass vacuously. Attaching caplog's handler directly to the ``inspect_ai``
    logger captures in every ordering, without mutating any inspect logging
    config. See meta-tests in ``tests/test_conftest_caplog.py``.

    Caution: never wrap code that may run the process's first ``eval()`` in
    ``caplog.at_level(..., logger="inspect_ai")`` — ``at_level`` snapshots the
    level on entry and force-restores it on exit, wiping out the capture level
    ``init_logger()`` set mid-block (the memoized handler guard means it is
    never repaired), which silently drops sub-WARNING inspect records for the
    rest of the process. ``at_level`` on ``inspect_ai.*`` *module* loggers is
    fine (``init_logger()`` never sets those levels), and is usually
    unnecessary anyway: this handler attachment captures WARNING+ records
    without any level change.
    """
    dedupe = _DedupeRecordsFilter()
    caplog.handler.addFilter(dedupe)
    inspect_logger = logging.getLogger("inspect_ai")
    inspect_logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        inspect_logger.removeHandler(caplog.handler)
        caplog.handler.removeFilter(dedupe)


@pytest.fixture(autouse=True)
def fast_retry_waits(request):
    """Zero out model-generate and chat-API retry backoff during tests.

    Both retry paths default to ``wait_exponential_jitter(initial=3, ...)`` /
    ``wait_exponential_jitter()``, so any test that exercises a retry waits a
    real 3s + 6s + ... per attempt. The backoff *duration* is never the thing
    under test, so we replace the module-level ``wait_exponential_jitter`` with
    a no-wait stand-in. Tests that genuinely assert on backoff timing can opt
    out with ``@pytest.mark.real_retry_wait``.
    """
    if request.node.get_closest_marker("real_retry_wait"):
        yield
        return

    from tenacity.wait import wait_none

    import inspect_ai.model._providers.util.chatapi as chatapi
    import inspect_ai.model._retry as model_retry

    def no_wait(*args: object, **kwargs: object) -> wait_none:
        return wait_none()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(model_retry, "wait_exponential_jitter", no_wait)
        mp.setattr(chatapi, "wait_exponential_jitter", no_wait)
        yield


@pytest.fixture(autouse=True)
def isolate_active_model():
    """Keep the active-model contextvar from leaking across tests.

    `eval` sets the process `active_model` contextvar. A test that runs `eval`
    or `eval_set` *synchronously* in its own context (not a background thread)
    keeps that value after the call, so it leaks into later tests. A later test
    that resolves a bare model then gets the leaked model instead of
    `INSPECT_EVAL_MODEL`. Restore the contextvar after each test.
    """
    from inspect_ai.model._model import active_model_context_var

    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)


@pytest.fixture(autouse=True)
def fresh_concurrency_registry():
    """Reset the process-global concurrency registry before each test.

    Registry entries wrap anyio primitives bound to the async backend they
    were created under. `eval()` calls `init_concurrency()` at startup but
    leaves its entries behind on exit, so a fixture that runs `eval()` (on
    its own asyncio loop — e.g. building a log file for async tests) leaves
    an asyncio-bound limiter registered under the model's connection key. A
    later trio test in the same process that generates against the same model
    then reuses that limiter and crashes with "no running event loop"
    (asyncio-backend acquire under trio). Give every test the same clean
    slate an eval run gets.
    """
    from inspect_ai.util._concurrency import init_concurrency

    init_concurrency()
    yield


@pytest.fixture(scope="session")
def registrations_at_session_start() -> dict[str, object]:
    """Load extension entry points up front, then snapshot the registry.

    Registration is an import side effect, so it happens at most once per
    process: `ensure_entry_points()` re-runs `ep.load()`, but the `@hooks` /
    `@modelapi` / ... decorators inside it do not re-run once the module is in
    `sys.modules`. Nothing can re-create a registration that a test deletes.

    Loading here — before any test body — is what stops a *first* load from
    landing inside a test that has temporarily emptied the registry
    (`registry_find` re-scans entry points whenever a find comes up empty).
    That is how a registration once got created and then destroyed within a
    single test, breaking unrelated tests later on the same worker. Note that
    `ensure_test_package_installed()` calls `clear_entry_points_state()`, so a
    later full re-scan can still happen; it is harmless, because by then the
    modules are imported and re-loading them registers nothing new.

    The snapshot is what `protect_registrations` puts back, and is the only
    way back, for the same reason.

    A regression is not unit-testable — it turns on *when* the load happens
    during session startup — but it reproduces in about two seconds: restore
    the pre-45de3f534 `_without_registered_hooks` in
    tests/model/test_tool_info_lifecycle.py, then run that file's
    `test_no_hook_model_event_tools_share_raw_tool_parameters` followed by
    `tests/test_extensions.py::test_hooks`, collecting `tests/_control` first.
    That last part matters: it registers a hook at import time, so
    `init_hooks()`'s once-only first `get_all_hooks()` finds one and skips the
    entry-point load, which defers the load into the fixture.
    """
    from inspect_ai._util.entrypoints import ensure_entry_points
    from inspect_ai._util.registry import _registry

    ensure_entry_points()
    return dict(_registry)


@pytest.fixture(autouse=True)
def protect_registrations(
    registrations_at_session_start: dict[str, object],
) -> Iterator[None]:
    """Restore any registration a test removed, and error its teardown.

    Restoring stops the damage from spreading: without it a test that drops a
    registration keeps passing while unrelated later tests on the same worker
    fail, which is expensive to diagnose. Erroring names the test that did it
    (it reports as a teardown ERROR, not as a failure of the test itself).
    """
    from inspect_ai._util.registry import (
        _registry,
        registry_add,
        registry_info,
    )

    yield

    missing = registrations_at_session_start.keys() - _registry.keys()
    for key in missing:
        registered = registrations_at_session_start[key]
        registry_add(registered, registry_info(registered))
    if missing:
        pytest.fail(
            f"test removed registration(s) that existed before it ran: "
            f"{sorted(missing)}. Registration is an import side effect and "
            f"cannot be redone, so this breaks unrelated later tests on the "
            f"same worker. Restore exactly what you removed, and leave in "
            f"place anything registered while you held the registry open."
        )


@pytest.fixture
def no_model_copyreg_reducer():
    """Suspend any copyreg reducer registered for Model for the test's duration.

    Importing inspect_scout registers ``copyreg.pickle(Model, ...)`` (so Models
    can cross multiprocessing boundaries), but ``copyreg.dispatch_table`` is
    also consulted by ``copy.copy()``, which then reconstructs through memoized
    ``get_model()`` and returns a shared instance instead of a copy. Tests that
    assert ``copy()``-produces-a-distinct-``Model`` semantics (role stamping)
    fail whenever an earlier test in the same worker imported inspect_scout.
    Remove the entry for the test and restore it after, since inspect_scout's
    own pickling still needs it. Workaround until
    https://github.com/meridianlabs-ai/inspect_scout/issues/537 scopes the
    reducer to pickling.
    """
    import copyreg

    from inspect_ai.model._model import Model

    saved = copyreg.dispatch_table.pop(Model, None)
    try:
        yield
    finally:
        if saved is not None:
            copyreg.dispatch_table[Model] = saved


# ---------------------------------------------------------------------------
# Diagnostics for silent xdist worker deaths in CI ("node down: Not properly
# terminated" with no traceback or output — meridianlabs-ai/inspect_ai#232).
# Unconfirmed suspects, and the hook that makes each legible on its next
# occurrence:
#   - stray SIGALRM landing on SIG_DFL         -> _stray_sigalrm_handler
#   - hang killed by pytest-timeout's thread
#     method (os._exit(1), output swallowed
#     inside a worker)                          -> hang-dump watchdog
#   - OOM SIGKILL                               -> _report_oom_kills
# None of these changes test behavior.
# ---------------------------------------------------------------------------

_HANG_DUMP_DIR_ENV = "INSPECT_TEST_HANG_DUMP_DIR"
_HANG_DUMP_SECONDS_ENV = "INSPECT_TEST_HANG_DUMP_SECONDS"
# Per-session token baked into dump filenames (controller sets it, workers
# inherit it): the report matches on it so stale dumps left in a user-supplied
# (never-cleaned) dump dir by earlier runs are not re-printed.
_HANG_DUMP_TOKEN_ENV = "INSPECT_TEST_HANG_DUMP_TOKEN"

# Resolved in pytest_configure; 0 disables the watchdog.
_hang_dump_seconds = 0
# Keeps the dump file open for the life of the process: faulthandler writes
# to the raw fd, so the file must stay open until the timer fires.
_hang_dump_file: TextIO | None = None
_hang_dump_disabled = False
# The dump dir this process created (controller only); the only dir we may
# delete — a pre-existing user-supplied _HANG_DUMP_DIR_ENV is left alone.
_hang_dump_dir_created: str | None = None

_STRAY_SIGALRM_MESSAGE = (
    "stray SIGALRM: an alarm()/setitimer() armed by an earlier test "
    "outlived it (see meridianlabs-ai/inspect_ai#232)"
)


def _stray_sigalrm_handler(signum: int, frame: FrameType | None) -> None:
    """Turn a stray SIGALRM into a loud failure instead of silent process death.

    Several tests install temporary SIGALRM handlers (``keyboard_interrupt()``,
    test_google, test_grok).  If an armed timer outlives its test, the signal
    is delivered later when the disposition is SIG_DFL — which kills the
    worker with no output at all.  The stack is written to raw fd 2: between
    tests (capture suspended) it reaches the CI job log directly; mid-test
    under the default ``--capture=fd`` it lands in captured stderr instead,
    reaching the log via the failure report — or, when a retry wrapper
    swallows the raised error, via the ``-rA`` PASSES section (set in both
    addopts and the CI pytest command; dropping ``-rA`` loses that path).
    """
    stack = "".join(traceback.format_stack(frame))
    with contextlib.suppress(OSError):
        os.write(
            2,
            f"\n*** {_STRAY_SIGALRM_MESSAGE}. Stack at delivery:\n{stack}\n".encode(
                errors="replace"
            ),
        )
    raise RuntimeError(f"{_STRAY_SIGALRM_MESSAGE}; stack on stderr")


def _install_stray_sigalrm_handler() -> None:
    """Replace a SIG_DFL SIGALRM disposition with the loud diagnostic handler.

    Installs over SIG_DFL only, so a live pytest-timeout signal-method handler
    is never replaced.  Called at configure and re-called after every item's
    runtest protocol: pytest-timeout's signal-method cancel() restores SIG_DFL
    rather than the previously saved handler, which would otherwise leave this
    diagnostic permanently uninstalled after the first timed test.  The
    reinstall must run post-protocol, not at test setup — pytest-timeout arms
    in its own pytest_runtest_protocol hookwrapper (before setup) and cancels
    after teardown, so at setup the disposition is its handler and the SIG_DFL
    check never matches.  A conftest hookwrapper runs outermost (conftest
    wrappers register after plugin wrappers), so its post-yield executes after
    that cancel; it also covers skip-marked items, whose setup hooks never run.
    """
    if not hasattr(signal, "SIGALRM"):
        return
    # suppress ValueError defensively: signal.signal only works on the main
    # thread (pytest and xdist 3.x workers always call hooks there)
    with contextlib.suppress(ValueError):
        if signal.getsignal(signal.SIGALRM) == signal.SIG_DFL:
            signal.signal(signal.SIGALRM, _stray_sigalrm_handler)


def _resolve_hang_dump_seconds(config: pytest.Config) -> int:
    """Resolve the hang-dump watchdog threshold; 0 disables it.

    Defaults to 300s before pytest-timeout's per-test kill when one is
    configured (e.g. CI's --timeout=900 -> dump at 600s), since that kill —
    os._exit(1) from the thread method — is exactly the silent death the dump
    exists to explain.  Without a --timeout there is nothing bounding slow
    tests, so a fixed threshold would false-positive on legitimately long
    docker-based tests; stay off unless _HANG_DUMP_SECONDS_ENV forces a value.

    For timeouts <= 60s the floor puts the threshold at or past the kill
    point, so under the thread method the dump never fires (os._exit(1) wins).
    Left armed anyway: under the signal method a hang stuck in C code can
    outlive the timeout, and the dump still catches it.
    """
    env = os.environ.get(_HANG_DUMP_SECONDS_ENV)
    if env is not None:
        try:
            return max(0, int(env))
        except ValueError:
            warnings.warn(f"ignoring non-integer {_HANG_DUMP_SECONDS_ENV}={env!r}")
            return 0
    try:
        # mirror pytest-timeout's own resolution order (option -> PYTEST_TIMEOUT
        # env var -> ini key) so the watchdog arms however the timeout is set
        timeout = config.getoption("timeout")
        env_timeout = os.environ.get("PYTEST_TIMEOUT")
        if timeout is None and env_timeout is not None:
            # a set env var is used verbatim — an explicit 0 disables — and
            # never falls through to the ini key (pytest-timeout INTERNALERRORs
            # the session itself on a non-float value, before any test runs;
            # the suppress just keeps this earlier-running hook from being the
            # crash site)
            with contextlib.suppress(ValueError):
                timeout = float(env_timeout)
        elif timeout is None:
            timeout = float(config.getini("timeout") or 0) or None
    except ValueError:  # pytest-timeout not installed (or garbage ini value)
        timeout = None
    # pytest-timeout treats a non-positive timeout as disabled (a negative
    # --timeout/PYTEST_TIMEOUT is a way to switch off an ini-set timeout)
    if timeout and timeout > 0:
        return max(60, int(timeout) - 300)
    return 0


def _arm_hang_dump() -> None:
    """(Re-)arm the faulthandler watchdog.

    If the current test (plus its share of fixture work) runs longer than
    ``_hang_dump_seconds``, all thread stacks are dumped to a per-process
    file, which the controller prints at session end.  faulthandler writes to
    the raw fd, so the dump survives both the ``os._exit(1)`` that
    pytest-timeout's thread method uses and execnet's stream redirection.
    """
    global _hang_dump_file, _hang_dump_disabled
    if _hang_dump_disabled or _hang_dump_seconds <= 0:
        return
    dump_dir = os.environ.get(_HANG_DUMP_DIR_ENV)
    if dump_dir is None:
        return
    try:
        if _hang_dump_file is None:
            token = os.environ.get(_HANG_DUMP_TOKEN_ENV, "")
            worker = os.environ.get("PYTEST_XDIST_WORKER", "controller")
            _hang_dump_file = open(
                os.path.join(dump_dir, f"hang-{token}-{worker}-pid{os.getpid()}.txt"),
                "w",
            )
        faulthandler.dump_traceback_later(
            _hang_dump_seconds, exit=False, file=_hang_dump_file
        )
    except (OSError, RuntimeError, ValueError) as ex:
        # disable rather than retry-and-fail on every test, but say so: a
        # silently inert watchdog is the very failure mode it exists to fix
        _hang_dump_disabled = True
        warnings.warn(f"hang-dump watchdog disabled: {ex}")


def pytest_runtest_setup(item: pytest.Item) -> None:
    _arm_hang_dump()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Iterator[None]:
    """Reinstall the stray-SIGALRM diagnostic after each item's protocol.

    See _install_stray_sigalrm_handler for why this must run post-yield.
    """
    yield
    _install_stray_sigalrm_handler()


def pytest_exception_interact(
    node: pytest.Item | pytest.Collector,
    call: pytest.CallInfo[object],
    report: pytest.CollectReport | pytest.TestReport,
) -> None:
    # pytest's builtin faulthandler plugin cancels the (single, process-global)
    # dump timer in its tryfirst impl of this hook whenever a test fails; this
    # plain impl runs after it, so re-arming here sticks and keeps a hanging
    # teardown after a failure covered.  Re-arming only on failure — not at
    # every teardown — preserves the setup-armed deadline on the ordinary
    # path, aligned with pytest-timeout's once-per-item kill clock (a
    # per-teardown re-arm would reset the dump clock while the kill clock
    # keeps running, so a teardown hang after a 300s+ call phase would be
    # killed before it could dump).
    _arm_hang_dump()


def _report_hang_dumps() -> None:
    """Print any non-empty faulthandler hang dumps to the terminal (job log)."""
    if _hang_dump_seconds <= 0:
        # watchdog never armed this run (workers resolve the same threshold as
        # the controller, so no dump can exist from it); a user-supplied dump
        # dir may still hold stale dumps from earlier runs — don't re-print them
        return
    dump_dir = os.environ.get(_HANG_DUMP_DIR_ENV)
    if not dump_dir or not os.path.isdir(dump_dir):
        return
    prefix = f"hang-{os.environ.get(_HANG_DUMP_TOKEN_ENV, '')}-"
    for name in sorted(os.listdir(dump_dir)):
        if not name.startswith(prefix):
            continue
        try:
            with open(os.path.join(dump_dir, name)) as f:
                content = f.read().strip()
        except OSError:
            continue
        if content:
            print(
                f"\n=== hang dump {name}: a test ran longer than "
                f"{_hang_dump_seconds}s (meridianlabs-ai/inspect_ai#232 "
                "diagnostics; benign if the run passed) ==="
            )
            print(content)
            print("=== end hang dump ===")
    if _hang_dump_dir_created is not None:
        shutil.rmtree(_hang_dump_dir_created, ignore_errors=True)
        os.environ.pop(_HANG_DUMP_DIR_ENV, None)
    # drop the token so an in-process follow-up run gets a fresh one
    os.environ.pop(_HANG_DUMP_TOKEN_ENV, None)


def _report_oom_kills(exitstatus: int) -> None:
    """Grep the kernel log for OOM kills after a failed session (CI only).

    GitHub Actions does not surface OOM events, and an OOM SIGKILL of an
    xdist worker is indistinguishable in pytest output from any other silent
    worker death (a dead worker always fails the session, hence the
    exitstatus gate).  Runners allow passwordless sudo; fall back to plain
    dmesg and give up silently where neither works (e.g. locally).
    """
    if not os.environ.get("CI") or exitstatus == 0:
        return
    for cmd in (["sudo", "-n", "dmesg"], ["dmesg"]):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace", timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        pattern = re.compile(
            r"out of memory|oom[-_ ]?kill|killed process", re.IGNORECASE
        )
        matches = [line for line in result.stdout.splitlines() if pattern.search(line)]
        if matches:
            print(
                "\n=== kernel OOM events since boot — job-scoped only on "
                "ephemeral runners (meridianlabs-ai/inspect_ai#232 "
                "diagnostics; 'Memory cgroup' lines are container-local "
                "kills, e.g. from sandbox tests with memory limits, not "
                "worker deaths) ==="
            )
            for line in matches:
                print(line)
            print("=== end kernel OOM events ===")
        else:
            print(
                "\nno kernel OOM events since boot "
                "(meridianlabs-ai/inspect_ai#232 diagnostics)"
            )
        return


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "api: mark test as requiring API access")
    config.addinivalue_line("markers", "flaky: mark test as flaky/unreliable")
    config.addinivalue_line(
        "markers",
        "real_retry_wait: opt out of the fast-retry fixture and use real "
        "exponential backoff (for tests that assert on retry wait timing)",
    )
    os.environ["INSPECT_EVAL_LOG_MODEL_API"] = "1"
    # Dummy provider keys so tests that only construct a client (not call the
    # API) work without real credentials. Real keys (when present) win via
    # setdefault. api-marked tests are gated behind --runapi and skip when the
    # real key is absent, so a dummy here doesn't enable accidental API calls.
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")

    _install_stray_sigalrm_handler()
    global _hang_dump_seconds, _hang_dump_dir_created
    _hang_dump_seconds = _resolve_hang_dump_seconds(config)
    # The controller sets the hang-dump dir before xdist spawns workers (they
    # inherit it via the environment); workers see it already set.
    if _hang_dump_seconds > 0 and _HANG_DUMP_DIR_ENV not in os.environ:
        _hang_dump_dir_created = tempfile.mkdtemp(prefix="pytest-hang-dumps-")
        os.environ[_HANG_DUMP_DIR_ENV] = _hang_dump_dir_created
    if _hang_dump_seconds > 0:
        os.environ.setdefault(_HANG_DUMP_TOKEN_ENV, uuid.uuid4().hex[:8])


def pytest_collection_modifyitems(config, items):
    # Block @pytest.mark.asyncio — use @pytest.mark.anyio instead
    for item in items:
        if item.get_closest_marker("asyncio"):
            raise pytest.UsageError(
                f"{item.nodeid}: Use @pytest.mark.anyio instead of @pytest.mark.asyncio"
            )

    if config.getoption("--runtrio"):
        # --runtrio: run ONLY trio async variants (skip asyncio variants and
        # sync tests).  This must be a separate pytest invocation because
        # asyncio tests create global state (locks, etc.) that is invalid
        # under trio.
        skip_non_trio = pytest.mark.skip(reason="running trio variants only")
        for item in items:
            if "[trio" not in item.nodeid:
                item.add_marker(skip_non_trio)
    else:
        skip_trio = pytest.mark.skip(reason="need --runtrio option to run")
        for item in items:
            if "[trio" in item.nodeid:
                item.add_marker(skip_trio)

    if not config.getoption("--runslow"):
        skip_slow = pytest.mark.skip(reason="need --runslow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)

    if not config.getoption("--runapi"):
        skip_api = pytest.mark.skip(reason="need --runapi option to run")
        for item in items:
            if "api" in item.keywords:
                item.add_marker(skip_api)

    if not config.getoption("--runflaky"):
        skip_flaky = pytest.mark.skip(reason="need --runflaky option to run")
        for item in items:
            if "flaky" in item.keywords:
                item.add_marker(skip_flaky)

    # Auto-apply a 5-minute per-attempt timeout to every async test, then
    # flaky_retry(max_retries=3) for tests that hit external services (model
    # providers or Docker). The timeout is wrapped first so it sits inside the
    # retry — each attempt gets its own fresh budget. The item is passed so the
    # retry can honor xfail markers, including ones added during fixture setup
    # (as the sandbox self-check suite does): expected failures run once, and a
    # flaky pass on a retry can't turn into a hard XPASS(strict) failure.
    from test_helpers.utils import flaky_retry, with_timeout

    _timeout = with_timeout(300)
    for item in items:
        fn = item.obj
        if inspect.iscoroutinefunction(fn) and not getattr(
            fn, "_has_default_timeout", False
        ):
            fn = _timeout(fn)
        if getattr(fn, "_needs_flaky_retry", False) and not getattr(
            fn, "_flaky_retry", False
        ):
            fn = flaky_retry(max_retries=3, item=item)(fn)
        item.obj = fn


@pytest.fixture(scope="module")
def mock_s3():
    # Use port=0 so the kernel assigns a free ephemeral port. Pinning a fixed
    # port (e.g. 19100) caused EADDRINUSE flakes when other tests or leftover
    # workers held it; the prior `time.sleep(1)` was working around that race
    # rather than a server-readiness issue.
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()

    existing_env = {
        key: os.environ.get(key, None)
        for key in [
            "AWS_ENDPOINT_URL",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
        ]
    }

    os.environ["AWS_ENDPOINT_URL"] = f"http://{host}:{port}"
    os.environ["AWS_ACCESS_KEY_ID"] = "unused_id_mock_s3"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "unused_key_mock_s3"
    os.environ["AWS_DEFAULT_REGION"] = "us-west-1"

    # Drop any cached fsspec S3FileSystem instance from a previous module's
    # mock_s3 fixture — its baked-in client points at a moto server that
    # was already torn down, and reuse causes EndpointConnectionError.
    from s3fs import S3FileSystem  # type: ignore

    S3FileSystem.clear_instance_cache()

    s3_client = boto3.client("s3")
    s3_client.create_bucket(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "us-west-1"},
    )

    yield

    # Unfortunately, we can't just throw away moto after the test,
    # because there is caching of S3 bucket state (e.g. ownership)
    # somewhere in s3fs or boto. So we have to go through
    # the charade of emptying and deleting the mocked bucket.
    s3 = boto3.resource("s3")
    s3_bucket = s3.Bucket("test-bucket")
    bucket_versioning = s3.BucketVersioning("test-bucket")
    if bucket_versioning.status == "Enabled":
        s3_bucket.object_versions.delete()
    else:
        s3_bucket.objects.all().delete()

    s3_client.delete_bucket(Bucket="test-bucket")

    server.stop()
    # Clear again on teardown so a later non-mock_s3 caller doesn't grab
    # the stale instance either.
    S3FileSystem.clear_instance_cache()
    for key, value in existing_env.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value


def pytest_sessionfinish(session, exitstatus):
    # Cancel the hang-dump watchdog (in every process) so a timer armed by the
    # last test can't fire during interpreter shutdown and write a bogus dump.
    global _hang_dump_file
    faulthandler.cancel_dump_traceback_later()
    if _hang_dump_file is not None:
        dump_path = _hang_dump_file.name
        _hang_dump_file.close()
        _hang_dump_file = None
        # each process owns its uniquely-named (pid-suffixed) dump file, so
        # removing it when empty is safe — and keeps a user-supplied
        # (never-cleaned) dump dir from accumulating one empty file per run
        with contextlib.suppress(OSError):
            if os.path.getsize(dump_path) == 0:
                os.remove(dump_path)

    # When running under pytest-xdist, this hook fires once per worker as well
    # as on the controller. Letting every worker race to uninstall the test
    # package corrupts the install for sibling workers; only the controller
    # (which has no `workerinput` attribute on its config) should clean up.
    if hasattr(session.config, "workerinput"):
        return

    _report_hang_dumps()
    _report_oom_kills(exitstatus)

    if importlib.util.find_spec("inspect_package"):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "uninstall", "-y", "inspect_package"]
            )
            shutil.rmtree("tests/test_package/build")
            shutil.rmtree("tests/test_package/inspect_package.egg-info")
        except subprocess.CalledProcessError as ex:
            warnings.warn(f"Error occurred uninstalling inspect_package: {ex}")

        except BaseException:
            pass
