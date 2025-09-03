#!/usr/bin/env python3
"""
PORTABLE PLAYWRIGHT PYINSTALLER BUILD SCRIPT

PURPOSE:
This script uses PyInstaller to create a fully self-contained, portable executable
from a Python application that uses Playwright and a headless browser. It solves
the problem of bundling Chromium dependencies with the application to ensure it
can run on different Linux systems without requiring users to install Playwright
or Chromium separately.

WHY MANUAL DEPENDENCY COLLECTION IS REQUIRED:
PyInstaller automatically handles Python module dependencies and their C extensions,
but it does NOT analyze or bundle dependencies of standalone binaries included via
--add-binary. When we include Chromium's headless_shell executable, PyInstaller
treats it as a data file and doesn't discover its shared library dependencies. This
script manually uses ldd to find these dependencies and explicitly bundles them,
which PyInstaller cannot do automatically.

WORKFLOW:
1. Install Chromium into the Playwright package directory (not user home)
2. Locate the chromium-headless-shell binary that Playwright uses for Chromium
3. Use ldd to discover all shared library dependencies
4. Explicitly add NSS and WebGL libraries that may be loaded dynamically
5. Bundle everything into a single executable with PyInstaller

OUTPUT:
A single executable file in dist/main that contains:
- Embedded python interpreter
- The python application code
- The Playwright library
- Chromium browser (headless_shell)
- All necessary shared libraries
- NSS security libraries
- WebGL libraries

COMPATIBILITY:
- Requires same or newer glibc version as build system (core glibc libraries are
  excluded to maintain ABI compatibility)
- For true cross-distribution compatibility, run StaticX on the output
"""

import argparse
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

# Import build configuration
try:
    from ._tool_support_build_config import BuildConfig, filename_to_config
except ImportError:
    # Handle direct execution or when run from Docker
    from _tool_support_build_config import BuildConfig, filename_to_config

# Directory where this build script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Temporary directory where collected libraries will be staged before bundling
BUILD_LIBS = SCRIPT_DIR / "build_libs"


