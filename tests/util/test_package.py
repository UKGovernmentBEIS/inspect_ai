import os

import httpx
import numpy as np
import pytest
from test_helpers.tools import addition, list_files

import inspect_ai
from inspect_ai._util.package import get_installed_package_name


def test_numpy_package():
    assert get_installed_package_name(np.array) == "numpy"
    assert get_installed_package_name(np.random.rand) == "numpy"


def test_httpx_package():
    assert get_installed_package_name(httpx.get) == "httpx"
    assert get_installed_package_name(httpx.Client) == "httpx"


def test_builtin_module():
    assert get_installed_package_name(os.path.join) is None
    assert get_installed_package_name(list.append) is None


def test_inspect_ai_package():
    assert get_installed_package_name(inspect_ai.eval) == "inspect_ai"


def test_local_module():
    assert get_installed_package_name(addition) is None
    assert get_installed_package_name(list_files) is None


def test_local_function():
    def local_func():
        pass

    assert get_installed_package_name(local_func) is None


def test_local_class():
    class LocalClass:
        pass

    assert get_installed_package_name(LocalClass) is None


def test_none_input():
    assert get_installed_package_name(None) is None


@pytest.mark.parametrize("value", [42, "string", [1, 2, 3]])
def test_builtin_types(value):
    assert get_installed_package_name(value) is None
