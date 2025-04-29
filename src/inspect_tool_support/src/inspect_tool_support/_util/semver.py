from packaging.version import Version as PyPiVersion
from semver import Version as SemVerVersion


def pep440_to_semver(pep440_version: str) -> SemVerVersion:
    """Convert a PEP 440 version string to a SemVer-compatible version string."""
    p = PyPiVersion(pep440_version)

    major = p.release[0] if len(p.release) > 0 else 0
    minor = p.release[1] if len(p.release) > 1 else 0
    patch = p.release[2] if len(p.release) > 2 else 0

    if p.pre is not None:
        pre_type = "a" if p.pre[0] == "a" else "b" if p.pre[0] == "b" else "rc"
        pre_num = p.pre[1]
        prerelease = f"{pre_type}{pre_num}"
        return SemVerVersion(
            major=major, minor=minor, patch=patch, prerelease=prerelease
        )
    elif p.dev is not None:
        return SemVerVersion(major=major, minor=minor, patch=patch, build=f"dev{p.dev}")
    elif p.post is not None:
        return SemVerVersion(
            major=major, minor=minor, patch=patch, build=f"post{p.post}"
        )
    else:
        return SemVerVersion(major=major, minor=minor, patch=patch)
