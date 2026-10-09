#!/usr/bin/env python3
"""
Python script to tag a git repository, build a package, and upload to PyPI.

Usage:
    # Release commands (default)
    python pypi-release.py <tag_name>
    python pypi-release.py release <tag_name>
    python pypi-release.py release <tag_name> --skip-confirmation
    python pypi-release.py release <tag_name> --branch develop
    python pypi-release.py release <tag_name> --dry-run
    python pypi-release.py release <tag_name> --skip-sandbox-download

    # Sandbox tools download command
    python pypi-release.py sandbox-tools-download
    python pypi-release.py sandbox-tools-download --dry-run

    # Non-interactive steps for the publish workflow (.github/workflows/publish.yml)
    python pypi-release.py prepare
    python pypi-release.py verify-dist <version>
    python pypi-release.py verify-parity <version>
    python pypi-release.py skip-published <version>

    # Release PR check (.github/workflows/release-pr-checks.yml)
    python pypi-release.py verify-sandbox-tools-published
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

SANDBOX_TOOLS_UTILS_DIR = Path("src/inspect_ai/tool/_sandbox_tools_utils")
SHA256SUMS_FILE = SANDBOX_TOOLS_UTILS_DIR / "SHA256SUMS"
SANDBOX_TOOLS_BASE_URL = "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com"


def setup_logging(name: str) -> None:
    """Set up logging to both console and file."""
    log_dir = Path("release-logs")
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    log_file = log_dir / f"{name}_{timestamp}.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    logging.info(f"Logging to {log_file}")


def run_command(
    cmd: list, capture_output: bool = False, check: bool = True, dry_run: bool = False
) -> Optional[subprocess.CompletedProcess]:
    """Run a command using subprocess with list arguments for safety."""
    try:
        logging.info(f"Running: {' '.join(cmd)}")

        if dry_run:
            logging.info("[DRY RUN] Would execute the above command")
            return None

        result = subprocess.run(
            cmd, capture_output=capture_output, text=True, check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running command: {' '.join(cmd)}")
        logging.error(f"Error message: {e.stderr if e.stderr else str(e)}")
        sys.exit(1)
    except FileNotFoundError:
        logging.error(f"Command not found: {cmd[0]}")
        sys.exit(1)


def sha256_of_file(path: Path) -> str:
    """Compute the SHA256 hex digest of a file's contents."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_pinned_digests() -> Dict[str, str]:
    """Read the vendored SHA256SUMS into a filename -> digest mapping.

    The file pins one digest per published sandbox-tools artifact and is
    rewritten by upload_to_s3.py alongside every version bump. Tolerates the
    optional `*` binary marker, like sha256sum itself.
    """
    if not SHA256SUMS_FILE.exists():
        logging.error(f"Sandbox tools digest file not found: {SHA256SUMS_FILE}")
        sys.exit(1)

    entries: Dict[str, str] = {}
    pattern = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)$")
    for line in SHA256SUMS_FILE.read_text().splitlines():
        match = pattern.match(line.strip())
        if match:
            entries[match.group(2)] = match.group(1).lower()

    if not entries:
        logging.error(f"No digest entries found in {SHA256SUMS_FILE}")
        sys.exit(1)

    return entries


def get_sandbox_tools_version() -> str:
    """Read the required sandbox tools version from the version file."""
    version_file = SANDBOX_TOOLS_UTILS_DIR / "sandbox_tools_version.txt"

    if not version_file.exists():
        logging.error(f"Sandbox tools version file not found: {version_file}")
        sys.exit(1)

    try:
        version = version_file.read_text().strip()
        if not version:
            logging.error("Sandbox tools version file is empty")
            sys.exit(1)
        logging.info(f"Required sandbox tools version: {version}")
        return version
    except Exception as e:
        logging.error(f"Error reading sandbox tools version: {e}")
        sys.exit(1)


def clean_sandbox_tools_directory() -> None:
    """Remove all files from the binaries directory to ensure only one version exists."""
    binaries_dir = Path("src/inspect_ai/binaries")

    if not binaries_dir.exists():
        logging.info(f"Binaries directory does not exist: {binaries_dir}")
        return

    # List and remove all files
    removed_files = []
    for file in binaries_dir.iterdir():
        if file.is_file():
            removed_files.append(file.name)
            file.unlink()

    if removed_files:
        logging.info(f"Removed old sandbox tools: {', '.join(removed_files)}")
    else:
        logging.info("No old sandbox tools to remove")


def check_sandbox_tools_exist(version: str, digests: Dict[str, str]) -> bool:
    """Check if both platform binaries exist with their pinned digests.

    Compares digests, not sizes: a stale or tampered local file must be
    treated as missing (cleaned and re-downloaded), never silently bundled
    into the wheel.
    """
    binaries_dir = Path("src/inspect_ai/binaries")

    if not binaries_dir.exists():
        return False

    for platform in ["amd64", "arm64"]:
        filename = f"inspect-sandbox-tools-{platform}-v{version}"
        binary = binaries_dir / filename
        if not binary.exists():
            logging.info(f"Sandbox tools v{version}: {filename} missing")
            return False
        expected = digests.get(filename)
        if expected is None:
            logging.error(f"No digest entry for {filename} in {SHA256SUMS_FILE}")
            sys.exit(1)
        if sha256_of_file(binary) != expected:
            logging.info(
                f"Sandbox tools v{version}: {filename} does not match its pinned "
                f"digest; treating as missing"
            )
            return False

    logging.info(f"✓ Sandbox tools v{version} already downloaded and verified")
    return True


