# Running monitors outside the eval process

Companion to `monitor.md`, which defines the `Monitor` protocol. This document
covers deploying one where there is no eval: inside a proxy on the wire in
front of a model API.

Status: measured where marked, reasoned elsewhere.

## Why bother

A monitor enforced at the network boundary is tamper-resistant in a way an
in-process one is not — the agent cannot bypass it — and it covers all agent
traffic rather than only what an eval generates. There is no `Task`, no
sample, no `Store`, and the traffic is not necessarily Inspect's.

That deployment restricts the protocol sharply, which is why the constraints
belong in the design rather than in a later integration note.

## What a proxy can see

A proxy sits on one HTTP exchange: a request and a response. It never sees a
tool execute, because tools execute client-side after the response is
delivered.

So the four affordances are two, with the tool affordances recovered as
projections:

| Affordance | In a proxy | Fidelity |
|---|---|---|
| `on_model_input` | the request body | full |
| `on_model_output` | the response body | full |
| `on_tool_call` | `tool_use` blocks in the response | good |
| `on_tool_result` | `tool_result` blocks in the *next* request | **lossy** |

A proxy sees a tool result only if the agent makes another request carrying
it. The final step of an episode is never seen, and by the time a result
appears the model has already consumed it — verbatim the limitation #5355
wrote the `Reviewer` protocol to escape. No vocabulary choice fixes this; it
is a property of where the code runs, and `on_tool_result` should say so.

## Evidence from an analogous constraint

`agent/_bridge/_approval.py` already enforces a policy with nothing but a
model response to work with: a bridged scaffold runs its own tool loop, so
Inspect never executes its calls. The deployment differs — that code runs
in-process — but the constraint is the proxy's exactly. Five restrictions it
arrived at, each of which transfers:

1. **`reject` cannot be an edit to the response.** Stripping a rejected
   `tool_use` block "reads as 'turn complete' to most scaffolds, which stalls
   the agent". Rejection is a *replay*: append the rejected call and a
   synthetic result to the model's input and generate again. The proxy owns a
   retry loop.
2. **Rejection therefore needs a bound.** `MAX_CONSECUTIVE_REJECTIONS = 3`,
   because a model that keeps proposing rejected calls would loop forever.
   In-process, `react()` owns the loop and this does not arise.
3. **`modify` narrows to arguments only** — "the scaffold dispatches on the
   function name and may have no handler for a substituted one".
4. **`terminate` is out-of-band**: not in the response at all, but a side
   call, `bridge.request_terminate(...)`.
5. **`n = 1` only.** Alternate choices carrying tool calls are dropped with a
   warning, since returning them would hand the scaffold calls no approver
   saw.

Plus a payload restriction from the same file: there is **no `ToolCallView`**
— "bridged tools reach us as `ToolInfo` from the scaffold's request, not as
`ToolDef`, so there is no registered viewer to resolve." A proxy has wire
types, not registered Inspect objects.

## The restricted vocabulary

**Every portable decision is an edit to the exchange.**

| Action | As an edit | Portable |
|---|---|---|
| `continue` | no edit | ✓ |
| `modify` | rewrite the body (arguments only, for a call) | ✓ |
| `reject` | append and regenerate, bounded | ✓ |
| `escalate` | defer to the next filter in the chain | ✓ |
| `terminate` | — not an edit | **✗** |

`terminate` is a statement about a sample lifecycle — cancel sibling calls,
record an operator limit, end the epoch — and in a production deployment that
lifecycle does not merely belong to someone else, it does not exist. Envoy has
no word for it either: ext_authz is allow/deny, ext_proc is
continue/modify/immediate-response.

The nearest honest equivalent is "refuse, and keep refusing" — `reject` plus
the caller's own policy about what repeated refusal means. `_bridge/_approval.py`
demonstrates the conversion in miniature: `MAX_CONSECUTIVE_REJECTIONS` is
precisely "repeated rejection becomes termination, decided by the side that
owns the lifecycle."

So `PortableAction` is `MonitorAction` minus `terminate`. If `terminate` must
survive the trip it needs a wire convention — a sentinel `stop_reason`, a
distinguished status, a side channel — implemented at both ends. A small
contract, but a contract, and the only one on this list.

## The host ABI

The single most useful structural decision: define a monitor as pure logic
plus a small declared effect surface. Then the compilation and transport
strategy becomes a deployment detail rather than a design constraint.

