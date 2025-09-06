import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Import playwright to find its installation directory
import playwright  # type: ignore


def stage_playwright_dependencies(
    build_working_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    """
    Handle the complex task of bundling Playwright and Chromium dependencies for PyInstaller builds.

    This function solves the problem of including all necessary shared libraries
    required by Chromium's headless browser in a portable executable.

    WHY MANUAL DEPENDENCY COLLECTION IS REQUIRED:
    PyInstaller automatically handles Python module dependencies and their C extensions,
    but it does NOT analyze or bundle dependencies of standalone binaries included
    via --add-binary. When we include Chromium's headless_shell executable, PyInstaller
    treats it as a data file and doesn't discover its shared library dependencies.
    This function manually uses ldd to find these dependencies and explicitly bundles
    them, which PyInstaller cannot do automatically.

    WORKFLOW:
    1. Install Chromium into the Playwright package directory (not user home)
    2. Locate the chromium-headless-shell binary that Playwright uses for Chromium
    3. Use ldd to discover all shared library dependencies
    4. Explicitly add NSS and WebGL libraries that may be loaded dynamically
    5. Return --add-binary arguments for PyInstaller to include all dependencies

    USAGE:
    Called by build_v2.py when build_config.browser is True. Should not be
    used directly - use build_v2.py as the main entry point.

    Args:
        build_working_dir: The working directory for the build process where
                          temporary files and staged libraries will be stored.

    Returns:
        A list of PyInstaller arguments that tell PyInstaller to include:
        - Chromium browser (headless_shell) via --add-binary
        - All necessary shared libraries discovered via ldd as --add-binary arguments
        - NSS security libraries as --add-binary arguments
        - WebGL libraries as --add-binary arguments
        - Complete playwright package collection via --collect-all
        - Playwright metadata via --copy-metadata
        Each --add-binary argument is in the format "source:dest" where dest is "lib"
        to place files in a lib/ subdirectory.
    """
    # Adjust BUILD_LIBS to be in the working directory
    build_libs_dir = build_working_dir / "build_libs"

    # Install browser into package (not user home)
    headless_shell = _install_chromium_headless_shell()

    # Collect and stage all extra dependencies/libraries
    if build_libs_dir.exists():
        shutil.rmtree(build_libs_dir)
    build_libs_dir.mkdir(parents=True, exist_ok=True)

    if headless_shell:
        _stage_libraries(_ldd_deps(headless_shell), "ldd dependencies", build_libs_dir)
        _stage_libraries(_nss_deps(), "NSS dependencies", build_libs_dir)
        _stage_libraries(_webgl_deps(), "WebGL dependencies", build_libs_dir)
    else:
        print("[3/4] Skipping library collection (no browser support)")

    # Each library needs a --add-binary argument in the format "source:dest"
    # The :lib suffix tells PyInstaller to place these in a lib/ subdirectory
    binary_args = [f"--add-binary={str(f)}:lib" for f in build_libs_dir.glob("*")]

    # Add playwright-specific PyInstaller options
    playwright_args = [
        "--collect-all",
        "playwright",
        "--copy-metadata=playwright",
    ]

    custom_env = os.environ.copy()
    custom_env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    return (binary_args + playwright_args, custom_env)


def remove_playwright_dependencies() -> tuple[list[str], None]:
    """
    Generate PyInstaller arguments to exclude Playwright dependencies.

    This function is essentially the opposite of stage_playwright_dependencies().
    While stage_playwright_dependencies() includes all necessary components for
    browser automation, this function explicitly excludes them to prevent
    wasting space in executables that don't need browser capabilities.

    Returns:
        A list of --exclude-module arguments that tell PyInstaller to exclude:
        - playwright: The main Playwright package and all its submodules
        - greenlet: Async support library used by Playwright
        - pyee: Event emitter library used by Playwright

    This results in significantly smaller executables (~75% size reduction)
    when browser automation is not required.
    """
    return (
        [
            "--exclude-module",
            "playwright",
            "--exclude-module",
            "greenlet",
            "--exclude-module",
            "pyee",
        ],
        None,
    )


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout


def _install_chromium_headless_shell() -> Path:
    """
    Install Chromium browser into the Playwright package directory.

    By setting PLAYWRIGHT_BROWSERS_PATH=0, we tell Playwright to install
    browsers into its package directory instead of the user's home directory.
    This is crucial for creating a portable executable - the browser files
    will be included when PyInstaller bundles the playwright package.

    Without this step, Playwright would look for browsers in ~/.cache/ms-playwright
    at runtime, which wouldn't exist on target systems.
    """
    # Copy current environment and override browser path
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"  # "0" means use package directory

    print("[1/4] Ensuring Chromium is installed into the Playwright package path")

    # Run playwright install command with modified environment
    _run(
        [sys.executable, "-m", "playwright", "install", "chromium-headless-shell"],
        env=env,
    )

    return _find_chromium_headless_shell()


def _find_chromium_headless_shell() -> Path:
    """
    Locate the headless_shell binary within the Playwright package.

    The binary is typically located at:
    playwright/driver/package/.local-browsers/chromium-*/chrome-linux/headless_shell

    Returns:
        Path to the headless_shell executable

    Raises:
        FileNotFoundError: If headless_shell cannot be located, suggesting
                          that Chromium installation may have failed
    """
    print("[2/4] Locating headless_shell used by Playwright")

    # Get the playwright package directory
    pkg = Path(playwright.__file__).parent

    # Search recursively for headless_shell in the driver/package subdirectory
    # This is where Playwright stores downloaded browser binaries
    for p in (pkg / "driver" / "package").rglob("headless_shell"):
        # Verify it's an executable file (not a directory or symlink to nowhere)
        if p.is_file() and os.access(p, os.X_OK):
            print(f"Using headless_shell: {p}")
            return p

    # If we get here, something went wrong with browser installation
    raise FileNotFoundError(
        "Could not locate headless_shell. Ensure 'playwright install chromium' succeeds."
    )


def _parse_ldd_paths(ldd_output: str) -> list[Path]:
    """
    Parse the output of the ldd command to extract library paths.

    ldd output format examples:
    - Normal library: libX11.so.6 => /lib/x86_64-linux-gnu/libX11.so.6 (0x00007f...)
    - Virtual library: linux-vdso.so.1 (0x00007fff...)
    - Not found: libmissing.so => not found

    This function:
    1. Extracts the absolute paths from "=>" mappings
    2. Filters out core system libraries that shouldn't be bundled
    3. Returns unique paths as a set

    CRITICAL: All libraries referenced by ldd (except core system libraries that
    are intentionally excluded) MUST be found on the system to create a functional
    PyInstaller package. Missing libraries (=> not found) indicate system dependency
    issues that will cause runtime failures in the bundled executable.

    Args:
        ldd_output: Raw output from the ldd command

    Returns:
        Set of Path objects for libraries that should be bundled

    Raises:
        RuntimeError: If any required libraries are not found on the system
    """
    # Core system libraries that should NOT be bundled
    # These are provided by the host OS and bundling them would break compatibility
    # The dynamic linker (ld-linux) and core C libraries must match the host system
    LDD_EXCLUDES = (
        "ld-linux",  # Dynamic linker/loader - must match host kernel
        "libc.so",  # Core C library - defines system ABI
        "libm.so",  # Math library - part of core glibc
        "libpthread.so",  # POSIX threads - part of core glibc
        "libdl.so",  # Dynamic loading - part of core glibc
        "librt.so",  # Real-time extensions - part of core glibc
    )

    # Check for missing libraries first - these are fatal for PyInstaller packaging
    if not_found_libs := [
        line.split()[0] for line in ldd_output.splitlines() if "=> not found" in line
    ]:
        raise RuntimeError(
            f"Missing required system libraries: {', '.join(not_found_libs)}. "
            "These libraries are required by Chromium but not installed on the system. "
            "Install the missing packages or ensure all dependencies are available."
        )

    return [
        Path(m.group(1))
        for line in ldd_output.splitlines()
        if "=>"
        in line  # Skip lines without "=>" (like linux-vdso or statically linked)
        for m in [re.search(r"=>\s+(\S+)", line)]  # Extract the path after "=>"
        if m
        and m.group(1).startswith("/")  # Skip non-absolute paths (like "not found")
        and not any(
            ex in m.group(1) for ex in LDD_EXCLUDES
        )  # Filter out core system libraries
    ]


def _ldd_deps(binary: Path) -> list[Path]:
    """
    Use ldd to discover all shared library dependencies of a binary.

    These are the libraries explicitly linked by headless_shell.

    Args:
        binary: Path to the executable to analyze

    Returns:
        Set of paths to required shared libraries (excluding core system libs)
    """
    print("[3/4] Collecting shared libraries via ldd")

    return _parse_ldd_paths(_run(["ldd", str(binary)]))


# Cache for ldconfig output to avoid multiple calls
_ldconfig_cache: dict[str, Path] | None = None


def _get_ldconfig_cache() -> dict[str, Path]:
    """
    Build and cache a dictionary of library names to paths from ldconfig output.

    This function runs ldconfig once and parses its output into a dictionary
    for fast lookups. The cache is stored globally to avoid repeated calls.

    Returns:
        Dictionary mapping library names to their file paths
    """
    global _ldconfig_cache

    if _ldconfig_cache is not None:
        return _ldconfig_cache

    _ldconfig_cache = {}

    # Check if ldconfig is available (might not be in minimal containers)
    if shutil.which("ldconfig"):
        try:
            # Get the library cache listing
            out = _run(["ldconfig", "-p"])

            for line in out.splitlines():
                # ldconfig -p format:
                # libX11.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libX11.so.6

                line = line.strip()
                if not line or "=>" not in line:
                    continue

                # Split on first space to get library name
                parts = line.split(" ", 1)
                if len(parts) < 2:
                    continue

                lib_name = parts[0]

                # Extract the path after "=>"
                m = re.search(r"=>\s+(\S+)$", line)
                if m:
                    p = Path(m.group(1))
                    # Verify the file actually exists and cache it
                    if p.exists():
                        _ldconfig_cache[lib_name] = p
        except Exception:
            # ldconfig might fail in some environments, continue with empty cache
            pass

    return _ldconfig_cache


def _webgl_deps() -> list[Path]:
    """
    Best-effort include graphics libraries

    libGLESv2 is needed for WebGL support but location varies by distribution
    """
    return [
        Path(gpath)
        for pattern in ("/usr/lib/*-linux-gnu/libGLESv2.so*",)
        for gpath in glob.glob(pattern)
        if Path(gpath).exists()
    ]


def _nss_deps() -> list[Path]:
    """
    Locate the NSS (Network Security Services) Libraries.

    These security libraries are dynamically loaded by Chromium at runtime for HTTPS
    support and must be explicitly included.
    """
    # NSS (Network Security Services) libraries handle SSL/TLS, certificates, and
    # cryptographic operations and are required by Chromium. These are often loaded
    # dynamically at runtime using dlopen(), so they don't always appear in ldd output.
    NSS_NAMES = [
        "libsoftokn3.so",  # Software token implementation for NSS
        "libsoftokn3.chk",  # Checksum file for libsoftokn3
        "libnss3.so",  # Main NSS library
        "libnssutil3.so",  # NSS utility functions
        "libsmime3.so",  # S/MIME cryptographic functions
        "libssl3.so",  # SSL/TLS protocol implementation
        "libnssckbi.so",  # Built-in root certificates (CRITICAL for HTTPS)
        "libnspr4.so",  # Netscape Portable Runtime (NSS dependency)
        "libplc4.so",  # NSPR library for classic I/O
        "libplds4.so",  # NSPR library for data structures
        "libfreebl3.so",  # Freebl cryptographic library
        "libfreeblpriv3.so",  # Private Freebl functions
    ]

    return [path for name in NSS_NAMES if (path := _find_nss_lib(name))]


def _find_nss_lib(name: str) -> Path | None:
    """
    Find an NSS library by name, trying multiple strategies.

    NSS libraries are critical for HTTPS support but may be installed
    in various locations depending on the distribution. This function:
    1. First tries the fast ldconfig cache lookup
    2. Falls back to filesystem search in common locations

    Args:
        name: NSS library filename (e.g., "libnssckbi.so")

    Returns:
        Path to the library if found, None otherwise.
        Any returned Path is guaranteed to exist at the time of return.
    """
    # Strategy 1: Try ldconfig cache (fastest)
    if path := _get_ldconfig_cache().get(name):
        return path

    # Strategy 2: Search common library directories
    # Different distributions use different layouts:
    # - Debian/Ubuntu: /usr/lib/x86_64-linux-gnu/
    # - Fedora/RHEL: /usr/lib64/
    # - Alpine: /usr/lib/
    for root in ("/usr/lib", "/lib"):
        # rglob searches recursively, handling all subdirectory structures
        for candidate in Path(root).rglob(name):
            if candidate.is_file():
                return candidate

    return None


def _stage_dependency(src: Path, dest_dir: Path) -> None:
    """
    Copy a dependency file (typically a lib) to the destination directory, resolving symlinks.

    Many libraries are symlinks (e.g., libfoo.so -> libfoo.so.1.2.3).
    This function follows symlinks to copy the actual file content, ensuring the
    bundled library is complete and functional.

    Args:
        src: Source library path (may be a symlink)
        dest_dir: Destination directory for the copy
    """
    # Ensure destination directory exists
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Keep the original filename in the destination
    target = dest_dir / src.name

    # follow_symlinks=True ensures we copy the actual file content,
    # not just create another symlink
    shutil.copy2(src, target, follow_symlinks=True)


def _stage_libraries(
    dependencies: Iterable[Path], description: str, build_libs_dir: Path
) -> None:
    """
    Stage multiple libraries to the build_libs_dir directory with error handling.

    Args:
        dependencies: Iterable of library paths to stage
        description: Optional description for error messages
        build_libs_dir: Directory where libraries should be staged
    """
    print(f"\nStaging {description} dependencies")
    for dependency in dependencies:
        try:
            _stage_dependency(dependency, build_libs_dir)
            print(f"\t{dependency}")
        except OSError as e:
            # Some libraries might be inaccessible, continue with others
            print(f"WARN: failed to copy {dependency}: {e}")
