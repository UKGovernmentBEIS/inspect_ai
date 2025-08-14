# Engineering Plan: Runtime Injection of inspect_tool_support

## Problem Statement

The current approach for running some inspect tools in sandboxes requires users to either use pre-built `aisiuk/inspect-tool-support` image or rebuild their existing images with inspect-tool-support installation steps. This creates friction for users with existing, complex container environments.

## Solution Overview

Runtime injection of `inspect-tool-support` into arbitrary running containers eliminates the need for image modification or pre-built images. The system automatically injects the appropriate executable based on container architecture and OS detection.

## Success Criteria

- No need for pre-built reference images
- No need for user Dockerfile modifications
- Existing tool functionality and performance unchanged
- No version mismatch scenarios

## Requirements

- **Offline-first**: Must not rely on containers having network access. Host system may have network access during installation
- **Air-gapped support**: Must ultimately work when inspect_ai is manually copied to isolated machines
- **No fallback**: Single injection approach - if injection fails, the evaluation fails (no maintenance of dual approaches)
- **Architecture variants**: `linux/amd64` and `linux/arm64` both supported
- **Pre-existing tools**: Ignore but tolerate pre-existing inspect-tool-support installations in containers
- **Air-gapped containers**: Playwright functionality makes sense in air-gapped containers with localhost web servers

## Recent Accomplishments & Current Status

### Phase 1 Core Implementation - **✅ COMPLETED**

The technical foundation for runtime injection has been successfully implemented and tested:

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
- **Multi-distribution testing**: Confirmed working across Ubuntu, Debian, and Kali Linux containers
- **Architecture support**: Both amd64 and arm64 executables building and deploying correctly
- **Integration testing**: Full injection pipeline from detection through execution validated

### Current Status
Phase 1 core implementation is **functionally complete** and ready for broader community testing before production deployment.

## Current Execution Flow

1. User configures the sandbox in their evaluation (no change from current workflow - though they could stop manually including inspect_tool_support the old way)
2. Tool calls `tool_support_sandbox()` (no change)
3. The `tool_support_sandbox` implementation looks for the appropriate sandbox with `inspect_tool_support` already injected. If not found:
   1. **Container Reconnaissance**: Probes container OS/architecture via shell commands
   2. **Executable Selection**: Determines exact executable version based on detected container architecture
   3. **Executable Access**: Retrieves executable from bundled package data via `importlib.resources`
   4. **File Injection**: Copies executable to container filesystem at `/opt/inspect-tool-support`
   5. **Permission Setup**: Sets executable permissions via `chmod +x`
4. **Normal Operation**: Proceeds with existing JSON-RPC communication pattern with the JSON-RPC transport pointing at the injected executable.

## Implementation Architecture

### 1. Executable Build System

**Status**: ✅ **Implemented and tested** - Produces portable executables for Ubuntu, Debian, Kali Linux on amd64/arm64 architectures

- Build dependency-free executables using PyInstaller + StaticX pipeline
- Fully static ~13MB binaries with no runtime dependencies

#### Build Tools

- **PyInstaller**: Bundles Python application and all dependencies into a single executable, including the Python interpreter, libraries, and application code. However, PyInstaller executables still depend on system shared libraries like `libc.so.6`, `libssl.so.1.1`, `libffi.so.6`, and `libz.so.1`
- **StaticX**: Post-processes PyInstaller output to create a fully static binary that includes all shared libraries, eliminating runtime dependencies on the target system. StaticX bundles all system libraries directly into the executable, making it truly portable across different Linux distributions and versions

> [!WARNING]
> **StaticX Project Status**: StaticX is no longer actively maintained and hasn't received updates in years. Consider migration to **Nuitka** as a potential replacement for both PyInstaller and StaticX in future iterations.


#### Build Process

> [!WARNING]
> **Network Access Required**: The build process requires network access at multiple stages - both during Docker image creation (for downloading build tools) and during container execution (for installing Python dependencies via `pip install .`). The build system cannot operate in air-gapped environments.

- **Docker Image Build**: Creates a container image with PyInstaller, StaticX, and all build dependencies (requires network access for package downloads)
- **Source Mount**: Mounts the source code read-only at `/inspect_tool_support` in the container  
- **Output Mount**: Mounts `../inspect_ai/binaries/` directory for direct package integration
- **Build Execution**: Runs the containerized build script which:
  1. Copies source to a writable temporary directory
  2. Installs the package dependencies with `pip install .` (requires network access for PyPI downloads)
  3. Runs PyInstaller to create the executable
  4. Uses StaticX to create a fully static binary (~13MB)
  5. Copies the final executable to the output directory with proper naming

