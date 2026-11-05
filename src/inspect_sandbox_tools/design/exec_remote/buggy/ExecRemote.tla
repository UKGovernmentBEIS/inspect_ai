---------------------------- MODULE ExecRemote ----------------------------
(***************************************************************************)
(* exec_remote, ONE job, as the code behaves at                             *)
(* ec29c121852f14b276bba03fcc04ede546e60719 ("buggy" model).                *)
(*                                                                         *)
(* Host  : ExecRemoteProcess  (src/inspect_ai/util/_sandbox/exec_remote.py) *)
(* Guest : Controller + Job + AckedChunkBuffer                              *)
(*         (inspect_sandbox_tools/_remote_tools/_exec_remote/)              *)
(*                                                                         *)
(* Abstractions are explained in ../INVARIANTS.md.  In short:              *)
(*  - The network is a set of messages, so replies can arrive in any order.*)
(*    At most one message of each type and caller is in flight.            *)
(*  - Output items are numbered 1..MaxOut in emission order (one stream).  *)
(*  - Output moves: process write -> pipe (gPipe) -> reader -> bounded     *)
(*    job buffer (gBuf, BufCap items) -> AckedChunkBuffer (gHeld).         *)
(*  - poll is two steps: entry captures the live Job, resume replies.      *)
(*    kill / kill_key wait for spawn or the shared termination (gWaiters). *)
(*    stdin and close_stdin handlers stay atomic.                          *)
(*  - A push of empty output does not advance the guest seq (renumbering  *)
(*    only; keeps the state space finite).                                 *)
(*                                                                         *)
(* Revision r1 added: poll capture/resume, keyed kill                     *)
(* after start, retry backoff, reader pipe and bounded buffer, output      *)
(* order and kill_key join invariants.                                     *)
(*                                                                         *)
(* The INVARIANTS section is identical in buggy/ and fixed/.               *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Killers,    \* host tasks that may call kill() concurrently
    MaxOut,     \* number of output items the process may emit
    MaxStdin,   \* number of write_stdin() calls the host may make
    MaxRetry,   \* RuntimeError retries per poll() call (real code: up to 5 attempts)
    MaxFail,    \* transient (non-missing-job) poll errors the transport may raise
    BufCap,     \* job buffer capacity in items (BoundedByteBuffer)
    KeyedKillAnyTime  \* TRUE: the keyed kill after start may reach the guest
                      \* before the host's kill; FALSE: only after it

NoKiller == "none"
NoPoll == 99           \* gPoll value when no poll handler holds a captured Job
Items == 1..MaxOut
Max(a, b) == IF a >= b THEN a ELSE b

VARIABLES
    \* ---- network ----
    net,            \* set of in-flight request/reply messages
    \* ---- host: start ----
    hStart,         \* "waiting" | "started" | "killingKey" | "aborted"
    \* ---- host: iterator (__anext__ loop) ----
    hIter,          \* "unstarted" | "idle" | "polling" | "sleep" | "retryWait" | "done" | "failed"
    hRetries,       \* RuntimeError retries used by the current poll() call
    \* ---- host: stop ----
    hStopReq,       \* buggy: ExecRemoteProcess._killed
    hStopRpc,       \* "none" | "queued" | "sent" | "finished" | "abandoned"
    hStopOwner,     \* buggy: the kill() caller that owns the RPC
    hRemoteStopped, \* host learned that the remote job stopped (kill ok / poll "killed")
    hCaller,        \* [Killers -> "idle" | "waiting" | "returned" | "cancelled"]
    hXKK,           \* keyed kill issued after start: "idle" | "sent" | "returned"
    \* ---- host: process / output ----
    hCompleted,     \* ExecRemoteProcess._completed
    hLastSeq,       \* ExecRemoteProcess._last_seq
    hPending,       \* ExecRemoteProcess._pending_events (items)
    hDelivered,     \* items yielded to the consumer, in order
    hGot,           \* every item carried by a reply the host processed
    hStdinSent,     \* write_stdin() calls made
    hStdinBusy,     \* a write_stdin() RPC is in flight
    \* ---- guest: controller key ----
    gReg,           \* "none" | "spawning" | "live" | "retired"
    gRefused,       \* key in Controller._refused_keys
    \* ---- guest: job ----
    gProc,          \* "none" | "running" | "exited"   (the OS leader process)
    gKilled,        \* Job._killed
    gTerm,          \* Job._termination: "none" | "running" | "done"
    gReaders,       \* "open" | "eof" | "cancelled"  (reader tasks)
    gEmitted,       \* items the process has written
    gPipe,          \* items written to the pipe, not yet in the job buffer
    gBuf,           \* items in the bounded job buffers, not yet drained
    gSeq,           \* AckedChunkBuffer._seq
    gHeld,          \* AckedChunkBuffer._held as a set of [seq, items]
    gWaiters,       \* kill / kill_key handlers waiting for spawn or termination
    gPoll,          \* ack of the poll handler that captured the Job, or NoPoll
    gFails,         \* transient poll errors raised so far
    \* ---- history (only read by invariants) ----
    hMaxSeq,        \* highest seq the host ever received
    pollAfterStop,  \* a poll request (new or retry) was sent after local stop
    retryAfterStop, \* a poll retry was sent after local stop
    gTermPoll,      \* a terminal poll reply was built while termination ran
    gDropped,       \* written items that will never reach the job buffer
    gCutLive,       \* readers were cancelled while the leader still ran
    gTaken,         \* items pushed into the AckedChunkBuffer
    kkEarly,        \* a kill_key reply was built while termination ran
    gKeyStep        \* last controller key step <<from, to, refusedBefore>>

hostVars  == <<hStart, hIter, hRetries, hStopReq, hStopRpc, hStopOwner,
               hRemoteStopped, hCaller, hXKK, hCompleted, hLastSeq, hPending,
               hDelivered, hGot, hStdinSent, hStdinBusy>>
guestVars == <<gReg, gRefused, gProc, gKilled, gTerm, gReaders, gEmitted,
               gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails>>
histVars  == <<hMaxSeq, pollAfterStop, retryAfterStop, gTermPoll, gDropped,
               gCutLive, gTaken, kkEarly, gKeyStep>>
vars == <<net, hostVars, guestVars, histVars>>

-----------------------------------------------------------------------------
(* Messages: one record shape for requests and replies.                    *)
(* For kill_key the ack field tags the caller: 0 = start abort,            *)
(* 1 = keyed kill after start.                                             *)
Req(t, ack) == [dir |-> "req", type |-> t, ack |-> ack, ok |-> TRUE,
                seq |-> 0, chunks |-> {}, state |-> "none"]
Rep(t, ok, seq, chunks, st) ==
               [dir |-> "rep", type |-> t, ack |-> 0, ok |-> ok,
                seq |-> seq, chunks |-> chunks, state |-> st]
KKRep(tag) == [dir |-> "rep", type |-> "killkey", ack |-> tag, ok |-> TRUE,
               seq |-> 0, chunks |-> {}, state |-> "none"]
IsReq(m, t) == m.dir = "req" /\ m.type = t
IsRep(m, t) == m.dir = "rep" /\ m.type = t
ItemsOf(m)  == UNION {c.items : c \in m.chunks}

RECURSIVE SeqOf(_)
SeqOf(S) == IF S = {} THEN << >>
            ELSE LET m == CHOOSE x \in S : \A y \in S : x <= y
                 IN <<m>> \o SeqOf(S \ {m})

Range(s) == {s[i] : i \in 1..Len(s)}

(* Guest AckedChunkBuffer: push(items) then collect(ack).                  *)
NewSeq(items) == IF items = {} THEN gSeq ELSE gSeq + 1
HeldAfter(items, ack) ==
    {c \in gHeld \cup (IF items = {} THEN {}
                       ELSE {[seq |-> gSeq + 1, items |-> items]}) : c.seq > ack}

(* Job._state *)
JobState == IF gKilled THEN "killed"
            ELSE IF gProc = "exited" THEN "completed" ELSE "running"

SetKey(to) == gReg' = to /\ gKeyStep' = <<gReg, to, gRefused>>

(* Job._terminate_group started by the first kill; later kills join it.    *)
StartTermination ==
    IF gTerm = "none"
    THEN IF gProc = "running"
         THEN gKilled' = TRUE /\ gTerm' = "running" /\ UNCHANGED gProc
         ELSE gTerm' = "done" /\ UNCHANGED <<gKilled, gProc>>
    ELSE UNCHANGED <<gTerm, gKilled, gProc>>

(* Job._wait_for_readers: readers move pipe data into the bounded buffer   *)
(* until it is full; they reach EOF only if the leader exited and the pipe *)
(* is empty.  Otherwise the 1 s cutoff cancels them and the rest of the    *)
(* pipe is dropped.  Nothing drains the buffer during the wait (the drain  *)
(* follows it), so a reader blocked on a full buffer is cancelled even     *)
(* after the leader exited.                                                *)
Lowest(S, k) == {x \in S : Cardinality({y \in S : y < x}) < k}
Moved   == IF gReaders = "open" THEN Lowest(gPipe, BufCap - Cardinality(gBuf)) ELSE {}
WaitBuf == gBuf \cup Moved
WaitReaders ==
    IF gReaders # "open"
    THEN UNCHANGED <<gReaders, gPipe, gDropped, gCutLive>>
    ELSE LET rest == gPipe \ Moved
         IN /\ gPipe' = {}
            /\ IF gProc = "exited" /\ rest = {}
               THEN gReaders' = "eof" /\ UNCHANGED <<gDropped, gCutLive>>
               ELSE /\ gReaders' = "cancelled"
                    /\ gDropped' = gDropped \cup rest
                    /\ gCutLive' = (gCutLive \/ gProc = "running")

(* Drain the buffer (after any reader wait), push, collect(ack).          *)
DrainPush(items, ack) ==
    /\ gBuf' = {}
    /\ gSeq' = NewSeq(items)
    /\ gHeld' = HeldAfter(items, ack)
    /\ gTaken' = gTaken \cup items

-----------------------------------------------------------------------------
Init ==
    /\ net = {Req("start", 0)}
    /\ hStart = "waiting"
    /\ hIter = "unstarted"
    /\ hRetries = 0
    /\ hStopReq = FALSE
    /\ hStopRpc = "none"
    /\ hStopOwner = NoKiller
    /\ hRemoteStopped = FALSE
    /\ hCaller = [k \in Killers |-> "idle"]
    /\ hXKK = "idle"
    /\ hCompleted = FALSE
    /\ hLastSeq = 0
    /\ hPending = << >>
    /\ hDelivered = << >>
    /\ hGot = {}
    /\ hStdinSent = 0
    /\ hStdinBusy = FALSE
    /\ gReg = "none"
    /\ gRefused = FALSE
    /\ gProc = "none"
    /\ gKilled = FALSE
    /\ gTerm = "none"
    /\ gReaders = "open"
    /\ gEmitted = 0
    /\ gPipe = {}
    /\ gBuf = {}
    /\ gSeq = 0
    /\ gHeld = {}
    /\ gWaiters = {}
    /\ gPoll = NoPoll
    /\ gFails = 0
    /\ hMaxSeq = 0
    /\ pollAfterStop = FALSE
    /\ retryAfterStop = FALSE
    /\ gTermPoll = FALSE
    /\ gDropped = {}
    /\ gCutLive = FALSE
    /\ gTaken = {}
    /\ kkEarly = FALSE
    /\ gKeyStep = <<"none", "none", FALSE>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Guest: OS process, pipe, readers, termination                            *)
