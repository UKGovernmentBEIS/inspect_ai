# Engineering Plan: Runtime Injection of inspect_tool_support

## Problem Statement

The current approach for running some inspect tools in sandboxes requires users to either use pre-built `aisiuk/inspect-tool-support` image or rebuild their existing images with inspect-tool-support installation steps. This creates friction for users with existing, complex container environments.

## Solution Overview

Runtime injection of `inspect-tool-support` into arbitrary running containers, following VS Code remote development pattern. Eliminates need for image modification or pre-built images.

## Key Components

### 1. Executable Build System
- Build dependency-free executables using PyInstaller + StaticX (POC working)
- Target OS support: Ubuntu, Debian, Kali (initially)
- **Issues**: How should we deal with Playwright? Always include it for os/distro's that support it?
- **Details TBD**: Architecture variants

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
- **Details TBD**: Storage location, retrieval method, offline support

## Assumptions

- **Offline-first**: No network access required for containers or inspect_ai process
- **Airgapped support**: Must work when inspect_ai manually copied to isolated machines
- **No fallback**: We will not maintain both the old and new approaches. This means that if injection fails, it will fail the sample (eval?). 


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

## Success Criteria

- Eliminate need for pre-built reference images
- Eliminate need for user Dockerfile modifications
- Maintain existing tool functionality and performance
- Zero version mismatch possibilities

## New Execution Flow

1. User configures `sandbox="docker"` in their evaluation  
2. Tool calls `tool_support_sandbox("tool_name")`
3. inspect_ai detects that container lacks `inspect-tool-support`
4. **Container Reconnaissance**: Probe container OS/architecture via shell commands
5. **Executable Selection**: Determine exact executable version based on:
   - inspect_ai version
   - Detected container OS/architecture
6. **Executable Acquisition**: Obtain executable via installation-method-specific approach:
   - Git clone: Download/cache from network source
   - Package install: Retrieve from bundled/pre-positioned executables
7. **File Injection**: Copy executable to container filesystem
8. **Service Startup**: Execute injected binary to start tool support services
9. **Normal Operation**: Proceed with existing JSON-RPC communication pattern

