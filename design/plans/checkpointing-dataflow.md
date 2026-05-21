# Checkpointing dataflow

Where each piece of checkpointable data originates, where it's
serialized or captured, where restic backs it up, and (when the
destination is remote) where it's transferred to. Vocabulary is
defined in
[`src/inspect_ai/util/_checkpoint/UBIQUITOUS_LANGUAGE.md`](../../src/inspect_ai/util/_checkpoint/UBIQUITOUS_LANGUAGE.md);
this doc reuses those terms without redefining them.

## Example setup

```python
CheckpointConfig(
    trigger=TurnInterval(every=10),
    sandbox_paths={
        "default": ["/root", "/workspace"],
        "tools":   ["/opt/agent-state"],
    },
    checkpoints_location=...,   # see each scenario
)
```

Log path: `logs/<eval-name>.eval`. Single sample, id `7`, epoch `0`.
The diagrams trace the **N-th fire** of the sample.

In both scenarios the in-memory inputs are identical:

- Live transcript events accumulated since the previous fire
- Current `Store` contents
- Attachments captured by the transcript during the cycle
- Values returned by every `Checkpointer.track(...)` callback
- The two configured sandboxes' in-container restic repos at
  `/opt/inspect-restic/repo`, holding snapshots from earlier fires.

What differs: **where the bytes land**, and **whether the host
process does anything after writing the local checkpoint file**.

---

## Scenario 1 — local destination

```python
checkpoints_location=None                 # default: sibling of the log
# or
checkpoints_location="/scratch/ckpts"     # explicit local override
```

No staging dir. Restic writes directly into the sample checkpoints
dir; checkpoint files land directly into it; nothing is shipped anywhere.

### Notes (local)

- **Concurrency.** The host context lane and the two sandbox lanes
  run concurrently via `tg_collect`. Within a sandbox lane the steps
  are sequential (the egress diff sees what the backup just wrote).
- **Commit point.** The checkpoint file (`ckpt-NNNNN.json`) is
  written last. Restic snapshots written but never matched by a
  checkpoint file are orphans cleaned up on the next resume.
- **The "in-container restic" hop exists in the local case too.**
  It exists because the in-sandbox restic has no creds and the
  sandbox is a privilege boundary — not because the destination is
  remote.

---

## Scenario 2 — remote sample checkpoints dir

```python
checkpoints_location="s3://my-bucket/ckpts/"
```

Restic writes to a host-local **sample staging dir** under
`inspect_cache_dir("checkpoints")`. At the end of each fire,
**host_egress** ships new files to the destination via
`AsyncFilesystem`. The context subdir is restic's input — it never
leaves the host. The manifest is host-only bookkeeping — never
shipped.

### Notes (remote)

- **Restic never sees the destination URL.** All restic invocations
  target local paths under the staging dir. This sidesteps restic's
  narrow AWS auth (no SSO, no `~/.aws/config`, no assume-role);
  inspect's `AsyncFilesystem` uses the full boto3 credential chain
  for the host-egress shipment.
- **Two checkpoint file writes.** The local checkpoint file in the
  staging dir is an intermediate commit; the remote checkpoint file
  is the cross-machine commit point — it ships last in the safe
  upload order, so its presence at the destination signals "this
  checkpoint is durable."
- **`context/` never crosses the boundary.** Restic snapshots its
  contents into `restic/host/`; only the snapshot ships, not the raw
  JSON. Same data, different shape.
- **`.egress-manifest.txt` never ships.** It's the host-local diff
  cache that records what's already at the destination. Lost on
  resume; rebuilt by re-deriving from the destination contents.
- **Failure recovery**. A host_egress crash partway through →
  destination has some new files but the manifest didn't update →
  next fire's diff over-reports new files and re-ships completes
  idempotently (restic data files are content-addressed; checkpoint
  files overwrite cleanly). The local checkpoint file is intact, so
  the local restic state is unaffected.

---

## What's deliberately not in this doc

- **Resume read path.** The destination layout is the source of
  truth for resume; the resume-side hydrate code reads it (today's
  implementation handles the local case; the remote-resume read
  path is a separate work item).
- **Retention.** Staging-dir cleanup post-eval and destination
  retention are tracked separately.
- **Sandbox privilege model.** Why the in-sandbox repo and the
  in-sandbox tarball are root-owned mode-0700 is covered in
  `checkpointing-working.md` §4h. Both scenarios inherit it
  unchanged.
