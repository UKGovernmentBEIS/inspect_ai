# Engineering Plan: Runtime Injection of inspect_tool_support

## Problem Statement

The current approach for running some inspect tools in sandboxes requires users to either use pre-built `aisiuk/inspect-tool-support` image or rebuild their existing images with inspect-tool-support installation steps. This creates friction for users with existing, complex container environments.

## Solution Overview

Runtime injection of `inspect-tool-support` into arbitrary running containers, following VS Code remote development pattern. Eliminates need for image modification or pre-built images.

## Success Criteria

-   No need for pre-built reference images
-   No need for user Dockerfile modifications
-   Existing tool functionality and performance is unchanged
-   No more need for version mismatch scenarios

## Requirements

-   **Offline-first**: Must not rely on containers having network access. Same is true for the `inspect_ai` scaffold process, but we could stage the work initially if that proves wise.
-   **Airgapped support**: Must ultimately work when inspect_ai manually copied to isolated machines
-   **No fallback**: We will not maintain both the old and new approaches. This means that if injection fails, it will fail the sample (eval?).
-   **Architecture variants**: `linux/amd64` and `linux/arm64` both supported.
-   Ignore but tolerate pre-existing its in container
-   Playwright makes sense in an air gapped container. It's common for containers to have localhost web servers.

## New Execution Flow

1. User configures the sandbox in their evaluation just like they always have.
2. Tool calls `tool_support_sandbox("tool_name")` (No change)
3. The implementation of `tool_support_sandbox` will do look for the appropriate sandbox (optionally named) that has `inspect_tool_support` already injected. If not found, it will:

    1. **Container Reconnaissance**: Probe container OS/architecture via shell commands
    2. **Executable Selection**: Determine exact executable version based on:
        - inspect_ai version
        - Detected container OS/architecture
    3. **Executable Acquisition**: Obtain executable via installation-method-specific approach:
        - Git clone: Download/cache from network source
        - Package install: Retrieve from bundled/pre-positioned executables
    4. **File Injection**: Copy executable to container filesystem

4. **Normal Operation**: Proceed with existing JSON-RPC communication pattern

## Key Components

### 1. Executable Build System

**Status**: ✅ **Implemented and validated** - Build system producing portable executables across target Linux distributions

-   Build dependency-free executables using PyInstaller + StaticX 
-   Target OS support: Ubuntu, Debian, Kali Linux
-   Cross-platform builds: amd64 and arm64 architectures

#### Build Tools

-   **PyInstaller**: Bundles Python application and all dependencies into a single executable, including the Python interpreter, libraries, and application code. However, PyInstaller executables still depend on system shared libraries like `libc.so.6`, `libssl.so.1.1`, `libffi.so.6`, and `libz.so.1`
-   **StaticX**: Post-processes PyInstaller output to create a fully static binary that includes all shared libraries, eliminating runtime dependencies on the target system. StaticX bundles all system libraries directly into the executable, making it truly portable across different Linux distributions and versions

> [!WARNING]
> **StaticX Project Status**: StaticX is no longer actively maintained and hasn't received updates in years. Consider migration to **Nuitka** as a potential replacement for both PyInstaller and StaticX in future iterations.

> [!NOTE] > `PyInstaller` output might still depend on system shared libraries like:
>
> -   libc.so.6 (GNU C Library)
> -   libssl.so.1.1 (OpenSSL library)
> -   libffi.so.6 (Foreign Function Interface library)
> -   libz.so.1 (zlib compression library)
>
> So when you run ldd on a `PyInstaller` executable, you might see:
> linux-vdso.so.1 (0x00007fff123456789)
> libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f1234567890)
> libssl.so.1.1 => /usr/lib/x86_64-linux-gnu/libssl.so.1.1 (0x00007f1234567891)
>
> This means the executable would fail on a target system that has:
>
> -   Different glibc version
> -   Missing OpenSSL libraries
> -   Different library paths
>
> `StaticX` fixes this by bundling all these shared libraries directly into the executable, so `ldd` on the `StaticX` output shows: not a dynamic executable
>
> This makes the binary truly portable across different Linux distributions and versions, which is crucial for injecting into arbitrary user containers that may have different library versions or missing dependencies.