def download_file(
    url: str, dest_path: Path, expected_sha256: str, dry_run: bool = False
) -> bool:
    """Download a file from URL, verifying it against the expected digest.

    Streams to a sibling tempfile, hashing while streaming, and renames into
    place only after the digest has been verified, so a failed or corrupted
    download never leaves a file at dest_path.
    """
    if dry_run:
        logging.info(f"[DRY RUN] Would download {url} to {dest_path}")
        return True

    logging.info(f"Downloading {url}")
    logging.info(f"         to {dest_path}")

    # Create parent directory if needed
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = dest_path.parent / (dest_path.name + ".partial")
    try:
        hasher = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=120) as response:
            total_size = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while chunk := response.read(1 << 20):
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = min(downloaded * 100 / total_size, 100)
                        print(
                            f"\r  Progress: {percent:.1f}% "
                            f"({downloaded / (1024 * 1024):.1f}/"
                            f"{total_size / (1024 * 1024):.1f} MB)",
                            end="",
                            flush=True,
                        )
        print()  # New line after progress

        actual = hasher.hexdigest()
        if actual != expected_sha256:
            logging.error(
                f"Digest mismatch for {url}: expected {expected_sha256}, got "
                f"{actual}. This may indicate a compromised or corrupted "
                f"published artifact — do not re-upload over it; investigate."
            )
            return False

        tmp_path.chmod(0o755)
        os.replace(tmp_path, dest_path)

        size_mb = dest_path.stat().st_size / (1024 * 1024)
        logging.info(f"  ✓ Downloaded and verified ({size_mb:.1f} MB)")
        return True

    except Exception as e:
        logging.error(f"Error downloading {url}: {e}")
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


def download_sandbox_tools(
    version: str, digests: Dict[str, str], dry_run: bool = False
) -> bool:
    """Download sandbox tools for both platforms from S3, digest-verified."""
    binaries_dir = Path("src/inspect_ai/binaries")

    platforms = ["amd64", "arm64"]
    success = True

    # Ensure binaries directory exists
    if not dry_run:
        binaries_dir.mkdir(parents=True, exist_ok=True)

    for platform in platforms:
        filename = f"inspect-sandbox-tools-{platform}-v{version}"
        expected = digests.get(filename)
        if expected is None:
            logging.error(f"No digest entry for {filename} in {SHA256SUMS_FILE}")
            return False
        url = f"{SANDBOX_TOOLS_BASE_URL}/{filename}"
        dest_path = binaries_dir / filename

        if not download_file(url, dest_path, expected, dry_run):
            success = False
            break

    return success


def verify_sandbox_tools_published(
    version: str, digests: Dict[str, str], download_dir: Path
) -> None:
    """Release PR gate: every SHA256SUMS artifact is on S3 with its digest.

    Covers the musl builds as well as the bundled glibc ones, since the
    package downloads those at runtime.

    Raises:
        RuntimeError: If SHA256SUMS does not pin the glibc builds of
            `version`, or an artifact is missing or does not match.
    """
    required = {
        f"inspect-sandbox-tools-{platform}-v{version}"
        for platform in ("amd64", "arm64")
    }
    unpinned = sorted(required - digests.keys())
    if unpinned:
        raise RuntimeError(f"{SHA256SUMS_FILE} has no digest for {unpinned}")

    failed = [
        filename
        for filename, digest in sorted(digests.items())
        if not download_file(
            f"{SANDBOX_TOOLS_BASE_URL}/{filename}", download_dir / filename, digest
        )
    ]
    if failed:
        raise RuntimeError(
            f"Not published at {SANDBOX_TOOLS_BASE_URL} with the digest pinned "
            f"in {SHA256SUMS_FILE}: {failed}"
        )
    logging.info(f"✓ All {len(digests)} pinned sandbox tools artifacts are published")


def verify_sandbox_tools_bundle(
    version: str,
    digests: Dict[str, str],
    binaries_dir: Path = Path("src/inspect_ai/binaries"),
) -> None:
    """Pre-build gate: binaries/ holds exactly the two glibc artifacts, verified.

    Runs unconditionally right before `python -m build` — regardless of how
    the files got there (including --skip-sandbox-download) — as the last
    line of defense for the wheel.

    Raises:
        RuntimeError: If an artifact is missing, an unexpected file is
            present, or a digest does not match.
    """
    expected_files = {
        f"inspect-sandbox-tools-amd64-v{version}",
        f"inspect-sandbox-tools-arm64-v{version}",
    }

    present = (
        {f.name for f in binaries_dir.iterdir() if f.is_file()}
        if binaries_dir.exists()
        else set()
    )
    if present != expected_files:
        raise RuntimeError(
            f"binaries/ must contain exactly {sorted(expected_files)} before "
            f"building; found {sorted(present)}"
        )

    for filename in sorted(expected_files):
        expected = digests.get(filename)
        if expected is None:
            raise RuntimeError(f"No digest entry for {filename} in {SHA256SUMS_FILE}")
        actual = sha256_of_file(binaries_dir / filename)
        if actual != expected:
            raise RuntimeError(
                f"{filename} does not match its pinned digest (expected "
                f"{expected}, got {actual}); refusing to bundle it into the wheel"
            )

    logging.info(f"✓ Pre-build gate passed: sandbox tools v{version} verified")


