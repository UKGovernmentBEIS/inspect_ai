# Ubiquitous Language

Canonical vocabulary for the checkpointing subsystem. Use these terms
consistently in code, docstrings, design docs, and discussion. When the
codebase drifts, prefer fixing the code over picking up the drifted term.

## Directories

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Evals checkpoints dir** | Parent directory under which **eval checkpoints dir** are created. Customizable per inspect process via `CheckpointConfig.checkpoints_location`; defaults to the eval log's parent dir. Any `AsyncFilesystem`-resolvable path (local, `s3://`, etc.). | "checkpoints location" (as a *concept*; remains the config field name), "checkpoints root" |
| **Eval checkpoints dir** | Per-eval parent for sample-level checkpoint state. Path: `<evals_checkpoints_dir>/<log-base>.checkpoints/`. | "checkpoints directory" (ambiguous), "checkpoint dir" |
| **Sample checkpoints dir** | Per-sample subtree under the **eval checkpoints dir**. Path: `<eval_checkpoints_dir>/<sample-id>__<epoch>/`. Always exists; may be local or remote. Layout: `ckpt-*.json` **checkpoint files** at the root, plus `restic/restic-config.json` (per-sample restic password — written once, preserved across retries), `restic/host/` (host restic repo), and `restic/sandboxes/<name>/` (per-sandbox restic repos). The **context subdir** also lives here when the destination is local; when remote, it lives only in the **sample staging dir**. Path helpers in code: `host_repo_dir(sample_root)`, `sandbox_repo_dir(sample_root, name)`, `restic_config_path(sample_root)`. | "attempt dir", "per-attempt directory" |
| **Sample staging dir** | Per-sample host-local mirror of the **sample checkpoints dir** that exists only when the resolved **sample checkpoints dir** is remote. Same internal layout as a local sample checkpoints dir, plus `.egress-manifest.txt` for **host egress** bookkeeping. Restic writes here; host egress ships everything except the **context subdir** and the manifest to the (remote) sample checkpoints dir. Path: `inspect_cache_dir("checkpoints")/<log-basename>/<sample-id>__<epoch>/`. | "shadow dir", "buffer", "local checkpoints dir", "sample working dir" |
| **Context subdir** | Per-sample subdirectory containing the host context files restic snapshots at each fire (`events.json`, `events_data.json`, `attachments.json`, `store.json`, `agent_state.json`). Path: `<sample-root>/context/`. Overwritten in place every fire — restic's *input*, not its output. Lives at the destination only when the destination is local; in the remote case it lives only in the **sample staging dir** and is never shipped (its contents are part of the `restic/host/` snapshot, which does ship). | "sample working dir" (former top-level name), "scratch dir" |
| **In-sandbox restic repo** | Fixed standard location inside each sandbox container, initialized by `init_sandbox_repo`. Holds in-sandbox snapshots of paths declared in `CheckpointConfig.sandbox_paths[<name>]`. | "sandbox repo" (ambiguous: host-side `restic/sandboxes/<name>/` is also a sandbox repo) |

Where the term **sample root** appears in code or text, it refers to "wherever the sample's restic state and **checkpoint files** are first materialized": the **sample checkpoints dir** when the destination is local, the **sample staging dir** when remote. Not a UL term in its own right — just a convenience name for that union.

## Lifecycle and actions

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Checkpoint** (noun) | One persisted point-in-time of a sample, identified by an ordinal `checkpoint_id`. Materialized as a **checkpoint file** plus one host snapshot plus one snapshot per sandbox repo. | "save", "snapshot" (snapshot is a restic concept) |
| **Checkpoint file** (noun) | The `ckpt-NNNNN.json` file at the root of the **sample checkpoints dir** (and **sample staging dir** when remote). One per fired **checkpoint**; its presence is the commit point — a checkpoint is visible to resume only when its file is in place. Pydantic shape: `Checkpoint`. | "sidecar" |
| **Fire** (verb) | The act of writing a new checkpoint: write host context → restic backup host → per-sandbox (restic backup → sandbox egress) in parallel → write **checkpoint file** → (when destination is remote) **host egress**. | "save", "checkpoint" (as verb) |
| **Tick** (verb) | A turn-boundary signal from the agent (`cp.tick()`). May or may not result in a fire, depending on the policy in `CheckpointConfig.trigger`. | "step" |
| **Track** (verb) | Agent-side registration of a key + capture callback + initial value via `cp.track(...)`. Captured values land in `agent_state.json` at each fire. | "register", "stash" |
| **Sandbox egress** (verb) | Copy a freshly-written in-sandbox snapshot from the **in-sandbox restic repo** to the host-side `restic/sandboxes/<name>/` repo (under the sample root). | "export", "extract" |
| **Host egress** (verb) | Ship newly-written files from the **sample staging dir** to the (remote) **sample checkpoints dir** using the manifest-diff protocol (sorted list of files already shipped; diff identifies new files; ship in safe order; manifest commits only after the ship succeeds). Runs at the end of each fire when the resolved **sample checkpoints dir** is remote; not used in the local case. | "upload", "sync" |
| **Hydrate** (verb) | Populate the post-resume world from on-disk state: copy the old **sample checkpoints dir** into the current run's sample dir, restic-restore the **context subdir**, push restored events/attachments/store into framework state, load `agent_state.json` onto `_EnteredCheckpointer`. Implemented as `_hydrate` (orchestrator) → `_hydrate_host` + `_hydrate_sandbox` (per sandbox). | "rehydrate" (use "hydrate" — the function handles both fresh and resume), "restore" (too narrow; restore is one step within hydrate) |

## Data types

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Checkpoint** (type) | Pydantic model for the per-checkpoint metadata persisted as a **checkpoint file** (`ckpt-NNNNN.json`). Carries `checkpoint_id`, `trigger`, `turn`, `created_at`, `duration_ms`, `size_bytes`, `host` (`SnapshotDetails`), `sandboxes` (mapping name → `SnapshotDetails`). Also the payload shape flattened into `CheckpointEvent` via multiple inheritance. | "CheckpointDetails" |

