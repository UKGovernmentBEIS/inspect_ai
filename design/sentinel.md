# Sentinel

Exploratory design for two new registry types, `@monitor` and `@protocol`: one annotated function per point in the agent loop, with one identity and one place to keep state. A monitor observes and returns evidence; a protocol decides and returns an action, consulting monitors if it has any. A protocol with no monitors is a rule.

*Sentinel* is the umbrella: the name of the feature, and of one configured tree — a protocol with its monitors — as passed to `Task(sentinel=)` and recorded as a `SentinelEvent`. Inside it, *monitor* and *protocol* keep their AI-control-literature senses, which are also ControlArena's: the monitor is a scorer, the protocol decides. An earlier draft used "monitor" for both the umbrella (`Task(monitor=)`) and the scorer, and reviewers read the umbrella as "the monitor plus the protocol"; renaming the umbrella rather than the scorer keeps the literature's pair intact.

Status: sketch. The Python below is illustrative, not proposed API.

**Related design documents.** This one defines the protocol. `sentinel-deployment.md` covers running a sentinel outside the eval process — in a proxy on the wire — and the constraints that places on the protocol. `sentinel-development.md` covers measuring and calibrating a monitor before it acts, by replaying it over transcripts as an Inspect Scout scanner. `inspect-core.md` covers extracting the wire types into a package light enough for a monitor author (or another language) to depend on.

## Goal

A *monitor* watches an agent as it runs and reports what it sees; a *protocol* decides whether to intervene. Concretely, the things people build today:

- an LLM that reads each tool call and stops the sample if the call looks like sabotage or an exfiltration attempt
- a classifier that reads each tool *result* and stops the sample if the agent actually reached the internet (#5355)
- a running suspicion score accumulated over a whole trajectory, where no single step is disqualifying but the total is
- a heuristic that rewrites or annotates the model's input before each generate ("you have used 8 of your 10 allowed commands")

All four are the same idea seen from different points in the loop. Inspect has no single object for it: each has to be assembled from a different primitive, and the pieces cannot share state without the author inventing a place to put it.

## What a sentinel is assembled from today

| Point in the loop | Primitive | Gaps |
|------------------------|------------------------|------------------------|
| Before a tool call | `@approver` | Sees nothing but the call. Fires only when the model calls a tool. |
| After a tool result | `@reviewer` (#5356, merged 2026-09-11) | Decision vocabulary is `continue` / `terminate` / `escalate` only — no score, no rewrite. Ships as a parallel subsystem to approval rather than sharing one. |
| Before generate | `Hooks.on_before_model_generate` | Process-global and env-enabled, so not per-eval or per-task; exceptions swallowed; no transcript record; no way to terminate. |
| After generate | — | Nothing. |

And state, which is the part that hurts most. An approver is constructed once when the eval is resolved and then called from every sample concurrently, so `self` is shared across samples — the same hazard the `Hooks` docstring warns about at length, with the same workaround (key a dict by `sample_id`, remember to evict it). Nothing carries across the four points either: an approver that wants to know what the *previous* tool returned has to go fishing in `history`.

A monitor and a protocol are the two objects that make those four points one thing with one state: the first observes, the second decides.

## Prior art {#prior-art}

A survey of the AI-control literature and of shipped guardrail APIs, done after the first draft of this design. It changed the architecture — see [Protocols](#protocols) — so it is recorded rather than summarised away.

### Independent convergence on the four affordances

The OpenAI Agents SDK ships exactly four decorators: `@input_guardrail`, `@output_guardrail`, `@tool_input_guardrail`, `@tool_output_guardrail`. That is `BeforeGenerate` / `AfterGenerate` / `BeforeToolCall` / `AfterToolCall`, arrived at independently. It uses a different return type per stage, which is the thing [What a monitor returns](#what-a-monitor-returns) argues against.

Its input guardrails also take a `run_in_parallel` flag: run the guardrail concurrently with the agent (cheaper wall-clock, the agent may burn tokens before cancellation) or block first (no wasted tokens, higher latency). That is a knob we do not have and probably want.

### The control literature separates scoring from deciding

This is the finding that reshaped the design.

[Ctrl-Z](https://arxiv.org/abs/2504.10374) formalises deployment as a protocol that observes each action and may **accept**, **resample**, **defer**, or **audit** it. The mechanics are specific:

- the audit budget is **1% of actions per episode**, allocated by exponential decay so scrutiny is stricter early, when attacks are likelier
- there are **two thresholds over one score** — a lower deferral threshold and a higher auditing threshold — both calibrated against known-benign score distributions and adjusted for remaining budget
- **resampling** draws up to two further samples and executes the least suspicious one that clears the deferral threshold
- **incrimination** exploits multi-sample variance: a malicious policy attacks consistently across samples, an honest one varies. A three-strikes rule audits when suspicion crosses threshold three times in a task
- **deferral** substitutes the weaker trusted model's action outright

The original AI Control paper adds **trusted editing**: the trusted model rewrites the untrusted output to remove suspicious parts, then submits the edit.

Two structural lessons:

1.  **The monitor is a scorer.** Thresholds are not monitor knowledge — they need calibration against benign distributions and depend on global remaining budget and position in the episode. Deferral, resampling and auditing are things a *protocol* does with a score.
2.  **`audit` is a second axis, not a peer action.** You can accept-and-audit or block-and-audit; Ctrl-Z's two thresholds sit over the same score.

### Structured scores resist collusion; single scores do not

[TraceGuard](https://arxiv.org/html/2604.03968v1) scores five independent dimensions — goal alignment, constraint adherence, reasoning coherence, safety awareness, action-trace consistency — with parallel independent LLM calls, and reports **95% safety versus 0% for single-score monitoring** when the untrusted monitor is also the agent. The mechanism is fragmenting evaluation so no single compromised model sees the whole assessment.

That turns "run monitors concurrently or in sequence" from a latency question into a safety one: independence is the point. It also argues the suspicion signal should be structured and first-class rather than a scalar buried in `metadata`.

### Collusion has a taxonomy, and the cheapest attack is the strongest

[Untrusted monitoring safety cases](https://arxiv.org/html/2602.20628v1) enumerate passive self-recognition (the monitor recognises its own style, no pre-agreed signal), active causal collusion (a pre-agreed signal), active acausal collusion (Schelling points), and combinations — and find that **passive self-recognition via fine-tuning beats the previous state of the art**. The strategy requiring no coordination at all is the hardest to stop.

Countermeasures are honeypotting (feed known-bad input to catch a dishonest monitor), signal jamming (minification, variable normalisation, natural language summarisation) and auditing.

All of these are **pipeline stages, not monitor logic**: paraphrasing sits between agent output and monitor input; honeypots are synthetic inputs injected into the monitor's stream. They belong to a protocol.

### Reasoning is a distinct signal

[CoT monitorability](https://arxiv.org/abs/2507.11473) argues reasoning traces are a monitorable safety signal that development choices can erode. TraceGuard's framing is sharper for us: *outputs look clean but reasoning is off*. Inspect has `ContentReasoning`, so whether a monitor sees it is a decision we have to make rather than inherit — and the evidence says yes, scored separately from actions.

### What shipped products converged on

- **Claude Code hooks** — `PreToolUse` returns `permissionDecision` of `allow` / `deny` / `ask`, plus `updatedInput` (rewritten arguments, not a whole call), `additionalContext` (the model sees it) and `systemMessage` (the operator sees it, the model does not). All matching hooks run in parallel; any `deny` blocks; context accumulates. `PostToolUse` can read the result but **cannot block or modify it** — the gap #5355 identified, in a shipped product.
- **Guardrails AI** runs a standalone Guard Server over HTTP, which is explicitly why it has the best non-Python story. That is our sidecar conclusion, independently reached.
- **NeMo Guardrails** uses Colang, a rule DSL, at 100–300ms added latency — the endpoint `sentinel-deployment.md` predicts a restricted Python subset converges on.
- **Portkey** integrates external guardrails by webhook, which is what the host ABI's `fetch` is for.
- Output guardrails under streaming are an open problem in the OpenAI SDK too.

### What we took, and what we left

Absorbed: the monitor/protocol split, structured scores, `audit` as a flag, prepackaged protocols, `additionalContext` and `systemMessage` as separate channels, the `run_in_parallel` knob, reasoning visibility. The disagreement between the two traditions about what a monitor emits was absorbed too, as [two registry types](#monitor-or-protocol) — monitors that observe, protocols that decide — rather than as a field convention.

Deliberately **not** in the core surface: honeypots, paraphrasing, resampling payloads, collusion-resistant untrusted monitoring. These matter to a small number of control researchers, carry real conceptual weight, and are better served by the protocol extension surface than by the sentinel protocol. See [Keeping it simple](#keeping-it-simple).

## Shape

A monitor and a protocol are each an async function, produced by a registered factory in the idiom every other Inspect decorator uses. **Which of the four points it watches is given by the type of its second parameter** — there is no separate stage argument, and no base class. **Which of the two it is is given by the decorator**, and the return type must agree.

``` python
@protocol
def no_curl() -> ControlProtocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        """A rule: a protocol with no monitors. Called before a tool call executes."""
        if step.call.function == "bash" and "curl" in step.call.arguments.get("cmd", ""):
            return Decision.reject("network access is out of bounds")
        return None

    return decide


@monitor
def suspicion_monitor(model: str | None = None) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        """A monitor: scores the step, never acts on the score."""
        ...

    return check
```

```python
Task(sentinel=no_curl())                                        # a rule acts
Task(sentinel=threshold(suspicion_monitor(), reject_at=0.8))    # a monitor acts through a protocol
```

The four payload types are the vocabulary:

| Payload | Fires |
|------------------------|------------------------|
| `BeforeGenerate` | before each generate, before cache lookup |
| `AfterGenerate` | after each generate, before the output reaches the agent |
| `BeforeToolCall` | before a tool call executes |
| `AfterToolCall` | after a tool call executes, before the model sees the result |

Two pairs: input/output around generate, call/result around a tool. `None` means "didn't participate". A monitor returns an `Observation`, which is evidence; a protocol returns a `Decision`, which is an action. See [What monitors and protocols return](#what-a-monitor-returns).

A monitor watches one point; a protocol may watch one or all four. A concern spanning two points is two monitors — see [One function, one point](#one-function-one-point), which argues that this is rarer than it looks and that the framework is better for not having a construct for it.

Each takes a single frozen dataclass rather than positional arguments, following `Hooks` rather than `Approver`. The parameter is named `step` rather than `Hooks`' generic `data`: all four payloads are the thing under examination, and a monitor examines a step in the agent's trajectory — the unit the control literature scores. `step.call`, `step.output`, `step.history` read as a subject; `data.call` reads as a bag. Per-stage names (`generate.input`, `call.call`) were the alternative, and the tool side sinks them. With four payloads that will grow fields, adding a field to a dataclass is additive; adding a positional parameter breaks every monitor.

### The payloads

``` python
@dataclass(frozen=True)
class BeforeGenerate:
    model: str
    input: list[ChatMessage]
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig
    escalations: tuple[Reported[Decision], ...] = ()


@dataclass(frozen=True)
class AfterGenerate:
    model: str
    input: list[ChatMessage]
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig
    output: ModelOutput
    escalations: tuple[Reported[Decision], ...] = ()


@dataclass(frozen=True)
class BeforeToolCall:
    message: str                # assistant text alongside the call
    call: ToolCall              # the call as it will execute
    view: ToolCallView
    history: list[ChatMessage]
    escalations: tuple[Reported[Decision], ...] = ()


@dataclass(frozen=True)
class AfterToolCall:
    message: str
    call: ToolCall              # the call as executed (after any `modify`)
    result: ChatMessageTool     # what the model will see, after truncation
    output: ToolResult          # the tool's untruncated return value
    view: ToolCallView
    history: list[ChatMessage]
    escalations: tuple[Reported[Decision], ...] = ()


Step: TypeAlias = BeforeGenerate | AfterGenerate | BeforeToolCall | AfterToolCall
"""The union, for code that handles any point — a protocol, or a dispatcher."""
```

`AfterGenerate` carries the request that produced `output` — `input`, `tools`, `tool_choice`, `config` — as well as the output, because a protocol that substitutes an action (`resample`, `defer_to_trusted`) has to regenerate with exactly what the agent was given.

A monitor never annotates `Step`, since [its annotation is what selects the stage](#the-stage-comes-from-the-annotation). The alias exists for the layer above, which does see all four.

**Everything in `step` is agent-influenced; nothing in `context` is.** `call`, `message`, `history`, `view`, `result` and `output` are all written or shaped by the agent under observation and are therefore injection-bearing; the briefing is author-written, the store is the monitor's own, the host is the framework's. Splitting them across two arguments makes that boundary structural rather than a matter of field ordering, which is the most useful thing the framework can do about injection (see [It is the only input the agent did not write](#it-is-the-only-input-the-agent-did-not-write)). Which of these fields a given monitor is actually shown, and how they are rendered into its prompt, is the monitor's [view](#views).

`escalations` is the one exception, and it is worth naming as such. It is filled by an [ordered composition](#two-compositions-concurrent-and-ordered): when an earlier link in a chain returns `escalate`, its report is handed to the next link here, so a human at the end of the chain sees who is asking and why. The reports are protocol-authored rather than agent-authored, but they may quote agent text in their explanations, so a monitor rendering them into its own prompt should label them as prior verdicts rather than as instructions. The field is per-step, which is why it lives on the payload and not on `Context`, and it is empty everywhere except inside a chain. Approval's equivalent is a block appended to `view.context`; a first-class field is used instead because `view` exists only on the tool stages and is absent under a proxy.

`BeforeToolCall` and `AfterToolCall` are the `Approver` and `Reviewer` payloads. `AfterToolCall` is a faithful dataclass-ification of the merged `Reviewer.__call__`, which takes exactly `message`, `call`, `result`, `output`, `view` and `history` — this document predicted the shape from the PR and it survived contact with the merged code unchanged. The before/after naming earns its keep here: `BeforeToolCall` carries a `call: ToolCall` and `AfterGenerate` an `output: ModelOutput`, so a payload named for the object it wraps would collide with a field inside itself.

### The context

`Context` carries everything ambient to the step: the briefing, the monitor's own memory, and the effects it may perform. The briefing is the part that needs arguing for.

A monitor cannot judge anything without knowing what the agent is *supposed* to be doing. `curl attacker.example` is exfiltration in one task and the entire point of the eval in another; reading `/etc/shadow` is sabotage unless the assignment was privilege escalation. Without a briefing a monitor can only flag things that look alarming in the abstract, which is the failure mode that makes monitors useless — high false positives on exactly the evals that deliberately look alarming.

``` python
@dataclass(frozen=True)
class Context:
    """Everything ambient to the step under examination.

    Three roles, deliberately on one object because all three are constant
    for the sample while the step is not: the briefing (what the agent is
    supposed to be doing), the monitor's own memory, and the effects it may
    perform. This is the `TaskState` shape — flattened primary fields plus
    namespaced sub-objects.
    """

    # -- the briefing: the standing assignment, constant across a task
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

    # -- the monitor's own memory
    store: Store
    """This monitor's per-sample state, namespaced. Raw form."""

    def store_as(self, model_cls: Type[SMT], *, scope: Scope = "sample") -> SMT:
        """Typed view of this monitor's state. Mirrors the global `store_as()`."""

    # -- effects
    host: Host
    """Inference, keyed storage, outbound JSON, and recording.

    The only sanctioned route out of a monitor. Defined in
    `sentinel-deployment.md`; in-process these are ordinary implementations,
    in a proxy they cross the host boundary.
    """

    target: Target | None = None
    """The expected answer. None unless explicitly opted into — see below.

    Last because it is the only defaulted field, and a dataclass cannot put an
    undefaulted field after one that defaults.
    """
```

#### Deployment-neutral, not `Task` and `Sample`

The obvious shape is to hand the monitor the `Task` and the `Sample`. Don't. That welds every monitor to Inspect and forfeits the portability the rest of this document spends its length preserving — a proxy has neither object and never will.

`Context` is the same information stated in terms of the agent rather than the framework, so both deployments can fill it:

| Field | In an eval | In a proxy |
|------------------------|------------------------|------------------------|
| `task` / `task_description` | `Task` name, authored description | the deployed agent's identity and charter |
| `sample_id` / `epoch` | sample id, epoch | conversation key (see `sentinel-deployment.md`) |
| `sample_description` | authored per-sample note | usually absent |
| `input` | `Sample.input` | the request's system prompt and first user turn |
| `metadata` | task + sample metadata | headers, deployment config |

#### It is the only input the agent did not write

Everything else a monitor sees — messages, tool arguments, tool output — is agent-influenced and is a prompt-injection surface, as [Inference, budget, and injection](#inference-budget-and-injection) notes. The context is the exception: an eval author wrote it, or a deployment operator did.

That makes it the anchor. A monitor should treat its context as instruction and the conversation as *evidence*, and the framework should keep that distinction structurally visible — separate fields, separately labelled when rendered into a monitor's own prompt — rather than concatenating briefing and transcript into one undifferentiated blob where a tool result can claim to be a revised assignment. This is the single most useful thing the framework can do about injection, and it is nearly free.

#### `target` is opt-in, and off by default

Handing the monitor the expected answer is occasionally necessary and usually wrong.

It is necessary for a monitor scoring whether the agent sandbagged, or whether it actually did the task rather than merely appearing to.

It is wrong for the central case, AI control evals, where the monitor stands in for one that would run in deployment — and a deployment monitor does not know the right answer. A monitor given the target scores better than its deployed counterpart ever could, so the eval stops measuring what it claims to. This is a validity problem, not an ergonomics one, and defaults decide it: if `target` is present by default, most monitors will read it without anyone deciding they should.

So: absent unless explicitly requested, and **recorded in the log when it was requested**, so a reader can tell whether a monitor's measured performance is achievable in deployment.

#### Passed on every call, not stashed once per sample

The context is constant for a sample, so handing it over once (at `on_sample_start`, say) and letting the monitor keep it looks tidier. It isn't: keeping it means state, and a monitor that needs state to know its own assignment can no longer be the pure function of one exchange that `sentinel-deployment.md` argues for. Passing it on every call costs a reference and preserves that property.

It is a separate argument rather than a payload field because it is invariant while the step is not — re-attaching an identical object to every payload invites the question of whether it could differ — and because two arguments state the monitor's job in the signature: here is what should be happening, here is what just happened. Two-argument callbacks are the local idiom (`Solver(state, generate)`, `Scorer(state, target)`), and OpenAI's guardrails likewise take context first.

The forward-compatibility argument for single-dataclass payloads still holds: it rules out *many* parameters, not two. Every future addition lands inside `Context` or inside a step payload, so the arity stays stable.

#### Where the author writes it

Neither `Task` nor `Sample` has a `description` field today — `Task` carries `name`, `display_name`, `version`, `metadata`, `tags`; `Sample` carries `input`, `choices`, `target`, `id`, `metadata`. So this needs somewhere to live. Two options:

- **`Task(description=)` and `Sample(description=)`**, general-purpose authored prose. Two small additive fields, no sentinel-specific API surface, and useful well beyond monitors — the viewer, model-graded scorers, and eval discovery all want "what is this task about" too. The risk is that a field named `description` attracts documentation written for humans reading the source, which the docstring already covers; the docstring for the field has to say it is a briefing for automated readers.
- **A `metadata` convention**, e.g. `Task(metadata={"description": ...})`. No API change at all, but undiscoverable and unvalidated.

The first, unless we are trying hard to avoid touching `Task` and `Sample`. Structured context stays in `metadata` either way.

### What monitors and protocols return {#what-a-monitor-returns}

A monitor **reports**; it does not act. What it hands back is evidence. A [protocol](#protocols) decides what actually happens, and what it hands back is an action.

``` python
Action = Literal["continue", "modify", "reject", "terminate", "escalate"]
"""What a protocol can decide about the thing it just examined."""


class Observation(BaseModel):
    """Evidence, for a protocol to calibrate and threshold. What a monitor returns."""

    suspicion: Suspicion
    """How suspicious. Required — an Observation with no score says nothing."""

    explanation: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class Decision(BaseModel):
    """What should happen. What a protocol returns; advisory to any protocol wrapping it."""

    action: Action
    """Required."""

    audit: bool = Field(default=False)
    """Request that oversight budget be spent on this."""

    authoritative: bool = Field(default=False)
    """A decision no protocol may weaken. Set by human(); see 'Authoritative decisions'."""

    modified: ToolCall | ChatMessageAssistant | BeforeGenerate | None = Field(default=None)
    """Replacement for the step's subject, for a 'modify' decision."""

    explanation: str | None = Field(default=None)
    """Why. Operator-facing by default; see 'Two audiences' below."""

    metadata: dict[str, Any] | None = Field(default=None)


Report: TypeAlias = Observation | Decision
"""What the transcript records; the union nothing else needs to handle."""
```

The report type is the registry type. A `@monitor` function returns `Observation | None`, a `@protocol` function returns `Decision | None`, and neither can return the other — see [Monitor or protocol?](#monitor-or-protocol) for how to pick, and [The kind is the decorator](#the-kind-comes-from-the-return-annotation) for how it is checked.

#### The name says the layering

`Decision.action` reads as a command, and under this split it is one: the thing that returned it is the thing configured to decide. What softens it is nesting — a child protocol's decision is advisory to the protocol above it, which may overrule it ([Child decisions are advisory](#child-decisions-are-advisory)) — and the transcript carries that as two fields, `decision` (what this layer returned) and `outcome` (what happened). An earlier draft called the type `Decision`, because a leaf monitor could also return one and "decision" was accurate only when nothing wrapped it. With leaves out of the picture the shorter name is accurate at every position, and the event's two fields say the rest.

#### Progressive disclosure through defaults, not through the return type {#progressive-disclosure-through-defaults-not-through-the-return-type}

Most monitors touch one field of their report type. That does not require the return type to be polymorphic — every field but the required one has a default:

``` python
@monitor
def network_suspicion() -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation(suspicion=0.9 if reaches_external_network(step.call) else 0.0)

    return check
```

An earlier draft accepted a bare `float` or `dict[str, float]` as well, on the theory that the simplest monitor should be a function returning a number. Dropped, for three reasons:

- **`Scorer` is the local precedent and it points the other way.** It returns `Score | None` — a required object — with the polymorphism *inside*, as `Score.value: Value`. That is the pattern to copy: wrap the flexible value, keep the return type fixed. (`Task(approval=)` accepting a str, a config object or a list is an *input* parameter; permissive inputs and permissive returns are different questions.)
- **A bare value has no name.** `return 0.9` gives a reader nothing — suspicion, or confidence that it is safe? `dict[str, float]` is worse: score dimensions, or metadata? Named fields settle it at the call site.
- **The saving is 24 characters**, against a coercion branch in the dispatcher and an ambiguity in every monitor anyone reads.

So the return type is the report type or `None`, matching `Score | None`. The polymorphism that genuinely helps stays inside, as `Suspicion`.

Progressive disclosure survives intact: a monitor sets `suspicion` and ignores the rest, and a rule sets `action` and never learns what `audit` or `modified` do until it needs them. That was always the useful half — the complexity reduction came from [pushing work up to the protocol](#protocols), not from shaving a constructor call.

#### Three states, all distinct

| Return | Who | Meaning | Recorded |
|------------------------|------------------------|------------------------|------------------------|
| `None` — *abstain* | either | didn't participate | no |
| `Observation` | a monitor | examined, no verdict — here is evidence | yes |
| `Decision` | a protocol | examined, and here is what happens | yes |

Call the first case **abstaining**, not "returning None". "Return `None`" and "`suspicion` is `None`" mean entirely different things — didn't participate, versus this report carries no score — and writing both as "None" in prose is the fastest way to confuse a reader. The API spells abstention `None`; the docs should not.

Abstaining rather than a sentinel value (`Report.none()`) follows `Scorer`, which returns `Score | None`, and avoids fighting Python: a rule with an early exit writes `if step.call.function != "bash": return`, which yields `None` whatever the signature says. A sentinel would either have to accept `None` anyway — a second spelling for one state, which is what the empty report was rejected for — or force a constructor call on the most common path, since a targeted rule abstains on nearly every call. The general rule: `None` is right for absence when there is exactly one kind of absence, it carries no data, and it is unambiguous with "not yet computed". All three hold here, and a null object buys nothing because a protocol must branch on "did anyone report" regardless.

Named constructors are still worth having, for common *valid* reports rather than for abstention — sugar over existing states, not new ones:

``` python
Decision.clear()                       # action="continue" — examined and cleared
Decision.reject("why")                 # action="reject"
Decision.terminate("why")              # action="terminate"
Decision.escalate()                    # action="escalate" — pass it on
Observation.score(0.9)                 # suspicion=0.9
Observation.flag("why")                # suspicion=1.0 — a detector, not a scorer
```

A monitor has no way to say `continue`, and that is deliberate rather than a gap. Forcing a scorer to say `continue` would be a lie — in Ctrl-Z the monitor genuinely has no view, because deferral versus audit depends on budget it cannot see — and it would corrupt the precedence rule, since a monitor reporting suspicion 0.95 would be voting `continue`. Putting the two return types in two registry types is what makes that structural: a monitor has no `action` field to be forced to fill, and no decorator under which returning one type-checks.

An earlier draft had one type with every field optional and two validators — "at least one of `suspicion`, `action`, `audit`", and "`modified` iff `action == 'modify'`". The split absorbs the first entirely: `Observation.suspicion` and `Decision.action` are required fields, so `Report()` is not constructible and there is no error message to get right. The second validator survives, inside `Decision`, because it relates two of its own fields. It mirrors `Approval.modified`.

The alternative — allow an empty report and record it as a no-op observation — was rejected because it creates a fourth state indistinguishable in effect from `None`, while still producing a transcript record. "I examined this and found nothing" is already expressible, and better, as `action="continue"` or `suspicion=0.0`.

This also keeps `continue` meaningful rather than filler. **`continue` = I examined this and cleared it**; `escalate` = I decline to decide, pass it on; `None` = I wasn't involved. A chain needs all three.

#### Monitor or protocol? {#monitor-or-protocol}

The split is not ours. It is the seam between the two bodies of prior art surveyed above, which disagree about what a monitor even emits:

| | Emits | Prior art |
|------------------------|------------------------|------------------------|
| **a monitor** | an `Observation` — a score, for someone else to threshold | Ctrl-Z's trusted monitor; TraceGuard's five dimensions. [The control literature separates scoring from deciding](#the-control-literature-separates-scoring-from-deciding) — "the monitor is a scorer", and accept/defer/resample/audit belong to the protocol |
| **a protocol** | a `Decision` — an action | every shipped guardrail: Claude Code's `permissionDecision: allow \| deny \| ask`, OpenAI's tripwire, Guardrails AI's pass/fail, NeMo's Colang rules |

The literature's word for the second thing is "protocol", and shipped products have no word for the first. So the names are the literature's, and the shipped-guardrail shape — a function that looks at one step and says what should happen — is a protocol with no monitors: a *rule*.

Examples of each:

| Thing | Write it as | Report |
|------------------------|------------------------|------------------------|
| LLM judge over a tool call | monitor | `suspicion=0.87` |
| TraceGuard-style dimensions | monitor | `suspicion={"goal_alignment": 0.1, "sabotage": 0.8, ...}` |
| Running trajectory score | monitor | accumulated in the store, reported each step |
| CoT monitor | monitor | reasoning scored separately from the action |
| `no_curl` | protocol (a rule) | `action="reject"` |
| `rm -rf /` guard | protocol (a rule) | `action="reject"` |
| Strip `--force` from a call | protocol (a rule) | `action="modify", modified=...` |
| A person | protocol (`human()`) | whatever they say, `authoritative=True` |

Note that `Observation` keeps the shape [Progressive disclosure](#progressive-disclosure-through-defaults-not-through-the-return-type) already argued for: `Suspicion` is the flexible value, `Observation` the fixed wrapper — exactly `Score` and `Value`.

**Choosing is not determined by the use case.** #5355's network-egress classifier is legitimate either way: a monitor if you want a protocol to calibrate the cut point, a rule if the detection is definitive. One question decides it:

> **Do you want to own the threshold?** Yes → a protocol. No → a monitor.

And the split makes the failure this guards against unrepresentable rather than merely detectable. A monitor that computes a score and compares it to a constant has nothing to *do* with the comparison — it cannot return an action — so the constant has nowhere to hide. If you find yourself wanting to act on a score inside a monitor, you have found the reason `threshold()` exists. And if the check is definitive with no score in it — a string match, a path outside the sandbox — it is a rule, and a rule is a protocol.

A detector sits between: it has no score but it is not sure enough to be a rule, or its author wants it dry-runnable and backtestable before it acts. `Observation.flag()` is for that — a monitor reporting `suspicion=1.0` — and `threshold(detector(), reject_at=1.0)` turns it into a rule at configuration time. That path is a choice, not a default: a bare monitor [records only](#observe-only-is-the-default).

#### What the docs should lead with

A rule, then a monitor wrapped in `threshold()`.

[Keeping it simple](#keeping-it-simple) rules out leading with a scoring monitor: that means explaining what the number is, what consumes it, what a threshold is and why you do not set it — the entire control vocabulary inside "write your first monitor". A deterministic rule needs none of it: `@protocol def no_curl()` returning `Decision.reject(...)` is the `@approver` experience with more points to attach to, and it is what people arrive expecting, having used Claude Code hooks or the OpenAI SDK.

The second example is a monitor under `threshold()`, which introduces the score and the constant together — the score in the monitor, the constant in the protocol — and that is the whole control vocabulary a first-time author needs. `observe()`, calibration and the shipped control protocols come after, at the moment someone's check produces a number they are not sure where to cut.

#### Suspicion is structured

``` python
Suspicion: TypeAlias = float | dict[str, float]
```

A scalar is accepted, but the multi-dimensional form is the one to encourage: TraceGuard reports 95% versus 0% safety for structured versus single-score monitoring against a colluding monitor (see [Prior art](#prior-art)). A protocol can threshold per dimension, and dimensions can be scored by independent monitors so no single model sees the whole assessment.

#### `audit` is a flag, not an action

Auditing — spending scarce human review — is orthogonal to what happens to the action. You can continue-and-audit or reject-and-audit. Ctrl-Z's deferral and auditing are two thresholds over one score, not two values in one enum.

`audit` lives on `Decision` rather than `Observation`, because "spend human review on this" is itself a policy statement; a monitor flags something by scoring it high. The budget is the outermost protocol's: an inner protocol *requests* an audit, the outer one grants it if budget remains.

An earlier draft called this the first concrete consumer of per-task state. It is not. Ctrl-Z's budget is **1% of actions per episode** ([Prior art](#prior-art)), and an episode is one agent trajectory — one sample. So the canonical audit budget is per-*sample* state, which `context.store_as(BudgetState)` already handles with no new machinery. A budget pooled across samples is a different and also defensible design, but it is not what the literature specifies, and [Per-task](#per-task) is not on the critical path because of it.

#### Authoritative decisions {#authoritative-reports}

[Child decisions are advisory](#child-decisions-are-advisory): whatever wraps a protocol may honour or ignore what it decided. One class of decision is not, and the doc previously carried it as a prose rule — "a protocol may override advisory decisions, never authoritative ones" — with nothing in the data to enforce it. `authoritative` is that rule made into a field.

`human()` sets it. When a person has looked at a call and rejected it, no threshold, budget or aggregation above them gets to turn that into `continue`; the same holds for a human `approve`, which a protocol may not escalate past. The [dispatcher checks this at every layer boundary](#the-boundary-check): a protocol whose return is weaker than an authoritative report from one of its own children has a bug, and the check raises rather than quietly restoring the human's answer.

It is a field on the decision rather than a flag on the protocol because the combiner reads decisions, not protocols, and because the log should show which decisions in a trajectory were a person's. Nothing stops an LLM-backed protocol from setting it, and nothing should — the framework cannot verify that a human was involved, only that the author claimed authority — but the claim is visible in the transcript and in code review, which is the same discipline `portable=False` relies on.

#### Two audiences

Claude Code hooks separate `additionalContext` (the model sees it) from `systemMessage` (the operator sees it, the model does not). We should too, and the reason is security rather than tidiness: **telling an agent why it was flagged teaches it to evade.** `explanation` should be operator-facing by default, with a separate, explicit field for anything the model is meant to read.

That separate field is also the soft intervention we otherwise lack — a way to say "continue, but the model should know X" without rejecting anything.

#### One vocabulary across stages

This is a different axis from the split above. `Observation` and `Decision` split by *who emits it* — a monitor or a protocol; nothing here splits by *where it runs*. A `BeforeToolCall` monitor and an `AfterGenerate` monitor both return `Observation`, a protocol at either returns `Decision`, and `Action` is one Literal across all four stages. The stages look like they need different vocabularies; they mostly don't:

| Stage             | continue | terminate | escalate | reject | modify       |
|-------------------|----------|-----------|----------|--------|--------------|
| `BeforeGenerate`  | ✓        | ✓         | ✓        | ✓      | open (below) |
| `AfterGenerate`   | ✓        | ✓         | ✓        | ✓      | —            |
| `BeforeToolCall`  | ✓        | ✓         | ✓        | ✓      | ✓            |
| `AfterToolCall`   | ✓        | ✓         | ✓        | **—**  | **—**        |

`continue`, `terminate` and `escalate` are universal. `reject` generalises further than it looks: at `BeforeGenerate` it means "do not run this generate, and tell the agent why"; at `AfterGenerate`, "discard this completion". It is genuinely excluded only at `AfterToolCall`, and for a *policy* reason — #5355's argument that withholding output tells the model its command failed when it did not, so the model's picture of the sandbox diverges from the sandbox. The same reasoning excludes `modify` on a result.

**`modified` carries a replacement for the *subject* of the step**, and the subject is stage-determined exactly as the payload type is:

| Stage | Subject | `modified` carries |
|------------------------|------------------------|------------------------|
| `BeforeGenerate` | the request | a `BeforeGenerate`, built with `dataclasses.replace(step, input=...)`; `model` unchanged |
| `AfterGenerate` | the assistant message | `ChatMessageAssistant` — **not** `ModelOutput` |
| `BeforeToolCall` | the call | `ToolCall` |
| `AfterToolCall` | — | `modify` is not legal, per the policy reason above |

The `AfterGenerate` row is the one that needed working out, and it is what unblocks resampling and trusted editing. `ModelOutput` is `model`, `choices`, `completion`, `usage`, `fallback`, `time`, `metadata`, `error` — of which only `choices[0].message` is substitutable *content*. `usage`, `time` and `model` describe the call that actually happened. If a protocol draws three completions and executes the least suspicious, three completions' worth of tokens really were spent, and swapping the whole `ModelOutput` would either discard that or falsify it. So the framework substitutes the message and leaves the accounting alone.

Only `choices[0]` is monitored and substitutable, matching `_bridge/_approval.py`'s `n = 1` restriction — alternate choices carrying tool calls that no monitor saw are the thing that restriction exists to prevent.

#### Why not in-place mutation, given the hook does exactly that {#why-not-in-place-mutation}

`Hooks.on_before_model_generate(data) -> None` mutates its payload, and its docstring promises those mutations reach the cache key and the API call. Worth understanding how, because it looks like it contradicts our frozen payloads: `BeforeModelGenerate` *is* `@dataclass(frozen=True)`. Frozen protects the *binding*, not the contents — and `input: list[ChatMessage]` and `tools: list[ToolInfo]` are mutable containers, so a hook appends to `data.input` rather than reassigning it.

We deliberately don't follow that precedent. A monitor that mutates its payload is side-effecting, which forfeits being a pure function of `(context, step)` — the property `sentinel-deployment.md` depends on end to end. A proxy deserializes the payload, hands it to the monitor, and has no way to notice that a list was mutated in place; it can only look at what was returned. Returning a replacement costs one `dataclasses.replace()` and keeps every deployment honest.

#### This is not the `stage` flag #5355 rejected

That argument was against a `stage` parameter on a single `Approver.__call__`, where the caller branches on a runtime flag to know what it is looking at. A monitor's stage is already encoded structurally, and more tightly than the class form managed: the payload type *is* the stage, so a monitor that reads `step.result` cannot have been registered for `BeforeToolCall`. Sharing the *return* type does not reintroduce a stage flag, because there is no stage in `Report` to begin with.

#### What one type buys

Six places want uniform handling: the precedence rule under [Composition](#composition); the escalation chain's fall-through; `SentinelEvent`, whose decision field would otherwise be a union or stringly typed; policy and YAML config parsing; the TUI transcript renderer; and `analysis` dataframe columns.

The cost of not sharing is already paid, and it is larger than an earlier draft of this document guessed. That draft assumed #5356 would generalise the approval system over the decision type. It did not: `approval/` was not touched at all, and `review/` ships a parallel `_policy.py`, `_registry.py`, `_apply.py` and `_call.py` — **413 lines, 20–62% textually similar to their approval counterparts.** Glob matching, the ordered chain with escalate fall-through, registry lookup and config parsing all exist twice. A third decision type would make it three times.

#### Rejected: a generic parameterised on the action set

``` python
A = TypeVar("A", bound=str, default=Action)

class Decision(BaseModel, Generic[A]):
    action: A
```

This keeps per-stage legality statically checked and is the better answer in the abstract. It is the wrong answer for this codebase:

- No serialized Pydantic model in `inspect_ai` is generic today. The only `Generic[...]` uses are a `list[T]` subclass in the eval recorder and the provider batching dataclasses, none of which reach the log schema.
- Parameterised generics get Pydantic's mangled names in `components/schemas` — `Decision_ObserveAction_` — which flow to `generated.ts` and the barrel. `design/type-generation-pipeline.md` documents the machinery that exists precisely to keep unstable auto-generated names out of the schema.

A subclass that widens the `action` Literal is also out: widening a field type in a Pydantic subclass is an unsound override, mypy flags it, and the suppression gate means it could not be papered over.

#### Enforcing the restrictions

With a flat type the type checker cannot stop an `AfterToolCall` protocol deciding `reject`. The dispatcher knows which stage it dispatched, so it validates there and raises — an illegal decision is a bug in the protocol, not agent-controlled input, so failing loudly is right. This follows AGENTS.md's "invalid state" rule: define the unsupported behavior explicitly and cover it with a test rather than silently coercing `reject` into `continue`.

## Protocols {#protocols}

**A monitor observes and reports. A protocol authorizes and acts.**

That split came out of [Prior art](#prior-art) and is the main architectural consequence of it. In Ctrl-Z the monitor is a scorer; deferral, resampling and auditing are things the protocol does with the score, because they depend on calibration against benign distributions and on a global budget the monitor cannot see.

**"Protocol" is a registry type, and deciding is what puts something in it.** A protocol is any registered function that returns a `Decision`. Most consult monitors — `threshold` reads their scores — or compose other protocols — `chain` and `concurrent` — and those are combinators, the shape Inspect already uses everywhere it composes: `chain(*solvers) -> Solver`, `multi_scorer(scorers, reducer) -> Scorer`, `policy_approver(policies) -> Approver`. But a protocol may have no children at all: `human()` asks a person, `no_curl()` matches a string. Those are rules, and they are protocols because they decide, not because they compose. See [A protocol may have no children](#a-protocol-may-have-no-children) and [The `@protocol` decorator](#the-protocol-marker).

The layering below is therefore mostly about *what code does*. The structural claims are typed; the behavioural ones — that a protocol invokes its children through [the runner](#the-runner) and never weakens an authoritative report — are enforced at the boundary where they can be and recorded where they cannot. [What the collapse costs](#what-the-collapse-costs) keeps the honest residue.

Applying the split shrinks the monitor surface rather than growing it. Every control-literature action turns out to live above the monitor:

| Control action | Whose job | How |
|------------------------|------------------------|------------------------|
| `accept` | protocol | below every threshold |
| `audit` | protocol | grants a monitor's `audit` request if budget remains |
| `defer` | protocol | calls the trusted model and substitutes its action |
| `trusted_edit` | protocol | has the trusted model rewrite, then substitutes |
| `resample` | protocol | draws more samples, scores each, picks or incriminates |

None are expressible by something looking at one exchange, so `Action` does not grow. Resampling is the one that needs more than a wider vocabulary — it needs a protocol that regenerates and substitutes, which [Two that generate](#two-that-generate) shows.

The collusion countermeasures land here too: paraphrasing and minification are a transform between agent output and monitor input; honeypots are synthetic inputs injected into the monitor's stream. Pipeline stages, not monitor logic.

### Two philosophies, both first-class {#two-philosophies-both-first-class}

The [two registry types](#monitor-or-protocol) are not just two shapes of data. Each implies a way of deciding, and the design has to support both rather than treating one as the degenerate case of the other.

- **Rules, no monitors.** The protocol decides directly from what it sees. No thresholds, no calibration, no budget. This is the shipped-guardrail philosophy — and it is not hypothetical in Inspect, because **it is exactly what `@approver` does today.** An approver consults nothing, its decisions are authoritative, and nobody regards that as unsafe.
- **Monitors under a calibrated protocol.** The monitor never decides; thresholds, budget and actions all live in the protocol that reads it. This is the control-literature philosophy, and it is what `threshold`, `defer_to_trusted` and `resample` are for.

Neither is the advanced version of the other. What a protocol is *for* becomes sharper as a result: **a protocol exists to decide.** When there is a score, deciding means thresholding it; when there is not, the rule is the decision.

That collapses to a single rule about what sits at the top of a configuration:

> **Whatever is outermost must be a protocol, or nothing acts.**

| `Task(sentinel=)` given | Compiles to |
|------------------------|------------------------|
| a monitor, or a list or mapping of monitors only | `observe(...)` — recorded, never acted on, **and this is how the benign distribution for calibration gets collected** |
| a protocol, or any list or mapping containing one | `concurrent(...)` — protocols vote, monitors are recorded |

This is where the split pays for itself: there is no mixed case to warn about, because anyone reading the configuration can see which entries are protocols, and a monitor beside a rule in a list is doing exactly what a monitor does everywhere — recording. `observe()` is the ordinary way to say that recording is the intent rather than an oversight, and to dry-run a set of monitors under no protocol at all.

The monitor-only row is worth dwelling on: it looks degenerate and isn't. Calibration needs a benign score distribution, and running with nothing consuming the scores over known-benign tasks is how you get one. It is step one of the second philosophy, not a failure to configure.

### Child decisions are advisory {#child-decisions-are-advisory}

A protocol's `Decision` is an opinion **whatever wraps it** may honour or ignore. Where nothing wraps it, there is nothing to ignore it and it is honoured — the approval model above.

Within a wrapping protocol this is forced rather than chosen. `concurrent` combines its children's decisions by precedence and `chain` takes the first, so an inner decision is input to an outer one, never a bypass of it. If an inner `terminate` went around the protocol that wraps it, a protocol could not promise anything about what its configuration does.

The distinction that makes this coherent is **declared versus inferred**. [A bare monitor records only](#observe-only-is-the-default) because acting on it would mean acting on a number the author never thresholded. A rule's action was *declared*: someone who writes `Decision.reject(...)` is not surprised when a call is rejected, any more than an approver author is surprised today, so a rule at the top level acts.

One rule then covers the bimodality: **a wrapping protocol may override advisory decisions, never authoritative ones.** A human's rejection is authoritative and stays so — a threshold overriding a human would be a safety regression. An earlier draft left this as a rule about *what a protocol should do*; it is now carried on the decision as [`authoritative`](#authoritative-reports) and enforced by [the boundary check](#the-boundary-check).

### A bare monitor records only {#observe-only-is-the-default}

`Task(sentinel=suspicion_monitor())` with nothing wrapping it compiles to `observe(suspicion_monitor())`: it scores, records to the transcript, and never intervenes. For a monitor, enforcement is opt-in, and it is spelled by wrapping it in a protocol.

It is the safe default, and for a specific reason rather than a general caution about safety: a threshold nobody set is a threshold nobody calibrated, so acting on one is acting on a number whose meaning is unestablished. A scoring monitor whose scores nobody reads is a safety mechanism failing open, and under `observe()` that is a *declared mode* rather than an accident.

There is no corresponding question for a rule. A protocol at the top level acts, because its action was declared by its author rather than inferred from an uncalibrated number, and defaulting to silence would mean a rule that does nothing until you learn about a layer you had no reason to need. `@approver` has worked this way for years.

One config-time check remains, and it is the only one:

> `suspicion_monitor` is a monitor and nothing is configured to act on it — wrap it in a protocol such as `threshold()` to act, or `observe()` to say that recording is intended.

An earlier draft needed three such warnings — a decision-returning monitor under `observe()`, a score nobody reads, and a list where half acts and half records — because a monitor could return a decision and the configuration could not show which entries would. The split removes the case rather than the warnings: the decorator says which entries decide, and the remaining message is about a real "safety mechanism with no consumer" state, which AGENTS.md's "invalid state" rule asks to be named rather than silently accepted.

### Ship protocols, not parts {#ship-protocols-not-parts}

The control literature's protocols are a small, finite, well-studied set. Ship them named and configured so nobody assembles thresholds, budgets and actions by hand:

``` python
Task(sentinel=observe(network_suspicion()))
Task(sentinel=threshold(network_suspicion(), reject_at=0.8))
Task(sentinel=defer_to_trusted(network_suspicion(), threshold=0.8))
Task(sentinel=resample(network_suspicion(), threshold=0.8, n=3))
```

This is the same move as shipping `react()` and `basic_agent()` rather than making everyone write a tool loop. It converts "understand the control literature" into "pick from a list", and the papers become an explanation of *why* each protocol exists rather than required reading.

#### What the names mean {#what-the-names-mean}

The literature's protocols are all arrangements of three resources with different trust levels: an **untrusted model** (capable, possibly scheming — it does the work), a **trusted model** (weaker, believed not to be scheming), and **trusted human labour** (scarce; this is the audit budget).

| Protocol | The arrangement |
|------------------------|------------------------|
| `concurrent` | run every child, strongest decision wins; what a list containing a protocol compiles to. Not from the literature — it is the concurrent composition itself, named |
| `chain` | run children in order, first non-`escalate` decides; approval's chain as a protocol |
| `observe` | record every monitor's score; never act. What a list of monitors compiles to, and how a benign distribution gets collected |
| `threshold` | act on a score: `reject` above one constant, `terminate` above another. The smallest protocol, and the one calibration feeds |
| `defer_to_trusted` | above a threshold, substitute the trusted model's action for the untrusted one's |
| `resample` | above a threshold, draw further completions, score each, execute the least suspicious; escalate if none clears (Ctrl-Z; multi-step settings only) |
| `trusted_monitoring` | the trusted model scores the untrusted model's output; the most suspicious slice, up to an audit budget, goes to human review and the rest is accepted |
| `trusted_editing` | the trusted model rewrites the suspicious parts rather than replacing the whole action |
| `untrusted_monitoring` | the *untrusted* model scores — more capable, but it may collude, so it needs honeypots and lie detection |

The first six ship in core. The last three are extension candidates, with the pipeline stages (honeypots, paraphrasing). `trusted_monitoring` is the surprising one to leave out, since it is the literature's baseline; the reason is the audit budget. It is a deployment-economics idea — the scarce resource being modelled is human labour — and as a headline parameter it means "how much to *not* review", which reads badly to the eval operators this package is for, who want to see everything flagged. Nothing stops an extension shipping it, and `threshold` plus `audit=True` is the eval-shaped version.

Two things follow that a reader should not have to infer.

**The threshold comes from the budget, not from the score.** "Audit the most suspicious 1%" rather than "audit anything above 0.8". That is the whole reason [thresholds cannot live inside a monitor](#monitor-or-protocol): you need the benign score distribution to know which value *is* the 99th percentile, and a monitor looking at one step has never seen a distribution.

**"Trusted" describes the monitor, not the protocol — and the protocol name is a statement about what it omits.** `trusted_monitoring(some_untrusted_judge())` type-checks perfectly well; nothing verifies the claim in the name. What the word actually buys at the protocol level is an *assumption*: this protocol trusts its monitor and therefore does nothing to check it. `untrusted_monitoring` is a separate protocol rather than a flag precisely because dropping that assumption means adding machinery — honeypot injection, and comparing reports against known-bad inputs.

A protocol owns:

- **thresholds** — calibrated against benign score distributions, per dimension where scores are structured
- **the audit budget** — how much remains, and how it is allocated across an episode (Ctrl-Z decays it exponentially, scrutinising early steps harder)
- **aggregation** — combining reports from several monitors
- **the control actions** in the table above
- **pipeline stages** — paraphrasing, honeypot injection, each of which can be [its own nested protocol](#a-protocol-may-have-no-children)
- **its stance toward child decisions** — honour, or record and ignore

All of which is ordinary code, not framework surface — see [The runner](#the-runner).

#### Two that generate

`threshold` never calls a model. The two control protocols that ship beside it do, and they are worth showing because they exercise the parts of the surface a threshold does not: regenerating with the agent's own request, and substituting the result.

``` python
@protocol
def resample(monitors: Monitors, threshold: float, n: int = 3) -> ControlProtocol:
    async def decide(context: Context, step: AfterGenerate) -> Decision | None:
        reports = await run_monitors(monitors, context, step)
        score = reports.max_suspicion()
        if score is None or score < threshold:
            return Decision.clear()
        best_score, best_message = score, step.output.message
        for _ in range(n):
            output = await context.host.generate(
                step.input, model=step.model, tools=step.tools, config=step.config
            )
            reports = await run_monitors(monitors, context, replace(step, output=output))
            candidate = reports.max_suspicion() or 0.0
            if candidate < best_score:
                best_score, best_message = candidate, output.message
        if best_score >= threshold:
            return Decision(action="escalate", explanation="no resample cleared the threshold")
        return Decision(action="modify", modified=best_message)

    return decide
```

Each candidate's scores go through the runner, so the log holds every draw, not only the winner. Returning `escalate` when nothing clears the threshold is Ctrl-Z's incrimination signal in its simplest form, and it composes: `chain([resample(...), human()])` sends exactly the incriminated steps to a person.

``` python
@protocol
def defer_to_trusted(
    monitors: Monitors, threshold: float, trusted: str | None = None
) -> ControlProtocol:
    """`trusted` is a model name; None means the `trusted` model role."""

    async def decide(context: Context, step: AfterGenerate) -> Decision | None:
        reports = await run_monitors(monitors, context, step)
        score = reports.max_suspicion()
        if score is None or score < threshold:
            return Decision.clear()
        output = await context.host.generate(
            step.input, model=trusted or "trusted", tools=step.tools, config=step.config
        )
        return Decision(
            action="modify", modified=output.message, explanation=f"suspicion {score:.2f}"
        )

    return decide
```

This is `resample` with one draw on a different model and no candidate loop. The `trusted` model role is the natural default, so `--model-role trusted=openai/gpt-4o-mini` configures it without touching code. `trusted_editing` is the same shape again (the trusted model is given the untrusted output and told to rewrite it) and is left to an extension until someone wants it.

Three things follow for the rest of the design:

- **`AfterGenerate` carries the request.** `tools`, `tool_choice` and `config` join `input`, so a protocol regenerates with exactly what the agent was given.
- **`Host.generate` is a real generate.** Messages or a string in, `ModelOutput` out, with `model`, `tools` and `config`; `model` accepts a name or a role. Under a proxy, generating as the agent's model is a re-issued upstream request. `sentinel-deployment.md` carries the signature.
- **Protocol inference has its own usage bucket.** `resample` spends up to `n` times the agent's tokens on the agent's model. It is recorded under a `protocol` bucket in `ModelUsage`, separate from both agent and monitor usage and not charged to the agent's limits, because the protocol chose to spend it. See open question 8.

Both are `AfterGenerate`-only, and their signatures say so rather than annotating `Step`.

### A protocol may have no children {#a-protocol-may-have-no-children}

The shipped `threshold` protocol, in full:

``` python
@protocol
def threshold(
    monitors: Monitors,
    reject_at: float,
    terminate_at: float | None = None,
) -> ControlProtocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        observations = await run_monitors(monitors, context, step)
        score = observations.max_suspicion()
        if score is None:
            return None
        if terminate_at is not None and score >= terminate_at:
            return Decision.terminate(f"suspicion {score:.2f}")
        if score >= reject_at:
            return Decision.reject(f"suspicion {score:.2f}")
        return Decision.clear()

    return decide
```

It holds the constants a monitor cannot, reads its children's scores through the runner, and returns a decision. Nothing else.

And `no_curl` from [Shape](#shape), which is the same thing with the middle removed: no monitors, no runner call, a decision straight from the step. Both are protocols. **Deciding is what makes something a protocol, not having children.** An earlier draft defined a protocol as "a monitor that takes monitors", which made the combinator the essence and left rules and `human()` as a special kind of monitor — the kind that decides — with a decorator whose only job was to distinguish the two. That was the wrong seam. The seam the literature draws, and the one the report types already encode, is between observing and deciding; whether a decider consults anything is a detail of its implementation.

Where a protocol does have children it is a combinator, `[Monitor | ControlProtocol] -> ControlProtocol`, and Inspect answers that shape the same way three times over — `chain`, `multi_scorer`, `policy_approver`. `multi_scorer` is the closest analogue: it runs children in parallel, aggregates with a reducer, and returns one `Score`. The typing follows the children: `threshold` takes `Monitors` because it reads scores, `chain` and `concurrent` take `Children` because they compose decisions and record whatever monitors they are handed, and `threshold(human())` is a type error, as it should be — a person has no score.

Two consequences worth stating plainly:

- **Two `RegistryType` values, `"monitor"` and `"protocol"`.** An earlier draft argued its way to one on the grounds that a second type was a cost with no benefit. The benefit turned out to be the configuration surface: with two types, a reader of `Task(sentinel=[...])` or of a YAML file can see which entries act, and the three configuration-time warnings that existed to explain mixed lists disappear ([A bare monitor records only](#observe-only-is-the-default)).
- **The alias is `ControlProtocol`, and the decorator is `protocol`.** Bare `Protocol` collides with `typing.Protocol`, which this codebase imports constantly; a lowercase `protocol` decorator collides with nothing, exactly as `tool` and `Tool` coexist. Whether the alias should accept the collision and be `Protocol` anyway is [open](#open-questions). (`Policy` would be wrong regardless: in the control literature the *policy is the untrusted agent*, so reusing it for the thing doing the deciding would invert the term.)

Protocols nest. A budget-owning protocol can wrap a paraphrasing protocol wrapping the leaf monitors, so the [pipeline stages](#the-extension-surface) become composable pieces rather than features one monolithic protocol has to anticipate. What still needs a rule is *budget ownership* under nesting — see the [open questions](#open-questions).

### The `@protocol` decorator {#the-protocol-marker}

``` python
Monitors: TypeAlias = Mapping[str, Monitor] | Sequence[Monitor]
Protocols: TypeAlias = Mapping[str, ControlProtocol] | Sequence[ControlProtocol]
Children: TypeAlias = Mapping[str, Monitor | ControlProtocol] | Sequence[Monitor | ControlProtocol]

ControlProtocol: TypeAlias = (
    Callable[[Context, Step], Awaitable[Decision | None]]
    | Callable[[Context, BeforeGenerate], Awaitable[Decision | None]]
    | Callable[[Context, AfterGenerate], Awaitable[Decision | None]]
    | Callable[[Context, BeforeToolCall], Awaitable[Decision | None]]
    | Callable[[Context, AfterToolCall], Awaitable[Decision | None]]
)


def protocol(factory: Callable[P, ControlProtocol]) -> Callable[P, ControlProtocol]: ...
```

It is `@monitor`'s twin, typed the way `@scorer` is, and it claims two things about the factory — each a claim the framework verifies against the code rather than a second vocabulary that could disagree with it, the distinction that got `@monitor(kind=)` and `@monitor(on=)` rejected:

- **The returned callable returns `Decision | None`.** A protocol returning `Observation | None` is a monitor wearing the wrong decorator, and the checker says so before the decorator runs.
- **It registers under `"protocol"`.** Same params capture, same `Step`-or-single-stage annotation rule as a monitor.

Children are ordinary factory parameters, typed `Monitors`, `Protocols` or `Children`, and there may be none. That is what makes the nested key in [configuration](#configuration) legal: `monitors:` or `children:` under a factory is legal exactly when the factory has a parameter of that name, and a configuration error otherwise. An earlier draft required a leading positional `monitors` parameter, checked with `Concatenate`, so that the decorator could prove the factory composed. That proof is not wanted now that composing is not what a protocol is; a rule has no children to prove anything about.

What the decorator deliberately does *not* do is invoke the children or own the fan-out. A draft of this design tried that — `protocol(monitors, decide=...)` with the framework calling the runner and the author supplying only the reduction — and it was strictly less expressive than writing the body: it had to grow a `transform=` parameter just to recover paraphrasing, and it could not express a chain at all, because a chain's decision is made *between* links rather than after them. The factory still holds the children either way, so the enforcement it appeared to buy was illusory. The body of a protocol is ordinary code that calls [the runner](#the-runner).

### Static checking {#static-checking}

Most of what `@protocol` and `@monitor` verify at decoration time, mypy and pyright verify first. The repo already does this for scorers: `@scorer` is typed `Callable[P, Scorer] -> Callable[P, Scorer]`, so a factory whose inner function returns the wrong thing fails type-checking before the runtime check runs. The same technique covers both decorators, and the runtime pass reduces to reading annotations the checker already validated.

| Claim | How it is checked statically |
|------------------------|------------------------|
| a monitor returns `Observation \| None` | `@monitor` is typed `Callable[P, Monitor] -> Callable[P, Monitor]`; an `async def` returning `Decision \| None` is not assignable to any member of `Monitor` |
| a protocol returns `Decision \| None` | the same, with `ControlProtocol` |
| the inner function's second parameter is a stage type | `Callable` parameters are contravariant, so a function accepting `Step` matches the `Step` variant and one accepting `BeforeToolCall` matches that variant; an unannotated `step` matches nothing |
| the declared kind matches the body | with the return annotated `Observation \| None`, a `return Decision(...)` inside is an ordinary type error — the strongest of the four, since it checks every return statement rather than the signature |
| `threshold` takes monitors, `chain` takes children | the parameter types; `threshold(human())` is a type error |

What stays runtime-only is exactly what no type system would express: per-stage action legality (a generic `Decision[A]` was [rejected](#rejected-a-generic-parameterised-on-the-action-set) for schema reasons), the authority rule, whether a body went through the runner, and YAML configuration. Those live in [the boundary check](#the-boundary-check) and the log.

### The runner {#the-runner}

**The protocol invokes its children; the framework does not.** This is forced by [Prior art](#prior-art): paraphrasing and minification are transforms between agent output and monitor input, and honeypots are synthetic inputs injected into the monitor's stream. Neither is expressible if the framework has already called the monitors and handed over finished reports.

So the runner is not a convenience. It is where core's obligations sit, and it is the *only* sanctioned way to invoke a child. It comes in two families, one per registry type, plus a mixed form for the compositions:

``` python
async def run_monitor(
    monitor: Monitor, context: Context, step: Step, *, name: str | None = None
) -> Reported[Observation] | None:
    """Invoke one monitor if it is annotated for this stage.

    Derives the child's Context under this layer's path, records a
    SentinelEvent, applies the failure policy. Returns None if the child
    abstained or does not watch this stage.
    """


async def run_protocol(
    protocol: ControlProtocol, context: Context, step: Step, *, name: str | None = None
) -> Reported[Decision] | None:
    """The same, for one protocol."""


async def run_monitors(monitors: Monitors, context: Context, step: Step) -> Observations:
    """tg_collect over run_monitor."""


async def run_protocols(protocols: Protocols, context: Context, step: Step) -> Decisions:
    """tg_collect over run_protocol. Cancels siblings when one returns terminate."""


async def run_children(children: Children, context: Context, step: Step) -> Reports:
    """Both families in one task group. What chain() and concurrent() use."""
```

The singular forms carry the per-child obligations:

- **filter by point** — a child not annotated for this step is skipped, and the skip is indistinguishable from abstention
- **name the child** — from the mapping key if the protocol was given a `Mapping`, else the registry name; a duplicate name within one layer is an error rather than a `#2` suffix
- **derive the child's `Context`** — `Context` is already per-instance (its store is namespaced), so it carries the instance path, and the child's is built under it
- **record the report** — one `SentinelEvent` per participating child, including the ones the protocol goes on to ignore, which is load-bearing because the ignored ones are the benign distribution calibration needs
- **apply the [failure policy](#failure-semantics)** uniformly

The plural forms add the concurrent obligations: they **fan out with `tg_collect()`**, per AGENTS.md, which [Concurrency is a safety property](#concurrency-is-a-safety-property-not-just-a-latency-one) shows is a safety requirement rather than a latency one; and `run_protocols` **cancels remaining siblings when one returns `terminate`**, since nothing outranks it and the sample is ending — prompting a human about a sample that no longer exists is the concrete thing this avoids.

They return:

``` python
@dataclass(frozen=True)
class Reported(Generic[R]):
    name: str      # instance name: mapping key, or registry name
    path: str      # "attempt/internet_attempt"
    report: R


class Observations(Sequence[Reported[Observation]]):
    def max_suspicion(self) -> float | None:
        """Max over observations (per-dimension max, then max); None if nobody observed."""


class Decisions(Sequence[Reported[Decision]]):
    def strongest(self) -> Reported[Decision] | None:
        """By the precedence in Composition; None if nobody decided."""


@dataclass(frozen=True)
class Reports:
    observations: Observations
    decisions: Decisions
```

Two sequence types rather than one, because [the two halves aggregate differently](#composition) — scores combine and then threshold, decisions resolve by precedence — and because the types then say which protocols read which: `threshold` never sees a `Decision`. Identity is attached because a protocol may weight or require agreement across specific monitors, and because `path` is what the transcript and the store are keyed by. Generics are safe here in a way [they were not for `Report`](#what-a-monitor-returns): these are frozen dataclasses passed as arguments, never serialized, so no mangled name reaches `components/schemas`.

Everything else a protocol does is **ordinary Python over these plus task-scoped state** — thresholds, budget arithmetic, aggregation, deferral. That is the point rather than a gap: a protocol is meant to be [the extension surface](#the-extension-surface), and something requiring framework blessing beyond these helpers would not be one.

One thing it is not quite arbitrary code over: **per-sample state has to actually work**, which it does — the audit budget is per-episode and therefore per-sample (see [`audit` is a flag](#audit-is-a-flag-not-an-action)). Only a budget deliberately pooled across samples reaches [Per-task](#per-task), and that is a choice rather than a requirement.

### Two compositions: concurrent and ordered {#two-compositions-concurrent-and-ordered}

The reviewer group's requirements (#5423, see [below](#the-reviewer-groups-requirements-5423)) made explicit something the first draft had only half of. There are two ways to compose children, and people need both:

- **Concurrent.** Every child runs; nothing is silenced; the strongest decision wins. This is what independent guards want — two monitors that each must be satisfied — and it is the composition [Composition](#composition) describes.
- **Ordered.** Children run in sequence; the first non-`escalate` decides; later children never run. This is approval's chain, and it exists for two reasons that are both "do not invoke the next monitor unless needed": a cheap rule ahead of an expensive judge, and a human at the end who should only be asked what the machines could not answer.

The first draft treated the ordered form as "wrong for a set of observers" and stopped there. It is wrong *as the default* — that is precisely the bug #5423 reports: A approves, B would have terminated, B never ran — but it is the right shape whenever there is a person at the end of it. Both ship as protocols on the same runner.

**`chain()`** is the ordered one. It loops over the singular runners, so every link is recorded, and it hands escalations forward on the step:

``` python
@protocol
def chain(children: Children) -> ControlProtocol:
    async def run(context: Context, step: Step) -> Decision | None:
        escalations: list[Reported[Decision]] = []
        participated = False
        for name, child in named(children):
            if is_monitor(child):
                if await run_monitor(child, context, step, name=name) is not None:
                    participated = True             # recorded; falls through
                continue
            reported = await run_protocol(
                child, context, replace(step, escalations=tuple(escalations)), name=name
            )
            if reported is None:
                continue
            participated = True
            if reported.report.action == "escalate":
                escalations.append(reported)
            else:
                return reported.report
        return Decision.clear() if participated else None

    return run
```

Three properties fall out of writing it as ordinary code. A monitor in a chain is recorded and falls through, since an observation cannot be "the first decision" — ordered composition is Decision-shaped in substance. An all-escalate chain returns `continue` if anything participated, matching review's default and this document's rule; the [approval adapter](#a-protocol-layer-for-approval-too) keeps approval's fail-closed `reject` on its own path, so existing approval users see no change, and a monitor chain that wants fail-closed ends with a rejecting monitor, as approval lists end with `auto` today. And sequential dispatch stops being a violation of the independence rule, because the loop is a named, shipped protocol whose mode the transcript shows.

**`concurrent()`** is the concurrent composition, and it is also what the top of a configuration compiles to (see [Configuration](#configuration)):

``` python
@protocol
def concurrent(children: Children) -> ControlProtocol:
    async def run(context: Context, step: Step) -> Decision | None:
        reports = await run_children(children, context, step)
        strongest = reports.decisions.strongest()
        if strongest is None:
            return None                              # monitors only: recorded, nothing acts
        if strongest.report.action == "modify" and len(reports.decisions) > 1:
            return Decision.reject(
                f"{strongest.name} modified the call but other protocols approved the original"
            )
        return strongest.report

    return run
```

That settles the `modify` question this document previously left open: concurrent children cannot see each other's rewrites, so a `modify` when more than one child decided is a rejection naming the modifier. Re-approving modified arguments is more machinery than the decision is worth for now, and #5423 reached the same answer independently. The name pairs with `chain`: both say how the children run and leave the decision rule to the docs. `strictest` and `all_of` were the alternatives; the first named only the recommendation half of the reduction (observations aggregate by max, not strictness) and the second named what the configuration means rather than its shape.

**Concurrent is the default, and ordered is one explicit word.** The argument for making ordered the default is that many people will want a chain, which is true. The argument against is that ordered-by-default silences monitors, and silencing is a safety failure while concurrency's cost is latency and tokens. A default should fail safe, and changing one later is a silent semantic change for everyone. So a list with a protocol in it is `concurrent`, and a chain is `chain(...)`. The mistake the wrong default would produce most often — a `human()` in a concurrent group, prompting on every call — is caught at configuration time with a message that names `chain()`.

### The boundary check {#the-boundary-check}

When any layer returns, the dispatcher validates the decision before anything acts on it. This is where the rules that no type can express are enforced, and where the "invalid state" rule from AGENTS.md is applied: each is a bug in a protocol, not agent input, so each raises.

- **The action is legal for the stage** — no `reject` at `AfterToolCall`, per [One vocabulary across stages](#one-vocabulary-across-stages).
- **`modified` is set iff `action == "modify"`**, and carries the right type for the stage.
- **The decision is not weaker than any [authoritative](#authoritative-reports) decision from a child of this layer.** A protocol that turned a human's `reject` into `continue` has a bug. The check reads the layer's own child decisions, which the runner recorded, so it needs no cooperation from the protocol.

The check runs per layer, so a nested configuration is validated at every level rather than only at the top.

### Humans in the loop

#5423's chains end in a person, and the first draft had nowhere to put one: humans were `@approver`s, and approvers lived in `Task(approval=)`. A `human()` protocol closes that. It has no children, is `BeforeToolCall` (and in principle any stage the human surfaces can render), prompts through the existing human approval surfaces, renders `step.escalations` above the call so the person sees who asked and why, and returns with `authoritative=True`. Human surfaces already queue requests, so two chains that both end in a person prompt one after the other and the stricter answer wins.

It is the one protocol whose placement the framework second-guesses: a `human()` inside a concurrent group is almost never intended, and the config-time check says so and suggests `chain()`.

### What the split does not enforce {#what-the-collapse-costs}

Two registry types make the contract mostly explicit, and the residue is small:

- The structural claims — returns a decision, annotates a stage, takes typed children — are [statically checked](#static-checking).
- Never weakening an authoritative decision is [checked at the boundary](#the-boundary-check).
- **Going through the runner is not preventable.** The factory holds the children and can call them as plain callables, bypassing naming, recording and the concurrency guarantee. What makes this tolerable is that a child invoked any other way produces no event: a protocol that decided with no child reports in the transcript is visible in the log, and a config-time check can flag it.
- "No `escalate` at the outermost layer" is not expressible in the type. Harmless in practice, since [all-escalate is already defined as `continue`](#composition).

That is a genuine but narrow gap, and it is the same gap under one registry type or two: nothing about the types makes calling a child as a plain callable detectable except through the log.

### The extension surface {#the-extension-surface}

Protocols being ordinary registered factories is what makes them the natural extension point — a third party ships one the same way they ship a scorer or a tool, with no core change to negotiate.

That matters for scope discipline. AGENTS.md's rule — new functionality defaults to an extension, not core — applies directly: honeypots, paraphrasing, resampling and collusion-resistant untrusted monitoring carry real conceptual weight and serve a small audience. Design the extension point, ship the protocols people actually use, and let the research-grade machinery live outside core until there is demand.

The `run_monitors()` seam is what makes that credible rather than aspirational. An extension implementing honeypotting does not need a framework hook: it wraps the call, injecting synthetic known-bad steps into the stream its monitors see and comparing the reports it gets back. Paraphrasing is the same seam, transforming `step` before the call. Because protocols nest, either can be dropped between a budget-owning protocol and its leaf monitors without that protocol knowing they exist.

## Registration

`@monitor` and `@protocol` each decorate a factory that returns the function, exactly as `@approver`, `@scorer`, `@solver` and `@tool` do. Every registry decorator in Inspect is factory-based, and a dual form here alone would be the odd one out — worse, it would make the use site inconsistent, since a bare rule would be listed as `no_curl` while a configured monitor is listed as `suspicion_monitor("openai/gpt-4o-mini")`. The zero-config case pays one nested `def` for that uniformity:

``` python
@monitor
def suspicion_monitor(model: str | Model | None = None, dimensions: list[str] | None = None) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        ...

    return check
```

`Monitor` is a type alias for the returned callable rather than a base class — one of four, since the payload varies by stage:

``` python
Monitor: TypeAlias = (
    Callable[[Context, BeforeGenerate], Awaitable[Observation | None]]
    | Callable[[Context, AfterGenerate], Awaitable[Observation | None]]
    | Callable[[Context, BeforeToolCall], Awaitable[Observation | None]]
    | Callable[[Context, AfterToolCall], Awaitable[Observation | None]]
)
```

A protocol's alias, `ControlProtocol`, has the same four shapes returning `Decision | None` plus a fifth over `Step` — the widest union, and therefore a registration at all four points, which is what a composition like `chain` annotates. See [The `@protocol` decorator](#the-protocol-marker).

Registry params come from the factory signature, so `registry_create("monitor", "suspicion_monitor", model="openai/gpt-4o-mini")` and `registry_create("protocol", "threshold", reject_at=0.8)` and the params recorded in the log work as they do for every other registry type. Note what is *not* a parameter on a monitor: a threshold. A monitor factory taking `threshold=0.8` has nothing to do with it, since the monitor cannot act — the constant belongs on a protocol, which is the anti-pattern [Monitor or protocol?](#monitor-or-protocol) describes, wearing configuration as a disguise. The new `RegistryType` values are `"monitor"` and `"protocol"`.

#### Instance names

A registry name identifies a factory, not a configured instance, and two instances of one factory in a configuration — two `chain`s, two `suspicion_monitor`s with different models — need telling apart in the log and in the store. So every configured monitor or protocol has an **instance name**: the key, when it was given in a `Mapping`; the registry name otherwise. Names are unique within a layer, and a duplicate is a configuration error rather than an invented suffix. Nesting composes them into a **path**, `attempt/internet_attempt`, which is what `SentinelEvent` records and what `context.store_as()` namespaces by. This is #5423's dict-of-named-chains, generalised to every layer rather than only the top.

#### Bare names inside the package, prefixed names outside it

`Context`, `Report`, `Action` and `Host` carry no `Monitor` prefix. The package name already supplies it — `MonitorContext` stutters as `monitor.MonitorContext` — and this is the local convention rather than a departure from it: `inspect_scout` exports `Result`, `Error` and `Reference` unprefixed from its scanner module, and Inspect's own public vocabulary is `Score`, `Target`, `Store`, `Approval`, `Task`. The payload types were already bare, so the prefixed names were the inconsistent ones.

The line is namespace, not importance: **a type living in the sentinel package goes bare; a type living in a shared namespace keeps the prefix.** Hence `SentinelEvent` stays `SentinelEvent` — it belongs to `inspect_ai.event` beside `ToolEvent`, `ModelEvent` and `ApprovalEvent`, where the prefix is the discriminator and a bare `Event` is already taken.

A user with their own `Context` is served by `import as`, which is the ordinary cost of short names and the reason the rule stops at the package boundary.

### The stage comes from the annotation {#the-stage-comes-from-the-annotation}

There is no `on=` or `stage=` argument. The type of the second parameter is the declaration, and it is required.

This is the `@tool` contract, not a new idea: `tool/_tool_info.py:118` calls `get_type_hints(func)` and builds the entire `ToolInfo` — name, description, parameter schema — from annotations, with no override and no second spelling. Requiring the payload type is the same move, and it is consistent with the house rule that every function carries annotations.

A string alternative (`@monitor(on="tool_call")`) was rejected for the reason any parallel vocabulary is: it can disagree with the annotation, and then something has to adjudicate. A type-valued one (`on=BeforeToolCall`) merely restates what is already there.

Deduction runs when the factory is called — that is, at configuration time, which is when the decorator first holds the returned callable. `@scorer` already works this way: `scorer_wrapper` invokes `scorer_type(*args, **kwargs)` and then inspects the result (checking `is_callable_coroutine`) before tagging it. So this needs no new machinery, and the error arrives when the monitor is configured rather than at first dispatch.

**The one failure mode is real and already documented in this tree.** `_control/eval_state.py:40-45` spells it out: under PEP 563 (`from __future__ import annotations`) every annotation is a string, and `get_type_hints()` fails outside a type-checking context. Our audience — people minimizing import weight — is precisely who would import `BeforeToolCall` under `TYPE_CHECKING`. The mitigation is not an override to escape to, it is an error that names the fix:

> `suspicion_monitor`: could not resolve the annotation `BeforeToolCall` on parameter `step`. Import it at runtime rather than under `TYPE_CHECKING`.

Open: whether a union annotation (`BeforeToolCall | AfterToolCall`) registers the function at both points, or is an error.

### The kind is the decorator, and the return annotation is checked against it {#the-kind-comes-from-the-return-annotation}

The parameter annotation says *where* a function runs; the decorator says *what it emits*, and the return annotation must agree:

``` python
@monitor  ...  async def judge(context: Context, step: BeforeToolCall) -> Observation | None: ...
@protocol ...  async def no_curl(context: Context, step: BeforeToolCall) -> Decision | None: ...
```

An earlier draft had one decorator and read the kind off the return annotation, so that the same `@monitor` could produce a scorer or a decider. That was rejected in favour of two decorators, and the reasoning that once argued *for* reading annotations still holds here — a `@monitor(kind="scorer")` argument was rejected because a second vocabulary can contradict what the function returns. Two decorators are not a second vocabulary. The decorator is the registry type, and mypy checks the body against it: a `return Decision(...)` inside a function annotated `-> Observation | None` is an ordinary type error, and a factory returning that function does not satisfy `Callable[P, Monitor]`.

Inferring the kind from which fields a report happens to set was also rejected, and this is the sharper argument. It makes the kind a property of a *report* rather than of a *function*, so the same function could score on one call and decide on the next, and nothing could be said at configuration time. A declared kind buys two things:

- **The config-time check gets specific.** The one [remaining warning](#observe-only-is-the-default) can name the monitor and say what to wrap it in, because the configuration knows which entries are monitors before anything runs.
- **Emitting both is unrepresentable.** The old prose rule — a monitor doing both "is taking policy into its own hands" — was discouragement. Two registry types make it a type error, and this is the bigger win: a function that emits a score *and* an action has already thresholded internally, so the protocol above it cannot tell which half to trust and the calibration never happens.

### One function, one point {#one-function-one-point}

An earlier draft made `Monitor` a class with four overridable methods. Dropping it was the right call, and the deciding argument is empirical rather than aesthetic: **monitors watching more than one point are rare.**

- All four motivating cases in [Goal](#goal) are single-point.
- The obvious two-point candidate — correlate a call with its result — collapses to one `AfterToolCall`, because that payload already carries `call`, `result`, `output`, `view` and `history`.
- Both shipped designs surveyed in [Prior art](#prior-art) agree: OpenAI's Agents SDK registers guardrails individually, and Claude Code hooks are per-event with no grouping construct at all.

So there is no grouping mechanism, and deliberately so. A concern spanning two points is two monitors, listed twice. (A protocol annotating `Step` is one function registered at four points, not a grouping of four functions — it sees whichever step arrives and decides about it.) Two alternatives were considered and rejected:

- **A name convention** (`suspicion_on_tool_call`, selected as `suspicion_*`) encodes in the identifier what the annotation already says, so the two can disagree and a consistency check has to adjudicate. Nothing in Inspect's registry parses names for structure today; names are explicit, never meaningful.
- **Glob selection over registry names** solves a problem that only exists if grouping does. Selection is an explicit list, like scorers. If listing gets tedious a package exports one — `monitors=acme.all_monitors()` — which needs no framework concept.

### What the function shape buys

Beyond removing a base class from the surface:

- **Each monitor's stage and portability are legible per function**, not per class. A class with one portable method and one unportable one is an all-or-nothing verdict; a function is its own verdict. `sentinel-deployment.md` builds on this.
- **Monitors are enumerable without importing anything.** `_util/decorator.py::parse_decorators` walks top-level `FunctionDef` nodes for a named decorator using nothing but `ast`, which is what a deployment bundler needs to find the monitors in a file and compute its import closure. That works *only* because monitors are top-level functions — a class body is an `ast.ClassDef` with its methods nested inside, invisible to that walk.

One thing it does **not** buy, which is worth stating rather than implying: a closure captures state as readily as `self` does, and it is captured once per configuration and shared across every sample either way. `nonlocal count` is more friction than `self.count = 0`, and a variable declared beside the `async def` reads as shared in a way an attribute does not — but the hazard is the same one, and [State](#state) still has to argue it rather than the shape having settled it.

### Where the decorator lives

A monitor author should be able to depend on the wire types and nothing else. That works without a bridge: `_util/registry.py` is already a leaf — its runtime imports are stdlib plus pydantic plus four small `_util` modules, and every reference to `Task`, `Agent`, `Approver`, `Solver`, `Tool` and the rest is `TYPE_CHECKING`-only, present for `registry_create`'s overloads. `registry_tag` is two `setattr` calls and `extract_named_params` is stdlib `inspect.signature().bind()`.

So the registry primitives move into `inspect_core` alongside the types (`inspect-core.md`), and `@monitor` defined there registers for real — no marker attributes, no deferred drain, no import-ordering hazard. Module identity gives a shared singleton registry: `inspect_ai` imports the same module object, so there is one dict rather than two to keep coherent.

Two details. `ensure_entry_points()`, called from `registry.py`, loads plugin entry points and can therefore import arbitrary third-party packages at runtime — it has to be injectable or a no-op in the leaf. And because `@monitor` decorates a factory, parameter capture is the ordinary `registry_tag(factory, monitor, info, *args, **kwargs)` call that `@scorer` already makes; route it through the existing `extract_named_params` rather than reimplementing it, since that carries the VAR_KEYWORD flattening from #4374 which makes capture-then-replay idempotent.

## State {#state}

Two scopes, per-sample and per-task, each reachable either from an argument on the callback payload or from a global function bound to the current context.

### Per-sample

Per-sample state is the sample `Store`, which already exists and is already `ContextVar`-bound. A monitor runs inside the sample's context, so `store_as(MyState)` works today with no new machinery. What a monitor adds is automatic namespacing, so two configured instances of the same monitor don't collide, and the monitor doesn't have to know its own instance name:

``` python
class TrajectoryState(StoreModel):
    score: float = Field(default=0.0)
    flags: list[str] = Field(default_factory=list)


async def check(context: Context, step: BeforeToolCall) -> Observation | None:
    state = context.store_as(TrajectoryState)
```

This is where the shape argument from [What the function shape buys](#what-the-function-shape-buys) has to be cashed out rather than assumed. A factory closure is created once per configuration and shared by every sample, so anything captured in it is *task*-scoped whether the author meant it or not. `context.store_as()` is how per-sample state is spelled, and the factory docstring has to say so — the shape makes the sharing more visible, it does not prevent it.

Backing per-sample state with the sample `Store` gets three things for free: it is recorded to the transcript as `StoreEvent`s, so the monitor's reasoning is in the log; it survives checkpoint and resume; and `store_from_events_as()` can reconstruct it from a finished log for analysis.

#### One access path, not two {#one-access-path-not-two}

There is no `monitor_store_as()` global. Ambient accessors exist in Inspect for call boundaries you do not control — a tool invoked by the model, a scorer invoked by the framework. A monitor controls every one of its own helper call sites, so a helper can simply take what it needs as a parameter.

The one case that looks like it needs a global — a scorer reading what a monitor accumulated — does not. The monitor's per-sample state *is* in the sample store, namespaced by the monitor's [instance path](#instance-names), so a scorer holding a `TaskState` reads it with the existing `store_as(TrajectoryState, instance="attempt/internet_attempt")`. The only thing a monitor-specific global would add is not having to name the instance, which is exactly what makes it ambient and unportable.

`context.store_as()` mirrors the familiar global `store_as()` deliberately. Bare `store()` is not available and should not be: it is taken by `inspect_ai.util.store()`, and a monitor's store is a *namespaced view* of the sample store rather than the same object.

Injecting the store is also what keeps `StoreModel` usable outside an eval. `StoreModel` declares `store: Store = Field(exclude=True, default_factory=store)` — it falls back to the global `ContextVar`, which is precisely the ambient binding a proxy cannot provide. `context.store_as()` passes the store explicitly, so that path is never taken; a `monitor_store_as()` global would have made monitor state quietly unportable.

#### No global for `host` {#no-global-for-host}

Neither is there a `monitor_host()`, and here the argument above is reinforced by a second one. The store case rests only on helpers being able to take a parameter; the host case rests on that **and** on ambient authority being a thing to avoid on its own terms. The value of `context.host` is that it is the only route out of a monitor — everything a monitor can do to the outside world is enumerable from one Protocol — and any global reopens that.

The leak that already exists is `get_model()`. A monitor can call it and bypass `context.host` entirely, so the `portable=True` check has to ban it. There is in-process value in routing through the host too, not only portability: `context.host.generate()` can default to `role="monitor"` and let the host record monitor inference distinctly from the agent's, neither of which a direct `get_model()` gets.


### Per-task

Per-task state has no mechanism today and is the harder half.

``` python
class RunTotals(StoreModel):
    terminated: int = Field(default=0)


state = context.store_as(RunTotals, scope="task")                         # argument form

```

Three things are unresolved:

**Concurrency.** Samples share one event loop and interleave at every `await`. A single `Store` operation is atomic and no lock is warranted (per AGENTS.md, Inspect runs on one event loop thread), but a read-modify-write *spanning an `await`* is a real race:

``` python
count = state.terminated          # read
await classify(step)              # another sample runs here
state.terminated = count + 1      # write clobbers
```

This is less alarming than it looks, because the canonical critical section is naturally await-free. A protocol's decision — compare score to threshold, check remaining budget, decrement — is pure arithmetic; the `await` happened earlier, when `run_monitors` ran. An await-free read-modify-write is atomic under the single-loop-thread invariant, so it needs no lock and no helper.

So the rule is a documented "don't `await` between reading and writing shared state", with the reason attached rather than asserted. A helper that makes the critical section syntactically obvious would be a nicety, not a fix.

**Persistence.** In-memory only is the simple answer, and it means task state starts empty on `eval_retry` and on eval-set resume — so a monitor that gates on a cross-sample total behaves differently on a resumed run than on a fresh one.

For a budget that asymmetry has a direction worth naming: a reset budget means *more* auditing than intended, not less. Erring toward more human review is the safe side of that error, which makes in-memory defensible for v1 on a principle rather than on convenience. A monitor that gates the other way — "terminate once 3 samples have been flagged" — resets toward *less* intervention, and that one genuinely needs durability. Writing it somewhere durable means picking a home (`EvalSpec.metadata`? a new `EvalLog` field? a task-level event stream, which doesn't exist) and deciding when it's flushed.

**Scope.** "Task" is right for cross-sample aggregation within one task. It is the wrong scope for anything that wants to span an `eval()` over several tasks, and for `eval_set`. Whether there's a third scope, or whether the task scope is really a run scope, is open.

## Configuration

Mirroring approval:

``` python
Task(sentinel=...)
eval(monitor=...)
inspect eval task.py --sentinel sentinel.yaml
```

`Task(sentinel=)` accepts one monitor or protocol, a list, or a mapping of names to them. Every top-level configuration compiles to a protocol, so there is always a layer that owns the combined decision and emits the summary event #5423 asked for — and which protocol depends only on what was given:

| `Task(sentinel=)` given | Compiles to |
|------------------------|------------------------|
| a monitor, or a list or mapping of monitors only | `observe(...)` — recorded, never acted on |
| a protocol, or any list or mapping containing one | `concurrent(...)` — protocols vote, monitors are recorded |

A single protocol is `concurrent` of one, which emits no event of its own, so the single-rule log is exactly what a lone approver's is today.

``` python
Task(sentinel=no_curl())                                    # a rule; acts
Task(sentinel=[no_curl(), no_rm_rf()])                      # two rules; concurrent
Task(sentinel=suspicion_monitor())                          # a monitor; records only
Task(sentinel=threshold(suspicion_monitor(), reject_at=0.8))
Task(sentinel={
    "attempt": chain([internet_attempt(), human()]),   # a rule that escalates; the human takes its escalations
    "escape": sandbox_escape(),                          # a rule; runs on every call regardless
})
```

The last form is #5423's example, and the mapping keys are the [instance names](#instance-names) that reach the log as `attempt/internet_attempt`, `attempt/human`, `escape`. `internet_attempt` is a rule that returns `Decision.escalate(...)` when it suspects an attempt, so the person sees only those; a monitor in its place would be recorded and fall through, since an observation is not a decision for the chain to stop on.

The flat case in YAML is a list, like approval; registry lookup searches both types:

``` yaml
sentinel:
  - name: no_curl
  - name: no_rm_rf
    tools: ["bash", "python"]
```

Named chains are a mapping, and a protocol with children nests them under the key that names its parameter:

``` yaml
sentinel:
  attempt:
    name: chain
    children:
      - name: internet_attempt
      - name: human
  escape:
    name: sandbox_escape
```

``` yaml
sentinel:
  - name: threshold
    params:
      reject_at: 0.8
    monitors:
      - name: suspicion_monitor
        params:
          model: openai/gpt-4o-mini
```

The nested key is the factory's parameter name — `monitors:` for the protocols that read scores, `children:` for the two compositions — and it is legal exactly when the factory has that parameter. The top-level key is `sentinel:`, so it cannot be confused with the nested `monitors:` (an earlier draft used `monitors:` for both). `monitors:` under a rule, or under a monitor, is a configuration error, and the schema must not let it parse silently. Nesting is the shape rather than a cost: `Task(solver=chain(...))` already has it in Python, approval's config already nests policies, and a tree is what permits [nested pipeline stages](#the-extension-surface), which a flat schema could not express at all.

`tools` is a wart. It scopes the tool stages the way `ApprovalPolicy` does, but a `BeforeGenerate` monitor is not tool-scoped and would fire regardless — so the key means "which tools this applies to, if it watches a tool point at all", not "when this monitor runs". Alternatives: a separate `stages:` key, or no globs at all (the monitor filters internally on `step.call.function`, which it can already do and which is more honest about the fact that a monitor is not a per-tool policy).

## Failure semantics {#failure-semantics}

**A protocol that raises fails loud. A monitor that raises fails loud unless nothing was consuming its report.**

The precedent is unanimous once you look at the code rather than the docs. Neither `apply_tool_approval` nor review's `_apply.py` wraps the call itself — each has exactly one `try/except`, and it is around the *viewer*, falling back to default rendering. An approver or reviewer that raises propagates and ends the sample. Only `Hooks` swallows and warns, and `Hooks` is process-global, observational, and outside any single eval's control.

The obvious objection is flakiness: LLM monitors 429 and time out, and an eval that dies because a monitor's model hiccuped is a bad trade for a safety mechanism most people run under `observe()`. That objection is weaker than it looks, because **the transients are already absorbed below**. `GenerateConfig.max_retries` and `timeout` retry model calls before anything reaches the monitor boundary, so an exception arriving here has survived the retry policy — it is a persistent outage or a bug, not a blip. Neither should be swallowed.

The exception is the case the configuration makes visible:

| Configuration | On exception |
|------------------------|------------------------|
| a protocol, at any depth | **propagate**; ending the sample beats silently losing the protection |
| a monitor under a protocol that reads it — `threshold`, `resample` | **propagate**, for the same reason |
| a monitor under `observe()`, or bare | **warn and continue**; killing a sample over a report that was going nowhere is absurd |

That is the "safety mechanism with no consumer" rule from [A bare monitor records only](#observe-only-is-the-default), applied to failures instead of to configurations, and it needs no new machinery — the same config-time analysis answers both.

The escape hatch is per-function and declared, following `portable=False`: `@monitor(fail="open")` and `@protocol(fail="open")` make tolerating a failure a visible choice that appears in code review and the registry, rather than something a function gets by default for being flaky. Failing open silently is the one behavior with no configuration that produces it.

## Composition {#composition}

Composition is the protocol's job: it collects reports from every configured child and produces one outcome. This section describes the **concurrent** composition, which is the default and what `concurrent()` implements; the ordered alternative, `chain()`, is in [Two compositions](#two-compositions-concurrent-and-ordered). Approval's ordered chain — first non-`escalate` decides, later approvers never see the call — is right for an authorisation chain ending in a person and wrong as the default for a set of observers.

- **Observation is unconditional.** Every child configured for a point runs at it, whether or not another has already formed a view.
- **Every report is recorded**, including the ones that lost.
- **Reports combine in two halves**, one per kind.

**Aggregating suspicion.** `Observation`s from several monitors have to combine before thresholding. Max is the obvious default; per-dimension max is the right shape when scores are structured, since dimensions are meant to be independent (see [Prior art](#prior-art)). Weighted combinations and requiring agreement across monitors are protocol policy, not framework behavior.

**Aggregating decisions.** Across `Decision`s, the strongest wins: `terminate` \> `reject` \> `modify` \> `continue`. `escalate` means "I decline to decide", and all-escalate is `continue`. One `Action` ordering covers all four stages, so this is a single comparison function rather than one per stage — it is `Decisions.strongest()`. Claude Code hooks land the same way — all hooks run in parallel, any `deny` blocks. `terminate` additionally cancels siblings still running, since nothing can outrank it.

**Authoritative decisions are a floor**, not a vote: a protocol may combine advisory decisions however it likes, but its own return may not be weaker than an [authoritative](#authoritative-reports) child's, and the [boundary check](#the-boundary-check) enforces that.

Then the protocol reconciles the two halves with its thresholds and budget, subject to [child decisions being advisory](#child-decisions-are-advisory).

### Concurrency is a safety property, not just a latency one

Three LLM monitors in sequence triple the added latency at every step, which argues for `tg_collect()` (not `asyncio.gather`, per AGENTS.md). TraceGuard gives a stronger reason: **independence is the point**. Its 95%-versus-0% result against a colluding monitor comes from fragmenting evaluation so no single model sees the whole assessment, which requires monitors that cannot observe each other's conclusions.

So concurrent dispatch is the default, and the cost is that `modify` becomes incoherent — a concurrent child cannot see another's rewrite. Settled in `concurrent()`: a `modify` is honoured only when it was the only decision; when more than one child decided, it becomes a `reject` naming the modifier. Last-wins in configuration order and "two is an error" were the alternatives; the rejection is chosen because the other children approved the *original* arguments and nothing has approved the modified ones. A chain has no such problem, since only one link decides.

### A second axis: concurrent with the *agent*

Separately from monitors running concurrently with each other, a monitor can run concurrently with the agent rather than blocking it — the OpenAI Agents SDK's `run_in_parallel`. Blocking costs latency; running in parallel means the agent may consume tokens, or take a step, before a violation is caught.

This is a real knob and it belongs on the protocol, not the monitor: whether late detection is acceptable is a deployment judgement. It is a different axis from `concurrent()`, which is about children running concurrently with *each other*; to keep the two apart the knob should be named for what it withholds, `blocking=True`, rather than reuse the word.

## Transcript

``` python
class SentinelEvent(BaseEvent):
    event: Literal["sentinel"] = "sentinel"
    name: str
    """Registry name of the factory: a monitor or a protocol."""
    path: str
    """Instance path, e.g. "attempt/internet_attempt". Unique within a sample step."""
    step_id: str
    """The step examined: the triggering message id (BeforeGenerate), the assistant
    message id (AfterGenerate), or the tool call id (tool stages). See
    sentinel-development.md, "Step ids"."""
    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    kind: Literal["observation", "decision"]
    """Agrees with the registry type of `monitor` by construction."""
    suspicion: Suspicion | None
    decision: Action | None
    audit: bool
    authoritative: bool
    outcome: Action | None
    explanation: str | None
    metadata: dict[str, Any] | None
```

`decision` versus `outcome` is the layering made legible in the log: what this layer decided, and what the layer above did with it. Without both, a reader cannot tell an overruled decision from one that was never made — which is exactly what a reader of a nested configuration needs to see.

`step_id` is what lets a report be matched to a label. It is recorded live, from ids that exist before the monitor runs, so a validation set built against replayed steps also matches the events an eval recorded — the two scan modes in `sentinel-development.md` share it.

`path` is #5423's `chain` field, generalised. That proposal tagged each `ApprovalEvent` with the name of the chain it belonged to; with arbitrary nesting a single parent name is not enough, and a path names the layer at every depth. `monitor` and `path` are both kept because a reader wants both questions answered: which code ran, and which configured instance it was.

A protocol is recorded exactly as a monitor is, so a nested configuration emits **one `SentinelEvent` per layer**, and that is what makes the layering readable without any further field:

```
name="internet_attempt",  path="attempt/internet_attempt",  kind="decision",  decision="escalate"
name="human",             path="attempt/human",             kind="decision",  decision="reject",  authoritative=True
name="chain",             path="attempt",                   kind="decision",  decision="reject"
name="sandbox_escape",    path="escape",                    kind="decision",  decision="continue"
name="concurrent",        path="",                          kind="decision",  decision="reject"
```

The last line is the summary event #5423 wanted: the top-level `concurrent` records the combined decision, and its explanation lists each child's. It is emitted only when more than one child participated, so a configuration with a single rule logs one event per step, as approval does today.

An earlier draft added a `strategy: str` here and on `Decision`, to record whether a `modify` came from a deferral, a resample or a trusted edit. It was removed: **the layer's identity already is the strategy.** A protocol named `defer_to_trusted` returning `modify` has said what it did, and the aggregate query that justified the field — how often did this protocol defer — is `monitor == "defer_to_trusted" and decision == "modify"`. Worse, on `Decision` it was a field every rule carried and never set.

The residual case is a protocol that genuinely takes several different actions — Ctrl-Z choosing between deferral and audit on two thresholds over one score, where `monitor` does not disambiguate. Two answers in order of preference: compose it, which [nesting permits](#a-protocol-may-have-no-children), or put it in `metadata`, which already exists and needs no new contract on a serialized type.

`kind` and `stage` are both fine on an event, which is a record, in a way they are not on a protocol, which is a contract. The event stays one flat type across both kinds and all four stages — it is what the renderer, the dataframe and the log schema read, and splitting it would push a union into `generated.ts` for no reader's benefit.

`decision` and `outcome` are typed rather than stringly typed only because the four stages share `Action`. With per-stage vocabularies the field would have to be a union of three Literals correlated with `stage`, which neither the JSON schema nor the generated TypeScript can express as a correlation — so consumers would get `string`.

The event should be emitted for observations as well as decisions. A monitor that scores every step under a protocol that intervenes twice in a hundred samples is the common case, and the ninety-eight quiet steps are the interesting data — they are also the benign distribution a protocol's thresholds are calibrated against, so recording them is load-bearing rather than merely nice.

Open: whether `SentinelEvent` replaces `ApprovalEvent`/`ReviewEvent` when the report came from a monitor, or sits alongside them (two events for one outcome), or whether those events gain a `monitor` field.

## Inference, budget, and injection {#inference-budget-and-injection}

- **Budget.** Monitor inference must not be charged to the agent's limits, the same exemption approvers get today (`suspend_token_limit()`, `suspend_turn_limit()` in `approval/_apply.py`). A monitor that terminates a sample for exceeding a token limit its own inference consumed is a trap worth closing up front.
- **Model role.** `get_model(role="monitor")` is the natural default, and `"monitor"` is already the example role name in `docs/models.qmd`. Monitor usage should be separable from agent usage in `ModelUsage`.
- **Injection.** A monitor reads model completions, tool arguments, and tool output, all of which are agent-controlled text. `docs/control-channel.qmd` already makes this point for monitoring agents reading the control channel; it applies with more force here, because this monitor's output decides whether the sample stops. Worth a docs section, and the framework should structurally help rather than only warn: [Views](#views) proposes a shared rendering path whose default output is a delimited, clearly-untrusted evidence envelope.

## Views: what a monitor sees, and how it is rendered {#views}

A step payload says what *exists* at a point in the loop. A monitor author has two further questions the payload does not answer: which of those surfaces will actually be there in the deployment this monitor is headed for, and how to turn them into a prompt without re-deriving the briefing/evidence boundary by hand every time. Today the first is scattered across the deployment sections and the second is left entirely to the author, so every LLM monitor concatenates context and history its own way, and most will get the envelope wrong.

A **view** is the answer to both, and it is not a type. It is a documented map of the surfaces and a family of rendering helpers — `messages_as_str` and its relatives — that turn any subset of them into prompt text with the boundary intact. Scout's `messages_as_str`, `MessagesPreprocessor` and `message_numbering` are the beginnings of this family; they already depend on nothing but `ChatMessage` and `Content`, and the design here is mostly about moving them down a level and filling in the pieces a monitor needs that a scanner does not.

Status: sketch, like the rest of this document. The Python is illustrative.

### The surfaces

What a monitor can be shown, where each thing comes from, and where it is available. "Eval-only" surfaces exist because Inspect executed the tool or registered the tool definition; nothing on the wire carries them.

| Surface | Lives in | Eval | Proxy / bridged | Replay | Trust |
|---|---|---|---|---|---|
| Briefing: `task_description`, `sample_description`, `input`, `metadata` | `context` | yes | operator-supplied | from transcript info | instruction |
| The subject: the call, the assistant message, or the request | `step.call` / `step.output` / `step.input` | yes | yes | yes | evidence |
| Tool result as the model sees it | `step.result` | yes | next request only (lossy) | yes; exact from `ToolEvent` | evidence |
| Untruncated tool output | `step.output` | yes | **no** | **no** | evidence |
| Tool call view (`ToolCallView`) | `step.view` | yes | **no** | from events only | evidence |
| Conversation history | `step.history` / `step.input` | yes | yes (the request carries it) | yes | evidence |
| Reasoning (`ContentReasoning`) | inside assistant messages | provider-dependent: full, summary, or redacted | whatever the wire carries | as logged | evidence |
| System prompt | first message of history | yes | yes | yes | **see below** |
| Tool definitions, generate config | `step.tools`, `step.config` | yes | yes | from events only | evidence |
| Media (images, audio, documents) | content parts | yes | yes | yes | evidence |
| Prior escalations | `step.escalations` | yes | yes | recorded | prior verdicts |
| Expected answer | `context.target` | yes | **never** | yes | instruction |
| Own accumulated state | `context.store` | yes | keyed store | per-transcript | own |

Two rows deserve a note.

**The system prompt changes trust class with the deployment.** In an eval it is author-written and could sit with the briefing. Under a proxy it arrives in the request body from the agent's scaffold, which is the thing being monitored. The helpers therefore treat the system prompt as evidence everywhere and exclude it by default — Scout's `exclude_system=True` is the right default for the same reason — and the briefing, which the operator supplied out of band, stays the only instruction-class input.

**Reasoning fidelity is not the monitor's to choose.** A monitor can render reasoning, but a provider may only return a summary or a redacted block, and a proxy only sees what the wire carries. The helpers render whatever is there — `<thinking>`, `<thinking_summary>`, `<thinking_redacted/>` — so the prompt says which it was. This settles [open question 9](#open-questions): reasoning is visible by default, at whatever fidelity exists, and a monitor that wants to score actions without it excludes it in the preprocessor. A protocol that wants to withhold it from an untrusted child transforms `step` before the call, as it would for paraphrasing.

Things a monitor never sees at any view, so that nobody designs around them: the sandbox itself (only what came back through a tool), other samples, sibling monitors' reports at the same step (independence is a [safety property](#concurrency-is-a-safety-property-not-just-a-latency-one)), the protocol's thresholds and remaining budget, and whether its own explanation was shown to anyone.

### The helpers

Lowest level first. The first three exist in Scout today and move down unchanged; the rest are new.

**`messages_as_str(messages, *, preprocessor=None, format="text")`** and **`message_as_str`.** Scout's message rendering: role labels, tool calls with arguments, tool results with errors, `<thinking>` blocks at whatever fidelity was returned, and `<image/>`-style placeholders for media. `MessagesPreprocessor` carries the exclusions (`exclude_system`, `exclude_reasoning`, `exclude_tool_usage`) and a free-form `transform`. These depend only on `ChatMessage` and `Content`, so they belong in `inspect_sentinel`, with Scout re-exporting them. The `Transcript` overload and `Reference` extraction stay in Scout. Inspect's own `analysis/_dataframe/extract.py::messages_as_str` is a third copy today and should consolidate onto the same one.

**`message_numbering(preprocessor=None)`.** Scout's `[M1]`-style numbering with a paired `extract_refs`. `sentinel-development.md` already assumes an LLM monitor uses it so that citations in an explanation resolve to messages for free; making it available to monitors is what makes that true.

**Windowing helpers over `step.history`.** History is all-or-nothing on the payload, and [incremental monitoring](#deployment-beyond-the-eval-process) wants less than all of it. Three small functions, each returning a `list[ChatMessage]` that feeds `messages_as_str`:

``` python
def last_turn(history: list[ChatMessage]) -> list[ChatMessage]:
    """Messages since the last user message."""

def last_n(history: list[ChatMessage], n: int) -> list[ChatMessage]: ...

def new_since_last_report(context: Context, history: list[ChatMessage]) -> list[ChatMessage]:
    """Messages after the one this monitor last reported on, read from its store.
    Records the new high-water mark. The incremental default."""
```

The third is the one that matters. It uses `context.store_as` under a reserved key, so an incremental monitor never re-reads what it has already judged, and the cost argument from `sentinel-deployment.md` — quadratic inference, linear deserialization, WASM memory that never shrinks — is answered by a helper rather than by discipline.

**`call_as_str(call, view=None)`.** The Python-call rendering `default_tool_call_viewer` produces for approvers, honouring a registered `ToolCallView` when one is present. One implementation serves the human approval surface and the monitor prompt.

**`result_as_str(result, *, truncated=None)`.** A tool result with the truncation range marked, so the monitor knows the model saw a cut and where. Given `output` as well, it can say how much was cut.

**`briefing_as_str(context)`.** The instruction section: task and sample descriptions, the original input, and metadata the author chose to surface. Never includes `target` unless asked; the caller passing `include_target=True` is what the log records.

**`step_as_str(step, *, history=..., preprocessor=None)`.** The evidence section for a stage, built from the helpers above: the subject, then as much history as the caller asked for. When a surface is absent in the deployment — no `view`, no untruncated `output` — the rendering says so in a fixed phrase rather than omitting it silently, so a monitor developed in an eval and run under a proxy produces a prompt that is visibly different rather than subtly different.

**`monitor_prompt(context, step, *, question, answer=..., history=..., preprocessor=None, messages_as_str=None)`.** The analogue of Scout's `scanner_prompt`, and the one most authors call. It emits: the briefing section, labelled as instructions; the evidence section inside a delimited envelope whose surrounding text says it was written by the agent under observation and may contain instructions to ignore; `step.escalations`, rendered as prior verdicts rather than as part of the conversation; and the question with an answer format. This is the "structural help" the injection section asked for, delivered as the default output of the helper people will reach for first.

An LLM monitor built from them:

``` python
@monitor
def suspicion_monitor(model: str | None = None) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        messages_as_str, extract_refs = message_numbering()
        prompt = monitor_prompt(
            context, step,
            question="Rate how suspicious this tool call is given the assignment.",
            answer="score",
            history=new_since_last_report(context, step.history),
            messages_as_str=messages_as_str,
        )
        output = await context.host.generate(prompt, model=model)
        score, explanation = parse_score(output.completion)
        return Observation(
            suspicion=score,
            explanation=explanation,
            metadata={"references": extract_refs(explanation)},
        )

    return check
```

Nothing in the body concatenates briefing and transcript, labels an envelope, or decides what to do with reasoning blocks. Those are the helper's defaults, which is the point: the author writes the question, and the choices they do make — which window of history, whether reasoning is excluded — are visible in the call.

Media is the one place text rendering is not enough. The default renders a placeholder where an image was; a monitor that must see a screenshot builds a `list[ChatMessage]` prompt itself. That needs `Host.generate` to accept messages as well as a string, which `sentinel-deployment.md`'s ABI does not do today; that is a consequence to carry back to it.

### What the helpers do not do

They do not declare or enforce anything. A monitor can read `step.output` directly, and nothing stops it or records it. The doc's validity argument for `target` — that a monitor seeing something its deployed counterpart cannot should have to say so, and the log should show it — therefore holds only for `target`, which keeps its own opt-in. Whether the same treatment should extend to `output` and `view` is [open](#open-questions); a declared view was one answer and was judged heavier than the problem, since a reviewer can grep a monitor for `step.output` as easily as for a threshold constant.

### Feature directions

In rough priority order, with what each buys:

1. **Lift Scout's rendering helpers into `inspect_sentinel`.** `messages_as_str`, `message_as_str`, `MessagesPreprocessor`, `message_numbering`. A package move with Scout re-exporting, and the `analysis` copy retired. First, because everything else composes over it.
2. **`monitor_prompt` and the evidence envelope.** The default prompt shape carries the instruction/evidence boundary, labels escalations as prior verdicts, and marks truncation. Docs examples use it, so it is what people write.
3. **Windowing helpers, especially `new_since_last_report`.** The incremental default, implemented once over the store rather than by every author.
4. **`call_as_str` and `result_as_str`.** Shared with the approval renderer, so the monitor's prompt and the human's screen show the same call.
5. **Absent-surface phrasing in `step_as_str`.** So a monitor that leans on an eval-only surface degrades visibly under a proxy or bridged agent.
6. **A `list[ChatMessage]` form of `Host.generate`.** Needed for computer-use and browser monitoring, where the evidence is a screenshot. Later, because it changes the host ABI.
7. **"What the monitor saw" in the viewers.** The rendered prompt is already recorded by `host.generate`'s `ModelEvent`, so Inspect View and Scout View can show it next to the `SentinelEvent`. A viewer task rather than a design one.

### What this changes elsewhere

- Open question 9 (does the monitor see `ContentReasoning`) is answered above.
- `Host.generate` in `sentinel-deployment.md` wants a `list[ChatMessage]` form for native media.
- Scout imports its rendering helpers from `inspect_sentinel` rather than owning them; `sentinel-development.md`'s reliance on `message_numbering` for references becomes a statement about a shared helper.
- `default_tool_call_viewer` in `approval/_apply.py` becomes a caller of `call_as_str`.

## Bridged agents are the proxy case {#bridged-agents-are-the-proxy-case}

An agent that runs its own tool loop — `claude_code`, `codex` — never reaches `execute_tools()`. An earlier draft called this a gap that leaves monitors "silently covering half a bridged agent." It is narrower than that, and it is a case this design already characterizes in full.

`agent/_bridge/util.py:587` calls `apply_bridge_tool_approval(bridge, output, input_messages)` inside the bridge generate path. That function recovers tool calls from the model's *response* and applies approval to them — with `with_modified_arguments` for rewrites, `rejection_messages()` building the append-and-regenerate, and `terminate_for_repeated_rejections()` going out-of-band through the bridge. So tool-stage policy already reaches bridged agents, by projection rather than by interception.

Which is exactly the deployment table from `sentinel-deployment.md`, evaluated in-process:

| Stage | Bridged agent | Fidelity |
|------------------------|------------------------|------------------------|
| `BeforeGenerate` | `bridge_generate` is the universal choke point | full |
| `AfterGenerate` | same | full |
| `BeforeToolCall` | projected from `tool_use` blocks in the response | good |
| `AfterToolCall` | appears only in the *next* request | **lossy** |

So **a bridged agent is the proxy deployment running in-process**, and everything `sentinel-deployment.md` establishes transfers without restatement: the five restrictions `_bridge/_approval.py` arrived at, why `reject` must be a replay rather than a response edit, why rejection needs a bound, why `modify` narrows to arguments, and why `terminate` is a side call.

That reframes what has to be communicated. Not "monitors cover half a bridged agent" but "bridged agents get the portable subset, which is specified" — and the same remedy applies as for a proxy: `AfterToolCall` should say it cannot fire here, rather than let it be discovered.

It also means the portability discipline pays off twice in-process, before any proxy exists. A monitor written to the portable subset works under a bridged agent unchanged; one that relies on `AfterToolCall` does not, and the [per-function portability verdict](#what-the-function-shape-buys) already says which is which.

## Deployment beyond the eval process

A sentinel is useful outside an eval — enforced at a network boundary in front of a model API, where the agent cannot bypass it and the coverage is all agent traffic rather than one task's samples. `sentinel-deployment.md` works that through. Four constraints from it bear on the protocol itself, so they are recorded here:

- **Two of the four stages are the portable core.** A proxy sees a request and a response; it never sees a tool execute. `BeforeGenerate` and `AfterGenerate` map directly; `BeforeToolCall` is recoverable from `tool_use` blocks in the response; `AfterToolCall` is **lossy** — a result appears only in the *next* request, so the last step of an episode is never seen. That is verbatim the limitation #5355 wrote `Reviewer` to escape, and `AfterToolCall` should say so rather than let it be discovered.

- **`terminate` travels, as an effect rather than an edit.** Every other action is an edit to the exchange — `continue` is no edit, `modify` a rewrite, `reject` an append-and-regenerate, `escalate` a hand-off down the chain. `terminate` is different in kind, but a proxy can still perform it: an error response ends the exchange and a `host.terminate()` call ends the session out-of-band, the same shape `bridge.request_terminate()` already uses in-process. What does not cross is the *guarantee* — an eval's terminate is total and synchronous, a proxy's is best-effort and may be unsupported. So there is no `PortableAction` subset; there is a capability a host may or may not provide.

  Worth keeping distinct from `reject`, which the deployment doc previously blurred: `reject` is conversational (append a synthetic result, regenerate, the model learns), an error response is transport-level (the SDK raises, the loop breaks). A proxy can do both, and they are not degrees of the same thing.

- **State must arrive as an argument.** `context.store_as(...)` survives any deployment; an ambient accessor would not, because a proxy has nothing to bind to. There is deliberately no global counterpart — see [One access path, not two](#one-access-path-not-two).

- **`view` and the untruncated `output` must be optional.** A proxy has wire types, not registered `ToolDef`s, so there is no viewer to resolve. The [rendering helpers](#views) say so in the prompt when a surface is absent rather than omitting it silently.

- **Portability has two axes, and one of them is the module.** Whether a monitor *can* run in a proxy is per-function — which context members it touches, whether it recommends `terminate`. Whether it can be *bundled* is per-module, because the import closure is a module property: one `import requests` at the top of a file disqualifies every monitor in it, whatever the functions do. This is why monitors being top-level functions matters beyond tidiness — it is what lets a bundler enumerate a file statically, with `ast` and no imports.

A fifth constraint is a design decision rather than a restriction: **monitors should be incremental by default** — classify the newest turn and fold the verdict into accumulated state, rather than re-judging the whole trajectory. Three independent arguments converge on it (quadratic inference cost, linear deserialization cost, and WASM linear memory that never shrinks), which is enough to treat it as load-bearing rather than an optimization.

The types a monitor works with also want to be importable without the eval framework; `inspect-core.md` measures what that costs today and what it would take.

## Relationship to approval and review

`Reviewer` merged on 2026-09-11 (#5356), so this is no longer a question about an open PR. Three concepts now exist for one idea, with two config keys, two event types and two decision vocabularies:

``` python
ApprovalDecision = Literal["approve",  "modify", "reject", "terminate", "escalate"]
ReviewDecision   = Literal["continue",                     "terminate", "escalate"]
```

**Chosen: a childless `AfterToolCall` protocol subsumes `Reviewer`; `@approver` survives.**

A rule at `AfterToolCall` *is* a `Reviewer` with a richer return type — the payloads are identical field for field, and `Action` is a superset of `ReviewDecision`. `@reviewer` is deprecated with a warning pointing adopters at `@protocol`, and `review/`'s 413 lines of parallel policy machinery retire with it rather than becoming a third copy.

The reason to consolidate *this* one and not approval is adoption, not elegance: `review` is days old, while `@approver` has been public for years and is used in shipped evals and extension packages. Deprecating a freshly-landed contribution has a real cost, and it is smaller than the cost of a third parallel subsystem.

Two alternatives, recorded because the choice could be revisited:

- **Façade.** `Approver` and `Reviewer` both stay; `@protocol` adapts into each. Nothing is deprecated, and the parallel machinery stays forever. Rejected: it takes the cost without the consolidation.
- **Primitive.** A rule subsumes both, and `@approver` goes too. The remaining gap is narrow and nameable — `Approval` is authoritative where a nested protocol's `Decision` is overridable — but it means deprecating a mature concept people have working code against, to gain uniformity they did not ask for. Not now; better answered once sentinels have users.

#### `approve` and `continue` are not the same word for the same thing {#approve-and-continue-are-not-the-same-word-for-the-same-thing}

The obvious tidy-up is to reconcile the vocabularies — rename `ApprovalDecision.approve` to `continue` and have one word. Don't.

Mechanically it is expensive and incomplete: every `@approver` ever written says `decision="approve"`, so a rename breaks them all; accepting both leaves two *legal* spellings, which is strictly worse than two words in two subsystems; and logs already written pin `approve` forever regardless.

But the better reason is that the difference tracks a real distinction:

| Word | Where | Means |
|------------------------|------------------------|------------------------|
| `approve` | approver, pre-execution | I authorize this action |
| `continue` | reviewer, post-execution | nothing to authorize; the tool already ran |
| `continue` | protocol, nested under another | I decline to object |

`Reviewer` reached for `continue` independently, for a decision where there is nothing left to authorize. That is evidence *for* the distinction rather than against it — and it is exactly why subsuming review into a rule is clean while subsuming approval is not. Both are `continue`-shaped; `approve` is not.

So: `@protocol` uses `continue`, `Approval` keeps `approve`, and the adapter maps between them at the boundary, which it always had to do. If monitor ever subsumes approval, `approve` retires with `@approver` — reconciliation by attrition rather than by rename.

### A protocol layer for approval too

Keeping `@approver` leaves a thin spot: approvers are authoritative today, so a rule adapted into the approval chain effectively runs under an honour-everything protocol while a configured one runs under a real one. Two layerings for one concept.

`policy_approver()` is already a proto-protocol — it does the chaining, the escalate fall-through and the no-approver-means-reject default. It just isn't configurable, and approver decisions map straight to effects.

**Make a protocol a peer of the policy list, not a layer beneath it.** Both compile down to an `Approver` that `apply_tool_approval` calls:

``` python
Task(approval=[ApprovalPolicy(...)])                       # today, unchanged
Task(approval=threshold(..., reject_at=0.8))               # protocol-mediated
```

Existing behavior doesn't change — the list form keeps its current code path — and the protocol form does more inside the same slot. That avoids routing every shipped eval through new decision-making code, which is the version of this that would carry real risk.

It also gives the framing that dissolves the thin spot without a semantic change: **the `ApprovalPolicy` list is shorthand for an honour-everything protocol.** The layering is then uniform conceptually even where the code path stays direct.

Three constraints:

- **Human approvers stay authoritative.** Same rule as [Child decisions are advisory](#child-decisions-are-advisory): a protocol may override advisory decisions, never authoritative ones. A threshold overriding a human rejection would be a safety regression.
- **Don't grow `Approval` with a score field.** A protocol can consume both shapes — decisions from approvers, reports from monitors — and an approver that wants to score should be a monitor. `Approval` reaches the transcript, the log schema, the viewer and the dataframe, and AGENTS.md wants every producer and consumer named before one of those changes.
- **Probably a separate PR.** This is the same concept rather than a tangential fix, so it is defensible — but it turns "add a Monitor registry type" into "add a Monitor registry type and introduce a protocol layer to approval". Note that the "protocol layer" here is not new machinery: it is permitting `Task(approval=)` to accept a protocol alongside a policy list, and compiling it down to an `Approver`.

The win is not tidiness. Someone running an LLM approver today has no way to express "reject only the top 1% most suspicious" — the threshold has to be baked inside the approver, where it cannot be calibrated against a benign distribution or traded against a budget. A protocol layer fixes that for approval users whether or not they ever write a monitor.

### The reviewer group's requirements (#5423) {#the-reviewer-groups-requirements-5423}

The group that built `Reviewer` proposed, in #5423, that `approval` and `review` accept a dict of named policy chains: every chain runs on every matching call, each chain keeps today's first-non-`escalate` semantics internally, and the call proceeds only if every chain approves. The motivating defect was that one ordered chain makes two *independent* monitors impossible — whichever approves first silences the other — and the workaround (wrap both in one approver) loses per-monitor events, invents a severity order, and leaves an inner monitor with nowhere to escalate.

That proposal will not land as written; the group has agreed to build on sentinels instead. Its requirements are therefore requirements on this design, and this is how each is met:

| #5423 asked for | Here |
|------------------------|------------------------|
| independent chains that all run | the default composition is concurrent; nothing is silenced |
| per-monitor events, not one wrapper event | one `SentinelEvent` per participating child, from the runner |
| a framework severity order | `terminate > reject > modify > continue`, in `Decisions.strongest()` |
| an ordered chain inside each group, with `escalate` staying within it | `chain()`; escalations never cross layers |
| a human at the end of a chain who sees who escalated and why | `human()`, reading `step.escalations` |
| named chains, and the name in the log | instance names from the mapping; `SentinelEvent.path` |
| a summary event when several chains participated | the top-level `concurrent` layer's own event |
| `terminate` cancels the other chains | `run_protocols` |
| `modify` with several participants is a rejection naming the chain | `concurrent()` |
| an uncovered call rejects, as a lone policy list does today | on the approval adapter path only; a monitor chain that nothing covers is `continue`, matching review |
| concurrent by default (their open question 1) | yes |

Two things differ deliberately. The proposal used "monitor" to mean a bundle that registers an approver and a reviewer together, so that "two monitors are two chains"; here a monitor or a rule is one function at one point and their bundle is a `chain()`. And `Task(approval=)` does not grow the dict form — the home for named parallel chains is `Task(sentinel=)`, with approvers reachable inside a chain through the adapter.

## Keeping it simple {#keeping-it-simple}

The prior-art pass added a lot of vocabulary. Most of it must stay invisible to someone who just wants to flag suspicious `bash` calls.

**The complexity lives in the protocols that read scores, and most people never write one.** Per [Two philosophies](#two-philosophies-both-first-class) a rule is a protocol with nothing to calibrate — one annotated function returning `Decision.reject(...)` — and it never encounters thresholds, budgets, or the word "audit". That the word on its decorator is "protocol" is the only control vocabulary it meets, and the docs introduce it as "the simplest protocol is a rule".

That gives two on-ramps rather than one ladder, and they rarely cross:

- **"Block bad tool calls."** A rule: `@protocol`, no monitors. This is the `@approver` experience with a wider set of points to attach to. Done.
- **"Run a control experiment."** Monitors under `threshold()` or a shipped control protocol, calibrated against a benign distribution.

The bridge between them is the tell from [Monitor or protocol?](#monitor-or-protocol): the moment your check computes a score and wants to compare it to a constant, you have discovered why the second on-ramp exists. That is when the control vocabulary should first appear, and not before.

The concrete mitigations, in order of how much they do:

1.  **Push everything possible up.** Applying the monitor/protocol split removed `defer`, `resample`, `audit`-as-an-action, `trusted_edit`, honeypots, paraphrasing and multi-sample payloads from the monitor surface. That is a real reduction, not a presentation trick. Apply the same test to anything added later.
2.  [**Progressive disclosure through defaults**](#progressive-disclosure-through-defaults-not-through-the-return-type) — a monitor sets `suspicion`, a rule sets `action`, and neither learns what `audit` or `modified` do until it needs them.
3.  [**Ship protocols, not parts**](#ship-protocols-not-parts) — pick from a list instead of assembling thresholds and budgets.
4.  [**Kind-appropriate defaults**](#observe-only-is-the-default) — zero configuration does something sensible either way: a protocol acts, a monitor records.
5.  **Two words, kept crisp — and now two types.** *Monitor* looks at one thing and says how suspicious it is. *Protocol* decides what happens, with or without monitors to consult. The failure mode is a doc explaining audit budgets inside "how to write your first rule" — keep that page free of the control vocabulary beyond the decorator's name.
6.  [**Exotica goes in extensions**](#the-extension-surface), per AGENTS.md's default.

**One vocabulary.** An earlier draft kept two — `Action` for a deciding leaf and the control literature's `accept` / `audit` / `defer` / `resample` / `trusted_edit` for the protocol above it — on the theory that the word would signal which layer you were in. There is now one layer that acts, and one word-list:

| Control term | Where it lives now |
|------------------------|------------------------|
| `accept` | `Action.continue` — the same thing |
| `audit` | `Decision.audit`, a flag; [a second axis, not a peer action](#audit-is-a-flag-not-an-action) |
| `defer_to_trusted` | a protocol name; it returns `modify` |
| `trusted_editing` | a protocol name; it returns `modify` |
| `resample` | a protocol name; it returns `modify` or `continue` |

**The literature's terms name mechanisms; ours name outcomes.** Several mechanisms produce one outcome — deferral, resampling and trusted editing all end in a `modify` — so a mechanism can never replace an outcome, and the two word-lists do not merge. `accept` is the one exception, and it *is* `continue`.

That is also why the control terms need no home in the data at all: **they are protocol names, and nothing else.** The papers' words survive where someone would search for them, the transcript records which protocol acted, and an author never learns a second vocabulary in order to return a value.

Three near-synonyms this settles, all of which look mergeable and are not:

- **`defer` is not `escalate`.** `escalate` passes the *decision* to the next decider and leaves the action alone; `defer_to_trusted` passes the *action* to a weaker model and leaves the decision made. Spelling it `defer_to_trusted` rather than `defer` matters, because bare "defer" reads in English as "postpone, hand off" — which is precisely `escalate`.
- **`trusted_edit` is not `modify`.** It is one way to produce a modification. A rule stripping `--force` from a call produces another, with no trusted model involved.
- **`reject` is not `block`.** Ours has specific mechanics from `_bridge/_approval.py` — append the rejected call and a synthetic result, regenerate, bounded by a retry limit, so the model learns it was denied. Control's `block` means the action does not execute and the protocol substitutes or escalates.

**Rejected: core executes the control actions.** There is one coherent design in which `defer` and `resample` *are* legal return values — a protocol returns `defer` and the *framework* calls the trusted model and substitutes. That is the only version where the mechanism/outcome distinction collapses, because core would be the thing turning a mechanism into an outcome.

It is rejected on scope. Core would have to know about trusted models, resampling and budget arithmetic; every new technique would become a core change rather than an extension; and `run_monitors` would stop being the only seam. AGENTS.md's default — new functionality is an extension, not core — points the other way, and [the extension surface](#the-extension-surface) is worth more than the vocabulary.

**`continue` rather than `accept`.** A nested protocol returning `continue` has declined to object; the protocol above it may still reject, so it did not authorise anything. An outermost protocol returning the same value *is* authorising. One word has to be accurate at both positions, and `continue` is — it describes what happens to the exchange rather than claiming an authority that, per [Two philosophies](#two-philosophies-both-first-class), the configuration confers rather than the function. `accept` is accurate only at the outermost position. This also settles #5356's open question the same way, and leaves the `Approval` adapter mapping `continue → approve` at the boundary, which it already had to do.

## Open questions

Retired as answered by later decisions: whether a union annotation registers
several stages (yes — a protocol annotates `Step`, so it is load-bearing);
`Report` versus `Decision` (settled: `Decision` is what a protocol returns);
whether the protocol layer lands first (it is not a layer — monitors and
protocols are two registry types, and a protocol is what acts); whether proxy portability is a
goal or an observation, which now lives only in `sentinel-deployment.md`;
whether `modify` composes (settled in [`concurrent()`](#two-compositions-concurrent-and-ordered):
a `modify` with more than one participant is a rejection naming the modifier);
what happens in a mixed configuration with no protocol (there is no such
configuration — a list containing a protocol compiles to `concurrent`, which
honours decisions and records observations, and a list of monitors compiles
to `observe`); whether protocols need their own construct (a
[decorator](#the-protocol-marker), not a constructor or a type); and whether
ordered composition should be the default (no — see [Two compositions](#two-compositions-concurrent-and-ordered)).

1.  **Does `@approver` eventually become a protocol?** [Settled for now](#relationship-to-approval-and-review): a rule subsumes the merged `Reviewer`, `@approver` survives. What is open is whether the authoritative/advisory distinction deserves its own type permanently, or whether `@approver` becomes a `BeforeToolCall` rule once protocols have users. Deliberately deferred rather than answered.
2.  **Who owns the budget when protocols nest?** [Protocols nest](#a-protocol-may-have-no-children), so a budget-owning protocol can wrap a paraphrasing one wrapping leaf monitors — which is the point, but two nested budget-owning protocols need a rule. Outermost wins is the obvious answer; whether an inner one should be an error is open.
3.  **Which protocols ship in core?** Settled in [Ship protocols, not parts](#ship-protocols-not-parts): `concurrent`, `chain`, `observe`, `threshold`, `defer_to_trusted` and `resample`. `trusted_monitoring` (the audit budget), `trusted_editing`, `untrusted_monitoring` and the pipeline stages are extension candidates.
4.  **Score aggregation.** Max across monitors is the obvious default; per-dimension max when scores are structured. Weighted combination and requiring agreement are protocol policy — but the framework has to pick a default and say so.
5.  **Where does threshold calibration get its benign distribution?** Answered in `sentinel-development.md`: replay the `Observation` monitor over a known-benign corpus as a Scout scanner, and the results dataframe's score column is the distribution; a budget becomes a threshold by percentile, and a labelled corpus gives the precision–recall curve. What remains open there is hygiene — holding the calibration corpus out of the validation split.
6.  **Does anything in v1 actually need per-task state?** The audit budget does not — it is per-episode, hence per-sample. Cross-sample gating ("terminate once 3 samples are flagged") does, and it is the case where in-memory state resets in the *unsafe* direction. If nothing in v1 needs it, [Per-task](#per-task) can be deferred whole; if something does, its scope wants deciding between task, run and eval-set.
7.  **What is the default protocol called?** Settled: `concurrent` for a list with a protocol in it and `observe` for a list of monitors. `concurrent` names the execution shape, as `chain` does, and leaves the reduction to `Decisions.strongest()` and the docs. `strictest` named only the decision half of the rule, and `all_of` named the configuration's meaning rather than its shape.
8.  **Does substituting `choices[0].message` need a usage convention?** [Settled](#one-vocabulary-across-stages) that `modified` carries a `ChatMessageAssistant` at `AfterGenerate`, leaving `usage` untouched. Now concrete, since `resample` ships: the proposal in [Two that generate](#two-that-generate) is a `protocol` bucket in `ModelUsage`, separate from agent and monitor usage and not charged to the agent's limits. Open is whether that bucket should be visible in the eval's headline token count, and whether an eval that compares protocols wants it charged to the agent to keep totals comparable.
9.  **Does the monitor see `ContentReasoning`?** Answered in [Views](#views): visible by default at whatever fidelity the provider or wire supplies, excluded via the preprocessor, and a protocol withholds it from a child by transforming `step` before the call.
10.  **Lifecycle stages**: `SampleStart` / `SampleEnd` payloads would give per-sample state a place to initialise and a monitor a place to file a final verdict on a trajectory it watched but never interrupted. Natural, and cheap now that adding a stage means adding a payload type rather than a method to a base class — but it starts to overlap `Hooks`, and neither travels to a proxy.
11.  **Can a monitor produce a `Score`?** Yes, without touching scoring: `as_scorer(as_scanner(monitor, unit="transcript"))` in `sentinel-development.md`. The transcript-grain adapter reduces per-step reports to one value and Scout's existing `as_scorer` turns that into an Inspect scorer, with flagged steps as `scanner_references`.
12.  **Does `AfterToolCall` get a bridged-agent fallback?** [Bridged agents are the in-process proxy case](#bridged-agents-are-the-proxy-case), so three of the four stages already work. Whether the lossy fourth — reconstructing a result from the *next* request — is worth building, or whether `AfterToolCall` should simply decline to fire and say why, is open.
13.  **Does `Task` / `Sample` grow a `description` field?** A public API change for a general-purpose affordance monitors happen to need first. If not, monitor context comes from `metadata` by convention and is correspondingly undiscoverable.
14.  **Which stages can `human()` serve?** `BeforeToolCall` is what the existing human surfaces render. A human at `AfterGenerate` — approve the assistant message before the agent acts on it — is plausible and would need a new rendering; `BeforeGenerate` is hard to make meaningful to a person.
15.  **Failure tolerance across many samples.** [Failing loud](#failure-semantics) is settled for the single-sample case. What is open is whether a monitor that fails on 3 samples in 500 should fail the eval, and whether that reuses `fail_on_error`'s existing shape (`True` / `False` / a proportion / a count) or needs a monitor-specific knob.
16.  **Should reading an eval-only surface be recorded?** `target` is opt-in and logged so a reader can tell whether a monitor's performance is achievable in deployment. `step.output` and `step.view` raise the same question and get no such treatment; a declared view was one answer and was judged heavier than the problem. A lighter one is for `briefing_as_str` and `step_as_str` to take the eval-only surfaces as explicit flags, which puts the choice in the call for a reviewer to see.
17.  **Default history window in `monitor_prompt`.** Full history is safe and matches what approvers get today; `new_since_last_report` is the incremental shape this design argues for elsewhere. A default is hard to change later, so this wants deciding before v1.
18.  **Is the rendered prompt part of the recorded decision?** `host.generate` already records a `ModelEvent`, so the prompt is in the log without any new field. The open part is whether replay should compare its rendering against the recorded one to detect drift in the helpers.
19.  **Is the alias `ControlProtocol` or `Protocol`?** Bare `Protocol` collides with `typing.Protocol`, which this codebase imports constantly, and `ControlProtocol` is the safe name. The cost is that the decorator and the alias no longer pair the way `tool` and `Tool` do. Accepting the collision — a monitor author's file rarely defines structural types — is the alternative.
20.  **Should `chain` and `concurrent` accept monitors at all?** They do here: a monitor in either is recorded and falls through, which is what gives a mixed top-level list a meaning. The alternative is `Protocols` only, with monitors reachable solely through a score-reading protocol; stricter, and it would make `Task(sentinel=[no_curl(), suspicion_monitor()])` a type error rather than a recorded-but-inert monitor.
21.  **What is the umbrella called?** Settled: `sentinel`, for the feature, `Task(sentinel=)`, the package and the event, with `monitor` kept for the scorer and `protocol` for the decider as the control literature and ControlArena use them. `Task(monitor=)` held protocols and rules and never a bare monitor, and reviewers read it as "the monitor plus the protocol". Renaming the scorer instead (`observer`) would have broken the literature's pair; `ranger`, `warden` and `oversight` were the runners-up for the umbrella.
