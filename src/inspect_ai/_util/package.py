import importlib.util
import inspect
import json
import os
import site
import sys
from functools import lru_cache
from importlib.metadata import (
    Distribution,
    PackageNotFoundError,
    packages_distributions,
)
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname

from pydantic import BaseModel, Field


def get_installed_package_name(obj: Any) -> str | None:
    # special handling for built-in functions
    if inspect.isbuiltin(obj):
        # try to get the module name
        if getattr(obj, "__module__") is not None:
            module_name = obj.__module__
            if module_name:
                return module_name.split(".")[0]

        # try to get the class that defines this method
        if hasattr(obj, "__objclass__"):
            cls = obj.__objclass__
        elif hasattr(obj, "__self__"):
            cls = type(obj.__self__)
        else:
            return None

        for base_cls in inspect.getmro(cls):
            module = inspect.getmodule(base_cls)
            if module:
                return module.__name__.split(".")[0]

    # get the module of the object
    module = inspect.getmodule(obj)
    if module is None:
        return None

    # find the origin (install path) for the module
    module_name = module.__name__
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return None
    if spec is None or spec.origin is None:
        return None

    # check if this is a package (either in library or installed editable)
    package_name = module_name.split(".")[0]
    if package_path_is_in_site_packages(spec.origin):
        return package_name
    if package_is_installed_editable(package_name):
        return package_name
    else:
        return None


@lru_cache(maxsize=None)
def package_path_is_in_site_packages(path: str) -> bool:
    path = path.lower()
    return (
        any(path.startswith(p.lower()) for p in site.getsitepackages())
        or path.startswith(site.getusersitepackages().lower())
        or any(
            "site-packages" in p.lower() and path.startswith(p.lower())
            for p in sys.path
        )
    )


class VcsInfo(BaseModel):
    vcs: Literal["git", "hg", "bzr", "svn"]
    commit_id: str
    requested_revision: str | None = None
    resolved_revision: str | None = None


class ArchiveInfo(BaseModel):
    hash: str | None = None  # Deprecated format: "<algorithm>=<hash>"
    hashes: dict[str, str] | None = None  # New format: {"sha256": "<hex>"}


class DirInfo(BaseModel):
    editable: bool = Field(default=False)  # Default: False


class DirectUrl(BaseModel):
    url: str
    vcs_info: VcsInfo | None = None
    archive_info: ArchiveInfo | None = None
    dir_info: DirInfo | None = None
    subdirectory: str | None = None


@lru_cache(maxsize=None)
def get_package_direct_url(package: str) -> DirectUrl | None:
    """Retrieve the PEP 610 direct_url.json for an installed distribution.

    `direct_url.json` is a metadata file created by pip (and other Python package
    installers) in the .dist-info directory of installed packages. It's defined by
    PEP 610 and records how a package was installed when it came from a direct URL
    source rather than PyPI.

    When is it created?

    This file is created when installing packages via:
    - Git URLs: pip install git+https://github.com/user/repo.git
    - Local directories: pip install /path/to/package
    - Editable installs: pip install -e /path/to/package or pip install -e git+...
    - Direct archive URLs: pip install https://example.com/package.tar.gz
    """
    try:
        distribution = Distribution.from_name(package)
    except (ValueError, PackageNotFoundError):
        return None
    return get_distribution_direct_url(distribution)


def get_distribution_direct_url(distribution: Distribution) -> DirectUrl | None:
    """Parse the PEP 610 direct_url.json of an installed distribution (if any)."""
    if (json_text := distribution.read_text("direct_url.json")) is None:
        return None
    try:
        return DirectUrl.model_validate_json(json_text)
    except (json.JSONDecodeError, ValueError):
        return None


def get_distribution_for_object(obj: Any) -> Distribution | None:
    """Find the installed distribution that provides `obj`'s defining module.

    Unlike `get_installed_package_name` (which returns the top-level *import*
    package name), this returns the actual installed *distribution*. It handles
    namespace packages whose import name is shared across several distributions
    (e.g. a uv workspace where each task is its own distribution under a shared
    `foo` namespace) by locating the distribution whose installed files include
    the object's module file.
    """
    module_name = getattr(obj, "__module__", None)
    if not module_name:
        return None
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    origin = os.path.realpath(spec.origin)

    # Fast path: a distribution named like the top-level import package
    # (the common case where import name == distribution name). Confirm it
    # actually ships the module before trusting it — a local module or a
    # namespace subpackage can share a top-level name with an unrelated
    # installed distribution, in which case we must fall through to the scan.
    top_level = module_name.split(".")[0]
    try:
        distribution = Distribution.from_name(top_level)
    except PackageNotFoundError:
        pass
    else:
        # Trust the name match unless the distribution lists its files and
        # they positively exclude this module (the namespace / shadowing case).
        if distribution.files is None or _distribution_ships_origin(
            distribution, origin
        ):
            return distribution

    # Namespace package / name mismatch: among the distributions that provide
    # the top-level import name, find the one whose files include this module.
    for dist_name in packages_distributions().get(top_level, []):
        try:
            distribution = Distribution.from_name(dist_name)
        except PackageNotFoundError:
            continue
        if _distribution_ships_origin(distribution, origin):
            return distribution
    return None


def _distribution_ships_origin(distribution: Distribution, origin: str) -> bool:
    """Whether `distribution` provides the module file at `origin`.

    `origin` must already be a realpath. Handles both regular installs (the
    module file is listed in the distribution's ``RECORD``) and editable
    installs (whose ``RECORD`` lists only a ``.pth`` and metadata, not the
    source tree — there we test whether ``origin`` lives under the editable
    source root recorded in PEP 610 ``direct_url.json``).
    """
    for file in distribution.files or []:
        try:
            if os.path.realpath(str(file.locate())) == origin:
                return True
        except Exception:
            continue
    editable_root = _editable_source_root(distribution)
    return editable_root is not None and _path_is_within(origin, editable_root)


def _editable_source_root(distribution: Distribution) -> str | None:
    """The realpath of an editable install's source root, else None.

    Returns None for non-editable installs and for editable installs whose
    `direct_url.json` records a non-local (e.g. VCS) URL.
    """
    direct_url = get_distribution_direct_url(distribution)
    if (
        direct_url is None
        or direct_url.dir_info is None
        or not direct_url.dir_info.editable
    ):
        return None
    parsed = urlparse(direct_url.url)
    if parsed.scheme != "file":
        return None
    root = url2pathname(parsed.path)
    # PEP 610 allows `subdirectory` (relative to the URL root) for local dirs
    # too; without it every workspace member shares the repo root and namespace
    # disambiguation can't tell them apart.
    if direct_url.subdirectory:
        root = os.path.join(root, direct_url.subdirectory)
    return os.path.realpath(root)


def _path_is_within(path: str, root: str) -> bool:
    """Whether realpath `path` is `root` itself or nested under it."""
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # different drives / mixed absolute-relative — not comparable
        return False


def package_is_installed_editable(package: str) -> bool:
    return (
        (direct_url := get_package_direct_url(package)) is not None
        and direct_url.dir_info is not None
        and direct_url.dir_info.editable
    )