(***************************************************************************)
Emit ==       \* the process writes one item to its pipe
    /\ gProc = "running" /\ gEmitted < MaxOut
    /\ gEmitted' = gEmitted + 1
    /\ IF gReaders = "open"
       THEN gPipe' = gPipe \cup {gEmitted + 1} /\ UNCHANGED gDropped
       ELSE gDropped' = gDropped \cup {gEmitted + 1} /\ UNCHANGED gPipe
    /\ UNCHANGED <<net, hostVars, gReg, gRefused, gProc, gKilled, gTerm,
                   gReaders, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails,
                   hMaxSeq, pollAfterStop, retryAfterStop, gTermPoll, gCutLive,
                   gTaken, kkEarly, gKeyStep>>

ReaderRead == \* a reader task moves the oldest pipe item into a buffer with room
    /\ gReaders = "open" /\ gPipe # {} /\ Cardinality(gBuf) < BufCap
    /\ LET x == CHOOSE i \in gPipe : \A j \in gPipe : i <= j
       IN gPipe' = gPipe \ {x} /\ gBuf' = gBuf \cup {x}
    /\ UNCHANGED <<net, hostVars, gReg, gRefused, gProc, gKilled, gTerm,
                   gReaders, gEmitted, gSeq, gHeld, gWaiters, gPoll, gFails,
                   histVars>>

