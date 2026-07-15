# FastAPI Endpoint Async Convention

## Rules

1. **`async def`** — endpoint awaits something. Runs on the event loop.
2. **`def`** — endpoint does sync blocking I/O (file reads, subprocess, etc.) and never awaits. FastAPI auto-runs it in a threadpool, keeping the event loop free.
3. **`async def` + `anyio.to_thread.run_sync`** — endpoint must await *and* do sync blocking I/O. The sync blocker is manually offloaded.
4. **`async def` with no awaits and no blocking** — fine as-is. Trivially fast, no reason to pay threadpool overhead.

## ⚠️ Critical exception: never threadpool *remote* `fsspec`

Rules 2 and 3 both run the endpoint body in a threadpool. **Do not use either for `fsspec` work on a remote filesystem** (s3/gcs/azure — i.e. `filesystem(path).is_async()`). Those backends' sync API runs coroutines on fsspec's **own** background event-loop thread and blocks the caller; nesting a threadpool over that internal threading can **deadlock**. This includes the sample buffer when it is filestore-backed.

For blocking remote I/O, use the async filesystem (`inspect_ai._util.asyncfiles.AsyncFilesystem`) from an `async def` endpoint — not `def` and not `to_thread`. `to_thread`/`def` remain fine for **known-local** fsspec (`LocalFileSystem` is plain sync, no background loop) and for genuinely fsspec-free blocking work (local `sqlite`, `subprocess`). See the warning in the repo `CLAUDE.md`.

## Why this matters

`async def` endpoints run directly on the asyncio event loop thread. A sync blocking call inside one blocks the *entire* loop — no other request can be served until it returns. FastAPI's auto-threadpool for `def` endpoints exists specifically to handle this.

## Decision tree

```
Does the endpoint await anything?
├─ No
│   ├─ Does sync blocking I/O? → def (auto-threadpooled)
│   └─ No blocking?            → async def (fine, trivially fast)
└─ Yes
    ├─ Also does sync blocking I/O? → async def + to_thread on blockers
    └─ No blocking?                  → async def (correct)
```

## What counts as sync blocking

- File/directory I/O (`open`, `read`, `exists`, `rename`, `iterdir`) — safe to threadpool when known-local, but if it may hit a *remote* `fsspec` backend see the critical exception above (use `AsyncFilesystem`, never `def`/`to_thread`)
- `subprocess.Popen`, `send2trash`
- Sync database or KV store access (local `sqlite` is threadpool-safe)
- Heavy CPU work or module introspection

## What does NOT count

- Returning a value, dict copy, pure computation
- Checking an in-memory variable

## When in doubt

If an endpoint has no awaits and you're unsure whether it blocks, use `def`. The threadpool overhead is negligible, and it's always safe — a non-blocking function runs fine in a thread. The only thing to avoid is paying threadpool cost for something you *know* is trivial.
