# Plan: Migrate inspect_ai www/ into ts-mono as apps/inspect

## Context

inspect_ai's TypeScript frontend (`src/inspect_ai/_view/www/`) is a standalone Yarn+Vite project. inspect_scout already migrated its frontend into the shared `ts-mono` monorepo (pnpm+Turbo). This effort brings inspect_ai in line with that pattern, as a first step toward shared code. This is a pure lift-and-shift: no dependencies on `@tsmono/react` or `@tsmono/util`.

**Source commit**: `6b8eea6d1369b6bd59b` (inspect_ai HEAD at time of copy). If more code lands in www/ on main before this merges, diff from this commit to HEAD and forward-port changes.

**This plan lives at `design/ts-mono-migration.md`** in the inspect_ai repo and should be kept up to date as work progresses (mark steps done, note blockers, update commit refs).

---

## Phase 0: Prep

- [x] Commit this plan to `design/ts-mono-migration.md` in the inspect_ai repo
- [x] Sync submodule to latest main (synced to `22c65f1`)

## Phase 1: Add apps/inspect to ts-mono

Work happens inside the submodule at `src/inspect_ai/_view/ts-mono/`.

**1a. Copy source files from www/ into apps/inspect/**
- Copy: `src/`, `index.html`, `favicon.svg`, `log-schema.json`
- Copy configs: `vite.config.js`, `tsconfig.json`, `jest.config.mjs`, `babel.config.js`, `jsconfig.json`, `eslint.config.mjs`, `postcss.config.cjs`, `.prettierrc.js`, `.prettierignore`
- Copy: `scripts/get-version.js`
- Do NOT copy: `node_modules/`, `dist/`, `lib/`, `yarn.lock`

**1b. Create new package.json**
- Name: `inspect` (no `@tsmono/` prefix for apps, matching scout convention)
- Add `"publishConfig": { "name": "@meridianlabs/log-viewer" }` to preserve npm identity
- Convert all `yarn` scripts to pnpm equivalents
- Convert `resolutions` to `pnpm.overrides`
- Keep all deps/devDeps as-is
- Add `"typecheck"` script alias (turbo convention)

**1c. Convert vite.config.js to vite.config.ts**
- Model after `apps/scout/vite.config.ts`
- Add `copyToPythonRepo()` plugin for app build mode
- Create `scripts/python-repo.js` modeled on scout's:
  - Traverse up to find `pyproject.toml` with `name = "inspect_ai"`
  - Target: `src/inspect_ai/_view/dist`
- Keep hashless output filenames (`assets/index.js`, `assets/index.css`)
- Keep library build mode (`--mode library`) outputting to `lib/`

**1d. Add scripts/generate-types.js** (follow scout pattern)
- Use `json-schema-to-typescript` (existing json2ts tool, NOT openapi-typescript)
- Read `log-schema.json` from apps/inspect/ (already in the workspace)
- Write `src/@types/log.d.ts`
- Add `"types:generate"` script to package.json

**1e. Keep own tooling configs**
- Do NOT extend `@tsmono/tsconfig`, `@tsmono/eslint-config`, `@tsmono/prettier-config`
- Keep Jest (don't convert to Vitest)

**1f. Verify**
- [x] `pnpm install` from monorepo root
- [x] `pnpm --filter inspect build` produces dist/ + copies to `_view/dist/`
- [x] `pnpm --filter inspect build:lib` produces lib/
- [x] `pnpm --filter inspect test` passes (182 tests)
- [x] `pnpm --filter inspect tsc` passes
- [ ] `pnpm --filter inspect dev` starts dev server on :7575

**Notes from Phase 1:**
- Added `@codemirror/view` as explicit dep (pnpm strict resolution vs yarn hoisting)
- Added `@jest/globals` and `@types/node` as devDeps (same reason)
- Added `picocolors` as devDep (for copyToPythonRepo plugin)
- `pnpm.overrides` in package.json warns - should move to root monorepo config later

## Phase 2: Update inspect_ai to use monorepo

**2a. Build and commit dist at new location**
- `cd src/inspect_ai/_view/ts-mono && pnpm install && pnpm --filter inspect build`
- Commit `src/inspect_ai/_view/dist/` (created by copyToPythonRepo plugin)

**2b. Update Python dist path references (3 files)**
- `src/inspect_ai/_view/server.py:481` -- `"www" / "dist"` -> `"dist"`
- `src/inspect_ai/_view/fastapi_server.py:490` -- `"www" / "dist"` -> `"dist"`
- `src/inspect_ai/log/_bundle.py:20` -- `"_view", "www", "dist"` -> `"_view", "dist"`

**2c. Update schema.py**
- `src/inspect_ai/_view/schema.py:10` -- `WWW_DIR` -> point to `ts-mono/apps/inspect`
- Lines 57-74: `yarn` -> `pnpm` subprocess calls
- `cwd` for json2ts and prettier -> apps/inspect dir within submodule

**2d. Update .gitignore**
- Line 14: `!src/inspect_ai/_view/www/dist` -> `!src/inspect_ai/_view/dist`

**2e. Delete www/**
- `git rm -r src/inspect_ai/_view/www/`

**2f. Update pyproject.toml package-data (if needed)**
- Verify `src/inspect_ai/_view/dist/` is included in the Python sdist/wheel
- Currently `[tool.setuptools.package-data]` only lists `binaries/*` and sandbox tools
- dist/ may need explicit inclusion: `"_view/dist/**"`

## Phase 3: Update CI workflows ✓

**3a. Rewrite .github/workflows/log_viewer.yml** ✓
- Added pnpm/action-setup, submodules: recursive, pnpm caching
- Added submodule-on-main check and dist-validation jobs
- All jobs now use pnpm --filter inspect

**3b. Update .github/workflows/build.yml** ✓
- Removed favicon.svg deletion hack

**3c. Update .github/workflows/npm-publish.yml** ✓
- working-directory → apps/inspect for npm publish, ts-mono root for pnpm install/build
- yarn → pnpm, added submodule checkout and pnpm setup

## Phase 4: Update ancillary files ✓

**4a. Update .vscode/settings.json** ✓
**4b. Update CLAUDE.md** ✓ (root + created new apps/inspect/CLAUDE.md)

## Phase 5: Update inspect_vscode

- `src/core/package/props.ts`: `_view/www/dist` -> `_view/dist`
- One-line change (plus any backward-compat fallback if needed)

---

## Unresolved Questions

1. **pyproject.toml package-data**: does `_view/dist/` get auto-included in the wheel via `find` packages, or need explicit `package-data` entry? Need to test.
2. **npm-publish.yml**: `npm publish` needs to run from the dir with the publishable package.json. With monorepo, may need `pnpm --filter inspect publish` or `cd apps/inspect && npm publish`. Need to verify the publishConfig approach works.
3. **generate-types.js**: inspect_ai currently has schema.py (Python) calling json2ts. Scout has generate-types.js (Node). Leaning toward keeping schema.py but having it call `pnpm --filter inspect types:generate`.

## Verification

- [ ] `pnpm build` and `pnpm --filter inspect test` pass in ts-mono
- [ ] `inspect view` serves from new `_view/dist/` path
- [ ] `python src/inspect_ai/_view/schema.py` regenerates types inside submodule
- [ ] All log_viewer.yml CI jobs pass
- [ ] VS Code extension discovers dist at new `_view/dist/` path
