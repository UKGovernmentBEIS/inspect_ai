# Design Document: Tool Support Executable Publishing and Retrieval

## Overview

This document outlines the complete lifecycle of tool support executables: from automated publishing of versioned executables to S3 storage through to on-demand retrieval by `inspect_ai` installations. The system ensures that the required executables are available when needed across a variety of usage scenarios.

## Success Criteria

1. **Version Integrity**: Both `inspect_ai` and `inspect_tool_support` code can rely on exact version matching
2. **Build Validation**: PRs that modify `inspect_tool_support` cannot merge until executable builds succeed
3. **Immediate Availability**: Users can download executables immediately after S3 promotion
4. **Container Isolation Support**: The injection process succeeds even when the target container has no network connectivity
5. **Air-Gapped Host Support**: The system provides mechanisms for pre-staging executables when the host system lacks network access

## Stakeholder Roles

### **Release version user**
- Runs `pip install inspect-ai` to get the latest stable release from PyPI
- Expects executables to be pre-bundled in the package with no additional steps
- Represents the majority of users who want a "just works" experience

### **Pre-release version user**
- Runs `pip install git+https://github.com/...` to get latest features from main branch that haven't been published to PyPI yet
- Does not make edits to `inspect_ai` code
- Expects executables to be automatically available without manual intervention

### **Developer**
- Works with editable or development installations of `inspect_ai`
- May or may not make changes to tool support code in `src/inspect_tool_support/`
- Has limited permissions and cannot directly publish to production systems

### **GitHub Workflows (Automated System)**
- Automated CI/CD system that handles the publishing workflow
- Operates with secure credentials and publishing permissions
- Builds and validates executables across multiple architectures
- S3 publishing workflows can only be triggered by **Repository Maintainers**

### **Repository Maintainer**
- Has administrative permissions for the repository and publishing systems
- Reviews and approves changes before they reach production
- Controls the promotion of executables from development to production storage

The following sections detail how these stakeholders interact in the publishing workflow.

## Executable Publishing

### Pre-Release Publishing

When a **developer** makes any changes to `src/inspect_tool_support/`, the following is the process:

1. **Developer** makes changes to `src/inspect_tool_support/` and bumps `tool_support_version.txt` file (e.g., 1 → 2)
2. **Developer** creates PR with code changes and version bump
3. **GitHub Workflow `build_tool_support.yml`** detects `tool_support_version.txt` change in PR and automatically rebuilds on every push to the PR branch:
   - Builds executables for both architectures using `build_within_container.py --include-version` from the latest commit
   - Stores as workflow artifacts, overwriting previous executables:
     - `inspect-tool-support-amd64-v2`
     - `inspect-tool-support-arm64-v2`
   - Comments on PR with build status and link to Actions artifacts
   - Sets PR status check (blocks merge if build fails)
   - **Only triggers for PRs - ensures all `tool_support_version.txt` changes go through review process**
   - **Ensures promoted executables are built from the final commit state**
4. **Repository Maintainer** reviews PR, code changes, and downloads artifacts from Actions tab for testing
5. **Repository Maintainer** manually triggers `promote_tool_support.yml` workflow (specifies PR number or workflow run):
   - Downloads artifacts from the specified workflow run
   - Uploads artifacts to S3 bucket with versioned names:
     - `inspect-tool-support-amd64-v2`
     - `inspect-tool-support-arm64-v2`
   - Sets S3 objects as world-readable (immediately available for download)
6. **Repository Maintainer** merges PR (executables already available in S3)

For official releases, a separate process packages these S3 executables into PyPI distributions:

### PyPI Publishing

For **Repository Maintainers** preparing PyPI releases:

1. **Repository Maintainer** checks out the commit that will be published
1. **Repository Maintainer** runs `download-tool-support.sh` script:
   - Script reads version from `tool_support_version.txt`
   - Downloads proper executables for both architectures from S3
   - No credentials needed (S3 objects are world-readable)
   - Places executables into `binaries` directory
1. **Repository Maintainer** proceeds with standard PyPI publishing process

Once executables are published (either to S3 or bundled in PyPI), the system must retrieve them on-demand:

## Executable Retrieval

The retrieval of tool support executables happens on-demand when a tool requires the support code be injected into the container. The public API `inject_tool_support_code()` is called at tool execution time, which internally orchestrates the entire retrieval process implemented in `_tool_support_sandbox.py`. This flow supports multiple installation scenarios while ensuring users always get the correct executable version.

The on-demand retrieval system handles these installation types:

1. **PyPI installed** - Standard `pip install inspect-ai` from PyPI package (**Release version user**)
2. **Git reference installed** - `pip install git+https://github.com/...` from specific commit/branch (**Pre-release version user**)
3. **Editable install** - `pip install -e .` either using existing version or after a local version increment (**Developer**)

#### `inject_tool_support_code()` Flow

1. **OS and Architecture Detection**
   - Call `_detect_sandbox_os()` to determine the OS and architecture of the running sandbox
   - Returns architecture (amd64/arm64) along with OS information

2. **Version Resolution**
   - Read required version from `tool_support_version.txt`
   - Build versioned executable name: `inspect-tool-support-{arch}-v{version}`

3. **Resolve Required Executable**
   
   3.1. **Local Executable Check**
      - Check if required executable already exists in `binaries/` directory
      - If found → **DONE**

   3.2. **S3 Download Attempt**
      - Attempt to download versioned executable from S3 bucket
      - Download URL: `s3://inspect-tool-support/inspect-tool-support-{arch}-v{version}`
      - Save to local `binaries/` directory with standard name
      - If download successful → **DONE**
      - Report/warn about failure and proceed to next step

   3.3. **User Build Prompt**
      - If S3 download fails, prompt user: "Executable not found. Build locally? (requires Docker)"
      - If user declines → **ERROR**
      - Proceed to next step

   3.4. **Local Build Process**
      - Execute `build_within_container.sh` with target architecture
      - Build creates the required executable in `binaries/` directory
      - If build successful → **DONE**
      - If build fails → **ERROR**

4. **Inject Resolved Executable Into Container**

The following components implement this publishing and retrieval system:

## Technical Details

### Code Components

#### `tool_support_version.txt`

Contains the version. Could be enhanced to also contain the fingerprint.

#### `inject_tool_support_code()`

Public API function that orchestrates the entire retrieval process as detailed in the flow above.

#### `build-tool-support.yml`

 A GitHub workflow (configured to run on pushes to a PR branch) will notice `tool_support_version.txt` bump and will include a gated CI step to build `inspect-tool-support-amd64-v2` into action artifact

**Triggers:**
- PR opened/updated with changes to `tool_support_version.txt` (PRs only)
- Every subsequent push to a PR branch with `tool_support_version.txt` changes (ensures latest commit)

**Jobs:**
1. **Version Detection**
   - Extract old/new version from `tool_support_version.txt` file
   - Skip if version unchanged
   - Validate version format (simple integer)
2. **Multi-Architecture Build**
   - Matrix build: `[amd64, arm64]`
   - Use existing `build_within_container.py --include-version` script to create versioned executables
   - Upload executables as workflow artifacts (auto-expire after 90 days)
3. **PR Integration**
   - Comment on PR with build status
   - Set status check for merge blocking
   - Link to Actions artifacts for download/testing

#### `promote-tool-support.yml`

This workflow will given a PR # as input. It will grab the workflow artifact `inspect-tool-support-amd64-v2` from that PR and publish it to S3 bucket. The workflow will require the proper S3 access credentials in its environment. It will need to mark the uploaded files as world readable. This workflow must be triggerable only by maintainers.

**Triggers:**
- Manual dispatch (**Repository Maintainers** only)
- **Inputs**: PR number or workflow run ID (to identify which artifacts to promote)

**Jobs:**
1. **S3 Promotion**
   - Download artifacts from specified workflow run
   - Upload artifacts to S3 bucket with versioned names
   - Set S3 object permissions to world-readable
   - Verify upload success (immediately available for download)

#### `download-tool-support.sh`

 The script will not need any credentials since the executables in S3 are world readable.

These components require specific security measures and access controls:

## Security

**Repository Secrets Required:**
- `AWS_ACCESS_KEY_ID`: AWS access key for S3 publishing
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for S3 publishing
- **IAM Permissions Required**: `s3:PutObject`, `s3:PutObjectAcl`
- **S3 Bucket**: Managed by Meridian Labs, all objects set as world-readable

**Access Control:**
- Only **Repository Maintainers** can publish to S3
- All S3 publishing goes through PR review process
- Manual S3 promotion restricted to **Repository Maintainers**
- **Developers** cannot bypass S3 publishing process or upload unauthorized executables

**Permission Model:**
- Workflows run with `contents: read` and `actions: write` permissions
- Only repository collaborators can create PRs that trigger builds
- S3 publishing uses configured AWS credentials with minimal required permissions
- S3 objects are immediately world-readable upon upload

## Potential Enhancements

1. **Automatic Version Detection**: Detect when any changes have been made to `src/inspect_tool_support` and warn about (or make) the version bump
2. **Verifiable Executables**: The `tool_support_version.txt` file could be enhanced to include the fingerprint of the executable which could be validated prior to injection