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
"""

import argparse
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

SANDBOX_TOOLS_UTILS_DIR = Path("src/inspect_ai/tool/_sandbox_tools_utils")
SHA256SUMS_FILE = SANDBOX_TOOLS_UTILS_DIR / "SHA256SUMS"


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
    base_url = "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com"
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
        url = f"{base_url}/{filename}"
        dest_path = binaries_dir / filename

        if not download_file(url, dest_path, expected, dry_run):
            success = False
            break

    return success


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


def verify_wheel_contents(wheel_path: Path, version: str) -> None:
    """Post-build gate: the wheel ships the digest/version files and binaries.

    Every other gate runs from a repo checkout, which always has the committed
    sums file, so a dropped or broken pyproject.toml package-data entry would
    otherwise surface only as hard runtime failures for PyPI users.

    Raises:
        RuntimeError: If a required member is missing from the wheel.
    """
    required = [
        "inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS",
        "inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt",
        f"inspect_ai/binaries/inspect-sandbox-tools-amd64-v{version}",
        f"inspect_ai/binaries/inspect-sandbox-tools-arm64-v{version}",
    ]
    with zipfile.ZipFile(wheel_path) as wheel:
        members = set(wheel.namelist())
    missing = [member for member in required if member not in members]
    if missing:
        raise RuntimeError(
            f"Built wheel {wheel_path.name} is missing required members: "
            f"{missing}. Check the package-data entries in pyproject.toml."
        )

    logging.info(f"✓ Wheel contents verified: {wheel_path.name}")


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
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