def main() -> None:
    """
    Main orchestration function that runs the complete build process.

    This function coordinates all steps in sequence:
    1. Parse command line arguments and build configuration
    2. Verify PyInstaller is available
    3. Conditionally install Chromium into the package directory
    4. Find the headless_shell binary (if browser support enabled)
    5. Collect all required libraries
    6. Build the final executable with PyInstaller
    7. Optionally apply staticx for maximum portability

    The result is a portable executable that includes everything needed
    to run with or without Playwright and Chromium on any compatible Linux system.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-tool-support executable"
    )
    parser.add_argument(
        "filename",
        nargs="?",
        help="Executable filename (e.g., 'inspect-tool-support-amd64-v667-dev')",
    )
    parser.add_argument(
        "--entry-point",
        help="Path to main.py entry point (relative to current directory or absolute)",
    )
    parser.add_argument(
        "--output-dir", help="Output directory for the built executable"
    )
    parser.add_argument(
        "--no-staticx",
        action="store_true",
        help="Skip staticx processing (reduces portability but faster build)",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for the build (for container-based builds)",
    )

    args = parser.parse_args()

    # Handle filename argument and build config
    if args.filename:
        build_config = filename_to_config(args.filename)
        executable_name = args.filename
    else:
        # Default configuration when no filename specified
        build_config = BuildConfig(arch="amd64", version=1, browser=True, suffix=None)
        executable_name = "main"

    print(f"\nBuilding portable executable for {executable_name}...\n")
    print(
        f"Configuration: arch={build_config.arch}, version={build_config.version}, browser={build_config.browser}, suffix={build_config.suffix}"
    )

    # Determine entry point
    if args.entry_point:
        entrypoint = Path(args.entry_point)
        if not entrypoint.is_absolute():
            entrypoint = SCRIPT_DIR / entrypoint
    else:
        # Try container path first, then fallback to local main.py
        container_entry = Path(
            "/inspect_ai/src/inspect_tool_support/src/inspect_tool_support/_cli/main.py"
        )
        local_entry = SCRIPT_DIR / "main.py"
        relative_entry = (
            SCRIPT_DIR.parent.parent.parent
            / "inspect_tool_support/src/inspect_tool_support/_cli/main.py"
        )

        if container_entry.exists():
            entrypoint = container_entry
        elif relative_entry.exists():
            entrypoint = relative_entry
        elif local_entry.exists():
            entrypoint = local_entry
        else:
            raise FileNotFoundError(
                f"Could not locate main.py entry point. Tried:\n"
                f"  - {container_entry}\n"
                f"  - {relative_entry}\n"
                f"  - {local_entry}\n"
                f"Use --entry-point to specify the location."
            )

    print(f"Using entry point: {entrypoint}")

    # Determine output directory and path
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Check if we're in a container environment
        container_output = Path("/inspect_ai/src/inspect_ai/binaries")
        if container_output.exists():
            output_dir = container_output
        else:
            output_dir = SCRIPT_DIR / "dist"

    output_path = output_dir / executable_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output will be: {output_path}")

    # Handle working directory for container builds
    original_cwd = None
    if args.working_dir:
        original_cwd = Path.cwd()
        working_path = Path(args.working_dir)
        if working_path.exists():
            os.chdir(working_path)
            print(f"Changed working directory to: {working_path}")

    try:
        # Verify build environment
        _ensure_pyinstaller_available()

        # Prepare build environment (copy source and install package)
        build_working_dir = _prepare_build_environment()

        # Adjust BUILD_LIBS to be in the working directory
        build_libs_dir = build_working_dir / "build_libs"

        # Conditionally install browser and collect dependencies
        headless_shell = None
        if build_config.browser:
            # Install browser into package (not user home)
            headless_shell = _install_chromium_headless_shell()
        else:
            print("[1/4] Skipping Chromium installation (browser support disabled)")

        # Collect and stage all extra dependencies/libraries
        if build_libs_dir.exists():
            shutil.rmtree(build_libs_dir)
        build_libs_dir.mkdir(parents=True, exist_ok=True)

        if headless_shell:
            _stage_libraries(
                _ldd_deps(headless_shell), "ldd dependencies", build_libs_dir
            )
            _stage_libraries(_nss_deps(), "NSS dependencies", build_libs_dir)
            _stage_libraries(_webgl_deps(), "WebGL dependencies", build_libs_dir)
        else:
            print("[3/4] Skipping library collection (no browser support)")

        # Each library needs a --add-binary argument in the format "source:dest"
        # The :lib suffix tells PyInstaller to place these in a lib/ subdirectory
        add_binary_args = [
            f"--add-binary={str(f)}:lib" for f in build_libs_dir.glob("*")
        ]

        # Build the executable
        temp_output = _build_executable(add_binary_args, entrypoint, executable_name)

        # Apply staticx by default for maximum portability (matching build_executable.py)
        if args.no_staticx:
            print("[5/5] Skipping staticx (--no-staticx specified)")
            # Just move the file to final location
            if temp_output != output_path:
                shutil.move(temp_output, output_path)
                output_path.chmod(0o755)
        else:
            print("[5/5] Applying staticx for maximum portability...")
            _apply_staticx(temp_output, output_path)

        # Verify the build (matching build_executable.py verification)
        _verify_build(output_path, executable_name, build_config)

    finally:
        # Restore original working directory
        if original_cwd:
            os.chdir(original_cwd)


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout


def _ensure_pyinstaller_available() -> None:
    try:
        # Try to run PyInstaller as a module to check if it's available
        _run([sys.executable, "-m", "PyInstaller", "--version"])
    except RuntimeError as e:
        # Provide helpful error message with installation command
        raise RuntimeError(
            "PyInstaller not found in this Python environment. "
            f"Install it with:\n  {sys.executable} -m pip install pyinstaller"
        ) from e


def _prepare_build_environment() -> Path:
    """
    Prepare the build environment by copying source and installing package.

    This matches the workflow from build_executable.py:
    1. Copy /inspect_ai/src/inspect_tool_support to /tmp/inspect_tool_support-copy
    2. Change to the copy directory
    3. Run pip install . to install the package

    Returns:
        Path to the working directory for the build
    """
    # Container paths (matching build_executable.py)
    repo_dir = Path("/inspect_ai")
    source_dir = repo_dir / "src" / "inspect_tool_support"
    copy_dir = Path("/tmp/inspect_tool_support-copy")

    # Verify we're in a container environment
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Expected container source directory not found: {source_dir}\n"
            "This function requires the container environment setup."
        )

    # Remove existing copy directory to allow multiple runs
    if copy_dir.exists():
        shutil.rmtree(copy_dir)

    print(f"Copying source from {source_dir} to {copy_dir}")
    print("  (This avoids mutating the mounted repo)")

    # Make a copy into /tmp to avoid mutating the mounted repo
    shutil.copytree(source_dir, copy_dir)

    # Change to the copy directory
    os.chdir(copy_dir)
    print(f"Changed working directory to: {copy_dir}")

    # Install the package
    print("Installing package...")
    _run([sys.executable, "-m", "pip", "install", "."])

    return copy_dir


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

    Args:
        ldd_output: Raw output from the ldd command

    Returns:
        Set of Path objects for libraries that should be bundled
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


def _build_executable(
    extra_binaries: list[str], entrypoint: Path, executable_name: str
) -> Path:
    """
    Execute PyInstaller to create the final executable.

    The resulting executable will self-extract to a temporary directory
    at runtime and set up the library paths appropriately.

    Args:
        extra_binaries: List of --add-binary arguments for shared libraries
        entrypoint: Path to the main Python script
        executable_name: Name for the output executable

    Returns:
        Path to the built executable
    """
    print("[4/4] Building PyInstaller onefile binary")

    # Set environment to use package-local browser
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    # Construct the full PyInstaller command
    cmd = (
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",  # Single executable output
            "--noupx",  # Don't compress - prevents driver corruption
            # "--strip",  # REMOVED - can break node binary (consider re-enabling if issues are resolved)
            "--optimize",
            "2",
            "--collect-all",  # Collect all files from the playwright package
            "playwright",  # Package name for --collect-all
            "--hidden-import=psutil",
            "--copy-metadata=inspect_tool_support",
            "--copy-metadata=playwright",  # Include playwright metadata
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "test",
            "--exclude-module",
            "unittest",
            "--exclude-module",
            "pdb",
            "--name",
            executable_name,
        ]
        + extra_binaries
        + [str(entrypoint)]
    )  # --add-binary arguments + entry point

    print("# PyInstaller command:")
    print(" ".join(cmd))

    # Run PyInstaller in the current directory (temp directory for container builds)
    _run(cmd, env=env)

    # Return path to built executable
    return Path("dist") / executable_name


def _apply_staticx(input_path: Path, output_path: Path) -> None:
    """
    Apply staticx to create a fully static executable for maximum portability.

    Args:
        input_path: Path to the PyInstaller-built executable
        output_path: Path for the final static executable
    """
    try:
        staticx_cmd = [
            "staticx",
            "--strip",
            str(input_path),
            str(output_path),
        ]
        _run(staticx_cmd)

        # Make executable
        output_path.chmod(0o755)

    except subprocess.CalledProcessError as e:
        print(f"Warning: staticx failed: {e}")
        print("Falling back to PyInstaller-only build...")
        # Just copy the file if staticx fails
        shutil.copy2(input_path, output_path)
        output_path.chmod(0o755)


def _verify_build(
    output_path: Path, executable_name: str, build_config: BuildConfig
) -> None:
    """
    Verify the built executable and display build information.

    This matches build_executable.py's verification approach exactly.

    Args:
        output_path: Path to the final executable
        executable_name: Name of the executable
        build_config: Build configuration for architecture messaging
    """
    # Verify portability (matching build_executable.py lines 112-123)
    print("Verifying portability...")
    try:
        result = subprocess.run(
            ["ldd", str(output_path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("✅ Fully static - maximum portability achieved")
        else:
            print(result.stdout)
    except FileNotFoundError:
        # ldd not available
        print("⚠️ ldd not available - portability could not be verified")

    # Show what we built (matching build_executable.py lines 125-127)
    try:
        subprocess.run(["ls", "-lh", str(output_path)], check=True)
        subprocess.run(["file", str(output_path)], check=True)
    except subprocess.CalledProcessError:
        # Commands might not be available in some environments
        pass

    # Final success messages (matching build_executable.py lines 129-130)
    print(f"✅ Portable executable ready: {executable_name}")

    # Architecture-specific compatibility message
    if build_config.arch == "arm64":
        print("This should run on any Linux ARM64/aarch64 system from ~2016 onwards")
    else:
        print("This should run on any Linux x86_64 system from ~2016 onwards")


if __name__ == "__main__":
    # Entry point when running as a script
    main()
