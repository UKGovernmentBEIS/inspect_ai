---
name: land-ts-mono
description: Land a PR that requires a coordinated ts-mono submodule change. Use when the check-schema-and-types CI job fails, when a Python model change requires regenerating the OpenAPI spec / TypeScript types, or when any change touches the ts-mono submodule and needs to be landed.
---

# Landing coordinated ts-mono changes

A change in this repo sometimes requires a matching change in the ts-mono
submodule — most commonly because a Python model feeding the type-generation
pipeline changed, which regenerates a file *inside* the submodule. Landing
then requires a cross-repo dance: a ts-mono PR, a gitlink bump here, and a
specific merge order. This skill is the sanctioned exception to the AGENTS.md
rule against changing the submodule gitlink.

## Repo facts

<!-- Porting this skill to another repo (e.g. inspect_scout): swap this
     section's values; the procedure below is repo-agnostic. -->

- Submodule: `src/inspect_ai/_view/ts-mono` → https://github.com/meridianlabs-ai/ts-mono (branch `main`)
- Regeneration command: `python src/inspect_ai/_view/schema.py` (from repo root, venv activated; requires `pnpm install` done in the submodule)
- Generated artifacts:
  - `src/inspect_ai/_view/inspect-openapi.json` (this repo)
  - `packages/inspect-common/src/types/generated.ts` (inside the submodule)
- CI jobs (`.github/workflows/log_viewer.yml`):
  - `check-schema-and-types` — artifacts must match the Python source (docstring-only drift tolerated) and each other (exactly)
  - `submodule-on-main` — the gitlink SHA must be reachable from ts-mono `main`
  - `dist-validation` — the checked-in viewer bundle `src/inspect_ai/_view/dist` must match `pnpm --filter @meridianlabs/log-viewer build` run at the pinned submodule commit
- Submodule checks before pushing: `pnpm typecheck` and `pnpm test` from the ts-mono root (turbo), not per-package tsc
- Pipeline internals: `design/type-generation-pipeline.md`
- Sibling consumer: `inspect_scout` (also embeds ts-mono; its `apps/scout/src/types/generated.ts` duplicates the shared types). Its regen script `scripts/export_openapi_schema.py` regenerates its `openapi.json` from the installed inspect_ai and chains scout's `types:generate`.

## Recognize the situation

- `check-schema-and-types` is red on your PR, or
- you changed a Python model that flows into the pipeline (Content, ChatMessage, Event, Citation, ToolChoice, EvalLog, or anything they reference), or
- your change requires editing code in the submodule directly.

## Procedure

Your job is to reach the landed state from **whatever state you find** — you
may be starting fresh or resuming mid-flight (possibly in a new session).
First assess where things stand, then enter at the matching step:

| Observed state | Enter at |
|---|---|
| No ts-mono branch/PR yet | step 1 |
| Regeneration not done or stale | step 2 |
| ts-mono PR open; this repo's PR not yet gitlink-bumped/pushed | step 3 |
| Both PRs open; this repo's PR behind `main` or conflicted | update the branch (see pitfalls), then step 4 |
| Both PRs in phase-1 state (green / green-except-gate) | step 4 |
| ts-mono PR merged; gate still red | step 4.2 |

Resumption relies on the PR cross-links (step 3) to find the paired PR, and
any monitors/watches from a previous session are gone — re-arm them.

**Finding the paired ts-mono branch:** the submodule sits on a detached HEAD,
so the work branch isn't announced. The authoritative probes work whatever
the branch is named: `git -C <submodule> branch -a --contains HEAD` lists
every branch containing the gitlink commit, and the PR cross-links (step 3)
name the ts-mono PR's head branch. Branches are *usually* named the same as
this repo's branch (step 1's convention), which makes a good first guess —
but never a requirement. If nothing but `main`-ish refs contain HEAD, there's
no branch yet — that's the fresh-start case (step 1). Before committing in
the submodule, `git checkout <branch>` — a commit made on the detached HEAD
lands on no branch. A local branch may also lag its remote; trust
`origin/<branch>`, not the local ref.

### 1. Start submodule work from current main

