# exec_remote TLA+ model

`ExecRemote.tla` models one `exec_remote` job end to end: the host
`ExecRemoteProcess` (`src/inspect_ai/util/_sandbox/exec_remote.py`), and the
guest `Controller`, `Job` and `AckedChunkBuffer`
(`src/inspect_sandbox_tools/src/inspect_sandbox_tools/_remote_tools/_exec_remote/`).
TLC checks it with every reply order, concurrent `kill()` callers, cancelled
callers, retries and output arriving at any time.

`INVARIANTS.md` lists the rules, the abstractions and the known limits.

| File | What |
|---|---|
| `ExecRemote.tla` | The code as implemented. Actions changed from `buggy/` are marked `FIXED`. |
| `ExecRemote.cfg` | Main config: all safety invariants. |
| `ExecRemote-liveness.cfg` | Main config plus the temporal properties. |
| `buggy/ExecRemote.tla`, `buggy/ExecRemote.cfg` | The code before the stop and output fixes, at `94ef6eacc` (main, #6275), with the same invariants. Kept to show what each invariant catches. Defect sites are marked `BUGGY`. |

## Changing exec_remote

A change to the stop, poll, retry, termination or output behavior of
`exec_remote`, on the host or in the guest, needs a matching edit to
`ExecRemote.tla` and a TLC run of `ExecRemote.cfg` recorded below (or in the
PR). If the change breaks an invariant on purpose, change the invariant in both
modules and say why.

## Run TLC

TLC 2.19 (`tla2tools.jar` from the TLA+ tools releases), Java 11 or later:

```sh
cd src/inspect_sandbox_tools/design/exec_remote
java -cp tla2tools.jar tlc2.TLC -workers auto -config ExecRemote.cfg ExecRemote.tla
java -cp tla2tools.jar tlc2.TLC -workers auto -config ExecRemote-liveness.cfg ExecRemote.tla
cd buggy && java -cp tla2tools.jar tlc2.TLC -workers auto -config ExecRemote.cfg ExecRemote.tla
```

TLC writes a `states/` directory beside the module; do not commit it.

## Recorded runs

Constants: `Killers = {k1, k2}, MaxOut = 2, MaxStdin = 1, MaxRetry = 2,
MaxFail = 1, BufCap = 2, KeyedKillAnyTime = FALSE`.

| Date | Model, config | Result |
|---|---|---|
| 2026-11-05 | `ExecRemote.tla`, `ExecRemote.cfg` | All 21 invariants hold, no deadlock. 1,039,393 distinct states, depth 41. |
| 2026-11-05 | `ExecRemote.tla`, `ExecRemote-liveness.cfg` | All 21 invariants and the five temporal properties hold. 1,039,393 distinct states. |
| 2026-11-05 | `buggy/ExecRemote.tla`, `buggy/ExecRemote.cfg` | Breaks at once (`IteratorStoppedAfterRpc`: the iterator ends before the kill request finished). Earlier per-invariant runs also broke `KillReturnJoinsStop`, `StopNeverAbandoned`, `NoPollAfterLocalStop`, `NoMissingJobRetryAfterStop`, `IteratorNeverFails`, `IteratorEndsDrained`, `TerminalPollAfterTermination`, `RetireOnlyAfterTermination`, `ReadersCutOnlyAfterExit`, `NoGuestOutputLoss`, `SeqMonotonic`, `NoDuplicateEvent`, `OutputSequenceMonotone`, `NoEventLoss` and `CompletedDeliversAll`. |

The `buggy/` row lists invariant names from before the rename of
`IteratorNeverFails` to `IteratorFailsOnlyAfterFailedKill`.
