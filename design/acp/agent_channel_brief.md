# Implementation Brief: Migrate `acp_session()` to a generic `agent_channel()`

> **Scope in one line:** Generalize the existing ACP-specific session/cancellation mechanism (`acp_session()` and its turn-cancel exception) into a source-agnostic agent-runtime primitive (`agent_channel()` / `AgentInterrupted`), with ACP refactored to be one *producer* on top of it. This is a **behavior-preserving refactor** and the **first step** toward a larger general-purpose orchestration capability described under "Context" below. **The orchestration features themselves are out of scope for this task.**

## Audience and prerequisites

You are a coding agent with full access to the Inspect AI repository (`inspect_ai`). This brief specifies one focused refactor. It assumes familiarity with Inspect's agent layer (`@agent`, `AgentState`, the `react()` agent), the ambient execution-context accessors (`transcript()`, `store()`, the limit context managers), and the existing ACP integration.

**Read the existing code before writing any.** In particular, locate and read: the current `acp_session()` accessor and everything that constructs, accesses, or tears it down; the turn-cancel exception it currently uses and every site that raises or catches it; the `react()` implementation and how it interacts with ACP cancellation today; the agent protocol / `AgentState` definitions; and the ambient context accessors and how they are scoped via contextvars (use the limit context managers as a model for scope-style context managers). Do not assume the names and shapes in this brief match the repo exactly — confirm against the code and adapt, preserving existing ACP behavior.

## Context (motivation — NOT this task)

We are, separately and later, building a single-directive, autonomous, multi-agent **orchestrator** hosted on Inspect's execution engine: a long-horizon agent that works one top-level directive and spawns subagents to parallelize work. That future system needs several kinds of intervention into a *running* agent — operator messages and interrupts (via ACP), model-initiated human input (an `ask_user` tool), and orchestrator→subagent control (steer and kill).

The design principle we have settled on is that all of these should funnel through **one source-agnostic primitive owned by the agent runtime**, rather than accreting a separate ad-hoc mechanism ("band") per intervention source. The mental model is the actor model: each agent execution is an addressable entity with a channel; producers send it **messages** (cooperative, processed at turn boundaries) and **signals** (forceful, preempt the current work).

**Today, the cancellation mechanism is welded to ACP** (`acp_session()` owns it). That coupling is the thing blocking the broader work. This task removes it. You are not building the orchestrator, the subagent supervisor, or `ask_user` — you are generalizing the substrate so they become "write a producer" later. Keep the broader direction in mind only so your design choices stay forward-compatible (see "Forward-compatibility").

## This task

Generalize `acp_session()` → `agent_channel()` and make ACP a consumer/producer rather than the owner of cancellation. Concretely:

1. **Introduce the core primitive** in the agent runtime (`inspect_ai.agent` or wherever the ambient accessors live): `agent_channel()`, the channel type, an `AgentRef` producer-side handle, and `AgentInterrupted`. Source-agnostic; ambient; **not** on `AgentState`.
2. **Make `react()` (and the agent runtime generally) a consumer** of the channel: drain at turn boundaries, wrap each turn's foreground work in an interruptible scope, catch `AgentInterrupted`.
3. **Migrate the ACP integration to a producer**: it holds an `AgentRef` and calls `post` / `interrupt`; it no longer owns or raises the cancel exception, and the core no longer references ACP.
4. **Preserve ACP behavior exactly.** An operator attached over ACP must see identical behavior before and after this change. This is a refactor, not a feature.

### ACP attachment is top-level-only (preserve this constraint)

Today `acp_session()` noops in nested contexts — ACP applies only at the top level. Preserve that, but **relocate where the constraint lives**: it must become a property of *the ACP producer's attachment*, not of the channel mechanism.

- `agent_channel()` is uniform and functional at **every** level. Nested executions get a real, working channel (future producers — e.g. a subagent supervisor — will use nested channels to steer/kill children). Do not make the channel itself aware of nesting.
- **ACP attaches as a producer to the top-level execution's channel only.** It must capture the top-level `AgentRef` at the run entry point and hold exactly that. It must **not** acquire a ref by calling `agent_channel()` ambiently from inside an arbitrary context — ambiently that returns the *current*, possibly nested, channel. ACP has no path to nested channels and does not look for them.
- Do **not** reintroduce noop-when-nested inside the channel. The channel never knows whether it is nested; top-level-ness is purely ACP's binding policy.
- **Behavior parity is automatic:** a nested channel with no producer attached is inert (per inert-by-default), so a nested context behaves exactly as it does today when ACP noops there. The channel is present but silent until some future producer attaches.

