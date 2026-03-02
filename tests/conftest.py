import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
import time
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


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "api: mark test as requiring API access")
    config.addinivalue_line("markers", "flaky: mark test as flaky/unreliable")
    os.environ["INSPECT_EVAL_LOG_MODEL_API"] = "1"


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
            if "[trio]" not in item.nodeid:
                item.add_marker(skip_non_trio)
    else:
        skip_trio = pytest.mark.skip(reason="need --runtrio option to run")
        for item in items:
            if "[trio]" in item.nodeid:
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


@pytest.fixture(scope="module")
def mock_s3():
    server = ThreadedMotoServer(port=19100)
    server.start()

    # Give the server a moment to start up
    time.sleep(1)

    existing_env = {
        key: os.environ.get(key, None)
        for key in [
            "AWS_ENDPOINT_URL",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
        ]
    }

    os.environ["AWS_ENDPOINT_URL"] = "http://127.0.0.1:19100"
    os.environ["AWS_ACCESS_KEY_ID"] = "unused_id_mock_s3"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "unused_key_mock_s3"
    os.environ["AWS_DEFAULT_REGION"] = "us-west-1"

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
    for key, value in existing_env.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value


def pytest_sessionfinish(session, exitstatus):
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