def read_package_data_globs(
    pyproject: Path = Path(__file__).resolve().parents[1] / "pyproject.toml",
) -> List[str]:
    """Read the `inspect_ai` package-data globs from pyproject.toml.

    Defaults to this script's own revision, which is also the built tree
    except when CI rebuilds an older tag for the parity check; that build is
    then held to the current package-data contract.

    Raises:
        RuntimeError: On Python < 3.11 without `tomli` (installed with
            `build`). Imported here so the other commands stay stdlib-only.
    """
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
    except ImportError as e:
        raise RuntimeError(
            "Reading pyproject.toml on Python < 3.11 requires tomli "
            "(pip install tomli, or install build)"
        ) from e

    with open(pyproject, "rb") as f:
        globs: List[str] = tomllib.load(f)["tool"]["setuptools"]["package-data"][
            "inspect_ai"
        ]
    return globs


def _package_data_regex(pattern: str) -> "re.Pattern[str]":
    """Translate a setuptools package-data glob to a wheel member regex."""
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    return re.compile(f"inspect_ai/{regex}")


# package-data globs whose files are empty by design (the PEP 561 marker).
EMPTY_PACKAGE_DATA = {"py.typed"}


def verify_wheel_contents(
    wheel_path: Path, version: str, package_data_globs: Optional[List[str]] = None
) -> None:
    """Post-build gate: the wheel ships its bundled, non-package files.

    Every other gate runs from a repo checkout, which always has the committed
    sums file and viewer bundle, so a dropped or broken pyproject.toml
    package-data entry, or a build tree that lacks the downloaded binaries,
    would otherwise surface only as hard runtime failures for PyPI users.
    Requires the sandbox-tools digest/version files and binaries, the viewer
    entry point and its JS/CSS assets, and at least one member for every
    package-data glob, all non-empty.

    Raises:
        RuntimeError: If a required member or package-data glob is missing
            from the wheel, or is empty.
    """
    if package_data_globs is None:
        package_data_globs = read_package_data_globs()

    required = [
        "inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS",
        "inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt",
        f"inspect_ai/binaries/inspect-sandbox-tools-amd64-v{version}",
        f"inspect_ai/binaries/inspect-sandbox-tools-arm64-v{version}",
        "inspect_ai/_view/dist/index.html",
    ]
    with zipfile.ZipFile(wheel_path) as wheel:
        sizes = {info.filename: info.file_size for info in wheel.infolist()}

    problems = [
        f"{member} {'is empty' if member in sizes else 'is missing'}"
        for member in required
        if not sizes.get(member)
    ]
    for suffix in [".js", ".css"]:
        if not any(
            name.startswith("inspect_ai/_view/dist/assets/")
            and name.endswith(suffix)
            and size
            for name, size in sizes.items()
        ):
            problems.append(f"no non-empty viewer {suffix} assets")
    for pattern in package_data_globs:
        regex = _package_data_regex(pattern)
        matched = {name: size for name, size in sizes.items() if regex.fullmatch(name)}
        if not matched:
            problems.append(f"package-data '{pattern}' matches no files")
        elif pattern not in EMPTY_PACKAGE_DATA:
            empty = sorted(name for name, size in matched.items() if not size)
            if empty:
                problems.append(f"package-data '{pattern}' has empty files {empty}")

    if problems:
        raise RuntimeError(
            f"Built wheel {wheel_path.name} failed the contents check: "
            f"{'; '.join(problems)}. Check the package-data entries in "
            f"pyproject.toml and that `prepare` ran before the build."
        )

    logging.info(f"✓ Wheel contents verified: {wheel_path.name}")


