import re
from importlib.metadata import version

import semver

from .error import module_max_version_error, module_version_error


def verify_required_version(feature: str, package: str, version: str) -> None:
    if not has_required_version(package, version):
        raise module_version_error(feature, package, version)


def verify_max_version(feature: str, package: str, max_version: str) -> None:
    if _installed_version(package).compare(max_version) > 0:
        raise module_max_version_error(feature, package, max_version)


def has_required_version(package: str, required_version: str) -> bool:
    if _installed_version(package).compare(required_version) >= 0:
        return True
    else:
        return False


def _installed_version(package: str) -> semver.Version:
    """The installed version, which is PEP 440 and not always valid SemVer.

    Released versions ("0.4.46") parse as-is. Development and local builds
    ("0.4.47.dev19", "0.3.262.dev32+g5ea5c5ce1") are not SemVer, so
    everything after the release triple is folded into a prerelease tag
    (plus build metadata for a local segment) — preserving PEP 440's
    ordering, where a dev build precedes the release it is building toward.
    """
    raw = version(package)
    try:
        return semver.Version.parse(raw)
    except ValueError:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)[.\-]?(.+)$", raw)
        if match is None:
            raise
        major, minor, patch, rest = match.groups()
        pre, _, build = rest.partition("+")
        return semver.Version(
            major=int(major),
            minor=int(minor),
            patch=int(patch),
            prerelease=pre.replace(".", "-") or None,
            build=build or None,
        )