### 2. On Demand Executable Injection

**Status**: ✅ **Implemented and tested** - Complete runtime injection system that automatically deploys executables to containers based on architecture detection

The injection system performs container reconnaissance to determine the appropriate executable, then dynamically deploys it without requiring pre-built images or container modifications.

#### 2.1 Container Reconnaissance

- Detects OS/distribution and architecture via shell command probes
- Normalizes architecture names (amd64→x86_64, arm64→aarch64) for consistent executable selection
- Multiple fallback mechanisms: `/etc/os-release` → version files → `uname` output

#### 2.2 File Injection Infrastructure

- Injects executable to `/opt/inspect-tool-support` using existing `SandboxEnvironment.write_file()`
- Accesses bundled executables via `importlib.resources` from package data
- Handles permission setting with `chmod +x` after injection

### 3. Executable Distribution

**Status**: 🔄 **Partially Implemented** - Working (manually) for editable installs, other cases need additional work

Mechanism for `tool_support_sandbox` to obtain appropriate executables varies by installation method. Ultimately, the executables will end up in a common location (`/binaries`), but the way that get there will differ based on three distinct installation cases below:

#### Case 1: PyPI Package Installation (`pip install inspect-ai`)

**Status**: ⚠️ **CI integration needed**

- **Build Process**: Executables pre-built during package publishing process
  - CI/CD pipeline runs `./build_within_container.sh --all` to create both amd64 and arm64 binaries
  - Total size impact: ~26MB (13MB × 2 architectures) added to package
- **Distribution**: Executables bundled in the wheel file via package data, ensuring exact version matching
- **Runtime Access**: Using `importlib.resources` to locate bundled executables (✅ implemented)
- **Version Management**: Executables are built from the same source tree as the package, guaranteeing version consistency

#### Case 2: Git Reference Installation (`pip install git+https://github.com/...`)

**Status**: ❌ **Critical requirement - needs pre-built binary hosting solution**

- **Challenge**: Cannot require Docker for users installing from git references
- **Proposed Solution**: Pre-built binaries hosted externally (GitHub releases, CDN) tagged with specific commit hashes or version tags
  - **Remaining question**: Publishing frequency (every commit vs. releases)
- **Requirement**: Must work without network access in containers, but host can download binaries during installation
- **Version Management**: Binaries tagged/named with commit hashes to ensure exact version matching with source installation

#### Case 3: Editable Installation (`pip install -e .` or `pip install -e git+...`)

**Status**: 🔄 **Working manually, but not yet automated** - Build script functional but requires manual execution

- **Build Process**: Manual calling of `build_within_container.sh` (automation integration pending)
- **Distribution**: Build system outputs directly to `src/inspect_ai/binaries/` for immediate availability
- **Runtime Access**: Same `importlib.resources` pattern as other installation methods
- **Version Management**: Executables built from current source tree ensure perfect version alignment with development code

## Remaining Work

### High Priority

1. **Case 2 Git Installation Support**: Design and implement pre-built binary hosting solution for git reference installations
2. **Case 3 On-Demand Build Integration**: Integrate `build_within_container.sh` calling into the injection flow for editable installations when binaries are missing
3. **CI/CD Integration**: Integrate build system into inspect_ai's existing CI and deployment processes for automated binary generation

### Medium Priority

1. **Web Browser Tools**: Resolve PyInstaller/StaticX conflicts with Playwright's bundled shell scripts to re-enable web browser functionality
2. **Playwright Dependencies**: Consult PyInstaller's explicit Playwright documentation for proper bundling strategies in air-gapped containers

### Future Considerations

1. **Build Tool Migration**: Evaluate migration from StaticX (unmaintained) to Nuitka for improved long-term sustainability


## Implementation Phases

### Phase 1: Core Runtime Injection - ✅ **COMPLETED**

- ✅ Cross-platform build system with portable executables
- ✅ Container reconnaissance and injection mechanics
- ✅ Validation across Ubuntu, Debian, and Kali Linux containers
- **Next**: Community testing and feedback collection

### Phase 2: Installation Method Support - 🔄 **IN PROGRESS**

- **Remaining**: Git reference installation binary distribution (Case 2)
- **Remaining**: Editable installation automation (Case 3)
- **Remaining**: CI/CD integration for PyPI packaging (Case 1)

### Phase 3: Remaining Requirements - ⏳ **PENDING**

- Web browser tools re-enablement
- Full air-gap support for all installation methods