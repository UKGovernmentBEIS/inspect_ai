import importlib.util
import os
from importlib.metadata import (
    Distribution,
    PackageNotFoundError,
    packages_distributions,
)
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._package import ArchiveInfo as ArchiveInfo
from inspect_ai.core._package import DirectUrl as DirectUrl
from inspect_ai.core._package import DirInfo as DirInfo
from inspect_ai.core._package import VcsInfo as VcsInfo
from inspect_ai.core._package import (
    get_distribution_direct_url as get_distribution_direct_url,
)
from inspect_ai.core._package import (
    get_installed_package_name as get_installed_package_name,
)
from inspect_ai.core._package import get_package_direct_url as get_package_direct_url
from inspect_ai.core._package import (
    package_is_installed_editable as package_is_installed_editable,
)
from inspect_ai.core._package import (
    package_path_is_in_site_packages as package_path_is_in_site_packages,
)

# End of backward-compatible re-exports.


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