Forward note (not this task): once subagents exist, operator control over a *child* is mediated through the top-level orchestrator — the operator interrupts/redirects the top level and the orchestrator decides whether to kill children — since ACP deliberately never reaches nested channels directly.

### Naming (settled)

- Accessor: **`agent_channel()`** — returns the current execution's channel; ambient, in the `transcript()` / `store()` family. Replaces `acp_session()`.
- Exception: **`AgentInterrupted`** — raised when the current execution's interruptible scope is cancelled. Generalizes the old ACP-specific turn-cancel exception. A `react()`-level alias using "turn" vocabulary is acceptable, but the core exception is execution-level and must not carry react or ACP concepts.
- Producer-side handle: **`AgentRef`** — what a producer (ACP now; supervisor later) holds to address an execution's channel. Same underlying channel, opposite vantage point.
- Channel surface: **`post`** (data plane), **`interrupt`** (control plane), **`scope`** (interruptible region; a context manager), **`drain`** (consume queued items at a boundary).

## Architecture for this task

### Layering and dependency direction

```
inspect_ai.agent (core)
  ├─ agent_channel() ............. ambient accessor, per execution
  ├─ AgentChannel ................ post / interrupt / scope / drain
  ├─ AgentRef .................... producer-side handle to a channel
  └─ AgentInterrupted ............ raised by a cancelled scope

consumers (depend on core):        producers (depend on core):
  └─ react()                         └─ ACP client integration
     (and any @agent)

  [future, NOT in this task: Deep Agent / SWE / custom consumers;
   subagent supervisor, ask_user, operator console producers]
```

The core owns the channel, the scope, and the exception. `react()` and ACP both depend on the core and **never on each other**. This inverts today's coupling, where the ACP layer owns cancellation. After this change, adding a new intervention source is "write a producer," and adding a new agent type gets interruptibility for free — but you are only wiring `react()` and ACP now.

### The channel

A per-execution, source-agnostic conduit carrying **typed items**. Design the item type as an **open/extensible union** so future item types slot in without touching the core, but only implement the two item types ACP needs now:

- `UserMessage` — from an operator send (or any injected user turn) → appended to the conversation as a user message at the next boundary.
- `Cancel(reason)` — control plane; the only item that travels the control plane (see below).

Reserve room for (do **not** implement now): `Announce(run_id, result)` for future subagent completion and `Steer(...)` for future orchestrator→child messaging. A short comment noting these are intentionally deferred is enough.

Note on `ask_user`: a separate, parallel effort adds a model-callable `ask_user` tool (see "Related work" below). That tool deliberately does **not** route its answer through `agent_channel` — it is an agent-initiated request/response that uses ACP's native `elicitation/create` surface and its own resolver abstraction, not an operator-initiated push. So do **not** add a `ToolAnswer` channel item in anticipation of it. (A durable, resume-surviving variant of `ask_user` may revisit this much later, but that is out of scope for both efforts now.)

Suggested shape (adapt to repo conventions):

```python
def agent_channel() -> AgentChannel: ...   # ambient; valid only inside a running execution

class AgentChannel:
    def post(self, item: InterventionItem) -> None: ...
        # data plane: enqueue for drain at the next boundary
    def interrupt(self, item: CancelItem) -> None: ...
        # control plane: enqueue AND cancel the currently-bound scope (if any)
    def scope(self) -> ContextManager[None]: ...
        # demarcates an interruptible region; cancelling it raises AgentInterrupted inside
    def drain(self) -> list[InterventionItem]: ...
        # sole-consumer drain; non-blocking; returns and clears queued items
```

### Two delivery disciplines, one band

- **Data plane (`post`)**: producer enqueues; the consuming agent drains at its own boundaries. Non-preemptive; cannot affect an in-flight model call, it simply waits for the boundary.
- **Control plane (`interrupt`)**: producer enqueues a `Cancel` item **and** cancels the channel's currently-bound scope. Cancellation surfaces as `AgentInterrupted` inside the running region; the agent catches it, drains (now seeing the cancel marker plus any follow-up message a producer posted alongside), and continues.

This is exactly how ACP's "stop, then redirect" must work after migration: the operator's interrupt becomes `ref.interrupt(Cancel(...))` optionally followed by `ref.post(UserMessage(...))`. The agent is preempted, then on its next drain sees the redirection. Confirm this reproduces today's ACP behavior.

