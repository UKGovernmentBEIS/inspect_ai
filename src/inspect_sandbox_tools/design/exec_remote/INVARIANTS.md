# exec_remote model: rules, abstractions, limits

## Guarantee

Once the host calls `kill()`, it sends no new poll and no poll retry, and the
iterator ends only after the one shared kill request has finished and its
output has been yielded. No caller's cancellation abandons that request. The
guest reports a terminal poll, or retires a job, only after termination has
finished. Readers are never cancelled while the leader runs. The host takes
each output chunk once, in emission order, and never drops queued output.

This does not say that readers reach EOF after termination: a reader blocked on
a full job buffer when the leader exits is cancelled after 1 s and its output
is lost (F2).

## The five races

| # | Race | Rules that break in `buggy/` | Fix (actions marked `FIXED`) |
|---|---|---|---|
| 1 | Poll or poll retry after a local kill; the iterator ends before the kill's output | `NoPollAfterLocalStop`, `NoMissingJobRetryAfterStop`, `IteratorNeverFails`, `IteratorEndsDrained`, `IteratorStoppedAfterRpc` | The iterator checks the stop and queued output before every poll and before each retry send. A poll error after a stop ends iteration through the stop. The iterator waits for the stop before it ends. |
| 2 | A second `kill()` returns while the first one's request runs; cancelling the first abandons it | `KillReturnJoinsStop`, `StopNeverAbandoned`, `IteratorStoppedAfterRpc` | One stop operation per process. The first `kill()` starts it, later calls wait for it, and a caller's cancellation does not abandon it. |
| 3 | The guest reports `killed` and retires the job while termination runs | `TerminalPollAfterTermination`, `RetireOnlyAfterTermination`, `ReadersCutOnlyAfterExit`, `NoGuestOutputLoss` | `Job.poll` waits for a termination in progress before its terminal drain. The handler answers from the Job it took. |
| 4 | Overlapping poll, stdin and kill replies duplicate output or lower `_last_seq` | `SeqMonotonic`, `NoDuplicateEvent`, `OutputSequenceMonotone` | Replies carry each held chunk with its seq. The host takes only chunks above `_last_seq` and never lowers it. |
| 5 | A poll reply replaces output a concurrent reply queued | `NoEventLoss`, `OutputSequenceMonotone` | Every reply's output is appended through one merge path. |

## Invariants

| Invariant | Rule |
|---|---|
| `TypeOK` | Variable domains. |
| `NoPollAfterLocalStop` | No poll (new or retry) is sent after the host requested a stop. |
| `NoMissingJobRetryAfterStop` | No poll retry is sent after a stop, including a stop requested during the retry backoff. |
| `IteratorNeverFails` | The iterator never raises a poll error (in the model a poll fails only after a stop, a terminal reply, or fewer transient errors than the retry limit). |
| `IteratorEndsDrained` | The iterator ends only with nothing queued. |
| `IteratorStoppedAfterRpc` | If a stop request was started, the iterator ends only after it finished. |
| `KillReturnJoinsStop` | `kill()` returns normally only after the shared stop request finished, or once the process is known completed. |
| `StopNeverAbandoned` | A caller's cancellation never abandons the stop request. |
| `TerminalPollAfterTermination` | No terminal poll reply is built while termination runs. |
| `RetireOnlyAfterTermination` | No retired job has a termination still running. |
| `ReadersCutOnlyAfterExit` | Readers are never cancelled while the leader runs. |
| `NoGuestOutputLoss` | No written item is dropped. |
| `OutputConserved` | Every written item is in exactly one of: pipe, job buffer, acked buffer, dropped. |
| `KeyStepsLegal` | The controller key moves only none → spawning → live → retired; a refused key never spawns. |
| `KillKeySettles` | After a `kill_key` returns, the leader and its termination are not running. |
| `KillKeyJoinsTermination` | No `kill_key` reply is built while termination runs. |
| `SeqMonotonic` | Host `_last_seq` never decreases. |
| `NoDuplicateEvent` | No output item is yielded or queued twice. |
| `OutputSequenceMonotone` | Yielded-then-queued output is in emission order and skips nothing that reached the acked buffer before it. |
| `NoEventLoss` | Every item in a processed reply is yielded or still queued. |
| `CompletedDeliversAll` | If the iterator ended on `completed`, every written item was yielded. |

Liveness (`ExecRemote-liveness.cfg`): `StopTakesEffect`, `KillCallsReturn`,
`IteratorEnds`, `AbortedStartSettles`, `KeyedKillReturns`. They assume
messages are delivered and termination succeeds; they do not mean a remote
kill is confirmed.

## Abstractions

- One job and one host process object. The network is a set of messages, so
  replies are processed in any order; at most one message of each type and
  caller is in flight. The only transport failure is a transient poll
  `RuntimeError`.
- Output items `1..MaxOut` on one stream (stderr behaves the same). A reply
  carries the held chunks, each with its seq. Empty output gets no chunk and
  does not advance the guest seq, as in `Job._collect`.
- Readers: unbounded pipe into a job buffer of `BufCap` items; the 1 s reader
  cutoff is `WaitReaders`. The per-poll output cap is not modeled.
- Not modeled: `close_stdin`, the server poll wait, server restart, spawn and
  stdin-initialization failure, repeated starts, iterator cancellation, poll
  timeouts and `poll_timeout_recovery`, kill failures other than "job not
  live", the `kill_key` timeout, termination errors, the completion event's
  exit code.

## How the code refines the model

- `kill()`: the first caller sends the request in a task it waits for to the
  end (`_complete_before_cancelling`), so its cancellation is raised once the
  request finishes. The model also lets the first caller stop waiting at once;
  the code has fewer behaviors, so the rules still hold.
- A poll `TimeoutError` after `kill()` (not modeled) waits for the stop, then
  ends iteration if the kill reached the sandbox, and is raised otherwise, as
  `poll_timeout_recovery` documents.

## Known limits

- **F1.** If a keyed kill (`kill_key`) could reach the guest after start and
  before the host's kill (`KeyedKillAnyTime = TRUE`), the iterator can end
  before an in-flight stdin reply queues its output (`IteratorEndsDrained`).
  No host path sends such a keyed kill, so the config keeps it after the host
  kill.
- **F2.** With a job buffer smaller than the unread output when the leader
  exits (`BufCap = 1`), the reader cutoff drops output
  (`NoGuestOutputLoss`, `CompletedDeliversAll`). The config uses
  `BufCap = MaxOut`. Draining while waiting for the readers would fix it.
