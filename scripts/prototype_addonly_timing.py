"""PROTOTYPE: time the boundary writes of tamper-evident eval logs.

Against a LOCAL EMULATOR (moto server on 127.0.0.1), not real S3: the times
show the prototype's own cost (reading buffer rows, JSON, boto3 in a worker
thread, HTTP to localhost), not S3 latency.

Runs the scripted agent eval (tests/test_helpers/addonly_agents.py) with and
without the add-only store, validates the store, and prints:
- the time each boundary write waited (row read + JSON + put), and the put alone;
- record sizes;
- eval wall time with and without the store;
- the records of one sample, to show what each boundary stored.

Usage (from the repo root): PYTHONPATH=tests python scripts/prototype_addonly_timing.py [--samples N] [--epochs N]
"""

import argparse
import json
import os
import statistics
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from test_helpers.addonly_agents import agent_task, run
from test_helpers.addonly_moto import BUCKET, moto_addonly_store

from inspect_ai.log._addonly._records import SampleRecord
from inspect_ai.log._addonly._store import AddOnlyStore
from inspect_ai.log._addonly._validate import validate_store
from inspect_ai.log._addonly._writer import SampleRecordWriter

write_times: list[float] = []
put_times: list[float] = []
put_sizes: list[int] = []
# sample record puts in flight per sample attempt, and how many started while
# another put of the same attempt was in flight
in_flight: Counter[str] = Counter()
overlapped: list[bool] = []


def timed(
    fn: Callable[..., Awaitable[None]], times: list[float]
) -> Callable[..., Awaitable[None]]:
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        start = time.perf_counter()
        await fn(*args, **kwargs)
        times.append(time.perf_counter() - start)

    return wrapper


def summary(name: str, values: list[float], scale: float, unit: str) -> str:
    ordered = sorted(values)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    return (
        f"{name}: n={len(values)} median={statistics.median(values) * scale:.2f}{unit} "
        f"p95={p95 * scale:.2f}{unit} max={max(values) * scale:.2f}{unit}"
    )


def describe(row_data: str) -> str:
    event = json.loads(row_data)
    kind = event["event"]
    detail = event.get("function") or event.get("name") or ""
    pending = " pending" if event.get("pending") else ""
    return f"{kind}{':' + detail if detail else ''}{pending}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=2)
    args = parser.parse_args()

    original_write = SampleRecordWriter.write
    original_put = AddOnlyStore.put

    async def put(self: AddOnlyStore, key: str, body: bytes) -> None:
        put_sizes.append(len(body))
        attempt, _, seq = key.rpartition("/")
        if not seq.isdigit():
            await timed(original_put, put_times)(self, key, body)
            return
        overlapped.append(in_flight[attempt] > 0)
        in_flight[attempt] += 1
        try:
            await timed(original_put, put_times)(self, key, body)
        finally:
            in_flight[attempt] -= 1

    with (
        patch.object(SampleRecordWriter, "write", timed(original_write, write_times)),
        patch.object(AddOnlyStore, "put", put),
        moto_addonly_store() as store,
        tempfile.TemporaryDirectory() as tmp,
    ):
        os.environ.update(store.env(store.evalhost))

        # warm up (imports, first eval), then without the store, for wall time
        run(agent_task(1, 2), Path(tmp, "warmup"))
        start = time.perf_counter()
        run(agent_task(args.epochs, args.samples), Path(tmp, "plain"), max_samples=10)
        plain_seconds = time.perf_counter() - start

        start = time.perf_counter()
        log = run(
            agent_task(args.epochs, args.samples),
            Path(tmp, "store"),
            max_samples=10,
            tamper_evident_store=store.url,
        )
        store_seconds = time.perf_counter() - start
        assert log.status == "success", log.error

        store.require_if_none_match_policy()
        report = validate_store(
            store.url, str(Path(tmp, "store")), client=store.client(store.validator)
        )

        s3 = store.client(store.validator)
        sample_prefix = f"{store.prefix}/{log.eval.eval_id}/s0.1/1/"
        keys = sorted(
            (
                o["Key"]
                for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=store.prefix)[
                    "Contents"
                ]
                if o["Key"].startswith(sample_prefix)
                and o["Key"].rsplit("/", 1)[1].isdigit()
            ),
            key=lambda k: int(k.rsplit("/", 1)[1]),
        )
        layout = [
            SampleRecord.model_validate_json(
                s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            )
            for key in keys
        ]

    print("Against a local moto server (127.0.0.1), NOT real S3.")
    print(
        f"Eval: {args.samples} samples x {args.epochs} epochs, max_samples=10, "
        "mockllm, react agent, 2 sub-agents at once."
    )
    print(summary("boundary wait (row read + JSON + put)", write_times, 1000, "ms"))
    print(summary("put only", put_times, 1000, "ms"))
    print(summary("record size", [float(s) for s in put_sizes], 1 / 1024, "KiB"))
    print(
        f"sample record puts started while another put of the same sample was "
        f"in flight: {sum(overlapped)} of {len(overlapped)}"
    )
    print(
        f"wall time: {plain_seconds:.2f}s without store, "
        f"{store_seconds:.2f}s with store"
    )
    print(
        f"validator: {len(report.findings)} finding(s), "
        f"{report.samples_compared} sample(s) compared"
    )
    for finding in report.findings:
        print(f"  {finding.kind} {finding.key}: {finding.message}")
    print("\nRecords of sample s0, epoch 1 (each line: one write):")
    for record in layout:
        events = ", ".join(describe(row.data) for row in record.rows.events)
        print(f"  {record.seq}: {events}")


if __name__ == "__main__":
    main()