### Scope binding and "interrupt degrades to deliver"

The channel holds a reference to the **currently bound interruptible scope** (if the agent has entered one):

- An agent enters `with agent_channel().scope():` around work it is willing to have preempted.
- `interrupt()` cancels the bound scope. If **no scope is bound** (between regions, or just finished one), `interrupt()` must degrade gracefully to a plain `post()` of the cancel item, drained at the next boundary. So "interrupt" means **"preempt if a region is running, otherwise just deliver"** — no race window to special-case.
- The forceful path is **runtime-enforced**: because the runtime (not the agent) owns the scope, `interrupt()` works even on an agent that never drains. (The cooperative `post` path requires the agent to drain. This asymmetry — forceful always works, cooperative requires cooperation — is intentional; preserve it.)

### `react()` changes (consumer)

`react()` becomes a consumer of `agent_channel()`. Sketch (adapt to the real loop):

```python
ch = agent_channel()
while not done:
    for item in ch.drain():            # fold queued items before generating
        apply(item, state)             # for now: UserMessage -> append user turn
    try:
        with ch.scope():               # react's choice: one interruptible region per turn
            output = await model.generate(state.messages, tools)
            state = handle(output, state)   # tool execution INSIDE the scope (see note)
    except AgentInterrupted:
        for item in ch.drain():        # pick up the cancel marker + any redirect message
            apply(item, state)
        continue
```

Requirements:
- Drain at the top of each iteration and again in the `AgentInterrupted` handler.
- Wrap a turn's foreground work in exactly one `scope()`, and **the scope must enclose tool execution, not just `generate()`.** A blocking tool (e.g. a future `ask_user`, or a slow tool) must be cancellable by an `interrupt()` mid-call; if tool execution sits outside the scope, an operator interrupt can't preempt a tool the model is waiting on. (This stays compatible with the future no-cascade rule: a non-blocking spawn tool returns immediately and its detached child is not *awaited* inside the scope, so cancelling the scope cancels blocking awaits without touching detached children.)
- **Inert default:** with no producers attached, `react()` must behave identically to current `main` — drain returns empty, no scope ever cancels. This is the most important regression guard.
- Keep "turn" vocabulary inside `react()` only; the core exception stays `AgentInterrupted`.

### Invariants to hold (relevant now)

- **Channel is ambient and ephemeral**, never serialized, **never on `AgentState`** (keeps `AgentState` clean and serializable — important for the future checkpointing work).
- **Single-writer:** producers (the ACP layer) only ever enqueue via `post`/`interrupt`; only the consuming agent loop mutates `state.messages`, and only at a drain. Add an assertion/guard if feasible.

## Forward-compatibility (design now so later work isn't boxed in — but don't build it)

These are not tasks; they are constraints on *how* you build the above so the deferred work slots in cleanly:

- Keep the channel and exception **free of any ACP-specific assumptions**. ACP is just the first producer.
- Make the **item type extensible** (open union / registrable types) so `Announce`, `Steer`, and any future items can be added later without touching the core. (Note `ask_user` answers are *not* such an item — see "The channel" and "Related work".)
- Design `scope()` so that, in the future, cancelling a parent's turn will **not** cascade into detached child tasks (children will run in their own scopes on their own channels). You don't have children now, so you can't test this — just don't design a scope that would force cascade.
- Be aware that ambient contextvars are captured at task-creation time, so a future detached child task will need its **own** channel established inside its context rather than inheriting the parent's. Nothing to implement now; just don't build in an assumption that there is exactly one channel per process.

## Testing requirements

