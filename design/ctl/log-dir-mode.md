# Read-only log mode for `inspect ctl` (`--log-dir`)

> **Status: proposed, 2026-09-23; open questions resolved by Ransom the
> same day (see "Open questions").** Companion to the eval sharding design
> ([`../eval-sharding.md`](../eval-sharding.md)), which defines the `<name>.shards/<k>/` layout this mode
> reads and leaves "targeted live-view improvements ... (`inspect ctl`, the
> running-sample viewer)" to its Step 3. Builds on
> [`control-channel.md`](control-channel.md) (the ctl surface, the agent
> output contract), [`endpoint-cost-audit.md`](endpoint-cost-audit.md) (the
> cost vocabulary used in "Cost and scale") and [`security.md`](security.md)
> (the content threat model). Issue:
> [meridianlabs-ai/inspect_ai#509](https://github.com/meridianlabs-ai/inspect_ai/issues/509).
> Author: agent (Claude), reviewed by Codex; see the PR. Verified against
> `06537c328c`.

## Why

`inspect ctl` observes a running eval through the eval process's control
server, an AF_UNIX socket at `<inspect_data_dir>/control/<pid>.sock` found
through per-process discovery files (`discovery_dir`,
`src/inspect_ai/_control/discovery.py:25`; transport in
`src/inspect_ai/_cli/ctl/_http.py`). By construction that socket is
reachable only from the same machine and user (`security.md`, "Access
model"). A sharded run puts each shard on its own machine (down to one
sample per machine, the sharding design's target case of about 300 shards
on S3). The operator, or the agent driving the run, sits on another host,
often behind networking rules that allow it to read the shared log bucket
and nothing else. Today it has no ctl view of the run at all: every ctl
command except `process anomalies` needs a discovered, reachable process, and
`process anomalies` reads trace files that live on the worker host.

What the operator can reach is the log directory. Every shard writes its
`.eval` file there, flushed as samples complete, and with `--log-shared`
each shard also syncs its running samples to a `.buffer` directory beside
its log. That is enough to answer the questions a monitoring agent asks
most often (which shards are running, finished or failed; how many samples
are done; which samples errored and why; what a sample did), a little
behind the live process, with no network path to the workers.

This design adds a read-only ctl mode that answers those questions from the
log directory. It is the MVP for sharded-run status under networking
restrictions; it also works for any unsharded log directory.

## Goals and non-goals

Goals:

- A CLI flag that points `inspect ctl` at a log directory (local, `s3://`,
  or any fsspec URL Inspect reads), in which the read commands that can be
  served from logs and shared sample buffers work, with the same `--json`
  envelopes as live mode plus a small set of additive fields.
- One logical task row per sharded run, aggregating the shards under
  `<name>.shards/*/` and the merged log `<name>.eval` when it exists, and
  one row per task for an unsharded directory.
- Every command that mutates, or that needs state held only in the live
  process, has no `--log-dir` option, so passing it is click's ordinary
  usage error and a new command fails closed until it is implemented and
  given the option (decision: Ransom, 2026-09-24).
- Stated staleness per field, and a cost per invocation at about 300 shards
  on S3 and for large logs, with a cache that keeps steady-state polling
  cheap.
- No code execution and no writes to the log directory: the mode never
  recomputes metrics, imports task code, recovers or merges logs.

Non-goals:

- Any mutation (cancel, pause, requeue, drain, retune, scoring, log flush).
  No design here reaches a worker.
- Whole-task metrics for a running sharded task. Recomputing metrics needs
  the trusted merge (sharding design, "Trust"); this mode shows the merged
  log's stored results when one exists and per-sample scores otherwise.
- Relaying or proxying the control channel across machines (see
  "Alternatives considered").
- Changes to the log format, the sample buffer format, the viewer, or the
  control API. The mode is a reader of existing artifacts.
- A live push or `--follow` shape. Callers poll.

## Current behaviour

Only what the design depends on. Command-by-command routes are in "Command
inventory" below.

### How ctl reads today

- **Discovery and transport.** Every command first lists discovery files
  (`_http.list_discovered_servers`, `src/inspect_ai/_cli/ctl/_http.py:24`),
  then reads `GET /tasks` from each process concurrently
  (`_fetch_summaries`, `src/inspect_ai/_cli/ctl/_fetch.py:54`; concurrency
  capped at 32 by `_collect_reads`, `_http.py:386`) and resolves the TASK
  selector client-side (`_resolve_target_eval`, `_fetch.py:260`: exact
  `task_id`, `task_id` prefix, task name, then `--model`). Sample commands
  then call per-eval routes with the resolved `eval_id`
  (`_fetch_samples_async` `_fetch.py:467`, `_fetch_sample_detail` `:578`,
  `_fetch_sample_events` `:612`, `_fetch_sample_messages` `:675`,
  `_fetch_sample_store` `:723`). `_run_task_list` stamps `as_of` before the
  reads and wraps the server's bare list as `{as_of, tasks}`
  (`src/inspect_ai/_cli/ctl/_task.py:375-383`).
- **Row shapes.** A task row is built by `_build_summary`
  (`src/inspect_ai/_control/state.py:1312`, keys at `:1451-1490`); a
  terminal sample row by `_summary_from_eval_sample_summary`
  (`state.py:1031-1071`), a pure function of an `EvalSampleSummary`. The
  listing envelope is `{as_of, counts, samples, truncated}`
  (`server.py:798-858`) with `counts` over the fixed vocabulary
  `SAMPLE_STATUSES` (`state.py:56`).
- **The server already reads logs for finished evals.**
  `completed_eval_sample_summaries` (`state.py:683`) falls back from the
  recorder to `read_eval_log_sample_summaries_async(log_location)`, and
  `_full_sample` (`state.py:749`) to `read_eval_log_sample_async`. The events
  route pages an in-memory event list for a logged sample
  (`_resolve_logged_source`, `src/inspect_ai/_control/events.py:306-396`)
  and applies the shared cursor, filter and projection code
  (`sample_events` `:139-252`, `_attempt_nonce` `:255`, `_filter` `:428`,
  `_project` `:451`). The messages and store reads have the same
  running/logged split (`messages.py:62,146`, `store.py:60,164`).
- **The `--json` error contract.** Every terminal failure raises
  `_CtlFailure`, usually through `_fail`
  (`src/inspect_ai/_cli/ctl/_failure.py:111`), and every command runner is
  wrapped by `_envelope_failures` (`_failure.py:216`), which emits
  `{"error": {kind, exception, message, status}}` on stdout with a non-zero
  exit. `kind` is a closed `Literal` (`_failure.py:42-53`). A guard test keeps
  bare `click.exceptions.Exit` out of error sites
  (`test_no_bare_click_exit_in_ctl_error_sites`,
  `tests/_control/test_ctl.py:8490`).
- **No log-dir notion.** Nothing under `src/inspect_ai/_cli/ctl/` reads a log
  file or directory; `log_location` on a task row is informational.

### What the log directory holds while a run is live

- **The `.eval` file.** A zip with `_journal/start.json` from the start,
  `samples/<id>_epoch_<n>.json` per flushed sample, and one
  `_journal/summaries/<n>.json` member per flush batch
  (`write_buffered_samples`, `src/inspect_ai/log/_recorders/eval.py:1148-1185`)
  or per sample on the streaming completion path (`_journal_summary`,
  `:1082-1100`). `header.json`, `summaries.json` and `reductions.json` are
  written at finish (`:303-340`). A running log has no `header.json`;
  readers synthesise the header from `start.json` (`_read_header_async`,
  `:1858-1886`) and read the journal summaries, 25 at a time
  (`_read_all_summaries_async`, `:1936-1970`). Each flush copies the whole
  local temp zip to the destination, so the remote object is replaced, and
  its ETag changes, on every flush.
- **Flush cadence.** A completed sample joins `flush_pending`; the log is
  flushed when `log_buffer` samples are pending
  (`src/inspect_ai/_eval/task/log.py:766-776`) or when the stale-flush
  timer fires 60 seconds after the first pending sample
  (`_STALE_FLUSH_INTERVAL`, `log.py:76`; armed at `:986`). The default
  `log_buffer` for `.eval` is `max(1, min(floor(n/3), 10))`
  (`eval.py:135-144`). So a completed sample reaches the remote `.eval`
  within about 60 seconds plus the upload.
- **The shared sample buffer (`--log-shared` only).** The running process
  keeps its realtime buffer in a local SQLite database under
  `inspect_data_dir("samplebuffer")`, keyed by a hash of the log directory
  (`src/inspect_ai/log/_recorders/buffer/database.py:2130-2142`): it exists
  only on the worker host. With `log_shared` set, a daemon thread copies it
  to `<log_dir>/.buffer/<log stem>/` at most once per `log_shared` seconds
  (filestore created at `database.py:286-291`; throttle at `:1386-1419`;
  `DEFAULT_LOG_SHARED = 10`, `src/inspect_ai/_util/constants.py:30`; off
  unless `--log-shared` is given, `EvalConfig.log_shared`,
  `src/inspect_ai/log/_log.py:220`). The directory holds:
  - `manifest.json`, rewritten on every sync: the display metrics, one
    `SampleManifest` per sample still in the database (its
    `EvalSampleSummary` and its segment list), and a global segment list
    that only grows (`filestore.py:39-78`; rebuild in `sync_to_filestore`,
    `database.py:1894-1930`).
  - `segment.<n>.zip`, one per sync, holding for each sample with new data a
    `<id>_<epoch>.json` member with the event, attachment and pool rows
    added since its previous segment (`filestore.py:266-283,654-659`).
  - `metadata.<digest>.<hash>.json` sidecars and an empty `.keep`.

  A sample enters the database at start with its start-time summary
  (`start_sample`, `database.py:304-313`) and leaves it after the flush
  that writes it to the `.eval` (`remove_samples`, called at
  `log.py:820-822` after `recorder.flush`). A running sample's summary is
  therefore the start snapshot: no token or message progress until it
  completes (`complete_sample` rewrites it, `database.py:391-432`). The
  recorder writes the `.eval` before the rows are removed, so a sample that
  drops out of the manifest is already in the `.eval`.
- **Cleanup.** A normal finish deletes both the local database and
  `.buffer/<stem>/` for every final status (`database.py:626-628`,
  `filestore.py:378-380`). A hard-killed worker leaves its log `started`
  and its `.buffer/<stem>/` in place indefinitely: the sweep a later
  `eval()` runs in that directory removes a buffer only when its log is
  absent or no longer `started` (`cleanup_sample_buffer_filestores`,
  `filestore.py:614-642`, test at `:625-632`). A crashed shard is therefore
  indistinguishable from a running one by status alone, and its stale
  manifest stays readable.
- **Recorded selection is a seed, not an index.** `TaskLogger.__init__`
  records the sliced dataset's ids in `dataset.sample_ids` at start
  (`src/inspect_ai/_eval/task/log.py:242-306`). A `SampleSource` can admit
  further samples during the run (`src/inspect_ai/_eval/task/run.py:1684`,
  `:1730`) without updating that field, so a finished log can hold samples
  whose ids are not in its header, with `results.total_samples` counting
  them; `sample_ids` is also optional and absent in older logs
  (`src/inspect_ai/log/_log.py:966`). Only a finished log's
  `results.total_samples` is authoritative for its size.
- **The same key can have an older record in the log and a newer attempt in
  the buffer.** A seeded retry carries the prior attempt's sample members
  for keys it re-runs, and an in-process requeue re-runs a key already
  flushed. Recovery resolves this by comparing timestamps: a buffer row
  that started after the logged record's `sample_record_time`
  (completion, else start) supersedes it (`_superseded_by_buffer` and
  `sample_record_time`, `src/inspect_ai/log/_recover/_api.py:334-385`). Both
  sides of one log are written by one host, so the comparison needs no
  cross-host clock agreement. The live control server prefers the running
  source over the terminal one for the same reason
  (`resolve_sample_source`, `src/inspect_ai/_control/terminal_cache.py:164`).
- **Recovered logs.** `inspect log recover` writes `<stem>-recovered.eval`
  beside the original, keeping the original's timestamp prefix and task id
  (`default_output_path`, `src/inspect_ai/log/_recover/_write.py:371-375`).
  The checkpoint layout's `log_basename` strips both `.eval` and
  `-recovered` when deriving a companion directory
  (`src/inspect_ai/util/_checkpoint/_layout/eval_checkpoints_dir.py:23`),
  and the sharding design reuses it so `<name>-recovered.eval` maps to
  `<name>.shards/`.

### Existing readers and their request patterns

- **Zip reads.** `AsyncZipReader` finds the central directory with one
  suffix range read of up to 65,557 bytes (`_find_central_directory`,
  `src/inspect_ai/_util/async_zip.py:63-80`, `_MAX_ZIP_COMMENT_SIZE` and
  `_MIN_EOCD_SIZE` at `:25-26`), plus one more read when the central
  directory does not fit in that tail (`_parse_central_directory`,
  `:155-173`). A full member read is then one ranged GET covering its local
  header and compressed data (`read_member_fully`, `:422-465`); a streamed
  read, which the field-excluding sample read uses
  (`_read_member_json_excluding`, `src/inspect_ai/log/_recorders/eval.py:666`,
  via `open_member`), first reads the 30-byte local header and then the
  body (`_get_member_range_and_method`, `async_zip.py:472-490`; stream at
  `:278-281`). So a sample read is two requests after the central
  directory with exclusions and one without. The central directory records
  each member's CRC-32 and compressed size; `_parse_central_directory`
  parses the CRC and discards it (`async_zip.py:190`), and no member read
  verifies it. The central-directory and
  member reads are separate, unconditioned range requests, so an object
  replaced between them can yield bytes from two versions.
- **Whole-object reads return bytes only.** `AsyncFilesystem.read_file`
  (`asyncfiles.py:507`) returns the content without the response's ETag or
  Last-Modified.
- **Listing.** On S3, `list_eval_logs_async` lists with a single
  `list_objects_v2` sweep and, when recursive, no delimiter
  (`_list_eval_logs_async`, `src/inspect_ai/log/_file.py:221-259`;
  `AsyncFilesystem.iter_files`, `src/inspect_ai/_util/asyncfiles.py:881-916`),
  so it pages through every key under the directory, including every
  `.buffer/<stem>/segment.<n>.zip` and every object in sandbox checkpoint
  companions (`<name>.checkpoints/`). `iter_files(recursive=False)` sends
  `Delimiter="/"` but yields only `Contents`; `iter_dirs(recursive=False)`
  (`asyncfiles.py:952-977`) yields only `CommonPrefixes`. Listing entries
  carry size, mtime and ETag (`_s3_obj_to_file_info`, `asyncfiles.py:1166`).
- **The viewer's pending-sample reads** go through `sample_buffer()`
  (`buffer.py:10-14`), which opens the local database when present and
  otherwise the filestore, calling its synchronous fsspec readers on the
  event loop (`src/inspect_ai/_view/fastapi_server.py:507-580`). The
  filestore readers open each object through `open_file`: a size lookup plus
  a read, one read for objects under s3fs's 50 MiB default block
  (`s3fs.S3FileSystem.default_block_size`, s3fs 2026.6.0).
  `SampleBufferFilestore.running_tasks` uses `pathlib` and so works only on
  local directories (`filestore.py:382-393`).
- **Measured sizes** (mock model, this tree): a finished one-sample log is
  4.4 KB with a 383-byte central directory, `header.json` 0.7 KB compressed
  and `summaries.json` 0.3 KB; a 50-sample log has a 3.8 KB central
  directory and a 2.1 KB compressed `summaries.json` (27 KB raw). Real
  headers grow with the plan, task arguments and model configuration, and
  sample members of agentic tasks run to megabytes.

### The sharding layout (from `eval-sharding.md`)

The merged log is `<dir>/<name>.eval`; its shards are the `.eval` files
under `<dir>/<name>.shards/<k>/`, each with its own `.buffer` beside it.
`<name>` has the `{created}_{task}_{id}` shape, and `{id}` becomes the
merged log's `task_id`. Shards keep their own `task_id`s. Several files in
one `<k>/` are attempts of the same shard and the newest is current. The
merged log may lag the shards: it exists only after a merge, which runs when
the launcher calls it or at the next `eval_set()` startup. Shards are
retained after merging unless deleted explicitly. After a merge, an
`eval_set()` retry of an incomplete merged log is an ordinary unsharded log
that reuses the merged log's `task_id`, and with `retry_cleanup=False` the
merged log and its companion stay beside it; an unsharded `success` log
wins over a merged log with the same `task_id` regardless of mtime (parent
design, "Eval-set integration"). The merged log carries a
provenance field and ledger (per shard: file name, `eval_id`, samples merged,
status, ETag or mtime), whose exact shape is left to the sharding
implementation document.

## Design

### CLI surface

An option on each command the mode serves, after the command like every
other `ctl` option and like `--log-dir` on `inspect eval`, `eval-set` and
`log list` (decision: Ransom, 2026-09-24):

```
inspect ctl task list --log-dir <dir> [--shards] [--json]
inspect ctl sample list [TASK] --log-dir <dir> [...]
inspect ctl sample events TASK SAMPLE_ID [EPOCH] --log-dir <dir> [...]
```

- `--log-dir` takes a directory in any form Inspect reads (plain path,
  `file://`, `s3://`, other fsspec URLs). It is also accepted when the
  directory is a `<name>.shards/` companion or a single `<k>/`; the walk
  below treats the given directory as the root either way.
- It is a per-command option, declared once as a shared decorator
  (`_log_dir_option` in `_group.py`) and applied to `task list` and the six
  sample reads, so the help and behaviour cannot drift between them. Every
  other command lacks it: `--log-dir` there is click's usage error (exit 2,
  `No such option`, no `--json` envelope), like any other unknown option.
  The bare nouns (`task --log-dir <dir>`, `sample --log-dir <dir>`) take it
  through the existing `list`-option mirroring (`_mirror_list_options`); a
  noun-level `--log-dir` before a verb without the option is refused by
  `_forward_group_options`.
