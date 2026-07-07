# Vendored restic binary acquisition

`resolver.py` downloads and caches the restic binary on demand. The pinned
version is in `version.txt`, and `SHA256SUMS` holds the official upstream
checksums for that version. The downloaded archive is verified against the
vendored `SHA256SUMS` (no checksum is fetched at runtime), so the trust
anchor for the binary is this repo's code review and git history.

## Updating the pinned restic version

When bumping the restic version, refresh both files together. Run these
commands from the repository root:

1. Set the new version in `src/inspect_ai/util/_restic/version.txt`.
2. Download the official checksums:
   ```bash
   VERSION=$(cat src/inspect_ai/util/_restic/version.txt)
   curl -fsSL -o src/inspect_ai/util/_restic/SHA256SUMS \
     "https://github.com/restic/restic/releases/download/v${VERSION}/SHA256SUMS"
   ```
3. (Recommended) Verify authenticity before trusting the file:
   ```bash
   curl -fsSL -o /tmp/restic-SHA256SUMS.asc \
     "https://github.com/restic/restic/releases/download/v${VERSION}/SHA256SUMS.asc"
   # import restic's signing key (https://restic.net/gpg-key-alex.asc), then:
   gpg --verify /tmp/restic-SHA256SUMS.asc src/inspect_ai/util/_restic/SHA256SUMS
   ```
4. Confirm every supported platform verifies:
   ```bash
   inspect download restic
   ```
   (or run `pytest tests/util/test_restic_binary.py`).
5. Commit both files together:
   ```bash
   git add src/inspect_ai/util/_restic/version.txt src/inspect_ai/util/_restic/SHA256SUMS
   git commit -m "chore(restic): bump pinned restic to v${VERSION}"
   ```

If `version.txt` and `SHA256SUMS` disagree, `resolve_restic()` raises a
"regenerate it after a restic version bump" error and
`test_vendored_sums_cover_all_supported_platforms` fails in CI.
