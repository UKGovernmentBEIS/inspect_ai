#!/usr/bin/env bash
#
# Verify the build-provenance attestations of the four sandbox-tools artifacts.
#
# Usage: verify-sandbox-tools-attestations.sh <run_id> <version> <dir>
#
# For each of the four variant artifacts (amd64/arm64 x glibc/musl) in <dir>,
# checks that its attestation was produced by sandbox-tools-build.yml on main
# and signed by build run <run_id> on its first attempt. The attestation names
# the run that signed it; that run's title names the commit it built, so this
# ties the bytes to that commit. Exits non-zero on the first failure, naming
# the artifact, so no caller uploads an artifact that failed to verify.
#
# Shared by scripts/release-sandbox-tools.sh (the wizard) and
# .github/workflows/sandbox-tools-publish.yml so the security-critical check has
# one source. Needs `gh` authenticated (the workflow passes GH_TOKEN).

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <run_id> <version> <dir>" >&2
  exit 2
fi

RUN_ID="$1"
VERSION="$2"
DIR="$3"
UPSTREAM_REPO="UKGovernmentBEIS/inspect_ai"
BUILD_WORKFLOW="sandbox-tools-build.yml"
VARIANTS="amd64 arm64 amd64-musl arm64-musl"

for f in $VARIANTS; do
  name="inspect-sandbox-tools-$f-v$VERSION"
  path="$DIR/$name"
  if [[ ! -f "$path" ]]; then
    echo "Run $RUN_ID has no $name, aborting." >&2
    exit 1
  fi
  invocation=$(gh attestation verify "$path" --repo "$UPSTREAM_REPO" \
    --signer-workflow "$UPSTREAM_REPO/.github/workflows/$BUILD_WORKFLOW" \
    --source-ref refs/heads/main --format json \
    --jq '.[0].verificationResult.statement.predicate.runDetails.metadata.invocationId') || {
    echo "Attestation check failed for $name. Do not upload it." >&2
    exit 1
  }
  if [[ "$invocation" != */actions/runs/"$RUN_ID"/attempts/1 ]]; then
    echo "$name was attested by $invocation, not run $RUN_ID attempt 1. Do not upload it." >&2
    exit 1
  fi
  echo "✓ $name attested by run $RUN_ID"
done
