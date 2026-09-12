# Monitors

Exploratory design for a new registry type, `@monitor`: one annotated function per point in the agent loop, with one identity, one place to keep state, and one report type.

Status: sketch. The Python below is illustrative, not proposed API.

**Related design documents.** This one defines the protocol. `monitor-deployment.md` covers running a monitor outside the eval process — in a proxy on the wire — and the constraints that places on the protocol. `inspect-core.md` covers extracting the wire types into a package light enough for a monitor author (or another language) to depend on.

## Goal

A *monitor* watches an agent as it runs and may intervene. Concretely, the things people build today:

- an LLM that reads each tool call and stops the sample if the call looks like sabotage or an exfiltration attempt
- a classifier that reads each tool *result* and stops the sample if the agent actually reached the internet (#5355)
- a running suspicion score accumulated over a whole trajectory, where no single step is disqualifying but the total is
- a heuristic that rewrites or annotates the model's input before each generate ("you have used 8 of your 10 allowed commands")

All four are the same idea seen from different points in the loop. Inspect has no single object for it: each has to be assembled from a different primitive, and the pieces cannot share state without the author inventing a place to put it.

## What a monitor is assembled from today

| Point in the loop | Primitive | Gaps |
|------------------------|------------------------|------------------------|
| Before a tool call | `@approver` | Sees nothing but the call. Fires only when the model calls a tool. |
| After a tool result | `@reviewer` (#5356, open) | New; not yet merged. |
| Before generate | `Hooks.on_before_model_generate` | Process-global and env-enabled, so not per-eval or per-task; exceptions swallowed; no transcript record; no way to terminate. |
| After generate | — | Nothing. |

And state, which is the part that hurts most. An approver is constructed once when the eval is resolved and then called from every sample concurrently, so `self` is shared across samples — the same hazard the `Hooks` docstring warns about at length, with the same workaround (key a dict by `sample_id`, remember to evict it). Nothing carries across the four points either: an approver that wants to know what the *previous* tool returned has to go fishing in `history`.

A monitor is the object that makes those four points one thing with one state.

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
- **NeMo Guardrails** uses Colang, a rule DSL, at 100–300ms added latency — the endpoint `monitor-deployment.md` predicts a restricted Python subset converges on.
- **Portkey** integrates external guardrails by webhook, which is what the host ABI's `fetch` is for.
- Output guardrails under streaming are an open problem in the OpenAI SDK too.

### What we took, and what we left

Absorbed: the monitor/protocol split, structured scores, `audit` as a flag, prepackaged protocols, `additionalContext` and `systemMessage` as separate channels, the `run_in_parallel` knob, reasoning visibility. The disagreement between the two traditions about what a monitor emits was absorbed too, as [two report kinds](#two-kinds-and-how-to-choose) rather than as a field convention.

Deliberately **not** in the core surface: honeypots, paraphrasing, resampling payloads, collusion-resistant untrusted monitoring. These matter to a small number of control researchers, carry real conceptual weight, and are better served by the protocol extension surface than by the monitor protocol. See [Keeping it simple](#keeping-it-simple).

## Shape

A monitor is an async function, produced by a registered factory in the idiom every other Inspect decorator uses. **Which of the four points it watches is given by the type of its second parameter** — there is no separate stage argument, and no base class.

``` python
@monitor
def no_curl() -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Recommendation | None:
        """Called before a tool call executes."""
        ...

    return check
```

The four payload types are the vocabulary:

| Payload | Fires |
|------------------------|------------------------|
| `BeforeGenerate` | before each generate, before cache lookup |
| `AfterGenerate` | after each generate, before the output reaches the agent |
| `BeforeToolCall` | before a tool call executes |
| `AfterToolCall` | after a tool call executes, before the model sees the result |

Two pairs: input/output around generate, call/result around a tool. `None` means "didn't participate"; a `Report` — either an `Observation` or a `Recommendation` — carries evidence or an opinion. See [What a monitor returns](#what-a-monitor-returns).

A monitor watches one point. A concern spanning two is two monitors — see [One function, one point](#one-function-one-point), which argues that this is rarer than it looks and that the framework is better for not having a construct for it.

Each monitor takes a single frozen dataclass rather than positional arguments, following `Hooks` rather than `Approver`. The parameter is named `step` rather than `Hooks`' generic `data`: all four payloads are the thing under examination, and a monitor examines a step in the agent's trajectory — the unit the control literature scores. `step.call`, `step.output`, `step.history` read as a subject; `data.call` reads as a bag. Per-stage names (`generate.input`, `call.call`) were the alternative, and the tool side sinks them. With four payloads that will grow fields, adding a field to a dataclass is additive; adding a positional parameter breaks every monitor.

### The payloads

``` python
@dataclass(frozen=True)
class BeforeGenerate:
    model: str
    input: list[ChatMessage]
    tools: list[ToolInfo]
    tool_choice: ToolChoice
    config: GenerateConfig


@dataclass(frozen=True)
class AfterGenerate:
    model: str
    input: list[ChatMessage]
    output: ModelOutput


@dataclass(frozen=True)
class BeforeToolCall:
    message: str                # assistant text alongside the call
    call: ToolCall              # the call as it will execute
    view: ToolCallView
    history: list[ChatMessage]


@dataclass(frozen=True)
class AfterToolCall:
    message: str
    call: ToolCall              # the call as executed (after any `modify`)
    result: ChatMessageTool     # what the model will see, after truncation
    output: ToolResult          # the tool's untruncated return value
    view: ToolCallView
    history: list[ChatMessage]


Step: TypeAlias = BeforeGenerate | AfterGenerate | BeforeToolCall | AfterToolCall
"""The union, for code that handles any point — a protocol, or a dispatcher."""
```

A monitor never annotates `Step`, since [its annotation is what selects the stage](#the-stage-comes-from-the-annotation). The alias exists for the layer above, which does see all four.

**Everything in `step` is agent-influenced; nothing in `context` is.** `call`, `message`, `history`, `view`, `result` and `output` are all written or shaped by the agent under observation and are therefore injection-bearing; the briefing is author-written, the store is the monitor's own, the host is the framework's. Splitting them across two arguments makes that boundary structural rather than a matter of field ordering, which is the most useful thing the framework can do about injection (see [It is the only input the agent did not write](#it-is-the-only-input-the-agent-did-not-write)).

`BeforeToolCall` and `AfterToolCall` are the `Approver` and `Reviewer` payloads from #5356. The before/after naming earns its keep here: `BeforeToolCall` carries a `call: ToolCall` and `AfterGenerate` an `output: ModelOutput`, so a payload named for the object it wraps would collide with a field inside itself.

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
    `monitor-deployment.md`; in-process these are ordinary implementations,
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
| `sample_id` / `epoch` | sample id, epoch | conversation key (see `monitor-deployment.md`) |
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

The context is constant for a sample, so handing it over once (at `on_sample_start`, say) and letting the monitor keep it looks tidier. It isn't: keeping it means state, and a monitor that needs state to know its own assignment can no longer be the pure function of one exchange that `monitor-deployment.md` argues for. Passing it on every call costs a reference and preserves that property.

It is a separate argument rather than a payload field because it is invariant while the step is not — re-attaching an identical object to every payload invites the question of whether it could differ — and because two arguments state the monitor's job in the signature: here is what should be happening, here is what just happened. Two-argument callbacks are the local idiom (`Solver(state, generate)`, `Scorer(state, target)`), and OpenAI's guardrails likewise take context first.

The forward-compatibility argument for single-dataclass payloads still holds: it rules out *many* parameters, not two. Every future addition lands inside `Context` or inside a step payload, so the arity stays stable.

#### Where the author writes it

Neither `Task` nor `Sample` has a `description` field today — `Task` carries `name`, `display_name`, `version`, `metadata`, `tags`; `Sample` carries `input`, `choices`, `target`, `id`, `metadata`. So this needs somewhere to live. Two options:

- **`Task(description=)` and `Sample(description=)`**, general-purpose authored prose. Two small additive fields, no monitor-specific API surface, and useful well beyond monitors — the viewer, model-graded scorers, and eval discovery all want "what is this task about" too. The risk is that a field named `description` attracts documentation written for humans reading the source, which the docstring already covers; the docstring for the field has to say it is a briefing for automated readers.
- **A `metadata` convention**, e.g. `Task(metadata={"description": ...})`. No API change at all, but undiscoverable and unvalidated.

The first, unless we are trying hard to avoid touching `Task` and `Sample`. Structured context stays in `metadata` either way.

### What a monitor returns {#what-a-monitor-returns}

A monitor **reports**; it does not act. What it hands back is evidence, and optionally an opinion about what should happen. A [protocol](#protocols) decides what actually happens.

``` python
Action = Literal["continue", "modify", "reject", "terminate", "escalate"]
"""What a monitor can recommend about the thing it just examined."""


class Observation(BaseModel):
    """Evidence, for a protocol to calibrate and threshold."""

    suspicion: Suspicion
    """How suspicious. Required — an Observation with no score says nothing."""

    explanation: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class Recommendation(BaseModel):
    """An opinion about what should happen. Advisory — a protocol may honour or ignore it."""

    recommend: Action
    """Required."""

    audit: bool = Field(default=False)
    """Request that oversight budget be spent on this."""

    modified: ToolCall | None = Field(default=None)
    """Rewritten tool call, for a 'modify' recommendation."""

    explanation: str | None = Field(default=None)
    """Why. Operator-facing by default; see 'Two audiences' below."""

    metadata: dict[str, Any] | None = Field(default=None)


Report: TypeAlias = Observation | Recommendation
"""What everything downstream records and aggregates."""
```

A monitor returns one kind or the other, declared by its return annotation and fixed for the life of the monitor. `Report` is the union everything downstream handles — see [Two kinds, and how to choose](#two-kinds-and-how-to-choose) for why the split is structural rather than a field convention.

#### The name says the layering

`Decision.action` would read as a command — the monitor decided, the thing happens. Sometimes it does: with no protocol configured, a `Recommendation` is honoured directly ([Two philosophies](#two-philosophies-both-first-class)). But it is the *configuration* that makes it so, not the monitor, and under any configured protocol the same report can be thresholded, overridden or merely recorded. `Recommendation.recommend` is accurate in both cases where `Decision` is accurate in only one, which is worth the longer name.

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

So the return type is one of the report types or `None`, matching `Score | None`. The polymorphism that genuinely helps stays inside, as `Suspicion`.

Progressive disclosure survives intact: a scorer sets `suspicion` and ignores the rest, and never learns what `audit` or `modified` do until it needs them. That was always the useful half — the complexity reduction came from [pushing work up to the protocol](#protocols), not from shaving a constructor call.

#### Three states, all distinct

| Return | Meaning | Recorded |
|------------------------|------------------------|------------------------|
| `None` — *abstain* | didn't participate | no |
| report with `suspicion`, no `recommend` | examined, no verdict — here is evidence | yes, as an observation |
| report with `recommend` | examined, and here is what I think should happen | yes, as a recommendation |

Call the first case **abstaining**, not "returning None". "Return `None`" and "`suspicion` is `None`" mean entirely different things — didn't participate, versus this report carries no score — and writing both as "None" in prose is the fastest way to confuse a reader. The API spells abstention `None`; the docs should not.

Abstaining rather than a sentinel (`Report.none()`) follows `Scorer`, which returns `Score | None`, and avoids fighting Python: a monitor with an early exit writes `if step.call.function != "bash": return`, which yields `None` whatever the signature says. A sentinel would either have to accept `None` anyway — a second spelling for one state, which is what the empty report was rejected for — or force a constructor call on the most common path, since a targeted monitor abstains on nearly every call. The general rule: `None` is right for absence when there is exactly one kind of absence, it carries no data, and it is unambiguous with "not yet computed". All three hold here, and a null object buys nothing because the protocol must branch on "did anyone report" regardless.

Named constructors are still worth having, for common *valid* reports rather than for abstention — sugar over existing states, not new ones:

``` python
Recommendation.clear()     # recommend="continue" — examined and cleared
Observation.score(0.9)     # suspicion=0.9
```

A monitor is **not** required to recommend an action. Forcing a scorer to say `continue` would be a lie — in Ctrl-Z the monitor genuinely has no view, because deferral versus audit depends on budget it cannot see — and it would corrupt the precedence rule, since a monitor reporting suspicion 0.95 would be voting `continue`. Splitting the types is what makes that structural: a scorer has no `recommend` field to be forced to fill.

An earlier draft had one type with every field optional and two validators — "at least one of `suspicion`, `recommend`, `audit`", and "`modified` iff `recommend == 'modify'`". The split absorbs the first entirely: `Observation.suspicion` and `Recommendation.recommend` are required fields, so `Report()` is not constructible and there is no error message to get right. The second validator survives, inside `Recommendation`, because it relates two of its own fields. It mirrors `Approval.modified`.

The alternative — allow an empty report and record it as a no-op observation — was rejected because it creates a fourth state indistinguishable in effect from `None`, while still producing a transcript record. "I examined this and found nothing" is already expressible, and better, as `recommend="continue"` or `suspicion=0.0`.

This also keeps `continue` meaningful rather than filler. **`continue` = I examined this and cleared it**; `escalate` = I decline to decide, pass it on; `None` = I wasn't involved. A chain needs all three.

#### Two kinds, and how to choose {#two-kinds-and-how-to-choose}

The split is not ours. It is the seam between the two bodies of prior art surveyed above, which disagree about what a monitor even emits:

| | Emits | Prior art |
|------------------------|------------------------|------------------------|
| **`Observation`** | a score, for someone else to threshold | Ctrl-Z's trusted monitor; TraceGuard's five dimensions. [The control literature separates scoring from deciding](#the-control-literature-separates-scoring-from-deciding) — "the monitor is a scorer", and accept/defer/resample/audit belong to the protocol |
| **`Recommendation`** | an action | every shipped guardrail: Claude Code's `permissionDecision: allow \| deny \| ask`, OpenAI's tripwire, Guardrails AI's pass/fail, NeMo's Colang rules |

Neither tradition has a noun for the thing itself — the literature says "suspicion score", products say "decision" — so the names are ours, chosen to keep the layering legible.

Examples of each:

| Monitor | Kind | Report |
|------------------------|------------------------|------------------------|
| LLM judge over a tool call | `Observation` | `suspicion=0.87` |
| TraceGuard-style dimensions | `Observation` | `suspicion={"goal_alignment": 0.1, "sabotage": 0.8, ...}` |
| Running trajectory score | `Observation` | accumulated in the store, reported each step |
| CoT monitor | `Observation` | reasoning scored separately from the action |
| `no_curl` | `Recommendation` | `recommend="reject"` |
| `rm -rf /` guard | `Recommendation` | `recommend="reject"` |
| Strip `--force` from a call | `Recommendation` | `recommend="modify", modified=...` |

Note that `Observation` keeps the shape [Progressive disclosure](#progressive-disclosure-through-defaults-not-through-the-return-type) already argued for: `Suspicion` is the flexible value, `Observation` the fixed wrapper — exactly `Score` and `Value`.

**Choosing is not determined by the use case.** #5355's network-egress classifier is legitimate either way: an `Observation` if you want a protocol to calibrate the cut point, a `Recommendation` if the detection is definitive. One question decides it:

> **Do you want to own the threshold?** Yes → `Recommendation`. No → `Observation`.

And one tell makes it checkable, which matters more than the rule because it catches the failure in the act:

> If your monitor computes a score and compares it to a constant, **that constant is a threshold** and it belongs in the protocol. Return the score instead.

That is the whole defect the protocol layer exists to fix, restated as something an author can see in their own diff — and something a reviewer, or a lint, can grep for.

#### Which kind the docs should lead with

`Recommendation`, and not because it is the more important one.

[Keeping it simple](#keeping-it-simple) rules out the alternative: leading with `Observation` means explaining what the number is, what consumes it, what a threshold is and why you do not set it — the entire control vocabulary inside "write your first monitor". A deterministic rule needs none of it, and recommendation-shaped guards are what people arrive expecting, having used Claude Code hooks or the OpenAI SDK.

The control vocabulary then enters where it is actually needed: at the tell above, the moment someone's check produces a number.

This would collide with observe-only if observe-only applied to both kinds. It doesn't: per [Two philosophies](#two-philosophies-both-first-class) a `Recommendation` monitor with no protocol is honoured, so a beginner's first monitor works with no configuration and never meets the word "protocol". Observe-only remains [the default for scores](#observe-only-is-the-default), where an uncalibrated threshold is the thing being guarded against.

#### Suspicion is structured

``` python
Suspicion: TypeAlias = float | dict[str, float]
```

A scalar is accepted, but the multi-dimensional form is the one to encourage: TraceGuard reports 95% versus 0% safety for structured versus single-score monitoring against a colluding monitor (see [Prior art](#prior-art)). A protocol can threshold per dimension, and dimensions can be scored by independent monitors so no single model sees the whole assessment.

#### `audit` is a flag, not an action

Auditing — spending scarce human review — is orthogonal to what happens to the action. You can continue-and-audit or reject-and-audit. Ctrl-Z's deferral and auditing are two thresholds over one score, not two values in one enum.

`audit` lives on `Recommendation` rather than `Observation`, because "spend human review on this" is itself a policy statement; a scorer flags something by scoring it high. The budget is the protocol's, not the monitor's: a monitor *requests* an audit, the protocol grants it if budget remains. This is the first concrete consumer of the per-task state left open under [State](#state).

#### Two audiences

Claude Code hooks separate `additionalContext` (the model sees it) from `systemMessage` (the operator sees it, the model does not). We should too, and the reason is security rather than tidiness: **telling an agent why it was flagged teaches it to evade.** `explanation` should be operator-facing by default, with a separate, explicit field for anything the model is meant to read.

That separate field is also the soft intervention we otherwise lack — a way to say "continue, but the model should know X" without rejecting anything.

#### One vocabulary across stages

This is a different axis from the two kinds above. `Observation` and `Recommendation` split by *what a monitor emits*; nothing here splits by *where it runs*. A `BeforeToolCall` scorer and an `AfterGenerate` scorer both return `Observation`, and `Action` is one Literal across all four stages. The stages look like they need different vocabularies; they mostly don't:

| Stage             | continue | terminate | escalate | reject | modify       |
|-------------------|----------|-----------|----------|--------|--------------|
| `BeforeGenerate`  | ✓        | ✓         | ✓        | ✓      | open (below) |
| `AfterGenerate`   | ✓        | ✓         | ✓        | ✓      | —            |
| `BeforeToolCall`  | ✓        | ✓         | ✓        | ✓      | ✓            |
| `AfterToolCall`   | ✓        | ✓         | ✓        | **—**  | **—**        |

`continue`, `terminate` and `escalate` are universal. `reject` generalises further than it looks: at `BeforeGenerate` it means "do not run this generate, and tell the agent why"; at `AfterGenerate`, "discard this completion". It is genuinely excluded only at `AfterToolCall`, and for a *policy* reason — #5355's argument that withholding output tells the model its command failed when it did not, so the model's picture of the sandbox diverges from the sandbox. The same reasoning excludes `modify` on a result.

`modify` is the one action that is tool-call-shaped, because `modified` must carry something and only `BeforeToolCall` has a single object for it. Rewriting a generate's input is three things — messages, tools, config — so `modify` at `BeforeGenerate` is left open; the likely answer is in-place mutation of the payload, which is what `Hooks.on_before_model_generate` does today, and never a recommendation at all.

#### This is not the `stage` flag #5355 rejected

That argument was against a `stage` parameter on a single `Approver.__call__`, where the caller branches on a runtime flag to know what it is looking at. A monitor's stage is already encoded structurally, and more tightly than the class form managed: the payload type *is* the stage, so a monitor that reads `step.result` cannot have been registered for `BeforeToolCall`. Sharing the *return* type does not reintroduce a stage flag, because there is no stage in `Report` to begin with.

#### What one type buys

Six places want uniform handling: the precedence rule under [Composition](#composition); the escalation chain's fall-through; `MonitorEvent`, whose decision field would otherwise be a union or stringly typed; policy and YAML config parsing; the TUI transcript renderer; and `analysis` dataframe columns.

The cost of not sharing is already visible — #5356 had to make the approval system generic over the protocol to share glob matching, the ordered chain, decision recording, registry lookup and config parsing between two decision types. A third type makes that worse.

#### Rejected: a generic parameterised on the action set

``` python
A = TypeVar("A", bound=str, default=Action)

class Recommendation(BaseModel, Generic[A]):
    recommend: A
```

This keeps per-stage legality statically checked and is the better answer in the abstract. It is the wrong answer for this codebase:

- No serialized Pydantic model in `inspect_ai` is generic today. The only `Generic[...]` uses are a `list[T]` subclass in the eval recorder and the provider batching dataclasses, none of which reach the log schema.
- Parameterised generics get Pydantic's mangled names in `components/schemas` — `Recommendation_ObserveAction_` — which flow to `generated.ts` and the barrel. `design/type-generation-pipeline.md` documents the machinery that exists precisely to keep unstable auto-generated names out of the schema.

A subclass that widens the `recommend` Literal is also out: widening a field type in a Pydantic subclass is an unsound override, mypy flags it, and the suppression gate means it could not be papered over.

#### Enforcing the restrictions

With a flat type the type checker cannot stop an `AfterToolCall` monitor recommending `reject`. The dispatcher knows which stage it dispatched, so it validates there and raises — an illegal recommendation is a bug in the monitor, not agent-controlled input, so failing loudly is right. This follows AGENTS.md's "invalid state" rule: define the unsupported behavior explicitly and cover it with a test rather than silently coercing `reject` into `continue`.

## Protocols {#protocols}

**A monitor observes and reports. A protocol authorizes and acts.**

That split came out of [Prior art](#prior-art) and is the main architectural consequence of it. In Ctrl-Z the monitor is a scorer; deferral, resampling and auditing are things the protocol does with the score, because they depend on calibration against benign distributions and on a global budget the monitor cannot see.

**"Protocol" is a role, not a type.** A protocol is a monitor that takes other monitors as arguments and converts their reports into one recommendation — the combinator shape Inspect already uses everywhere it composes: `chain(*solvers) -> Solver`, `multi_scorer(scorers, reducer) -> Scorer`, `policy_approver(policies) -> Approver`. None of those is a separate registry type, and neither is this. See [Protocols are monitors](#protocols-are-monitors).

The layering below is therefore about *what code does*, not about what type it has. That is a weaker guarantee than a type would give, and [the cost of that](#what-the-collapse-costs) is recorded rather than glossed.

Applying the split shrinks the monitor surface rather than growing it. Every control-literature action turns out to live above the monitor:

| Control action | Whose job | How |
|------------------------|------------------------|------------------------|
| `accept` | protocol | below every threshold |
| `audit` | protocol | grants a monitor's `audit` request if budget remains |
| `defer` | protocol | calls the trusted model and substitutes its action |
| `trusted_edit` | protocol | has the trusted model rewrite, then substitutes |
| `resample` | protocol | draws more samples, scores each, picks or incriminates |

None are expressible by something looking at one exchange, so `Action` does not grow. Resampling is the one that needs more than a wider vocabulary — it needs a way to substitute a whole `ModelOutput`, which is [open question 9](#open-questions).

The collusion countermeasures land here too: paraphrasing and minification are a transform between agent output and monitor input; honeypots are synthetic inputs injected into the monitor's stream. Pipeline stages, not monitor logic.

### Two philosophies, both first-class {#two-philosophies-both-first-class}

The [two report kinds](#two-kinds-and-how-to-choose) are not just two shapes of data. Each implies a way of running monitors, and the design has to support both rather than treating one as the degenerate case of the other.

- **Recommendations, no protocol.** The monitor decides; the framework applies. No thresholds, no calibration, no budget. This is the shipped-guardrail philosophy — and it is not hypothetical in Inspect, because **it is exactly what `@approver` does today.** An approver has no protocol, its decisions are authoritative, and nobody regards that as unsafe.
- **Observations, heavily calibrated protocol.** The monitor never decides; thresholds, budget and actions all live in the protocol. This is the control-literature philosophy, and it is what the protocol layer was built for.

Neither is the advanced version of the other. What a protocol is *for* becomes sharper as a result: **a protocol exists to turn scores into a recommendation.** Where there are no scores, there is nothing for it to do, and requiring one would be ceremony.

That collapses to a single rule about what sits at the top of a configuration:

> **Whatever is outermost must be `Recommendation`-kind, or nothing acts.**

| Outermost | Behaviour |
|------------------------|------------------------|
| a `Recommendation` monitor | honoured — the approval model |
| an `Observation` monitor | recorded, never acted on — **and this is how the benign distribution for calibration gets collected** |
| a protocol wrapping either | whatever the protocol decides; it is `Recommendation`-kind by construction |
| a mix of both, unwrapped | recommendations act, scores record — worth a warning, since half the configuration acts and half does not |

This is where the type collapse pays for itself: a protocol needs no special case in this table, because "converts `Observation`s into a `Recommendation`" *is* what being `Recommendation`-kind means. `observe_only()` becomes the ordinary way to suppress a recommendation rather than a distinct mode — a dry run, "what would my guards have done".

The `Observation`-outermost row is worth dwelling on: it looks degenerate and isn't. Calibration needs a benign score distribution, and running with nothing consuming the scores over known-benign tasks is how you get one. It is step one of the second philosophy, not a failure to configure.

### Recommendations are advisory {#recommendations-are-advisory}

A monitor's `recommend` is an opinion **whatever wraps it** may honour or ignore. Where nothing wraps it, there is nothing to ignore it and it is honoured — the approval model above.

Within a wrapping protocol this is forced rather than chosen. We want [observe-only as the default for scores](#observe-only-is-the-default); if a monitor's `terminate` bypassed a configured protocol, observe-only would not be observe-only, and a monitor could end a sample under a configuration that promised it wouldn't.

The distinction that makes this coherent is **declared versus inferred**. Observe-only protects against actions a protocol *inferred* from a number the author never thresholded. It was never protecting against actions the author *declared*: someone who writes `recommend="reject"` is not surprised when a call is rejected, any more than an approver author is surprised today.

One rule then covers the bimodality: **a wrapping monitor may override advisory reports, never authoritative decisions.** A human approver's rejection is authoritative and stays so — a threshold overriding a human would be a safety regression. Note this is a rule about *what a protocol should do*, not something its type prevents — one of the things [the collapse costs](#what-the-collapse-costs).

### Observe-only is the default for scores {#observe-only-is-the-default}

`Task(monitor=suspicion_monitor())` with nothing wrapping it scores, records to the transcript, and never intervenes. For an `Observation` monitor, enforcement is opt-in.

It is the safe default for that kind, and for a specific reason rather than a general caution about safety: a threshold nobody set is a threshold nobody calibrated, so acting on one is acting on a number whose meaning is unestablished. A scoring monitor whose scores nobody reads is a safety mechanism failing open, and under observe-only that is a *declared mode* rather than an accident.

**It is not the default for `Recommendation` monitors**, per [Two philosophies](#two-philosophies-both-first-class). There the action was declared by the author, not inferred from an uncalibrated number, and defaulting to silence would mean a monitor that does nothing until you learn about a layer you had no reason to need. That is the answer to what was open question 18, and the deciding evidence is that `@approver` has worked this way for years.

Either way a config-time check makes the dead configurations visible, and the [declared kind](#the-kind-comes-from-the-return-annotation) is what lets it be specific rather than generic:

> `no_curl` is a `Recommendation` monitor, but the configured protocol is `observe_only()` — its recommendations will be recorded and not acted on.

> `suspicion_monitor` is an `Observation` monitor and the configured protocol has no threshold for it — its scores will be recorded and never read.

> `no_curl` will act while `suspicion_monitor` only records, because no protocol is configured to read its scores.

All three are the "safety mechanism with no consumer" problem, and all three are what AGENTS.md's "invalid state" rule asks for: define the unsupported state explicitly rather than silently doing nothing with it. None is statable without knowing the kind up front, which is the practical case for declaring it.

### Ship protocols, not parts {#ship-protocols-not-parts}

The control literature's protocols are a small, finite, well-studied set. Ship them named and configured so nobody assembles thresholds, budgets and actions by hand:

``` python
Task(monitor=observe_only(network_suspicion()))
Task(monitor=trusted_monitoring(network_suspicion(), audit_budget=0.01))
Task(monitor=defer_to_trusted(network_suspicion(), trusted="openai/gpt-4o-mini"))
```

This is the same move as shipping `react()` and `basic_agent()` rather than making everyone write a tool loop. It converts "understand the control literature" into "pick from a list", and the papers become an explanation of *why* each protocol exists rather than required reading.

A protocol owns:

- **thresholds** — calibrated against benign score distributions, per dimension where scores are structured
- **the audit budget** — how much remains, and how it is allocated across an episode (Ctrl-Z decays it exponentially, scrutinising early steps harder)
- **aggregation** — combining reports from several monitors
- **the control actions** in the table above
- **pipeline stages** — paraphrasing, honeypot injection, each of which can now be [its own nested protocol](#protocols-are-monitors)
- **its stance toward recommendations** — honour, or record and ignore

All of which is ordinary code, not framework surface — see [`run_monitors` is where the guarantees live](#run-monitors-is-where-the-guarantees-live).

### Protocols are monitors {#protocols-are-monitors}

``` python
@monitor
def trusted_monitoring(
    *monitors: Monitor,
    audit_budget: float = 0.01,
    defer_threshold: float = 0.8,
    audit_threshold: float = 0.95,
) -> Monitor:
    async def decide(context: Context, step: Step) -> Recommendation | None:
        reports = await run_monitors(monitors, context, step)
        ...

    return decide
```

Everything that made a protocol look like a separate kind of object turns out to be convention rather than structure:

| Looked like a difference | Actually |
|------------------------|------------------------|
| sees all four points | annotate `Step`, the widest union — same mechanism as any monitor |
| returns a different type | `Recommendation` is exactly what it produces |
| stateful | convention; both use `context.store_as` |
| one per configuration | convention |
| **takes monitors as input** | **the only real one — and that makes it a combinator** |

A combinator is `[Monitor] -> Monitor`, and Inspect answers that shape the same way three times over — `chain`, `multi_scorer`, `policy_approver` — never with a new registry type. `multi_scorer` is the closest analogue: it runs children in parallel, aggregates with a reducer, and returns one `Score`. It is a `Scorer`.

Two consequences worth stating plainly, because both remove things this document previously carried:

- **`@monitor` is the only new `RegistryType` value.** One decorator, one config surface, one set of plumbing. This answers what was open question 3 by dissolving it.
- **The naming problem disappears.** An earlier draft needed `ControlProtocol` because bare `Protocol` collides with `typing.Protocol`, which this codebase imports constantly. With no type to name, "protocol" goes back to being what the literature uses it for — a word for a role — and nothing collides. (`Policy` would still have been wrong, for what it is worth: in the control literature the *policy is the untrusted agent*, so reusing it for the thing doing the monitoring would invert the term.)

Protocols nest, which the previous design forbade. A budget-owning protocol can wrap a paraphrasing protocol wrapping the leaf monitors, so the [pipeline stages](#the-extension-surface) become composable pieces rather than features one monolithic protocol has to anticipate. What still needs a rule is *budget ownership* under nesting — see [open question 3](#open-questions).

### `run_monitors` is where the guarantees live {#run-monitors-is-where-the-guarantees-live}

**The protocol invokes its monitors; the framework does not.** This is forced by [Prior art](#prior-art): paraphrasing and minification are transforms between agent output and monitor input, and honeypots are synthetic inputs injected into the monitor's stream. Neither is expressible if the framework has already called the monitors and handed over finished reports.

So `run_monitors()` is not a convenience. It is where core's obligations sit:

- **filters by point** — only monitors annotated for this step are called
- **fans out with `tg_collect()`**, per AGENTS.md, which [Concurrency is a safety property](#concurrency-is-a-safety-property-not-just-a-latency-one) shows is a safety requirement rather than a latency one
- **handles abstention** and applies the failure policy uniformly
- **records every report to the transcript, including the ones the protocol ignores** — load-bearing, because the ignored ones are the benign distribution calibration needs

It returns:

``` python
@dataclass(frozen=True)
class Reported(Generic[R]):
    monitor: str
    report: R


@dataclass(frozen=True)
class Reports:
    observations: Sequence[Reported[Observation]]
    recommendations: Sequence[Reported[Recommendation]]
```

Split by kind, because [the two halves aggregate differently](#composition) — scores combine and then threshold, recommendations resolve by precedence. Monitor identity is attached because a protocol may weight or require agreement across specific monitors. Generics are safe here in a way [they were not for `Report`](#what-a-monitor-returns): these are frozen dataclasses passed as arguments, never serialized, so no mangled name reaches `components/schemas`.

Everything else a protocol does is **ordinary Python over `Reports` plus task-scoped state** — thresholds, budget arithmetic, aggregation, deferral. That is the point rather than a gap: a protocol is meant to be [the extension surface](#the-extension-surface), and something requiring framework blessing beyond one helper would not be one.

Two things it is not quite arbitrary code over, both of which are existing open questions the collapse makes load-bearing:

- **Task-scoped state has to actually work.** The audit budget is its first real consumer, and `scope="task"` currently has three unresolved problems under [State](#state) — the read-modify-write race across `await`, persistence across `eval_retry`, and whether the scope is really task or run.
- **Resampling needs generate-stage substitution.** Drawing alternative completions and executing the least suspicious means replacing a whole `ModelOutput`, which is [open question 9](#open-questions). The previous design could defer this as "a protocol concern the monitor never sees"; with one type that dodge is gone, and either the protocol calls `context.host.generate()` and substitutes, or resampling is not expressible.

### What the collapse costs {#what-the-collapse-costs}

A separate type could have made the contract explicit. One type cannot, so three things become convention plus documentation:

- Nothing stops a protocol from **skipping `run_monitors`**, calling its monitors sequentially, and quietly destroying the independence property TraceGuard's result depends on.
- Nothing stops it from **never recording** the reports it ignored, losing the benign distribution.
- "No `escalate` at the outermost layer" is no longer expressible in the type. Harmless in practice, since [all-escalate is already defined as `continue`](#composition).

The first two are **detectable rather than preventable**: a composing monitor that produced a recommendation with no child reports in the transcript is visible in the log, and a config-time check can flag it. That is a genuine reduction in guarantee, and it buys one registry type instead of two, composable pipeline stages, and a table in [Two philosophies](#two-philosophies-both-first-class) with no special case in it.

### The extension surface {#the-extension-surface}

Protocols being ordinary monitors is what makes them the natural extension point — a third party ships one the same way they ship any monitor, with no new registry type to register into and no core change to negotiate.

That matters for scope discipline. AGENTS.md's rule — new functionality defaults to an extension, not core — applies directly: honeypots, paraphrasing, resampling and collusion-resistant untrusted monitoring carry real conceptual weight and serve a small audience. Design the extension point, ship the protocols people actually use, and let the research-grade machinery live outside core until there is demand.

The `run_monitors()` seam is what makes that credible rather than aspirational. An extension implementing honeypotting does not need a framework hook: it wraps the call, injecting synthetic known-bad steps into the stream its monitors see and comparing the reports it gets back. Paraphrasing is the same seam, transforming `step` before the call. Because protocols nest, either can be dropped between a budget-owning protocol and its leaf monitors without that protocol knowing they exist.

## Registration

`@monitor` decorates a factory that returns the monitor, exactly as `@approver`, `@scorer`, `@solver` and `@tool` do. Every registry decorator in Inspect is factory-based, and a dual form for monitors alone would be the odd one out — worse, it would make the use site inconsistent, since a bare monitor would be listed as `no_curl` while a configured one is listed as `suspicion_monitor("openai/gpt-4o-mini")`. The zero-config case pays one nested `def` for that uniformity:

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
    Callable[[Context, BeforeGenerate], Awaitable[Report | None]]
    | Callable[[Context, AfterGenerate], Awaitable[Report | None]]
    | Callable[[Context, BeforeToolCall], Awaitable[Report | None]]
    | Callable[[Context, AfterToolCall], Awaitable[Report | None]]
    | Callable[[Context, Step], Awaitable[Report | None]]
)
```

The last variant is what a [protocol](#protocols-are-monitors) annotates — `Step` being the widest union, and therefore a registration at all four points.

Registry params come from the factory signature, so `registry_create("monitor", "suspicion_monitor", model="openai/gpt-4o-mini")` and the params recorded in the log work as they do for every other registry type. Note what is *not* a parameter here: a threshold. A factory taking `threshold=0.8` would be the anti-pattern [Two kinds](#two-kinds-and-how-to-choose) warns about, wearing configuration as a disguise. The new `RegistryType` value is `"monitor"`.

#### Bare names inside the package, prefixed names outside it

`Context`, `Report`, `Action` and `Host` carry no `Monitor` prefix. The package name already supplies it — `MonitorContext` stutters as `monitor.MonitorContext` — and this is the local convention rather than a departure from it: `inspect_scout` exports `Result`, `Error` and `Reference` unprefixed from its scanner module, and Inspect's own public vocabulary is `Score`, `Target`, `Store`, `Approval`, `Task`. The payload types were already bare, so the prefixed names were the inconsistent ones.

The line is namespace, not importance: **a type living in the monitor package goes bare; a type living in a shared namespace keeps the prefix.** Hence `MonitorEvent` stays `MonitorEvent` — it belongs to `inspect_ai.event` beside `ToolEvent`, `ModelEvent` and `ApprovalEvent`, where the prefix is the discriminator and a bare `Event` is already taken.

A user with their own `Context` is served by `import as`, which is the ordinary cost of short names and the reason the rule stops at the package boundary.

### The stage comes from the annotation {#the-stage-comes-from-the-annotation}

There is no `on=` or `stage=` argument. The type of the second parameter is the declaration, and it is required.

This is the `@tool` contract, not a new idea: `tool/_tool_info.py:118` calls `get_type_hints(func)` and builds the entire `ToolInfo` — name, description, parameter schema — from annotations, with no override and no second spelling. Requiring the payload type is the same move, and it is consistent with the house rule that every function carries annotations.

A string alternative (`@monitor(on="tool_call")`) was rejected for the reason any parallel vocabulary is: it can disagree with the annotation, and then something has to adjudicate. A type-valued one (`on=BeforeToolCall`) merely restates what is already there.

Deduction runs when the factory is called — that is, at configuration time, which is when the decorator first holds the returned callable. `@scorer` already works this way: `scorer_wrapper` invokes `scorer_type(*args, **kwargs)` and then inspects the result (checking `is_callable_coroutine`) before tagging it. So this needs no new machinery, and the error arrives when the monitor is configured rather than at first dispatch.

**The one failure mode is real and already documented in this tree.** `_control/eval_state.py:40-45` spells it out: under PEP 563 (`from __future__ import annotations`) every annotation is a string, and `get_type_hints()` fails outside a type-checking context. Our audience — people minimizing import weight — is precisely who would import `BeforeToolCall` under `TYPE_CHECKING`. The mitigation is not an override to escape to, it is an error that names the fix:

> `suspicion_monitor`: could not resolve the annotation `BeforeToolCall` on parameter `step`. Import it at runtime rather than under `TYPE_CHECKING`.

Open: whether a union annotation (`BeforeToolCall | AfterToolCall`) registers the function at both points, or is an error.

### The kind comes from the return annotation {#the-kind-comes-from-the-return-annotation}

The same mechanism, read on the way out. The parameter annotation says *where* a monitor runs; the return annotation says *what it emits*:

``` python
async def judge(context: Context, step: BeforeToolCall) -> Observation | None: ...
async def no_curl(context: Context, step: BeforeToolCall) -> Recommendation | None: ...
```

A `@monitor(kind="scorer")` argument was rejected for the reason `on=` was: a second vocabulary that can contradict what the function actually returns, needing something to adjudicate. A return type cannot disagree with itself.

Leaving it implicit — inferring the kind from which fields a report happens to set — was also rejected, and this is the sharper argument. It makes the kind a property of a *report* rather than of a *monitor*, so the same monitor could score on one call and recommend on the next, and nothing could be said at configuration time. A declared kind buys two things that needs:

- **The config-time check gets specific.** Today's warning is "this protocol will record recommendations and not act on them". With kinds it can say "`trusted_monitoring` thresholds scores, but `no_curl` is a `Recommendation` monitor — its recommendation is honoured directly, not calibrated."
- **Emitting both becomes unrepresentable.** The old prose rule — a monitor doing both "is taking policy into its own hands" — was discouragement. Two types make it a type error, and this is the bigger win: a monitor that emits a score *and* an action has already thresholded internally, so the protocol cannot tell which half to trust and the calibration never happens.

### One function, one point {#one-function-one-point}

An earlier draft made `Monitor` a class with four overridable methods. Dropping it was the right call, and the deciding argument is empirical rather than aesthetic: **monitors watching more than one point are rare.**

- All four motivating cases in [Goal](#goal) are single-point.
- The obvious two-point candidate — correlate a call with its result — collapses to one `AfterToolCall`, because that payload already carries `call`, `result`, `output`, `view` and `history`.
- Both shipped designs surveyed in [Prior art](#prior-art) agree: OpenAI's Agents SDK registers guardrails individually, and Claude Code hooks are per-event with no grouping construct at all.

So there is no grouping mechanism, and deliberately so. A concern spanning two points is two monitors, listed twice. Two alternatives were considered and rejected:

- **A name convention** (`suspicion_on_tool_call`, selected as `suspicion_*`) encodes in the identifier what the annotation already says, so the two can disagree and a consistency check has to adjudicate. Nothing in Inspect's registry parses names for structure today; names are explicit, never meaningful.
- **Glob selection over registry names** solves a problem that only exists if grouping does. Selection is an explicit list, like scorers. If listing gets tedious a package exports one — `monitors=acme.all_monitors()` — which needs no framework concept.

### What the function shape buys

Beyond removing a base class from the surface:

- **Each monitor's stage and portability are legible per function**, not per class. A class with one portable method and one unportable one is an all-or-nothing verdict; a function is its own verdict. `monitor-deployment.md` builds on this.
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

The one case that looks like it needs a global — a scorer reading what a monitor accumulated — does not. The monitor's per-sample state *is* in the sample store, namespaced by monitor name, so a scorer holding a `TaskState` reads it with the existing `store_as(TrajectoryState, instance=...)`. The only thing a monitor-specific global would add is not having to name the instance, which is exactly what makes it ambient and unportable.

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

**Concurrency.** Samples share one event loop and interleave at every `await`. A single `Store` operation is atomic under the GIL and no lock is warranted (per AGENTS.md), but a read-modify-write spanning an `await` is a real race:

``` python
count = state.terminated          # read
await self._classify(...)         # another sample runs here
state.terminated = count + 1      # write clobbers
```

Per-sample state never had this problem because each sample owns its store. Task state needs either a documented "don't do that" or an atomic helper.

**Persistence.** In-memory only is the simple answer, and it means task state starts empty on `eval_retry` and on eval-set resume — so a monitor that gates on a cross-sample total behaves differently on a resumed run than on a fresh one. Writing it somewhere durable means picking a home (`EvalSpec.metadata`? a new `EvalLog` field? a task-level event stream, which doesn't exist) and deciding when it's flushed.

**Scope.** "Task" is right for cross-sample aggregation within one task. It is the wrong scope for anything that wants to span an `eval()` over several tasks, and for `eval_set`. Whether there's a third scope, or whether the task scope is really a run scope, is open.

## Configuration

Mirroring approval:

``` python
Task(monitor=...)
eval(monitor=...)
inspect eval task.py --monitor monitors.yaml
```

The flat case is a list, like approval:

``` yaml
monitors:
  - name: no_curl
  - name: no_rm_rf
    tools: ["bash", "python"]
```

Because [protocols are monitors](#protocols-are-monitors), the configured case nests:

``` yaml
monitors:
  - name: trusted_monitoring
    params:
      audit_budget: 0.01
      defer_threshold: 0.8
    monitors:
      - name: suspicion_monitor
        params:
          model: openai/gpt-4o-mini
      - name: no_curl
```

**This nesting is the real cost of the collapse**, and it is the one place a separate registry type would have read better — `monitors:` plus a sibling `protocol:` key is flatter and more declarative than a tree. Three things make it acceptable rather than merely survivable: `Task(solver=chain(...))` already has this shape in Python, approval's config already nests policies, and the tree is what actually permits [nested pipeline stages](#the-extension-surface), which a two-key schema could not express at all.

What the schema must not do is let `monitors:` under a leaf monitor parse silently. A monitor that takes no monitors and is handed some is a configuration error, and it is only catchable at config time because the factory signature is introspectable.

`tools` is a wart. It scopes the tool stages the way `ApprovalPolicy` does, but a `BeforeGenerate` monitor is not tool-scoped and would fire regardless — so the key means "which tools this applies to, if it watches a tool point at all", not "when this monitor runs". Alternatives: a separate `stages:` key, or no globs at all (the monitor filters internally on `step.call.function`, which it can already do and which is more honest about the fact that a monitor is not a per-tool policy).

## Composition {#composition}

Composition is the protocol's job: it collects reports from every configured monitor and produces one outcome. Approval's ordered chain — first non-`escalate` decides, later approvers never see the call — is right for an authorisation chain and wrong for a set of observers.

- **Observation is unconditional.** Every monitor configured for a point runs at it, whether or not another has already formed a view.
- **Every report is recorded**, including the ones that lost.
- **Reports combine in two halves**, one per kind.

**Aggregating suspicion.** `Observation`s from several monitors have to combine before thresholding. Max is the obvious default; per-dimension max is the right shape when scores are structured, since dimensions are meant to be independent (see [Prior art](#prior-art)). Weighted combinations and requiring agreement across monitors are protocol policy, not framework behavior.

**Aggregating recommendations.** Across `Recommendation`s, the strongest wins: `terminate` \> `reject` \> `modify` \> `continue`. `escalate` means "I decline to decide", and all-escalate is `continue`. One `Action` ordering covers all four stages, so this is a single comparison function rather than one per stage. Claude Code hooks land the same way — all hooks run in parallel, any `deny` blocks.

Then the protocol reconciles the two halves with its thresholds and budget, subject to [recommendations being advisory](#recommendations-are-advisory).

### Concurrency is a safety property, not just a latency one

Three LLM monitors in sequence triple the added latency at every step, which argues for `tg_collect()` (not `asyncio.gather`, per AGENTS.md). TraceGuard gives a stronger reason: **independence is the point**. Its 95%-versus-0% result against a colluding monitor comes from fragmenting evaluation so no single model sees the whole assessment, which requires monitors that cannot observe each other's conclusions.

So concurrent dispatch is the default, and the cost is that `modify` becomes incoherent — a concurrent monitor cannot see another's rewrite. Options: allow at most one modifying monitor per configuration (simplest and probably right), make it last-wins in protocol order, or make two modifications an error.

### A second axis: concurrent with the *agent*

Separately from monitors running concurrently with each other, a monitor can run concurrently with the agent rather than blocking it — the OpenAI Agents SDK's `run_in_parallel`. Blocking costs latency; running in parallel means the agent may consume tokens, or take a step, before a violation is caught.

This is a real knob and it belongs on the protocol, not the monitor: whether late detection is acceptable is a deployment judgement.

## Transcript

``` python
class MonitorEvent(BaseEvent):
    event: Literal["monitor"] = "monitor"
    monitor: str
    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    kind: Literal["observation", "recommendation"]
    suspicion: Suspicion | None
    recommend: Action | None
    audit: bool
    outcome: Action | None
    explanation: str | None
    metadata: dict[str, Any] | None
```

`recommend` versus `outcome` is the layering made legible in the log: what the monitor advised, and what the protocol did. Without both, a reader cannot tell an ignored recommendation from one that was never made — which is exactly what a reader of an observe-only run needs to see.

Since [protocols are monitors](#protocols-are-monitors), a nested configuration emits **one `MonitorEvent` per layer**, and that is what makes the layering readable without any further field:

```
monitor="suspicion_monitor",  kind="observation",     suspicion=0.87
monitor="defer_to_trusted",   kind="recommendation",  recommend="modify"
```

An earlier draft added a `strategy: str` here and on `Recommendation`, to record whether a `modify` came from a deferral, a resample or a trusted edit. It was removed: **the layer's identity already is the strategy.** A protocol named `defer_to_trusted` returning `modify` has said what it did, and the aggregate query that justified the field — how often did this protocol defer — is `monitor == "defer_to_trusted" and recommend == "modify"`. Worse, on `Recommendation` it was a field every leaf monitor carried and never set.

The residual case is a protocol that genuinely takes several different actions — Ctrl-Z choosing between deferral and audit on two thresholds over one score, where `monitor` does not disambiguate. Two answers in order of preference: compose it, which [the collapse now permits](#protocols-are-monitors), or put it in `metadata`, which already exists and needs no new contract on a serialized type.

`kind` and `stage` are both fine on an event, which is a record, in a way they are not on a protocol, which is a contract. The event stays one flat type across both kinds and all four stages — it is what the renderer, the dataframe and the log schema read, and splitting it would push a union into `generated.ts` for no reader's benefit.

`recommend` and `outcome` are typed rather than stringly typed only because the four stages share `Action`. With per-stage vocabularies the field would have to be a union of three Literals correlated with `stage`, which neither the JSON schema nor the generated TypeScript can express as a correlation — so consumers would get `string`.

The event should be emitted for observations as well as interventions. A monitor that scores every step and intervenes twice in a hundred samples is the common case, and the ninety-eight quiet steps are the interesting data — they are also the benign distribution a protocol's thresholds are calibrated against, so recording them is load-bearing rather than merely nice.

Open: whether `MonitorEvent` replaces `ApprovalEvent`/`ReviewEvent` when the report came from a monitor, or sits alongside them (two events for one outcome), or whether those events gain a `monitor` field.

## Inference, budget, and injection {#inference-budget-and-injection}

- **Budget.** Monitor inference must not be charged to the agent's limits, the same exemption approvers get today (`suspend_token_limit()`, `suspend_turn_limit()` in `approval/_apply.py`). A monitor that terminates a sample for exceeding a token limit its own inference consumed is a trap worth closing up front.
- **Model role.** `get_model(role="monitor")` is the natural default, and `"monitor"` is already the example role name in `docs/models.qmd`. Monitor usage should be separable from agent usage in `ModelUsage`.
- **Injection.** A monitor reads model completions, tool arguments, and tool output, all of which are agent-controlled text. `docs/control-channel.qmd` already makes this point for monitoring agents reading the control channel; it applies with more force here, because this monitor's output decides whether the sample stops. Worth a docs section, and worth thinking about whether the framework should structurally help (for example by defaulting to delivering tool output to the monitor in a delimited, clearly-untrusted envelope) rather than only warning.

## Deployment beyond the eval process

A monitor is useful outside an eval — enforced at a network boundary in front of a model API, where the agent cannot bypass it and the coverage is all agent traffic rather than one task's samples. `monitor-deployment.md` works that through. Four constraints from it bear on the protocol itself, so they are recorded here:

- **Two of the four stages are the portable core.** A proxy sees a request and a response; it never sees a tool execute. `BeforeGenerate` and `AfterGenerate` map directly; `BeforeToolCall` is recoverable from `tool_use` blocks in the response; `AfterToolCall` is **lossy** — a result appears only in the *next* request, so the last step of an episode is never seen. That is verbatim the limitation #5355 wrote `Reviewer` to escape, and `AfterToolCall` should say so rather than let it be discovered.

- **`terminate` travels, as an effect rather than an edit.** Every other action is an edit to the exchange — `continue` is no edit, `modify` a rewrite, `reject` an append-and-regenerate, `escalate` a hand-off down the chain. `terminate` is different in kind, but a proxy can still perform it: an error response ends the exchange and a `host.terminate()` call ends the session out-of-band, the same shape `bridge.request_terminate()` already uses in-process. What does not cross is the *guarantee* — an eval's terminate is total and synchronous, a proxy's is best-effort and may be unsupported. So there is no `PortableAction` subset; there is a capability a host may or may not provide.

  Worth keeping distinct from `reject`, which the deployment doc previously blurred: `reject` is conversational (append a synthetic result, regenerate, the model learns), an error response is transport-level (the SDK raises, the loop breaks). A proxy can do both, and they are not degrees of the same thing.

- **State must arrive as an argument.** `context.store_as(...)` survives any deployment; an ambient accessor would not, because a proxy has nothing to bind to. There is deliberately no global counterpart — see [One access path, not two](#one-access-path-not-two).

- **`view` and the untruncated `output` must be optional.** A proxy has wire types, not registered `ToolDef`s, so there is no viewer to resolve.

- **Portability has two axes, and one of them is the module.** Whether a monitor *can* run in a proxy is per-function — which context members it touches, whether it recommends `terminate`. Whether it can be *bundled* is per-module, because the import closure is a module property: one `import requests` at the top of a file disqualifies every monitor in it, whatever the functions do. This is why monitors being top-level functions matters beyond tidiness — it is what lets a bundler enumerate a file statically, with `ast` and no imports.

A fifth constraint is a design decision rather than a restriction: **monitors should be incremental by default** — classify the newest turn and fold the verdict into accumulated state, rather than re-judging the whole trajectory. Three independent arguments converge on it (quadratic inference cost, linear deserialization cost, and WASM linear memory that never shrinks), which is enough to treat it as load-bearing rather than an optimization.

The types a monitor works with also want to be importable without the eval framework; `inspect-core.md` measures what that costs today and what it would take.

## Relationship to approval and review

Two ways to fit `Monitor` next to `Approver` and the `Reviewer` proposed in #5356.

**A. Monitor as a façade.** `Approver` and `Reviewer` stay as they are. `@monitor` is a new registry type whose `BeforeToolCall` monitors are adapted into `Approver`s and whose `AfterToolCall` monitors are adapted into `Reviewer`s, both slotted into the existing policy chains. The genuinely new code is the two generate stages, the state model, and the composition rules.

- Nothing existing breaks; #5356 lands on its own terms and is not blocked.
- Cost: `Report` has to be adapted to `Approval` and `Review` at the boundary (field-for-field, plus mapping `continue` to `approve`), and, depending on the transcript answer, possibly two events per decision.

**B. Monitor as the primitive.** `Monitor` subsumes both. `@approver` and `@reviewer` become thin wrappers, or `@reviewer` is never introduced and #5356's post-execution hook ships as an `AfterToolCall` monitor.

- One concept, one event, one decision vocabulary, one config key.
- Cost: it makes #5356 a prerequisite negotiation rather than a merge, and it turns on whether `@approver` should survive as a first-class concept.

**Two later decisions moved this fork, both toward B.**

The function shape removed the ergonomic argument. Under the class design, A's advantage was that a single-purpose approver stayed a single function while B forced it into a class with three no-op methods. With monitors as annotated functions that difference is gone — a `BeforeToolCall` monitor and an `Approver` are the same shape.

[Two philosophies](#two-philosophies-both-first-class) then removed most of what was left. A `Recommendation` monitor with no protocol configured *is* an approver: it decides, its decision is honoured, nothing calibrates it. The remaining gap is narrow and nameable — `Approval` is authoritative where a `Recommendation` is overridable by a protocol that happens to be configured — which is a difference in what a protocol may do to it, not in what the monitor is.

So the fork now turns on #5356's timing and on whether that authoritative/advisory distinction deserves its own type, rather than on the floor for the simple case. Worth stating the cost of B plainly all the same: it would deprecate a concept people have working code against, to gain uniformity they did not ask for.

The fork matters now because #5356 is open. Under A it merges unchanged.

### A protocol layer for approval too

The façade leaves a thin spot: approvers are authoritative today, so a monitor adapted into the approval chain effectively runs under an honour-everything protocol while a configured monitor runs under a real one. Two layerings for one concept.

`policy_approver()` is already a proto-protocol — it does the chaining, the escalate fall-through and the no-approver-means-reject default. It just isn't configurable, and approver decisions map straight to effects.

**Make a protocol a peer of the policy list, not a layer beneath it.** Both compile down to an `Approver` that `apply_tool_approval` calls:

``` python
Task(approval=[ApprovalPolicy(...)])                       # today, unchanged
Task(approval=trusted_monitoring(..., audit_budget=0.01))  # protocol-mediated
```

Existing behavior doesn't change — the list form keeps its current code path — and the protocol form does more inside the same slot. That avoids routing every shipped eval through new decision-making code, which is the version of this that would carry real risk.

It also gives the framing that dissolves the thin spot without a semantic change: **the `ApprovalPolicy` list is shorthand for an honour-everything protocol.** The layering is then uniform conceptually even where the code path stays direct.

Three constraints:

- **Human approvers stay authoritative.** Same rule as [Recommendations are advisory](#recommendations-are-advisory): a protocol may override advisory reports, never authoritative decisions. A threshold overriding a human rejection would be a safety regression.
- **Don't grow `Approval` with a score field.** A protocol can consume both shapes — decisions from approvers, reports from monitors — and an approver that wants to score should be a monitor. `Approval` reaches the transcript, the log schema, the viewer and the dataframe, and AGENTS.md wants every producer and consumer named before one of those changes.
- **Probably a separate PR.** This is the same concept rather than a tangential fix, so it is defensible — but it turns "add a Monitor registry type" into "add a Monitor registry type and introduce a protocol layer to approval". The protocol layer could land first, as an additive alternative to the policy list, with monitors arriving into a slot that already exists.

The win is not tidiness. Someone running an LLM approver today has no way to express "reject only the top 1% most suspicious" — the threshold has to be baked inside the approver, where it cannot be calibrated against a benign distribution or traded against a budget. A protocol layer fixes that for approval users whether or not they ever write a monitor.

## Keeping it simple {#keeping-it-simple}

The prior-art pass added a lot of vocabulary. Most of it must stay invisible to someone who just wants to flag suspicious `bash` calls.

**The complexity lives in the protocol, and most people never need one.** Per [Two philosophies](#two-philosophies-both-first-class) a protocol exists to turn scores into a recommendation, so a `Recommendation` monitor needs none — the common monitor is one annotated function returning `recommend="reject"`, and it never encounters thresholds, budgets, or the word "audit".

That gives two on-ramps rather than one ladder, and they rarely cross:

- **"Block bad tool calls."** A `Recommendation` monitor, no protocol. This is the `@approver` experience with a wider set of points to attach to. Done.
- **"Run a control experiment."** An `Observation` monitor, a protocol, calibration against a benign distribution.

The bridge between them is the tell from [Two kinds](#two-kinds-and-how-to-choose): the moment your check computes a score and compares it to a constant, you have discovered why the second on-ramp exists. That is when the control vocabulary should first appear, and not before.

The concrete mitigations, in order of how much they do:

1.  **Push everything possible up.** Applying the monitor/protocol split removed `defer`, `resample`, `audit`-as-an-action, `trusted_edit`, honeypots, paraphrasing and multi-sample payloads from the monitor surface. That is a real reduction, not a presentation trick. Apply the same test to anything added later.
2.  [**Progressive disclosure through defaults**](#progressive-disclosure-through-defaults-not-through-the-return-type) — a scorer sets `suspicion` and ignores every other field, and never learns what `audit` or `modified` do until it needs them.
3.  [**Ship protocols, not parts**](#ship-protocols-not-parts) — pick from a list instead of assembling thresholds and budgets.
4.  [**Kind-appropriate defaults**](#observe-only-is-the-default) — zero configuration does something sensible either way: a `Recommendation` monitor acts, an `Observation` monitor records.
5.  **Two words, kept crisp — as roles, not types.** *Monitor* looks at one thing and says how suspicious it is. *Protocol* turns suspicion into a recommendation under a budget. That they are [the same type](#protocols-are-monitors) is an implementation fact a first-time author never needs. The failure mode is a doc explaining audit budgets inside "how to write your first monitor" — keep that page free of the control vocabulary entirely.
6.  [**Exotica goes in extensions**](#the-extension-surface), per AGENTS.md's default.

**One vocabulary.** An earlier draft kept two — `Action` for the monitor layer and the control literature's `accept` / `audit` / `defer` / `resample` / `trusted_edit` for the protocol layer — on the theory that the word would signal which layer you were in. [The collapse](#protocols-are-monitors) removed the two layers that theory rested on:

| Control term | Where it lives now |
|------------------------|------------------------|
| `accept` | `Action.continue` — the same thing |
| `audit` | `Recommendation.audit`, a flag; [a second axis, not a peer action](#audit-is-a-flag-not-an-action) |
| `defer_to_trusted` | a protocol name; it returns `modify` |
| `trusted_editing` | a protocol name; it returns `modify` |
| `resample` | a protocol name; it returns `modify` or `continue` |

**The literature's terms name mechanisms; ours name outcomes.** Several mechanisms produce one outcome — deferral, resampling and trusted editing all end in a `modify` — so a mechanism can never replace an outcome, and the two word-lists do not merge. `accept` is the one exception, and it *is* `continue`.

That is also why the control terms need no home in the data at all: **they are protocol names, and nothing else.** The papers' words survive where someone would search for them, the transcript records which protocol acted, and an author never learns a second vocabulary in order to return a value.

Three near-synonyms this settles, all of which look mergeable and are not:

- **`defer` is not `escalate`.** `escalate` passes the *decision* to the next decider and leaves the action alone; `defer_to_trusted` passes the *action* to a weaker model and leaves the decision made. Spelling it `defer_to_trusted` rather than `defer` matters, because bare "defer" reads in English as "postpone, hand off" — which is precisely `escalate`.
- **`trusted_edit` is not `modify`.** It is one way to produce a modification. A leaf monitor stripping `--force` from a call produces another, with no trusted model involved.
- **`reject` is not `block`.** Ours has specific mechanics from `_bridge/_approval.py` — append the rejected call and a synthetic result, regenerate, bounded by a retry limit, so the model learns it was denied. Control's `block` means the action does not execute and the protocol substitutes or escalates.

**Rejected: core executes the control actions.** There is one coherent design in which `defer` and `resample` *are* legal return values — a protocol returns `defer` and the *framework* calls the trusted model and substitutes. That is the only version where the mechanism/outcome distinction collapses, because core would be the thing turning a mechanism into an outcome.

It is rejected on scope. Core would have to know about trusted models, resampling and budget arithmetic; every new technique would become a core change rather than an extension; and `run_monitors` would stop being the only seam. AGENTS.md's default — new functionality is an extension, not core — points the other way, and [the extension surface](#the-extension-surface) is worth more than the vocabulary.

**`continue` rather than `accept`**, and the collapse strengthens this rather than weakening it. A leaf monitor that scored 0.3 did not authorise anything, it declined to object; an outermost protocol returning the same value *is* authorising. One word now has to be accurate at both positions, and `continue` is — it describes what happens to the exchange rather than claiming an authority that, per [Two philosophies](#two-philosophies-both-first-class), the configuration confers rather than the monitor. `accept` is accurate only at the outermost position. This also settles #5356's open question the same way, and leaves the `Approval` adapter mapping `continue → approve` at the boundary, which it already had to do.

## Open questions

1.  **Façade or primitive** — `Monitor` as a façade over `Approver`/`Reviewer`, or the primitive that replaces them. The function shape removed the ergonomic argument that previously favoured the façade, so this is genuinely open again.
2.  **Does the protocol layer land first?** It is useful to approval users on its own, and monitors then arrive into a slot that already exists. It also makes each change reviewable separately.
3.  **Who owns the budget when protocols nest?** [Protocols are monitors](#protocols-are-monitors), so a budget-owning protocol can wrap a paraphrasing one wrapping leaf monitors — which is the point, but two nested budget-owning protocols need a rule. Outermost wins is the obvious answer; whether an inner one should be an error is open.
4.  **Which protocols ship in core?** `observe_only` and something like `trusted_monitoring` seem clear. `defer_to_trusted`, `resample` and the collusion-resistant variants are candidates for an extension package.
5.  **Score aggregation.** Max across monitors is the obvious default; per-dimension max when scores are structured. Weighted combination and requiring agreement are protocol policy — but the framework has to pick a default and say so.
6.  **Where does threshold calibration get its benign distribution?** Ctrl-Z calibrates against known-benign runs. In an eval that could be a warm-up pass, a prior run's transcripts, or a static configuration. This is the least-specified part of the protocol layer.
7.  **Audit budget is the first concrete consumer of per-task state.** Is that state in-memory for v1, with the resume asymmetry that implies? Does its scope want to be task, run, or eval-set?
8.  **Does a `modify` compose?** Concurrent dispatch makes two rewrites incoherent. At most one modifying monitor per configuration is the simplest answer; last-wins in protocol order and "two is an error" are the alternatives.
9.  **What `modified` carries at the generate points.** At `BeforeToolCall` it is a `ToolCall`; a generate rewrite is three things (messages, tools, config). Either input rewriting is in-place mutation of the payload — what `Hooks.on_before_model_generate` does today — or `modify` becomes an attachment rather than a recommendation. This is now load-bearing rather than cosmetic: **resampling and trusted editing both require substituting a whole `ModelOutput`**, so until it is answered, two of the five control-literature actions are not expressible.
10. **Does the monitor see `ContentReasoning`?** The CoT-monitorability literature says reasoning is a distinct signal and TraceGuard scores it as its own dimension. Defaulting it visible seems right; the question is whether a protocol should be able to withhold it.
11. **`Report` versus `Decision`.** `Report` encodes the layering in the API — a monitor reports, a protocol decides — at the cost of being the less obvious word. The naming is settled; the semantic question it encodes is what is still open, and it is the same fork as [Recommendations are advisory](#recommendations-are-advisory).
12. **Lifecycle stages**: `SampleStart` / `SampleEnd` payloads would give per-sample state a place to initialise and a monitor a place to file a final verdict on a trajectory it watched but never interrupted. Natural, and cheap now that adding a stage means adding a payload type rather than a method to a base class — but it starts to overlap `Hooks`, and neither travels to a proxy.
13. **Can a monitor produce a `Score`?** A suspicion score over a trajectory is a metric people want beside the task's own scores. If yes, this touches scoring rather than only the agent loop, and the scope grows considerably.
14. **Bridged agents.** An agent that runs its own tool loop (`claude_code`, `codex`) never reaches `execute_tools()`, so `BeforeToolCall` and `AfterToolCall` monitors never fire — the gap #5356 documents for reviewers. The generate stages *do* fire, since bridged agents route through `bridge_generate`. A monitor that silently covers half a bridged agent is worse than one that says so.
15. **Is proxy portability a goal or an observation?** If a goal, the portable core should be the shape the protocol is designed around and the in-process extras visibly additive. See `monitor-deployment.md`.
16. **Does `Task` / `Sample` grow a `description` field?** A public API change for a general-purpose affordance monitors happen to need first. If not, monitor context comes from `metadata` by convention and is correspondingly undiscoverable.
17. **Does a union annotation register two stages?** `step: BeforeToolCall | AfterToolCall` could mean "call me at both", or be rejected as ambiguous. Registering both is the more useful reading and costs nothing structurally; the argument against is that it quietly reintroduces the multi-stage monitor [One function, one point](#one-function-one-point) says is rare.
18. **What happens in a mixed configuration with no protocol?** Recommendations act, scores only record — coherent, and surprising enough to warrant a warning. Whether it should instead be an error, forcing an explicit `observe_only()` or a real protocol, is open.
19. **Failure semantics.** An approver exception ends the sample; a hook exception is swallowed and warned. A monitor is a safety mechanism, so failing closed matches the approver precedent — but that makes a flaky monitor model a source of eval errors. Configurable per monitor, or per protocol?