1. **Inert default:** a `react()` run with no producers attached behaves identically to current `main` (transcript/snapshot equivalence). *(Primary regression guard.)*
2. **ACP behavior parity:** existing ACP operator flows (attach, send message, interrupt) produce the same observable behavior as before the migration.
3. **Cooperative message:** `post(UserMessage)` mid-run is folded in at the next boundary, not before.
4. **Forceful interrupt:** `interrupt()` during a long `generate()` raises `AgentInterrupted`; the loop drains and continues, applying any posted redirect.
5. **Interrupt degrades to deliver:** `interrupt()` with no scope bound is delivered at the next boundary without error.
6. **Dependency direction:** the core module does not import or reference ACP; the ACP layer no longer raises/owns the old turn-cancel exception and instead goes through `agent_channel()`.
7. **Single-writer:** a producer cannot mutate `state.messages` except via drain (assertion/guard test).
8. **ACP top-level-only:** a nested agent execution exposes a functional `agent_channel()` but receives no ACP interventions, and the observable behavior of a nested context is unchanged from `main`. ACP holds only the top-level `AgentRef` and has no path to nested channels (e.g. an interrupt issued over ACP affects only the top-level execution's bound scope).

## Suggested implementation order

1. Add the core: `AgentChannel`, `agent_channel()`, `AgentRef`, `AgentInterrupted`, scope binding, the extensible item type with `UserMessage` + `Cancel` concrete. Inert; nothing wired yet.
2. Make `react()` a consumer (drain + scope + catch). Verify inert-default equivalence (test 1).
3. Migrate the ACP layer from `acp_session()`/owned-cancel to a producer using `AgentRef` + `post`/`interrupt`. Remove ACP ownership of the cancel exception. Verify ACP parity and the remaining tests.
4. Delete or alias `acp_session()` per repo deprecation conventions; update call sites and docs.

## Related work: the parallel `ask_user` effort (coordinate, do not merge)

A separate effort adds a model-callable `ask_user` tool (structured questions answered by a human, via ACP's `elicitation/create` plus a resolver/notifier abstraction). It is **architecturally independent** of this task — it is agent-initiated request/response (pull), whereas `agent_channel` is operator-initiated intervention (push) — but the two efforts physically touch the same ACP integration files (`connection.py`, `session.py`, `session_live.py`) and both reference the ACP session accessor. To avoid collisions:

- **Land this migration first.** It is small and foundational and it renames/generalizes the ACP session accessor. Doing it first lets the `ask_user` effort build against the post-migration ACP transport rather than against a name that is about to change.
- **`request_elicitation` (and the elicitation client registry) belong on the ACP transport layer**, which survives this migration as the channel *producer* — not on `agent_channel`. Keep elicitation off the channel entirely.
- If the two run concurrently, the deprecation-alias of `acp_session()` (per the implementation order below) keeps an in-flight `ask_user` working through the alias until it can be repointed.
- The interruptibility requirement above (scope must enclose tool execution) is what makes a pending `ask_user` cancellable by an operator interrupt; that is the only behavioral dependency between the two, and it lives entirely on this side.

## Explicitly out of scope (future PRs)

Note these as the trajectory so reviewers see where this leads, but **do not implement**:
- Subagent supervisor (spawn / steer / kill / announce, registry, status block, concurrency caps, per-child limits).
- The generic `ask_user` tool (a separate, parallel effort using ACP elicitation + resolvers — see "Related work"; it does not route through this channel).
- Resume reconciliation / orphaned-spawn scan; the top-level-turn, disposable-subagent checkpoint contract; idempotent re-dispatch.
- Detached child channels and their contextvar/transcript-nesting handling.
- Multi-session/channel-based ingress, a gateway daemon, persistent cross-process session storage.
- ACP permission-gating of high-stakes actions.

## Definition of done

- `agent_channel()`, `AgentChannel`, `AgentRef`, and `AgentInterrupted` exist in the agent core, are ambient, are out of `AgentState`, and are inert with no producers attached.
- `react()` consumes the channel (drain + single scope per turn + catch `AgentInterrupted`) with no behavior change when no producers are attached.
- The ACP integration is a producer: it goes through `post`/`interrupt` and no longer owns or raises the turn-cancel exception; the core has no ACP dependency.
- ACP attaches only to the top-level execution's channel (captured at run entry), nested channels exist but ACP never produces to them, and the top-level-only constraint is preserved without any nesting-awareness inside the channel.
- `acp_session()` is removed/aliased per repo conventions, with call sites and docs updated.
- All tests above pass; existing eval and ACP behavior is unchanged.
- The item type is extensible and the deferred item types are noted but unimplemented.

## A note on judgment

This brief encodes a specific decoupling. If, while reading the actual code, you find that the repo's existing conventions make a cleaner fit than what is described here (where the ambient context is established, how scopes compose with the existing limit context managers, deprecation/alias style for `acp_session()`), prefer the repo's grain and flag the deviation in your summary rather than forcing this brief's exact shape. The **non-negotiables** are: one source-agnostic primitive (not an ACP-owned mechanism), core ownership with inverted dependencies (core never depends on ACP), the channel ambient and out of `AgentState`, runtime-enforced `interrupt` vs. cooperative `drain`, ACP attachment remaining top-level-only as a binding policy (not as channel-level nesting-awareness), behavior-preserving for current ACP usage, and inert-by-default for evals with no producers. Everything beyond that is deliberately deferred to later PRs.
