# ts-mono Viewer — Manual Validation Plan

Regression validation of the ts-mono viewer (this branch) against the origin/main viewer. Every check runs the same action in both viewers against the same fixture logs; a check passes when new behavior matches old. Deviations are inventoried in the findings table (no inline fixing during the pass).

## What actually changed (risk weighting)

origin/main already ships ts-mono; the comparison is between two submodule pins (`76a71e0` → branch HEAD, 218 commits, 273 files). The backend transports (view-server / static-http / vscode clients, `resolveApi`) are **unchanged**. Changed and therefore highest-risk:

- **Dir-mode listing**: replicator `database/service.ts` rework; log-list filter/sort backed by new server query models (`schema.py` — the only python diff)
- **Unreadable-log isolation**: new per-file summary fallback when a batched `/log-headers` request fails (`get_log_summaries_settled`)
- **Samples grid**: filtrex FILTER-string ↔ column-filter bridge, FilterSpec operators, Apply-only commit
- **Live eval polling**: several fixes (poll parking, activity bar, cold-dir preview drain)
- **DataGrid rendering**: rotated headers, multiline cells, row selection persistence, keyboard focus

Static/VS Code sections stay as smoke passes (dist rebuild affects all hosts) but the deep effort concentrates on the above, in env 1.

## Scope & pruning

Backends: view-server (local FS + S3), static (bundle + embed), VS Code. Source modes: dir listing + single-file. Formats: `.eval` + `.json`. Live evals via `mockllm`.

Documented N/A (impossible by design — not tested, except one negative check):

| Combo | Why N/A |
|---|---|
| static × edit / delete / streaming / scout search / download_log | static-http backend has no such methods |
| VS Code × download file/log | disabled by capabilities |
| VS Code × direct S3 fetch | CSP forces proxy path |
| `.json` × etag/If-Match | JSON logs carry no etag; last-writer-wins |
| `file://` serving of bundle/embed | CORS blocks range fetches; unsupported by design |
| `?log_dir=` + `?log_file=` together | hard throw in `urlLogSource.ts` — negative check S9 confirms |

## Setup

### Checkouts

Two working copies, each with its own venv:

- **old**: worktree of `origin/main` (e.g. `git worktree add ../main-viewer origin/main`), `uv pip install -e .`
- **new**: this checkout (ts-mono branch)

Servers always on distinct ports: old = 7575, new = 7676.

### Fixture log dir

Generated once by script (checked in next to this doc as `ts-mono-viewer-validation-fixtures.py`, run from the **new** checkout; both viewers read the same dir):

| Fixture | Purpose |
|---|---|
| small `.eval` (5 samples, tool calls, image attachment) | range-read + lazy sample path, transcript rendering |
| same task as `.json` (`inspect eval … --log-format json`) | whole-file path, no-etag edit |
| listing-breadth set: ~15 logs, varied task names / statuses / scores / dates | log-list filter + sort against the new server query models |
| `.eval` with 20+ samples, varied scores + sample metadata columns | samples-grid column filters / filtrex bridge |
| corrupt `.eval` (truncated copy) alongside good logs | unreadable-log isolation: listing still shows the rest |
| errored eval (task raises) + cancelled eval (Ctrl-C) | status rendering in listing + log view |
| logs in nested subdir `sub/inner/` | listing recursion / `--recursive` |
| log with pre-set tags + metadata | edit round-trip baseline |

Live fixture (started on demand, not pre-generated): `mockllm` eval with per-sample `time.sleep`, enough samples to stay running for several minutes.

### S3 copy

Bucket: `s3://meridian-scratch` (default profile, SSO — run `aws sso login` if creds expired). `s3fs` required in both venvs (`uv pip install s3fs`; not an inspect dependency).

Two gotchas discovered during execution:

