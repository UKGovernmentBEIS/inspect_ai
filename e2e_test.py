import subprocess, time, asyncio, json, glob, os, sys

OUT = "/home/rafaelcarvalho/code/inspect_ai/e2e_output.txt"
f = open(OUT, "w")


def log(msg):
    f.write(msg + "\n")
    f.flush()


proc = subprocess.Popen(
    [
        "python3",
        "-m",
        "inspect_ai._cli.main",
        "eval",
        "src/inspect_ai/_display/socket/test_task.py@interactive_counting",
        "--model",
        "mockllm/model",
        "--display=socket",
        "--max-samples=1",
    ],
    cwd="/home/rafaelcarvalho/code/inspect_ai",
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
log("Eval started, waiting for socket...")

sock_path = None
for i in range(20):
    time.sleep(1)
    socks = glob.glob("/tmp/inspect-*.sock")
    if socks:
        sock_path = max(socks, key=os.path.getmtime)
        log(f"Socket: {sock_path} ({i + 1}s)")
        break
    log(f"  waiting... {i + 1}s")

if not sock_path:
    log("NO SOCKET")
    proc.kill()
    f.close()
    sys.exit(1)


async def test():
    r, w = await asyncio.open_unix_connection(sock_path)
    for i in range(50):
        try:
            line = await asyncio.wait_for(r.readline(), timeout=3)
            if not line:
                log("CONN CLOSED")
                break
            d = json.loads(line)
            t = d.get("type")

            if t == "snapshot":
                pending = d.get("pending_inputs", [])
                log(f"snapshot: tasks={len(d.get('tasks', []))} pending={len(pending)}")
                for p in pending:
                    w.write(
                        (
                            json.dumps(
                                {
                                    "type": "input_response",
                                    "request_id": p["request_id"],
                                    "text": "yes",
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                    await w.drain()
                    log(f"  responded to {p['request_id']}")
            elif t == "print":
                log(f"PRINT: {d.get('message', '')}")
            elif t == "input_requested":
                log(f"INPUT_REQUESTED: {d.get('prompt', '')[:50]}")
                w.write(
                    (
                        json.dumps(
                            {
                                "type": "input_response",
                                "request_id": d["request_id"],
                                "text": "yes",
                            }
                        )
                        + "\n"
                    ).encode()
                )
                await w.drain()
                log("  responded")
            elif t == "eval_complete":
                log("EVAL_COMPLETE")
                break
            elif t in (
                "sample_start",
                "sample_end",
                "sample_complete",
                "input_resolved",
                "metrics_update",
            ):
                log(t)
            else:
                log(f"other: {t}")
        except asyncio.TimeoutError:
            log("TIMEOUT")
            break
    w.close()


try:
    asyncio.run(test())
except Exception as e:
    log(f"ERROR: {e}")

proc.terminate()
try:
    proc.wait(timeout=5)
except:
    proc.kill()
f.close()