```python
class MonitorHost(Protocol):
    async def generate(self, prompt: str, *, model: str | None = None) -> str: ...
    async def fetch(
        self,
        endpoint: str,                      # a NAME, not a URL — see below
        *,
        method: str = "POST",
        json: Any = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HostResponse: ...
    def get(self, key: str) -> dict | None: ...
    def put(self, key: str, value: dict) -> None: ...
    def record(self, event: dict) -> None: ...


class HostResponse(Protocol):
    status: int
    headers: Mapping[str, str]
    def json(self) -> Any: ...
    @property
    def text(self) -> str: ...
```

The same surface whether the host is Envoy via proxy-wasm, a Go runtime, or
ordinary Python in-process where these are normal implementations.

### Why `fetch` is a primitive, not an escape hatch

Monitors routinely need organisational services that are not LLMs: a
purpose-built classifier endpoint, a domain allowlist, a threat-intel feed, an
internal risk score, a SIEM sink. That is ordinary monitor work, not an edge
case.

And it cannot be `httpx`. **A WASM guest has no sockets** — all I/O crosses
the host boundary by construction. A monitor that imports an HTTP client is
not portable no matter how few other dependencies it has. So the ABI either
provides HTTP or portable monitors can only talk to a model.

### JSON-oriented, with JSON-RPC as a helper

`fetch` encodes and decodes JSON and surfaces status, rather than handing back
bytes for every monitor to re-implement encode/decode/status/error handling.

JSON-RPC then needs no separate primitive — it is a POST with a
`{jsonrpc, method, params, id}` body and an envelope to unwrap, so it is a
helper over `fetch` rather than a second ABI function:

```python
async def rpc(host: MonitorHost, endpoint: str, method: str, params: Any) -> Any:
    ...   # POST the envelope, raise on `error`, return `result`
```

**gRPC is the right thing to leave out.** In a guest it would need a protobuf
runtime and a generated stub per service compiled into the image, and most
internal JSON services do not speak it anyway. It also does not need to be in
the guest: because endpoints are *named* rather than addressed (below), a host
can expose a gRPC service behind a named endpoint and translate. The guest
always speaks JSON; whether the host turns that into REST, JSON-RPC or gRPC is
configuration.

### Named endpoints, not URLs

`fetch` takes an endpoint *name* that host configuration resolves to a URL,
auth and transport. This is the security-critical part of the design.

A monitor reads model completions, tool arguments and tool output — all
agent-controlled text, and a prompt-injection surface (see
`monitor.md`, "Inference, budget, and injection"). A monitor that can then
make arbitrary outbound HTTP calls is a confused deputy sitting on the network
boundary: **unrestricted egress turns the monitor into an exfiltration
channel**, and the payload it would exfiltrate is the conversation it was
given privileged access to.

Naming the endpoints closes that:

- injected text cannot steer a monitor to an attacker-controlled host, because
  the monitor cannot express one
- credentials never enter the guest; the host attaches them
- the deployment operator owns the egress surface and can audit it
- the same monitor runs against different endpoints in dev and prod without
  code changes, which is a portability win independent of security

A host that wants to allow arbitrary URLs can still register a `"*"`-style
endpoint, but that should be a deliberate configuration choice rather than the
default shape of the API.

### Other constraints on `fetch`

- **Timeouts and budgets are the host's.** A monitor sits in the request path;
  an external call that hangs stalls the agent. The host enforces a ceiling
  regardless of what the monitor asks for.
- **Retries belong to the host too**, for the same reason and so that retry
  policy is uniform across monitors.
- **It must be non-blocking**, exactly like `generate()` — the same
  asyncio-on-WASI question decides both.
- **Record calls for replay.** If a monitor decision is to be reproducible
  from a transcript, its external calls have to be recorded alongside its
  inputs. Worth deciding early whether `fetch` results are part of the
  recorded decision.

### Should `generate` just be `fetch`?

It could be — `fetch("model", ...)` — but keeping it distinct is better.
Model calls carry token accounting, model roles, provider retry/backoff, and
the limit-suspension semantics approvers already have (`monitor.md`,
"Inference, budget, and injection"). Collapsing them into a generic HTTP call
loses all of that, and the host would have to re-derive it from the endpoint
name.

### Two further notes

- **Regex belongs in the ABI** if transpilation is ever a target. Python's
  `re` has backtracking, lookahead and backreferences; Go's RE2 has none and
  Lua patterns are not regex. A monitor with a lookahead silently is not
  portable. Routing regex through the host makes semantics consistent by
  construction.
