import os
import subprocess
import sys
import time

import pytest
from moto.server import ThreadedMotoServer

sys.path.append(os.path.join(os.path.dirname(__file__), "helpers"))

try:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "uninstall", "-y", "inspect_package"]
    )
except subprocess.CalledProcessError:
    pass


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
        for key in ["AWS_ENDPOINT_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    }

    os.environ["AWS_ENDPOINT_URL"] = "http://127.0.0.1:19100"
    os.environ["AWS_ACCESS_KEY_ID"] = "unused_id_mock_s3"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "unused_key_mock_s3"

    yield

    for key, value in existing_env.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value

    server.stop()
