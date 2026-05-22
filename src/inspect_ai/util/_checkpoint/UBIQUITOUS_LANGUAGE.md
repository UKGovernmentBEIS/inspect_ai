# Ubiquitous Language

Canonical vocabulary for the checkpointing subsystem. Use these terms
consistently in code, docstrings, design docs, and discussion. When the
codebase drifts, prefer fixing the code over picking up the drifted term.

## Directories

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Evals checkpoints dir** | Parent directory under which **eval checkpoints dir** are created. Customizable per inspect process via `CheckpointConfig.checkpoints_location`; defaults to the eval log's parent dir. Any fsspec-resolvable path (local, `s3://`, etc.). | "checkpoints location" (as a *concept*; remains the config field name), "checkpoints root" |
| **Eval checkpoints dir** | Per-eval parent for sample-level checkpoint state. Path: `<evals_checkpoints_dir>/<log-base>.checkpoints/`. | "checkpoints directory" (ambiguous), "checkpoint dir" |
| **Sample checkpoints dir** | Per-sample subtree under the **eval checkpoints dir**. Path: `<eval_checkpoints_dir>/<sample-id>__<epoch>/`. (A `_<retry>` suffix is reserved for sample-level retries but currently unused.) | "attempt dir", "per-attempt directory" |
| **Eval working dir** | Host-local cache parent for every **sample working dir** in this eval. Path: `inspect_cache_dir("checkpoints")/<log-basename>/`. Never shipped to remote storage. | "cache dir", "scratch dir" |
| **Sample working dir** | Per-sample host-local cache. Path: `<eval_working_dir>/<sample-id>__<epoch>/`. Holds the host-side JSON files restic snapshots at each fire; overwritten in place every fire. | "scratch dir", "context dir" |
| **In-sandbox restic repo** | Fixed standard location inside each sandbox container, initialized by `init_sandbox_repo`. Holds in-sandbox snapshots of paths declared in `CheckpointConfig.sandbox_paths[<name>]`. | "sandbox repo" (ambiguous: host-side `sandboxes/<name>/` is also a sandbox repo) |

## Lifecycle and actions

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Checkpoint** (noun) | One persisted point-in-time of a sample, identified by an ordinal `checkpoint_id`. Materialized as a sidecar plus one host snapshot plus one snapshot per sandbox repo. | "save", "snapshot" (snapshot is a restic concept) |
| **Fire** (verb) | The act of writing a new checkpoint: write host context to working dir → restic backup host → per-sandbox (restic backup → egress) in parallel → write sidecar (commit point). | "save", "checkpoint" (as verb) |
| **Tick** (verb) | A turn-boundary signal from the agent (`cp.tick()`). May or may not result in a fire, depending on the policy in `CheckpointConfig.trigger`. | "step" |
| **Track** (verb) | Agent-side registration of a key + capture callback + initial value via `cp.track(...)`. Captured values land in `agent_state.json` at each fire. | "register", "stash" |
| **Egress** (verb) | Copy a freshly-written in-sandbox snapshot from the **in-sandbox restic repo** to the host-side **sandbox repo (host-side)**. | "export", "extract" |
| **Hydrate** (verb) | Populate the post-resume world from on-disk state: FS-copy the old **sample checkpoints dir**, restic-restore the **sample working dir**, push restored events/attachments/store into framework state, load `agent_state.json` onto `_EnteredCheckpointer`. Implemented as `_hydrate` (orchestrator) → `_hydrate_host` + `_hydrate_sandbox` (per sandbox). | "rehydrate" (use "hydrate" — the function handles both fresh and resume), "restore" (too narrow; restore is one step within hydrate) |