- **Where the ABI lives differs by path.** In the sidecar model it stays
  entirely inside Python — the sidecar implements it and the proxy only posts
  payloads. In the embedded model it becomes a real cross-language interface.
  So its design barely matters for the sidecar and matters a great deal for
  embedding: design it now even if the sidecar ships first.

## State

A proxy has no ContextVar, no sample identity and no `Store`. Two mechanisms
replace them, and they are complementary.

**The conversation is state.** Every request carries the entire history, so a
monitor that is a pure function of the request needs no storage: "has this
agent reached the internet" is recomputable by scanning messages. Nothing to
key, evict, or forge.

**A keyed store in the proxy layer.** A session header plus a local store,
carrying what the conversation does not: the monitor's own accumulated
judgment.

### The store is not merely a convenience

Re-judging the whole trajectory on every request is O(n) work at turn n, so
O(n²) across a conversation. When judging is an LLM call that is O(n²)
*inference* — by turn 40 the monitor has spent more than the agent. The
affordable shape is incremental: classify only the newest turn and fold the
verdict into running state. Incremental monitoring requires somewhere to fold
into.

It also holds what the conversation genuinely does not contain: the monitor's
own prior reasoning, a confidence trajectory, which calls it already cleared.

### Making the key trustworthy

- **Per-principal state** (API key, tenant, mTLS identity) is already
  trustworthy. Derive it from the proxy's authentication context and strip any
  client-supplied copy of the header on the way in — the ordinary gateway
  rule.
- **Per-conversation state** is harder: the authenticated principal does not
  identify a conversation, one key runs many at once, and a client can rotate
  a discriminator it supplies.

The fix comes from the first mechanism: **derive or verify the conversation
key from the conversation itself.** A fingerprint over the stable head of the
history — system prompt plus first user turn — cannot be rotated without
discarding the context the agent needs the model to have. Use the client
header as a fast path and the fingerprint as the check, or key on the
fingerprint alone.

So the store is as trustworthy as its key, and the key can be anchored in data
the agent must send truthfully.

### Operational consequences

- **No end-of-conversation signal.** Entries expire on a TTL rather than at a
  lifecycle boundary. Too short and a slow agent loses state mid-trajectory;
  too long and the store grows with every abandoned conversation.
- **Local means per-replica.** With multiple replicas a local store requires
  consistent hashing on the session key, or the state moves to shared storage.
  Sticky routing is cheaper and reuses the key that already exists.
- **Fail open on a store miss.** A cold replica, evicted entry or restart
  yields a monitor with no history. It should degrade to the pure-function
  path rather than read absent state as "nothing suspicious has happened".

### Consequence for the protocol

The two access paths in `monitor.md` are not equals here. `data.state`
survives — the dispatcher hands the monitor whatever it loaded for the key.
`monitor_store_as()` does not, because there is no ambient context to bind to.
The argument form is primary; the global is an in-process convenience.

Scopes map cleanly: per-sample becomes per-conversation, per-task becomes
per-principal — which a proxy is better placed to hold than the eval process,
since it sees every conversation rather than one task's samples.

## Serialization

The intuition that Pydantic is a cost worth avoiding does not survive
inspection.

`model_validate_json` hands raw bytes to `jiter` (Rust) and materializes only
declared fields. `json.loads` uses CPython's parser and builds a complete dict
of the entire payload, including the majority a monitor never reads. If the
model is a subset of the payload — and it is — Pydantic can win end to end. A
TypedDict-plus-`json.loads` design avoids the cheaper half of the work.

This holds in WASM too, where both are native code compiled to wasm32. Passing
raw bytes into guest memory and validating inside the guest is likely the
efficient path, and it is the Pydantic one. The Component Model alternative is
probably worse: marshaling a deeply nested variant like `ChatMessage` across
the component boundary builds intermediate representations and you still
construct Python objects on top. One parse beats two.

Where deserialization cost *does* dominate is a pure heuristic monitor whose
own work is microseconds — and the fix there is the same as everywhere else in
this document: feed it the delta rather than the whole history.

## How the Python runs there

### External processor (Envoy `ext_proc`)

| `ext_proc` phase | Affordance |
|---|---|
| `request_body` (BUFFERED) | `on_model_input` |
| `response_body` | `on_model_output` |

| `ProcessingResponse` | Action |
|---|---|
| no mutation | `continue` |
| `body_mutation` | `modify` |
| `immediate_response` | `reject`, and the `terminate` wire convention |

