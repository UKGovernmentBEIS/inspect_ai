import os
from importlib.metadata import PackageNotFoundError
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pydantic
import pytest
from test_helpers.tools import addition, list_files

import inspect_ai
from inspect_ai._util.package import (
    get_distribution_for_object,
    get_installed_package_name,
)


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


# ---------------------------------------------------------------------------
# Tests for get_distribution_for_object
# ---------------------------------------------------------------------------


def test_get_distribution_for_object_fast_path():
    """Fast path: top-level import name == distribution name (e.g. pydantic)."""
    dist = get_distribution_for_object(pydantic.BaseModel)
    assert dist is not None
    assert dist.name.replace("-", "_").lower() == "pydantic"


def test_get_distribution_for_object_no_module():
    """An object with no resolvable module returns None."""
    obj = object()
    # object().__module__ == "builtins"; find_spec("builtins").origin is None
    # or find_spec may return a spec with no origin — either way we get None.
    result = get_distribution_for_object(obj)
    assert result is None


def test_get_distribution_for_object_namespace_package():
    """Namespace package: import name is NOT a distribution; fall through to file scan."""
    # We construct a fake module origin that matches only dist-b's files.
    fake_origin = "/fake/site-packages/ns_pkg/task_b.py"

    # dist-a: has a file whose realpath does NOT match fake_origin
    file_a = MagicMock()
    file_a.locate.return_value = "/fake/site-packages/ns_pkg/task_a.py"
    dist_a = MagicMock()
    dist_a.files = [file_a]

    # dist-b: has a file whose realpath DOES match fake_origin
    file_b = MagicMock()
    file_b.locate.return_value = fake_origin
    dist_b = MagicMock()
    dist_b.files = [file_b]

    fake_spec = MagicMock()
    fake_spec.origin = fake_origin

    def fake_from_name(name: str):
        if name == "ns_pkg":
            raise PackageNotFoundError(name)
        if name == "dist-a":
            return dist_a
        if name == "dist-b":
            return dist_b
        raise PackageNotFoundError(name)

    obj = MagicMock()
    obj.__module__ = "ns_pkg.task_b"

    with (
        patch(
            "inspect_ai._util.package.importlib.util.find_spec", return_value=fake_spec
        ),
        patch(
            "inspect_ai._util.package.Distribution.from_name",
            side_effect=fake_from_name,
        ),
        patch(
            "inspect_ai._util.package.packages_distributions",
            return_value={"ns_pkg": ["dist-a", "dist-b"]},
        ),
        patch(
            "inspect_ai._util.package.os.path.realpath", side_effect=os.path.realpath
        ),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist_b
