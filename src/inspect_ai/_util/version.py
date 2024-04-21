from importlib.metadata import version

import semver

from .error import module_version_error


def verify_required_version(feature: str, package: str, version: str) -> None:
    if not has_required_version(package, version):
        raise module_version_error(feature, package, version)


def has_required_version(package: str, required_version: str) -> bool:
    if semver.Version.parse(version(package)).compare(required_version) >= 0:
        return True
    else:
        return False
