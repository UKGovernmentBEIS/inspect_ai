# Agent ACP

A way for an external client (initially: the Zed editor) to attach to a running
Inspect eval, observe a specific sample's agent activity, and interact with it
(send messages, interrupt, approve tool calls) via the Agent Client Protocol.

## Goals

- A **generic agent-side facility** that any Inspect agent can opt into (not just `react()` / `deepagent()`).
- An **eval-level JSON-RPC 2.0 endpoint** (unix socket or TCP) opened by `inspect eval --agent-acp` that:
  - enumerates running tasks/samples/epochs,
  - exposes ACP methods routed to a chosen `(task, sample_id, epoch)`.
- An **`inspect acp`** stub binary that talks ACP-over-stdio to an editor and proxies into the eval.
- **Interruption** semantics that work mid-turn: cancel an in-flight `generate()` or tool call without terminating the sample, then let the user inject a message before the agent's next step.

## In scope / out of scope

ACP integration applies to agents that use the `before_turn` /
`turn_scope` / `after_cancel` splice — initially `react()` and
`deepagent()`. **Custom solvers and agents that don't go through this
splice are silently out of scope**: they run normally, don't appear in
`inspect/listSessions`, and aren't ACP-controllable. Any custom scaffold
can opt in by adding the same three calls in its turn loop; the contract
is small enough to be a one-time, well-documented addition.

This is intentional. We don't try to retrofit ACP into arbitrary
solver pipelines — interactive control needs the agent author to mark
their turn boundaries explicitly, and there's no safe way to infer them.

## Non-goals (v1)

- Multi-user, authenticated, or remote-over-WAN access.
- Token-level streaming inside ACP `sessionUpdate` (we ship turn-granularity first).
- ACP permission requests routed through the editor (future; today's `approval` machinery still runs).
- Resumption of completed samples / log-file replay over ACP (future).

## Background

### What ACP provides

ACP is JSON-RPC 2.0, conventionally over stdio between editor and agent process.
Surface we care about:

- `initialize`, `authenticate`, `newSession`, `loadSession`
- `session/prompt` — client sends a user message; response carries the turn-end status.
- `session/cancel` — interrupt the current turn.
- `session/update` (notification) — agent → client streaming activity:
  `user_message_chunk`, `agent_message_chunk`, `agent_thought_chunk`,
  `tool_call`, `tool_call_update`, `plan`.
- `session/request_permission` — agent → client, ask before running a tool.

The agent is the *server* in ACP. Our eval process is the agent.

### Inspect primitives we'll reuse

| Primitive | Location | Role |
|---|---|---|
| `ActiveSample` registry | `log/_samples.py` | Per-running-sample object with `tg`, `transcript`, sample event stream, hard `interrupt()`. |
| Sample event stream (`event_send`/`event_receive`) | `log/_samples.py` | Already-built fan-out of `SampleEvent`s; perfect substrate for `session/update`. |
| `track_active_model_event` ContextVar | `log/_samples.py` | In-flight model call marker; we'll extend the pattern for an in-flight *turn* marker. |
| Task group cancel scopes | anyio | Mechanism for targeted in-flight cancellation. |
| Human agent | `agent/_human/` | Architectural precedent for "external thing drives a running sample". |
| Tool execution wrapper | `model/_call_tools.py` etc. | Where tool cancellation already integrates. |

## Architecture

```
Editor (Zed)                  inspect acp                    inspect eval --agent-acp
+----------+   ACP over   +------------------+   ACP over   +-------------------------+
|          | <==========> | stdio↔socket     | <==========> | AcpServer (JSON-RPC mux)|
| editor   |    stdio     | bridge + session |   AF_UNIX    +-------------------------+
|          |              | picker (thin)    |    /TCP                  |
+----------+              +------------------+                          | dispatch
                                                                        v
                                                            +-----------------------+
                                                            | SessionRouter         |
                                                            |  per (task, sid, ep)  |
                                                            +-----------------------+
                                                                        |
                                                            +-----------------------+
                                                            | AcpSession (in-task)  |
                                                            |  - user-msg queue     |
                                                            |  - turn cancel scope  |
                                                            |  - transcript→update  |
                                                            +-----------------------+
                                                                        |
                                                              react() / deepagent()
                                                              (agent loop with yield
                                                               points to AcpSession)
```

Four cooperating layers — agent-side `AcpSession`, eval-side `SessionRouter`,
eval-side `AcpServer`, external `inspect acp` stub.

## Component design

### 1. `AcpSession` (agent-side, in-task)

Lives in the same task as the agent. **Every** running sample has one — the
default implementation is a no-op so ACP-unaware agents and ACP-disabled runs
cost nothing and need no conditional code.

```python
class AcpSession:
    """Per-agent ACP interface. Obtained via `async with acp_session() as acp:`.
       An async context manager: __aexit__ is the moment the session
       terminates (clients receive `end` + EOF)."""

    async def __aenter__(self) -> "AcpSession": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    # Yield-point API the agent calls.
    async def before_turn(self, state: AgentState) -> list[ChatMessageUser]:
        """Return any user messages queued by the client since last turn.
           Blocks only if (a) this is the first call and (b) `state.messages`
           has no user content yet. Otherwise drains the queue and returns
           immediately. First call also claims this sample as an ACP target."""

    @contextmanager
    def turn_scope(self) -> Iterator[CancelScope]:
        """Wrap a turn body. ACP session/cancel cancels this scope."""

    async def after_cancel(self) -> list[ChatMessage]:
        """Drain pending user messages; if none, wait for one. Also returns
           any synthetic `ChatMessageTool` results needed to repair
           `state.messages` after cancelled tool calls. Returned in order
           ready to extend onto `state.messages`."""

    # Producer-side API used by the SessionRouter.
    def submit_user_message(self, msg: ChatMessageUser) -> None: ...
    def cancel_current_turn(self) -> None: ...
    def attach(self) -> SessionAttachment: ...   # returns event subscription
    def detach(self, attachment) -> None: ...

    @property
    def is_active(self) -> bool: ...      # has the agent claimed ACP? (see below)
    @property
    def capabilities(self) -> AcpCapabilities: ...
```

Being a context manager is load-bearing: `__aexit__` is the single
deterministic moment to send the final `session/update`, close
attached clients, and clean up. This dovetails with "exit on done, no
chat-after-completion" in the lifecycle section.

The **default no-op adapter** is installed on every `ActiveSample`. Its
`before_turn` returns `[]` immediately, `turn_scope` is a `nullcontext()`,
and `after_cancel` is never reached. Agents that don't know about ACP get
zero overhead and no behavior change.

**Demand-driven advertisement of ACP support.** A sample only becomes an
ACP target the first time its agent calls `before_turn()` on a real
adapter. That call promotes the dormant per-sample adapter to active state
and registers the sample in `inspect/listSessions`. There's no separate
"this agent supports ACP" capability flag for authors to maintain — calling
`before_turn` *is* the declaration. Until it's called, clients can't see
the session.

#### Integration into `react()`

The agent wraps its loop in `async with acp_session() as acp:`. The
factory handles installation (real if outermost, no-op if shadowed) and
`__aexit__` is the deterministic moment to close client connections:

```python
async with acp_session() as acp:
    while True:
        state.messages.extend(await acp.before_turn(state))

        try:
            with acp.turn_scope():
                state.output = await get_model().generate(state.messages, tools)
                state.messages.append(state.output.message)
                if state.output.message.tool_calls:
                    messages, output = await execute_tools(...)
                    state.messages.extend(messages)
                    # ... existing react logic ...
        except TurnCancelled:
            state.messages.extend(await acp.after_cancel())
            continue
```

There's no `if acp else` because the no-op default `AcpSession` handles
the disabled case transparently. `TurnCancelled` is raised by the session
inside `turn_scope` to distinguish a client-driven cancel from a
sample-level hard cancel (which still goes through
`ActiveSample.tg.cancel_scope.cancel()` and terminates the sample as
today).

There are **two access patterns** for the session:
- `async with acp_session() as acp:` — agent's loop wrap site. Returns
  a context manager; the factory enforces top-level-only by shadowing
  with a no-op if one is already active.
- `current_acp_session()` — peek-only retrieval for code deep in the
  call stack (e.g., the approval framework wanting to route a prompt
  to the active session). Returns the active `AcpSession` or the no-op
  singleton; never enters a new scope.

#### Integration into `deepagent()`

Same splice in the top-level deepagent loop. Sub-agents are explicitly
**not** ACP-controllable (see "Top-level only" below) — they get cancelled
as a side effect of cancelling the top-level turn, the same way any
in-flight tool call gets cancelled.

#### Top-level only

ACP control applies to the **outermost** agent in a sample. Nested
agents (via `handoff()`, `as_tool()`, `deepagent()` sub-agent dispatch,
or any other path including a direct call) must see a no-op session
even if they also wrap their loop in `async with acp_session()`.

The enforcement lives in the `acp_session()` factory itself —
**"if one is already active, shadow with no-op"**:

```python
# Sketch
_acp_var: ContextVar[AcpSession] = ContextVar("acp", default=_NoOp())

@asynccontextmanager
async def acp_session():
    current = _acp_var.get()
    # If a real (non-no-op) session is already active, this scope gets a
    # no-op. Otherwise build and install the real one.
    install = _NoOp() if not isinstance(current, _NoOp) else _LiveAcpSession(...)
    token = _acp_var.set(install)
    try:
        async with install:
            yield install
    finally:
        _acp_var.reset(token)

def current_acp_session() -> AcpSession:
    return _acp_var.get()
```

Result:
- The outermost `async with acp_session()` (in the top-level agent's
  body) sees a no-op default in the var and installs the real session.
- Any nested agent that opens `async with acp_session()` sees the real
  one is already active and installs a no-op for its body.
- Sub-agents that don't open one at all simply have no `acp` variable.
  Code anywhere in the call stack that calls `current_acp_session()`
  still sees the outer real session — which is exactly what we want
  for the approval framework (it routes to the top-level driver).
- No depth counter, no per-entry-point coordination, no `@agent`-
  decorator magic for ACP. The decorator's only ACP-related job is to
  emit a sub-agent boundary span so the SessionRouter can filter
  events (see "Filtering top-level events").

**Direct calls.** Because the check is "is there already a real one
active?" rather than "what's my depth?", an agent that calls another
agent's function directly still gets the right behavior — *if* that
called function opens its own `acp_session()`, it'll be shadowed; if
it doesn't, it just runs without an `acp` handle (no harm).

`session/cancel` cancels the top-level `turn_scope`. anyio propagates
that into all nested sub-tasks (sub-agents, their tool calls, their
model calls) as ordinary `CancelledError`. The top-level loop catches
`TurnCancelled` and resumes; the sub-agent stack unwinds normally.

### 2. `SessionRouter` (eval-side, one per sample)

Bridges the `AcpSession` and the per-session JSON-RPC traffic.

Responsibilities:
- Owns the **`sessionId`** (an opaque uuid we mint per ActiveSample).
- Subscribes to the sample's transcript event stream; **filters to top-level
  events only** (see below), converts each event to a `session/update`
  notification, and pushes to attached clients.
- Translates inbound JSON-RPC method calls (`prompt`, `cancel`) into `AcpSession` calls.
- On attach, **replays** the last N messages of prior session as
  `session/update` notifications so the editor's view is coherent (N is
  configurable; tool call payloads beyond a size threshold are elided).
- Supports multiple concurrent observers attaching to the same session
  (one driver — the prompt source — plus passive read-only viewers); see
  "Multi-attach" below.

#### Filtering top-level events (critical correctness requirement)

**Only top-level agent events reach ACP clients.** The raw event stream
contains many more events than a client should see — every sub-agent
emits its own `MessageEvent`s, `ToolEvent`s, `ModelEvent`s. If we
naively forwarded the whole stream the editor would see an interleaved
mess of "agent message" notifications from agents the user never
addressed.

The router subscribes with a span-boundary filter: only events whose
enclosing span chain stays at the top level are mapped to
`session/update`. Sub-agent activity collapses to a single `tool_call` /
`tool_call_update` pair (the `as_tool` invocation, or the deepagent
sub-agent dispatch tool) at the outer level — the inner generates and
tool calls **must not** leak as separate updates. Inspect's regular
transcript view still shows full detail; ACP is the "outer conversation"
surface only.

Implementation: the `@agent` decorator emits a span tagged as a
sub-agent boundary (e.g., `span.attributes["agent.boundary"] = True`).
The router maintains a small per-event "current sub-agent depth" by
watching `SpanBeginEvent` / `SpanEndEvent` for those tagged spans, and
drops events whose depth > 0. This is a small, well-scoped change to
the `@agent` decorator and the router.

Event → `session/update` mapping (initial pass, top-level only):

| Inspect event | ACP update |
|---|---|
| `MessageEvent(user)` | `user_message_chunk` (no-op for client-originated messages) |
| `MessageEvent(assistant)` text blocks | `agent_message_chunk` |
| `MessageEvent(assistant)` thinking blocks | `agent_thought_chunk` |
| `ToolEvent` start | `tool_call` |
| `ToolEvent` complete | `tool_call_update` |
| `StateEvent` / `InfoEvent` | (filtered out) |

Token-level streaming requires hooking into the provider's streaming
generator, separate from the transcript fan-out — deferred to phase 4.

#### Inbound `session/prompt` content

ACP's prompt content is a list of content blocks (text, image, file
reference, etc.). The SessionRouter translates these into a
`ChatMessageUser` with multi-modal `content` blocks. Text and image
blocks map straight onto Inspect's `ContentText` / `ContentImage`. Other
ACP block types we can support trivially (e.g., file references → text
with a `[file: path]` placeholder) get a simple translation; anything we
can't translate produces a `session/update` error response with a clear
message so the editor can fall back. We pass `source="operator"` on the
resulting `ChatMessageUser` regardless of content shape.

#### Multi-attach

The server is a JSON-RPC mux — multiple TCP/socket connections can be
open at once, each bound to its own sessionId. So **concurrent observation
of different samples** is fully supported from day one.

Within a single session, we support multiple attached clients. One is the
**driver** (the most recent to send `session/prompt` becomes the driver
implicitly, or it can be explicitly claimed); others are read-only
observers receiving `session/update`. This matters for the TUI + editor
case where both might want to attach to the same session.

### 3. `AcpServer` (eval-side, single instance)

Started when `--agent-acp` is passed. Lifecycle tied to the eval run.

- Listens on an AF_UNIX socket at
  `inspect_data_dir("acp") / f"{eval_id}.sock"` (POSIX default), or TCP
  `127.0.0.1:N` if `--agent-acp-port=N`. We use the standard
  `inspect_data_dir(...)` helper (from `inspect_ai._util.appdirs`),
  not a hard-coded path, for cross-platform correctness.
