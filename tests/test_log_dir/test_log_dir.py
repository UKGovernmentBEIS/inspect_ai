import os
import shutil

import pytest

from inspect_ai import eval_async


@pytest.fixture(scope="session")
def base_tmp_dir():
    base_dir = "tmp_testing_log_dir"
    yield base_dir
    # Cleanup after all tests are done
    # TODO this does not work when the logs are saved in a different directory i.e. the test failed.
    shutil.rmtree(base_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize("log_dir", ["logs", "logs/my_custom_location"])
async def test_log_dir(log_dir, base_tmp_dir):
    log_dir = str(os.path.join(base_tmp_dir, log_dir))
    await eval_async(
        ["tests/test_log_dir/example_task"], model="mockllm/model", log_dir=log_dir
    )
    assert os.path.exists(log_dir)
    assert (
        len(os.listdir(log_dir)) >= 1
    )  # as currently a empty dir is created before cwd to task dir is called.