ProcExit ==   \* the leader exits on its own (may race with termination)
    /\ gProc = "running"
    /\ gProc' = "exited"
    /\ UNCHANGED <<net, hostVars, gReg, gRefused, gKilled, gTerm, gReaders,
                   gEmitted, gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails,
                   histVars>>

TermFinish == \* SIGTERM/SIGKILL took effect
    /\ gTerm = "running"
    /\ gTerm' = "done" /\ gProc' = "exited"
    /\ UNCHANGED <<net, hostVars, gReg, gRefused, gKilled, gReaders, gEmitted,
                   gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails, histVars>>

(***************************************************************************)
(* Guest: Controller handlers                                               *)
(***************************************************************************)
GuestStartRecv ==
    \E m \in net :
      /\ IsReq(m, "start")
      /\ IF gRefused
         THEN /\ net' = (net \ {m}) \cup {Rep("start", FALSE, 0, {}, "none")}
              /\ UNCHANGED <<gReg, gKeyStep>>
         ELSE /\ net' = net \ {m}
              /\ SetKey("spawning")
      /\ UNCHANGED <<hostVars, gRefused, gProc, gKilled, gTerm, gReaders,
                     gEmitted, gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails,
                     hMaxSeq, pollAfterStop, retryAfterStop, gTermPoll,
                     gDropped, gCutLive, gTaken, kkEarly>>

GuestSpawn ==
    /\ gReg = "spawning"
    /\ SetKey("live")
    /\ gProc' = "running"
    /\ net' = net \cup {Rep("start", TRUE, 0, {}, "none")}
    /\ UNCHANGED <<hostVars, gRefused, gKilled, gTerm, gReaders, gEmitted,
                   gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, gFails,
                   hMaxSeq, pollAfterStop, retryAfterStop, gTermPoll,
                   gDropped, gCutLive, gTaken, kkEarly>>

(* A waiter: kind "kill" | "killkey"; phase "spawn" | "term"; ack for the  *)
(* collect; tag = kill_key caller; drain = it runs Job.kill (wait readers, *)
(* drain, push, collect) after termination, i.e. it went through          *)
(* Controller.kill on a live job.  The retired branch of kill_key only     *)
(* awaits termination (drain = FALSE).                                     *)
KillW(ack) == [kind |-> "kill", phase |-> "term", ack |-> ack, tag |-> 0, drain |-> TRUE]
KKW(phase, tag, drain) ==
    [kind |-> "killkey", phase |-> phase, ack |-> 0, tag |-> tag, drain |-> drain]

GuestKillKeyRecv ==   \* Controller.kill_key (post-ec29c12)
    \E m \in net :
      /\ IsReq(m, "killkey")
      /\ CASE gReg = "none" ->
                /\ gRefused' = TRUE
                /\ net' = (net \ {m}) \cup {KKRep(m.ack)}
                /\ kkEarly' = (kkEarly \/ gTerm = "running")
                /\ UNCHANGED <<gWaiters, gTerm, gKilled, gProc>>
           [] gReg = "spawning" ->
                /\ gRefused' = TRUE
                /\ net' = net \ {m}
                /\ gWaiters' = gWaiters \cup {KKW("spawn", m.ack, TRUE)}
                /\ UNCHANGED <<gTerm, gKilled, gProc, kkEarly>>
           [] gReg = "live" ->
                /\ net' = net \ {m}
                /\ StartTermination
                /\ gWaiters' = gWaiters \cup {KKW("term", m.ack, TRUE)}
                /\ UNCHANGED <<gRefused, kkEarly>>
           [] gReg = "retired" ->   \* await_termination(), then killed=False
                /\ IF gTerm = "running"
                   THEN /\ net' = net \ {m}
                        /\ gWaiters' = gWaiters \cup {KKW("term", m.ack, FALSE)}
                        /\ UNCHANGED kkEarly
                   ELSE /\ net' = (net \ {m}) \cup {KKRep(m.ack)}
                        /\ kkEarly' = (kkEarly \/ gTerm = "running")
                        /\ UNCHANGED gWaiters
                /\ UNCHANGED <<gRefused, gTerm, gKilled, gProc>>
      /\ UNCHANGED <<hostVars, gReg, gReaders, gEmitted, gPipe, gBuf, gSeq, gHeld,
                     gPoll, gFails, hMaxSeq, pollAfterStop, retryAfterStop,
                     gTermPoll, gDropped, gCutLive, gTaken, gKeyStep>>

