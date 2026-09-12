# Monitors

Exploratory design for a new registry type, `@monitor`, that packages the
affordances a monitor needs into one object with one identity and one place to
keep state.

Status: sketch. The Python below is illustrative, not proposed API.

**Related design documents.** This one defines the protocol.
`monitor-deployment.md` covers running a monitor outside the eval process — in
a proxy on the wire — and the constraints that places on the protocol.
`inspect-core.md` covers extracting the wire types into a package light enough
for a monitor author (or another language) to depend on.

## Goal

A *monitor* watches an agent as it runs and may intervene. Concretely, the
things people build today:

- an LLM that reads each tool call and stops the sample if the call looks like
  sabotage or an exfiltration attempt
- a classifier that reads each tool *result* and stops the sample if the agent
  actually reached the internet (#5355)
- a running suspicion score accumulated over a whole trajectory, where no
  single step is disqualifying but the total is
- a heuristic that rewrites or annotates the model's input before each
  generate ("you have used 8 of your 10 allowed commands")

All four are the same idea seen from different points in the loop. Inspect has
no single object for it: each has to be assembled from a different primitive,
and the pieces cannot share state without the author inventing a place to put
it.

## What a monitor is assembled from today

| Point in the loop | Primitive | Gaps |
|---|---|---|
| Before a tool call | `@approver` | Sees nothing but the call. Fires only when the model calls a tool. |
| After a tool result | `@reviewer` (#5356, open) | New; not yet merged. |
| Before generate | `Hooks.on_before_model_generate` | Process-global and env-enabled, so not per-eval or per-task; exceptions swallowed; no transcript record; no way to terminate. |
| After generate | — | Nothing. |

And state, which is the part that hurts most. An approver is constructed once
when the eval is resolved and then called from every sample concurrently, so
`self` is shared across samples — the same hazard the `Hooks` docstring warns
about at length, with the same workaround (key a dict by `sample_id`, remember
to evict it). Nothing carries across the four points either: an approver that
wants to know what the *previous* tool returned has to go fishing in
`history`.

A monitor is the object that makes those four points one thing with one state.

## Shape

```python
class Monitor:
    """Base class for monitors.

    Override the affordances you need; the rest are no-ops. A monitor is
    constructed once per eval and called concurrently from every sample, so
    per-sample state belongs in the store (see `monitor_store_as`), not on
    `self`.
    """

    async def on_model_input(self, data: MonitorModelInput) -> MonitorDecision | None:
        """Called before each generate, before cache lookup."""
        return None

    async def on_model_output(self, data: MonitorModelOutput) -> MonitorDecision | None:
        """Called after each generate, before the output reaches the agent."""
        return None

    async def on_tool_call(self, data: MonitorToolCall) -> MonitorDecision | None:
        """Called before a tool call executes."""
        return None

    async def on_tool_result(self, data: MonitorToolResult) -> MonitorDecision | None:
        """Called after a tool call executes, before the model sees the result."""
        return None
```

Four points, two pairs: input/output around generate, call/result around a
tool. `None` from any of them means "no opinion", which is what an observing
monitor returns almost always.

Each callback takes a single frozen dataclass rather than positional
arguments, following `Hooks` rather than `Approver`. With four callbacks that
will grow fields, adding a field to a dataclass is additive; adding a
positional parameter to a protocol method breaks every implementation.

### The payloads

```python
@dataclass(frozen=True)
class MonitorModelInput:
    model: str
    input: list[ChatMessage]
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig
    state: MonitorState
    context: MonitorContext


@dataclass(frozen=True)
class MonitorModelOutput:
    model: str
    input: list[ChatMessage]
    output: ModelOutput
    state: MonitorState
    context: MonitorContext


@dataclass(frozen=True)
class MonitorToolCall:
    message: str                # assistant text alongside the call
    call: ToolCall              # the call as it will execute
    view: ToolCallView
    history: list[ChatMessage]
    state: MonitorState
    context: MonitorContext


@dataclass(frozen=True)
class MonitorToolResult:
    message: str
    call: ToolCall              # the call as executed (after any `modify`)
    result: ChatMessageTool     # what the model will see, after truncation
    output: ToolResult          # the tool's untruncated return value
    view: ToolCallView
    history: list[ChatMessage]
    state: MonitorState
    context: MonitorContext
```

`MonitorToolCall` and `MonitorToolResult` are the `Approver` and `Reviewer`
signatures from #5356 with `state` and `context` added.

### The context

A monitor cannot judge anything without knowing what the agent is *supposed*
to be doing. `curl attacker.example` is exfiltration in one task and the
entire point of the eval in another; reading `/etc/shadow` is sabotage unless
the assignment was privilege escalation. Without a briefing a monitor can only
flag things that look alarming in the abstract, which is the failure mode that
makes monitors useless — high false positives on exactly the evals that
deliberately look alarming.

```python
@dataclass(frozen=True)
class MonitorContext:
    """What the agent under observation is supposed to be doing."""

    # the standing assignment — constant across a task / a deployment
    task: str | None
    """Task name, or the deployed agent's identifier."""

    task_description: str | None
    """What agents in this setting are asked to do, and what is in bounds."""

    # this particular instance of it
    sample_id: str | int | None
    epoch: int | None

    sample_description: str | None
    """What is distinctive about this instance."""

    input: str | list[ChatMessage]
    """The prompt this agent was given."""

    metadata: dict[str, Any]
    """Author-supplied structured context (task metadata merged with sample)."""

    target: Target | None = None
    """The expected answer. None unless explicitly opted into — see below."""
```

#### Deployment-neutral, not `Task` and `Sample`

The obvious shape is to hand the monitor the `Task` and the `Sample`. Don't.
That welds every monitor to Inspect and forfeits the portability the rest of
this document spends its length preserving — a proxy has neither object and
never will.

`MonitorContext` is the same information stated in terms of the agent rather
than the framework, so both deployments can fill it:

| Field | In an eval | In a proxy |
|---|---|---|
| `task` / `task_description` | `Task` name, authored description | the deployed agent's identity and charter |
| `sample_id` / `epoch` | sample id, epoch | conversation key (see `monitor-deployment.md`) |
| `sample_description` | authored per-sample note | usually absent |
| `input` | `Sample.input` | the request's system prompt and first user turn |
| `metadata` | task + sample metadata | headers, deployment config |

#### It is the only input the agent did not write

Everything else a monitor sees — messages, tool arguments, tool output — is
agent-influenced and is a prompt-injection surface, as
[Inference, budget, and injection](#inference-budget-and-injection) notes. The
context is the exception: an eval author wrote it, or a deployment operator
did.

That makes it the anchor. A monitor should treat its context as instruction
and the conversation as *evidence*, and the framework should keep that
distinction structurally visible — separate fields, separately labelled when
rendered into a monitor's own prompt — rather than concatenating briefing and
transcript into one undifferentiated blob where a tool result can claim to be
a revised assignment. This is the single most useful thing the framework can
do about injection, and it is nearly free.

#### `target` is opt-in, and off by default

Handing the monitor the expected answer is occasionally necessary and usually
wrong.

It is necessary for a monitor scoring whether the agent sandbagged, or whether
it actually did the task rather than merely appearing to.

It is wrong for the central case, AI control evals, where the monitor stands
in for one that would run in deployment — and a deployment monitor does not
know the right answer. A monitor given the target scores better than its
deployed counterpart ever could, so the eval stops measuring what it claims
to. This is a validity problem, not an ergonomics one, and defaults decide it:
if `target` is present by default, most monitors will read it without anyone
deciding they should.

So: absent unless explicitly requested, and **recorded in the log when it was
requested**, so a reader can tell whether a monitor's measured performance is
achievable in deployment.

#### Delivered on the payload, not once per sample

The context is constant for a sample, so delivering it once (at
`on_sample_start`, say) and letting the monitor keep it looks tidier. It isn't:
keeping it means state, and a monitor that needs state to know its own
assignment can no longer be the pure function of one exchange that
`monitor-deployment.md` argues for. Putting it on every payload
costs a reference and preserves that property.

#### Where the author writes it

Neither `Task` nor `Sample` has a `description` field today — `Task` carries
`name`, `display_name`, `version`, `metadata`, `tags`; `Sample` carries
`input`, `choices`, `target`, `id`, `metadata`. So this needs somewhere to
live. Two options:

- **`Task(description=)` and `Sample(description=)`**, general-purpose authored
  prose. Two small additive fields, no monitor-specific API surface, and
  useful well beyond monitors — the viewer, model-graded scorers, and eval
  discovery all want "what is this task about" too. The risk is that a field
  named `description` attracts documentation written for humans reading the
  source, which the docstring already covers; the docstring for the field has
  to say it is a briefing for automated readers.
- **A `metadata` convention**, e.g. `Task(metadata={"description": ...})`. No
  API change at all, but undiscoverable and unvalidated.

The first, unless we are trying hard to avoid touching `Task` and `Sample`.
Structured context stays in `metadata` either way.

### The decisions

One decision type for all four affordances:

```python
MonitorAction = Literal["continue", "modify", "reject", "terminate", "escalate"]
"""Every action a monitor can take, anywhere in the loop."""

PortableAction = Literal["continue", "modify", "reject", "escalate"]
"""The subset expressible as an edit to one request/response exchange.

`MonitorAction` minus `terminate`, which is a statement about a sample
lifecycle rather than about the exchange. See `monitor-deployment.md`.
"""


class MonitorDecision(BaseModel):
    decision: MonitorAction
    modified: ToolCall | None = Field(default=None)
    """Rewritten tool call, for decision 'modify'."""
    explanation: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)
```

The field names match `Approval` and `Review` so the façade adapters
(below) are field-for-field copies.

#### Why one type and not three

The affordances look like they need different vocabularies. They mostly
don't:

| Affordance | continue | terminate | escalate | reject | modify |
|---|---|---|---|---|---|
| `on_model_input` | ✓ | ✓ | ✓ | ✓ | open (see below) |
| `on_model_output` | ✓ | ✓ | ✓ | ✓ | — |
| `on_tool_call` | ✓ (`approve`) | ✓ | ✓ | ✓ | ✓ |
| `on_tool_result` | ✓ | ✓ | ✓ | **—** | **—** |

`continue`, `terminate` and `escalate` are universal — every affordance needs
all three, with `approve` being nothing but `continue`'s name in the approval
system. That is already three quarters of `Approval` and the whole of
`Review`.

`reject` generalises further than it first appears. At `on_model_input` it
means "don't run this generate, and tell the agent why"; at `on_model_output`
it means "discard this completion". Both are coherent and both are things a
monitor plausibly wants. The one place `reject` is genuinely excluded is
`on_tool_result`, and for a *policy* reason rather than a structural one:
#5355's argument that withholding output tells the model its command failed
when it did not, so the model's picture of the sandbox diverges from the
sandbox. The same reasoning excludes `modify` on a result — redacting a leaked
credential from tool output is a real use case we are choosing not to allow,
for the same fidelity reason.

`modify` is the one action that is genuinely tool-call-shaped, because
`modified` has to carry *something* and at `on_tool_call` that something is a
`ToolCall`. Rewriting a generate's input is a different payload — messages,
tools, and config, three things rather than one — so `modify` at
`on_model_input` is left open rather than typed as a `ToolCall`. The likely
answer is that input rewriting is in-place mutation of the payload, which is
what `Hooks.on_before_model_generate` does today, and never a decision at all.
See [Open questions](#open-questions).

So: one vocabulary, universal in its first three values, with `reject`
excluded at one stage and `modify` restricted to the one stage whose payload
it fits. Not four irreconcilable vocabularies.

#### This is not the `stage` flag #5355 rejected

That argument was against a `stage` parameter on a single `Approver.__call__`,
where the caller has to branch on a runtime flag to know what it is looking
at. A monitor's stage is already encoded structurally — four separately named
methods, four distinct payload types. Sharing the *return* type does not put
the stage back into a flag, because there is no stage in `MonitorDecision` to
begin with.

#### What one type buys

Six places want to handle decisions uniformly:

1. the precedence rule under [Composition](#composition) (`terminate` >
   `reject` > `modify` > `continue`)
2. the escalation chain's fall-through
3. `MonitorEvent` — otherwise its decision field is a union or stringly typed
4. policy and YAML config parsing
5. the TUI transcript renderer
6. `analysis` dataframe columns

The cost of not sharing is already visible: #5356 had to make the approval
system "generic over the protocol" to share glob matching, the ordered chain,
decision recording, registry lookup, and config parsing between two decision
types. A third type makes that machinery worse, not better.

#### Rejected: a generic parameterised on the action set

```python
A = TypeVar("A", bound=str, default=MonitorAction)

class MonitorDecision(BaseModel, Generic[A]):
    decision: A
    ...

async def on_tool_result(...) -> MonitorDecision[ObserveAction] | None: ...
```

This is the version that keeps per-stage legality *statically* checked, and in
the abstract it is the better answer. It is the wrong answer for this
codebase:

- No serialized Pydantic model in `inspect_ai` is generic today. The only
  `Generic[...]` uses are a `list[T]` subclass in the eval recorder and the
  provider batching dataclasses, none of which reach the log schema.
- Parameterised generics get Pydantic's mangled names in
  `components/schemas` — `MonitorDecision_ObserveAction_` — which flow through
  to `generated.ts` and the barrel. `design/type-generation-pipeline.md`
  documents the RootModel-wrapper and stub-endpoint machinery that exists
  precisely to keep auto-generated, unstable names *out* of the schema. One
  logical type would become two TS types named after a Python TypeVar.

A subclass that widens the `decision` Literal is also out: widening a field
type in a Pydantic subclass is an unsound override, mypy flags it, and the
suppression gate means we could not paper over it.

#### Enforcing the restrictions

With a flat type the type checker cannot stop `on_tool_result` returning
`reject`. The dispatcher knows which method it called, so it validates there
and raises — an illegal decision is a bug in the monitor, not
agent-controlled input, so failing loudly is right. This follows AGENTS.md's
"Invalid state" rule: define the unsupported-state behavior explicitly and
cover it with a test, rather than silently coercing `reject` into `continue`.

#### Possible refinement: `modify` as an attachment, not an action

"Approve with modification" could be `continue` plus a `modified` payload,
dropping `modify` from `MonitorAction` and leaving `reject`-at-`on_tool_result`
as the single illegal combination. It also makes `modified` read as what it is,
and it makes the `on_model_input` question above disappear — a stage simply
carries whatever `modified` payload it has one for, or none.
Against it: the precedence rule needs `modify` orderable against `continue`,
which is more awkward when it is a field rather than a value, and the
`Approval` adapter stops being a field-for-field copy.

## Registration

```python
@monitor
class SuspicionMonitor(Monitor):
    def __init__(self, threshold: float = 0.8, model: str | Model | None = None) -> None:
        self._threshold = threshold
        self._model = model

    async def on_tool_call(self, data: MonitorToolCall) -> MonitorDecision | None:
        ...
```

`@monitor` decorates the class, like `@hooks` and `@sandboxenv`, rather than a
factory function like `@approver` and `@scorer`. A four-method object in a
closure reads badly:

```python
@monitor
def suspicion_monitor(threshold: float = 0.8) -> Monitor:
    class _Impl(Monitor):          # the nesting is the problem
        ...
    return _Impl()
```

Registry params come from `__init__` instead of the factory signature, so
`registry_create("monitor", "suspicion_monitor", threshold=0.9)` and the
params recorded in the log work as they do for every other registry type. The
new `RegistryType` value is `"monitor"`.

For the one-affordance case a convenience constructor keeps the terse form
available:

```python
Monitor.from_callables(on_tool_result=my_reviewer_fn)
```

### Where the decorator lives

A monitor author should be able to depend on the wire types and nothing else.
That works without a bridge: `_util/registry.py` is already a leaf — its
runtime imports are stdlib plus pydantic plus four small `_util` modules, and
every reference to `Task`, `Agent`, `Approver`, `Solver`, `Tool` and the rest
is `TYPE_CHECKING`-only, present for `registry_create`'s overloads. `registry_tag`
is two `setattr` calls and `extract_named_params` is stdlib
`inspect.signature().bind()`.

So the registry primitives move into `inspect_core` alongside the types
(`inspect-core.md`), and `@monitor` defined there registers for real — no
marker attributes, no deferred drain, no import-ordering hazard. Module
identity gives a shared singleton registry: `inspect_ai` imports the same
module object, so there is one dict rather than two to keep coherent.

Two details. `ensure_entry_points()`, called from `registry.py`, loads plugin
entry points and can therefore import arbitrary third-party packages at
runtime — it has to be injectable or a no-op in the leaf. And because
`@monitor` decorates a class, construction arguments are captured by wrapping
`__init__` and calling `registry_tag(cls, self, info, *args, **kwargs)` there;
route that through the existing `extract_named_params` rather than
reimplementing it, since it carries the VAR_KEYWORD flattening from #4374 that
makes capture-then-replay idempotent.

## State

Two scopes, per-sample and per-task, each reachable either from an argument
on the callback payload or from a global function bound to the current
context.

### Per-sample

Per-sample state is the sample `Store`, which already exists and is already
`ContextVar`-bound. A monitor runs inside the sample's context, so
`store_as(MyState)` works today with no new machinery. What a monitor adds is
automatic namespacing, so two configured instances of the same monitor don't
collide, and the monitor doesn't have to know its own instance name:

```python
class SuspicionState(StoreModel):
    score: float = Field(default=0.0)
    flags: list[str] = Field(default_factory=list)


async def on_tool_call(self, data: MonitorToolCall) -> MonitorDecision | None:
    state = data.state.sample_as(SuspicionState)     # argument form
    state = monitor_store_as(SuspicionState)         # global form
```

Both forms reach the same object. This mirrors `TaskState.store` vs the
`store()` global: the argument is for the callback body, the global is for
helper code the callback reaches into (a tool the monitor installed, a
scoring function that wants the accumulated score).

Backing per-sample state with the sample `Store` gets three things for free:
it is recorded to the transcript as `StoreEvent`s, so the monitor's reasoning
is in the log; it survives checkpoint and resume; and `store_from_events_as()`
can reconstruct it from a finished log for analysis.

### Per-task

Per-task state has no mechanism today and is the harder half.

```python
class RunTotals(StoreModel):
    terminated: int = Field(default=0)


state = data.state.task_as(RunTotals)                         # argument form
state = monitor_store_as(RunTotals, scope="task")             # global form
```

Three things are unresolved:

**Concurrency.** Samples share one event loop and interleave at every `await`.
A single `Store` operation is atomic under the GIL and no lock is warranted
(per AGENTS.md), but a read-modify-write spanning an `await` is a real race:

```python
count = state.terminated          # read
await self._classify(...)         # another sample runs here
state.terminated = count + 1      # write clobbers
```

Per-sample state never had this problem because each sample owns its store.
Task state needs either a documented "don't do that" or an atomic helper.

**Persistence.** In-memory only is the simple answer, and it means task state
starts empty on `eval_retry` and on eval-set resume — so a monitor that gates
on a cross-sample total behaves differently on a resumed run than on a fresh
one. Writing it somewhere durable means picking a home (`EvalSpec.metadata`?
a new `EvalLog` field? a task-level event stream, which doesn't exist) and
deciding when it's flushed.

**Scope.** "Task" is right for cross-sample aggregation within one task. It is
the wrong scope for anything that wants to span an `eval()` over several
tasks, and for `eval_set`. Whether there's a third scope, or whether the task
scope is really a run scope, is open.

## Configuration

Mirroring approval:

```python
Task(monitor=...)
eval(monitor=...)
inspect eval task.py --monitor monitors.yaml
```

```yaml
monitors:
  - name: suspicion_monitor
    tools: ["bash", "python"]
    params:
      threshold: 0.9

  - name: exfiltration_monitor
    tools: "*"
```

`tools` is a wart. It scopes the tool affordances the way `ApprovalPolicy`
does, but the generate affordances are not tool-scoped and would fire
regardless — so the key means "which tools this monitor's tool affordances
apply to", not "when this monitor runs". Alternatives: a separate `stages:`
key, or no globs at all (the monitor filters internally on
`data.call.function`, which it can already do and which is more honest about
the fact that a monitor is not a per-tool policy).

## Composition

Approval is an ordered chain: the first approver that doesn't `escalate`
decides, and later approvers never see the call. That is right for an
authorisation chain and wrong for a set of observers, where every monitor
should see every step whether or not another one has already decided.

Proposed split:

- **Observation is unconditional.** Every configured monitor's affordance runs
  at every applicable point.
- **The decision is the strongest one.** `terminate` > `reject` > `modify` >
  `continue`; `escalate` from a monitor means "I decline to decide", and
  all-escalate is `continue`. One `MonitorAction` ordering covers all four
  affordances, so this is a single comparison function rather than one per
  stage.
- **Every decision is recorded**, including the ones that lost.

This raises two things worth settling early:

- **Sequential or concurrent?** Three LLM monitors run in sequence triple the
  added latency at every step. `tg_collect()` (not `asyncio.gather`, per
  AGENTS.md) makes them concurrent, at the cost of making `modify` incoherent:
  a concurrent monitor cannot see another's modification.
- **Does a `modify` compose?** Two monitors rewriting the same tool call is
  either last-wins, an error, or forbidden by allowing at most one modifying
  monitor per configuration.

## Transcript

```python
class MonitorEvent(BaseEvent):
    event: Literal["monitor"] = "monitor"
    monitor: str
    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    decision: MonitorAction | None
    explanation: str | None
    metadata: dict[str, Any] | None
```

A `stage` field is fine on an event, which is a record, in a way it is not on
a protocol, which is a contract.

`decision` is typed rather than stringly typed only because the four
affordances share `MonitorAction`. With per-stage vocabularies the field would
have to be a union of three Literals correlated with `stage`, which neither
the JSON schema nor the generated TypeScript can express as a correlation —
so consumers would get `string`.

The event should be emitted for observations as well as interventions — a
monitor that scores every step and intervenes twice in a hundred samples is
the common case, and the ninety-eight quiet steps are the interesting data.
That argues for `decision: None` being a legal, recorded outcome rather than
"nothing happened, log nothing".

Open: whether `MonitorEvent` replaces `ApprovalEvent`/`ReviewEvent` when the
decision came from a monitor, or sits alongside them (two events for one
decision), or whether those events gain a `monitor` field.

## Inference, budget, and injection

- **Budget.** Monitor inference must not be charged to the agent's limits, the
  same exemption approvers get today (`suspend_token_limit()`,
  `suspend_turn_limit()` in `approval/_apply.py`). A monitor that terminates a
  sample for exceeding a token limit its own inference consumed is a trap
  worth closing up front.
- **Model role.** `get_model(role="monitor")` is the natural default, and
  `"monitor"` is already the example role name in `docs/models.qmd`. Monitor
  usage should be separable from agent usage in `ModelUsage`.
- **Injection.** A monitor reads model completions, tool arguments, and tool
  output, all of which are agent-controlled text. `docs/control-channel.qmd`
  already makes this point for monitoring agents reading the control channel;
  it applies with more force here, because this monitor's output decides
  whether the sample stops. Worth a docs section, and worth thinking about
  whether the framework should structurally help (for example by defaulting to
  delivering tool output to the monitor in a delimited, clearly-untrusted
  envelope) rather than only warning.

## Deployment beyond the eval process

A monitor is useful outside an eval — enforced at a network boundary in front
of a model API, where the agent cannot bypass it and the coverage is all agent
traffic rather than one task's samples. `monitor-deployment.md` works that
through. Four constraints from it bear on the protocol itself, so they are
recorded here:

- **Two of the four affordances are the portable core.** A proxy sees a
  request and a response; it never sees a tool execute. `on_model_input` and
  `on_model_output` map directly; `on_tool_call` is recoverable from
  `tool_use` blocks in the response; `on_tool_result` is **lossy** — a result
  appears only in the *next* request, so the last step of an episode is never
  seen. That is verbatim the limitation #5355 wrote `Reviewer` to escape, and
  `on_tool_result` should say so rather than let it be discovered.

- **`terminate` does not travel.** Every other action is an edit to the
  exchange — `continue` is no edit, `modify` a rewrite, `reject` an
  append-and-regenerate, `escalate` a hand-off down the chain. `terminate` is
  a statement about a sample lifecycle that, outside an eval, does not exist.
  Hence `PortableAction` alongside `MonitorAction`.

- **State must take an explicit key.** `data.state` survives any deployment;
  `monitor_store_as()` does not, because a proxy has no ambient context to
  bind to. The argument form is primary and the global is an in-process
  convenience — not peers.

- **`view` and the untruncated `output` must be optional.** A proxy has wire
  types, not registered `ToolDef`s, so there is no viewer to resolve.

A fifth constraint is a design decision rather than a restriction:
**monitors should be incremental by default** — classify the newest turn and
fold the verdict into accumulated state, rather than re-judging the whole
trajectory. Three independent arguments converge on it (quadratic inference
cost, linear deserialization cost, and WASM linear memory that never shrinks),
which is enough to treat it as load-bearing rather than an optimization.

The types a monitor works with also want to be importable without the eval
framework; `inspect-core.md` measures what that costs today and what it would
take.

## Relationship to approval and review

Two ways to fit `Monitor` next to `Approver` and the `Reviewer` proposed in
#5356.

**A. Monitor as a façade (preferred).** `Approver` and `Reviewer` stay as
they are. `@monitor` is a new registry type whose `on_tool_call` is adapted
into an `Approver` and whose `on_tool_result` is adapted into a `Reviewer`,
both slotted into the existing policy chains. The genuinely new code is the
two generate affordances, the state model, and the composition rules.

- Nothing existing breaks; #5356 lands on its own terms and is not blocked.
- A single-purpose approver stays a single-purpose approver — you don't have
  to write a class with three no-ops to reject one tool call.
- Cost: `MonitorDecision` has to be adapted to `Approval` and `Review` at the
  boundary (field-for-field, plus mapping `continue` to `approve`), and,
  depending on the transcript answer, possibly two events per decision.

**B. Monitor as the primitive.** `Monitor` subsumes both. `@approver` and
`@reviewer` become thin wrappers, or `@reviewer` is never introduced and
#5356's post-execution hook ships as `Monitor.on_tool_result`.

- One concept, one event, one decision vocabulary, one config key.
- Cost: it makes #5356 a prerequisite negotiation rather than a merge, and it
  raises the floor for the simple case: a single-purpose approver becomes a
  class with three no-ops. The decision types no longer argue against it —
  `MonitorAction` is already the union `Approval` and `Review` would collapse
  into — so this comes down to whether `@approver` should survive as a
  first-class concept.

The fork matters now because #5356 is open. Under A it merges unchanged.

## Open questions

1. **A or B above** — façade over the existing protocols, or the primitive
   that replaces them.
2. **Task state**: is it in-memory for v1, and if so, is the resume-asymmetry
   acceptable? Does the scope want to be task, run, or eval-set?
3. **Concurrent or sequential** dispatch of multiple monitors, and what
   `modify` means under the answer.
4. **What `modified` carries, and whether it is an action at all.** At
   `on_tool_call` it is a `ToolCall`. At `on_model_input` a rewrite is three
   things (messages, tools, config), which is why that cell of the legality
   table is open. Either input rewriting is in-place mutation of the payload
   and never a decision — what `Hooks.on_before_model_generate` does today —
   or `modify` becomes an attachment rather than an action, per the refinement
   under [The decisions](#the-decisions).
5. **Lifecycle affordances**: `on_sample_start` / `on_sample_end` would give
   per-sample state a place to initialise and a monitor a place to file a
   final verdict on a trajectory it watched but never interrupted. Natural, but
   it starts to overlap `Hooks`.
6. **Can a monitor produce a `Score`?** A suspicion score over a trajectory is
   a metric people want next to the task's own scores. If yes, this touches
   scoring, not just the agent loop, and the scope grows considerably.
7. **Bridged agents.** An agent that runs its own tool loop (`claude_code`,
   `codex`) never reaches `execute_tools()`, so the tool affordances don't
   fire — the same gap #5356 documents for reviewers. The generate affordances
   *do* fire, since bridged agents route through `bridge_generate`. A monitor
   that silently covers half a bridged agent is worse than one that says so.
8. **Is proxy portability a goal or an observation?** If a goal, the portable
   core (`on_model_input` / `on_model_output`, `PortableAction`, no ambient
   state) should be the shape the protocol is designed around and the
   in-process extras should be visibly additive. If only an observation, the
   four affordances stay peers and portability is documented rather than
   enforced. See `monitor-deployment.md`.
9. **Does `Task` / `Sample` grow a `description` field?** A public API change
   for a general-purpose affordance that monitors happen to need first. If the
   answer is no, monitor context comes from `metadata` by convention and is
   correspondingly undiscoverable. See
   [Where the author writes it](#where-the-author-writes-it).
10. **Failure semantics.** An approver exception ends the sample; a hook
   exception is swallowed and warned. A monitor is a safety mechanism, so
   failing closed (end the sample) matches the approver precedent — but that
   makes a flaky monitor model a source of eval errors. Configurable per
   monitor?