- No environment-variable mirror: switching ctl from the live process to
  stale logs silently, because a variable was left set, is the wrong
  failure. Every output in the mode says where it came from (below).
- The option's callback stores the root in `ctx.meta` under
  `inspect_ai.ctl.log_dir` (click's per-invocation shared dict), read by a
  helper `_log_dir_root() -> str | None` in a new module
  `src/inspect_ai/_cli/ctl/_log_dir.py`; the value is not passed to the
  command function.
- `task list` gains `--shards`: expand each sharded row into one row per
  shard after the logical row. Without it, sharded runs show one row. The
  flag is mirrored onto the bare `task` noun by the existing
  `_mirror_list_options` (`_group.py:192`). In live mode `--shards` is
  accepted and a no-op (there are no shard rows).
- Human output starts with one stderr line naming the mode and the usual
  lag, for example: `Reading logs in s3://bucket/run (read-only, not live;
  completed samples normally reach the log within about 60 s, running
  samples are visible only with --log-shared, as of its last sync)`. The
  wording states cadences, not bounds ("Polling guidance"). The empty-directory
  message replaces `_echo_no_running_evals` with `No eval logs found in
  <dir>.`

### Command inventory

Verdicts: **works** (same semantics, data as of the last flush or sync),
**degraded** (served with fields missing or coarser; the difference is
listed), **not available** (the command has no `--log-dir` option; passing
it is click's usage error). Within an available command, an option or a
target the logs cannot serve fails with `kind: "unsupported"`. The live
route and handler are for reference; the mode calls none of them.

| Command (click definition) | Live route (handler) | Log-dir verdict | Source in log-dir mode, and what differs |
|---|---|---|---|
| `task list` (`_task.py:82`) | `GET /tasks` (`server.py:769`) | degraded | Headers, summaries and buffer manifests. Live-only fields null (see "Task rows"). |
| `task log-flush` (`_task.py:101`) | `POST /tasks/{id}/log-flush` (`server.py:990`) | not available | Mutation. The staleness bound replaces it. |
| `task cancel` (`_task.py:121`) | `POST /tasks/{id}/cancel` (`server.py:1011`) | not available | Mutation. |
| `task score` (`_task.py:177`), including `--status` | `POST`/`GET /tasks/{id}/score` (`server.py:1107,1125`) | not available | Mutation; the pass state read by `--status` lives in the process (`get_score_pass`, `src/inspect_ai/_control/scoring.py:396`). |
| `task drain` (`_task.py:253`) | `POST /tasks/{id}/drain` (`server.py:1052`) | not available | Mutation. |
| `task pause` / `resume` (`_task.py:295,342`) | `POST /tasks/{id}/pause`, `/resume` (`server.py:1073,1085`) | not available | Mutation. |
| `sample list` (`_sample.py:90`) | `GET /evals/{id}/samples` (`server.py:798`) | degraded; `--active-since` unsupported | Summaries plus manifest rows through one source selection; `activity`, `events`, `interrupt`, `last_activity_at` for running rows are null; no `queued` rows; `--active-since` would drop samples published after the next lower bound (see "Sample rows"). |
| `sample errors` (`_sample.py:184`) | same, `filter=errors&all=true` | degraded | Errors from flushed logs, and from completed-but-unflushed buffer rows where `--log-shared` is on. |
| `sample show` (`_sample.py:209`) | `GET /evals/{id}/sample` (`server.py:861`) | works when the selected record is in the log; degraded when it is a buffer row | Log: the sample member read with heavy fields excluded, as the live terminal path does. Buffer: the manifest summary only; `error_retries` empty until flushed. |
| `sample events` (`_sample.py:263`) | `GET /evals/{id}/sample/events` (`server.py:881`) | works for log records; degraded for buffer rows; unavailable for running samples without `--log-shared` | Log: the sample member's events. Buffer: events reconstructed from the sample's segments, up to the last sync; the cursor restarts when the source becomes the log. |
| `sample messages` (`_sample.py:401`) | `GET /evals/{id}/sample/messages` (`server.py:938`) | works for log records; unsupported for buffer rows | Log: the sample member. The buffer has no message list (decision: Ransom, 2026-09-23). |
| `sample store` (`_sample.py:477`) | `GET /evals/{id}/sample/store` (`server.py:966`) | works for log records; unsupported for buffer rows | Log: the sample member. The buffer has no store snapshot. |
| `sample cancel` (`_sample.py:552`) | `POST .../sample/cancel` (`server.py:1224`) | not available | Mutation. |
| `sample cancel-tool-call` (`_sample.py:610`) | `POST .../sample/cancel-tool-call` (`server.py:1288`) | not available | Mutation. |
| `sample requeue` (`_sample.py:671`) | `POST .../sample/requeue` (`server.py:1341`) | not available | Mutation. |
| `sample score` (`_sample.py:1422`), including `--status` | `POST`/`GET .../sample/score` (`server.py:1149,1191`) | not available | Interim scoring runs scorers in the process; its pass state is in memory. |
| `process list` (`_process.py:87`) | discovery files plus `GET /tasks` | not available | There are no processes to list; `task list` is the mode's discovery surface. |
| `process keep` / `release` / `pause` / `resume` (`_process.py:100,114,127,161`) | `POST /keep`, `/release`, `/pause`, `/resume` (`server.py:1615,1597,1631,1635`) | not available | Mutations. |
| `process anomalies` (`_process.py:181`) | none; reads `trace-<pid>.log[.gz]` (`_trace_file_for_pid`, `_process.py:429`) | not available | Trace files are on the worker hosts, keyed by their pids. |
| `model pause` / `resume` (`_model.py:47,85`) | `POST /models/pause`, `/resume` (`server.py:1668,1685`) | not available | Mutations. |
| `model throughput` (`_model.py:108`) | `GET /models/throughput` (`server.py:1650`) | not available | Windowed rates from an in-memory registry (`throughput_report`, `src/inspect_ai/model/_throughput.py:419`). |
| `config`, view and set (`_config.py:36`) | `GET`/`PATCH /config`, `/tasks/{id}/config` (`server.py:1375,1394,1466,1486`) | not available | The view reports live limiter and override state (`process_limits`, `task_limits`, `src/inspect_ai/_control/limits.py:155,242`). A log records the launch `EvalConfig` and persisted `ConfigUpdate`s, which could back a degraded view later ("Not this design"). |

### Structured errors in the mode

- **Two new `_ErrorKind` values** (`_failure.py:42-53`):
  - `unsupported`: one of an available command's options (`sample list
    --active-since`), or the command on this target (a sample whose
    selected record is a buffer row, for `sample messages`/`store`), cannot
    be served from logs. The message names the reason and, for the
    per-target case, the nearest supported read (``"sample s3 epoch 1 is
    still running; its message list is not in the shared buffer. `inspect
    ctl sample events ... --type model --log-dir ...` shows its model
    calls."``). `status` and `exception` are null. A command that cannot be
    served at all has no `--log-dir` option, so it never reaches this kind.
  - `storage_error`: reading the directory failed for a reason other than
    absence: permissions, credentials, throttling, a transport failure, or
    an object that kept changing under a per-sample read after the bounded
    re-reads ("Reading a member consistently").
    `exception` is the package-qualified exception name as today
    (`_exception_name`, `_failure.py:167`); `status` is the HTTP status of
    an S3 `ClientError` when present. This is separate from the existing
    kinds because `_classify` maps every `OSError` to `connect_error`
    (`_classify`, `_failure.py:141`), and `FileNotFoundError`, an `OSError`, must
    not read as "the process is gone".
- **Existing kinds keep their meanings.** A missing log directory, or a
  TASK or sample selector with no match, is `not_found`; an ambiguous
  selector is `ambiguous` with the candidate ids in the message, through
  the same `_resolve_target_eval` (`_fetch.py:260`) and `_exit_ambiguous`
  (`_fetch.py:392`) as live mode, run over log-dir rows. A sample key held
  by two overlapping shards is `ambiguous` for the per-sample reads, naming
  both member logs. A log that exists but cannot be parsed is reported in
  the list reads' `unreadable` list with `incomplete: true` (as the live
  fan-out warns and skips an unreachable server, but visible in the
  envelope) and is `invalid_response` for a single-target read of that
  log.
- **Where the mode is bounded.** Only commands carrying the shared
  `--log-dir` decorator accept the option, so a command added later fails
  closed (a usage error) until someone implements the mode for it and adds
  the decorator. The per-option case (`--active-since`) and the per-target
  cases (buffer rows for messages/store) raise `unsupported` from the
  log-dir read itself. `_envelope_failures` prints the mode's stderr banner
  before the runner.
- **Guard tests** (see "Testing"): the commands carrying the option are
  exactly the supported set; every other registered leaf command, invoked
  with `--log-dir <dir>`, is a usage error (exit 2) before any storage
  access; `task list`, `sample list` and the per-sample reads never reach
  the discovery layer in the mode.

### Walking the directory

The walk produces a listing of logical tasks without paging through
`.buffer` segment keys or checkpoint objects. New helper
`walk_log_dir(root) -> LogDirListing` in
`src/inspect_ai/_control/log_dir/walk.py`:

- One delimited listing per directory visited. On S3 a new
  `AsyncFilesystem.list_dir(base) -> DirListing(files: list[FileInfo],
  dirs: list[str])` issues `list_objects_v2` with `Delimiter="/"` and
  returns `Contents` and `CommonPrefixes` from the same pages (today's
  `iter_files` and `iter_dirs` would take two sweeps for the same answer).
  Local directories use `os.scandir` without following directory symlinks,
  so a symlink loop cannot hang the walk; other fsspec backends use
  `_ls(detail=True)` per directory.
- Recursion rules, by directory name:
  - `.buffer/`: never listed. Its presence as a prefix in the parent's
    listing is recorded; a member's manifest path is derived as
    `.buffer/<stem>/manifest.json` and fetched directly (below).
  - `*.checkpoints/`: skip.
  - `<name>.shards/`: list it to get the `<k>/` prefixes, then list each
    `<k>/` (its `.eval` files, and whether it has a `.buffer/` prefix).
    Deeper directories under `<k>/` are ignored.
  - Any other subdirectory: descend, as `list_eval_logs` recurses today, so
    an eval-set directory or a directory of runs works.
- `.eval` files only. `.json` logs are listed as unsupported rows: the
  format is deprecated and its reads are whole-file parses
  (`endpoint-cost-audit.md`, finding 2); the sharding design is
  `.eval`-only.
- The listing keeps each file's size, mtime and ETag (or `mtime`+`size`
  where the backend has no ETag), which the cache keys on.
- A delimited listing of a directory costs one LIST per 1,000 entries, so a
  walk over one sharded run costs `N + 2` LISTs for `N` shards (root,
  `<name>.shards/`, each `<k>/`), whatever the buffers hold.

### Logical tasks

The listing is grouped into logical tasks, the rows of `task list`. Each
logical task has one or more *attempts* and exactly one *current* attempt,
whose data the rows and sample reads use.

**Attempt order.** Where a rule below says "newest", attempts are ordered by
the timestamp prefix of the file name (the `{created}` part, matched as
`EvalLogInfo` matches names, `_try_parse_filename`,
`src/inspect_ai/log/_file.py:1178`), then a `-recovered` file after the
file it was recovered from (recovery keeps the original's prefix and writes
the original's records plus its buffer, so it is the more complete), then
listing mtime. Names with no timestamp prefix sort by mtime alone.

**Sharded runs.** Every directory `X.shards/` is a companion, and `X` is the
basename the parent design derives with `log_basename` (which strips
`.eval` and `-recovered`,
`src/inspect_ai/util/_checkpoint/_layout/eval_checkpoints_dir.py:23`; the
parent design moves it to a neutral module, and this mode calls the moved
helper rather than re-implementing the rule).

- Its shards are, for each `<k>/`, the newest `.eval` in it. Older files in
  the same `<k>/` (a retry, or an original beside its `-recovered` copy)
  are superseded: counted in the shard's `attempts`, otherwise ignored,
  matching the parent's newest-wins rule.
- Its merged log is the `.eval` in the companion's parent directory whose
  `log_basename` is `X`: `X.eval` or `X-recovered.eval`, the newest when
  both exist. It does not get a row of its own.
- The shard set is one attempt of the logical task identified by `{id}`
  parsed from `X` (the merged log's `task_id`), or by `X` itself when the
  name does not parse.

**Unsharded logs.** Every other `.eval` file is an attempt of the logical
task identified by its `task_id` (from the header, or parsed from the file
name once the cache holds the header). Retries share a `task_id`; so does a
`-recovered` copy. The newest attempt is current and `attempts` counts
them, as live `/tasks` folds attempts by `task_id`
(`current_eval_summaries`, `state.py:190-204`).

**A sharded run and an ordinary retry of it.** An unsharded log whose
`task_id` equals a shard set's `{id}` is an `eval_set()` retry seeded from
the merged log (only that path gives an unsharded log the merged log's
`task_id`; shards keep their own). Both fold into one logical task, and the
unsharded log is current whatever the mtimes, following the parent's rule
that the unsharded log wins over the merged log it was seeded from: it
holds the merged samples plus the re-runs. The shard set is a prior
attempt: counted in `attempts`, described by the row's `shards` block and
by `--shards` rows, and not used for sample rows. With `retry_cleanup` on,
`eval_set()` removes the merged log and companion after a successful retry,
and the task is an ordinary unsharded row.

**A merged log whose companion is gone** (shards deleted after a verified
merge) is an ordinary unsharded attempt.

Identity fields for a row whose current attempt is a shard set: `task_id`
as above; `task`, `model`, `solver` and `epochs` from the first shard's
header (the merge refuses shards that differ on `task_identifier`, epochs
or reducer; this mode only reports, so a shard whose `task`, `model` or
`epochs` differs from the first is counted in `shards.mismatched` rather
than hidden); `eval_id` from the merged log when present, else null;
`log_location` the merged log's path when present, else the companion
path.

Selector resolution runs the existing `_resolve_target_eval` over these
rows unchanged. Because every attempt of a `task_id` is folded into one
row, a full task id always resolves to exactly one row. Shards are not
separately selectable; `--shards` rows carry `shard: "<k>"` and the shard's
own `task_id`, and are informational.

**Carrying the target past selection.** The sample commands pass only the
resolved row's `socket_path` and `eval_id` to the fetch functions
(`_fetch_samples_async` at `_sample_read.py:283`, `_fetch_sample_detail` at
`:587`, `_fetch_sample_events` at `:725`, `_fetch_sample_messages` at
`:807`, `_fetch_sample_store` at `:872`). Both are null for an unmerged
shard set, so two different logical tasks would reach those functions as
the same call. Every log-dir row therefore carries an additive
`log_target`: an opaque string naming its logical task within the root
(`"shards:<root-relative path of X.shards/>"` for a task whose attempts
include a shard set, `"log:<task_id>"` otherwise). In the mode, each of
those five call sites calls the log-dir adapter with the whole resolved
row instead of the live fetch function; the adapter reads `log_target` and
looks the logical task up in the listing the same invocation already
walked, so members are not re-listed. Live-mode calls, the live fetch
signatures and the public null `eval_id` are unchanged. Unscoped listings
(`sample list` with no TASK) call the adapter once per row, each with its
own `log_target`.

### Sample identity and source selection

One function decides, for every sample key of a logical task, where its
current record is. `task list` counts, `sample list` rows and all four
per-sample reads call it, so they cannot disagree.

**Keys.** A sample key is `(str(id), epoch)`, the readers' deduplication
key. The key set of a logical task's current attempt is the union, over its
members (one log, or one current file per shard), of:

- the recorded selection: `dataset.sample_ids` times `epochs`, when the
  header records ids (absent in older logs);
- the keys of the member's `.eval` summaries (`summaries.json`, or the
  journal members of a running log);
- the keys of the member's manifest rows.

The recorded selection is a seed: a `SampleSource` can add samples it does
not record, and they enter the key set when their summaries or manifest
rows appear. The key set is what can be enumerated; it is not in general
the task's size. A finished member's summaries cover every sample it ran,
but samples it admitted and never started (queued when the eval failed,
was cancelled or was drained) leave no record, and a log that finished by
an exception may have no `results` (`src/inspect_ai/_eval/task/run.py:1562`,
`:1992`, `:2366`). Totals are therefore defined separately ("Totals"
below).

**Totals.** The authoritative total of a logical task, when one exists:

- for an unsharded current attempt, a finished log's
  `results.total_samples`, which counts dynamically admitted samples;
- for a shard set, the intended selection recorded in the merged log's
  provenance field: its id list times `epochs`, or its sample count times
  `epochs` when the parent's merge was given a count
  (parent design, "Completeness").

Then `samples.total` is the authoritative total when there is one (or the
known-key count if that is larger, which marks the total not final), else
the known-key count as a lower bound; `samples.total_final` is true only
when the authoritative total is used; and `samples.pending_unlisted` is the
authoritative total minus the known keys (pending samples no record
names, which appear in `counts.pending` but have no rows), 0 when the
difference is not positive, and null when the total is not final. A
running log, a finished log without `results`, an older log without
recorded ids and a shard set without a recorded intended selection all
report a lower bound.

**Candidates per key, within one member.**

- A *log record*: the member's `.eval` summary for the key (last row wins,
  `_dedupe_summaries`, `eval.py:1920-1932`).
- A *buffer row*: the member's manifest entry for the key, running
  (`completed` false) or completed but not yet flushed (`completed` true).

**Selection** (`select_source(task, key) -> SourceChoice`, one of `log`,
`buffer`, `pending`, `conflict`, with the member and the chosen summary):

1. If more than one member has a candidate for the key (overlapping
   shards), the key is a `conflict`. No timestamps are compared across
   members, since they come from different hosts.
2. Otherwise, within the one member: the buffer row wins when there is no
   log record, or when the buffer row started after the log record's
   `sample_record_time` (recovery's rule, reused from
   `src/inspect_ai/log/_recover/_api.py:372`). This covers a seeded retry
   re-running a key it inherited and an in-process requeue re-running a
   flushed key. Both timestamps come from the same worker's clock.
3. Otherwise the log record.
4. A key with no candidate (recorded but not started, or started with no
   shared buffer) is `pending`.

**Status of a choice.** `log` and `buffer` map through the existing
`_summary_from_eval_sample_summary` (`state.py:1031`): a buffer row with
`completed` false is `running`; a completed buffer row takes its terminal
status from its summary. `pending` is `pending`. `conflict` has no single
status (see "Task rows" and "Sample rows").

**When a member's key set is current.** A match in one member does not
prove no other member holds the key: a `SampleSource` can admit a key in
another shard at any time, and it first appears in that shard's manifest,
not in its recorded ids or its log. So a key set is used only when it is
current for this invocation:

- a *finished* member (its log has `header.json`) whose listing ETag equals
  the cached one: its summaries hold every key it will ever hold, so the
  cached set is complete;
- a *running* member whose listing ETag equals the cached one: its logged
  keys are unchanged, and its buffer keys are current only once its
  manifest has been read in this invocation (a running member with no
  shared buffer has no other place a key can appear, so its logged keys
  suffice);
- any member whose ETag changed: current once its log snapshot has been
  refreshed.

**Locating a key for a per-sample read.** Before answering, the read makes
every current member's key set current by the rules above (a manifest GET
per running member with a shared buffer, a log snapshot per changed
member), then applies `select_source` across all of them. It never returns
a match, or `not_found`, from a key set that is not current. Its cost is
therefore that of a list read's key refresh plus the sample read itself
("Cost and scale"); the cache saves the plan and unchanged-log reads, not
the manifests of running members.

### Reading a member consistently

A member's `.eval` and its manifest are separate objects written at
different times, and the `.eval` itself is replaced on every flush. The
mode assembles each member's view with these rules, and never turns a torn
read into missing or pending data.

- **Worker order.** The recorder writes a sample to the `.eval` before
  removing it from the database, and the sync then drops it from the
  manifest (`src/inspect_ai/_eval/task/log.py:818-822`,
  `log/_recorders/buffer/database.py:1894-1930`). So a log observation
  taken *after* a manifest observation contains every key that manifest
  had already dropped.
- **The rule: the log is observed after the manifest.** For a running
  member whose manifest is read, the mode reads the manifest first and then
  checks the log's current version with one metadata request
  (`AsyncFilesystem.info`, a `head_object` on S3,
  `src/inspect_ai/_util/asyncfiles.py:467`; locally a `stat`, keyed by
  inode, `mtime_ns` and size, since the recorder replaces the local file
  atomically). If that version equals the version of the log snapshot the
  mode holds (from the cache, or from this invocation's plan read), the
  snapshot is used; otherwise the log snapshot is re-read, and the fresh
  central-directory read returns the current object. The listing's ETag,
  which precedes the manifest read, is used only to skip plan work, never
  to validate a snapshot against a manifest. Members with no manifest
  (finished, or running without a shared buffer) have no second object to
  order against, and their listing ETag suffices.
- **The guarantee.** Each member's view is consistent as of its manifest
  observation: every key the worker had admitted by then is reported from
  the manifest, from the log, or both, and never as `pending` or missing.
  A key the mode does not see was admitted after that moment and appears
  on the next poll. The guarantee depends only on reads made in this
  invocation, not on anything a previous invocation stored, so concurrent
  pollers and stale or lost cache entries cannot weaken it; they can only
  cost extra reads.
- **Mixed versions.** A central-directory read and a member read are
  separate range requests. The log-dir reader verifies every member it
  reads (whole or streamed) against the central directory's CRC-32, which
  `ZipEntry` gains for this and for the journal-member cache key; a CRC mismatch, a
  decompression error or a JSON error re-reads the central directory and
  the member, up to twice. A streamed read is validated when its stream is
  fully consumed (the field-excluding parse scans the whole member, so the
  final checksum is always reached); a stream closed early, by
  cancellation or error, is never treated as validated.
- **Disappearing buffer objects.** A finishing worker deletes its
  `.buffer/<stem>/` after the final flush. A manifest or segment that
  returns not-found during a read triggers source re-selection with fresh
  reads (manifest, then log), up to twice; if the sample is then flushed,
  the read is served from the log.
- **What failure looks like.** When the re-reads are exhausted:
  - list reads (`task list`, `sample list`, `sample errors`) keep the other
    members, mark the result `incomplete: true` with an `unreadable` list
    of `{log_location, reason}` on the task row and on the samples
    envelope, count nothing from the unreadable member, and warn on stderr;
  - per-sample reads fail with `storage_error` and a message naming the
    object that changed during the read.
  A buffer-sourced events page is `done: true` only when the buffer row is
  completed and every segment it lists was read.
- **Cache writes** happen only from a member view that passed these checks,
  and are atomic (temp file then rename); a cancelled or failed read writes
  nothing.

### Task rows

A log-dir task row has every key of a live row (`state.py:1451-1490`, plus
the route-stamped keys at `server.py:786-795`) so existing parsers keep
working. Values, over the current attempt:

| Key | Log-dir value |
|---|---|
| `run_id`, `eval_id`, `task`, `task_id`, `model`, `solver`, `epochs` | From the plan (shard sets: see "Logical tasks"). |
| `log_location` | The current log (unsharded), or the merged log / companion path (shard set). |
| `status` | `running` if any current member's log status is `started`, else `completed` (live's two values). |
| `started_at` | Earliest sample `started_at` seen, else the earliest member's `created`. |
| `completed_at` | Latest member `stats.completed_at` when no member is `started`, else null. |
| `samples.total` | The authoritative total when one exists, else the known-key count as a lower bound ("Totals" under "Sample identity"). |
| `samples.completed` / `errored` / `cancelled` | Keys whose selected source maps to that status. |
| `samples.in_flight` | Keys selected as `buffer` with `running` status; null when a running member has no manifest. |
| `samples.queued` | Null: dispatch state is not in the logs. |
| `total_tokens`, `total_messages` | Sums over the selected summaries (running samples contribute nothing until they complete, because their buffer summary is the start snapshot). |
| `tokens_per_second` | `total_tokens` over elapsed, as live computes it. |
| `attempts` | Number of attempts of the logical task (a shard set counts as one); per shard in `--shards` rows. |
| `paused`, `paused_now`, `quiesced`, `held`, `resolving`, `refusals`, `http_retries`, `keep_alive`, `process_paused`, `process_paused_now`, `paused_models`, `api_version`, `pid`, `socket_path` | Null (`paused_models` an empty list): live-only state. `refusals` and `http_retries` are event-derived counters not recorded in summaries. |

Additive keys, present on every log-dir row and absent in live mode:

- `source`: `"log_dir"`.
- `log_target`: the logical task's identifier within the root, which the
  sample commands route by ("Carrying the target past selection").
- `updated_at`: the latest of the current members' log mtimes and the
  Last-Modified of the manifests read. With `status: running`, a
  long-quiet `updated_at` is the only signal that a worker died (a crashed
  shard stays `started` and keeps its last manifest); the human table marks
  rows quiet for more than 10 minutes, and the JSON leaves the judgement to
  the caller.
- `samples.conflicted`: keys selected as `conflict`, counted in no status.
- `samples.unfinished`: `total − completed − errored − cancelled −
  conflicted`. The subtracted terms count distinct known keys, and `total`
  is never below the known-key count, so it is never negative.
- `samples.total_final`: true only when `total` is an authoritative total
  ("Totals"). While any member runs, or when no authoritative total exists,
  `total` is a lower bound: a `SampleSource` can still add samples,
  admitted-but-unstarted samples leave no record, and unstarted shards are
  not in the directory.
- `samples.pending_unlisted`: pending samples counted by an authoritative
  total that no record names (0 when there are none, null when
  `total_final` is false). They are in `counts.pending` of `sample list`
  but have no rows.
- `live_samples`: `"buffer"` when every running member has a manifest,
  `"none"` when none does, `"partial"` otherwise, so a caller knows whether
  `in_flight` and running sample rows are complete.
- `current_attempt`: `"log"` or `"shards"`.
- `shards` (null when the task has no shard set): `{total, running,
  success, error, cancelled, overlapping, mismatched}` over the shard set's
  current files, by log status; for a task whose current attempt is an
  ordinary retry, it describes the prior shard set.
- `merged` (null when there is no merged log): see "Merged log".
- `incomplete` and `unreadable` (see "Reading a member consistently").

### Sample rows

`sample list` and `sample errors` build one row per key from the selected
source with the existing `_summary_from_eval_sample_summary`, then apply
the existing filters, sort and cap: `--status` through
`parse_status_filter` (`state.py:81`), the cap through
`effective_sample_limit` (`state.py:123`) and `_sorted_samples`
(`state.py:665`), `counts` over `SAMPLE_STATUSES`. Differences from live:

- `pending` rows come from known keys with no candidate; pending samples
  counted only by an authoritative total (`pending_unlisted`) add to
  `counts.pending` without rows. There are no `queued` rows (dispatch is
  not recorded).
- Running rows have `activity`, `events`, `interrupt` and `last_activity_at`
  null and zero usage (start snapshot).
- **`--active-since` is unsupported in the mode** (`kind: "unsupported"`).
  Callers feed the previous listing's `as_of` back as the next lower bound
  (`server.py:815`), and the filter compares sample activity timestamps
  (`_filter_active_since`, `state.py:510`). A sample that completes before
  one poll but reaches the log only after it (flush up to about 60 s later)
  would carry a timestamp older than the next lower bound and never be
  returned. A delta keyed on publication (the log's or manifest's change)
  rather than sample time would fix this; it is left out of the MVP
  ("Not this design").
- A `conflict` key yields one row per member holding it, each with that
  member's status and `conflict: true`; the envelope's `counts` count
  distinct keys and leave conflicted keys out, and the envelope gains
  `conflicted` (their number), so row count and `counts` can differ only
  by the conflicted rows.
- Additive per-row keys: `shard` (`"<k>"` or null), `log_location` (the
  member `.eval` holding the chosen record, so a caller can hand it to
  `inspect log` commands) and `conflict`.
- `--content` gates `error` and `limit_reason` exactly as live does
  (`state.py:493`); the metadata-only default holds.

### Per-sample reads

`sample show`, `events`, `messages` and `store` resolve TASK to a logical
task, locate the key, and act on `select_source`:

- **`log`**: read the member with the field exclusions the live terminal
  paths use (`read_eval_log_sample_async` with `exclude_fields`, streamed
  with ijson for `.eval`) and build the same envelope through the shared
  projection code. The events read needs the full event list, as the live
  terminal path does.
- **`buffer`, running**: `sample show` returns the manifest summary row
  (no `error_retries`, no scores). `sample events` reads the manifest, then
  every segment listed for the sample, and reconstructs its events with the
  recovery code (`collapse_event_versions` and the message/call pool and
  attachment resolution used by `reconstruct_eval_sample`,
  `src/inspect_ai/log/_recover/_reconstruct.py:172-230`); pooled references
  can point into earlier segments, so a correct page needs the sample's
  whole segment history. The page is sliced in memory, with `done: false`.
  The cursor nonce is `_attempt_nonce` prefixed with `buffer:`, so when the
  sample's source becomes the log, an old cursor is foreign and the read
  restarts at offset 0 (the existing stale-cursor rule,
  `events.py:196-199`): duplicates, never gaps. `sample messages` and
  `sample store` fail with `unsupported` (decision: Ransom, 2026-09-23).
- **`buffer`, completed but not flushed**: as running, except that `sample
  show` includes the summary's error message (under `--content`) and
  `sample events` may return `done: true` once every listed segment was
  read. `sample messages` and `sample store` fail with `unsupported` naming
  the pending flush (``"sample s3 epoch 1 has completed but is not yet in
  the log; retry after the next flush (up to about 60 s)"``).
- **`pending`**: `not_found`, naming why: not started, or started with no
  shared buffer (``"... run the shards with --log-shared to see running
  samples"``).
- **`conflict`**: `ambiguous`, with the message naming each member log that
  holds the key, so the caller can read them with `inspect log` commands.

To share the paging code, `sample_events` in `src/inspect_ai/_control/events.py`
is split into source resolution (unchanged for live) and a
`page_events(source: EventsSource, *, since, tail, types, content, full,
since_time, until, limit) -> dict[str, Any]` that both paths call; the
messages and store reads get the same split around their `_project`
functions. These are refactors with no behaviour change in live mode.

### Merged log

The merged log is read, cheaply, for what only it has, and the shards stay
the source for sample state:

- **Why both.** The merged log lags: it is written by a trusted merge that
  runs when the launcher calls it or at `eval_set()` startup, typically
  after the workers exit. During a run it is absent or stale, while the
  shards are current to the last flush. Shards are retained by default, so
  reading them loses nothing.
- **What the row takes from it.** `merged: {log_location, status,
  updated_at, samples, metrics}`: its header status, mtime, merged sample
  count (`results.completed_samples`) and stored `results.scores` (the
  whole-task metrics). These are labelled as of `updated_at`; the mode
  never recomputes them from shard summaries (a summaries rollup is lossy
  for custom metrics and would need task code; the sharding design's open
  question 1 decides whether a stored rollup exists).
- **Intended selection.** When the merged log's provenance field records the
  selection it merged against, it becomes the shard set's authoritative
  total ("Totals"). An id list also joins the key set, so samples of
  shards that have not started yet are enumerable `pending` rows; a count
  gives only `pending_unlisted`. Until then the total covers discovered
  shards only, and the human output says so.
- **Later optimisation (implementation step 6).** The ledger records each
  merged shard's ETag. On a cold cache, a shard whose listing ETag equals
  its ledger ETag can take its sample rows from the merged log's
  `summaries.json` (one GET for all such shards) instead of a read per
  shard. The warm cache already avoids re-reading unchanged shards, so this
  only matters for the first read of a finished run.

### Cache

A local, per-user cache makes steady-state polls cost a listing plus reads
of what changed. `src/inspect_ai/_control/log_dir/cache.py`:

- **Location.** `inspect_data_dir("ctl")/log-dir-cache/`, created 0700 like
  the control discovery directory. One JSON file per log URI, named by
  `sha256(uri)`, holding a schema version and:
  - the plan (valid for as long as the file exists; a retried shard writes
    a new file with a new name);
  - the header-derived status fields and the parsed summaries, keyed by the
    file's ETag (or `mtime`+`size` locally), valid only while the listing
    reports the same key;
  - for a running log, the journal summary members already parsed, keyed by
    member name, CRC-32 and compressed size from the central directory.
    Journal members are append-only, so a changed running log costs its
    central directory plus the new journal members rather than every
    journal member again;
  - the observed key set (plan ids and summary keys, both tied to the
    log's version) used to skip re-reading unchanged logs.
- **Not cached**: manifest contents (they change every sync), sample
  members and segments (large; each invocation reads what it pages).
- **Writes**: only from validated member views, atomically (temp file,
  then rename; "Reading a member consistently"). Every cached value is
  keyed by the version of the object it was read from, so the cache is a
  pure performance cache: correctness never depends on its history. Two
  concurrent pollers may overwrite each other's entries in either order;
  whichever entry survives describes some real version of the log, and a
  reader that finds it stale (its version differs from the object's)
  simply re-reads.
- **Bounds.** Pruned oldest-access-first above 256 MB. Entries with an
  unknown schema version, or that fail to parse, are discarded and rebuilt,
  logged at debug; the cache never changes what a read returns, only
  whether it is fetched.
- **Scope.** Keyed by URI, so two directories never share entries; nothing
  in the log directory is written.

### Cost and scale

All figures are for S3, for one complete invocation (the CLI is one-shot,
so an invocation is also a poll), with reads issued concurrently on one
shared `AsyncFilesystem` (entered once per invocation, so every read reuses
its client, `asyncfiles.py:1019-1027`) and bounded at 32 in flight, the
CLI's existing fan-out cap. Request kinds:

- *walk*: `N + 2` LISTs for one sharded run of `N` shards; one LIST per
  1,000 entries for a flat directory.
- *plan*: CD (one GET of up to 64 KiB, or the whole object when smaller;
  one more GET when a large log's central directory does not fit) plus
  `header.json` or `start.json` (one GET). Cached per file, so paid once.
- *manifest*: one GET, only for a running member whose plan has
  `log_shared` set and whose directory has a `.buffer/` prefix. It returns
  the content with its ETag and Last-Modified (new
  `AsyncFilesystem.read_file_info`); a not-found answer means no manifest.
- *freshness check*: one metadata request (`head_object`) per running
  member whose manifest was read, taken after the manifest ("Reading a
  member consistently"). No body is transferred.
- *log snapshot*: when the log's version differs from the snapshot held: the CD, then, when the CD lists `header.json`
  (the log has finished, possibly since the last poll), `header.json` for
  the status, `stats.completed_at`, `results` and `error` that the cached
  plan does not hold, plus `summaries.json`: three GETs; for a log still
  running, the CD plus the journal members not yet cached. Zero when
  unchanged.
- *sample read*: after the CD, two GETs for a field-excluding read (local
  header, then body) and one for a full read (`sample events`).
- *segments*: one GET per segment listed for the sample.

Every command, including the per-sample ones, first resolves TASK against
the logical-task rows, which needs the walk and the plans but no manifests
or summaries (unlike live mode, where target resolution reads every task
summary). A per-sample read then makes every current member's key set
current ("Sample identity and source selection"): one manifest and one
freshness check per running member with a shared buffer and a log snapshot
per changed member, the same
refresh a list read does, so it costs about as much as `sample list` for
that task plus the sample read itself.

**Target case: 300 shards of one task, one sample each, `--log-shared`
on.** `R` shards running, `C` members whose log changed since the last
poll.

| Command | Cache | LIST | GET | Bytes and notes |
|---|---|---|---|---|
| `task list`, `sample list`, `sample errors` | cold, all running | 302 | 300 plans × 2 + 300 manifests + 300 freshness checks = 1,200 | ≤ 300 × (64 KiB + header + manifest), about 20–45 MB. A running one-sample shard has no summaries yet; the freshness checks carry no body. |
| same | cold, all finished | 302 | 300 × (CD + `header.json` + `summaries.json`) = 900 | ≈ 300 × (object up to 64 KiB + header + ~1 KB). |
| same | warm | 302 | `R` manifests + `R` freshness checks + log snapshots of changed members (3 GETs for each member that finished since the last poll; CD + new journal members for one still running) | A finished run with nothing changed: 302 LISTs, no GETs. A fully running run between flushes: 302 LISTs, 300 small GETs and 300 HEADs. All 300 shards finishing between two polls: 900 GETs on the next. |
| `sample show` / `messages` / `store`, sample in the log | warm | 302 | key refresh (`R` manifests + `R` freshness checks + changed-member snapshots) + CD + 2 | Bytes: the manifests, the compressed sample and a 64 KiB CD. With every shard finished and unchanged, the key refresh is free and the read is CD + 2. |
| `sample events`, sample in the log | warm | 302 | key refresh + CD + 1 | Full member read and parse; each page invocation re-reads the member. |
| `sample events`, buffer row | warm | 302 | key refresh (which includes this member's manifest) + `S` segments | `S` is at most one per sync while the sample ran, each a small delta zip. |
| any command | cold | 302 | + 600 plan GETs for the shards not yet cached, and every member's log snapshot | The first invocation in a directory pays the plans and snapshots once. |

At S3 list pricing 302 LISTs is on the order of $0.0015 per invocation, and
the latency is a few round trips at 32 in flight (about 1–3 s). A manifest
grows by about 0.2 KB per sync that touches the sample (a global and a
per-sample segment cursor), about 70 KB after an hour at the 10 s default.
The delimited walk keeps the LIST count at `N + 2`: a recursive listing of
`<name>.shards/` would page through every `segment.<n>.zip` (up to one per
shard per sync: about 108,000 keys after an hour of 300 shards at 10 s, 108
sequential LIST pages), which is how `list_eval_logs_async` lists S3 today.

**Large unsharded log** (10,000 samples, several GB; walk is one LIST):

| Command | State | GET | Bytes and notes |
|---|---|---|---|
| `task list` / `sample list` | finished, cold | CD tail + CD + `header.json` + `summaries.json` = 4 (plus the plan's `header.json`, the same object) | ~64 KiB + ~1 MB CD (about 80 bytes per member) + header + summaries (~1–2 KB raw per sample, compressed). Then cached until the ETag changes. |
| same | finished, warm | 0 | |
| same | running, after a flush | CD tail + CD + new journal members (+ 1 manifest and 1 freshness check with `--log-shared`) | A flush every ≤60 s replaces the object, so each poll after one re-reads the central directory, which grows with samples and journal members. Without the journal-member cache a running log re-reads every journal member, up to one per sample on the streaming path. |
| same | finished since the last poll | CD tail + CD + `header.json` + `summaries.json` = 4 | The final header supplies status, completion time and results. |
| per-sample reads | any | the same key refresh plus the sample read, as in the table above, with no shard walk | |

The per-page re-read of a flushed sample repeats `endpoint-cost-audit.md`'s
finding 1 shape (a full transcript parse per page), but on the caller's
machine rather than on an eval's event loop: it costs the caller bandwidth
and CPU and never slows a worker. `--limit` fetches more per call.

**Polling guidance** (in the docs and the human banner): data is no fresher
than the workers' flush (a completed sample normally reaches the log within
about 60 s) and buffer sync (`log_shared`, default 10 s) cadences. These are
cadences, not guarantees: a failed upload, a stopped worker or a retuned
`log_shared` stretches them, and nothing records a heartbeat. Polling `task
list` or `sample list` faster than every 30 s buys nothing. S3 request
rates are not a constraint: a few hundred LISTs and GETs per poll are far
below per-prefix limits, and the mode never touches a worker.

### Where the code goes

- `src/inspect_ai/_cli/ctl/_group.py`: the shared `--log-dir` option
  decorator and its callback; `task list --shards`.
- `src/inspect_ai/_cli/ctl/_task.py`, `_sample.py`: the decorator on `task
  list` and the six sample reads.
- `src/inspect_ai/_cli/ctl/_log_dir.py` (new): `_log_dir_root()`, the
  stderr banner, and the CLI-side calls into the log-dir reader.
- `src/inspect_ai/_cli/ctl/_failure.py`: the two new kinds; the banner call
  in `_envelope_failures`; storage-exception classification for log-dir
  reads.
- `src/inspect_ai/_cli/ctl/_fetch.py`, `_task.py`, `_sample_read.py`: branch
  at the existing fetch seams (`_fetch_summaries`, `_fetch_sample_summaries`,
  `_fetch_samples_async`, `_fetch_sample_detail`, `_fetch_sample_events`,
  `_fetch_sample_messages`, `_fetch_sample_store`) so rendering, selector
  resolution and envelopes are shared with live mode. The sample call
  sites pass the resolved row, carrying `log_target`, to the log-dir
  adapter ("Carrying the target past selection"). In the mode,
  `_fetch_sample_summaries` (which the per-sample commands call first to
  resolve TASK, `_sample_read.py:573`) returns identity-only rows from the
  walk and the plans, reading no manifests or summaries.
- `src/inspect_ai/_control/log_dir/` (new package): `walk.py`,
  `snapshot.py` (logical tasks, task rows, sample listing), `samples.py`
  (per-sample reads), `select.py` (`select_source` and the key set),
  `consistency.py` (the member-view checks and bounded re-reads),
  `buffer.py` (manifest and segment reads through `AsyncFilesystem`),
  `cache.py`. It reuses `state.py`'s row builder,
  filters and vocabulary, the events/messages/store projection code, the
  buffer `Manifest` model and `segments_for_sample_cursor`, and the recovery
  reconstruction helpers. It lives under `_control/` because it produces the
  control API's row and envelope shapes; it imports nothing that starts a
  server.
- `src/inspect_ai/_util/async_zip.py`: keep the CRC-32 on `ZipEntry`, and an
  opt-in CRC check on member reads (whole and streamed) that the log-dir
  reader enables; existing callers are unchanged.
- `src/inspect_ai/_util/asyncfiles.py`: `AsyncFilesystem.list_dir` and
  `AsyncFilesystem.read_file_info` (content plus the response's ETag and
  Last-Modified; on local files, a read plus `stat`).
- `src/inspect_ai/_control/events.py`, `messages.py`, `store.py`: the
  `page_*` refactors.
- `docs/control-channel.qmd` and `design/ctl/control-channel.md`: the mode,
  the verdict table, the two error kinds.

## Alternatives considered

- **Relay or proxy the control channel.** Forward each worker's AF_UNIX
  socket to the operator (SSH socket forwarding, a TCP bridge, or a relay
  service the workers dial out to). Full live semantics, mutations
  included. Rejected for the MVP: the premise is that the operator cannot
  reach the workers, and an outbound relay is new networked infrastructure
  that needs the authenticated remote attach `security.md` leaves out of
  scope for v1 ("Future hardening"). It also multiplies the fan-out: 300
  relayed connections per poll against the CLI's 32-read cap. This mode
  does not preclude it later; mutations need it.
- **Shards push status to storage.** Each worker's control server writes a
  small status object (its `/tasks` row and sample rows) to the log
  directory every N seconds. One small GET per shard, fresher than the
  flush, with live-only fields (activity, pause state) and a heartbeat that
  distinguishes a crashed worker from a running one. Rejected for the MVP:
  a new writer and a new persisted format on every worker, with S3 writes
  from 300 workers every N seconds, largely duplicating what the buffer
  manifest already carries; and the sharding design keeps `<name>.shards/`
  to `.eval` files and their buffers ("Security", "The intended
  selection"). It is the natural next step if the gaps in "Task rows" and "Sample
  rows" prove to matter, mainly crash detection and running-sample
  progress.
- **Transparent fallback.** When no live server is found, read logs
  automatically. Rejected: a silent switch from live to stale semantics,
  and ctl has no way to know which directory to read without a process.
- **A root option on the `ctl` group** (`inspect ctl --log-dir <dir> task
  list`), so every command runs under the mode and an unsupported one fails
  with a structured `unsupported` envelope instead of a usage error. It was
  the first implementation; rejected because every other `ctl` option, and
  `--log-dir` everywhere else in Inspect, goes after the command, and a
  usage error is the ordinary answer to an option a command does not take
  (decision: Ransom, 2026-09-24).
- **Reuse `list_eval_logs` and `read_eval_log_headers`.** Simplest, and fine
  for a small local directory, but on S3 the recursive listing pages through
  every buffer segment and checkpoint object and the header read fetches
  every file each time. Rejected for the walk and the cache; the zip readers
  underneath are reused.
- **Read only the merged log.** One file, cheap, whole-task metrics
  included. Rejected as the primary source because it exists only after a
  merge and lags the shards during exactly the window this mode serves; it
  is used for what only it carries.
- **Roll up whole-task metrics from shard summaries.** Rejected: lossy for
  custom metrics (sharding design, "Summaries are a lossy input"), needs
  metric code, and duplicates the trusted merge.
- **Read the local SQLite buffer when present.** The viewer's
  `sample_buffer()` opens the database first. It exists only on the worker
  host, where the live control channel is reachable and is the better
  tool; opening a live writer's WAL database from a second process adds
  locking concerns for no gain in the case this mode serves. Rejected; the
  mode reads the shared filestore only.
- **Recursive listing, which is cheaper early in a run.** With few segment
  objects a recursive listing of `<name>.shards/` is one or two pages
  instead of 301 LISTs. Rejected for predictability: its cost grows with
  run age and sync frequency, the walk's with shard count only.

## Compatibility and migration

No migration required. The mode is opt-in through a new flag.

- **CLI.** A new `--log-dir` option on `task list` and the six sample reads,
  and a new `task list --shards` flag (a no-op in live mode). Other
  commands reject `--log-dir` as a usage error. Live-mode behaviour,
  envelopes and exit codes are unchanged.
- **`--json` contract.** The closed `kind` vocabulary gains `unsupported`
  and `storage_error`; neither is raised in live mode. In the mode, task and
  sample rows have every live key (live-only values null) plus the additive
  keys listed above; envelopes are otherwise the live ones. Consumers that
  branch on `kind` or read row keys keep working; a consumer that treats a
  null `in_flight` as zero would under-report, which is why `unfinished`
  and `live_samples` exist; likewise `total_final` and `pending_unlisted`
  say when `total` is only a lower bound. A polling consumer that uses `sample list
  --active-since` gets `unsupported` in the mode and must poll full
  listings (capped as live listings are).
- **Control API.** Unchanged; the mode talks to no server, so
  `CONTROL_API_VERSION` (`src/inspect_ai/_control/__init__.py:84`) does not
  move.
- **Stored formats.** None change. The mode reads `.eval` files and buffer
  manifests and segments as written by current versions. Logs written by
  older versions read as they do through `read_eval_log*`; a buffer
  manifest written before #4207 (bare segment ids) is handled by the
  existing `segments_for_sample_cursor` fallback. The merged-log fields
  (provenance, ledger) are used only once the sharding implementation adds
  them, and are optional.
- **Refactors.** The events, messages and store paging splits keep live
  behaviour, covered by the existing tests in `tests/_control/`. The
  `ZipEntry` CRC field and the CRC check are additive and opt-in; existing
  `AsyncZipReader` callers behave as before.
- **Viewer and generated types.** Unaffected.
- **New local state.** The cache directory under `inspect_data_dir("ctl")`;
  safe to delete at any time.

## Security

The mode reads a directory the user names, with the user's own storage
credentials. The content threat model in `security.md` applies unchanged,
with a different transport:

- **Untrusted content reaches the CLI as before.** Sample summaries, error
  messages, events, messages, store values and file and directory names in
  the log directory are agent-influenced or attacker-writable (anyone who
  can write to the bucket). They flow through the same projections, the
  metadata-only default with `--content`/`--full` opt-ins, and the same
  sanitizing `_echo` wrapper for human output (`security.md`, Vectors 1
  and 2). Shard directory names (`<k>`) and file names are rendered through
  the same sanitization; they are dynamic strings like any other.
- **No code execution.** The mode never recomputes metrics, never calls
  `resolve_scorers_info` or imports a header-named `task_file`, never runs
  recovery, and never merges. The merge stays a trusted step run by the
  launcher or `eval_set()` (sharding design, "Trust"). Stored metrics are
  displayed as stored.
- **Read-only.** Nothing is written to the log directory: no buffer cleanup
  (`cleanup_sample_buffers` is not called), no recovery output, no merge.
  Filestore paths are read through `AsyncFilesystem`, never through a
  `SampleBufferFilestore(create=True)`, whose constructor writes a `.keep`
  object (`filestore.py:228-232`). Local writes go only to the 0700 cache
  directory.
- **Paths come from the listing, not from content.** Member, manifest and
  segment paths are derived from listed names by fixed suffix rules
  (`.buffer/<stem>/manifest.json`, `segment.<n>.zip` from manifest segment
  ids, which are integers in the `Segment` model). The merged log's
  recorded companion path is ignored; the companion is derived from the
  name. The local walk does not follow directory symlinks.
- **Hostile or oversized inputs.** A crafted manifest, a huge
  `summaries.json` or a large sample member costs memory and bandwidth on
  the caller's machine, as the same files do for `read_eval_log*` and the
  viewer today; list reads parse only headers, summaries and manifests.
  Neither reaches a running eval: unlike a control endpoint, nothing here
  runs on an eval's event loop (`security.md`, Vector 3 does not apply).
- **Access.** No listener, no socket, no new network path. Anyone who can
  read the log directory could already read everything this mode shows; the
  mode adds convenience, not access. Limiting `--log-dir` to the read
  commands is not a security boundary (the mode has no write path to
  guard); it keeps a mutation from ever running against a directory.
- **Cache.** Owner-only, keyed by URI and ETag, re-parsed through the same
  pydantic models on read; a same-user attacker who can edit it is out of
  scope, as for the discovery directory.

## Testing

All tests run in the default CI job: no network, Docker or model provider.
S3 behaviour uses the existing `mock_s3` fixture (`tests/conftest.py`, a
real moto server on an ephemeral port). New tests go in a new
`tests/_control/test_log_dir.py` for the reader and in
`tests/_control/test_ctl.py` for the CLI surface.

- **Fixtures.** Finished logs from mock-model evals (unsharded, a retried
  task with two attempt files, a sharded layout `<name>.shards/{0,1,2}/`
  with and without `<name>.eval`, a `<k>/` holding an old attempt and its
  retry). Running logs built with the recorder APIs (`log_init`,
  `log_start`, journaled summaries, no `header.json`) plus a buffer written
  through `SampleBufferFilestore.write_manifest`/`write_segment`, including
  a running sample, a completed-but-unflushed one, and a pre-#4207 manifest.
  One end-to-end test runs a mock-model eval with `log_shared=1` whose
  solver waits on an `anyio.Event`, reads the directory through the async
  reader while the sample runs, then releases it.
- **Rows.** Unsharded, retried and sharded rows have every live key; counts,
  `in_flight`, `unfinished`, `conflicted`, `total_final`, `live_samples`,
  `shards` and `merged` match the fixture; mismatched shards are counted; a
  merged log whose companion is gone is an ordinary row.
- **Sample key set.** A static selection; a `SampleSource` that adds a
  sample mid-run (the added key appears in `total`, is locatable by every
  per-sample read, and `unfinished` never goes negative); an empty seed
  whose samples are all added; a log with no recorded `sample_ids`.
- **Attempt folding.** Retries of an unsharded task; an original and its
  `-recovered` copy (recovered is current), inside a `<k>/` and as
  ordinary logs; a recovered merged log `X-recovered.eval` beside
  `X.shards/` (one row, no extra); an ordinary `eval_set()` retry sharing a
  shard set's `task_id`, with the merged log and companion retained
  (`retry_cleanup=False`: one row, the retry current, a full task id
  resolves without ambiguity) and removed (cleanup on: an ordinary row).
- **Source selection.** For a seeded retry re-running an inherited key and
  for an in-process requeue of a flushed key: while the new attempt runs,
  after it completes but before its flush, and after the flush, `sample
  list`, `sample show`, `events`, `messages` and `store` all report the
  same attempt (no read returns the superseded record, and no old `done:
  true` page).
- **Overlap.** Two shards holding one key: `samples.total` counts it once,
  `conflicted` is 1, `unfinished` stays non-negative, the listing shows two
  rows with `conflict: true` and `counts` leaves the key out, and each
  per-sample read fails `ambiguous` naming both member logs.
- **Key-set currency.** For each of `sample show`, `events`, `messages` and
  `store`: a cold lookup of a key that no recorded selection names (a
  `SampleSource` addition) finds it; a warm lookup after a second shard
  admits the same key into its manifest, with its log ETag unchanged,
  fails `ambiguous` instead of returning the first shard's record; a warm
  lookup of a key newly admitted in any running shard's manifest finds it.
- **Totals.** A dynamic run that completes (authoritative
  `results.total_samples`, `total_final` true); one that fails or is
  cancelled with admitted samples still queued, with and without `results`
  (lower bound or `pending_unlisted`, never `total_final` true without an
  authoritative total); an older log with no recorded ids; a shard set
  whose merged log records an id list and one that records a count.
- **Logical-task routing.** Two unmerged companions under one root whose
  shards share a sample id: `sample show`/`events`/`messages`/`store` on
  each task return that task's record, and an unscoped `sample list`
  returns both tasks' rows, each routed by its `log_target`.
- **Sample reads.** List, errors, `--status`, `--limit`/`--all`, `--content`
  gating; `--active-since` is `unsupported`; `sample show`/`events`/
  `messages`/`store` on log records equal the live terminal envelopes for
  the same log (the live path's log fallback read over the same file);
  buffer-row events reconstructed from segments equal the events later
  flushed for that sample; a cursor from the buffer source restarts on the
  log source; a pending sample is `not_found`.
- **Races** (deterministic: the fixture's storage layer blocks on
  `anyio.Event` barriers between the listing, the manifest read, the
  freshness check and the log read). A warm poll where the worker flushes
  and drops a key from the manifest after the listing: the freshness check
  sees the new version and the key is reported from the re-read log, not as
  pending. The reviewer's schedule: poller A holds an older view and is
  paused between its cache re-read and rename; poller B, seeing key `x` in
  the manifest, commits; A renames over B's entry; then the worker flushes
  `x` and drops it from the manifest while poller C's listing still shows
  the old ETag. C reports `x` (from the log, after its freshness check) and
  never as pending or not found. A segment deleted after the manifest was read: the read
  re-selects and serves the flushed record. An object replaced between the
  central-directory read and the member read: the CRC check triggers a
  re-read. Exhausted re-reads: list reads return `incomplete: true` with
  the member in `unreadable`; per-sample reads fail `storage_error`. No
  failed or cancelled read leaves a cache entry. A streamed member read that
  is corrupted fails its CRC check; one cancelled mid-stream is not
  validated and writes nothing. Deleting or corrupting every cache entry
  between two polls changes no output, only the request count.
- **Contract guards.** The commands carrying `--log-dir` are exactly the
  supported set; every other leaf command, invoked with `--log-dir <tmp>`,
  is a usage error (exit 2, no envelope) and makes no storage or discovery
  call (parametrized over the command tree, so a new command is covered
  automatically); a missing directory is `not_found`; a storage permission
  failure is `storage_error` with `status`.
- **Cost.** On `mock_s3`, a botocore event hook counts requests by
  operation, and the tests assert the "Cost and scale" formulas for each
  supported command, cold and warm, with running and finished shards: a
  walk of 50 shards issues 52 LISTs regardless of how many
  `segment.<n>.zip` objects exist (the fixture adds hundreds) and never
  lists a `.buffer/`; a cold `task list` over 50 finished shards issues 150
  GETs and a warm one none; 50 running shards between flushes cost 50
  manifest GETs and 50 freshness checks warm, and no log reads; a warm poll after all 50 finish costs 150 GETs (CD,
  final `header.json`, `summaries.json`) and reports their new status and
  `completed_at`; changing one shard costs its reads only; per-sample
  commands read no manifests or summaries during target resolution and
  then pay the key refresh; a field-excluding sample read costs the CD plus
  two GETs; a running large log re-reads only new journal members.
- **Read-only and no code.** The directory tree, bytes and mtimes are
  unchanged after every supported command; `resolve_scorers_info` and
  task-file import are patched to fail and never called; hostile shard
  directory and file names (escape sequences, newlines, bidi controls) are
  sanitized in human output.
- **Async.** The reader's async tests run under asyncio and trio
  (`--runtrio` before the PR), including a cancellation mid-walk that
  leaves no partially written cache entry.

## Implementation plan

Each step is one PR; steps 1–5 are the MVP.

1. **Mode plumbing and the contract.** The shared `--log-dir` option
   decorator, `_log_dir_root()`, the `unsupported` and `storage_error`
   kinds, the stderr banner, the guard tests. Files: `_cli/ctl/_group.py`,
   `_cli/ctl/_log_dir.py`, `_cli/ctl/_failure.py`,
   `tests/_control/test_ctl.py`.
2. **Unsharded reads of logged data.** `AsyncFilesystem.list_dir`, the
   walk, logical tasks with attempt order, retry and `-recovered` folding,
   the key set, totals and `select_source` (log records only at this
   step), task rows with `log_target`, sample listing with `--active-since`
   refused, identity-only target resolution, `log_target` routing at the
   five sample call sites, per-sample reads of log records with the CRC check and
   bounded re-reads; the `page_*` refactors; the `--log-dir` option on `task list`, `sample
   list`/`errors`/`show`/`events`/`messages`/`store`. Files: `_util/asyncfiles.py`, `_util/async_zip.py`,
   `_control/log_dir/{walk,snapshot,select,consistency,samples}.py`,
   `_control/events.py`, `messages.py`, `store.py`, `_cli/ctl/_fetch.py`,
   `_task.py`, `_sample.py`, `_sample_read.py`, `tests/_control/test_log_dir.py`.
3. **Buffer rows from shared buffers.** `AsyncFilesystem.read_file_info`,
   manifest reads, buffer candidates and the newer-buffer precedence in
   `select_source`, the key-set currency rule for per-sample lookups, running and completed-but-unflushed rows, `in_flight`,
   `live_samples`, `updated_at` from manifests, buffer `sample show` and
   `sample events` from segments, the per-target `unsupported` for
   messages/store, the manifest-then-freshness-check ordering and
   disappearing-object re-selection. Files: `_util/asyncfiles.py`, `_control/log_dir/buffer.py`,
   `select.py`, `consistency.py`, `samples.py`, `snapshot.py`, tests.
4. **Shard aggregation.** The `<name>.shards/` walk rules, logical sharded
   rows, newest-attempt selection per `<k>/`, the recovered-merged-log
   mapping, folding an ordinary retry with its shard set, the `shards`
   block, conflicts (counts, rows, `ambiguous` per-sample reads) and
   mismatch counts, `--shards`. Depends only on the layout convention, so it
   can land before the sharding merge exists. Files: `walk.py`,
   `snapshot.py`, `select.py`, `_cli/ctl/_task.py`, `_group.py`, tests.
5. **Cache.** Plan, summaries, journal-member, observed-key and
   version-keyed caching, atomic validated writes, pruning, and the
   request-count tests. Files: `_control/log_dir/cache.py`, `snapshot.py`,
   tests.
6. **Merged-log integration** (after the sharding implementation adds the
   provenance field and ledger). The `merged` block, the intended selection
   (id list or count) as the authoritative total, the ledger-based
   cold-start read. Files:
   `snapshot.py`, tests.
7. **Docs.** `docs/control-channel.qmd` (the mode, the verdict table,
   polling guidance) and `design/ctl/control-channel.md` (the error kinds in
   the agent output contract); in each PR that changes the surface, or
   together at step 5.

## Open questions

None open. Ransom resolved all three on 2026-09-23, each as recommended:

1. **Default row shape for sharded runs.** One logical row per task by
   default, with per-shard rows behind `task list --shards`. A 300-row
   default would flood an agent's context, which the listing cap exists
   to prevent.
2. **Cache in the MVP.** Included (step 5). Without it every invocation
   over a 300-shard run pays the cold row of "Cost and scale": 302 LISTs
   and 900–1,200 requests (20–45 MB) for a list read, and 302 LISTs plus
   about 600 plan GETs before any per-sample read. With it, a warm list
   read of a finished run is 302 LISTs and no GETs, and a per-sample read
   of a finished run is 302 LISTs plus three GETs. A running run still
   costs one manifest GET and one freshness check per running shard on
   every read, cached or not. The cache affects cost only; the consistency
   guarantee does not depend on it.
3. **Messages and store for buffer rows.** Unsupported in the MVP for
   every buffer-sourced row, including completed-but-unflushed ones.
   `reconstruct_eval_sample` could rebuild a running sample's messages from
   its buffered model events (what `inspect log recover` produces), at the
   cost of reading every segment of the sample per call, and there is no
   store equivalent. `sample events --type model` is the pointer the
   `unsupported` error gives.

## Not this design

- `AsyncZipReader` reads a 64 KiB suffix to find every central directory,
  which dominates the bytes of reading many small logs (the viewer and
  `read_eval_log_headers_async` pay it too); a smaller first read with a
  fallback would cut it.
- `list_eval_logs_async` on S3 pages through every `.buffer` segment and
  checkpoint object under a log directory (the viewer's `/logs` listing
  pays this for any directory with `--log-shared` runs); a delimited walk
  like the one here would bound it.
- `SampleBufferFilestore.running_tasks` works only on local directories
  (`filestore.py:382-393`), although shared buffers exist mainly for remote
  ones; it has no callers today.
- A running sample's buffer summary is its start snapshot, so no reader
  (viewer included) sees token or message progress until it completes; a
  periodic summary refresh in the buffer database would fix it for every
  reader.
- `AsyncFilesystem` has no conditional GET; `If-None-Match` on manifest
  reads would make an unchanged running shard's poll a 304.
- A crashed worker's log stays `started` forever; nothing records a
  heartbeat. The status-push alternative above, or a heartbeat in the
  buffer manifest, would let every reader tell crashed from running.
- A degraded `config` view from the log's launch `EvalConfig` and persisted
  `ConfigUpdate` records.
- A publication-keyed delta for `sample list` in log-dir mode (a watermark
  over log and manifest changes rather than sample timestamps), which would
  make `--active-since`-style polling safe against flush delay.
- Range reads pinned to the central directory's ETag (`IfMatch` on member
  GETs) in `AsyncZipReader`, which would turn a mid-read replacement into
  an explicit error for every reader instead of relying on the CRC check.