GuestKillKeyResume ==  \* the start it waited for has spawned
    \E w \in gWaiters :
      /\ w.kind = "killkey" /\ w.phase = "spawn"
      /\ gReg = "live"
      /\ StartTermination
      /\ gWaiters' = (gWaiters \ {w}) \cup {KKW("term", w.tag, TRUE)}
      /\ UNCHANGED <<net, hostVars, gReg, gRefused, gReaders, gEmitted, gPipe,
                     gBuf, gSeq, gHeld, gPoll, gFails, histVars>>

GuestKillRecv ==      \* Controller.kill(pid) -> Job.kill
    \E m \in net :
      /\ IsReq(m, "kill")
      /\ IF gReg # "live"
         THEN /\ net' = (net \ {m}) \cup {Rep("kill", FALSE, 0, {}, "none")}
              /\ UNCHANGED <<gWaiters, gTerm, gKilled, gProc>>
         ELSE /\ net' = net \ {m}
              /\ StartTermination
              /\ gWaiters' = gWaiters \cup {KillW(m.ack)}
      /\ UNCHANGED <<hostVars, gReg, gRefused, gReaders, gEmitted, gPipe, gBuf,
                     gSeq, gHeld, gPoll, gFails, histVars>>

GuestKillFinish ==    \* termination done: Job.kill waits readers, drains, pushes,
                      \* collects; Controller.kill retires if still registered
    \E w \in gWaiters :
      /\ w.phase = "term" /\ gTerm = "done"
      /\ gWaiters' = gWaiters \ {w}
      /\ IF w.drain
         THEN /\ WaitReaders
              /\ DrainPush(WaitBuf, w.ack)
              /\ IF gReg = "live" THEN SetKey("retired") ELSE UNCHANGED <<gReg, gKeyStep>>
              /\ net' = net \cup
                   {IF w.kind = "kill"
                    THEN Rep("kill", TRUE, NewSeq(WaitBuf), HeldAfter(WaitBuf, w.ack), "none")
                    ELSE KKRep(w.tag)}
         ELSE /\ net' = net \cup {KKRep(w.tag)}
              /\ UNCHANGED <<gReaders, gPipe, gBuf, gSeq, gHeld, gReg, gKeyStep,
                             gDropped, gCutLive, gTaken>>
      /\ UNCHANGED <<hostVars, gRefused, gProc, gKilled, gTerm, gEmitted, gPoll,
                     gFails, hMaxSeq, pollAfterStop, retryAfterStop, gTermPoll,
                     kkEarly>>

(* Controller.poll entry: _get_job() captures the live Job, then the       *)
(* handler awaits.  A missing job is answered at once.                     *)
GuestPollRecv ==
    \E m \in net :
      /\ IsReq(m, "poll") /\ gPoll = NoPoll
      /\ IF gReg # "live"
         THEN /\ net' = (net \ {m}) \cup {Rep("poll", FALSE, 0, {}, "none")}
              /\ UNCHANGED gPoll
         ELSE /\ net' = net \ {m}
              /\ gPoll' = m.ack
      /\ UNCHANGED <<hostVars, gReg, gRefused, gProc, gKilled, gTerm, gReaders,
                     gEmitted, gPipe, gBuf, gSeq, gHeld, gWaiters, gFails, histVars>>

(* Transport raises a RuntimeError for a poll (not a missing job).         *)
PollTransientError ==
    \E m \in net :
      /\ IsReq(m, "poll") /\ gFails < MaxFail
      /\ net' = (net \ {m}) \cup {Rep("poll", FALSE, 0, {}, "none")}
      /\ gFails' = gFails + 1
      /\ UNCHANGED <<hostVars, gReg, gRefused, gProc, gKilled, gTerm, gReaders,
                     gEmitted, gPipe, gBuf, gSeq, gHeld, gWaiters, gPoll, histVars>>

(* BUGGY: Job.poll on a "killed" job does not join the termination task.  *)
(* _wait_for_readers cancels readers of a still-running group (1 s cutoff),*)
(* the poll reports "killed" and the controller retires the job.  The      *)
(* resume uses the captured Job even if a concurrent kill retired it; then *)
(* the pop finds nothing and the poll does not retire again.              *)
GuestPollResume ==
    /\ gPoll # NoPoll
    /\ LET st == JobState
           terminal == st # "running"
           items == IF terminal THEN WaitBuf ELSE gBuf
       IN /\ IF terminal THEN WaitReaders
             ELSE UNCHANGED <<gReaders, gPipe, gDropped, gCutLive>>
          /\ DrainPush(items, gPoll)
          /\ net' = net \cup {Rep("poll", TRUE, NewSeq(items), HeldAfter(items, gPoll), st)}
          /\ IF terminal /\ gReg = "live" THEN SetKey("retired")
             ELSE UNCHANGED <<gReg, gKeyStep>>
          /\ gTermPoll' = (gTermPoll \/ (terminal /\ gTerm = "running"))
    /\ gPoll' = NoPoll
    /\ UNCHANGED <<hostVars, gRefused, gProc, gKilled, gTerm, gEmitted, gWaiters,
                   gFails, hMaxSeq, pollAfterStop, retryAfterStop, kkEarly>>

GuestStdin ==
    \E m \in net :
      /\ IsReq(m, "stdin")
      /\ IF gReg # "live" \/ JobState # "running"
         THEN /\ net' = (net \ {m}) \cup {Rep("stdin", FALSE, 0, {}, "none")}
              /\ UNCHANGED <<gBuf, gSeq, gHeld, gTaken>>
         ELSE /\ DrainPush(gBuf, m.ack)
              /\ net' = (net \ {m}) \cup
                   {Rep("stdin", TRUE, NewSeq(gBuf), HeldAfter(gBuf, m.ack), "none")}
      /\ UNCHANGED <<hostVars, gReg, gRefused, gProc, gKilled, gTerm, gReaders,
                     gEmitted, gPipe, gWaiters, gPoll, gFails, hMaxSeq,
                     pollAfterStop, retryAfterStop, gTermPoll, gDropped, gCutLive,
                     kkEarly, gKeyStep>>

