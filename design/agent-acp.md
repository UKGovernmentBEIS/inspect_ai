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
    install = _NoOp() if not isinstance(current, _NoOp) else _RealAcpSession(...)
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
- Each connection auto-attaches to a synthetic **control session** on connect, then transparently rebinds to a chosen target session after the user picks one (see below).
- The server is a JSON-RPC mux: many concurrent connections, each independently bound to its own target session, fully supported.

The server is wired into the eval lifecycle similarly to `--display`: started before sample execution, drained on shutdown.

#### In-channel session picker

Rather than CLI-args-driven selection, the picker is exposed *through* the
ACP channel so editors with no Inspect-specific UI still get a usable flow:

1. Client connects + calls `initialize`. Server responds with capabilities.
2. Client calls `newSession` (or `loadSession`). Server returns a
   sessionId for a synthetic **control session** unique to this
   connection.
3. Server immediately pushes a `session/update` on the control session
   containing the list of available targets (formatted as an
   `agent_message_chunk` with a numbered list, plus a structured
   `plan`-style payload for richer clients).
4. Client's first `session/prompt` is the user's selection (a number or
   sessionId). Server validates, then **rebinds** this connection: future
   traffic on the same sessionId routes to the chosen target. From the
   editor's POV the sessionId is stable; the rebind is invisible.
5. If only one target is available, the server skips the picker prompt
   and rebinds immediately, pushing a `session/update` confirming the
   target.

This stays within standard ACP semantics (no custom JSON-RPC methods
required for the picker) while giving us a flexible UX.

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
    interrupted_tool_id: str | None = None
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

Foundation types only — no agent integration yet. Lands:

- `AcpSession` async context manager protocol plus a default `_NoOp` implementation.
- A real `AcpSession` shell that owns the user-message queue, the per-turn cancel scope slot, and an in-process pub/sub interface (subscribers register a callback for `session/update`-shaped payloads; the same interface will serve the TUI and the socket transport in later phases).
- `acp_session()` factory implementing the "shadow with no-op if a real session is already active" rule via a ContextVar.
- `current_acp_session()` peek-only accessor that returns whatever is in the ContextVar without entering a new scope.

**Tests.** Factory shadowing under nested `async with acp_session()` entries; `__aenter__` / `__aexit__` ordering; pub/sub subscribers receive published events and are unsubscribed on session exit; `current_acp_session()` returns the active session inside scope and the no-op outside.

### Phase 2: Transcript primitives — `InterruptEvent` and `source="operator"`

Schema-level changes to record cancels and operator-injected messages in the transcript.

- Extend `ChatMessageUser.source` from `Literal["input", "generate"] | None` to `Literal["input", "generate", "operator"] | None`. Audit existing references for switch/match statements that need updating.
- Add `InterruptEvent` to the transcript event union with fields `source` (`"user_cancel" | "limit" | "system"`), `interrupted` (`"generate" | "tool_call" | "between_turns"`), and ids for the active model event / cancelled tool call where applicable.

**Tests.** Schema serialization roundtrip for `InterruptEvent`; `ChatMessageUser(source="operator")` constructs and serializes; log read-back of a transcript containing both new elements; verify exhaustive matches across the codebase still cover the union.

### Phase 3: Turn scope and cancellation mechanics

The core cancel/inject machinery on `AcpSession`. No `react()` integration yet — exercised against synthetic turn bodies.

- `turn_scope()` synchronous context manager wrapping an anyio `CancelScope`, with the `_pending_turn_cancel` flag dance to distinguish client cancel from sample-level cancel.
- `TurnCancelled` exception, raised on scope exit when the cancel was client-driven.
- `before_turn(state)` queue draining with first-call blocking semantics (block only if `state.messages` has no user content yet).
- `after_cancel()` returning a flat `list[ChatMessage]` — synthetic `ChatMessageTool(error="cancelled by user")` for cancelled tool calls plus drained user messages, in order ready to extend onto `state.messages`.
- `submit_user_message()` and `cancel_current_turn()` producer-side methods.

