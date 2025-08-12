# Engineering Plan: Runtime Injection of inspect_tool_support

## Problem Statement

The current approach for running some inspect tools in sandboxes requires users to either use pre-built `aisiuk/inspect-tool-support` image or rebuild their existing images with inspect-tool-support installation steps. This creates friction for users with existing, complex container environments.

## Solution Overview

Runtime injection of `inspect-tool-support` into arbitrary running containers, following VS Code remote development pattern. Eliminates need for image modification or pre-built images.

## Success Criteria

- No need for pre-built reference images
- No need for user Dockerfile modifications
- Existing tool functionality and performance is unchanged
- No more need for version mismatch scenarios

## Requirements

- **Offline-first**: Must not rely on containers having network access. Same is true for the `inspect_ai` scaffold process, but we could stage the work initially if that proves wise.
- **Airgapped support**: Must ultimately work when inspect_ai manually copied to isolated machines
- **No fallback**: We will not maintain both the old and new approaches. This means that if injection fails, it will fail the sample (eval?).
- **Architecture variants**: `linux/amd64` only for now. No `linux/arm64`.
- Ignore but tolerate pre-existing its in container
- Playwright makes sense in an air gapped container. It's common for containers to have localhost web servers.

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

- Build dependency-free executables using PyInstaller + StaticX (POC working)
- Target OS support: Ubuntu, Debian, Kali (initially)

#### Build Tools

- **PyInstaller**: Bundles Python application and all dependencies into a single executable, including the Python interpreter, libraries, and application code. However, PyInstaller executables still depend on system shared libraries like `libc.so.6`, `libssl.so.1.1`, `libffi.so.6`, and `libz.so.1`
- **StaticX**: Post-processes PyInstaller output to create a fully static binary that includes all shared libraries, eliminating runtime dependencies on the target system. StaticX bundles all system libraries directly into the executable, making it truly portable across different Linux distributions and versions

> [!NOTE] > `PyInstaller` output might still depend on system shared libraries like:
>
> - libc.so.6 (GNU C Library)
> - libssl.so.1.1 (OpenSSL library)
> - libffi.so.6 (Foreign Function Interface library)
> - libz.so.1 (zlib compression library)
>
> So when you run ldd on a `PyInstaller` executable, you might see:
> linux-vdso.so.1 (0x00007fff123456789)
> libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f1234567890)
> libssl.so.1.1 => /usr/lib/x86_64-linux-gnu/libssl.so.1.1 (0x00007f1234567891)
>
> This means the executable would fail on a target system that has:
>
> - Different glibc version
> - Missing OpenSSL libraries
> - Different library paths
>
> `StaticX` fixes this by bundling all these shared libraries directly into the executable, so `ldd` on the `StaticX` output shows: not a dynamic executable
>
> This makes the binary truly portable across different Linux distributions and versions, which is crucial for injecting into arbitrary user containers that may have different library versions or missing dependencies.

#### Build Process

- **Docker Image Build**: Creates a container image with PyInstaller, StaticX, and all build dependencies
- **Source Mount**: Mounts the source code read-only at `/src` in the container
- **Output Mount**: Mounts `./container_build/` directory read-write at `/output` for build artifacts
- **Build Execution**: Runs the containerized build script which:
    1. Copies source to a writable temporary directory
    2. Installs the package dependencies with `pip install .`
    3. Runs PyInstaller to create the executable
    4. Uses StaticX to create a fully static binary
    5. Copies the final executable to the output directory

#### Open Issues

- **Playwright Dependencies**: How should we deal with Playwright? Always include it for distributions that support it?
- **Details TBD**: Architecture variants (x64, ARM64)

### 2. Container Reconnaissance

- OS/distro detection via shell command probes
- **Implementation approach**: Follow VS Code remote detection patterns
- **Details TBD**: Specific probing commands, edge case handling

### 3. File Injection Infrastructure

- Copy selected executable to target container
- **Potential approach**: Extend existing `SandboxEnvironment` interface for dynamic file copying
- **Details TBD**: Injection mechanics, permissions handling

### 4. Version Management System

- Compatibility mapping between inspect_ai versions and tool_support executables
- **Critical requirement**: Avoid any version mismatch possibilities
- **Approach**: Each inspect_ai version has exactly one unambiguous executable version per OS/arch - no compatibility matrix or fallbacks
- **Implementation**: Executables tied to specific inspect_ai commit hashes or version tags
- **Details TBD**: Versioning scheme, mapping storage

### 5. Executable Distribution

- Mechanism for inspect_ai to obtain appropriate executables
- **Network dependency varies by installation method**:
    - Git clone users: Network available during inspect_ai execution
    - Package install users: No network dependency (eventual goal)
- Worst case, we could include the binaries in the wheel file via the following in `pyproject.toml`

    ```toml
    [tool.setuptools.package-data]
    inspect_ai = ["binaries/*"]
    ```

    ```text
    inspect_ai/
    ├── __init__.py
    ├── main.py
    └── binaries/
        ├── inspect-tool-support-debian-x86_64
        ├── inspect-tool-support-ubuntu-x86_64
        └── inspect-tool-support-kali-x86_64
    ```

    And then reference the binaries at runtime with:

    ```python
    import importlib.resources as resources
    import subprocess

    # Get path to the binary
    with resources.path('inspect_ai.binaries', 'binary_name') as binary_path:
        # do something with binary_path
        pass
    ```

- **Details TBD**: Storage location, retrieval method, offline support

## Implementation Phases

### Phase 1: Validation (Git Clone + Network)

- Start with single Linux variant (Ubuntu x64) to prove approach
- Support git clone users with network-dependent executable retrieval
- Validate injection mechanics and performance

### Phase 2: Package Distribution

- Solve executable bundling vs alternative offline distribution
- Support package install users without network dependency
- Scale to multiple OS/architecture variants

### Phase 3: Full Airgap Support

- Complete offline support for all installation methods
- Support manually copied inspect_ai in isolated environments