- **Region**: bucket is `us-east-2` and the profile sets no region. Without `AWS_DEFAULT_REGION=us-east-2`, s3fs hits us-east-1, gets a 307 redirect, and aiohttp drops the auth header on redirect → S3 returns "No AWSAccessKey was presented". Always export the region for the servers.
- **Repo `.env`**: `inspect view` calls `init_dotenv()`; the repo root's `.env` contains AWS creds that override SSO and are stale → `PermissionError: Forbidden`. Start S3-backed servers from a cwd without a `.env`.

```bash
aws s3 sync fixtures/logs/ s3://meridian-scratch/viewer-validation/read/
aws s3 sync fixtures/logs/ s3://meridian-scratch/viewer-validation/scratch/   # edit/etag checks; re-sync to reset
```

For **D8** (presigned direct URLs) only:

- `inspect view` never enables direct URLs; launch programmatically per checkout with `view_server(..., generate_direct_urls=True)` (small launcher script, written at execution time).
- Bucket CORS must allow browser GETs of presigned URLs from the viewer origins (bucket currently has no CORS config):

```bash
aws s3api put-bucket-cors --bucket meridian-scratch --cors-configuration '{"CORSRules":[{"AllowedMethods":["GET","HEAD"],"AllowedOrigins":["http://127.0.0.1:7575","http://127.0.0.1:7676","http://localhost:7575","http://localhost:7676"],"AllowedHeaders":["*"],"MaxAgeSeconds":3000}]}'
```

### Static serving

Plain `http.server` does **not** support Range and will break `.eval` reads. Use:

```bash
uv pip install rangehttpserver
python -m RangeHTTPServer <port>   # from the bundle/embed output dir
```

## Check library

Each check = perform in old, perform in new, compare. IDs referenced from environment sections.

### Smoke tier

| ID | Check |
|---|---|
| S1 | Viewer loads, no console errors/warnings diff vs old |
| S2 | Dir listing complete: all fixtures shown incl. nested subdirs, statuses (success/error/cancelled) correct |
| S3 | Listing filter + sort controls work |
| S4 | Open `.eval` log: samples/info/json tabs all render |
| S5 | Open `.json` log: same tabs render |
| S6 | Sample detail: transcript, tool calls, image attachment render |
| S7 | Sample navigation: next/prev; deep-link URL to a sample reloads to same sample |
| S8 | Corrupt `.eval` in dir: listing shows remaining logs (not whole-listing failure); opening the corrupt log errors gracefully |
| S9 | Negative: URL with both `?log_dir=` and `?log_file=` errors in both viewers |

### Deep tier

| ID | Check |
|---|---|
| D1 | Edit tags/metadata, persists across reload (`.eval` and `.json`) |
| D2 | Etag conflict: edit same S3 `.eval` from two tabs → second gets 412/conflict UI |
| D3 | Download log works; downloaded file opens |
| D4 | Download file attachment works |
| D5 | Live eval: samples stream in while running (or refresh button appears + works where streaming unsupported); completes cleanly |
| D6 | Scout search (only if `inspect_scout` installed server-side) |
| D7 | Auth: non-loopback bind requires `INSPECT_VIEW_AUTHORIZATION_TOKEN`; `--unsafe-allow-unauthenticated` bypasses |
| D8 | S3 direct-URL: network tab shows presigned S3 fetches for sample data; kill creds/presign → falls back to proxy |
| D9 | Delete a log file on disk while listed → viewer surfaces error gracefully on open |
| D10 | Samples-grid filters: column-filter UI edits round-trip with the FILTER string; operators per column type; Apply-only commit; empty-filter no-op |
| D11 | Log-list filter + sort exercised across columns (status, task, score, date); results match old viewer exactly |
| D12 | DataGrid regressions: rotated headers separator, multiline cell alignment, row selection persists across navigation, keyboard focus on mount |

## Environments

### 1. Server / local FS

```bash
# old:  inspect view --log-dir fixtures/logs --port 7575
# new:  inspect view --log-dir fixtures/logs --port 7676
```

Checks: S1–S9 (full), D1 (both formats; note `.json` has no conflict protection), D3, D4, D5 (start live fixture, view in both), D6, D7 (restart with `--host 0.0.0.0` variants), D9, **D10–D12 (the changed-code focus — spend the most time here)**.