**Tests.** Simulate cancel during a mock turn body — assert `TurnCancelled` when the flag is set, `CancelledError` propagates otherwise; race test where the turn body completes simultaneously with cancel (queued message survives, no exception); `after_cancel` produces correct repair messages when a tool was mid-flight at cancel time; `before_turn` blocking behavior under both empty and non-empty `state.messages`.

### Phase 4: `react()` integration

Splice ACP into `agent/_react.py`:

- Wrap the agent body in `async with acp_session() as acp:`.
- `state.messages.extend(await acp.before_turn(state))` at the top of each loop iteration.
- Wrap the turn body (generate + execute_tools) in `with acp.turn_scope():`.
- Catch `TurnCancelled` to extend with `await acp.after_cancel()` and continue.
- Suppress agent-keeps-alive: when react would naturally exit (model returns no tool calls / submits), it exits — the `async with` block ends, clients disconnect, scoring runs.

**Tests** (mockllm + direct adapter manipulation in unit tests):

- Cancel mid-generate → `TurnCancelled` raised, queued user message picked up, loop continues.
- Cancel mid-tool-call → synthetic `ChatMessageTool(error="cancelled by user")` appears in `state.messages`, then queued user message.
- Inject user message between turns → picked up by next `before_turn`.
- Cancel arrives simultaneously with turn completion → message survives, no error.
- Model returns no tool calls → react exits normally, ACP session terminates, no hang.

### Phase 5: `@agent` sub-agent boundary span

Tag the span emitted by the `@agent` decorator with an attribute (e.g. `span.attributes["agent.boundary"] = True`) so downstream consumers can identify sub-agent boundaries from the event stream without relying on agent names. Verify the decorator's current span emission shape; add the attribute consistently. No filtering happens here — this is instrumentation only.

**Tests.** Decorating an agent function results in a span carrying the boundary attribute; nested `@agent` invocations each emit their own boundary span; span end events also carry the marker (or pair correctly with begin events).

### Phase 6: Event router with top-level filter

Implement the in-process event router that converts top-level transcript events into ACP `session/update` payloads.

- Subscribe to the active sample's transcript event stream.
- Maintain a per-stream "sub-agent depth" counter via Phase 5's boundary spans (incremented on `SpanBeginEvent` of a tagged span, decremented on the matching `SpanEndEvent`).
- Drop events whose enclosing depth is > 0 (i.e. inside a sub-agent).
- Map remaining events to `session/update` shapes (table in the design doc) and publish them via the `AcpSession` pub/sub from Phase 1.

**Tests.** Feed a synthetic stream of events including nested sub-agent spans; assert only outer-level events emerge; assert the event → `session/update` mapping table is exhaustive for the events we care about; verify ordering is preserved.

### Phase 7: TUI as in-process ACP client

Make the existing Textual TUI (`--display full`) a first-class ACP client *without* needing `--agent-acp`. The TUI subscribes to the active sample's `AcpSession` directly via Phase 1's in-process pub/sub.

- Conversation pane renders `session/update` events.
- Input line submits `session/prompt` (calls `submit_user_message`).
- Interrupt key fires `session/cancel` (calls `cancel_current_turn`).
- Acknowledge `end` notification and display final state + score when the session closes.

**Tests.** Scripted TUI session (Textual offers a test driver) driving a mockllm-backed agent: type a prompt → observe agent activity → interrupt mid-tool → type follow-up → observe recovery → agent completes → session ends. Verify no leaked sub-agent events when the agent is a deepagent (depends on Phase 12 ordering — until then, test with `react()`).

### Phase 8: `AcpServer` transport

Stand up the JSON-RPC 2.0 mux server. No ACP method dispatch yet — just transport.

- AF_UNIX socket (POSIX default) at `inspect_data_dir("acp") / f"{eval_id}.sock"`.
- TCP loopback when `--agent-acp-port=N` is passed.
- Discovery files at `inspect_data_dir("acp") / f"{pid}.json"` with `{eval_id, pid, socket_path, started}`.
- PID-liveness check + stale-file cleanup on enumerate (`os.kill(pid, 0)` / Windows equivalent).
- JSON-RPC 2.0 framing, multi-connection support, lifecycle hooks tied to the eval run.
- CLI flag plumbing: `--agent-acp` (boolean), `--agent-acp-port=N` (TCP override), `--agent-acp-socket=PATH` (socket override).