`ext_authz` is request-path only and cannot see the response body, so it
cannot do `on_model_output`. `ext_proc` is the one.

The Python runs unchanged. What is new is an adapter on each side — and under
the host-renders-core-JSON contract (`inspect-core.md`) the normalization half
lives in the host, so the guest needs only the core types.

### Not transpilation

The objection is not that Python-to-Go and Python-to-Lua transpilers are
immature, though they are. It is that **for a monitor the dependency graph is
the monitor**: the central operation is an LLM call, meaning an async HTTP
client, a provider SDK, and Pydantic whose core is Rust. Transpiling the
monitor means transpiling all of it — a reimplementation of the ecosystem plus
a permanent obligation to keep it in step with the Python authors test
against.

The performance case does not survive arithmetic either. A localhost hop is
well under a millisecond; an LLM-based monitor spends 200ms–2s in inference.
The transport is ~0.1% of the cost.

There is also no stable resting place: push a Python subset far enough to be
reliably portable — no deps, no `re` semantics gaps, no async — and what
remains converges on rule evaluation, at which point a declarative format is
simpler than shipping an interpreter. Keep it expressive enough to be worth
writing in Python and you need CPython in WASM.

### WASM

WASM **does** have async, in several forms — "no stack switching, therefore
host calls block" describes core WASM only:

- **Asyncify** (a Binaryen pass) instruments the module to unwind and rewind
  the stack, giving real suspension on plain WASM. Production-proven since
  ~2019; **Pyodide uses exactly this to make `await` work**. Costs roughly 2x
  code size and meaningful slowdown in instrumented paths.
- **WASI 0.2 `pollable` / `wasi:io/poll`** gives the guest non-blocking I/O.
- **Stack switching** (typed continuations) is the clean long-term answer;
  verify current proposal status rather than assuming.

The concurrency model matters more than the mechanism. One instance per
in-flight request is *not* required: if CPython's asyncio runs inside the
instance and host I/O is non-blocking, one instance serves many concurrent
invocations — the ordinary event-loop model, inside WASM. Size instances to
worker threads, not to in-flight requests. Compiled code is shared across
instances (wazero compiles once); only linear memory is per-instance.

**The load-bearing unknown** is whether CPython-on-WASI has a working asyncio
event loop driven by `wasi:io/poll`. If yes, monitors stay normal `async def`
and one instance serves many. If no, Asyncify is the fallback. Pyodide's loop
is backed by the browser's and does not transfer. This is the first thing to
prototype in the WASM direction; nothing else depends on the answer.

Two residual costs:

- **Linear memory only grows.** A large conversation becomes thousands of
  Python objects and permanently raises that instance's high-water mark; with
  pooled instances they all ratchet to the worst case. A third independent
  argument for incremental monitoring, after O(n²) inference and O(n)
  deserialization.
- **You are still shipping CPython.** Four dependencies instead of eighty
  (`inspect-core.md`) is a large improvement, but the image is ~10–20MB
  regardless. Lightweight relative to the alternative, not in absolute terms.
  Genuinely small means a rule DSL, or monitors written in a language that
  compiles small.

## Deployment recap

| | Monitor runs | Host provides | Codegen | Effort | Main catch |
|---|---|---|---|---|---|
| **Python proxy** | in-process call | nothing — ABI is native | none | hours | none; the reference deployment |
| **Go — sidecar** | Python service | HTTP client | Go structs (optional) | low | second deployable; fail-open policy |
| **Go — embedded** | CPython in wazero | ABI + normalizer | Go structs (required) | high | no sum types; pooling; memory ratchet |
| **Rust — sidecar** | Python service | HTTP client | Rust types (optional) | low | as Go |
| **Rust — embedded** | CPython in wasmtime | ABI + normalizer | Rust types (required) | medium | best tooling of the four |
| **Envoy** | ext_proc service | gRPC stream | optional | low–medium | cannot own the host |

**Python proxy** — none of this document's discipline applies. Import
`inspect_ai`, use `ChatMessage`, call the monitor.

**Go** — sidecar is hours and needs no WASM machinery. Embedded concentrates
the Go-specific cost: no sum types means the bespoke emitter
(`inspect-core.md`), and you own the async resumption model. `wazero` being
pure Go with no CGo is what makes embedded tolerable.

**Rust** — quietly the best target on both paths: `serde` tagged enums fit the
discriminated unions, `typify`/`progenitor` generate clean types, `wasmtime`
has the strongest component tooling. A Rust shop may prefer writing monitors
*in* Rust for a few-hundred-KB module — the genuinely lightweight path, at the
cost of the Python ecosystem.

