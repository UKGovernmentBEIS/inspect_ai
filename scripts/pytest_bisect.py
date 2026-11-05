#!/usr/bin/env python3
"""Replay a CI worker's test order and bisect it down to the polluting test.

CI runs the suite under pytest-xdist, so a failure caused by one test
corrupting process-global state for a later test on the same worker is
invisible in the log: it names the worker that failed but not what that worker
ran, or in what order. `--report-log` (pytest-reportlog) closes that gap — each
report it writes carries the `worker_id` xdist stamped on it, so the artifact
is a replayable per-worker execution order.

Given that artifact and a failing nodeid, this script

1. replays the failing worker's tests up to and including the victim, in order,
   in a single process, and checks the failure reproduces;
2. delta-debugs (Zeller's ddmin) the preceding tests down to a minimal set that
   still makes the victim fail — usually the single polluting test.

Both steps run plain `pytest` subprocesses, so any extra arguments the original
run needed (`--runslow`, `-p some_plugin`, ...) can be forwarded verbatim after
`--`.

Bisection assumes the failure reproduces deterministically. If the victim is
itself flaky, step 1 may pass by luck (reported as "did not reproduce"), or the
reduction may wander and return a larger set than the true cause.

Usage:

    scripts/pytest_bisect.py REPORT_LOG --failing NODEID [-- PYTEST_ARGS...]

Example:
    scripts/pytest_bisect.py test-report-log.jsonl
        --failing 'tests/test_extensions.py::test_hooks' -- --runslow --runapi
"""

from __future__ import annotations

import argparse
import gzip
import json
import shlex
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple, Sequence

# ---------------------------------------------------------------------------
# reading the recorded order
# ---------------------------------------------------------------------------


class Execution(NamedTuple):
    """One test as executed by one worker."""

    worker: str
    nodeid: str
    outcome: str


