import json
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
    dist_a.read_text.return_value = None  # not an editable install

    # dist-b: has a file whose realpath DOES match fake_origin
    file_b = MagicMock()
    file_b.locate.return_value = fake_origin
    dist_b = MagicMock()
    dist_b.files = [file_b]
    dist_b.read_text.return_value = None

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


def test_get_distribution_for_object_fast_path_falls_through_on_shadowing():
    """A same-named distribution that doesn't ship the module falls through."""
    fake_origin = "/fake/site-packages/ns_pkg/task_b.py"

    # A distribution literally named "ns_pkg" exists but ships unrelated files.
    file_shadow = MagicMock()
    file_shadow.locate.return_value = "/fake/site-packages/ns_pkg/other.py"
    dist_shadow = MagicMock()
    dist_shadow.files = [file_shadow]
    dist_shadow.read_text.return_value = None  # not an editable install

    # The distribution that actually ships the module.
    file_b = MagicMock()
    file_b.locate.return_value = fake_origin
    dist_b = MagicMock()
    dist_b.files = [file_b]
    dist_b.read_text.return_value = None

    fake_spec = MagicMock()
    fake_spec.origin = fake_origin

    def fake_from_name(name: str):
        if name == "ns_pkg":
            return dist_shadow
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
            return_value={"ns_pkg": ["ns_pkg", "dist-b"]},
        ),
        patch(
            "inspect_ai._util.package.os.path.realpath", side_effect=os.path.realpath
        ),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist_b


def test_get_distribution_for_object_fast_path_trusts_name_when_files_unknown():
    """A same-named distribution with no RECORD is trusted on the name match."""
    fake_spec = MagicMock()
    fake_spec.origin = "/fake/site-packages/some_pkg/__init__.py"

    dist = MagicMock()
    dist.files = None  # e.g. an editable install without a RECORD

    obj = MagicMock()
    obj.__module__ = "some_pkg"

    with (
        patch(
            "inspect_ai._util.package.importlib.util.find_spec", return_value=fake_spec
        ),
        patch("inspect_ai._util.package.Distribution.from_name", return_value=dist),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist


def _editable_dist(source_root: str, subdirectory: str | None = None) -> MagicMock:
    """A MagicMock distribution whose RECORD lists no sources (editable install)."""
    dist = MagicMock()
    # editable RECORDs list only the .pth and metadata, never the source tree
    dist.files = []
    direct_url = {"url": "file://%s" % source_root, "dir_info": {"editable": True}}
    if subdirectory is not None:
        direct_url["subdirectory"] = subdirectory
    dist.read_text.return_value = json.dumps(direct_url)
    return dist


def test_get_distribution_for_object_editable_fast_path():
    """Editable install (import == dist name) verifies via the source root."""
    source_root = "/fake/workspace/my_pkg"
    fake_spec = MagicMock()
    fake_spec.origin = f"{source_root}/src/my_pkg/task.py"

    dist = _editable_dist(source_root)

    obj = MagicMock()
    obj.__module__ = "my_pkg.task"

    with (
        patch(
            "inspect_ai._util.package.importlib.util.find_spec", return_value=fake_spec
        ),
        patch("inspect_ai._util.package.Distribution.from_name", return_value=dist),
        patch(
            "inspect_ai._util.package.os.path.realpath", side_effect=os.path.realpath
        ),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist


def test_get_distribution_for_object_editable_namespace_disambiguates_by_root():
    """Editable namespace dists are disambiguated by their source roots."""
    fake_origin = "/fake/workspace/ns-task-b/src/ns_pkg/task_b.py"

    dist_a = _editable_dist("/fake/workspace/ns-task-a")  # wrong root
    dist_b = _editable_dist("/fake/workspace/ns-task-b")  # contains fake_origin

    fake_spec = MagicMock()
    fake_spec.origin = fake_origin

    def fake_from_name(name: str):
        if name == "ns_pkg":
            raise PackageNotFoundError(name)
        if name == "ns-task-a":
            return dist_a
        if name == "ns-task-b":
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
            return_value={"ns_pkg": ["ns-task-a", "ns-task-b"]},
        ),
        patch(
            "inspect_ai._util.package.os.path.realpath", side_effect=os.path.realpath
        ),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist_b


def test_get_distribution_for_object_editable_namespace_honors_subdirectory():
    """Editable namespace dists sharing a repo root split by `subdirectory`."""
    repo_root = "/fake/workspace"
    fake_origin = f"{repo_root}/packages/b/src/ns_pkg/task_b.py"

    # Both record the same repo root, distinguished only by `subdirectory`.
    dist_a = _editable_dist(repo_root, subdirectory="packages/a")
    dist_b = _editable_dist(repo_root, subdirectory="packages/b")

    fake_spec = MagicMock()
    fake_spec.origin = fake_origin

    def fake_from_name(name: str):
        if name == "ns_pkg":
            raise PackageNotFoundError(name)
        if name == "ns-task-a":
            return dist_a
        if name == "ns-task-b":
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
            return_value={"ns_pkg": ["ns-task-a", "ns-task-b"]},
        ),
        patch(
            "inspect_ai._util.package.os.path.realpath", side_effect=os.path.realpath
        ),
    ):
        result = get_distribution_for_object(obj)

    assert result is dist_b