**Envoy** — most constrained, because the host is not yours. `ext_proc` is the
answer; `proxy-wasm` is where the async problem is hardest, since the callback
ABI is imposed rather than chosen.

Embedding CPython in Go via CGo is the one option to avoid outright:
goroutines and the GIL are a bad marriage, and you inherit libpython plus a
venv as deployment artifacts.

## Keeping monitors portable

**The sidecar path works identically across all four deployments and needs
none of the WASM work.** That makes it the obvious thing to ship first — and
creates a trap: by the time WASM matters, the monitors that exist were written
against whatever the sidecar permitted, by people with no incentive to port.
"Ship the easy path first" quietly makes it the only path.

The enforcement surface is smaller than it looks, though, and depends on the
target. For **WASM with CPython**, arbitrary Python *language* features are
fine; the constraint is **dependencies**, so an import allowlist is nearly
sufficient. Only true transpilation would additionally constrain language
semantics.

Mitigations, in order of how much they matter:

1. **Make the sidecar execute portable monitors through the same restricted
   host ABI that WASM would use** — not merely permit it. If a portable
   monitor cannot call `get_model()` and must call `host.generate()`, every
   production run exercises the constraint and the gap between "we say it is
   portable" and "it is" goes to zero. This is the difference between a
   property and an aspiration.
2. **Default to portable; make escaping one keyword.** `@monitor(portable=False)`
   should be a deliberate, visible choice that appears in code review and the
   registry, not the accidental result of writing normal Python.
   Default-permissive loses by construction; default-strict with no escape is
   hostile to the in-process case.
3. **Make the WASM build a CI target before a deployment target.** Compile the
   portable monitor set and run the conformance corpus against it. Catches
   drift the day it appears, at a fraction of deploying.
4. **Decide `re` explicitly in the allowlist** — exclude it and route regex
   through the ABI, or include it and accept that non-CPython targets are
   foreclosed.
5. **Docs shape this more than checkers.** Whatever the examples use is what
   people write.
6. **Make the portable path not feel like a downgrade.** If it is painful,
   authors escape and the checker becomes an obstacle to route around. This is
   where `inspect-core.md` pays off twice: portable monitors get the *real*
   `ChatMessage` and `Content`, not a stripped parallel API. The restriction
   should be fewer dependencies, not worse ergonomics.

Expect two tiers regardless, and design for them: portable monitors that run
anywhere, and eval monitors using the full ecosystem in-process. An eval-time
monitor doing sklearn classification over a trajectory is legitimate work that
should not be constrained by a deployment it will never see. What matters is
that monitors *intended* to be portable actually are — verified continuously
rather than asserted — and that the default pulls toward portable so the
choice is conscious.

## Status

**Measured:** `_bridge/_approval.py`'s restrictions and their stated
rationales; the bridge provider-normalization layer; the import-closure
figures in `inspect-core.md`.

**Reasoned, not verified:** every WASM claim (build size, instance behavior,
asyncio-on-WASI), serialization throughput, and `ext_proc` latency figures.
None of this has been built.

## Open questions

1. **Is portability a goal or an observation?** If a goal, the portable core
   should be the shape the protocol is designed around and the in-process
   extras visibly additive.
2. **Does CPython-on-WASI have a working asyncio loop over `wasi:io/poll`?**
   The one prototype that resolves the WASM path.
3. **What does the `terminate` wire convention look like**, if it needs to
   exist at all?
4. **Streaming versus buffering.** `BUFFERED` gives a complete `ModelOutput`
   at the cost of time-to-first-token; `STREAMED` preserves TTFT but forces
   judgment on partial output, after some tokens have reached the agent. A
   custom proxy can do better than either — forward text blocks while
   withholding `tool_use` blocks until cleared — which is a real capability
   difference from Envoy worth weighing in a build-versus-adopt decision.
5. **Recursion guard.** The monitor's own LLM call must not traverse the proxy
   it runs inside; it needs a distinct route, upstream, or skipped header.
6. **gRPC body limits.** The 4MB default is tight for LLM traffic, which
   re-sends the whole conversation each request.
7. **Are `fetch` results part of a recorded decision?** Replaying a monitor
   from a transcript requires its external calls to be recorded, which means
   deciding what is safe to record (an allowlist response is fine; a
   credentialed payload may not be).
8. **Fail open or closed** when the processor is down. A safety monitor wants
   closed, which makes it a hard dependency on the request path.