In the submodule, `git fetch origin` and branch from `origin/main` — NOT the
local `main` ref, which lags arbitrarily far behind (submodules live on
detached HEADs; nothing routinely updates their local branches, and `fetch`
moves only `origin/main`). You must be current with ts-mono `origin/main`
before merging anyway, so get current before making changes. Name the new
branch after this repo's branch — a convention that makes the pairing obvious
at a glance (discovery doesn't depend on it; see "Finding the paired ts-mono
branch" above).

### 2. Make the change / regenerate

Sync this repo's branch with its `origin/main` (fetch first) before
regenerating — the schema that
lands is generated from the merged Python, so regenerating against a stale
branch bakes in a schema that drifts the moment you update the branch.

For type changes, run the regeneration command. It rewrites both generated
artifacts — one in this repo, one in the submodule. Docstring-only changes do
NOT require regeneration (CI tolerates `description` drift); only structural
changes do.

Run the submodule checks (see repo facts) before pushing. Expect fixture
fallout: adding a required field means test/e2e fixtures constructing
literals of that type need the new field.

### 2a. If `scout#typecheck` breaks: sync the sibling's duplicated types

The sibling consumer's app in ts-mono carries its own generated duplicates of
the shared types. TypeScript's structural typing keeps them interchangeable
until the shape of an *existing* shared type changes incompatibly. Heuristic:
would the change break a strict TS consumer or producer of the type?

- Noneable field added (optional) — breaks nobody; nothing to do (the common case)
- New type added — nothing to do
- Enum/literal union widened — breaks readers; sync needed
- Required (non-Noneable) field added — breaks producers; sync needed
- Rename/removal/type change — sync needed

When sync is needed, regenerate with the sibling's real tooling — do NOT
hand-edit its generated file:

1. Push the ts-mono branch first.
2. Create a worktree of the sibling repo at its main; init its ts-mono
   submodule and check out your ts-mono branch in it.
3. Ephemeral venv: `uv pip install -e <sibling worktree> -e <this repo checkout>`
   (so the sibling's regen sees your unmerged Python change).
4. Run the sibling's regen script (see repo facts) with that venv's python.
5. Discard the sibling repo's own regenerated `openapi.json` (it can't land
   there until it upgrades this package); commit only the ts-mono
   `generated.ts` change to your ts-mono branch and push.
6. Eyeball the diff: if the sibling is behind on regens, unrelated drift
   rides along — fine for compatibility, but flag it in the PR.

### 3. Two-phase landing — phase 1: branch-pinned, reviewable

1. Commit on the ts-mono branch, push it, open a ts-mono PR.
2. In this repo, commit the gitlink pointing at the ts-mono **branch head**
   (plus any regenerated files here) and push.
3. Cross-link the two PRs in each other's descriptions.

Result: this repo's PR is green **except** `submodule-on-main`. That one red
gate is the expected signal meaning "waiting on ts-mono merge" — do not try
to fix it yet. Note: `submodule-on-main` is a job inside the "Validate
Embedded Viewer" workflow, so that whole workflow shows as failing in
rollup views — read job-level status before concluding anything else broke.

**Why two-phase:** once ts-mono merges, its `main` depends on Python changes
that aren't merged yet, blocking anyone else who pulls ts-mono `main`. The
goal is to make that window as short as possible: get *everything else* green
on both PRs first, and only then merge ts-mono.

### 4. Endgame — phase 2: merge in order, quickly

Preconditions — ALL of these before anyone merges anything:

- ts-mono PR green and approved
- this repo's PR green except `submodule-on-main`
- this repo's PR **provisionally approved**: a reviewer has approved it with
  the sole remaining red being `submodule-on-main`

The provisional approval matters: it puts review latency *before* the
blocking window opens. Once ts-mono merges, the only remaining work should
be re-running one gate — not waiting on a reviewer.

Auto-merge: NEVER enable it on the ts-mono PR — its merge is the deliberate,
human-timed act that opens the blocking window, and it must not fire just
because checks pass. The Python PR is the opposite: once ts-mono is merged,
enable auto-merge on it yourself (`gh pr merge --auto`) so it lands the
moment the gate clears.

1. Tell the user both PRs are ready and the ts-mono PR is safe to merge —
   then immediately start watching it (background poll of its merged state,
   e.g. `gh pr view <n> --json state,mergeCommit`); a human merges it (agents
   cannot). React to the merge the moment it lands — the blocking window
   opens at merge, so don't wait for the user to come back and tell you.
2. Fetch in the submodule, then compare the gitlink SHA against ts-mono
   `origin/main`:
   - **SHA changed** (squash/rebase merge): bump the gitlink to the merged
     `main` SHA. The bump picks up **every** ts-mono `main` change since the
     last bump, not just yours — so rebuild the viewer bundle at the new
     commit (`pnpm install --frozen-lockfile && pnpm --filter
     @meridianlabs/log-viewer build` in the submodule) and commit the gitlink
     together with any resulting `dist/` changes (often none — type-only
     deltas build identically — but `dist-validation` fails if you skip the
     check and something did change). Push.
   - **SHA unchanged** (merge commit; branch head now reachable from main):
     just re-run the red `submodule-on-main` check.
3. Enable auto-merge on this repo's PR (`gh pr merge --auto`) and tell the
   user — the PR lands automatically the moment the gate clears. Watch until
   it actually merges; if auto-merge is unavailable (repo settings), watch CI
   and tell the user the instant it's mergeable instead.

## Pitfalls

- You need push access to the Python PR's head branch. GitHub's
  allow-maintainer-edits does NOT work for PRs from organization-owned
  forks — if the head lives in one you can't push to, recreate the PR from
  an in-repo branch (preserving the original description and crediting the
  author) and close the original with a link.
- Never leave the gitlink pointing at an unpushed or local-only ts-mono
  commit — push the ts-mono branch before committing the bump.
- After merging this repo's `origin/main` into your branch, check `git status` for
  the gitlink: a merge can silently revert your intentional bump (the inverse
  of the accidental-bump failure mode in AGENTS.md).
- If `main` bumps the gitlink while your PR is open, GitHub reports a
  submodule conflict and stops running CI on the PR. Fix: merge `origin/main`
  into your branch; at the gitlink conflict, verify main's new pointer is an
  ancestor of your ts-mono branch head
  (`git -C <submodule> merge-base --is-ancestor <main-ptr> <yours>`) — it
  will be if you branched from current ts-mono main — then keep yours
  (`git add <submodule>`), commit, push. If it is NOT an ancestor, first
  merge ts-mono `origin/main` into your ts-mono branch and push, then point
  the gitlink at that. A gitlink-bumping main commit usually also rebuilds the
  checked-in viewer `dist/` — taking main's dist is correct when your ts-mono
  delta is types/tests only (type erasure leaves the build output identical);
  otherwise rebuild dist from your ts-mono branch.
- Regenerate only from a venv with this repo installed; stale submodule
  `node_modules` breaks the TypeScript half — `pnpm install` in the submodule
  first.
- Don't trust the branch's committed schema just because its CI once passed —
  a later branch commit can change the Python models and leave
  `inspect-openapi.json` stale against the branch's *own* source. When
  resuming mid-flight, re-run the regeneration command and confirm it's a
  no-op before entering the endgame.
