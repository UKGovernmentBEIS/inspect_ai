import importlib.util
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


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--runapi", action="store_true", default=False, help="run API tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "api: mark test as requiring API access")


def pytest_collection_modifyitems(config, items):
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