-----------------------------------------------------------------------------
(***************************************************************************)
(* Host: start                                                              *)
(***************************************************************************)
HostStartOk ==
    \E m \in net :
      /\ IsRep(m, "start") /\ m.ok /\ hStart = "waiting"
      /\ net' = net \ {m}
      /\ hStart' = "started" /\ hIter' = "idle"
      /\ UNCHANGED <<hRetries, hStopReq, hStopRpc, hStopOwner, hRemoteStopped,
                     hCaller, hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                     hStdinSent, hStdinBusy, guestVars, histVars>>

HostStartAbort ==   \* start cancelled / timed out before the PID reply: _kill_key
    /\ hStart = "waiting"
    /\ hStart' = "killingKey"
    /\ net' = net \cup {Req("killkey", 0)}
    /\ UNCHANGED <<hIter, hRetries, hStopReq, hStopRpc, hStopOwner, hRemoteStopped,
                   hCaller, hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                   hStdinSent, hStdinBusy, guestVars, histVars>>

HostKillKeyDone ==
    \E m \in net :
      /\ IsRep(m, "killkey") /\ m.ack = 0 /\ hStart = "killingKey"
      /\ net' = net \ {m}
      /\ hStart' = "aborted"
      /\ UNCHANGED <<hIter, hRetries, hStopReq, hStopRpc, hStopOwner, hRemoteStopped,
                     hCaller, hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                     hStdinSent, hStdinBusy, guestVars, histVars>>