Single-file mode: repeat S4/S6/S7 via `?log_file=<path>` URL — confirms direct loader path.

Driver: playwright against both ports.

### 2. Server / S3

Same commands with `--log-dir s3://meridian-scratch/viewer-validation/read/` (scratch prefix for D1/D2). D8 uses the programmatic `generate_direct_urls=True` launcher (see Setup → S3 copy).

Checks: S1, S2, S4–S6 (spot check, not full repeat), D1, **D2**, **D8**.

Driver: playwright.

### 3. Static bundle

```bash
# from each checkout:
inspect view bundle --log-dir fixtures/logs --output-dir /tmp/bundle-{old,new}
# serve each: python -m RangeHTTPServer {8575,8676}
```

Checks: S1–S8 (S9 n/a — bundle pins its own context). Static-specific:

- Network tab shows HTTP **Range** requests when opening `.eval` logs
- `listing.json` present in output; temporarily rename it → listing shows the "deploy a manifest" error, restore
- No edit/streaming/search affordances visible anywhere

Driver: playwright.

### 4. Static embed

```bash
cp -r fixtures/logs /tmp/embed-{old,new} && inspect view embed --log-dir /tmp/embed-{old,new}
# serve with RangeHTTPServer
```

Checks: S1, S4–S6 only (shares the static-http code path with bundle; smoke confirms the embed packaging itself).

### 5. VS Code

One installed extension; two Python interpreters (old venv / new venv). Switch interpreter between passes — the extension serves whichever viewer dist the active inspect_ai ships.

Checks per pass:

- S1–S7 via the Inspect sidebar (dir mode over vscode RPC)
- Open a specific log file from the explorer (single-file / embedded-state mode)
- D1 (edit tags), D5 (live eval in webview)
- Confirm download buttons absent; with S3 log dir, confirm network shows proxy-only (no direct S3)

**Automation attempt** (timebox ~1h, then fall back): launch `code --remote-debugging-port=9222`, attach chrome-devtools MCP, locate the webview iframe target, drive checks there. Fallback: guided-manual script — same check list, executed by hand.

**Automation result (worked)** — recipe for reruns:

1. `code --remote-debugging-port=9229 <workspace>` (VS Code must not already be running). Workspace: `~/code/viewer-validation` (fixture logs at `./logs`), `.vscode/settings.json` sets `python.defaultInterpreterPath` to the pass's venv.
2. Drive via playwright `chromium.connectOverCDP("http://127.0.0.1:9229")` (resolve playwright from ts-mono's pnpm store). The workbench page is scriptable: command palette, quick open, activity bar.
3. **Gotchas hit**: fresh workspace opens in Restricted Mode — trust it first (palette "Manage Workspace Trust" → Trust) or the extension stays inactive and `.eval` opens as binary; the `.eval` tab may stick to the text editor — use "View: Reopen Editor With… → Inspect Log Viewer"; interpreter switching needs "Python: Select Interpreter → Enter interpreter path" + "Developer: Reload Window" (settings.json alone doesn't retarget an explicit selection); the webview's app DOM is NOT reachable via frame evaluate (service-worker iframe) — drive by coordinate clicks on the workbench page + screenshots.

**Results**: new + old both render log webview (samples grid, tags, tabs), sample detail w/ image + transcript, sidebar dir-mode LOGS tree, no download buttons (per capabilities), webview state persists across reload. Old→new state upgrade restores cleanly; new→old downgrade crashes (finding 11). Status-bar version confirms which inspect_ai serves each pass (0.3.239.dev = new checkout, 0.3.235.dev = origin/main worktree).

## Findings

| # | Env | Check | Old behavior | New behavior | Severity |
|---|---|---|---|---|---|
| 1 | server/local | D5 live eval | SAMPLES grid lists completed + running samples ("2 / 3 Samples", badge "RUNNING (2 SAMPLES)") | Only a single live-sample detail view (tab "SAMPLE" singular, badge "RUNNING (1 SAMPLES)"); completed samples not listed/reachable during the run | **FIXED** (two stacked bugs, see 12+13): the count==1→inline rule is old unchanged design; the count was wrong because flushed samples never reached the settled side of the merge. Fixes: `pendingSamples.ts` per-tick `get_log_info` size/etag probe with fresh re-read on change (replaces the transition-triggered one-shot, which raced the flush and never retried), plus finding 12's stale-memo fix. Red-green tests at both layers; verified live end-to-end. "1 SAMPLES" grammar still open |
| 2 | server/local | S8 corrupt log in dir | Batched `/log-headers` 500 poisons ALL listing details (every row "-"), endless retry loop | Per-file fallback isolates the corrupt file; all other rows fully populated; bounded retries | improvement (intended fix) |
| 3 | server/local | S9 `?log_dir`+`?log_file` | No error — silently switches to static-http mode, dies on `file://` fetches (blank page, cryptic console) | Explicit thrown error: "mutually exclusive… pass only one" (blank page, clear console) | improvement; neither shows a user-visible error UI |
| 4 | server/local | S2 listing columns | Column order: …, Duration, Model | Model moved next to Task | cosmetic — confirm intentional |
| 5 | server/local | D11 sort nulls | Sort by Score asc: null scores (error/cancelled) FIRST | Null scores LAST | low — confirm intentional |
| 6 | server/local | S1 console noise | 404 on `/api/flow` | 404 on `/api/flow` AND `/api/eval-set` on every listing load | **FIXED** — not an extra fetch (old also fetches eval-set on every listing load, silently 200-null). New `useEvalSet` passed the FULL resolved logDir (`file:///...`) into `get_eval_set`'s `dir` param, whose contract is a SUBDIR relative to the server's log_dir (old passed the route subpath, i.e. nothing at root). Server concatenated default_dir + "/" + that URI → nonexistent path → `fs.info` FileNotFoundError → 404. Consequence beyond noise: `get_eval_set` ALWAYS returned undefined in server mode → eval-set detection (retried-logs grouping / Show Retried Logs) never activated. Fix: `useEvalSet(dir)` now takes the route subdir (keyed on it, matching old per-subdir refetch and the `useFlowQuery` pattern); LogsPanel passes `logPath`, SamplesPanel `samplesPath`. Hook tests + view-server wire tests; verified live (`/api/eval-set` no params → 200) |
| 7 | both | build process | — | Checked-in `dist/` was stale vs submodule HEAD (missed the entire filtrex-bridge feature); rebuilt during validation | **process — rebuild + recommit dist before merge; CI gate should catch this** |
| 8 | server/local | D5 run-end transition | Page watching a running eval stops polling `/pending-samples` when the run ends (probe → park) | Poll never stops after run ends: ~5/s `/pending-samples` 404 loop indefinitely (198 console errors in ~40s) until reload. Fresh open of a finished log is fine on both (probe + stop) | **FIXED** by the finding-1 fixes — same missing convergence: the run-end header write changes the file signature → fresh re-read lands the terminal status → the poll's enablement gate parks. Verified live: poll ticked 2s steady all run, went to zero at run end, stayed zero |
| 9 | server/local | D9 deleted log opened | Silently renders stale samples from client cache — no indication the file is gone | Error page "An error occurred while loading this task. HTTP 404" — correct, but displays a raw JS stack trace and keeps the previous log's tab title | low — new is better; polish: hide stack, fix title |
| 10 | static | missing listing.json | Renders app shell + "Error 404: <raw html of 404 page>" | Fails earlier: "Failed to load application configuration: 404: <raw html>" | low — same net effect; both dump raw 404 HTML |
| 11 | vscode | webview state downgrade | — | Webview state persisted by the NEW viewer crashes the OLD viewer on restore ("Cannot read properties of undefined (reading 'loading')", error page w/ stack). Upgrade direction (old state → new viewer) restores fine | low — downgrade-only; consider versioning the persist key in new so stale readers ignore it |
| 12 | server/local | D5 live eval (found fixing 1) | old invalidates `loadedEvalFile` only on edit | `client-api.ts` memoized `RemoteLogFile` (central-directory snapshot at open) is re-served for every `cached≠false` read of a RUNNING log and is never replaced by fresh reads — stale reads of a live log; their ingests clobbered the probe fix's fresh writes (last-writer-wins) | **FIXED**: `get_log_details` drops the memo when the read's status is "started" (running logs never serve from snapshot; completed logs memoize as before) |
| 13 | server/local | D5 live eval (found fixing 1) | — | fetchEngine ingest is last-writer-wins with no ordering: two overlapping details reads (one opened pre-flush, one post-) can commit out of order, landing stale data last. With 12 fixed the window shrinks to one read latency; a lost race self-heals on the next file change (worst case run end) | low — residual race; real fix is generation-stamped ingest; not fixed |
| 14 | server/local | D5 live eval (found fixing 1) | — | fetchEngine `flushDetailWrites`/`flushPreviewWrites`: a throttled flush arriving while one is in flight returns without rescheduling — background (unwaitered) results can sit in `_pendingDetailWrites` indefinitely (observed: fresh summaries read but never written) | medium — needs trailing-coalesce like `serializedSyncListing`; not fixed |

Verified matching (env 1, server/local): S2 listing data (18 rows identical), S3/D11 sort-by-score values, S4 log tabs + samples grid, S5 `.json` (incl. filter persistence across logs; per-sample tokens blank on json in both), S6 sample detail w/ image + transcript, S7 next/prev + deep-link, D1 tag edits round-trip old↔new, D10 new column-filter counts == old filtrex counts (12/24) with bidirectional FILTER-string sync, single-file mode (`?log_file=`+`inspect_server=true`), D3 download (both files valid), D5 streaming while running (both poll + render live), D7 0.0.0.0-without-token refusal (identical message), D12 cross-log Samples view (80 samples both after fresh load).

Env-1 leftovers: D6 scout search (installed in both venvs; UI entry point not yet located — find `list_searches` consumer), D4 attachment download (no per-attachment download button found in sample detail this pass).

Verified matching (env 3+4, static bundle + embed): listing (19 items incl. tags/scores from manifest), `.eval` opens via HTTP range reads against RangeHTTPServer (old ~114 reqs vs new ~14 — new batches better, same result), sample detail + image, edit/download affordances correctly absent on both, missing `listing.json` errors on both (old renders app shell + error text; new fails earlier with "Failed to load application configuration"; both dump raw 404 HTML — logged as finding 10).

Verified matching (env 2, server/S3): listing (19 items), sample detail + image via `/api/log-bytes` proxy, D1 tag edit persists to S3, **D2 etag conflict: both viewers return HTTP 412 with "This log was modified by someone else. Please reload and try again."**

D8 verified matching: with bucket CORS applied (ports 7579/7680) and `view_server(generate_direct_urls=True)` launchers, both viewers fetch pending-sample segments directly from presigned `meridian-scratch.s3.amazonaws.com` URLs after one `/pending-sample-data-urls` call (new: 8 direct + some proxied before direct pinned; old: 84 direct).

## Execution order

1. Build fixtures + S3 sync
2. Env 1 (server/local) — largest coverage, shakes out fixture problems early
3. Env 3 (bundle), Env 4 (embed)
4. Env 2 (server/S3)
5. Env 5 (VS Code)
6. Triage findings table

## Unresolved questions

- D6 scout: is `inspect_scout` expected installed in both venvs? Skip if not comparable.
- VS Code webview reachable via remote debugging port? Unknown until attempted.
- Old server lacks the new query models (`schema.py`) — if the new viewer's listing filter/sort sends new query shapes, the old side may implement filter/sort differently (client-side?). D11 compares outcomes, not wire traffic; note mechanism diffs in findings rather than failing the check.
