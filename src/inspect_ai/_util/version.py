from importlib.metadata import version

import semver

from .error import module_max_version_error, module_version_error


def verify_required_version(feature: str, package: str, version: str) -> None:
    if not has_required_version(package, version):
        raise module_version_error(feature, package, version)


def verify_max_version(feature: str, package: str, max_version: str) -> None:
    if semver.Version.parse(version(package)).compare(max_version) > 0:
        raise module_max_version_error(feature, package, max_version)


def has_required_version(package: str, required_version: str) -> bool:
    if semver.Version.parse(version(package)).compare(required_version) >= 0:
        return True
    else:
        return False
