# Design Document: Automated Tool Support Executable Publishing

## Overview

This document outlines the design for automatically building and publishing versioned tool support executables to GitHub Releases when the VERSION file is updated. The system ensures that prebuilt binaries are available immediately after merge completion while maintaining proper access controls.

## Problem Statement

Developers need to increment the tool support version when making changes to `src/inspect_tool_support/`, but they shouldn't have the permissions to directly publish releases. The system must:

- Build and publish artifacts automatically when VERSION changes
- Ensure artifacts are available before merge completion
- Maintain security by limiting who can trigger releases
- Handle build failures gracefully

## Stakeholder Roles

### Developer (Limited Permissions)

- Creates PRs with code changes to `src/inspect_tool_support/`
- Increments VERSION file when making breaking changes
- Cannot directly publish releases or access release secrets

### GitHub Actions (Automated System)

- Detects version changes in PRs
- Builds executables in secure environment
- Publishes to GitHub Releases using repository secrets
- Reports build status back to PR

### Repository Maintainer (Admin Permissions)

- Reviews and approves PRs
- Has access to configure GitHub Actions secrets
- Can manually trigger releases if needed
- Manages repository release permissions

## Publishing Flow

### Version Publishing Workflow

1. **Developer** makes changes to `src/inspect_tool_support/` and bumps VERSION file (e.g., 1 → 2)
2. **Developer** creates PR with code changes and version bump
3. **GitHub Actions** detects VERSION change in PR and automatically rebuilds on every push to the PR branch:
   - Builds executables for both architectures using `build_within_container.py --include-version` from the latest commit
   - Stores as workflow artifacts (auto-expire after 90 days), overwriting previous artifacts:
     - `inspect-tool-support-amd64-v2`
     - `inspect-tool-support-arm64-v2`
   - Comments on PR with build status and link to Actions artifacts
   - Sets PR status check (blocks merge if build fails)
   - **Only triggers for PRs - ensures all VERSION changes go through review process**
   - **Ensures promoted executables are built from the final commit state**
4. **Maintainer** reviews PR, code changes, and downloads artifacts from Actions tab for testing
5. **Maintainer** manually triggers "Promote to Release" action (specifies PR number or workflow run):
   - Downloads artifacts from the specified workflow run
   - Creates final release: `tool-support-v2`
   - Uploads artifacts with clean names:
     - `inspect-tool-support-amd64-v2`
     - `inspect-tool-support-arm64-v2`
   - Publishes release (immediately available via API)
6. **Maintainer** merges PR (executables already available)

*Note: Workflow artifacts automatically expire after 90 days, eliminating the need for manual cleanup.*

## Key Publishing Details

**Workflow Artifacts** (During PR Review):
- **Storage**: GitHub Actions artifacts (auto-expire after 90 days)
- **Names**:
  - `inspect-tool-support-amd64-v2`
  - `inspect-tool-support-arm64-v2`
- **Access**: Available in PR's Actions tab for download and testing
- **Isolation**: Each workflow run creates separate artifact set (no collisions)

**Final Release** (After Promotion):
- **Tag**: `tool-support-v{VERSION}` (e.g., `tool-support-v2`)
- **Assets**: Clean names that download code expects:
  - `inspect-tool-support-amd64-v2`
  - `inspect-tool-support-arm64-v2`

**Collision Prevention**:
- Each PR's workflow run creates isolated artifact set (no naming conflicts)
- **Only the maintainer-promoted PR creates the final release**
- **If multiple PRs target same version, first promotion wins, others must bump version**
- Abandoned PRs leave only workflow artifacts that auto-expire

**Publishing Process**:
1. **Workflow Artifacts**: Build outputs stored temporarily for validation/testing
2. **Maintainer-Controlled Promotion**: Before merge, maintainer creates final release from artifacts
3. **Safe Merge**: Clean release already published and available before PR merge
4. **API Availability**: Download logic finds versioned assets immediately (zero race condition)