- Writes a discovery file at `inspect_data_dir("acp") / f"{pid}.json"`
  containing `{eval_id, pid, socket_path, started}`.
- **PID liveness on enumerate.** When `inspect acp` enumerates active
  evals, it checks each discovery file's PID is still running
  (`os.kill(pid, 0)` on POSIX; equivalent on Windows). Stale files
  (process gone) are deleted as a side effect. This keeps the directory
  from accumulating cruft when evals crash or terminate abruptly.
- Accepts JSON-RPC 2.0 connections; each connection is its own ACP "agent server" session from the client's POV.
- Each connection's binding depends on which method the client uses:
  - `session/load(<known live uuid>)` binds directly to that target.
  - `session/load(<unknown uuid>)` returns `invalid_params` (call `session/new` instead if you want the picker).
  - `session/new` triggers the picker (or auto-binds when exactly one target is available).
- The server is a JSON-RPC mux: many concurrent connections, each independently bound to its own target session, fully supported.

The server is wired into the eval lifecycle similarly to `--display`: started before sample execution, drained on shutdown.

#### In-channel session picker

The picker is exposed *through* the ACP channel so editors with no Inspect-specific UI still get a usable flow. The path depends on which method the client called:

1. Client connects + calls `initialize`. Server responds with capabilities.
2. Client calls `session/new`. Server mints a synthetic **control session** uuid unique to this connection (the client's stable `wire_session_id` for the rest of the conversation) and returns it. **If only one target is available, the server skips the picker entirely** — the response sessionId IS the target's id and a `session/update` confirms the binding.
3. With multiple targets, server immediately pushes a `session/update` on the control session containing the list (numbered `agent_message_chunk` text body for editors, plus a structured `_meta["inspect.picker.targets"]: [{sessionId, task, sampleId, epoch}, ...]` payload for capability-aware clients).
4. Client's first `session/prompt` is the user's selection (a number resolved against the picker's snapshot, or a uuid from `_meta`). Server validates the resolved sessionId is still in the live target list (redisplays the picker if the sample finished in the window) and then **rebinds** this connection's `target_session_id`. The client's `wire_session_id` stays unchanged; subsequent `session/update` notifications continue to use it with target details surfaced via `_meta`. From the editor's POV the sessionId is stable; the rebind is invisible.
5. Alternative direct-attach path: `session/load(<known live uuid>)` binds straight to that target without going through the picker. Useful for resume / reconnect scenarios where the client already knows the sessionId.

The server validates incoming `session_id` on `session/prompt` and `session/cancel` against the connection's `wire_session_id`; mismatches surface as `invalid_params` (prompt) or are silently dropped (cancel notification).

This stays within standard ACP semantics (no custom JSON-RPC methods required for the picker) while giving us a flexible UX.

### 4. `inspect acp` — TUI + editor stub

`inspect acp` is **both** the human-facing ACP client we ship (a Textual
TUI) and the editor-passthrough stub. Mode is selected by a flag:

```
inspect acp                  # textual TUI client (default)
inspect acp --stdio          # passthrough: ACP-over-stdio ↔ socket
inspect acp [--eval-id EID]  # disambiguate when multiple evals are running
```

- **TUI mode**: opens an interactive Textual UI. Internally it's just an
  ACP client over the eval socket — message pane, input line, interrupt
  key. The picker step appears as a first screen if multiple sessions
  exist.
- **Stdio mode**: Zed (or any other ACP editor) is configured with
  `inspect acp --stdio` as its agent server command. The stub speaks ACP
  over stdio with the editor and bridges 1:1 to the eval's socket. The
  picker flow described above runs over stdio just like any other client.

We may want a small "I am an editor" capability flag exchanged at
`initialize` so the server tailors picker formatting (richer for the TUI,
plainer for editors).

### 5. In-process ACP for the existing Inspect TUI

The existing `--display full` Textual TUI already shows transcripts and
sample status. We make it a **first-class in-process ACP client** so
interactive features (type a message, interrupt, resume) work *without
needing `--agent-acp` to be set*.

To enable this cleanly:
- The `AcpSession` is **transport-agnostic**. It exposes a pub/sub
  interface for `session/update`-shaped events and a method surface for
  `prompt` / `cancel`.
- The `AcpServer` (socket transport) is one consumer of that interface.
- The local TUI is another consumer, subscribing **in-process** with no
  socket required.
- `--agent-acp` controls whether the *socket* is opened. It does **not**
  control whether ACP semantics work locally; that's always-on for the
  TUI.

So the flag-vs-default split becomes:

| | Local TUI interactive | External ACP clients |
|---|---|---|
| no flag | yes (in-process) | no |
| `--agent-acp` | yes (in-process) | yes (over socket) |

This makes ACP the canonical interaction protocol *inside* Inspect, with
external exposure as an optional layer on top. A pleasant side effect:
the TUI exercises the same code path as Zed, so we don't have two
interactive paths to test.

### Transcript record of user cancels

When a user cancels mid-turn and types a follow-up message, we want the
transcript to clearly show:
- *that* a cancel happened (and what was running when it did),
- *what* the user typed as a result.

Two complementary pieces handle this:

**1. `ChatMessageUser.source` gets a new value `"operator"`.** The field
is currently `Literal["input", "generate"] | None`; we extend it to
`Literal["input", "generate", "operator"] | None`. Every user message
the ACP adapter injects (whether following a cancel or just a normal
`session/prompt` between turns) is marked `source="operator"`. This is
the canonical provenance signal: any code (and the transcript view, log
analysis, etc.) can distinguish dataset-supplied user messages from
human-injected ones without consulting a separate event.

**2. A dedicated `InterruptEvent`** in the transcript marks the
*cancellation* itself — what was running when the cancel hit — emitted
by the adapter at the moment `session/cancel` is processed:

```python
class InterruptEvent(BaseEvent):
    event: Literal["interrupt"] = "interrupt"
    source: Literal["user_cancel", "limit", "system"] = "user_cancel"
    # what was interrupted, drawn from active_model_event / active tool call
    interrupted: Literal["generate", "tool_call", "between_turns"]
    interrupted_tool_call_id: str | None = None
    interrupted_model_event_id: str | None = None
```

The follow-up `ChatMessageUser(source="operator")` flows through
`state.messages` and appears as a regular `MessageEvent(user)`
immediately after the `InterruptEvent`. So the transcript reads
naturally: *interrupt → user message (operator)*. The `InterruptEvent`
doesn't need to duplicate the message preview because the next event
*is* the message.

`InterruptEvent` is also emitted on hard sample cancels (limit, eval
shutdown) with `source="limit"` / `"system"`, giving us a unified
mechanism for "agent execution was cut short" in the transcript regardless
of cause.

## Deep dive: session lifecycle

The agent loop runs normally; ACP enables **mid-flight intervention**
(interrupt + inject a user message), not chat-style continuation after
the agent is done. The client model is "intervene and forget" — users
don't have to babysit the agent to acknowledge termination.

**Lifecycle:**
1. Sample starts. `AcpSession` is installed but dormant.
2. Agent enters its body. First call to `before_turn` claims the
   adapter; the session becomes enumerable.
3. *Optional pre-start wait*: if `state.messages` has no user content
   yet, `before_turn` blocks for the first user message. Otherwise it
   returns immediately with whatever's queued (typically empty on first
   call).
4. Agent runs. Clients can attach at any point, observe events, and
   `session/cancel` + `session/prompt` to inject user messages
   mid-flight.
5. Model decides the agent is done (no more tool calls / submit
   tool fires). `react()` exits normally — **no waiting for the user**.
6. The adapter's context manager exit fires: send a final
   `session/update` with terminal status, close the session, drop all
   client connections to it (they receive an `end` notification + EOF
   on their session).
7. Scoring runs immediately (no waiting on humans).
8. Sample completes.

**Why exit on done, not keep alive:** the user wanted to express
intervention intent, not own the sample's lifetime. If they wanted to
keep the conversation going they could `session/cancel` before the
agent's final message. This keeps scoring timing predictable and
matches batch-eval expectations.

**`before_turn` blocking** is therefore narrow:
- First call, no user content in `state.messages` yet → block.
- Otherwise → drain queue and return immediately, non-blocking.

This means a user who attaches *after* the agent has already exited
sees an immediate `end` notification with the final state replayed.
They can read the transcript but can't drive further interaction —
that sample is over.

## Deep dive: interruption

The mechanism in three layers:

**Layer A — agent loop punctuation.**
Every ACP-aware agent wraps each "turn body" in `acp.turn_scope()`. That
context manager creates an anyio cancel scope and registers it with the
adapter as the current turn's scope. When the scope exits normally, it
unregisters. When the client calls `session/cancel`, the adapter cancels
that scope (and only that scope), and arranges for `TurnCancelled` to be
raised at the wrapping `except` site so the loop knows this was a client
cancel, not a sample cancel.

**Layer B — what's cancelled.**
Because `generate()` and `execute_tools()` both run *under* that scope as
ordinary awaits, anyio propagates cancellation into them. We do **not** need
to invent new cancellation plumbing for the model call — it's already
cancellable end-to-end (each provider's streaming HTTP call honors
cancellation; `httpx`/`anthropic`/`openai` SDKs all do). Tool calls are
likewise cancellable; tools that have side effects in sandboxes should
handle `CancelledError` to leave the sandbox in a reasonable state (most
already do via `anyio` discipline). The existing `track_active_model_event`
ContextVar lets us *describe* what was interrupted (in the cancel
notification's payload), but it doesn't drive cancellation.

**Layer C — restart.**
After the cancel propagates out of `turn_scope`, the agent calls
`await acp.after_cancel()` which blocks until the client has supplied a
follow-up user message (`session/prompt`). The agent loop continues from
the top of its next iteration with that message appended. From the
agent's perspective: "the last turn ended early; here's what the user
said."

**Edge cases:**
- *Cancel during partial tool result*: the partial result is discarded; the
  tool call appears in the transcript with a `cancelled` status, and the
  adapter injects a **synthetic `ChatMessageTool`** with
  `error="cancelled by user"` so the model on the next turn sees a clean
  pair (assistant tool_call → tool result-cancelled). The synthetic
  message is returned from `after_cancel` alongside the new user message.
- *Cancel after `generate` returned but before tools ran*: we still inject
  the user message; the just-produced assistant message stays in
  `state.messages` (it was a complete model output). The follow-up turn
  treats it as prior context.
- *Cancel between turns*: `turn_scope` isn't open, so cancellation does
  nothing at the scope level — but the adapter still queues the user
  message and the natural `before_turn` call at the top of the next
  iteration picks it up. No state lost.
- *Hard sample cancel (eval shutdown, limit exceeded)*: still routes
  through `ActiveSample.tg.cancel_scope.cancel()` and tears the sample
  down. ACP clients see a final `session/update` with end status and
  socket EOF for that session.

#### Distinguishing turn-cancel from sample-cancel

Two different cancels can hit the same code:
- **Turn cancel** — client calls `session/cancel`; we want to land in
  `except TurnCancelled:` and keep looping.
- **Sample cancel** — `ActiveSample.tg.cancel_scope.cancel()` from
  outside (limit, eval shutdown); we want to unwind the agent and
  terminate the sample.

Mechanism: `turn_scope()` opens an inner anyio `CancelScope`. On
client cancel the adapter:
1. Sets `_pending_turn_cancel = True` on itself.
2. Calls `cancel_scope.cancel()` on the inner scope.

On scope exit, the `turn_scope` context manager:
- If the inner scope caught a cancel **and** `_pending_turn_cancel` is
  set → clear the flag, raise `TurnCancelled`.
- If the inner scope caught a cancel but the flag isn't set → re-raise
  `CancelledError` (sample-level cancel propagating through).
- If no cancel was caught → exit normally.

This works because anyio cancel scopes are nested: the inner scope only
catches a cancel targeted at it (the client cancel does this). A
sample-level cancel targets the outer scope, so the inner scope's
`cancelled_caught` may still be true (anyio re-throws the outer cancel
through the inner scope on exit), but the absent flag tells us not to
treat it as a turn cancel.

#### Race: cancel arrives as turn completes

Sequence: client clicks cancel ↔ turn body finishes normally at roughly
the same moment.

- If the cancel reaches the scope before the turn body returns:
  `CancelledError` raised, becomes `TurnCancelled`. Normal cancel path.
- If the turn body returns first: the scope exits cleanly, the flag was
  set but no cancellation happened. We clear the flag without acting on
  it. The queued user message is picked up by the next iteration's
  `before_turn`.

Either way, the queued user message is honored. `cancel_current_turn()`
is fire-and-forget — it never raises on the caller's side.

#### Cancellation visibility to the agent: simple vs rich

`after_cancel` could return either a flat `list[ChatMessage]` ready to
extend onto `state.messages`, or a richer object describing what was
interrupted. Tradeoffs:

| | Flat `list[ChatMessage]` (chosen) | Rich `CancelResume` object |
|---|---|---|
| Agent code | `state.messages.extend(await acp.after_cancel())` — one line. | Agent must read fields and decide. |
| What the *model* sees | Synthetic tool result + user msg in messages. Model adapts. | Same, but agent can add system-style notes ("you were interrupted while running X"). |
| What the *agent code* can branch on | Nothing — agent treats the new user message as start of next turn. | Can branch on `cancelled="generate"` vs `"tool_call"` to e.g. retry, reset a plan, etc. |
| Adapter complexity | Adapter owns the bookkeeping; agent stays dumb. | Adapter exposes internals; agent's recovery logic gets richer over time. |
| Future flexibility | Agents that *do* want details can still introspect `state.messages` (last assistant message has tool_calls; matching tool message has `error="cancelled by user"`). | Direct, no introspection needed. |
| Risk of premature design | None — agents will tell us when they need more. | We design a struct for hypothetical needs and may not match the real ones. |

Going with the **flat list** for v1. Two reasons:
1. The model itself does the actual recovery work — it reads the
   synthetic tool result + user message and figures out what to do next.
   Agent-level recovery logic (beyond passing the messages along) is
   speculative.
2. If an agent later needs to act on "was this a generate cancel or a
   tool cancel?", it can read the transcript's `InterruptEvent` (which
   *does* carry that detail). We're not losing the information — we're
   just not putting it on the hot path.

Open option for v2: a `cancel_hook` callback an agent can register if it
wants to be notified with the rich detail, separate from the normal
`after_cancel` return value. Keeps the simple case simple.

## Deep dive: approval UI

When ACP clients are attached and Inspect's `approval` framework would
otherwise prompt a human (`human_approver` etc.), the prompt should be
routed to **the attached clients** rather than the local input panel.
Both the in-process TUI client and external editor clients are normal
ACP attachments, so the same mechanism serves both.

**Flow.**
1. Approver decides "I need a human decision" for a pending tool call.
2. Adapter broadcasts an ACP `session/request_permission` to **all**
   attached clients on this session (TUI + any external).
3. Whichever client responds first wins; subsequent responses are
   ignored.
4. Adapter resolves the approval future with the decision; tool
   execution proceeds (or is denied).
5. Adapter sends a `session/update` to the other clients indicating
   the decision was already made (so their UI can clear the pending
   prompt).

**Why broadcast + first-wins:** the user might have both Zed and the
TUI open. Forcing them to pick one channel before answering would be
annoying. Either can approve; whichever fires first is authoritative.

**Fallback.** If no clients are attached at the moment a prompt is
needed, fall back to the existing approver behavior (input panel,
defaults, etc.) — ACP doesn't *replace* the approval system, it just
proxies for it when a human is reachable.

**Timeout.** If clients are attached but none responds within the
configured approval timeout, fall back to default policy (typically
deny) and tell the clients via `session/update`.

Worth designing carefully because approval is the one place where ACP
clients can *block agent progress* outside of the cancel/turn-scope
mechanism. The futures and broadcast must be robust to client
disconnect mid-prompt.

## Deep dive: enumeration & routing

`inspect/listSessions` (internal lookup behind the in-channel picker)
returns the live `_active_samples` list, filtered to samples whose agent
has **claimed ACP support** — i.e., has called `before_turn()` on its
adapter at least once. Agents that never call `before_turn` are not
enumerable as ACP targets (though their transcripts remain observable in
the normal Inspect view).

`sessionId` is a fresh uuid minted when the adapter is claimed (not the
ActiveSample's existing id — we want the ACP session lifetime to be
distinguishable from the sample lifetime, especially if we later support
detach/re-attach).

`(task, sample_id, epoch)` is sufficient to *target* but not to *name* —
we always go through `sessionId` once attached, so the human-targeting
strings only matter at the picker step.

## Resolved decisions (summary)

- The agent-side facade is named **`AcpSession`** (accessor:
  `current_acp_session()`). Maps to ACP's own session vocabulary;
  `AcpClient` was rejected as misleading (in ACP, the editor is the
  client). The transport-side `SessionRouter` keeps its name — the two
  collaborate to implement one ACP session from different sides.
- `AcpSession` is **always installed** with a no-op default; agents call
  it unconditionally.
- Agents **claim ACP** by calling `before_turn()` for the first time. No
  separate capability flag.
- `before_turn` **blocks** only when the agent has no user message yet
  (initial `state.messages` is empty of user content) — otherwise it
  returns queued messages immediately.
- `after_cancel` returns a flat `list[ChatMessage]` (synthetic
  `ChatMessageTool` with `error="cancelled by user"` + new user
  messages, in order ready to extend onto `state.messages`).
- ACP applies to the **top-level agent only**, enforced by "no-op if a
  real adapter is already active in this scope" — checked in the
  `@agent` decorator's entry context manager. No depth counter needed.
- The SessionRouter **filters events** to top-level only, using span
  boundaries emitted by the `@agent` decorator. Sub-agent activity
  appears as a single `tool_call` from the editor's POV.
- The `AcpSession` is **transport-agnostic**; the existing Inspect TUI
  attaches **in-process** with no socket needed. `--agent-acp` controls
  *external* (socket) exposure only.
- Session selection happens **in-channel** (synthetic control session +
  rebind) rather than via CLI args. Stable from the client's POV.
  `session/new` triggers the picker (or auto-binds on single target);
  `session/load(<known>)` binds directly; `session/load(<unknown>)`
  returns `invalid_params` rather than falling back to picker — silent
  rebind of an explicit `session/load` call would surprise the client.
- **Multiple concurrent connections to different sessions** are supported
  by default. Within one session: one driver + read-only observers.
- A **`InterruptEvent`** in the transcript records every cancellation
  (user, limit, system) for a uniform record of "agent was interrupted".
- User messages injected via ACP are marked
  **`ChatMessageUser(source="operator")`** — extending the existing
  `source` literal from `"input" | "generate"` to
  `"input" | "generate" | "operator"`.
- Cancelled tool calls are repaired with **synthetic
  `ChatMessageTool(error="cancelled by user")`** in `state.messages`.

## Open questions

1. **Replay on attach** — replay last N messages (configurable), eliding
   large tool call payloads. Pick the default N and elision threshold.

2. **Driver claim mechanics in multi-attach** — implicit (last
   `session/prompt` wins) vs explicit (a `inspect/claimDriver` extension).
   Lean toward implicit for v1.

3. **Token-level streaming** — requires hooking into the provider stream
   before the message is finalized. Cleanest path is a streaming hook on
   the model provider that the adapter subscribes to. Phase 4.

4. **Span tagging for sub-agent boundaries** — verify the `@agent`
   decorator's current span shape and add the marker attribute we need;
   confirm `as_tool` / `handoff` / deepagent dispatch all go through it.

5. **`InterruptEvent` schema details** — pick concrete fields and confirm
   they survive transcript serialization / log replay.

6. **Approval timeout default** — when clients are attached but no one
   responds to a `session/request_permission`, pick a sensible default
   timeout and fallback policy.

## Implementation

### Guidelines

1. **One phase at a time.** Create a dedicated plan for the phase. Do not proceed with implementation or exit plan mode until the user has approved the plan. Implement, test, and verify each phase before moving to the next.
2. **Review before commit.** After tests pass, pause and review the code together before committing. Do not auto-commit.
3. **Full tests at each step.** Every phase produces both implementation and tests.
4. **Update this document.** After completing a phase but before committing, replace the phase's overview section below with a summary of what was actually built and tested — files created/modified, key design decisions made during implementation, and test coverage.

### Phase ordering rationale

Phases are ordered to maximize independent testability and incremental commit value. Phases 1–6 land the **in-process foundation** — each adds a self-contained piece exercisable with unit tests against a mock model. Phase 7 makes the foundation **immediately user-visible** by wiring the existing TUI to it (without `--agent-acp` needing to exist yet). Phases 8–10 add the **socket transport**. Phase 11 ships the **`inspect acp` CLI**. Phase 12 extends to **`deepagent()`**. Phases 13–14 add **approval UI** and **token streaming** as standalone enhancements.

Anyone reading the codebase mid-implementation should be able to use the features landed in phases 1–7 (interactive TUI control of a running agent) even before sockets exist — that's the design's payoff for separating transport from agent contract.

### Phase 1: `AcpSession` types, factory, and accessors

Foundation types only — no agent integration, no cancellation mechanics, no schema changes (all deferred to later phases).

**Files created:**
- `src/inspect_ai/agent/_acp/__init__.py` — package re-exports.
- `src/inspect_ai/agent/_acp/_session.py` — Protocol, no-op impl, real impl, ContextVar, factory, accessor (all in one module).
- `tests/agent/acp/__init__.py` — test package marker.
- `tests/agent/acp/test_session.py` — 15 unit tests.

**Files modified:**
- `src/inspect_ai/agent/__init__.py` — added `AcpSession` and `acp_session` to imports and `__all__`. `current_acp_session` is intentionally *not* surfaced at the top level — agent authors don't need it, only internal code that wants to peek the active session without entering a scope does. Import it via `from inspect_ai.agent._acp import current_acp_session` if needed.

**What landed:**
- `AcpSession` — `@runtime_checkable` Protocol with Phase 1 surface only: `session_id`, `__aenter__`, `__aexit__`, `attach()`, `detach()`, `publish()`. Cancel / turn / user-message-queue methods are explicitly *not* on the Protocol — those are added in Phase 3.
- `_NoOpAcpSession` — null-object impl; `session_id == "noop"` sentinel; `attach()` returns an already-closed receive stream; `detach()` / `publish()` are no-ops.
- `_LiveAcpSession` — owns the in-process pub/sub bus. Per-subscriber `anyio.create_memory_object_stream` with bounded buffer (256). `publish()` uses `send_nowait`; on `WouldBlock` logs a warning naming the session and drops the update. `__aexit__` closes every subscriber send-half so receivers see clean EOF.
- `acp_session()` — `@asynccontextmanager` factory; installs a fresh `_LiveAcpSession` on the outermost entry, a fresh `_NoOpAcpSession` on any nested entry (shadow-if-active rule).
- `current_acp_session()` — peek accessor returning the ContextVar's value (no-op singleton by default). Exported from `inspect_ai.agent._acp` only; not surfaced at the top-level `inspect_ai.agent` namespace.
- `AcpUpdate = dict[str, Any]` placeholder; Phase 6 will tighten to a `session/update` union.

**Design decisions made during implementation:**
- Fresh `_NoOpAcpSession` per shadowed scope (rather than reusing the global singleton): one extra allocation per nested entry, but cleaner identity semantics — `inner is outer` is always false in nested scopes.
- `_NOOP_SESSION_ID = "noop"` sentinel string returned by the no-op's `session_id` avoids `isinstance` guards in downstream code.
- `_is_noop(session)` helper centralizes the type check; the factory uses it rather than raw `isinstance`.
- The user-message queue slot and turn cancel scope slot mentioned in the original phase description were *deferred to Phase 3* — Phase 1 strictly delivers types, factory, accessors, and pub/sub. Adding queue/cancel slots without their consumers would leave dead state.

**Test coverage (15 tests, all pass under both asyncio and trio):**
1. `current_acp_session()` outside any scope returns no-op (`session_id == "noop"`).
2. Real session installed inside `async with acp_session()`; `session_id` stable across reads.
3. ContextVar resets to no-op after scope exits.
4. Nested scope is no-op shadow; `current_acp_session()` returns inner inside, outer after inner exits.
5. Publish reaches a single subscriber.
6. Publish fans out to multiple subscribers.
7. Detach closes the subscriber; subsequent publish does not raise.
8. Publish after detach is safe for remaining subscribers.
9. Subscriber sees `anyio.EndOfStream` after session exits.
10. No-op `attach()` returns an already-closed stream.
11. No-op `publish()` / `detach()` are safe.
12. Concurrent `anyio` tasks with overlapping `acp_session()` scopes (both held open via two events) each see their own session via `current_acp_session()` — proves ContextVar isolation under genuine overlap, not just sequential entry.
13. `publish()` prunes a subscriber whose receive half was closed by the consumer — prevents dead streams from accumulating across calls.
14. Bounded-buffer drop-on-full: filling the buffer is silent; the next publish drops with a single logger.warning naming the session.
15. Both real and no-op satisfy the `AcpSession` Protocol via `isinstance`.

Verification: `pytest tests/agent/acp/ -v` (14 passed asyncio); `pytest tests/agent/acp/ --runtrio -v` (14 passed trio); `mypy --exclude tests/test_package src/inspect_ai/agent/_acp src/inspect_ai/agent/__init__.py tests/agent/acp` clean; `ruff format` / `ruff check --fix` clean; public API import smoke succeeds.

### Phase 2: Transcript primitives — `InterruptEvent` and `source="operator"`

Schema-level changes to record cancels and operator-injected messages in the transcript. No agent integration; primitives only.

**Files created:**
- `src/inspect_ai/event/_interrupt.py` — `InterruptEvent` class.
- `tests/log/test_interrupt_event.py` — 12 unit tests.
- `src/inspect_ai/_view/ts-mono/packages/inspect-components/src/transcript/InterruptEventView.tsx` — new ts-mono view component.

**Files modified:**
- `src/inspect_ai/model/_chat_message.py` — extended `ChatMessageBase.source` from `Literal["input", "generate"] | None` to `Literal["input", "generate", "operator"] | None`.
- `src/inspect_ai/event/_event.py` — added `InterruptEvent` to the `Event` union.
- `src/inspect_ai/event/__init__.py` — re-exported `InterruptEvent`.
- `src/inspect_ai/log/_transcript.py` — added module-level `record_interrupt_event(...)` helper that appends to the current transcript via `transcript()._event(...)`. Kept as a module function rather than a `Transcript` method since callers are internal-only (Phase 3's cancellation machinery) and we don't want to grow the public `Transcript` API for it.
- `src/inspect_ai/_view/inspect-openapi.json` — regenerated to include the new event and the extended source Literal.
- `src/inspect_ai/_view/ts-mono/packages/inspect-common/src/types/generated.ts` — regenerated TypeScript types.
- `src/inspect_ai/_view/ts-mono/packages/inspect-common/src/types/index.ts` — exported `InterruptEvent`.
- `src/inspect_ai/_view/ts-mono/packages/inspect-components/src/transcript/types.ts` — added `InterruptEvent` to `EventType` union and `"interrupt"` to `eventTypeValues`.
- `src/inspect_ai/_view/ts-mono/packages/inspect-components/src/transcript/icons.ts` — added `interrupt: "bi bi-slash-circle"`.
- `src/inspect_ai/_view/ts-mono/packages/inspect-components/src/transcript/TranscriptVirtualList.tsx` — added `case "interrupt":` dispatch to `InterruptEventView`.

**What landed (Python):**
- `InterruptEvent(BaseEvent)` — `event: Literal["interrupt"]` discriminator; required fields `source: Literal["user_cancel", "limit", "system"]` and `interrupted: Literal["generate", "tool_call", "between_turns"]`; optional `interrupted_tool_call_id: str | None` (cross-ref to `ToolEvent.id`) and `interrupted_model_event_id: str | None` (cross-ref to `ModelEvent.uuid`).
- `record_interrupt_event(...)` — module-level keyword-only helper that constructs and appends the event to the current transcript. Internal API; not surfaced on `Transcript` itself.
- `ChatMessageBase.source` now accepts `"operator"` for ACP-injected user messages. No `_trim.partition_messages` change: operator messages flow into `conversation` (not `input`) because `"input"` is reserved for the original sample input; runtime injections belong with the model-generated conversation.

**What landed (TypeScript ts-mono):**
- `InterruptEvent` type generated from the OpenAPI schema, exported from `@tsmono/inspect-common/types`.
- `InterruptEventView` renders the event with a `bi-slash-circle` icon and human-readable titles (e.g. "Interrupted by user" / "during model generation"). Wired into the transcript dispatch switch.
- `"interrupt"` added to the `eventTypeValues` runtime array.

**Design decisions:**
- Field name: `interrupted_tool_call_id` (not `interrupted_tool_id` as the earlier design sketch had) — disambiguates from "tool name" and matches Inspect's `ToolCall.id` convention. Design-doc schema sketch updated to match.
- Helper exposed as a module-level `record_interrupt_event(...)` rather than `Transcript.interrupt(...)` — keeps the public `Transcript` API lean since the only callers are internal Inspect code (Phase 3's cancellation machinery). Implementation just calls `transcript()._event(InterruptEvent(...))`.
- `partition_messages` left untouched: operator messages should flow into `conversation` per the rationale above (`"input"` is reserved for original sample input).
- Bootstrap icon `bi bi-slash-circle` chosen for `interrupt` — semantically signals "stopped / cancelled" and is consistent with the icons.ts hardcoded-string convention.

**Test coverage (12 tests):**
1. Construct `InterruptEvent` with required fields; optional ids default to None.
2. Construct with both optional ids set; values preserved.
3. Inherits `BaseEvent` fields (`uuid`, `timestamp` auto-populated).
4. `source="bogus"` raises `ValidationError`.
5. `interrupted="bogus"` raises `ValidationError`.
6. Roundtrip via `TypeAdapter(Event).validate_python(model_dump())` — restored instance is an `InterruptEvent` with matching `uuid` and all fields preserved.
7. `record_interrupt_event(...)` appends correctly to the active transcript (via `_transcript.set`).
8. `ChatMessageUser(source="operator")` constructs.
9. All three source values (`"input"`, `"generate"`, `"operator"`) accepted.
10. `source="bogus"` on `ChatMessageUser` raises.
11. `ChatMessageUser(source="operator")` model_dump roundtrips.
12. `partition_messages` puts operator messages in `conversation`, not `input` — confirms the deliberate design choice.

Verification: `pytest tests/log/test_interrupt_event.py` (12 passed); `pytest tests/log/ tests/model/test_trim_messages.py tests/model/test_compaction.py tests/agent/acp/` (502 passed, no regressions); `ruff format` / `ruff check` clean; `mypy --exclude tests/test_package` clean (30 source files); `pnpm --filter @tsmono/inspect-common typecheck` / `pnpm --filter @tsmono/inspect-components typecheck` / `lint` all clean; `prettier --write` clean.

### Phase 3: Turn scope and cancellation mechanics

The core cancel/inject machinery on `AcpSession`. No `react()` integration — exercised purely by unit tests against synthetic turn bodies.

**Files created:**
- `tests/agent/acp/test_cancel.py` — 18 unit tests covering all turn/cancel/inject paths under both asyncio and trio.

**Files modified:**
- `src/inspect_ai/agent/_acp/_session.py` — extended Protocol, `_LiveAcpSession`, and `_NoOpAcpSession` with the Phase 3 surface; added `TurnCancelled` exception. ~300 → ~545 LoC, still single-file.
- `src/inspect_ai/tool/_tool_call.py` — added `"cancelled"` to `ToolCallError.type` Literal.
- `src/inspect_ai/_view/inspect-openapi.json` — regenerated to include the extended `ToolCallError.type` enum.
- `src/inspect_ai/_view/ts-mono/packages/inspect-common/src/types/generated.ts` and `apps/scout/src/types/generated.ts` — regenerated TS types for the new `"cancelled"` enum value.

**What landed:**
- `TurnCancelled(Exception)` — distinct from `CancelledError`. Raised on scope exit only when the cancel was client-driven (via `cancel_current_turn`). Sample-level `CancelledError` propagates through unchanged.
- `acp.turn_scope()` — sync `@contextmanager` wrapping an `anyio.CancelScope`. Resets `_pending_turn_cancel` and `_cancelled_tool_call_ids` at entry; on exit, raises `TurnCancelled` iff `scope.cancelled_caught and _pending_turn_cancel`. Discriminator works because anyio's inner scope only catches cancels targeted at it; outer-scope cancels propagate unswallowed.
- `acp.before_turn(state)` — drains queued user messages. Blocks only on the *first call* and only if `state.messages` has no `ChatMessageUser` yet — covers the "no dataset prompt, operator types the first message" case. Subsequent calls drain non-blockingly. Uses an `anyio.Event` reset-after-wait pattern (copied from `_util/future.py`).
- `acp.after_cancel()` — returns synthetic `ChatMessageTool(error=ToolCallError(type="cancelled", ...))` for every cancelled tool call followed by drained operator user messages. Blocks until at least one user message is available. Returned list is ready to extend onto `state.messages`.
- `acp.submit_user_message(msg)` — normalizes provenance (always sets `source="operator"` via `model_copy`, even if the caller passed `source=None` or `source="input"`) so the canonical Phase 2 provenance marker is applied uniformly; queues and signals the event. The caller's original instance is not mutated.
- `acp.cancel_current_turn()` — fire-and-forget. Snapshots in-flight state (active tool calls > `_active_model_event` > "between_turns"), emits `InterruptEvent(source="user_cancel", ...)` via Phase 2's `record_interrupt_event`, and cancels the turn scope if one is active.
- `acp.track_tool_call(tool_call_id)` — sync `@contextmanager` that pushes/pops onto the in-flight tool list. Phase 4 wires it into `_call_tools.py`; Phase 3 tests use it directly to simulate "a tool is mid-flight". Because nested-agent tool calls go to the no-op session (Phase 1's shadowing rule), only top-level tool calls land here — exactly what the ACP-visible interrupt record needs.
- `acp.track_model_event(event)` — sibling `@contextmanager` storing the in-flight `ModelEvent` **on the session** (save/restore semantics for nesting). Phase 4 will wrap each model generation in it. Critical: the previous design read from the existing `_active_model_event` ContextVar, which is task-local and invisible to a cancelling transport task running in a sibling task — so cancels would have been mis-recorded as `between_turns`. Storing on the session ensures the cancelling task sees the right value.
- `_NoOpAcpSession` — no-op implementations of every Phase 3 method. `cancel_current_turn()` deliberately does **not** call `record_interrupt_event` (sub-agents must not emit cancel events into the top-level transcript).

**Design decisions during implementation:**
- `AgentState` and `ModelEvent` typed via `TYPE_CHECKING` forward references to avoid runtime import cycles (`inspect_ai.agent._agent` may import from `_acp` in Phase 4; `inspect_ai.event._model` pulls in the whole event/scorer/log subsystem).
- Multi-tool-call cancel: `InterruptEvent.interrupted_tool_call_id` records only the *first* in-flight id (schema is a single string); `after_cancel()` synthesizes repair messages for *all* in-flight tool calls so `state.messages` stays consistent. Acceptable v1 tradeoff per the design doc — schema can be widened later (forward-compatible).
- Cancel between turns (no active scope): the `InterruptEvent` is still recorded; the scope-cancel call is skipped; queued messages survive for the next `before_turn`. Tested explicitly.
- `"cancelled"` value added to `ToolCallError.type` Literal — same forward-compatible additive pattern Phase 2 used for `source="operator"`; triggered the standard schema + TS regen flow.

**Test coverage (21 tests, all pass under asyncio + trio):**
1. `turn_scope` exits cleanly with no cancel.
2. Client cancel raises `TurnCancelled`.
3. Sample-level (outer-tg) cancel propagates as `CancelledError`, not `TurnCancelled`.
4. `submit_user_message` then non-blocking `before_turn` returns the message.
5. `before_turn` blocks on first call with empty `state.messages`.
6. `before_turn` non-blocking on second call with empty state (`anyio.move_on_after` verifies).
7. `after_cancel` drains queued messages.
8. `after_cancel` synthesizes `ChatMessageTool` for in-flight tool, then queued user message.
9. Multiple in-flight tool calls each get a repair message.
10. `after_cancel` blocks until a message arrives if the queue is empty.
11. Cancel during tool call emits `InterruptEvent(interrupted="tool_call", interrupted_tool_call_id=...)`.
12. Cancel during generate emits `InterruptEvent(interrupted="generate", interrupted_model_event_id=...)`.
13. Cancel between turns emits `InterruptEvent(interrupted="between_turns")` with no ids.
14. Cancel between turns preserves queued messages.
15. `turn_scope` resets `_pending_turn_cancel` and `_cancelled_tool_call_ids` between turns.
16. `track_tool_call` removes id on exception cleanup.
17. `_NoOpAcpSession` variants are all safe; no `InterruptEvent` recorded.
18. Race: cancel arrives just as turn completes — no exception, queued message survives.
19. Cancel during generate (`track_model_event` + cancel from sibling task) emits `InterruptEvent(interrupted="generate", interrupted_model_event_id=...)` — proves cross-task visibility via the session-stored event.
20. `track_model_event` nested save/restore — outer event is restored after inner exits.
21. `submit_user_message` normalizes source: `None`, `"operator"`, and `"input"` all end up as `"operator"`. Caller's instance is not mutated (`model_copy` is used).

Verification: `pytest tests/agent/acp/` (33 passed asyncio + 33 passed trio across Phase 1 + Phase 3); `pytest tests/log/test_interrupt_event.py tests/model/test_trim_messages.py tests/model/test_compaction.py` (75 passed, no regressions); `ruff format` / `ruff check` clean; `mypy --exclude tests/test_package` clean (6 source files); `pnpm typecheck` / `lint` / `test` across ts-mono all clean (348 TS tests pass, no regressions in inspect/scout apps from the `ToolCallError.type` extension).

### Phase 4: `react()` integration

The cancel/inject contract from Phase 3 wired into the real agent loops. No production API changes; Phase 1's shadow-with-no-op factory rule stays exactly as-is.

**Files modified:**
- `src/inspect_ai/agent/_react.py` — spliced `react()` and `react_no_submit()`. `acp_session()` opens alongside `checkpointer()` and `mcp_connection()` in the top-level `async with`. Each loop iteration calls `await acp.before_turn(state)` to drain operator messages. The turn body (generate + execute_tools + submission handling) runs inside `with acp.turn_scope():`. `TurnCancelled` is caught immediately after; `await acp.after_cancel(state.messages)` returns repair + follow-up messages and the loop continues. `on_continue` hook and checkpointer `tick` stay *outside* the turn scope.
- `src/inspect_ai/agent/_acp/_session.py` — `after_cancel()` now accepts an optional `messages` parameter and (when provided) scans the last assistant message's `tool_calls` to synthesize a repair for *every* unanswered id, not just those in `_cancelled_tool_call_ids`. This handles the sequential-execution case where the model returned multiple tool calls in one message and a later call was cancelled — the earlier completed call's result is lost when `_execute_tools_impl` is interrupted before returning, and the never-started later calls have no result either. Without this fix, providers that require complete tool_call/result pairing reject the next turn. Also: `cancel_current_turn` now clears `pending=True` on the in-flight `ModelEvent` and `ToolEvent`s — anyio cancellation bypasses the normal completion paths that would otherwise clear the flag, leaving cancelled rows shown as forever in-flight in the transcript / log viewer. `track_tool_call` accepts an optional `event` parameter so the session can register it for that purpose.
- `src/inspect_ai/model/_call_tools.py` — each individual tool call dispatch is wrapped with `current_acp_session().track_tool_call(call.id, event)` so the session's `_in_flight_tool_calls` is accurate at cancel time and the event's `pending` flag can be cleared on cancel. Local import to avoid circular dependency.
- `src/inspect_ai/model/_model.py` — `current_acp_session().track_model_event(event)` nested inside the existing `track_active_model_event(event)` so cancels see the right `ModelEvent.uuid` from sibling tasks. Both contexts coexist in a tuple `with` statement.
- `src/inspect_ai/model/_providers/mockllm.py` — `generate()`'s callable path now awaits if the result is awaitable, letting tests use `async def` callables that `await anyio.sleep(...)` to simulate slow generates.

**Files created:**
- `tests/agent/test_acp/_capture.py` — test helper: `capture_session_tool(captured, ready)` (captures the live `AcpSession` from inside react via a tool call) and `slow_tool_with_event(release)` (blocks until the test releases it).
- `tests/agent/test_acp/test_react_integration.py` — 8 end-to-end tests.

**Files renamed:**
- `tests/agent/acp/` → `tests/agent/test_acp/` (with all existing tests) — avoids a sys.path collision with the installed Zed `acp` Python package, which broke `inspect_swe._registry` entrypoint loading. The collision didn't bite Phases 1/3 but Phase 4's import chain triggered it.

**What landed (production):**
- Splicing react with `async with acp_session() as acp:` is unconditional. Production code without an ACP client transparently gets the live-session-then-discard path; the session's pub/sub bus has no subscribers; cancel methods never fire; transcript stays unchanged.
- Sub-agent isolation is preserved by Phase 1's existing shadowing rule: a sub-agent invoked via `as_tool`/`handoff` opens its own `acp_session()` which shadows the parent's session with a no-op. `track_tool_call` / `track_model_event` called from sub-agent code paths target the no-op; nothing leaks into the parent's ACP-visible record. No new mechanism added for this.
- The `acp_session()` lifecycle wraps everything below it: when react exits naturally (model returns no tool calls / submits), the `async with` block ends, `__aexit__` closes pub/sub subscribers, scoring runs as before. No agent-keeps-alive behavior in v1.

**Design decisions during implementation:**
- Hoisted `acp_session()` up alongside `checkpointer()` and `mcp_connection()` in the top-level `async with` (per user feedback) — cleaner symmetry; all three lifecycle context managers share the same scope.
- Per-tool-call wrap lives in `call_tool_task` (the per-call inner async function in `_call_tools.py`) so parallel tool calls each get their own track scope. The session's `_in_flight_tool_calls` correctly tracks all in-flight ids; cancel records the first and `after_cancel` repairs all.
- The model event wrap uses a tuple `with` statement nested inside `track_active_model_event` — both ContextVar (for log writers) and session-level (for ACP cancel snapshot) tracking coexist cleanly.
- **Test strategy: capture-via-tool.** Tests can't reach react's internal `_LiveAcpSession` from a sibling task (ContextVar task-inheritance forks before react's `acp_session()` enters). The test helper provides a tiny `capture_session` tool that captures `current_acp_session()` *from inside* react's execution and exports it to the test via a shared dict + `anyio.Event`. The producer task awaits the event, then drives the captured session externally. Zero production-API changes; uses real code paths.
- `get_model(...)` must be called with `memoize=False` in tests — Inspect memoizes by default, so without it the same mockllm instance (with its custom_outputs already exhausted) gets reused across tests in the same pytest run.
- mockllm tweak (`await output if awaitable`) is a small additive enhancement; existing sync-callable usage unchanged.

**Test coverage (11 tests, asyncio + trio):**
1. `react()` runs unchanged when no ACP producer is attached (no-op default path).
2. `track_model_event` populates `session._active_model_event` during a slow generate.
3. `track_tool_call` populates `session._in_flight_tool_calls` during slow tool execution.
4. Cancel mid-generate → `TurnCancelled` handled, follow-up message picked up, react completes via a later mockllm output.
5. Cancel mid-tool-call → synthetic `ChatMessageTool(error=ToolCallError(type="cancelled", ...))` lands in `state.messages` followed by the queued user message.
6. Cancel mid-generate also emits an `InterruptEvent(source="user_cancel", interrupted="generate", interrupted_model_event_id=<uuid>)` to the transcript.
7. Operator message submitted between turns appears in next iteration's `state.messages` with `source="operator"` (Phase 3 normalization).
8. `react_no_submit()` honors the splice (cancel-mid-tool test against it).
9. Cancel during a multi-tool batch produces a synthetic repair `ChatMessageTool` for *every* unanswered tool_call_id in the last assistant message — not just the one in flight at cancel time.
10. Cancelled `ModelEvent` and `ToolEvent` rows have `pending` cleared (`is None`) in the transcript — verifying the workaround for anyio-bypassed completion paths.
11. `cancel_current_turn` calls `transcript()._event_updated(event)` on each cancelled event — verified via a spy on the transcript hook. Without this notification, log writers / hook subscribers would never see the cleared pending state even though the in-memory list shows it.

Verification: `pytest tests/agent/test_acp/` (47 passed asyncio + 47 passed trio); `pytest tests/agent/test_agent_react.py` (21 passed, no regressions); `pytest tests/agent/test_acp/ tests/agent/test_agent_react.py` combined (68 passed); `ruff format`/`check` clean across all 9 modified/created files; `mypy` clean. No TS/OpenAPI regen needed (Phase 4 is pure Python wiring).

### Phase 5: `@agent` sub-agent boundary marker

Lock in the existing `type="agent"` span convention so Phase 6's event router can identify sub-agent boundaries from the transcript event stream. **Simplification from the original design** — exploration showed the marker already exists at every agent-invocation path, so no new `attributes` field on `SpanBeginEvent` is needed; no schema change, no TS regen.

**Files modified:**
- `src/inspect_ai/util/_span.py` — added `AGENT_SPAN_TYPE = "agent"` constant with a docstring explaining the convention.
- `src/inspect_ai/agent/_run.py:93` — replaced literal `type="agent"` with `type=AGENT_SPAN_TYPE`.
- `src/inspect_ai/agent/_as_tool.py:67` — same.
- `src/inspect_ai/agent/_as_solver.py:71` — same.
- `src/inspect_ai/model/_call_tools.py:583` — same (handoff dispatch's inner agent span; the outer `type="handoff"` and `type="tool"` spans are unrelated).

**Files created:**
- `tests/agent/test_acp/test_span_boundary.py` — 7 regression tests.

**What landed:**
- A single `AGENT_SPAN_TYPE` constant in `src/inspect_ai/util/_span.py` is the shared name for both producers (the four span call sites that wrap agent invocations) and Phase 6's eventual consumer (the router that counts nesting depth).
- All five known agent-invocation paths bottom out through `span(name=..., type=AGENT_SPAN_TYPE)`:
  - `agent.run()` invocation
  - `as_tool(agent)` invocation
  - `as_solver(agent)` invocation
  - `handoff(agent)` dispatch (inside `_call_tools.py`'s handoff branch)
  - deepagent task_tool → routes through `agent.run()`

**Design decisions during implementation:**
- The original design doc proposed adding a new `attributes["agent.boundary"] = True` marker on `SpanBeginEvent`. Rejected because:
  - `SpanBeginEvent.type` is already a serialized string field; using `type == "agent"` requires no schema change.
  - Adding a Pydantic `attributes` field would trigger OpenAPI/TS regen + scout submodule regen for zero functional gain.
  - The router can simply check `span.type == AGENT_SPAN_TYPE`, no new infrastructure.
- The `@agent` decorator itself does **not** emit spans. Spans are emitted at every invocation path. Phase 5 marks all of them via the constant; no decorator change needed.
- Sub-agent isolation now has two complementary layers in the codebase:
  1. **ACP session shadowing** (Phase 1's `acp_session()` factory rule) — sub-agents that call `react()` open their own no-op session and can't drive the parent's ACP client.
  2. **Span-boundary marking** (Phase 5) — Phase 6 will count nested boundary spans and drop events at depth > 1 from the `session/update` stream.

**Test coverage (7 tests):**
1. `AGENT_SPAN_TYPE` is the literal `"agent"` — protects against accidental renames that would break the wire format.
2. `agent.run(agent, ...)` opens a single `type="agent"` `SpanBeginEvent` with the agent's name.
3. `as_solver(agent)` invocation opens the boundary span.
4. react with an `as_tool` sub-agent: assert **two** boundary spans (parent + sub) — the canonical Phase 6 nesting case.
5. react with a `handoff(agent)` invocation: assert the handoff's inner boundary span is emitted.
6. Top-level `react()` invoked via `run()` opens its own boundary span.
7. **Grep-style guard**: walks the entire `src/inspect_ai` tree for `span(...type="agent"...)` literal usage and fails if any remain — protects against new agent-invocation paths silently skipping the marker.

Verification: `pytest tests/agent/test_acp/` (52 passed asyncio + 52 passed trio); `pytest tests/agent/test_acp/ tests/agent/test_agent_react.py` combined (75 passed, no regressions); `ruff format`/`check` clean; `mypy` clean (6 source files). No OpenAPI/TS regen needed.

### Phase 6: Event router with top-level filter ✅

Landed an in-process event router that converts top-level transcript events into `acp.SessionNotification` payloads and publishes them onto the Phase 1 pub/sub bus.

**What was built:**

1. **Multi-cast `Transcript._add_subscriber(cb) -> unsubscribe`** in `src/inspect_ai/log/_transcript.py`. Coexists with the legacy single-slot `_subscribe()` used by the eval runner's log writer. Multiple subscribers all fire on every event; each runs in a try/except so a failing subscriber doesn't block siblings or the agent loop.
2. **`_AcpEventRouter`** in `src/inspect_ai/agent/_acp/_router.py`. Attached at `_LiveAcpSession.__aenter__`, detached at `__aexit__`. Tracks sub-agent nesting depth by pairing `SpanBeginEvent(type=AGENT_SPAN_TYPE)` / `SpanEndEvent` by id (defensive against unknown ends). Maps `ModelEvent` text blocks → `AgentMessageChunk(TextContentBlock)`, reasoning blocks → `AgentThoughtChunk(TextContentBlock)`, `ToolEvent` first sight → `ToolCallStart(in_progress|completed)`, post-completion updates → `ToolCallProgress(completed|failed)`. Tracks first-sight tool ids so the pending → completed transition routes correctly.
3. **Configurable sub-agent filter.** `_LiveAcpSession._filter_subagent_events: bool = True` (default ACP semantic — editors see only the outer conversation) with public-ish `disable_subagent_filtering()` method. The router consults the flag on every event; the in-process TUI (Phase 7) and other consumers who want full granularity can opt out.
4. **No `inspect.events` extension yet.** Mapping the Inspect-native event family (`InfoEvent`, `CompactionEvent`, `InterruptEvent`, etc.) onto ACP's `_meta` extension point is deferred to Phase 8+. ACP's `session/update` discriminated union is strict (no unknown variants accepted), and none of the existing variants (`SessionInfoUpdate`, `UsageUpdate`, `AgentPlanUpdate`) are inert no-op carriers — `SessionInfoUpdate.title=null` and `updated_at=null` are *destructive* clears per the schema docs. Without the `initialize` handshake (Phase 8+) there's no capability-negotiation path for clients to opt in, so Phase 6 ships the safer minimum: silently drop these events. The router's `_map` dispatch is keyed on `type(event)` so adding the mapping later is a one-line change.

**Phase 7 implication (decided during planning):** the Inspect-native TUI will **not** subscribe to the router's `SessionNotification` stream — instead it'll subscribe to the transcript directly, preserving the existing event-stream display (which shows sub-agent internals at full granularity). The TUI only uses `AcpSession` for the producer-side `cancel_current_turn()` and `submit_user_message()`. This avoids dragging users from the current per-event view into an editor-shaped chunked-message view.

**Test coverage:**

- `tests/log/test_transcript_subscribers.py` (5 tests): subscriber ordering, multi-cast, legacy `_subscribe` coexistence, unsubscribe idempotence, exception isolation.
- `tests/agent/test_acp/test_router.py` (21 tests): depth tracking (agent vs non-agent spans, unknown-end defense), filter behavior (default ON drops sub-agent events; `disable_subagent_filtering()` flips it), detach removes subscription, mapping (`ModelEvent` text → `AgentMessageChunk`, reasoning → `AgentThoughtChunk`, mixed-block order, pending/empty drop), `ToolEvent` first sight → `ToolCallStart(in_progress)`, second sight → `ToolCallProgress(completed|failed)`, `_tool_call_status` helper, all currently-unmapped events drop silently, plus three integration tests against react/mockllm (notifications publish end-to-end, sub-agent isolation by default, sub-agent visibility when filter disabled).

**Phase 5 pivot ratified by the integration tests.** Sub-agent isolation works because every agent-invocation path opens a `type="agent"` boundary span; the router relies on this to scope its filter without coupling to react internals.

Verification: `pytest tests/agent/test_acp/ tests/log/test_transcript_subscribers.py` (101 passed asyncio); `--runtrio` passes (55 trio variants); `ruff format`/`check` clean; `mypy` clean. No OpenAPI/TS regen needed — Phase 6 is pure consumer code reading existing Inspect event types and producing acp-package objects.

### Phase 7: Inspect-native TUI — Interrupt + interject prompt ✅

Wires producer-side ACP interactivity into the existing Textual TUI (`--display full`'s Running Samples view), **deliberately scoped down** from the original plan: the TUI does NOT subscribe to `SessionNotification`s. It keeps rendering events via the existing transcript-based display (preserving sub-agent granularity that power users rely on for debugging) and uses the `AcpSession` channel only for two producer-side actions: `cancel_current_turn()` and `submit_user_message()`.

The motivation: typing-at-the-model as a *primary* always-on UI element is too aggressive — one-keystroke interventions are easy to fire by accident and inherently non-reproducible. Phase 7 gates injection behind a deliberate Interrupt button + transient prompt input, so operator messages are a considered action with a clear boundary in the transcript (the `InterruptEvent` from Phase 2 + the `ChatMessageUser(source="operator")` returned by `after_cancel`).

**What was built:**

1. **`ActiveSample.acp_session` field** in `src/inspect_ai/log/_samples.py`. `TYPE_CHECKING`-guarded import for the `AcpSession` type hint; default `None`.
2. **`_LiveAcpSession.__aenter__`/`__aexit__` splice** in `src/inspect_ai/agent/_acp/_session.py`. On entry looks up `sample_active()` and assigns `self` to its `acp_session`. On exit clears with an `is self` identity guard so a stale `__aexit__` from a race never clobbers a different live session. `_NoOpAcpSession` continues to do nothing on enter/exit, so sub-agent shadow sessions never overwrite the outer live session.
3. **Interrupt button** on the `SampleInfo` header (`samples.py`) at the top-right alongside the existing "View Log" link. `Button(variant="warning")` with id `interrupt-sample`. Visibility is recomputed on every `sync_sample` based on `sample.acp_session is not None and acp_session.session_id != "noop"` — explicitly OUTSIDE the early-return guard, since the ACP session can come and go without the sample identity changing. Click handler fires `acp.cancel_current_turn()` and switches the sibling `SampleToolbar` into prompt mode via direct widget reference.
4. **Prompt mode on `SampleToolbar`**. Adds an `Input(placeholder="Type a message for the model (e.g. 'please continue')")` and a `Send` button, both hidden by default. The Interrupt click flips a `_prompt_mode` flag, hides the status group + cancel buttons, reveals + auto-focuses the Input. Submission (Enter or Send) builds `ChatMessageUser(content=text)` and calls `acp.submit_user_message(msg)` — Phase 3's normalization stamps `source="operator"`. Empty input is silently ignored (spec: user must enter something to resume the agent). `sync_sample` auto-exits prompt mode on sample switch, sample completion, or ACP session loss, so the toolbar always recovers cleanly.
5. **Interrupt button styled `warning`** (yellow). The pre-existing Timeout Tool / Cancel (Score) / Cancel (Error) buttons retain their original neutral styling — the yellow Interrupt is distinct enough on its own without recoloring the others.

**Why fire-and-forget on `cancel_current_turn()`?** Phase 3 made the method synchronous and idempotent — it records the `InterruptEvent`, snapshots in-flight tool/model events for repair, marks cancelled tool events as `failed` with `ToolCallError(type="cancelled")` (per the Phase 6 fixes), clears their `pending` flags, and cancels the turn scope. The agent's `react()` loop catches `TurnCancelled` inside `turn_scope()`, calls `after_cancel(messages)` which synthesizes any tool repair messages and **blocks** until the user-message queue is non-empty. Our TUI submission unblocks it. The TUI's button-click → cancel → mode-switch sequence is purely synchronous; resume happens out-of-band on the agent task.

**Test coverage:**

- `tests/agent/test_acp/test_active_sample_link.py` (6 tests): no-ACP baseline; live session registers; exit clears; sub-agent shadow does not clobber outer registration; no-op never touches `ActiveSample` (both outside-any-sample and nested-shadow scenarios); `is self` identity guard protects an in-place registration from a stale `__aexit__`.

Pilot-based widget tests are deliberately deferred: the bulk of correctness lives in the link layer (covered above) and the producer-side `cancel_current_turn`/`submit_user_message` calls (already tested in Phase 3/4). The widget layer is a thin shim around those primitives; manual smoke + the link tests are sufficient confidence for v1.

Verification: `pytest tests/agent/test_acp/ tests/log/test_transcript_subscribers.py tests/agent/test_agent_react.py` (112 passed asyncio); `--runtrio` passes (61 trio variants); `ruff format`/`check` clean; `mypy` clean (1006 source files).

### Phase 8: `AcpServer` transport ✅

Landed the JSON-RPC 2.0 mux server so external ACP clients can reach a running eval over a socket. **Transport only** — connected clients can complete the wire-level handshake but every `initialize`/`newSession`/etc. request returns the standard JSON-RPC "method not found" error. Real method routing comes in Phase 9 (session picker) and Phase 10 (full SessionRouter + replay-on-attach).

**Two simplifications from the original sketch** (both requested during planning):

1. **One CLI flag instead of three.** The original plan had `--agent-acp` (bool) + `--agent-acp-port=N` + `--agent-acp-socket=PATH`. Collapsed to a single `--acp-server` with a `bool | int | str | None` value reusing the existing `int_bool_or_str_flag_callback` helper (the same callback `--cache` and `--batch` use):
   - `--acp-server` (or `--acp-server=true`) → default AF_UNIX socket at `<inspect_data_dir>/acp/<run_id>.sock`
   - `--acp-server=12345` → TCP loopback on port 12345
   - `--acp-server=/path/to.sock` → custom AF_UNIX path
   - omitted or `--acp-server=false` → disabled
2. **Persisted into the eval log** so `inspect eval-retry` brings the same transport back automatically. New `EvalConfig.acp_server: bool | int | str | None = None` field; retry follows the existing `value or eval_log.eval.config.field` override pattern.

The name `--acp-server` (rather than `--acp` or `--agent-acp`) is deliberate: it pairs with the future `inspect acp` *client* subcommand. The asymmetric noun makes the role asymmetric obvious — one flag enables the server, the other command runs a client.

**What was built:**

1. **`EvalConfig.acp_server`** in `src/inspect_ai/log/_log.py` — Pydantic field, auto-persists, defaults to `None`, backward-compatible with old logs.
2. **`--acp-server` CLI flag** in `src/inspect_ai/_cli/eval.py` — added to `eval_options()` (covers `inspect eval` + `inspect eval-set`) and a separate copy on `inspect eval-retry` so users can override the persisted value on retry. Env var: `INSPECT_EVAL_ACP_SERVER`.
3. **`acp_server` parameter threaded through** `eval()` / `eval_async()` / `eval_retry()` / `eval_retry_async()` in `src/inspect_ai/_eval/eval.py`. Retry merge uses the same `value if value is not None else eval_log.eval.config.acp_server` pattern as the rest of the replay-able flags.
4. **`_AcpServer` class + `acp_server()` async context manager** in `src/inspect_ai/agent/_acp/_server.py`. Binds the requested transport, writes a per-PID discovery JSON at `<inspect_data_dir>/acp/<pid>.json` (`{pid, eval_id, socket_path, port, started_at}`), accepts connections, wraps each in `acp.connection.Connection` with an empty `acp.router.MessageRouter`, and tears everything down at exit. PID-liveness checked via `os.kill(pid, 0)`; stale discovery files + orphan socket nodes are swept on each `start()`. AF_UNIX everywhere (Win 10+ supports it); older Windows errors with a hint to pass `--acp-server=<port>`.
5. **Lifecycle integration** — the eval runner wraps its eval-loop body in `async with _acp_server(eval_id=run_id, transport=config.acp_server):` (`src/inspect_ai/_eval/eval.py`). When `config.acp_server` is falsy the context yields `None` and binds nothing; otherwise the server lives for the eval's duration. **Per-eval lifecycle** (chosen over per-process): each `eval()` call gets its own socket named after its `run_id`. In `eval-set`, each sub-eval rebinds.

**Why empty `MessageRouter`?** `acp.connection.Connection` requires a handler. An empty `MessageRouter()` is the simplest valid handler — incoming requests match no route, so the dispatch raises `RequestError.method_not_found` which becomes a well-formed JSON-RPC error response. This is the correct Phase 8 behavior: clients can verify the transport handshake works without needing real ACP methods, and we avoid half-implementing methods whose shapes will change in Phase 9/10.

**Test coverage:**

- `tests/_cli/test_acp_server_flag.py` (8 tests): bare flag → True, =true/false, =N → int, =/path → str, omitted → None, env-var precedence.
- `tests/agent/test_acp/test_eval_config_persistence.py` (9 tests): round-trip serialization for each value type (parametrized), backward-compat with old logs missing the field, three retry-override scenarios (log-only, retry-only, neither).
- `tests/agent/test_acp/test_server.py` (14 tests): disabled/falsy transports yield None, AF_UNIX default + custom path, TCP loopback bind, JSON-RPC "method not found" for unknown method, stale-discovery cleanup (including malformed-file tolerance), multi-connection isolation, PID-liveness helper. Server tests use a `/tmp/<short>` data dir to fit inside the 104-char AF_UNIX path limit on macOS.

Verification: `pytest tests/agent/test_acp/ tests/_cli/test_acp_server_flag.py tests/log/test_transcript_subscribers.py tests/agent/test_agent_react.py` (143 passed asyncio); `--runtrio` clean (server tests skip under trio because `acp.connection.Connection` uses asyncio-specific `StreamReader`/`StreamWriter`); `ruff format`/`check` clean; `mypy` clean (1010 source files).

**Deferred to subsequent phases:**
- ACP method dispatch (Phase 9 picker + Phase 10 SessionRouter).
- Per-process server option for `eval-set`-wide attach UX.
- TCP auth / TLS (loopback-only for v1).
- Automatic TCP fallback on Windows where AF_UNIX isn't supported.
- Client SDK / `inspect acp` CLI (Phase 11).
- Replay-on-attach for late-joining clients (Phase 10).

### Phase 9: In-channel session picker ✅

Layer session selection on top of Phase 8's transport using only standard ACP semantics.

**Three refinements landed during implementation:**

1. **`loadSession` is split from `newSession`.** Original sketch had both methods trigger the picker. Implementation distinguishes:
   - `loadSession(sessionId=<known live target>)` → bind directly, no picker. Standard ACP reads "load *this* session".
   - `loadSession(sessionId=<unknown>)` → `invalid_params` error. Clients who want the picker call `newSession` instead. (Falling back to picker would silently rebind the client to a different session than they asked for, which is worse than an explicit error.)
   - `newSession` → picker (or auto-bind on single target).
2. **Picker payload carries `_meta`.** The notification body is an `agent_message_chunk` with a numbered list (for editors), AND a structured `_meta["inspect.picker.targets"]: [{sessionId, task, sampleId, epoch}, ...]` for capability-aware clients (the future `inspect acp` CLI). Pure ACP — no custom JSON-RPC methods, no overloaded sessionId fields.
3. **Wire sessionId is stable across rebind.** Client's `sessionId` stays whatever they got back from `session/new` / `session/load`. The picker rebind switches only an internal `target_session_id`; all outbound `session/update` notifications use the client-facing `wire_session_id`. Target details live in `_meta`.

**Picker selection robustness.** Numeric selections (`"1"`, `"2"`, ...) resolve against a **snapshot** of the target list captured at picker-push time, so samples that start/finish/reorder between push and selection don't shift the meaning of the indices. After snapshot resolution, the chosen sessionId is re-validated against a fresh `list_picker_targets()` enumeration — if the target finished in the window, we redisplay the picker rather than binding to a dead session.

**`session_id` validation.** Both `session/prompt` and `session/cancel` validate the incoming `session_id` against the connection's `wire_session_id`. Mismatched prompts return `invalid_params`; mismatched cancel notifications are silently dropped (notifications can't return errors).

**Tests.** `test_picker.py` (25 unit tests) and `test_server_dispatch.py` (16 integration tests over a real socket): initialize handshake; multi-target picker; single-target auto-bind; zero-target empty picker; `loadSession`-known direct bind; `loadSession`-unknown `invalid_params`; picker selection by index / by uuid / bad selection redisplay; bound-mode `prompt` returns `method_not_found` (Phase 10 boundary); cancel silent accept; `session_id` validation on prompt + cancel; snapshot pinning under reorder; redisplay when picked target has finished; concurrent-connection isolation.

### Phase 10: Full SessionRouter + replay + plan policy + raw events ✅

Phase 9 left the connection bound to a target session but `session/prompt` / `session/cancel` returned `method_not_found` / silently dropped. Phase 10 wires the full ACP method surface so a connected client can drive an Inspect agent end-to-end, plus adds two opt-in capabilities (`AgentPlanUpdate` for plan-rendering clients, raw transcript event stream).

**Four design refinements settled during planning:**

1. **AgentPlanUpdate via per-connection client sniff + `_meta` opt-in.** Plan-capable clients receive `AgentPlanUpdate` for `update_plan` / `todo_write` tool invocations *instead of* the standard tool-call notifications (no duplication). Detection runs at `initialize` time: `client_info.name` against a small allowlist (`{"zed", "toad"}`, case-insensitive — the two confirmed clients with first-class Plan UI), OR `clientCapabilities._meta["inspect.plan_rendering"]: true` for explicit opt-in. Anything else gets the standard tool-call notifications. The translation defaults `priority="medium"` since neither Inspect planning tool carries priority.
2. **Raw event stream opt-in via a new `inspect/event` JSON-RPC notification.** Clients set `clientCapabilities._meta["inspect.raw_events"]: true` at initialize. When enabled, the per-connection forwarder ALSO subscribes to the bound target's transcript directly and sends each event verbatim via a non-standard `inspect/event` JSON-RPC method (supplement, not replacement — runs alongside `session/update`). Standard editors ignore unknown methods; our future `inspect acp` client speaks it natively. Coverage is the full firehose — including events the semantic router drops (`InterruptEvent`, `ScoreEvent`, `InfoEvent`, `SandboxEvent`, `CompactionEvent`, etc.).
3. **Replay-on-attach with bounded payload.** On bind, the connection iterates the captured `target._transcript.events` through the same Phase 6 mapping (with the same sub-agent depth filter), applies the plan-policy transformation, and elides oversized `raw_input` / `raw_output` payloads. Last `REPLAY_MAX_EVENTS = 100` events post-filter; elision threshold `ELISION_THRESHOLD_BYTES = 4096`. Elided fields are replaced with `{"_inspect.elided": true, "_inspect.original_size": N}`. Live forwarding does NOT elide. Raw replay (when opted in) fires before semantic replay so the client has full context before the friendly stream starts.
4. **Pre-condensation forwarding guarantee.** The raw forwarder serializes events in the synchronous transcript-subscriber callback, NOT in the async task body. This is load-bearing: `Transcript._process_event` runs subscribers BEFORE the `walk_model_call` attachment-extraction step that reassigns `event.call` to a side-storage ref. Serializing in the callback captures the pre-condensation state. Deferred serialization (the obvious-but-wrong design) would see attachment refs by the time the task body picked up the event.

**What was built:**

1. **Phase 6 router enhancements** (`src/inspect_ai/agent/_acp/_router.py`):
   - `_map_event` / `_map_model_event` / `_map_tool_event` hoisted to module scope so the replay path can reuse them without instantiating a full router.
   - New `replay_transcript(events, session_id, filter_subagents=True) -> Iterator[SessionNotification]` standalone helper. Fresh depth-tracking + dedup state per call; no interference with the live router's state.
   - `start_tool_call` notifications now populate `raw_input=event.arguments`. Useful for all clients (gives editors visibility into tool arguments via the standard ACP field) and required by the plan-policy translator (which reads the plan/todos array from `raw_input`).

2. **`AcpSession` protocol additions** (`src/inspect_ai/agent/_acp/_session.py`):
   - `subscribe_transcript_events(callback) -> unsubscribe` — wraps `Transcript._add_subscriber` without exposing private state. Used by the raw forwarder. NoOp variant returns a no-op unsubscribe so callers can use a uniform pattern.
   - `transcript_events_snapshot() -> Sequence[Event]` — copy of the captured transcript's event list for replay. NoOp returns `[]`.

3. **Capability detection at `initialize`** (`_server.py`): `_ConnectionState` extended with `client_renders_plan: bool` and `raw_events_enabled: bool` (both default False). `initialize` populates them from `client_info.name` (lowercased, matched against `PLAN_RENDERING_CLIENTS = frozenset({"zed", "toad"})`) and `clientCapabilities._meta` keys (`inspect.plan_rendering`, `inspect.raw_events`).

4. **Inbound forwarding** (`_server.py` `prompt` / `cancel` handlers):
   - `session/prompt` in bound mode: `_find_live_session(state.target_session_id)` walks `active_samples()` for the matching `acp_session`; if found, translates ACP content blocks via `_translate_prompt_blocks` (full support for `TextContentBlock`, text-only fallback for other variants with a one-shot warning) into a `ChatMessageUser(source="operator")`, then calls `target.submit_user_message(msg)`. Returns `PromptResponse(stop_reason="end_turn")`. If the target session has vanished (sample finished after bind), returns `internal_error` with `reason: bound session no longer active`.
   - `session/cancel` in bound mode: same lookup, then `target.cancel_current_turn()`. Mismatched / unbound / vanished cases silently drop (notifications can't return errors).

5. **Per-connection forwarder** (`_server.py`):
   - `_start_forwarders(target_session_id)` runs on each bind path (`_auto_bind`, `_handle_picker_selection` success, `load_session` known-match). First action: `_stop_forwarders()` (idempotent — tears down any prior binding so rebinding doesn't leak the old subscriber or cross-stream the old target's notifications into the new connection).
   - Three-step setup: SNAPSHOT (sync) → ATTACH live subscribers (sync) → emit REPLAY → start LIVE forwarder task(s). Snapshot + attach are both sync so no event can slip into both — events ≤ snapshot go through replay, events > snapshot go through live.
   - `_run_semantic_forwarder`: drains `target.attach()`'s receive stream, applies `_maybe_transform_plan_tool` per notification, rewrites `session_id` to `wire_session_id` via `_rewrite_session_id` (no-op fast path when ids match — only the picker-selection path actually differs), forwards as `session/update`.
   - `_run_raw_forwarder`: drains a per-connection memory-object-stream of payloads (already serialized at callback time per refinement #4), forwards as `inspect/event`.

6. **Plan policy transformation** (`_server.py`):
   - `_maybe_transform_plan_tool(notif)` returns a transformed notification, the original notification, or `None` (suppress). For plan-capable clients: ToolCallStart for a plan tool with `status="in_progress"` is stashed (raw_input + title) and suppressed; matching ToolCallProgress on completion looks up the stash and emits an `AgentPlanUpdate`. Instant-complete plan tools (no in_progress phase) emit Plan directly on start. Non-capable clients always pass through unchanged.
   - `_build_plan_update(title, raw_input)` translates `update_plan`'s `{plan: [{step, status}, ...]}` and `todo_write`'s `{todos: [{content, status}, ...]}` into `AgentPlanUpdate(entries=[PlanEntry(content, status, priority="medium"), ...])`. Returns `None` on malformed input; caller falls back to passthrough.

7. **Replay-on-attach** (`_server.py`):
   - `_run_replay(snapshot)` emits raw replay first (if opted in) then semantic replay. Raw uses the full transcript (no sub-agent filter). Semantic filters via `_filter_subagent_events` (extracted depth-tracking helper) then maps via `replay_transcript`. Both are capped to `REPLAY_MAX_EVENTS = 100` post-filter.
   - `_elide_tool_call_notification(notif, threshold)` returns a model_copy with `raw_input` / `raw_output` replaced by the elision marker when serialized size exceeds the threshold. `_elide_raw_event_payload(payload, threshold)` mutates a serialized event dict in place for ToolEvent's `arguments` / `result` fields.

**Test coverage:**

- `tests/agent/test_acp/test_plan_policy.py` (25 unit tests, no socket): capability detection (allowlist + `_meta` + case-insensitivity + missing fields), `_build_plan_update` translation for both update_plan and todo_write (well-formed + degenerate inputs), `_is_plan_tool_notification` predicate, forwarder transformation behavior (suppress in-progress, emit Plan on complete, instant-complete, passthrough for non-capable, passthrough for non-plan tools).
- `tests/agent/test_acp/test_server_forwarding.py` (14 socket integration tests): inbound prompt/cancel forwarding to stubbed live sessions, outbound semantic forwarding via the bus, plan-tool live transformation for Zed-named clients + `_meta`-opted clients, non-plan-capable passthrough, forwarder cleanup on disconnect, bound-target-gone `internal_error`, replay-on-attach (cap + elision + sub-agent filter + plan policy + ordering), and the two P1/P2 regression tests (picker-selection sessionId rewrite, rebind cleanup).
- `tests/agent/test_acp/test_raw_events.py` (9 socket integration tests): opt-in detection, opt-in default-off, supplement-not-replacement (both streams fire), coverage of router-dropped events (InterruptEvent, ScoreEvent, etc.), no-leak-to-non-opted clients, raw replay, transcript subscriber cleanup on disconnect, pre-condensation guarantee (raw client sees inline `event.call` even after the threshold), CompactionEvent visibility + non-mutation of prior events, raw replay elision for oversized ToolEvent arguments.

**Code-review issues caught + fixed during implementation:**

- **P1 (high)**: live forwarder originally forwarded `SessionNotification`s unchanged from the bus. Notifications were published with the target's `session.session_id`, but after a picker selection the connection's `wire_session_id` (control id minted at `session/new`) differs. Clients keyed on the control id never saw matching updates. Fixed by `_rewrite_session_id` in the forwarder loop. The auto-bind / direct-loadSession tests passed even without the fix (wire == target in those paths); the picker selection is the only case that exercises the divergence.
- **P2 (medium)**: rebinding (`session/load` twice, or another `session/new` with picker re-select) installed new forwarders without stopping the old ones. The old target kept publishing into the same connection. Fixed by calling `_stop_forwarders()` at the top of `_start_forwarders` (idempotent on first bind).
- **Pre-condensation race**: the original raw forwarder enqueued the event reference and called `model_dump` in the task body. By then `walk_model_call` had already reassigned `event.call` to an attachment-ref form, so raw consumers saw `attachment://hash` instead of the original inline payload. Caught by the test that pre-populates a ModelEvent with a >8KB inline `call` and asserts the raw stream payload contains the inline data. Fixed by serializing in the synchronous transcript-subscriber callback.

**Tally:** 233 passed, 121 skipped (trio variants — socket integration tests use asyncio-specific `StreamReader`/`StreamWriter`), 0 failures. mypy clean (1016 source files). ruff clean.

**Caveats deferred:**
- Full multi-modal prompt translation (image/audio/resource blocks → Inspect content types). Phase 10 supports `TextContentBlock` fully and emits placeholder text for the others with a one-shot warning. Real multi-modal lands in Phase 13.
- `REPLAY_MAX_EVENTS = 100` and `ELISION_THRESHOLD_BYTES = 4096` are hard-coded; a server-level config option or per-connection override is a follow-up.
- The `_log_model_api` retention policy zeros `event.call` BEFORE subscribers fire once the per-model count threshold is crossed. Raw consumers past the threshold see `ModelEvent.call = None` even with our pre-condensation guarantee. Matches log-writer behavior — not a forwarder bug. Documented.
- Raw events go out unfiltered (no sub-agent depth filter). A `_meta` opt-in for sub-agent filtering of raw events could come later.
- Tool-call payload elision only fires on REPLAY, not live forwarding. If live notifications turn out too chatty we can reuse the elision logic.

### Phase 11: `deepagent()` integration ✅

**Punchline:** zero code changes. The audit found all three sub-agent dispatch paths already emit `AGENT_SPAN_TYPE` boundary spans, and `deepagent.execute()` delegates to `react()` which already opens `acp_session()` per Phase 4. The Phase 4-era sticky-`_acp_live_active` flag plus the Phase 6 router's depth filter handle the rest by composition. Phase 11 is a tests-only ratification of the composition.

**Why it works without code changes** — the composition trace:

| Layer | Where the wiring lives | What it guarantees |
|---|---|---|
| Top-level entry | `deepagent.execute()` → `inner = react(...); await inner(state)` (`_deepagent/deepagent.py:199-211`) | Outer ACP session is the same one `react()` opens — Phase 4 integration carries through verbatim. |
| Sub-agent dispatch via `task_tool` | `task_tool._dispatch` → `run(agent, ..., span_id=...)` (`_deepagent/task_tool.py:218`) | `run()` opens `span(name=..., type=AGENT_SPAN_TYPE)` (`_run.py:93`). Each sub-agent task is bracketed by a boundary span. |
| Sub-agent dispatch via `as_tool` | `as_tool` invocation in the agent loop (`_as_tool.py:68`) | Same `span(name=..., type=AGENT_SPAN_TYPE)`. |
| Sub-agent dispatch via `handoff` | `agent_handoff` in `execute_tools` (`_call_tools.py:583`) | Same `span(name=agent_name, type=AGENT_SPAN_TYPE)`. |
| Nested `acp_session()` calls | Each sub-agent's `react()` opens `acp_session()` again | Sticky `_acp_live_active` flag (set by the outermost Live entry) makes every nested call install a NoOp shadow. Sub-agents that try to drive the editor via `current_acp_session()` silently no-op. |
| Event filtering | Phase 6 `_AcpEventRouter._process` | Tracks `_sub_agent_depth` via SpanBegin/End for `AGENT_SPAN_TYPE`. Notifications fire only when depth == 0 from the router's POV (which is "inside top-level agent, outside any sub-agent" because the router attaches after the top-level agent's own span has begun). |

End-to-end consequence: a deepagent eval sends `session/update`s for top-level model output, top-level tool calls (including the visible `task` invocation that names the sub-agent), but NOT for anything inside a delegated subagent. The Phase 5 isolation promise lands automatically through the existing wiring.

**Audit findings:**

- `task_tool` (deepagent-specific): goes through `run()` → AGENT_SPAN_TYPE ✓
- `as_tool` (general): inherits from existing Phase 5 boundary ✓
- `handoff` (general): inherits from existing Phase 5 boundary ✓
- `deepagent._dispatch_forked` (`task_tool.py:222-232`): wraps in `timeline_branch` then calls `_dispatch` → `run()` → AGENT_SPAN_TYPE ✓
- Nested `acp_session()` inside subagent `react()`: sticky-flag fix from the Phase 4 hardening installs NoOp shadow at depth ≥ 2 ✓

No paths bypass the decorator. No code fix needed.

**Test coverage** — `tests/agent/test_acp/test_deepagent_integration.py` (6 tests):

1. `test_deepagent_task_dispatch_emits_agent_boundary_span` — the deepagent-specific dispatch audit. Complements `test_span_boundary.py`'s coverage of `run()` / `as_tool` / `handoff` by exercising the `task_tool` path end-to-end via `eval()`. Asserts a `SpanBeginEvent(type=AGENT_SPAN_TYPE, name="custom_sub")` appears in the transcript when deepagent dispatches a subagent.
2. `test_deepagent_outer_gets_live_subagent_gets_noop` — proves the nested-`acp_session` sticky-flag works through deepagent's dispatch chain. Captures `current_acp_session()` from both an outer tool AND a subagent tool; asserts outer is Live (`session_id != "noop"`), subagent is NoOp (`session_id == "noop"`). If this regresses, sub-agents could accidentally drive the editor's top-level session.
3. `test_deepagent_subagent_events_are_nested_inside_agent_span` — structural check that sub-agent ModelEvents / ToolEvents bracket between `AGENT_SPAN_TYPE` SpanBegin/End markers. Counts agent-span nesting depth from the log POV: outer `task` tool-call at depth 1 (would publish — inside deepagent's outer span but outside any sub-agent); sub-agent's submit + ModelEvents at depth ≥ 2 (would be filtered by the router). Composition: this structural property + the existing `test_router.py` filter test ⇒ end-to-end "no leakage" guarantee.
4. `test_deepagent_exit_on_submit_matches_react` — when the outer model calls `submit`, deepagent finishes the sample (doesn't loop past it). Mirrors react's exit semantics; verifies deepagent's outer react inherits it.
5. `test_deepagent_cancel_propagates_through_subagent_dispatch` — verifies `task_tool`'s dispatch teardown leaves agent SpanBegin/End pairs matched (no leaked state when the dispatch unwinds). Defers actual cancel timing tests to `test_react_integration.py` + `test_cancel.py` which exercise the Phase 3 cancel machinery directly.
6. `test_deepagent_todo_write_arguments_are_visible_in_tool_event` — the deepagent default config enables `todo_write`. Verifies the tool's `arguments` field round-trips through deepagent → react → tool-execution to the transcript with the structure Phase 10's plan-policy translator expects (`raw_input["todos"]: [{content, status}, ...]`). So a Zed-named or `_meta`-opted client gets `AgentPlanUpdate` from a deepagent eval the same way it does from a plain `react` one.

**Subtle test-design note** — the structural test (#3) replaces a more ambitious version that tried to verify the router's filtering by iterating log events through a fresh `_AcpEventRouter`. That approach doesn't work cleanly because the router's depth tracking is *relative to when it attached* (inside the top-level agent body, after that agent's own `AGENT_SPAN_TYPE` span has begun). Iterating raw log events from a different baseline includes the outer span and biases the depth counter. Verifying the structural property + leaning on the existing router unit tests is cleaner and gives equivalent coverage.

**Real production bug surfaced + fixed during Phase 11 testing** — `Transcript._process_event` could recurse infinitely when a transcript subscriber raised. The recursion: subscriber raises → `logger.exception("Transcript subscriber raised; continuing")` → `inspect_ai`'s `LogHandler` (installed by eval) calls `log_to_transcript` → `transcript()._event(LoggerEvent(...))` → re-enters `_process_event` → subscriber loop fires the same broken subscriber → raises → infinite. In tests this manifested as `test_router_exception_does_not_propagate_to_loop` failing with `RecursionError` whenever it ran AFTER a test that used `eval()` (the deepagent integration tests being the trigger). In production, any consistently-broken subscriber would have hung the agent process. Fixed in `src/inspect_ai/log/_transcript.py` by adding a `_notifying_subscribers` re-entry guard: the recursive event still gets appended to `_events` and sent to the log writer, but the subscriber loop is skipped on re-entry, breaking the cycle. The same bug would have affected any subscriber (not just the picker / ACP router) so the fix lives at the transcript layer.

**Verification:** `pytest tests/agent/test_acp/test_deepagent_integration.py -v` — all 6 tests pass. `pytest tests/agent/test_acp/ tests/_cli/test_acp_server_flag.py` — 239 passed (was 233 in Phase 10; +6 new tests, including the +1 from the transcript bug fix that flipped a previously-flaky existing test green). `mypy --exclude tests/test_package src tests` clean (1017 source files). `ruff format` / `ruff check` clean.

**Out of scope (no action needed):** the design doc originally said "audit and fix any path that bypasses the decorator." Audit complete; no bypass paths found. If a future dispatch path is added (e.g. a new sub-agent invocation route) that skips `run()` / the `span()` wrap, the deepagent integration test (#1) will fail because the expected boundary span won't appear — that's the regression guard.


### Phase 12: Inspect-specific ACP extensions: `inspect/*` action methods ✅

Two TUI-grade affordances that don't map onto any generic ACP method live as non-standard JSON-RPC requests under the `inspect/` namespace. The Inspect TUI has them today; the JSON-RPC surface exposes the same primitives so editor clients can offer them too.

- **`inspect/cancel_sample`** — terminal sample-level cancel. `params: { sessionId, action: "score" | "error" }`. `action="score"` runs the scorer on whatever work the sample produced before cancel; `action="error"` marks the sample errored. The `error` action is gated to match the TUI's polarity: rejected when `sample.fails_on_error == True` (the same scenario where the TUI hides its "Cancel (Error)" button — when the sample is already configured to fail on errors, manual cancel-as-error is moot).
- **`inspect/cancel_tool_call`** — per-tool-call cancel. `params: { sessionId, toolCallId }`. Returns `{ cancelled: bool }`. Walks the **full** transcript (including events inside `task` / `as_tool` / `handoff` sub-agent dispatches) for a pending `ToolEvent` with matching id and fires `ToolEvent._cancel()`. Superset of TUI behavior — the TUI's button only operates on the top-level in-flight tool. Idempotent: an unknown / already-completed id returns `{cancelled: false}` rather than an error.

Both methods differ from standard `session/cancel` (a per-turn, recoverable cancel — the agent loop sees a `TurnCancelled`, drains `after_cancel`, continues with the next user message). Sample cancel is terminal; tool-call cancel scopes to one tool call (the sub-agent's loop sees a synthesized `ChatMessageTool` with `error.type == "timeout"` and decides what to do — typically continue with a different tool or submit).

**Why register directly on the per-connection router?** The Agent protocol that `build_agent_router` was built for doesn't include these methods (they're inspect-only), so registering via a method-name string on the router avoids changing the upstream ACP schema. `_wrap_action_handler(func, model)` is a small adapter that mirrors `MessageRouter._make_func`: validates params against a Pydantic model (`_CancelSampleParams` / `_CancelToolCallParams` with camelCase `Field(alias=...)` for `sessionId` / `toolCallId`), unpacks fields as kwargs, then calls the handler. The handler validates `wire_session_id` parity and the `target_session_id` binding before touching any sample state.

**Always advertised, no capability opt-in.** Same pattern as `session/prompt` — a client that doesn't know about the methods just doesn't call them. The handlers do their own validation; there's no security boundary to gate. (An opt-out flag could come later if a client needs to assert they're not accidentally enabled.) Editor authors who want to expose Cancel buttons can call these methods regardless of how they declared `clientCapabilities` at `initialize`.

**Auth model.** Same as everything else on the ACP server: loopback-only TCP or AF_UNIX, no auth. Anyone on the socket can cancel. A real auth story is a Phase 13+ concern.

**Sample lookup.** A small `_find_active_sample(session_id)` helper walks `inspect_ai.log._samples.active_samples()` for the `ActiveSample` whose `acp_session.session_id` matches — sibling pattern to the existing `_find_live_session`. O(samples) per call; fine for expected scale (a handful of in-flight samples).

**Cancel propagation chain — pinned by integration test.** `_call_tools.py:346-348` is where each tool call gets a per-call `anyio.create_task_group()` and the ToolEvent's cancel_fn is set to `tg.cancel_scope.cancel`. `inspect/cancel_tool_call` → handler walks transcript → finds pending `ToolEvent` → calls `event._cancel()` → invokes that bound cancel_fn → cancels the per-call task group → slow body's `await` raises `CancelledError` → `_call_tools` synthesizes a `ChatMessageTool` with `error.type == "timeout"` for the agent loop. The per-call (not per-turn) scope means cancelling one tool **does not** cascade to siblings or outer task tools — `test_cancel_tool_call_propagates_through_nested_dispatch` in `tests/agent/test_acp/test_action_methods.py` pins this contract end-to-end with a real anyio task group + nested transcript span so a future refactor that widens the scope (or breaks the chain) will fail loudly.

**Files.** `src/inspect_ai/agent/_acp/_server.py` holds the handler methods, param models, `_wrap_action_handler`, `_find_active_sample`, and the route registration. `tests/agent/test_acp/test_action_methods.py` covers handler validation, the transcript walk for top-level + nested tools, end-to-end JSON-RPC over a real AF_UNIX socket, the always-advertised audit, and the cancel-propagation pinning test (23 tests total).

**Out of scope (deferred).** Read-side "generation in flight / retry count / tool in flight" indicators — already derivable from the Phase 10 `inspect/event` raw event stream (`ModelEvent.pending` / `ModelEvent.retries` / `ToolEvent.pending`); no new outbound notifications needed. Bulk cancel and status/introspection methods — not requested; the single-target form composes.


### Phase 13: `inspect acp --stdio` (editor bridge) ✅

Shipped the `inspect acp` subcommand in its minimum-viable form: a stdio↔socket bridge that lets external editors (Zed etc.) speak ACP to a running eval through the standard "spawn an agent subprocess on stdio" contract those editors already support. Phase 13 is *just* a transport adapter — one bridge process, one eval, line-framed byte forwarding. The TUI client (Phase 15) and approval UI (Phase 14) are independent concerns that layer on top of the same surface.

**Components landed:**

- **`inspect acp --stdio`** — bridge mode. Forwards newline-delimited JSON-RPC frames 1:1 between the editor's stdio and the eval's AF_UNIX (or loopback TCP) socket. Bare `inspect acp` (no `--stdio`) exits non-zero with a "TUI not yet implemented, use --stdio (Phase 15)" message — Phase 15's PR lifts this gate.
- **Discovery resolution** — `src/inspect_ai/agent/_acp/_discovery.py`. Public surface: `discovery_dir()`, `pid_alive()`, `parse_host_port()`, `has_unix_sockets()`, `cleanup_stale_discovery_files()` (all moved out of `_server.py` so the CLI can import them without server internals), plus the new `TargetAddress`, `DiscoveredEval`, `TargetResolutionError`, `list_discovered_evals()`, and `resolve_target()`. Policy: `--socket` wins (parses path or `host:port`); else `--eval-id` looks up the file; else auto-discover. Auto-discovery picks the most-recently-started alive eval; emits a stderr notice naming the choice + the candidate list when more than one is available, so editor debug panes show what happened.
- **Bridge** — `src/inspect_ai/agent/_acp/_stdio.py`. Two concurrent forwarders (stdin→socket, socket→stdout) with `asyncio.wait(return_when=FIRST_COMPLETED)` semantics so the bridge exits as soon as either side hits EOF — needed because the sibling forwarder may be blocked on `readline()` from a still-open reader. Line-framed via `StreamReader.readline()`; raw-byte forwarding could split or merge frames at chunk boundaries.
- **CLI** — `src/inspect_ai/_cli/acp.py`. Click subcommand registered in `_cli/main.py`. Uses `acp.stdio.stdio_streams()` (cross-platform — POSIX `loop.connect_read_pipe`, Windows thread-fed feeder + custom stdout transport) to get the stdio streams; calls `bridge_stdio()` with them. Rejects `--eval-id` + `--socket` together (mutually exclusive — different intents); translates `ConnectionRefusedError` / `FileNotFoundError` to clean stderr diagnostics + exit 2.

**Test coverage:** 29 new tests, all green under asyncio. Discovery (`tests/agent/test_acp/test_discovery.py`, 15) covers `--socket` parsing for UNIX paths + IPv4/IPv6 `host:port`, `--eval-id` hit/miss, auto-discovery zero/one/many (including the pinned no-flags happy path), stale-PID filtering, malformed-JSON resilience, and newest-wins ordering. Bridge (`tests/agent/test_acp/test_stdio_bridge.py`, 6) drives a real `acp_server` over a real AF_UNIX socket with in-memory `StreamReader`/`StreamWriter` stand-ins for editor stdio: initialize round-trip, `session/load` round-trip, an end-to-end `inspect/cancel_tool_call` flow through the bridge, EOF on stdin → clean exit, EOF on socket → clean exit, and a multi-line framing-integrity test. CLI (`tests/_cli/test_acp_cli.py`, 8) covers the click surface: bare command exits with Phase 15 hint, mutex enforcement, empty discovery, unknown `--eval-id`, bad `--socket`, multi-eval newest-picks + stderr notice, single-eval quiet path, `--help` content.

**Key design decisions:**

- **Asyncio-only concurrency** (not anyio). `acp.stdio_streams()` returns asyncio types directly; the bridge is a one-process CLI leaf that never composes with anyio agent code; wrapping the streams into anyio would be cost-for-no-gain. The bridge's tests skip under trio for this reason — the trio variants are present so the harness doesn't lose them silently if a future refactor goes anyio.
- **Discovery helpers moved, not copied.** The five test fixtures across `test_server.py` / `test_server_dispatch.py` / `test_server_forwarding.py` / `test_raw_events.py` / `test_action_methods.py` that patch `inspect_data_dir` were updated to point at the `_discovery` module's import instead of the `_server` re-export. Underscored back-compat aliases remain on `_server` so existing imports there still resolve.
- **Multi-eval policy = "pick the newest" (with stderr notice), not "error and require --eval-id".** Editor configs that hard-code `inspect acp --stdio` should keep working when the developer happens to spawn a second eval mid-session. Stderr notice naming the chosen eval + the candidate list gives the user a paper trail.
- **Enumeration across evals is a Phase 15 (TUI) concern, not Phase 13.** Once multiple evals are running, presenting a unified picker is a UI feature. The bridge stays as a 1:1 transport; Phase 15's TUI calls `list_discovered_evals()` (already shipped here) to build its own picker view.

**Verification:** `pytest tests/agent/test_acp/ tests/_cli/test_acp_server_flag.py tests/_cli/test_acp_cli.py` → 293 passed (was 264 in Phase 12). `ruff format` / `ruff check` clean. `mypy --exclude tests/test_package src tests` clean (1024 source files). Manual smoke: `inspect acp --help` shows the three flags; `inspect acp` exits 2 with the Phase-15 message; `inspect acp --stdio` against an empty discovery dir exits 2 with the "no running evals" hint.

**Out of scope (deferred):**

- **TUI client** — Phase 15. Will reuse `list_discovered_evals()`, `TargetAddress`, and `resolve_target()` already shipped here.
- **Approval UI (`session/request_permission`)** — Phase 14. The bridge forwards it transparently when it lands; no Phase-13 follow-up needed.
- **Bridge stderr logging** — silent in Phase 13. Editors surface subprocess stderr in debug panes; if we need visibility a `--verbose` flag routing to the existing log infra can come later.
- **Hot-swap eval target mid-session / reconnect-on-restart** — bridge attaches once at startup.
- **Authentication** — same trust model as the rest of the ACP server (loopback-only TCP / AF_UNIX). Real auth is a Phase 16+ concern.


### Phase 14: Approval UI via `session/request_permission` ✅

Routes the **human leaf** of the configured approval chain through ACP `session/request_permission` when one or more ACP clients are attached to the running sample. The rest of the chain (auto-approvers, model-judgment approvers, ApprovalPolicy matching, the global `apply_tool_approval` dispatch) is untouched — only `human_approver`'s "ask the person at the keyboard" step changes behavior. When no clients are attached, the existing in-proc Textual panel / console prompt flow runs unchanged.

**Why scoped to the human leaf and not the whole approval pipeline.** Original sketch spoke of intercepting at the framework level with timeout + default-deny. Real-world configs commonly mix auto-approve for safe tools (`grep`, `read_file`) with human approval for destructive ones (`bash`, `text_editor`); a global intercept would have skipped the auto rules and prompted the editor for every tool. Scoping to the human leaf keeps the configured policy in charge of *what* needs approval; ACP only changes *who renders the prompt* when there's a better surface available.

**Components landed:**

- **Per-session approver-client registry** (`src/inspect_ai/agent/_acp/_session.py`). `ApproverClient` Protocol (one method: `async def request_permission(request) -> response`) + `_LiveAcpSession.attach_approver_client(client) → unsubscribe` / `has_approver_clients()` / `approver_clients()`. NoOp session returns empty / False / no-op unsubscribe so callers don't need isinstance guards. Cleared on `__aexit__` so a late callback can't fire into a closed connection. Same hook pattern as the existing interrupted-subscriber registry.
- **Connection handler implements `ApproverClient`** (`_server.py`). `_ConnectionHandler.request_permission` wraps `conn.send_request("session/request_permission", payload)` and validates the response. Self-registers in `_start_forwarders` after the bind completes; deregisters in `_stop_forwarders`. Lifecycle mirrors the semantic / raw event forwarder tasks exactly.
- **Approval shim** (`src/inspect_ai/approval/_human/acp.py`). `request_human_approval_via_acp(message, call, view, choices) → Approval | None`. Returns `None` to signal "fall through to in-proc panel/console" when no clients attached or every client raised. Otherwise builds a `RequestPermissionRequest` (reusing the router's `descriptive_title` + `content_blocks_from_view` for visual consistency with live tool-call rendering), races attached clients via `asyncio.wait(FIRST_COMPLETED)`, cancels losers, maps the first-non-exception response back to `Approval` via `optionId` round-trip. Wait-forever (no timeout — the human at the editor is the source of truth).
- **`human_approver` checks ACP first** (`src/inspect_ai/approval/_human/approver.py`). One added line: call the shim before falling through to `panel_approval` / `console_approval`. Zero behavior change in the no-client case — the ACP routing is a strict superset.
- **Router helpers refactored** (`_router.py`). Extracted `descriptive_title(fn, args)` and `content_blocks_from_view(view)` to take primitives so they're shareable between the live-event router (which has `ToolEvent`) and the approval shim (which has `ToolCall` + `ToolCallView`). `_descriptive_title(event)` / `_content_from_view(event)` remain as thin adapters for the router's own use.

**Decisions settled with the user:**

- **Multi-client: broadcast + race.** First non-exception response wins; in-flight requests on losing clients are cancelled (their futures resolve with CancelledError on the client side).
- **Timeout: wait forever.** Mirrors the in-proc human approver's blocking behavior; default-deny on timeout would be surprising.
- **Disconnect mid-prompt: fall back gracefully.** If other clients are still racing, their responses still count; if every client raises (typically `ConnectionError` after disconnect), shim returns `None` and the existing in-proc panel/console path runs.
- **Option mapping: configured `choices` is the source of truth.** Each `PermissionOption.optionId` is the literal `ApprovalDecision` string (`"approve"` / `"reject"` / `"terminate"` / `"escalate"` / `"modify"`) so the response round-trips losslessly. `PermissionOptionKind` is a best-effort visual hint (`approve` → `allow_once`, `reject` → `reject_once`, `terminate` → `reject_always`).
- **No conflict with the in-proc TUI.** When ACP is attached, ACP "gets the stick" — the in-proc panel never opens. When ACP is not attached, the in-proc flow is unchanged.

**Test coverage** — 40 new tests in `tests/agent/test_acp/test_session.py` (7 — registry mechanics) and `tests/agent/test_acp/test_approval.py` (~22 — option mapping, response round-trip, race semantics, entry-point predicates, end-to-end over real AF_UNIX socket). Plus several integration tests in the existing suites verifying nothing regressed (382 ACP+CLI+approval passing total).

**Out of scope (deferred):**

- **`modify` decision over ACP.** ACP's `PermissionOption` doesn't have a "modify the call before approving" affordance; `Approval.modified` (a new `ToolCall`) would need a custom UI surface. If a configured `human_approver` includes `modify` in its choices, the optionId round-trips but downstream `apply_tool_approval` degenerates to using the original call (no modification). Could add a richer flow later via an `_meta`-flagged option for Inspect-aware clients.
- **`escalate` decision over ACP.** Same shape problem — sends and round-trips, but ACP options are binary allow/deny variants and most editors render it as a generic button without the escalation-chain semantics.
- **Timeout / approval expiry.** Wait-forever per the decision above. If a future deployment needs unattended fallback, an opt-in `timeout=` parameter on `human_approver` could become the ACP race deadline.
- **Telemetry / audit for "approval came from ACP client X vs in-proc".** `Approval.metadata` could carry it; not in v1.
- **Live approval card with diff preview for `edit` tools.** Currently the prompt content is the same markdown the live tool-call notification carries; richer per-kind formatting (e.g. `FileEditToolCallContent` for diff previews) is a follow-up.

**Verification.** `pytest tests/agent/test_acp/ tests/_cli/test_acp_server_flag.py tests/_cli/test_acp_cli.py tests/approval/` — 382 passed. `ruff format` + `ruff check` clean across all modified source and test files. `mypy --exclude tests/test_package src tests` clean (1026 source files). Manual smoke against Zed via `inspect eval <task> --acp-server --approval=human` confirms the permission card renders with the bash command and the user's response advances the eval.


### Phase 15: `inspect acp` (Textual TUI client)

The default `inspect acp` mode (no `--stdio`): an Inspect-native Textual client that speaks ACP over the eval socket instead of the in-process channel Phase 7's TUI uses. Shares the conversation UI with Phase 7 (extract shared rendering code into a reusable widget so the in-process TUI and the ACP-client TUI render identical conversation views); only the transport differs.

Reuses the `_resolve_target()` helper from Phase 13 for eval discovery and the `session/request_permission` machinery from Phase 14 so the TUI can render approval prompts the same way an editor would. New surface area is just (a) the client-side ACP I/O loop pointed at the socket and (b) the UI shell wrapping the shared conversation widget.

**Tests.** TUI smoke via Textual test driver (load → render initial state → drive a prompt → assert rendered output); approval-prompt rendering in the client UI; multi-eval picker resolution path matches `--stdio`'s behavior; shared-widget equivalence test (in-process TUI render ≡ ACP-client TUI render for the same event sequence).


### Phase 16: Token-level streaming

Hook into provider streaming generators to emit partial assistant message content as token-chunked `session/update`s (`agent_message_chunk` with incremental content). Wired at the provider boundary, not the transcript fan-out — transcript events fire only at message completion.

**Tests.** Live streaming providers (Anthropic / OpenAI) emit incremental chunks; final assembled content equals the completed message; cancel mid-stream interrupts cleanly without leaving the connection in a bad state; `agent_thought_chunk` correctly distinguished from `agent_message_chunk` for thinking blocks.