def _open_report_log(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        yield from f


def read_report_log(path: Path) -> list[Execution]:
    """Per-worker execution order, in the order the reports were written.

    A test produces up to three reports (setup/call/teardown). We key on first
    appearance so a test that never reached its call phase (hang, crash,
    setup error) still shows up in the order, and fold the phase outcomes into
    a single per-test outcome ("failed" wins, then "skipped").
    """
    order: list[tuple[str, str]] = []
    outcomes: dict[tuple[str, str], str] = {}
    for line in _open_report_log(path):
        line = line.strip()
        if not line:
            continue
        report = json.loads(line)
        if report.get("$report_type") != "TestReport":
            continue
        # Absent worker_id means the run was not distributed; treat the whole
        # session as one worker so replay still works.
        key = (report.get("worker_id") or "master", report["nodeid"])
        if key not in outcomes:
            order.append(key)
            outcomes[key] = "passed"
        outcome = report["outcome"]
        if outcome == "failed" or (outcome == "skipped" and outcomes[key] == "passed"):
            outcomes[key] = outcome
    return [Execution(w, n, outcomes[(w, n)]) for w, n in order]


class Worker(NamedTuple):
    """The tests that led up to a victim on the worker that ran it."""

    worker: str
    prefix: list[str]
    victim: str


def locate_victim(
    executions: Sequence[Execution], failing: str, worker: str | None
) -> Worker:
    by_worker: dict[str, list[str]] = defaultdict(list)
    for e in executions:
        by_worker[e.worker].append(e.nodeid)

    candidates = [
        w
        for w, nodeids in by_worker.items()
        if failing in nodeids and (worker is None or w == worker)
    ]
    if not candidates:
        known = ", ".join(sorted(by_worker)) or "none"
        raise SystemExit(
            f"nodeid {failing!r} does not appear in the report log"
            + (f" for worker {worker!r}" if worker else "")
            + f" (workers recorded: {known})"
        )
    if len(candidates) > 1:
        raise SystemExit(
            f"nodeid {failing!r} ran on multiple workers ({', '.join(sorted(candidates))}); "
            "pick one with --worker"
        )

    found = candidates[0]
    nodeids = by_worker[found]
    return Worker(found, nodeids[: nodeids.index(failing)], failing)


# ---------------------------------------------------------------------------
# running trials
# ---------------------------------------------------------------------------


@dataclass
class Runner:
    """Runs `pytest <tests> <victim>` and reports whether the victim failed."""

    victim: str
    pytest_args: Sequence[str]
    setup_command: str | None = None
    verbose: bool = False
    runs: int = 0
    invocations: int = 0
    seconds: float = 0.0
    setup_seconds: float = 0.0
    dropped: set[str] = field(default_factory=set)
    _tmp: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="bisect-")))

    def victim_fails(self, prefix: Sequence[str]) -> bool:
        log = self._tmp / f"trial-{self.runs}.jsonl"
        started = time.monotonic()
        proc = self._run(prefix, log)
        elapsed = time.monotonic() - started
        self.runs += 1
        self.seconds += elapsed

        outcome = self._victim_outcome(log)
        if outcome is None:
            print(
                f"  ! trial {self.runs}: victim produced no report "
                f"(pytest exit {proc.returncode}); treating as 'did not fail'",
                file=sys.stderr,
            )
            if self.verbose:
                print(proc.stdout[-4000:], file=sys.stderr)
        if self.verbose:
            print(
                f"  trial {self.runs}: {len(prefix)} preceding test(s) "
                f"-> victim {outcome or 'missing'} [{elapsed:.1f}s]"
            )
        return outcome == "failed"

    def _run(
        self, prefix: Sequence[str], log: Path
    ) -> subprocess.CompletedProcess[str]:
        """Run the trial, retrying once without nodeids this checkout lacks.

        A recording can name tests that were since renamed, removed or
        parametrized differently. pytest treats an unmatched nodeid argument as
        a usage error and runs nothing at all, so drop the reported ones and
        retry rather than mistaking it for "the victim passed".
        """
        selected = [t for t in prefix if t not in self.dropped]
        while True:
            if self.setup_command:
                setup_started = time.monotonic()
                setup = subprocess.run(self.setup_command, shell=True)
                if setup.returncode != 0:
                    raise SystemExit(
                        f"--setup-command failed (exit {setup.returncode}): "
                        f"{self.setup_command}"
                    )
                self.setup_seconds += time.monotonic() - setup_started
            self.invocations += 1
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                    "--continue-on-collection-errors",
                    *self.pytest_args,
                    # after the forwarded args, so a --report-log among them
                    # cannot redirect the log this trial reads back
                    f"--report-log={log}",
                    *selected,
                    self.victim,
                ],
                capture_output=True,
                text=True,
            )
            if self._missing_nodeids(proc.stderr, [self.victim]):
                raise SystemExit(
                    f"victim nodeid not found in this checkout: {self.victim}\n"
                    "The recording is stale, or the test was renamed, removed "
                    "or parametrized differently. Bisecting cannot proceed."
                )
            missing = self._missing_nodeids(proc.stderr, selected)
            if not missing:
                return proc
            print(
                f"  ! dropping {len(missing)} nodeid(s) not present in this "
                f"checkout (e.g. {sorted(missing)[0]})",
                file=sys.stderr,
            )
            self.dropped |= missing
            selected = [t for t in selected if t not in missing]

    @staticmethod
    def _missing_nodeids(stderr: str, selected: Sequence[str]) -> set[str]:
        """Nodeids pytest reported as `ERROR: not found:` (paths are absolute)."""
        if "ERROR: not found:" not in stderr:
            return set()
        lines = [line.strip() for line in stderr.splitlines()]
        return {t for t in selected if any(line.endswith(t) for line in lines)}

    def _victim_outcome(self, log: Path) -> str | None:
        if not log.exists():
            return None
        result: str | None = None
        for line in _open_report_log(log):
            line = line.strip()
            if not line:
                continue
            report = json.loads(line)
            if (
                report.get("$report_type") == "TestReport"
                and report["nodeid"] == self.victim
            ):
                if report["outcome"] == "failed":
                    result = "failed"
                elif result is None:
                    result = report["outcome"]
        return result


# ---------------------------------------------------------------------------
# delta debugging
# ---------------------------------------------------------------------------