#### Build Process

-   **Docker Image Build**: Creates a container image with PyInstaller, StaticX, and all build dependencies
-   **Source Mount**: Mounts the source code read-only at `/inspect_tool_support` in the container  
-   **Output Mount**: Mounts `../inspect_ai/binaries/` directory for direct package integration
-   **Build Execution**: Runs the containerized build script which:
    1. Copies source to a writable temporary directory
    2. Installs the package dependencies with `pip install .`
    3. Runs PyInstaller to create the executable
    4. Uses StaticX to create a fully static binary (~13MB)
    5. Copies the final executable to the output directory with proper naming

#### Remaining Work

-   **Playwright Dependencies**: Unresolved due to Playwright/StaticX conflicts. Need to resolve Playwright dependency management for air-gapped containers. PyInstaller has explicit Playwright documentation that should be consulted.
-   **CI/CD Integration**: Need to integrate build system into inspect_ai's existing CI and deployment processes for automated binary generation

### 2. Container Reconnaissance

**Status**: ✅ **Implemented and tested** - Robust OS/architecture detection across target platforms

-   OS/distribution detection via comprehensive shell command probes
-   Architecture detection with proper normalization (amd64→x86_64, arm64→aarch64)  
-   Multiple fallback mechanisms for edge case handling

#### Implementation Details

-   **Primary detection**: `/etc/os-release` parsing for modern Linux distributions
-   **Fallback mechanisms**: Version-specific files (`/etc/kali_version`, `/etc/debian_version`) and `uname` output
-   **Architecture mapping**: Handles Docker/platform naming variations (amd64↔x86_64, arm64↔aarch64)
-   **Cross-platform support**: Linux, Windows, and macOS detection logic (though only Linux injection supported currently)

#### Validation Results

-   **Distribution support**: Confirmed detection across Ubuntu, Debian, and Kali Linux containers
-   **Architecture support**: Proper detection of both amd64/x86_64 and arm64/aarch64 variants
-   **Edge case handling**: Robust fallback chain ensures detection even in minimal container environments

### 3. File Injection Infrastructure

**Status**: ✅ **Implemented and working** - Clean integration with existing sandbox infrastructure

-   Copy selected executable to target container at fixed path (`/opt/inspect-tool-support`)
-   Uses existing `SandboxEnvironment.write_file()` method without interface modifications
-   Automatic permission handling via `chmod +x` for executable deployment

#### Implementation Details

-   **Binary access**: Uses `importlib.resources` to access bundled executables from package data
-   **Injection target**: Fixed path `/opt/inspect-tool-support` suitable across Linux distributions  
-   **Permission handling**: Explicit `chmod +x` after injection (write_file() drops execute permissions)
-   **Memory efficiency**: Direct file stream copying without intermediate staging

#### Validation Results

-   **Cross-distribution compatibility**: Confirmed working across Ubuntu, Debian, and Kali Linux
-   **Permission handling**: Executable permissions correctly applied in all tested environments
-   **Integration**: Clean integration with existing `SandboxEnvironment` interface without modifications

### 4. Version Management System

-   Compatibility mapping between inspect_ai versions and tool_support executables
-   **Critical requirement**: Avoid any version mismatch possibilities
-   **Approach**: Each inspect_ai version has exactly one unambiguous executable version per OS/arch - no compatibility matrix or fallbacks
-   **Implementation**: Executables tied to specific inspect_ai commit hashes or version tags
-   **Details TBD**: Versioning scheme, mapping storage

### 5. Executable Distribution

**Status**: 🔄 **Partially implemented** - Working for editable installs, PyPI and git reference installs need additional work

Mechanism for inspect_ai to obtain appropriate executables varies by installation method. Three distinct installation cases must be handled:

#### Case 1: PyPI Package Installation (`pip install inspect-ai`)

**Status**: ⚠️ **CI integration needed**