**Risk Mitigation** (if maintainer promotes but doesn't merge):
- **Option 1:** Delete the published release (rollback)
- **Option 2:** Leave v2 published, next PR bumps to v3 (version skip)

## Technical Architecture

### GitHub Actions Workflows

#### Primary Workflow: `build-tool-support.yml`

**Triggers:**
- PR opened/updated with changes to `src/inspect_ai/tool/tool_support_version.txt` (PRs only)
- Every subsequent push to a PR branch with VERSION changes (ensures latest commit)
- Manual dispatch (for maintainers - emergency scenarios)

**Jobs:**
1. **Version Detection**
   - Extract old/new version from VERSION file
   - Skip if version unchanged
   - Validate version format (simple integer)
2. **Multi-Architecture Build**
   - Matrix build: `[amd64, arm64]`
   - Use existing `build_within_container.py --include-version` script to create versioned executables
   - Upload executables as workflow artifacts
3. **PR Integration**
   - Comment on PR with build status
   - Set status check for merge blocking
   - Link to Actions artifacts for download/testing

#### Secondary Workflow: `promote-tool-support.yml`

**Triggers:**
- Manual dispatch (maintainers only)
- **Inputs**: PR number or workflow run ID (to identify which artifacts to promote)

**Jobs:**
1. **Release Promotion**
   - Download artifacts from specified workflow run
   - Create clean release with standard naming: `tool-support-v{VERSION}`
   - Upload artifacts with clean names
   - Publish release immediately (available via API)


### Directory Structure

```
.github/
  workflows/
    build-tool-support.yml     # Main build workflow
    promote-tool-support.yml   # Manual promotion workflow
  scripts/
    build-and-publish.py       # Build orchestration script
    release-manager.py         # GitHub release API wrapper
```

### Security Considerations

**Repository Secrets Required:**
- `GITHUB_TOKEN`: Built-in token for creating releases (auto-provided)
- No additional secrets needed for public repositories

**Permission Model:**
- Workflows run with `contents: write` and `actions: write` permissions
- Only repository collaborators can create PRs that trigger builds
- Release publishing uses repository's built-in GITHUB_TOKEN
- Draft releases prevent accidental publication

**Access Control:**
- Developers cannot directly publish releases
- All releases go through PR review process
- Manual triggers restricted to repository maintainers
- Build logs are public and auditable

### Error Handling & Recovery

**Build Failures:**
- Clear error messages in PR comments
- Links to build logs for debugging
- Automatic retry on push to PR branch
- Manual retrigger option for maintainers

**Partial Failures:**
- If one architecture fails, mark entire build as failed
- Don't create partial releases with missing executables
- Provide architecture-specific error details

**Version Conflicts:**
- Detect if release version already exists
- Skip build if identical artifacts already published
- Error if VERSION decreases (rollback protection)

## Implementation Timeline

### Phase 1: Core Workflow (Week 1)
- [ ] Create `build-tool-support.yml` workflow
- [ ] Implement version change detection
- [ ] Add multi-architecture build matrix
- [ ] Test with draft releases

### Phase 2: Manual Promotion (Week 2)
- [ ] Create `promote-tool-support.yml` workflow
- [ ] Add PR status checks and comments
- [ ] Implement build failure handling
- [ ] End-to-end testing

### Phase 3: Production Deployment (Week 3)
- [ ] Deploy to main repository
- [ ] Document developer workflow
- [ ] Monitor initial version bumps
- [ ] Establish draft release retention policy

## Success Criteria

1. **Automated Publishing**: VERSION bumps trigger automatic executable builds and GitHub Release creation
2. **Merge Blocking**: PRs cannot merge until executable builds succeed
3. **Immediate Availability**: Git installation users can download executables immediately after PR merge
4. **Security**: Developers cannot bypass release process or publish unauthorized releases
5. **Reliability**: Build failures are clearly communicated with actionable error messages
6. **Auditability**: All release actions are logged and traceable through GitHub Actions

## Open Questions

1. **Release Naming**: Should releases be named `v1`, `tool-support-v1`, or include date stamps?
2. **Retention Policy**: How long should old executable versions be retained in releases?
3. **Notification**: Should successful releases trigger Slack/Discord notifications?
4. **Testing Strategy**: Should we include integration tests that verify downloaded executables work correctly?

---

**Next Steps**: After review approval, proceed with Phase 1 implementation starting with the core GitHub Actions workflow.