def ddmin(candidates: Sequence[str], fails: "Runner") -> list[str]:
    """Smallest subset of `candidates` that still makes the victim fail.

    Zeller's ddmin. A plain binary search would be enough when exactly one test
    pollutes, but ddmin also handles the case where the failure needs a
    combination of earlier tests, and degenerates to binary search otherwise.
    Subsets keep their original relative order, since pollution is frequently
    order-sensitive.
    """
    current = list(candidates)
    granularity = 2
    while len(current) >= 2:
        chunks = _chunks(current, granularity)
        for chunk in chunks:
            if fails.victim_fails(chunk):
                current, granularity = chunk, 2
                break
        else:
            for chunk in chunks:
                complement = [t for t in current if t not in set(chunk)]
                if complement and fails.victim_fails(complement):
                    current = complement
                    granularity = max(granularity - 1, 2)
                    break
            else:
                if granularity >= len(current):
                    break
                granularity = min(granularity * 2, len(current))
    return current


def _chunks(items: Sequence[str], n: int) -> list[list[str]]:
    size, extra = divmod(len(items), n)
    out: list[list[str]] = []
    start = 0
    for i in range(n):
        stop = start + size + (1 if i < extra else 0)
        if stop > start:
            out.append(list(items[start:stop]))
        start = stop
    return out


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def _format(cmd: Iterable[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("report_log", type=Path, help="--report-log artifact from CI")
    parser.add_argument("--failing", required=True, help="nodeid of the failing test")
    parser.add_argument("--worker", help="worker id, if the nodeid ran on several")
    parser.add_argument(
        "--setup-command",
        help="shell command run before every trial, to restore whatever the "
        "previous run tore down (this suite's conftest, for instance, "
        "uninstalls tests/test_package on session finish)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="don't print a line per trial"
    )
    # Split on `--` ourselves: argparse re-parses options that follow it, so
    # forwarded flags like `-p freshworker` would be swallowed.
    argv = list(sys.argv[1:] if argv is None else argv)
    pytest_args: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, pytest_args = argv[:split], argv[split + 1 :]
    args = parser.parse_args(argv)
    args.pytest_args = pytest_args

    executions = read_report_log(args.report_log)
    if not executions:
        raise SystemExit(f"no test reports found in {args.report_log}")
    worker = locate_victim(executions, args.failing, args.worker)

    workers = sorted({e.worker for e in executions})
    print(
        f"report log:  {args.report_log} ({len(executions)} test runs, {len(workers)} workers)"
    )
    print(f"victim:      {worker.victim}")
    print(
        f"worker:      {worker.worker} ({len(worker.prefix)} tests ran before the victim)"
    )
    print()

    runner = Runner(
        worker.victim,
        args.pytest_args,
        setup_command=args.setup_command,
        verbose=not args.quiet,
    )
    started = time.monotonic()

    print("[1/3] victim on its own (control) ...")
    if runner.victim_fails([]):
        print(
            "\nThe victim fails with nothing before it, so this is not "
            "cross-test pollution. Debug the test directly."
        )
        return _summary(runner, started, 1)

    print("[2/3] replaying the worker's order ...")
    if not runner.victim_fails(worker.prefix):
        print(
            "\nDID NOT REPRODUCE: the victim passes even after replaying every "
            "test that ran before it on this worker.\n"
            "The failure likely depends on something the recorded order does "
            "not capture — a test on a different worker, the worker count, "
            "timing/concurrency, or an environment difference from CI.\n"
            "Try: rerun with the CI python and the CI extra pytest args, or "
            "reproduce under `-n <same worker count>`."
        )
        return _summary(runner, started, 1)

    print(f"[3/3] bisecting {len(worker.prefix)} preceding tests ...")
    culprits = ddmin(worker.prefix, runner)

    print(f"\nMinimal set that reproduces the failure ({len(culprits)} test(s)):")
    for c in culprits:
        print(f"  {c}")
    print("\nReproduce with:")
    print(f"  {_format(['pytest', *args.pytest_args, *culprits, worker.victim])}")
    return _summary(runner, started, 0)


def _summary(runner: Runner, started: float, status: int) -> int:
    setup = (
        f" ({runner.setup_seconds:.1f}s of it in --setup-command)"
        if runner.setup_seconds
        else ""
    )
    retries = (
        f" ({runner.invocations - runner.runs} re-run after dropping stale nodeids)"
        if runner.invocations != runner.runs
        else ""
    )
    print(
        f"\n{runner.runs} trials / {runner.invocations} pytest invocations{retries}, "
        f"{time.monotonic() - started:.1f}s wall clock{setup}."
    )
    return status


if __name__ == "__main__":
    sys.exit(main())
