import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
import warnings

import boto3
import pytest
from moto.server import ThreadedMotoServer

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


@pytest.fixture(autouse=True)
def _reset_eval_process_globals():
    """Reset process-lifetime eval state so tests don't observe each other.

    `init_concurrency()` is idempotent (the registry is intentionally
    process-lifetime so concurrent `eval_async()` calls share adaptive
    controllers) and `init_refusal_tracking()` no longer zeroes the shared
    refusal counter — so we reset both here to keep per-test isolation.
    """
    import inspect_ai.log._refusal as _refusal
    from inspect_ai.util._concurrency import reset_concurrency

    reset_concurrency()
    _refusal._refusal_count = 0


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
    # retry — each attempt gets its own fresh budget.
    from test_helpers.utils import flaky_retry, with_timeout

    _timeout = with_timeout(300)
    _retry = flaky_retry(max_retries=3)
    for item in items:
        fn = item.obj
        if inspect.iscoroutinefunction(fn) and not getattr(
            fn, "_has_default_timeout", False
        ):
            fn = _timeout(fn)
        if getattr(fn, "_needs_flaky_retry", False) and not getattr(
            fn, "_flaky_retry", False
        ):
            fn = _retry(fn)
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
    # When running under pytest-xdist, this hook fires once per worker as well
    # as on the controller. Letting every worker race to uninstall the test
    # package corrupts the install for sibling workers; only the controller
    # (which has no `workerinput` attribute on its config) should clean up.
    if hasattr(session.config, "workerinput"):
        return

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