def verify_dist(dist_dir: Path, version: str, sandbox_version: str) -> None:
    """Post-build gate for CI: dist/ holds one sdist and one wheel of `version`.

    `version` is the release tag. setuptools_scm derives the built version
    from git, so a tag that is not on the built commit, or a dirty tree,
    produces a different version and fails here rather than on PyPI.

    Raises:
        RuntimeError: If dist/ holds anything other than exactly one sdist
            and one wheel of `version`, or the wheel fails
            `verify_wheel_contents`.
    """
    files = sorted(f.name for f in dist_dir.iterdir()) if dist_dir.is_dir() else []
    wheels = [f for f in files if f.endswith(".whl")]
    sdists = [f for f in files if f.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(files) != 2:
        raise RuntimeError(
            f"{dist_dir}/ must contain exactly one wheel and one sdist; found {files}"
        )

    wheel, sdist = wheels[0], sdists[0]
    built = {wheel: wheel.split("-")[1], sdist: sdist[: -len(".tar.gz")].split("-")[-1]}
    for filename, built_version in built.items():
        if built_version != version:
            raise RuntimeError(
                f"{filename} has version {built_version}, expected {version}"
            )

    verify_wheel_contents(dist_dir / wheel, sandbox_version)
    logging.info(f"✓ Distributions verified for version {version}: {files}")


PYPI_JSON_URL = "https://pypi.org/pypi/inspect-ai/{version}/json"


def _normalize_scm_version(content: bytes) -> bytes:
    """Drop `branch`, which names the checkout, not the source.

    It is "main" for a local release from main and "HEAD" for the detached
    tag checkout in CI.
    """
    data = json.loads(content)
    data.pop("branch", None)
    return json.dumps(data, sort_keys=True).encode()


# Archive members (path below the sdist's top-level directory) whose content
# legitimately differs between release builders, with the normalization
# applied to both sides before comparing. Every other member must match byte
# for byte.
PARITY_NORMALIZERS: Dict[str, Callable[[bytes], bytes]] = {
    "src/inspect_ai.egg-info/scm_version.json": _normalize_scm_version,
}


class ParityResult(NamedTuple):
    missing: List[str]
    extra: List[str]
    differing: List[str]
    compared: int


def archive_member_digests(path: Path) -> Dict[str, str]:
    """Map each member of a wheel or sdist to the SHA256 of its content.

    sdist member paths drop the top-level `<name>-<version>/` directory and
    have PARITY_NORMALIZERS applied. Directories and links are recorded by
    type so the member lists still compare.

    Raises:
        RuntimeError: If two members share a path, since one digest per path
            would hide the other entry from the comparison.
    """
    digests: Dict[str, str] = {}

    def add(name: str, digest: str) -> None:
        if name in digests:
            raise RuntimeError(f"{path.name} has duplicate member {name!r}")
        digests[name] = digest

    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as wheel:
            for info in wheel.infolist():
                add(info.filename, hashlib.sha256(wheel.read(info)).hexdigest())
        return digests

    with tarfile.open(path) as sdist:
        for member in sdist.getmembers():
            name = member.name.split("/", 1)[1] if "/" in member.name else ""
            if member.isfile():
                extracted = sdist.extractfile(member)
                assert extracted is not None
                content = extracted.read()
                normalize = PARITY_NORMALIZERS.get(name)
                if normalize:
                    content = normalize(content)
                add(name, hashlib.sha256(content).hexdigest())
            elif member.isdir():
                add(name, "<dir>")
            else:
                add(name, f"<link {member.linkname}>")
    return digests


def compare_archives(published: Path, built: Path) -> ParityResult:
    """Compare member lists and per-member content of two archives."""
    expected = archive_member_digests(published)
    actual = archive_member_digests(built)
    return ParityResult(
        missing=sorted(set(expected) - set(actual)),
        extra=sorted(set(actual) - set(expected)),
        differing=sorted(
            name
            for name in set(expected) & set(actual)
            if expected[name] != actual[name]
        ),
        compared=len(set(expected) | set(actual)),
    )


def download_published_dists(version: str, dest_dir: Path) -> List[str]:
    """Download the PyPI wheel and sdist for `version`, verifying PyPI's SHA256.

    Returns:
        The downloaded filenames.

    Raises:
        RuntimeError: If PyPI does not have exactly one wheel and one sdist
            for `version`, or a download fails verification.
    """
    url = PYPI_JSON_URL.format(version=version)
    logging.info(f"Fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        release = json.load(response)

    files = [f for f in release["urls"] if f["packagetype"] in ("bdist_wheel", "sdist")]
    if sorted(f["packagetype"] for f in files) != ["bdist_wheel", "sdist"]:
        raise RuntimeError(
            f"PyPI has {[f['filename'] for f in files]} for {version}; expected "
            f"one wheel and one sdist"
        )
    for f in files:
        if not download_file(
            f["url"], dest_dir / f["filename"], f["digests"]["sha256"]
        ):
            raise RuntimeError(f"Could not download {f['filename']} from PyPI")
    return sorted(f["filename"] for f in files)


def skip_published_dists(
    dist_dir: Path, version: str, published_dir: Path
) -> List[str]:
    """Move files PyPI already has out of `dist_dir`, so a retry uploads the rest.

    Returns:
        The moved filenames.

    Raises:
        RuntimeError: If PyPI has a file of the same name with a different
            SHA256, which PyPI would refuse to replace.
    """
    url = PYPI_JSON_URL.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            release = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logging.info(f"{version} is not on PyPI yet; nothing to skip")
            return []
        raise

    published = {f["filename"]: f["digests"]["sha256"] for f in release["urls"]}
    skipped: List[str] = []
    for path in sorted(p for p in dist_dir.iterdir() if p.is_file()):
        digest = published.get(path.name)
        if digest is None:
            continue
        if sha256_of_file(path) != digest:
            raise RuntimeError(
                f"PyPI already has {path.name} with a different SHA256 ({digest}); "
                f"this build does not match the published file"
            )
        published_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(published_dir / path.name))
        skipped.append(path.name)
        logging.info(f"✓ {path.name} is already on PyPI with the same SHA256; skipping")
    return skipped


def verify_parity(dist_dir: Path, version: str) -> None:
    """Compare locally built distributions with the ones published on PyPI.

    Raises:
        RuntimeError: If a published file was not built, or any archive has
            missing, extra or differing members.
    """
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for filename in download_published_dists(version, Path(tmp)):
            built = dist_dir / filename
            if not built.exists():
                raise RuntimeError(f"{built} was not built; PyPI has {filename}")
            result = compare_archives(Path(tmp) / filename, built)
            for label, names in [
                ("missing from build", result.missing),
                ("extra in build", result.extra),
                ("content differs", result.differing),
            ]:
                for name in names:
                    logging.error(f"  {filename}: {label}: {name}")
            logging.info(
                f"{filename}: {result.compared} members compared, "
                f"{len(result.missing)} missing, {len(result.extra)} extra, "
                f"{len(result.differing)} differing"
            )
            failed = failed or bool(result.missing or result.extra or result.differing)

    if failed:
        raise RuntimeError(f"Built distributions differ from PyPI's {version}")
    logging.info(f"✓ Built distributions match PyPI's {version}")


def ensure_sandbox_tools(
    version: str,
    digests: Dict[str, str],
    skip_download: bool = False,
    dry_run: bool = False,
) -> None:
    """Ensure the correct version of sandbox tools is present."""
    if skip_download:
        logging.info("Skipping sandbox tools download (--skip-sandbox-download flag)")
        return

    if check_sandbox_tools_exist(version, digests):
        # Check if there are any other versions present
        binaries_dir = Path("src/inspect_ai/binaries")
        if binaries_dir.exists():
            all_files = list(binaries_dir.iterdir())
            expected_files = {
                f"inspect-sandbox-tools-amd64-v{version}",
                f"inspect-sandbox-tools-arm64-v{version}",
            }
            unexpected_files = [
                f.name for f in all_files if f.name not in expected_files
            ]

            if unexpected_files:
                logging.info(
                    f"Found unexpected files in binaries directory: {unexpected_files}"
                )
                logging.info("Cleaning directory to ensure only one version exists...")
                clean_sandbox_tools_directory()
                # Need to re-download after cleaning
            else:
                # Correct version exists and no other versions
                return

    # Either wrong version exists or files are missing
    logging.info(f"Downloading sandbox tools v{version}...")

    # Clean directory first to ensure only one version
    clean_sandbox_tools_directory()

    # Download the required version
    if not download_sandbox_tools(version, digests, dry_run):
        logging.error("Failed to download sandbox tools")
        sys.exit(1)

    logging.info("✓ Sandbox tools downloaded successfully")


def check_dependencies() -> bool:
    """Check if required dependencies are installed."""
    dependencies = [
        (["python3", "-m", "build", "--version"], "build"),
        (["python3", "-m", "twine", "--version"], "twine"),
    ]

    all_present = True
    for cmd, name in dependencies:
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            logging.info(f"✓ {name} is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.error(f"❌ {name} is not installed")
            logging.error(f"   Install it with: pip install {name}")
            all_present = False

    return all_present


def check_pypi_auth() -> bool:
    """Check if PyPI authentication is configured."""
    try:
        # Check if .pypirc exists or environment variables are set
        pypirc_path = Path.home() / ".pypirc"
        has_pypirc = pypirc_path.exists()
        has_token = os.environ.get("TWINE_USERNAME") == "__token__"
        has_password = bool(os.environ.get("TWINE_PASSWORD"))

        if has_pypirc:
            logging.info("✓ PyPI configuration found (~/.pypirc)")
            return True
        elif has_token and has_password:
            logging.info("✓ PyPI token authentication found (environment variables)")
            return True
        else:
            logging.error("❌ No PyPI authentication found")
            logging.error(
                "   Configure ~/.pypirc or set TWINE_USERNAME and TWINE_PASSWORD"
            )
            return False
    except Exception as e:
        logging.error(f"Error checking PyPI auth: {e}")
        return False


def validate_tag_format(tag_name: str) -> bool:
    """Validate tag format (semantic versioning)."""
    # Pattern for semantic versioning with optional 'v' prefix
    # Matches: v1.2.3, 1.2.3, v1.2.3-alpha.1, v1.2.3+build.123, etc.
    semver_pattern = r"^v?\d+\.\d+\.\d+(-[a-zA-Z0-9\.-]+)?(\+[a-zA-Z0-9\.-]+)?$"

    if re.match(semver_pattern, tag_name):
        logging.info(f"✓ Tag '{tag_name}' follows semantic versioning")
        return True
    else:
        logging.warning(f"⚠️  Tag '{tag_name}' doesn't follow semantic versioning")
        response = input("Do you want to continue anyway? (yes/no): ").lower().strip()
        return response in ["yes", "y"]


def tag_exists(tag_name: str) -> bool:
    """Check if a git tag already exists locally or remotely."""
    result = run_command(
        ["git", "tag", "-l", tag_name], capture_output=True, check=False
    )
    return bool(result.stdout.strip()) if result else False


def get_confirmation(
    tag_name: str, dry_run: bool = False, no_publish: bool = False
) -> bool:
    """Get user confirmation before proceeding."""
    print("\n✅ All pre-flight checks passed!")
    print("\nYou are about to:")
    print("  1. Ensure sandbox tools are downloaded")
    print(f"  2. Create git tag: {tag_name}")
    print("  3. Remove dist/ directory")
    print("  4. Build the Python package")
    if not no_publish:
        print("  5. Upload to PyPI")
        print(f"  6. Push tag {tag_name} to origin")
    else:
        print("  5. Skip PyPI upload (--no-publish mode)")
        print("  6. Skip pushing tag to origin (--no-publish mode)")

    if dry_run:
        print("\n🔸 DRY RUN MODE - No actual changes will be made")
    elif no_publish:
        print("\n📦 NO PUBLISH MODE - Package will be built but not published")

    while True:
        response = input("\nDo you want to proceed? (yes/no): ").lower().strip()
        if response in ["yes", "y"]:
            return True
        elif response in ["no", "n"]:
            return False
        else:
            print("Please enter 'yes' or 'no'")


def remove_directories(dry_run: bool = False) -> None:
    """Remove build directories (but not binaries)."""
    # Only remove dist directory, not binaries
    dirs_to_remove = ["dist"]

    for dir_path in dirs_to_remove:
        if os.path.exists(dir_path):
            if dry_run:
                logging.info(f"[DRY RUN] Would remove {dir_path}/")
            else:
                logging.info(f"Removing {dir_path}/...")
                shutil.rmtree(dir_path)
        else:
            logging.info(f"Directory {dir_path}/ does not exist, skipping...")


def get_current_branch() -> str:
    """Get the current git branch name."""
    result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True
    )
    return result.stdout.strip() if result else ""


def is_branch_up_to_date() -> Tuple[bool, str]:
    """Check if the current branch is up to date with origin."""
    # First, fetch the latest from origin (including tags)
    logging.info("Fetching latest from origin...")
    run_command(["git", "fetch", "--tags"], capture_output=True)

    # Get the current branch
    branch = get_current_branch()

    # Compare local and remote
    result = run_command(
        ["git", "rev-list", f"HEAD...origin/{branch}", "--count"],
        capture_output=True,
        check=False,
    )

    if not result or result.returncode != 0:
        # Remote branch might not exist
        return True, "No remote branch to compare with"

    behind_count = int(result.stdout.strip()) if result.stdout else 0

    # Check if we're ahead of remote
    result = run_command(
        ["git", "rev-list", f"origin/{branch}...HEAD", "--count"], capture_output=True
    )
    ahead_count = int(result.stdout.strip()) if result and result.stdout else 0

    if behind_count > 0:
        return False, f"Branch is {behind_count} commit(s) behind origin/{branch}"
    elif ahead_count > 0:
        return True, f"Branch is {ahead_count} commit(s) ahead of origin/{branch}"
    else:
        return True, "Branch is up to date with origin"


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes."""
    result = run_command(["git", "status", "--porcelain"], capture_output=True)
    return bool(result.stdout.strip()) if result else False


def release_command(args):
    """Execute the release command."""
    tag_name = args.tag
    required_branch = args.branch
    dry_run = args.dry_run
    skip_sandbox_download = args.skip_sandbox_download
    no_publish = args.no_publish

    # Set up logging
    setup_logging(f"release_{tag_name}")

    if dry_run:
        logging.info("🔸 Running in DRY RUN mode")

    # Validate tag name format
    if not tag_name:
        logging.error("Error: Tag name cannot be empty")
        sys.exit(1)

    if not validate_tag_format(tag_name):
        logging.info("Tag format validation failed or rejected by user")
        sys.exit(1)

    # Check if we're in a git repository
    try:
        run_command(["git", "rev-parse", "--git-dir"], capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logging.error("Error: Not in a git repository")
        sys.exit(1)

    logging.info("\n🔍 Running pre-flight checks...")
    logging.info("-" * 40)

    # Check dependencies
    if not check_dependencies():
        logging.error("Missing required dependencies")
        sys.exit(1)

    # Check PyPI authentication (skip in no-publish mode)
    if not dry_run and not no_publish and not check_pypi_auth():
        logging.error("PyPI authentication not configured")
        sys.exit(1)

    # Ensure sandbox tools are present
    sandbox_version = get_sandbox_tools_version()
    sandbox_digests = read_pinned_digests()
    ensure_sandbox_tools(
        sandbox_version, sandbox_digests, skip_sandbox_download, dry_run
    )

    # Check current branch
    current_branch = get_current_branch()
    if current_branch != required_branch:
        logging.error(
            f"❌ Error: You must be on the '{required_branch}' branch to create a release tag"
        )
        logging.error(f"   Current branch: '{current_branch}'")
        logging.error(f"\n   To switch branches, run: git checkout {required_branch}")
        sys.exit(1)

    logging.info(f"✓ On '{required_branch}' branch")

    # Check for uncommitted changes
    if has_uncommitted_changes():
        logging.error("❌ Error: You have uncommitted changes!")
        logging.error(
            "\n   Please commit or stash your changes before creating a release tag."
        )
        logging.error("   To see uncommitted changes, run: git status")
        sys.exit(1)

    logging.info("✓ No uncommitted changes")

    # Check if branch is up to date
    is_up_to_date, message = is_branch_up_to_date()
    if not is_up_to_date:
        logging.error(f"❌ Error: {message}")
        logging.error(
            f"\n   Please pull the latest changes: git pull origin {required_branch}"
        )
        sys.exit(1)

    logging.info(f"✓ {message}")

    # Check if tag already exists
    if tag_exists(tag_name):
        logging.error(f"\n❌ Error: Tag '{tag_name}' already exists!")
        logging.error("\n   Existing tags:")
        run_command(["git", "tag", "-l"], capture_output=False)
        sys.exit(1)

    logging.info(f"✓ Tag '{tag_name}' is available")
    logging.info("-" * 40)

    # Get confirmation unless skipped
    if not args.skip_confirmation and not get_confirmation(
        tag_name, dry_run, no_publish
    ):
        logging.info("Operation cancelled by user")
        sys.exit(0)

    logging.info(f"\n🚀 Proceeding with tag '{tag_name}'...")
    logging.info("-" * 40)

    try:
        # Create git tag (but don't push yet - two-phase commit)
        logging.info(f"\n1. Creating git tag '{tag_name}' locally...")
        run_command(["git", "tag", tag_name], dry_run=dry_run)
        logging.info("   ✓ Tag created successfully (not pushed yet)")

        # Remove directories
        logging.info("\n2. Cleaning build directories...")
        remove_directories(dry_run=dry_run)
        logging.info("   ✓ Directories cleaned")

        # Build package (gated by unconditional pre/post-build verification)
        logging.info("\n3. Building Python package...")
        if dry_run:
            logging.info("[DRY RUN] Would verify sandbox tools bundle before build")
        else:
            try:
                verify_sandbox_tools_bundle(sandbox_version, sandbox_digests)
            except RuntimeError as e:
                logging.error(f"Pre-build sandbox tools gate failed: {e}")
                raise
        run_command(["python3", "-m", "build"], dry_run=dry_run)
        if dry_run:
            logging.info("[DRY RUN] Would verify built wheel contents")
        else:
            wheels = list(Path("dist").glob("*.whl"))
            if not wheels:
                logging.error("No wheel found in dist/ after build")
                sys.exit(1)
            try:
                for wheel in wheels:
                    verify_wheel_contents(wheel, sandbox_version)
            except RuntimeError as e:
                logging.error(f"Post-build wheel gate failed: {e}")
                raise
        logging.info("   ✓ Package built successfully")

        # Upload to PyPI (unless --no-publish)
        if not no_publish:
            logging.info("\n4. Uploading to PyPI...")
            if not dry_run:
                # Get all files in dist/ directory
                dist_files = list(Path("dist").glob("*"))
                if dist_files:
                    upload_cmd = (
                        ["python3", "-m", "twine", "upload"]
                        + [str(f) for f in dist_files]
                        + ["--verbose"]
                    )
                    run_command(upload_cmd, dry_run=dry_run)
                else:
                    logging.error("No files found in dist/ directory")
                    sys.exit(1)
            else:
                logging.info("[DRY RUN] Would upload dist/* to PyPI")
            logging.info("   ✓ Package uploaded successfully")

            # Push tag to origin (only after successful PyPI upload)
            logging.info(f"\n5. Pushing tag '{tag_name}' to origin...")
            run_command(["git", "push", "origin", tag_name], dry_run=dry_run)
            logging.info("   ✓ Tag pushed successfully")
        else:
            logging.info("\n4. Skipping PyPI upload (--no-publish mode)")
            logging.info("   ℹ️  Package built in dist/ directory")
            logging.info("\n5. Skipping tag push to origin (--no-publish mode)")
            logging.info(f"   ℹ️  Tag '{tag_name}' created locally only")

        if no_publish:
            logging.info(
                f"\n✨ Build complete! Tag '{tag_name}' created locally and package built."
            )
            logging.info("   To publish later, run:")
            logging.info("     python3 -m twine upload dist/*")
            logging.info(f"     git push origin {tag_name}")
        else:
            logging.info(
                f"\n✨ All done! Tag '{tag_name}' has been created and package uploaded."
            )
        logging.info("-" * 40)

    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
        logging.error(f"\n❌ Error occurred: {e}")

        # Offer to clean up the local tag if it was created
        if not dry_run and tag_exists(tag_name):
            cleanup = input(
                f"\nDo you want to delete the local tag '{tag_name}'? (yes/no): "
            )
            if cleanup.lower() in ["yes", "y"]:
                run_command(["git", "tag", "-d", tag_name], check=False)
                logging.info(f"Local tag '{tag_name}' deleted.")

        sys.exit(1)


def sandbox_tools_download_command(args):
    """Execute the sandbox-tools-download command."""
    dry_run = args.dry_run

    # Set up logging
    setup_logging("sandbox_tools_download")

    if dry_run:
        logging.info("🔸 Running in DRY RUN mode")

    logging.info("🔧 Downloading sandbox tools...")
    logging.info("-" * 40)

    # Get required version and pinned digests
    version = get_sandbox_tools_version()
    digests = read_pinned_digests()

    # Check if correct version already exists
    if check_sandbox_tools_exist(version, digests):
        # Clean any other versions
        binaries_dir = Path("src/inspect_ai/binaries")
        if binaries_dir.exists():
            all_files = list(binaries_dir.iterdir())
            expected_files = {
                f"inspect-sandbox-tools-amd64-v{version}",
                f"inspect-sandbox-tools-arm64-v{version}",
            }
            unexpected_files = [
                f.name for f in all_files if f.name not in expected_files
            ]

            if unexpected_files:
                logging.info(f"Found unexpected files: {unexpected_files}")
                logging.info("Cleaning directory to ensure only one version exists...")
                clean_sandbox_tools_directory()
                # Need to re-download after cleaning
            else:
                logging.info("Correct version already downloaded and no cleanup needed")
                return

    # Clean and download
    logging.info("Cleaning old versions...")
    clean_sandbox_tools_directory()

    logging.info(f"Downloading version {version}...")
    if not download_sandbox_tools(version, digests, dry_run):
        logging.error("Failed to download sandbox tools")
        sys.exit(1)

    logging.info("\n✨ Sandbox tools downloaded successfully!")
    logging.info("-" * 40)


def prepare_command(args: argparse.Namespace) -> None:
    """Execute the prepare command: download sandbox tools and gate them."""
    setup_logging("prepare")

    version = get_sandbox_tools_version()
    digests = read_pinned_digests()
    ensure_sandbox_tools(version, digests)
    try:
        verify_sandbox_tools_bundle(version, digests)
    except RuntimeError as e:
        logging.error(f"Pre-build sandbox tools gate failed: {e}")
        sys.exit(1)


def verify_sandbox_tools_published_command(args: argparse.Namespace) -> None:
    """Execute the verify-sandbox-tools-published command."""
    setup_logging("verify_sandbox_tools_published")

    version = get_sandbox_tools_version()
    digests = read_pinned_digests()
    with tempfile.TemporaryDirectory() as download_dir:
        try:
            verify_sandbox_tools_published(version, digests, Path(download_dir))
        except RuntimeError as e:
            logging.error(f"Sandbox tools publication check failed: {e}")
            sys.exit(1)


def verify_dist_command(args: argparse.Namespace) -> None:
    """Execute the verify-dist command: version and wheel-contents gate."""
    setup_logging("verify_dist")

    try:
        verify_dist(Path(args.dist_dir), args.version, get_sandbox_tools_version())
    except RuntimeError as e:
        logging.error(f"Post-build distribution gate failed: {e}")
        sys.exit(1)


def skip_published_command(args: argparse.Namespace) -> None:
    """Execute the skip-published command."""
    setup_logging("skip_published")

    try:
        skip_published_dists(
            Path(args.dist_dir), args.version, Path(args.published_dir)
        )
    except (RuntimeError, urllib.error.URLError) as e:
        logging.error(f"PyPI already-published check failed: {e}")
        sys.exit(1)


def verify_parity_command(args: argparse.Namespace) -> None:
    """Execute the verify-parity command: compare the build with PyPI."""
    setup_logging("verify_parity")

    try:
        verify_parity(Path(args.dist_dir), args.version)
    except RuntimeError as e:
        logging.error(f"Parity check failed: {e}")
        sys.exit(1)


def main():
    # Create main parser
    parser = argparse.ArgumentParser(
        description="Tag git repository, build package, and upload to PyPI"
    )

    # Add subparsers
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Release command (default)
    release_parser = subparsers.add_parser(
        "release", help="Create a release and publish to PyPI"
    )
    release_parser.add_argument("tag", help="Git tag name to create")
    release_parser.add_argument(
        "--skip-confirmation", action="store_true", help="Skip confirmation prompt"
    )
    release_parser.add_argument(
        "--branch", default="main", help="Required branch name (default: main)"
    )
    release_parser.add_argument(
        "--dry-run", action="store_true", help="Run in dry-run mode (no actual changes)"
    )
    release_parser.add_argument(
        "--skip-sandbox-download",
        action="store_true",
        help="Skip downloading sandbox tools",
    )
    release_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Build package but don't upload to PyPI or push tag",
    )

    # Sandbox tools download command
    sandbox_parser = subparsers.add_parser(
        "sandbox-tools-download", help="Download sandbox tools binaries"
    )
    sandbox_parser.add_argument(
        "--dry-run", action="store_true", help="Run in dry-run mode (no actual changes)"
    )

    # Non-interactive steps for the publish workflow
    subparsers.add_parser(
        "prepare",
        help="Download sandbox tools and run the pre-build digest gate",
    )
    subparsers.add_parser(
        "verify-sandbox-tools-published",
        help="Check every sandbox tools artifact in SHA256SUMS is on S3 with its digest",
    )
    verify_dist_parser = subparsers.add_parser(
        "verify-dist",
        help="Check built distributions match a version and run the wheel gate",
    )
    verify_dist_parser.add_argument("version", help="Expected package version")
    verify_dist_parser.add_argument(
        "--dist-dir", default="dist", help="Distribution directory (default: dist)"
    )

    skip_published_parser = subparsers.add_parser(
        "skip-published",
        help="Move distributions PyPI already has (same SHA256) out of the dist dir",
    )
    skip_published_parser.add_argument("version", help="Version being published")
    skip_published_parser.add_argument(
        "--dist-dir", default="dist", help="Distribution directory (default: dist)"
    )
    skip_published_parser.add_argument(
        "--published-dir",
        default="dist-published",
        help="Where to move already-published files (default: dist-published)",
    )

    verify_parity_parser = subparsers.add_parser(
        "verify-parity",
        help="Compare built distributions with the same version on PyPI",
    )
    verify_parity_parser.add_argument("version", help="Published version")
    verify_parity_parser.add_argument(
        "--dist-dir", default="dist", help="Distribution directory (default: dist)"
    )

    # Parse arguments
    args = parser.parse_args()

    # Handle backward compatibility: if no subcommand but first arg looks like a tag, treat as release
    if not args.command and len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # Backward compatibility: python pypi-release.py <tag>
        # Re-parse as release command
        sys.argv.insert(1, "release")
        args = parser.parse_args()

    # Execute appropriate command
    if args.command == "release":
        release_command(args)
    elif args.command == "sandbox-tools-download":
        sandbox_tools_download_command(args)
    elif args.command == "prepare":
        prepare_command(args)
    elif args.command == "verify-sandbox-tools-published":
        verify_sandbox_tools_published_command(args)
    elif args.command == "verify-dist":
        verify_dist_command(args)
    elif args.command == "skip-published":
        skip_published_command(args)
    elif args.command == "verify-parity":
        verify_parity_command(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