**Tests.** Spin up the server in-test, connect a JSON-RPC client, ping/echo a method; multi-connection isolation; stale-PID cleanup; socket-path override.

### Phase 9: In-channel session picker

Layer session selection on top of Phase 8's transport using only standard ACP semantics.

- On `newSession` / `loadSession`, server creates a synthetic control session unique to the connection.
- Server immediately pushes a `session/update` containing the list of attachable targets (filtered to `ActiveSample`s that have claimed ACP).
- Client's first `session/prompt` is the selection; server validates and **rebinds** the connection to the target session transparently (client's `sessionId` stays stable).
- If exactly one target exists, auto-rebind without prompting.

**Tests.** Multi-session enumeration over a real socket; pick-by-number; pick-by-id; auto-rebind on single target; client `sessionId` remains stable across rebind.

### Phase 10: Full SessionRouter + replay-on-attach

Wire the inbound and outbound ACP method surface.

- `session/prompt` → translate ACP content blocks (text/image/file refs) into `ChatMessageUser(source="operator")` and call `acp.submit_user_message()`.
- `session/cancel` → call `acp.cancel_current_turn()`.
- Forward `session/update` notifications from the in-process bus (Phase 6) out over the socket to attached clients.
- On attach (post-rebind), replay last N messages of prior transcript as `session/update` notifications, eliding tool-call payloads above a size threshold.
- Pick concrete defaults for N and elision threshold here.

**Tests.** End-to-end from a second process: connect, pick, prompt, observe `session/update`, cancel mid-turn, prompt again, see recovery, agent completes; late attach receives replay; replay respects N + elision threshold; multi-modal content survives translation.

### Phase 11: `inspect acp` CLI

Add the `inspect acp` subcommand with two modes:

- **Default (no flag)**: Textual TUI client speaking ACP over the eval socket. Shares the conversation UI with Phase 7's in-process TUI; only the transport differs (extract shared rendering code into a reusable widget).
- **`--stdio`**: stdio↔socket bridge for editors (Zed etc.) — forwards ACP traffic 1:1.

Both modes resolve the target eval via the discovery directory; if multiple evals are running, prompt the user or accept `--eval-id`.

**Tests.** Stdio fixture test that scripts an editor-shaped client through `inspect acp --stdio`; TUI smoke via Textual test driver; multi-eval resolution; manual smoke against Zed.

### Phase 12: `deepagent()` integration

Apply the same splice in `_deepagent/deepagent.py`. Sub-agent dispatch paths (`as_tool`, `handoff`, the deepagent `task()` multiplexer) must invoke `@agent`-decorated bodies so Phase 5's boundary spans land — audit and fix any path that bypasses the decorator.

**Tests.** Deepagent under ACP control via the TUI: dispatch a sub-agent task, verify sub-agent activity does *not* leak as `session/update`s (only the outer `task_call` does); interrupt mid-sub-agent task, verify the entire sub-agent task tree tears down cleanly; verify deepagent exit-on-done behavior matches react.

### Phase 13: Approval UI via `session/request_permission`

Wire Inspect's `approval` framework so that when one or more clients are attached, an approval prompt is broadcast as `session/request_permission` to all attached clients; first response wins; others receive a `session/update` marking the prompt resolved. Falls back to the existing approver behavior when no clients are attached. Configurable timeout with default-deny fallback.

**Tests.** Approver framework with mockllm; single-client approve/deny round-trip; multi-client broadcast + first-wins; client disconnect mid-prompt does not deadlock; timeout fallback; no-client fallback to existing approver.

### Phase 14: Token-level streaming

Hook into provider streaming generators to emit partial assistant message content as token-chunked `session/update`s (`agent_message_chunk` with incremental content). Wired at the provider boundary, not the transcript fan-out — transcript events fire only at message completion.

**Tests.** Live streaming providers (Anthropic / OpenAI) emit incremental chunks; final assembled content equals the completed message; cancel mid-stream interrupts cleanly without leaving the connection in a bad state; `agent_thought_chunk` correctly distinguished from `agent_message_chunk` for thinking blocks.
