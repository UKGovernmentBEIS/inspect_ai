## Continuation Prompt

The prompt below should be valuable when returning to the conversation

### Conversation Summary: Runtime Injection of inspect_tool_support

I analyzed the inspect_ai codebase to understand:
- inspect_tool_support architecture: Containerized tool execution framework with JSON-RPC communication between inspect_ai and sandboxed tools (web browser, bash sessions, text editor)
- Current integration pattern: Tools use tool_support_sandbox() → exec_model_request()/exec_scalar_request() → JSON-RPC calls to container
- User education approach: Users must either use pre-built aisiuk/inspect-tool-support image or add installation steps to their Dockerfiles

Problem Identified

Current approach creates friction - users must rebuild existing images or abandon their custom environments to use inspect_ai tools.

Solution Direction

Runtime injection following VS Code remote development pattern - dynamically inject inspect-tool-support into any running container without image modification.

Engineering Plan Created

Documented in src/inspect_tool_support/_tool_support_injection.md with 5 key components:
1. Executable build system (PyInstaller + StaticX POC working)
2. Container reconnaissance
3. File injection infrastructure
4. Version management system
5. Executable distribution

Topics Deferred for Later Discussion

Executable Distribution (#5):
- Where/how executables are stored and retrieved
- Offline support mechanisms for airgapped environments

OS Detection Strategy (#2):
- Specific shell commands for probing (following VS Code patterns)
- Edge case handling

Playwright Dependencies (#1):
- Whether to bundle in executable vs separate variants vs runtime installation
- Technical feasibility of bundling browser binaries

Version Management (#4):
- Compatibility mapping scheme between inspect_ai and tool_support versions
- Storage and lookup mechanisms
- **Critical requirement**: Zero version mismatch possibilities
- **Approach**: Executables tied to inspect_ai commit hashes/version tags

Network Constraints:
- **Installation method dependencies**:
  - Git clone: Network available during inspect_ai execution
  - Package install: No network dependency (eventual goal)
- Balance between common case usability and extreme offline scenarios

Injection Mechanics (#3):
- Extending SandboxEnvironment interface for dynamic file copying
- Fallback strategies if injection fails

Success Target

Eliminate need for pre-built images or Dockerfile modifications while maintaining full tool functionality.

## Additional Technical & Strategic Context

### Technical Implementation Details
- **POC Status**: Working proof-of-concept already exists using PyInstaller + StaticX combination
- **Initial OS Scope**: Starting with Ubuntu, Debian, and Kali Linux support
- **VS Code Pattern**: Following VS Code remote development injection approach as proven reference implementation
- **JSON-RPC Architecture**: Current system uses sophisticated session management, timeout handling, and error mapping that must be preserved

### Current Integration Methods (To Be Replaced)
1. Pre-built `aisiuk/inspect-tool-support` image usage
2. Custom Dockerfile modifications with installation steps  
3. Inheritance from base image approach

### Strategic Decisions
- **Complete Replacement**: Plan to stop publishing reference images and Dockerfile modification instructions once runtime injection works
- **Error Handling Preservation**: Maintain current clear error messaging when tools aren't available
- **Phased Implementation**: 
  - Phase 1: Ubuntu x64 + git clone + network (validation)
  - Phase 2: Multiple OS variants + package install support
  - Phase 3: Full airgap support

### Tool Communication Context
- Tools use `tool_support_sandbox()` → `exec_model_request()`/`exec_scalar_request()` → JSON-RPC
- Session state managed via Store Models (`WebBrowserStore`, `BashSessionStore`)
- Instance isolation through unique instance IDs
- Structured error mapping from container to inspect_ai exceptions