-   **Build Process**: Executables are pre-built during the package publishing process
    -   CI/CD pipeline runs `./build_within_container.sh --all` to create both AMD64 and ARM64 binaries
    -   Total size impact: ~26MB (13MB × 2 architectures) added to package
-   **Distribution**: Executables bundled in the wheel file via `pyproject.toml` package data:

    ```toml
    [tool.setuptools.package-data]
    inspect_ai = ["binaries/*"]
    ```

    ```text
    inspect_ai/
    ├── __init__.py
    ├── main.py
    └── binaries/
        ├── inspect-tool-support-amd64
        └── inspect-tool-support-arm64
    ```

-   **Runtime Access**: Using `importlib.resources` to locate bundled executables (✅ implemented)

#### Case 2: Git Reference Installation (`pip install git+https://github.com/...`)

**Status**: ❌ **Critical requirement - needs pre-built binary hosting solution**

-   **Challenge**: Cannot require Docker for users installing from git references
-   **Proposed Solution**: Pre-built binaries hosted externally (GitHub releases, CDN)
    -   **Remaining question**: Publishing frequency (every commit vs. releases)
-   **Requirement**: Must work without network access in containers, but host can download binaries during installation

#### Case 3: Editable Installation (`pip install -e .` or `pip install -e git+...`)

**Status**: ✅ **Working** - Can automate on-demand builds

-   **Build Process**: Automated calling of `build_within_container.sh` on-demand
-   **Distribution**: Build system outputs directly to `src/inspect_ai/binaries/` for immediate availability
-   **Runtime Access**: Same `importlib.resources` pattern as other installation methods

#### Common Architecture

All installation methods result in executables accessible via the same `importlib.resources` path, ensuring consistent runtime behavior regardless of installation method.

## Recent Accomplishments

### Phase 1 Core Implementation Completed

The technical foundation for Phase 1 has been successfully implemented and tested:

#### Build System Infrastructure
- **Cross-platform build orchestration**: `build_within_container.sh` supports both amd64 and arm64 architectures with `--all` flag
- **Portable executable generation**: `build_executable.sh` uses PyInstaller + StaticX pipeline to create fully static ~13MB Linux binaries
- **Container validation**: `test_distros.sh` confirms executable compatibility across Ubuntu, Debian, and Kali Linux containers
- **CI integration ready**: Build system outputs directly to `src/inspect_ai/binaries/` for package bundling

#### Runtime Injection System
- **Container reconnaissance**: Comprehensive OS/architecture detection in `_tool_support_sandbox.py` with robust fallback mechanisms
- **Dynamic injection**: `inject_tool_support_code()` uses `importlib.resources` to access bundled executables and inject via `SandboxEnvironment.write_file()`
- **Position independence**: Executable achieves location independence using `sys.argv[0]` for server subprocess spawning
- **PyInstaller compatibility**: Replaced dynamic module loading in `load_tools.py` with static imports and registry for build-time analysis

#### Validation Results
- **Multi-distro testing**: Confirmed working across Ubuntu, Debian, and Kali Linux containers
- **Architecture support**: Both amd64 and arm64 executables building and deploying correctly
- **Integration testing**: Full injection pipeline from detection through execution validated

### Current Status
Phase 1 core implementation is **functionally complete** and ready for broader community testing before production deployment.

## Implementation Phases

### Phase 1: Validation (Git Clone + Network) - **COMPLETED**

- ✅ Proved approach with Linux variants (Ubuntu, Debian, Kali)
- ✅ Built injection mechanics and performance validation infrastructure  
- ✅ Created cross-platform build system with portable executables
- **Next**: Community testing and feedback collection

### Phase 2: Package Distribution - **IN PROGRESS**

- **Remaining**: Solve executable bundling vs alternative offline distribution
- **Remaining**: Support package install users without network dependency
- **Remaining**: Scale to multiple OS/architecture variants
- **Remaining**: CI/CD integration for automated binary publishing

### Phase 3: Full Airgap Support - **PENDING**

- Complete offline support for all installation methods
- Support manually copied inspect_ai in isolated environments
