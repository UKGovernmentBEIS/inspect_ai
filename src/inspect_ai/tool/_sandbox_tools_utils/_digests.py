"""Read/write/lookup for the vendored sandbox-tools ``SHA256SUMS`` file.

The file pins one SHA256 digest per published sandbox-tools artifact (the four
arch × libc variants for the version in ``sandbox_tools_version.txt``) in
standard ``sha256sum`` format, so every consumer of the S3 bucket can verify
fetched bytes against digests committed in git. It is rewritten only by
``upload_to_s3.py`` and must land in the same PR as a version bump. See
``src/inspect_sandbox_tools/design/BINARY_INTEGRITY.md``.

Stdlib-only on purpose: like ``_build_config.py``, this module must be
importable both as part of the installed package and as a plain file (e.g. by
``upload_to_s3.py`` run outside an installed ``inspect_ai``).
"""

import re
from pathlib import Path

SHA256SUMS_PATH = Path(__file__).parent / "SHA256SUMS"

# Standard sha256sum line, tolerating the optional `*` binary marker before
# the filename (as sha256sum -b emits and the restic resolver accepts).
_ENTRY_PATTERN = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)$")


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse sha256sum-format text into a filename -> hex-digest mapping.

    Digests are lowercased. Lines that do not match the sha256sum format
    (including blank lines) are ignored.
    """
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = _ENTRY_PATTERN.match(line.strip())
        if match:
            entries[match.group(2)] = match.group(1).lower()
    return entries


def read_sha256sums(path: Path = SHA256SUMS_PATH) -> dict[str, str]:
    """Read and parse the vendored ``SHA256SUMS`` file.

    Raises:
        RuntimeError: If the file is missing or unreadable (corrupt install);
            same contract as the restic resolver's ``_read_sha256sums``.
    """
    try:
        text = path.read_text()
    except OSError as ex:
        raise RuntimeError(
            f"Vendored SHA256SUMS unreadable at {path} (corrupt installation?): {ex}"
        ) from ex
    return parse_sha256sums(text)


def lookup_digest(filename: str, path: Path = SHA256SUMS_PATH) -> str:
    """Return the pinned SHA256 digest for ``filename``.

    Raises:
        RuntimeError: If the sums file is unreadable or has no entry for
            ``filename``. The version file and sums file are committed
            together, so a missing entry means a corrupt install or a
            desynced commit — never a situation where fetching unverified
            bytes is the right answer.
    """
    digest = read_sha256sums(path).get(filename)
    if digest is None:
        raise RuntimeError(
            f"No SHA256 entry for {filename} in {path}. This indicates a "
            f"corrupt installation or a desynced commit (the sums file is "
            f"rewritten by upload_to_s3.py alongside every version bump); "
            f"refusing to download unverified bytes."
        )
    return digest


def write_sha256sums(entries: dict[str, str], path: Path = SHA256SUMS_PATH) -> None:
    """Write ``entries`` in standard sha256sum format, sorted by filename."""
    lines = [f"{digest}  {filename}" for filename, digest in sorted(entries.items())]
    path.write_text("\n".join(lines) + "\n")