(* A second keyed cleanup for the same key, issued after a successful     *)
(* start and after kill() was called (no such host path exists at         *)
(* ec29c12; this reaches the retired-job join in Controller.kill_key).    *)
(* Unless KeyedKillAnyTime, it reaches the guest only after the host's    *)
(* kill started termination (see ../INVARIANTS.md, finding F1).           *)
XKillKeySend ==
    /\ hXKK = "idle" /\ hStart = "started" /\ hStopRpc # "none"
    /\ (KeyedKillAnyTime \/ gTerm # "none")
    /\ hXKK' = "sent"
    /\ net' = net \cup {Req("killkey", 1)}
    /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopRpc, hStopOwner,
                   hRemoteStopped, hCaller, hCompleted, hLastSeq, hPending,
                   hDelivered, hGot, hStdinSent, hStdinBusy, guestVars, histVars>>

XKillKeyDone ==
    \E m \in net :
      /\ IsRep(m, "killkey") /\ m.ack = 1 /\ hXKK = "sent"
      /\ net' = net \ {m}
      /\ hXKK' = "returned"
      /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopRpc, hStopOwner,
                     hRemoteStopped, hCaller, hCompleted, hLastSeq, hPending,
                     hDelivered, hGot, hStdinSent, hStdinBusy, guestVars, histVars>>

HostDropStale ==    \* replies nobody awaits any more
    \E m \in net :
      /\ \/ IsRep(m, "start") /\ hStart # "waiting"
         \/ IsRep(m, "kill") /\ hStopRpc = "abandoned"
      /\ net' = net \ {m}
      /\ UNCHANGED <<hostVars, guestVars, histVars>>

(***************************************************************************)
(* Host: output acceptance                                                  *)
(* BUGGY: _last_seq is overwritten by every reply; all reply output is     *)
(* taken, even output an earlier reply already carried.                    *)
(***************************************************************************)
TakeSeq(m) == hLastSeq' = m.seq /\ hMaxSeq' = Max(hMaxSeq, m.seq)
NoteGot(m) == hGot' = hGot \cup ItemsOf(m)

(***************************************************************************)
(* Host: iterator                                                           *)
(***************************************************************************)
SendPoll ==
    /\ net' = net \cup {Req("poll", hLastSeq)}
    /\ hIter' = "polling"
    /\ hRetries' = 0
    /\ pollAfterStop' = (pollAfterStop \/ hStopReq)

IterNext ==
    /\ hIter = "idle"
    /\ IF hPending # << >>
       THEN /\ hDelivered' = Append(hDelivered, Head(hPending))
            /\ hPending' = Tail(hPending)
            /\ UNCHANGED <<net, hIter, hRetries, pollAfterStop>>
       ELSE IF hCompleted \/ hStopReq
       THEN /\ hIter' = "done"   \* BUGGY: does not wait for an in-flight kill
            /\ UNCHANGED <<net, hRetries, hPending, hDelivered, pollAfterStop>>
       ELSE /\ SendPoll
            /\ UNCHANGED <<hPending, hDelivered>>
    /\ UNCHANGED <<hStart, hStopReq, hStopRpc, hStopOwner, hRemoteStopped, hCaller,
                   hXKK, hCompleted, hLastSeq, hGot, hStdinSent, hStdinBusy,
                   guestVars, hMaxSeq, retryAfterStop, gTermPoll, gDropped,
                   gCutLive, gTaken, kkEarly, gKeyStep>>

(* BUGGY: _pending_events = events[1:] replaces output appended meanwhile. *)
IterPollReply ==
    \E m \in net :
      /\ IsRep(m, "poll") /\ m.ok /\ hIter = "polling"
      /\ net' = net \ {m}
      /\ TakeSeq(m) /\ NoteGot(m)
      /\ hCompleted' = (hCompleted \/ m.state = "completed")
      /\ hStopReq' = (hStopReq \/ m.state = "killed")
      /\ hRemoteStopped' = (hRemoteStopped \/ m.state = "killed")
      /\ LET ev == SeqOf(ItemsOf(m)) IN
         IF ev # << >> \/ m.state = "completed"
         THEN /\ hDelivered' = IF ev # << >> THEN Append(hDelivered, Head(ev)) ELSE hDelivered
              /\ hPending' = IF ev # << >> THEN Tail(ev) ELSE << >>
              /\ hIter' = "idle"
         ELSE /\ hIter' = IF hStopReq' THEN "done" ELSE "sleep"
              /\ UNCHANGED <<hPending, hDelivered>>
      /\ UNCHANGED <<hStart, hRetries, hStopRpc, hStopOwner, hCaller, hXKK,
                     hStdinSent, hStdinBusy, guestVars, pollAfterStop,
                     retryAfterStop, gTermPoll, gDropped, gCutLive, gTaken,
                     kkEarly, gKeyStep>>

(* BUGGY: a RuntimeError ("No job found" or transient) is retried with no *)
(* check of _killed: retryable() checks _killed only once timeout         *)
(* recovery started.  Tenacity then backs off (retryWait).                *)
IterPollError ==
    \E m \in net :
      /\ IsRep(m, "poll") /\ ~m.ok /\ hIter = "polling"
      /\ net' = net \ {m}
      /\ hIter' = IF hRetries < MaxRetry THEN "retryWait" ELSE "failed"
      /\ UNCHANGED <<hStart, hRetries, hStopReq, hStopRpc, hStopOwner,
                     hRemoteStopped, hCaller, hXKK, hCompleted, hLastSeq, hPending,
                     hDelivered, hGot, hStdinSent, hStdinBusy, guestVars, histVars>>

(* BUGGY: after the backoff the retry is sent with no check of _killed    *)
(* (the pre-send check only fires for a re-issued timed-out poll).        *)
IterRetrySend ==
    /\ hIter = "retryWait"
    /\ net' = net \cup {Req("poll", hLastSeq)}
    /\ hIter' = "polling"
    /\ hRetries' = hRetries + 1
    /\ pollAfterStop' = (pollAfterStop \/ hStopReq)
    /\ retryAfterStop' = (retryAfterStop \/ hStopReq)
    /\ UNCHANGED <<hStart, hStopReq, hStopRpc, hStopOwner, hRemoteStopped, hCaller,
                   hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                   hStdinSent, hStdinBusy, guestVars, hMaxSeq, gTermPoll,
                   gDropped, gCutLive, gTaken, kkEarly, gKeyStep>>

(* BUGGY: after anyio.sleep the loop polls again without checking stop.   *)
IterWake ==
    /\ hIter = "sleep"
    /\ SendPoll
    /\ UNCHANGED <<hStart, hStopReq, hStopRpc, hStopOwner, hRemoteStopped, hCaller,
                   hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                   hStdinSent, hStdinBusy, guestVars, hMaxSeq, retryAfterStop,
                   gTermPoll, gDropped, gCutLive, gTaken, kkEarly, gKeyStep>>

(***************************************************************************)
(* Host: kill()                                                             *)
(* BUGGY: _killed=True before the RPC; the RPC belongs to the first        *)
(* caller; later callers return at once; cancelling the first caller       *)
(* abandons the RPC.                                                       *)
(***************************************************************************)
KillCall(k) ==
    /\ hCaller[k] = "idle" /\ hStart = "started"
    /\ IF hCompleted \/ hStopReq
       THEN /\ hCaller' = [hCaller EXCEPT ![k] = "returned"]
            /\ UNCHANGED <<hStopReq, hStopRpc, hStopOwner>>
       ELSE /\ hCaller' = [hCaller EXCEPT ![k] = "waiting"]
            /\ hStopReq' = TRUE /\ hStopRpc' = "queued" /\ hStopOwner' = k
    /\ UNCHANGED <<net, hStart, hIter, hRetries, hRemoteStopped, hXKK, hCompleted,
                   hLastSeq, hPending, hDelivered, hGot, hStdinSent, hStdinBusy,
                   guestVars, histVars>>

StopSend ==
    /\ hStopRpc = "queued"
    /\ hStopRpc' = "sent"
    /\ net' = net \cup {Req("kill", hLastSeq)}
    /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopOwner, hRemoteStopped,
                   hCaller, hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                   hStdinSent, hStdinBusy, guestVars, histVars>>

KillCancel(k) ==
    /\ hCaller[k] = "waiting"
    /\ hCaller' = [hCaller EXCEPT ![k] = "cancelled"]
    /\ IF k = hStopOwner /\ hStopRpc \in {"queued", "sent"}
       THEN hStopRpc' = "abandoned"
       ELSE UNCHANGED hStopRpc
    /\ UNCHANGED <<net, hStart, hIter, hRetries, hStopReq, hStopOwner, hRemoteStopped,
                   hXKK, hCompleted, hLastSeq, hPending, hDelivered, hGot,
                   hStdinSent, hStdinBusy, guestVars, histVars>>

StopReply ==
    \E m \in net :
      /\ IsRep(m, "kill") /\ hStopRpc = "sent"
      /\ net' = net \ {m}
      /\ hStopRpc' = "finished"
      /\ hCaller' = [hCaller EXCEPT ![hStopOwner] = "returned"]
      /\ IF m.ok
         THEN /\ TakeSeq(m) /\ NoteGot(m)
              /\ hPending' = hPending \o SeqOf(ItemsOf(m))
              /\ hRemoteStopped' = TRUE
         ELSE UNCHANGED <<hLastSeq, hMaxSeq, hGot, hPending, hRemoteStopped>>
      /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopOwner, hXKK,
                     hCompleted, hDelivered, hStdinSent, hStdinBusy, guestVars,
                     pollAfterStop, retryAfterStop, gTermPoll, gDropped, gCutLive,
                     gTaken, kkEarly, gKeyStep>>

(***************************************************************************)
(* Host: write_stdin()                                                      *)
(***************************************************************************)
StdinWrite ==
    /\ hStart = "started" /\ ~hCompleted /\ ~hStopReq
    /\ ~hStdinBusy /\ hStdinSent < MaxStdin
    /\ hStdinSent' = hStdinSent + 1 /\ hStdinBusy' = TRUE
    /\ net' = net \cup {Req("stdin", hLastSeq)}
    /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopRpc, hStopOwner,
                   hRemoteStopped, hCaller, hXKK, hCompleted, hLastSeq, hPending,
                   hDelivered, hGot, guestVars, histVars>>

StdinReply ==
    \E m \in net :
      /\ IsRep(m, "stdin")
      /\ net' = net \ {m}
      /\ hStdinBusy' = FALSE
      /\ IF m.ok
         THEN /\ TakeSeq(m) /\ NoteGot(m)
              /\ hPending' = hPending \o SeqOf(ItemsOf(m))
         ELSE UNCHANGED <<hLastSeq, hMaxSeq, hGot, hPending>>
      /\ UNCHANGED <<hStart, hIter, hRetries, hStopReq, hStopRpc, hStopOwner,
                     hRemoteStopped, hCaller, hXKK, hCompleted, hDelivered,
                     hStdinSent, guestVars, pollAfterStop, retryAfterStop,
                     gTermPoll, gDropped, gCutLive, gTaken, kkEarly, gKeyStep>>

-----------------------------------------------------------------------------
(* Nothing left to do: stutter instead of reporting a deadlock.            *)
Finished ==
    /\ net = {} /\ gWaiters = {} /\ gPoll = NoPoll
    /\ gProc # "running" /\ gTerm # "running"
    /\ \/ hIter \in {"done", "failed"}
       \/ hIter = "unstarted" /\ hStart = "aborted"
    /\ \A k \in Killers : hCaller[k] # "waiting"
    /\ hStopRpc # "queued" /\ ~hStdinBusy /\ hXKK # "sent"

Done == Finished /\ UNCHANGED vars

\* Steps the system itself takes (fair); the rest are environment choices.
SystemNext ==
    \/ TermFinish \/ ReaderRead \/ GuestStartRecv \/ GuestSpawn
    \/ GuestKillKeyRecv \/ GuestKillKeyResume \/ GuestKillRecv \/ GuestKillFinish
    \/ GuestPollRecv \/ GuestPollResume \/ GuestStdin
    \/ HostStartOk \/ HostKillKeyDone \/ XKillKeyDone \/ HostDropStale
    \/ IterNext \/ IterPollReply \/ IterPollError \/ IterRetrySend \/ IterWake
    \/ StopSend \/ StopReply \/ StdinReply

EnvNext ==
    \/ Emit \/ ProcExit \/ HostStartAbort \/ StdinWrite \/ XKillKeySend
    \/ PollTransientError
    \/ \E k \in Killers : KillCall(k) \/ KillCancel(k)

Next == SystemNext \/ EnvNext \/ Done

\* Weak fairness per system action (not on the disjunction, which would let
\* one busy action starve another).
Fairness ==
    /\ WF_vars(TermFinish) /\ WF_vars(ReaderRead) /\ WF_vars(GuestStartRecv)
    /\ WF_vars(GuestSpawn) /\ WF_vars(GuestKillKeyRecv) /\ WF_vars(GuestKillKeyResume)
    /\ WF_vars(GuestKillRecv) /\ WF_vars(GuestKillFinish)
    /\ WF_vars(GuestPollRecv) /\ WF_vars(GuestPollResume) /\ WF_vars(GuestStdin)
    /\ WF_vars(HostStartOk) /\ WF_vars(HostKillKeyDone) /\ WF_vars(XKillKeyDone)
    /\ WF_vars(HostDropStale) /\ WF_vars(IterNext) /\ WF_vars(IterPollReply)
    /\ WF_vars(IterPollError) /\ WF_vars(IterRetrySend) /\ WF_vars(IterWake)
    /\ WF_vars(StopSend) /\ WF_vars(StopReply) /\ WF_vars(StdinReply)

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
(***************************************************************************)
(* INVARIANTS  (identical text in ../ExecRemote.tla; see ../INVARIANTS.md) *)
(***************************************************************************)
Waiter == [kind : {"kill", "killkey"}, phase : {"spawn", "term"},
           ack : Nat, tag : {0, 1}, drain : BOOLEAN]
TypeOK ==
    /\ hStart \in {"waiting", "started", "killingKey", "aborted"}
    /\ hIter \in {"unstarted", "idle", "polling", "sleep", "retryWait", "done", "failed"}
    /\ hRetries \in 0..MaxRetry
    /\ hStopReq \in BOOLEAN /\ hRemoteStopped \in BOOLEAN /\ hCompleted \in BOOLEAN
    /\ hStopRpc \in {"none", "queued", "sent", "finished", "abandoned"}
    /\ hStopOwner \in Killers \cup {NoKiller}
    /\ hCaller \in [Killers -> {"idle", "waiting", "returned", "cancelled"}]
    /\ hXKK \in {"idle", "sent", "returned"}
    /\ hStdinSent \in 0..MaxStdin /\ hStdinBusy \in BOOLEAN
    /\ hPending \in Seq(Items) /\ hDelivered \in Seq(Items)
    /\ gReg \in {"none", "spawning", "live", "retired"}
    /\ gRefused \in BOOLEAN /\ gKilled \in BOOLEAN
    /\ gProc \in {"none", "running", "exited"}
    /\ gTerm \in {"none", "running", "done"}
    /\ gReaders \in {"open", "eof", "cancelled"}
    /\ gEmitted \in 0..MaxOut
    /\ gPipe \subseteq Items /\ gBuf \subseteq Items /\ hGot \subseteq Items
    /\ Cardinality(gBuf) <= BufCap
    /\ \A w \in gWaiters : w \in Waiter
    /\ gPoll \in Nat /\ gFails \in 0..MaxFail
    /\ hLastSeq \in Nat /\ gSeq \in Nat
    /\ \A c \in gHeld : c.seq \in 1..gSeq /\ c.items \subseteq Items
    /\ \A m \in net : m.dir \in {"req", "rep"}
                      /\ m.type \in {"start", "poll", "kill", "killkey", "stdin"}

\* (1) No poll and no poll retry after the host's local stop.
NoPollAfterLocalStop == ~pollAfterStop
NoMissingJobRetryAfterStop == ~retryAfterStop
IteratorNeverFails == hIter # "failed"
\* (1)+(2) The iterator ends only after the stop finished and its output was yielded.
IteratorEndsDrained == hIter = "done" => hPending = << >>
IteratorStoppedAfterRpc == (hIter = "done" /\ hStopRpc # "none") => hStopRpc = "finished"

\* (2) kill() returns normally only after the shared stop RPC finished
\*     (or the process was already known completed). No caller's
\*     cancellation abandons the stop.
KillReturnJoinsStop ==
    \A k \in Killers : hCaller[k] = "returned" => (hCompleted \/ hStopRpc = "finished")
StopNeverAbandoned == hStopRpc # "abandoned"

\* (3) The guest reports a terminal poll and retires the job only after
\*     termination finished; readers are never cut off while the leader
\*     runs; no written output is dropped (see BufCap in ../INVARIANTS.md).
TerminalPollAfterTermination == ~gTermPoll
RetireOnlyAfterTermination == gReg = "retired" => gTerm # "running"
ReadersCutOnlyAfterExit == ~gCutLive
NoGuestOutputLoss == gDropped = {}
\* Every written item is in exactly one place.
OutputConserved ==
    /\ gPipe \cup gBuf \cup gTaken \cup gDropped = 1..gEmitted
    /\ gPipe \cap gBuf = {} /\ gPipe \cap gTaken = {} /\ gPipe \cap gDropped = {}
    /\ gBuf \cap gTaken = {} /\ gBuf \cap gDropped = {} /\ gTaken \cap gDropped = {}

\* Controller key: legal transitions only; a refused key never starts.
LegalKeySteps == {<<"none", "none">>, <<"none", "spawning">>,
                  <<"spawning", "live">>, <<"live", "retired">>}
KeyStepsLegal ==
    /\ <<gKeyStep[1], gKeyStep[2]>> \in LegalKeySteps
    /\ (gKeyStep[2] = "spawning" => ~gKeyStep[3])
\* After any kill_key returns, the process is not running and its
\* termination is not running; a key with no spawn is refused.
KillKeySettles ==
    /\ hStart = "aborted" =>
         (gProc # "running" /\ gTerm # "running" /\ (gReg = "none" => gRefused))
    /\ hXKK = "returned" => (gProc # "running" /\ gTerm # "running")
\* No kill_key reply is built while termination runs (it joins it).
KillKeyJoinsTermination == ~kkEarly

\* (4) Host seq never regresses; no output item is delivered twice.
SeqMonotonic == hLastSeq = hMaxSeq
NoDuplicateEvent ==
    LET all == hDelivered \o hPending
    IN \A i, j \in 1..Len(all) : i # j => all[i] # all[j]
\* (4)+(5) The yielded-then-queued output is in emission order and skips
\*     no item that reached the guest's acked buffer before a later one.
OutputSequenceMonotone ==
    LET all == hDelivered \o hPending
    IN /\ \A i, j \in 1..Len(all) : i < j => all[i] < all[j]
       /\ \A x \in Range(all), y \in gTaken : y < x => y \in Range(all)

\* (5) Output carried by any processed reply is yielded or still queued.
NoEventLoss == hGot \subseteq Range(hDelivered) \cup Range(hPending)

\* Extra end-to-end check (not one of the agreed rules).
CompletedDeliversAll ==
    (hIter = "done" /\ hCompleted) => Range(hDelivered) = 1..gEmitted

-----------------------------------------------------------------------------
(***************************************************************************)
(* REACHABILITY WITNESSES (expected to FAIL; each failure shows that a     *)
(* situation the review asked about is reachable).  Not design rules.      *)
(***************************************************************************)
\* A keyed kill waits on a retired job whose termination still runs.
NotRetiredKillKeyJoin ==
    ~\E w \in gWaiters : w.kind = "killkey" /\ ~w.drain /\ gTerm = "running"
\* A poll handler holds a captured Job that another handler already retired.
NotPollResumeAfterRetire == ~(gPoll # NoPoll /\ gReg = "retired")
\* kill() is called while the iterator backs off before a retry.
NotKillDuringBackoff == ~(hIter = "retryWait" /\ hStopReq)
\* A retry is sent and answered with no local stop.
NotRetryWithoutStop == ~(hRetries > 0 /\ ~hStopReq /\ hIter \in {"idle", "sleep"})

-----------------------------------------------------------------------------
(***************************************************************************)
(* LIVENESS  (check only after all safety invariants pass on fixed/)       *)
(***************************************************************************)
StopTakesEffect == hStopReq ~> (gProc # "running")
KillCallsReturn == \A k \in Killers : (hCaller[k] = "waiting") ~> (hCaller[k] # "waiting")
IteratorEnds == (hIter # "unstarted" /\ gProc = "exited") ~> (hIter \in {"done", "failed"})
AbortedStartSettles == (hStart = "killingKey") ~> (hStart = "aborted")
KeyedKillReturns == (hXKK = "sent") ~> (hXKK = "returned")
=============================================================================
