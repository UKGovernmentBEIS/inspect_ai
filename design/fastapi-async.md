# FastAPI Endpoint Async Convention

## Rules

1. **`async def`** — endpoint awaits something. Runs on the event loop.
2. **`def`** — endpoint does sync blocking I/O (file reads, subprocess, etc.) and never awaits. FastAPI auto-runs it in a threadpool, keeping the event loop free.
3. **`async def` + `anyio.to_thread.run_sync`** — endpoint must await *and* do sync blocking I/O. The sync blocker is manually offloaded.
4. **`async def` with no awaits and no blocking** — fine as-is. Trivially fast, no reason to pay threadpool overhead.

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

- File/directory I/O (`open`, `read`, `exists`, `rename`, `iterdir`)
- `subprocess.Popen`, `send2trash`
- Sync database or KV store access
- Heavy CPU work or module introspection

## What does NOT count

- Returning a value, dict copy, pure computation
- Checking an in-memory variable

## When in doubt

If an endpoint has no awaits and you're unsure whether it blocks, use `def`. The threadpool overhead is negligible, and it's always safe — a non-blocking function runs fine in a thread. The only thing to avoid is paying threadpool cost for something you *know* is trivial.
