# Sentinel

A sentinel is what a task runs to watch an agent: a protocol with its monitors, configured with `Task(sentinel=)`. A monitor is a function that watches an agent while it runs and reports what it sees. It attaches to one of four points in the agent loop: before a model call, after a model call, before a tool call, or after a tool call. At every point it receives the same context object and keeps its state in the same place. A monitor observes: it returns an `Observation` or nothing, and can never act. A protocol decides: it returns a `Decision`, optionally after consulting monitors and other protocols. A protocol with no children is a rule.

Status: design sketch. The Python in this document shows the intended shape. It is not a finished API.

Related documents:

- `sentinel-deployment.md` covers running a sentinel outside the eval process, as a proxy between the agent and the model API.
- `sentinel-development.md` covers measuring and calibrating a monitor before it acts, by replaying it over transcripts as an Inspect Scout scanner.
- `inspect-core.md` covers packaging the wire types so a monitor can depend on them without depending on all of Inspect.

Contents:

1. [Overview](#overview)
2. [Writing a monitor](#writing-a-monitor)
3. [Protocols](#protocols)
4. [Configuration](#configuration)
5. [Failures](#failures)
6. [Transcript](#transcript)
7. [Bridged agents and proxies](#bridged-agents-and-proxies)
8. [Relationship to approval and review](#relationship-to-approval-and-review)
9. [Design rationale](#design-rationale)
10. [Background: prior art](#background-prior-art)
11. [Open questions](#open-questions)

## Overview

Examples of monitors people build today:

- An LLM that reads each tool call and stops the sample if the call looks like sabotage or data exfiltration.
- A classifier that reads each tool result and stops the sample if the agent reached the internet (#5355).
- A running suspicion score over a whole trajectory, where no single step is disqualifying but the total is.
- A rule that rewrites or annotates the model's input before each generate, for example "you have used 8 of your 10 allowed commands".

Today each of these is built from a different primitive (`@approver`, `@reviewer`, `Hooks`), and the primitives cannot share state. See [Why one object for four points](#why-one-object-for-four-points).

The smallest protocol is a rule with no monitors:

```python
@protocol
def no_curl() -> ControlProtocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        if step.call.function == "bash" and "curl" in step.call.arguments.get("cmd", ""):
            return Decision.reject("network access is out of bounds")
        return None

    return decide
```

```python
Task(sentinel=no_curl())
```

This runs before every tool call, rejects calls that use `curl`, and returns `None` otherwise. A protocol at the top level acts directly, the same way an approver's decisions are applied today.

The smallest monitor scores, and a protocol decides what the score means:

```python
@monitor
def suspicion_monitor(model: str | None = None) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        ...
        return Observation.score(score, explanation)

    return check
```

```python
Task(sentinel=threshold(suspicion_monitor(), reject_at=0.8))
```

The pieces:

| Piece | What it is |
|---|---|
| Sentinel | The umbrella: the feature, and a configured tree of one protocol with its monitors. `Task(sentinel=)`, `SentinelEvent`, `inspect_ai.sentinel`. |
| `@monitor` | Registry decorator on a factory that returns a monitor function. A monitor observes and returns `Observation \| None`. Registry type `"monitor"`. |
| `@protocol` | Registry decorator on a factory that returns a protocol function. A protocol decides and returns `Decision \| None`. It may take monitors or other protocols as children, or none. Registry type `"protocol"`. |
| `Context` | The first argument. What the agent was asked to do, the caller's own state, and its route to inference and other effects. Constant for a sample. |
| `BeforeGenerate`, `AfterGenerate`, `BeforeToolCall`, `AfterToolCall` | The second argument. Which one you annotate selects the stage. |
| `Observation` | A monitor's report: a suspicion score and an explanation. Recorded; acted on only by a protocol. |
| `Decision` | A protocol's report: an action (`continue`, `modify`, `reject`, `terminate`, `escalate`). Applied at the top level; advisory to a parent protocol. |
| Rule | A protocol with no children. `no_curl`, `strip_force`, and `human` are rules. |
| `run_monitors`, `run_protocols`, `run_children` | The runner. The only way a protocol invokes a child. Names, records, and applies the failure policy. |
| `concurrent`, `chain` | The two shipped compositions: concurrent (every child runs, strongest decision wins) and ordered (first non-`escalate` decides). |
| `threshold`, `observe`, `defer_to_trusted`, `resample` | The shipped protocols that turn monitors' scores into decisions. |
| `human` | A rule that asks a person through the human approval surfaces. Its decisions are authoritative. |
| `SentinelEvent` | Transcript record of every report, keyed by instance path. |

## Writing a monitor

### Signature

```python
@monitor
def suspicion_monitor(model: str | Model | None = None, dimensions: list[str] | None = None) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        ...

    return check
```

Rules:

- **Decorate a factory, not the monitor itself.** The factory's parameters become registry params, recorded in the log and settable from config. This is how `@approver`, `@scorer`, `@solver`, and `@tool` work.
- **Annotate `step` with exactly one payload type.** That annotation is the stage declaration. There is no `on=` or `stage=` argument. Import the payload type at runtime, not under `TYPE_CHECKING`, or the framework cannot resolve it. The error tells you this:

  > `suspicion_monitor`: could not resolve the annotation `BeforeToolCall` on parameter `step`. Import it at runtime rather than under `TYPE_CHECKING`.

- **Annotate the return as `Observation | None`.** A monitor observes. If you find yourself wanting to return an action, you are writing a protocol; see [Monitor or protocol?](#monitor-or-protocol).
- **One function, one stage.** If a concern spans two stages, write two monitors and list both.
- **Never take a threshold as a factory parameter.** If your monitor compares a score to a constant, return the score as an `Observation` and let a protocol hold the constant. See [Monitor or protocol?](#monitor-or-protocol).
- **Do not keep per-sample state in the closure.** The factory runs once per configuration and the returned function is shared by every sample. Use `context.store_as()`. See [State](#state).

The `Monitor` type is an alias for the returned callable, one variant per payload:

```python
Monitor: TypeAlias = (
    Callable[[Context, BeforeGenerate], Awaitable[Observation | None]]
    | Callable[[Context, AfterGenerate], Awaitable[Observation | None]]
    | Callable[[Context, BeforeToolCall], Awaitable[Observation | None]]
    | Callable[[Context, AfterToolCall], Awaitable[Observation | None]]
)
```

The stage is checked by mypy and pyright against this alias, and read from the annotation when the factory is called, at configuration time. Errors surface then, not at first dispatch. See [Static checking](#static-checking). The new `RegistryType` values are `"monitor"` and `"protocol"`. Names in the sentinel package are unprefixed (`Context`, `Report`, `Action`, `Host`); `SentinelEvent` keeps its prefix because it lives in `inspect_ai.event` beside `ToolEvent` and `ModelEvent`.

### Instance names

Every configured monitor or protocol has an instance name: the key when it was configured in a mapping, the registry name otherwise. Two children of one layer with the same name is a configuration error. Nesting joins names into a path, `attempt/internet_attempt`. The path is what `SentinelEvent` records and what `context.store_as()` namespaces by.

### Stages

| Payload | Fires |
|---|---|
| `BeforeGenerate` | before each generate, before the cache lookup |
| `AfterGenerate` | after each generate, before the output reaches the agent |
| `BeforeToolCall` | before a tool call executes |
| `AfterToolCall` | after a tool call executes, before the model sees the result |

```python
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
"""The union. Protocols annotate this to run at every stage."""
```

Everything in `step` except `escalations` was written or shaped by the agent under observation and can carry prompt injection. Nothing in `context` came from the agent. Treat `step` as evidence and `context` as instructions.

`escalations` is filled only inside a `chain()`: when an earlier link returns `escalate`, its report is handed to the next link here, so a human at the end sees who is asking and why. It is empty everywhere else. The reports are written by monitors, but their explanations may quote agent text, so label them as prior verdicts if you render them into a prompt.

`BeforeToolCall` and `AfterToolCall` are the `Approver` and `Reviewer` payloads with the same fields. `view` and `output` are optional under a proxy, which has no registered tool definitions to render a view from.

### Context

```python
@dataclass(frozen=True)
class Context:
    """Everything constant for the sample while the step changes."""

    # -- the assignment, constant across a task
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
    """Inference, keyed storage, outbound JSON, and recording. The only route out of a monitor."""

    target: Target | None = None
    """The expected answer. None unless explicitly opted into."""
```

Rules:

- **Use the assignment fields to judge the step.** The same `curl` command is exfiltration in one task and the assigned work in another. A monitor that ignores `task_description` can only flag things that would look bad in any task, and it will produce false positives on tasks that are designed to look bad.
- **Keep context and step separate when you build a prompt.** Put the assignment in a labelled instructions section and the conversation in a labelled evidence section. Do not concatenate them into one block where a tool result can claim to be a revised assignment.
- **Do not read `target` unless the monitor's job requires the answer.** It is absent by default. Request it explicitly, and the log records that you did, so readers can tell whether the monitor's performance is achievable in deployment. Sandbagging detection needs it. An AI control monitor standing in for a deployed one must not have it. See [View](#view).
- **Do not cache the context.** It is passed on every call. Storing it would make the monitor stateful.
- **Use `context.host` for inference and every other outside effect.** Do not call `get_model()` directly. See [Effects](#effects).

How the fields are populated:

| Field | In an eval | In a proxy |
|---|---|---|
| `task` / `task_description` | `Task` name, `Task(description=)` | the deployed agent's identity and charter |
| `sample_id` / `epoch` | sample id, epoch | conversation key (see `sentinel-deployment.md`) |
| `sample_description` | `Sample(description=)` | usually absent |
| `input` | `Sample.input` | the request's system prompt and first user turn |
| `metadata` | task + sample metadata | headers, deployment config |

`Task(description=)` and `Sample(description=)` do not exist yet. They are the proposed home for the assignment text; the fallback is a `metadata` convention. See [Open questions](#open-questions) item 13. Structured context goes in `metadata` either way.

### Reports

```python
Action = Literal["continue", "modify", "reject", "terminate", "escalate"]


class Observation(BaseModel):
    """What a monitor returns: evidence, for a protocol to calibrate and threshold."""

    suspicion: Suspicion
    """Required. float or dict[str, float]."""

    explanation: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class Decision(BaseModel):
    """What a protocol returns. Applied at the top level; advisory to a parent protocol."""

    action: Action
    """Required."""

    audit: bool = Field(default=False)
    """Request that human review be spent on this."""

    authoritative: bool = Field(default=False)
    """A decision no parent protocol may weaken. Set by human()."""

    modified: ToolCall | ChatMessageAssistant | BeforeGenerate | None = Field(default=None)
    """Replacement for the step's subject. Set if and only if action == "modify"."""

    explanation: str | None = Field(default=None)
    """Why. Operator-facing. The model does not see it."""

    metadata: dict[str, Any] | None = Field(default=None)


Report: TypeAlias = Observation | Decision
Suspicion: TypeAlias = float | dict[str, float]
```

Return states:

| Returned by | Return | Meaning | Recorded |
|---|---|---|---|
| either | `None` | abstained; did not take part | no |
| a monitor | `Observation` | examined; here is evidence, no verdict | yes |
| a protocol | `Decision` | examined; here is what should happen | yes |

Rules:

- **Return `None` to abstain.** A bare `return` from an early exit does this. This document says "abstain" for this case so it is not confused with a `suspicion` field that is `None`.
- **Set only the fields you need.** Every field except the required one has a default. A monitor sets `suspicion` and nothing else.
- **`continue` means the protocol examined the step and found nothing wrong.** An `Observation` has no `action` field, so a monitor never says it.
- **`escalate` means the protocol is not deciding.** The next decider in the chain takes over. If every link escalates, the outcome is `continue`.
- **Prefer structured suspicion.** `{"goal_alignment": 0.1, "sabotage": 0.8}` lets a protocol threshold per dimension and lets independent monitors score separate dimensions. A scalar is accepted.
- **A detector reports `1.0`.** `Observation.flag(explanation)` is a monitor's way of saying "this is definitely it" without holding a threshold; `threshold(detector(), reject_at=1.0)` acts on it.
- **Set `audit=True` to request human review.** It is independent of the action: you can continue-and-audit or reject-and-audit. A parent protocol owning a budget may decline.
- **Write `explanation` for the operator.** The model does not see it. If the agent learns why it was flagged, it can learn to avoid being flagged. A separate field, not yet named, carries text the model is meant to read. That field also lets a protocol continue while giving the model information.
- **Set `authoritative=True` only for a decision a person made.** A parent protocol may not return anything weaker than an authoritative child decision; the dispatcher raises if it does. `human()` sets it. The framework cannot verify a human was involved, so the claim is visible in the log and in code review, as `portable=False` is.

Named constructors for the common cases:

```python
Observation.score(0.9)                  # suspicion=0.9
Observation.flag("definite match")      # suspicion=1.0
Decision.clear()                        # action="continue"
Decision.reject("why")                  # action="reject"
Decision.terminate("why")
Decision.escalate("why")
```

### Monitor or protocol? {#monitor-or-protocol}

Write a monitor if the function produces evidence and something else should decide the cut-off. Write a protocol if the function decides.

A common mistake is to compute a score and compare it to a constant inside the same function. That constant is a threshold. Under this division the mistake is structural: a monitor cannot act, so it has nothing to threshold for. Return the score and let `threshold()` hold the constant.

| Function | Kind | Report |
|---|---|---|
| LLM judge over a tool call | monitor | `suspicion=0.87` |
| Multi-dimension judge | monitor | `suspicion={"goal_alignment": 0.1, "sabotage": 0.8, ...}` |
| Running trajectory score | monitor | accumulated in the store, reported each step |
| Chain-of-thought monitor | monitor | reasoning scored separately from the action |
| Internet-egress detector | monitor | `Observation.flag(...)`; a protocol decides what a definite match means |
| `no_curl` | protocol (a rule) | `Decision.reject(...)` |
| `rm -rf /` guard | protocol (a rule) | `Decision.reject(...)` |
| Strip `--force` from a call | protocol (a rule) | `action="modify", modified=...` |
| `human()` | protocol (a rule) | whatever the person said, `authoritative=True` |

For a first guard, write a rule. It acts with no further configuration. Write a monitor and wrap it in `threshold()` when the function produces a score, or when you want a deterministic detector to be dry-runnable and backtestable before it acts.

### Actions

Which actions are legal at which stage:

| Stage | continue | terminate | escalate | reject | modify |
|---|---|---|---|---|---|
| `BeforeGenerate` | yes | yes | yes | yes | open |
| `AfterGenerate` | yes | yes | yes | yes | no |
| `BeforeToolCall` | yes | yes | yes | yes | yes |
| `AfterToolCall` | yes | yes | yes | no | no |

What each action does:

| Action | Effect |
|---|---|
| `continue` | no change to the exchange |
| `modify` | replace the step's subject with `modified` |
| `reject` | at `BeforeToolCall`: append the rejected call and a synthetic result, regenerate, bounded by a retry limit. At `BeforeGenerate`: do not run this generate, tell the agent why. At `AfterGenerate`: discard this completion. |
| `terminate` | end the sample |
| `escalate` | pass the decision to the next decider |

`reject` and `modify` are not allowed after a tool result. If a monitor withholds or changes output the tool already produced, the model believes its command failed when it did not, and the model's view of the sandbox no longer matches the sandbox.

What `modified` carries:

| Stage | Subject | `modified` carries |
|---|---|---|
| `BeforeGenerate` | the request | a `BeforeGenerate`, built with `dataclasses.replace(step, input=...)`; `model` unchanged |
| `AfterGenerate` | the assistant message | `ChatMessageAssistant`, not `ModelOutput`. `usage`, `time`, and `model` stay as recorded. Only `choices[0]` is monitored and substitutable. |
| `BeforeToolCall` | the call | `ToolCall` |
| `AfterToolCall` | none | not legal |

Rules:

- **Return a replacement. Never mutate `step`.** The payloads are frozen but their list fields are not. Mutating them works in-process and is invisible to a proxy. Use `dataclasses.replace()`.
- **An illegal action is a bug.** The dispatcher validates the decision against the stage and raises. It does not coerce `reject` into `continue`.
- **`reject` and an error response are different things.** `reject` is conversational: the model sees a synthetic result and regenerates. An error response is transport-level: the SDK raises and the loop breaks. A proxy can do both. See [Bridged agents and proxies](#bridged-agents-and-proxies).

### State

Per-sample state lives in the sample `Store`, namespaced to the monitor so two configured instances of the same monitor do not collide:

```python
class TrajectoryState(StoreModel):
    score: float = Field(default=0.0)
    flags: list[str] = Field(default_factory=list)


async def check(context: Context, step: BeforeToolCall) -> Observation | None:
    state = context.store_as(TrajectoryState)
    ...
```

You get three things for free: the state is recorded to the transcript as `StoreEvent`s, it survives checkpoint and resume, and `store_from_events_as()` reconstructs it from a finished log for analysis. A scorer holding a `TaskState` reads it with `store_as(TrajectoryState, instance=<instance path>)`, for example `instance="attempt/internet_attempt"`.

Per-task state uses `scope="task"`:

```python
class RunTotals(StoreModel):
    terminated: int = Field(default=0)


state = context.store_as(RunTotals, scope="task")
```

Rules:

- **Use `context.store_as()`, not the global `store_as()` and not variables in the closure.** Closure variables are shared across every sample. The global accessor binds to a `ContextVar` a proxy cannot provide.
- **Do not `await` between reading and writing shared task state.** Samples interleave at every `await`. A read-modify-write with no `await` inside it is atomic on Inspect's single event loop thread and needs no lock. The usual critical section (compare score to threshold, check budget, decrement) has no `await` in it; the `await` on the runner happens first.
- **Expect task state to reset on `eval_retry` and eval-set resume.** It is in-memory in v1. For a budget this errs toward more auditing, which is the safe side. A monitor that gates toward less intervention ("terminate once 3 samples are flagged") needs durable state, which does not exist yet.
- **Task scope covers one task.** Nothing spans an `eval()` over several tasks or an `eval_set`.

There is no `monitor_store_as()` or `monitor_host()` global. Helpers take what they need as parameters.

### Effects

`context.host` is the only route out of a monitor: inference, keyed storage, outbound JSON, and recording. `sentinel-deployment.md` defines it. In-process these are ordinary implementations; under a proxy they cross the host boundary.

Rules:

- **Call `context.host.generate()` for inference, never `get_model()`.** It takes a prompt string or a message list, with optional `model` (a name or a role), `tools` and `config`, and returns a `ModelOutput`. The host defaults to `role="monitor"` and records monitor inference separately from the agent's. The `portable=True` check bans `get_model()`.
- **Monitor inference is not charged to the agent's limits.** Approvers get the same exemption today via `suspend_token_limit()` and `suspend_turn_limit()`. Monitor usage is separable from agent usage in `ModelUsage`.
- **Treat model completions, tool arguments, and tool output as untrusted.** The monitor's output decides whether the sample stops, so a successful injection against the monitor can stop a sample or prevent it from being stopped. `monitor_prompt` delivers evidence in a delimited, clearly-untrusted envelope by default; see [View](#view).
- **Classify incrementally.** Judge the newest turn and fold the verdict into stored state rather than re-judging the whole trajectory each step. Re-judging is quadratic in inference cost and linear in deserialization cost, and under WASM the memory never shrinks.

### View

A view is what a monitor is shown and how it is rendered into a prompt. It is not a type. It is a map of the surfaces a step carries in each deployment, plus a family of helper functions, `messages_as_str` and its relatives, that render any subset of them into prompt text with the instruction/evidence boundary intact.

Which surfaces exist where:

| Surface | Eval | Proxy / bridged | Replay | Trust |
|---|---|---|---|---|
| Briefing (`context`) | yes | operator-supplied | from transcript info | instruction |
| The subject: call, assistant message, or request | yes | yes | yes | evidence |
| Tool result as the model saw it | yes | next request only, lossy | yes | evidence |
| Untruncated tool output | yes | no | no | evidence |
| `ToolCallView` | yes | no | from events only | evidence |
| History | yes | yes | yes | evidence |
| Reasoning | provider-dependent | whatever the wire carries | as logged | evidence |
| System prompt | yes | yes, but written by the scaffold under observation | yes | evidence |
| Tool definitions, config | yes | yes | from events only | evidence |
| Media | yes | yes | yes | evidence |
| `target` | yes | never | yes | instruction |

Rules:

- **The system prompt is evidence, not instruction.** In an eval the author wrote it; under a proxy the agent's scaffold did. The briefing in `context` is the only instruction-class input. The helpers exclude the system prompt by default.
- **Reasoning is rendered at whatever fidelity exists.** `<thinking>`, `<thinking_summary>`, or `<thinking_redacted/>`, so the prompt says which. Exclude it in the preprocessor to score actions without it. A protocol withholds it from a child by transforming `step` before the call.
- **A monitor never sees** the sandbox itself, other samples, sibling monitors' reports at the same step, the protocol's thresholds or budget, or whether its own explanation was shown.

The helpers, lowest level first. The first two exist in Scout today and move down to `inspect_sentinel`, with Scout re-exporting them:

| Helper | Does |
|---|---|
| `messages_as_str`, `message_as_str`, `MessagesPreprocessor` | Scout's message rendering: roles, tool calls and results, `<thinking>` blocks, media placeholders; exclusions and a `transform` via the preprocessor |
| `message_numbering()` | `[M1]`-style numbering plus `extract_refs` for citations in explanations |
| `last_turn`, `last_n`, `new_since_last_report` | windows over `step.history`; the last uses the monitor's store so an incremental monitor never re-reads what it already judged |
| `call_as_str(call, view=None)` | the Python-call rendering approvers use, honouring a `ToolCallView` |
| `result_as_str(result, truncated=None)` | a tool result with the truncation point marked |
| `briefing_as_str(context)`, `step_as_str(step, ...)` | the instruction and evidence sections; an absent surface is named in a fixed phrase, not omitted |
| `monitor_prompt(context, step, *, question, answer=...)` | the analogue of Scout's `scanner_prompt`: briefing, delimited evidence envelope, escalations as prior verdicts, the question |

```python
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
        return Observation(suspicion=score, explanation=explanation,
                           metadata={"references": extract_refs(explanation)})

    return check
```

Rules:

- **Use `monitor_prompt` for LLM monitors.** Its default output keeps briefing and evidence in separately labelled sections, wraps evidence in an envelope described as agent-written, and renders escalations as prior verdicts. Do not concatenate context and history yourself.
- **Use `message_numbering` so explanations cite.** References in the explanation resolve to messages, which the transcript and Scout's viewer render.
- **Window history with a helper.** `new_since_last_report` is the incremental shape; full history is the safe one. Whichever you choose is visible in the call.
- **Screenshots need a message-list prompt.** The text helpers render media as placeholders. A monitor that must see an image builds a `list[ChatMessage]` itself, and `Host.generate` has to grow to accept it.

## Protocols

A monitor reports what it sees. A protocol decides what happens.

A protocol is a function that returns a `Decision`. It may consult monitors (`threshold`, `resample`), other protocols (`chain`, `concurrent`), both, or nothing at all (`no_curl`, `human`). Deciding is what makes it a protocol, not having children. Inspect already composes this way in `chain(*solvers) -> Solver`, `multi_scorer(scorers, reducer) -> Scorer`, and `policy_approver(policies) -> Approver`.

A protocol owns:

- thresholds, calibrated against benign score distributions, per dimension where scores are structured
- any audit budget: how much human review remains and how it is allocated across a trajectory
- aggregation of reports from several children
- the control actions: accept, audit, defer to a trusted model, trusted edit, resample
- pipeline stages such as paraphrasing agent output before monitors see it, or injecting honeypot inputs
- its stance toward child protocols' decisions: honour them, or record and override them

All of these depend on information a single monitor does not have: calibration data, remaining budget, or other children's reports. So none of them are values a monitor can return.

### Writing a protocol

The shipped `threshold` protocol, in full:

```python
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

It holds the constants a monitor must not, reads its children's scores through the runner, and returns a decision.

```python
ControlProtocol: TypeAlias = (
    Callable[[Context, Step], Awaitable[Decision | None]]
    | Callable[[Context, BeforeGenerate], Awaitable[Decision | None]]
    | Callable[[Context, AfterGenerate], Awaitable[Decision | None]]
    | Callable[[Context, BeforeToolCall], Awaitable[Decision | None]]
    | Callable[[Context, AfterToolCall], Awaitable[Decision | None]]
)

Monitors: TypeAlias = Mapping[str, Monitor] | Sequence[Monitor]
Protocols: TypeAlias = Mapping[str, ControlProtocol] | Sequence[ControlProtocol]
Children: TypeAlias = Mapping[str, Monitor | ControlProtocol] | Sequence[Monitor | ControlProtocol]

def protocol(factory: Callable[P, ControlProtocol]) -> Callable[P, ControlProtocol]: ...
```

Rules:

- **Decorate with `@protocol`.** It registers under the `"protocol"` registry type. The returned callable must be `Decision`-kind; see [Static checking](#static-checking).
- **Take children as one named parameter, if any.** `monitors: Monitors` for a protocol that reads scores (`threshold`), `children: Children` for a composition (`chain`, `concurrent`). Not `*args`: a mapping is how children get names, and the parameter name is the nested key in YAML. A rule takes no children at all.
- **Annotate the return as `ControlProtocol`.** The name avoids `typing.Protocol`; see [Open questions](#open-questions) item 19.
- **Annotate `step` as `Step`** to run at all four stages. Annotate a single payload to run at one. `threshold` above runs at `BeforeToolCall` so that `reject` is always legal.
- **Return `Decision | None`.** A protocol's job is to produce a decision.
- **Invoke children only through the runner.** `run_monitors()` and `run_protocols()` for concurrent fan-out over one family, `run_children()` for a mixed group, `run_monitor()` and `run_protocol()` for one child at a time. See [The runner](#the-runner). A child called any other way produces no event, and a protocol that decided with no child reports in the transcript is visible in the log.
- **Transform `step` before the call, not after.** Paraphrasing, minification, and honeypot injection are transforms on the input to the runner.
- **Never return something weaker than an authoritative child decision.** The dispatcher raises if you do. See [The boundary check](#the-boundary-check).
- **Protocols can nest.** A budget-owning protocol can wrap a paraphrasing protocol that wraps monitors. The rule for two nested budget owners is open; outermost wins is the likely answer.
- **Everything else is ordinary Python** over the runner's results plus `context.store_as`. Thresholds, budget arithmetic, deferral to a trusted model via `context.host.generate()`, and aggregation need no framework support.

`@protocol` does not invoke the children for you. A draft that did (`protocol(monitors, decide=...)`) could not express a chain, because a chain decides between links rather than after them, and it had to add a `transform` parameter to recover paraphrasing. The body of a protocol is ordinary code.

### The runner

```python
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
    """The same, for a child protocol."""


async def run_monitors(monitors: Monitors, context: Context, step: Step) -> Observations:
    """tg_collect over run_monitor."""


async def run_protocols(protocols: Protocols, context: Context, step: Step) -> Decisions:
    """tg_collect over run_protocol. Cancels siblings when one returns terminate."""


async def run_children(children: Children, context: Context, step: Step) -> Reports:
    """Both families in one task group. What concurrent() and chain() use."""


@dataclass(frozen=True)
class Reported(Generic[R]):
    name: str      # instance name: mapping key, or registry name
    path: str      # "attempt/internet_attempt"
    report: R


class Observations(Sequence[Reported[Observation]]):
    def max_suspicion(self) -> float | None: ...


class Decisions(Sequence[Reported[Decision]]):
    def strongest(self) -> Reported[Decision] | None: ...


@dataclass(frozen=True)
class Reports:
    observations: Observations
    decisions: Decisions
```

What the runner does for every child:

- Skips children not annotated for this stage. The skip looks like abstention.
- Names the child from the mapping key, or the registry name. Raises on a duplicate name within a layer.
- Derives the child's `Context` under this layer's path.
- Records one `SentinelEvent` per participating child, including reports the parent ignores. Ignored observations are the benign distribution a protocol later calibrates against.
- Applies the failure policy.

What the plural forms add: fan-out with `tg_collect()`, so children cannot see each other's conclusions, and cancellation of the remaining children when one returns `terminate`.

Results are split by family because the two aggregate differently. `Decisions.strongest()` applies the precedence in [Combining reports](#combining-reports); `Observations.max_suspicion()` takes the per-dimension max. Identity is attached so a protocol can weight or require agreement across specific children.

### The boundary check

When any protocol returns, the dispatcher validates the decision and raises on a violation. Each is a bug in a protocol, not agent input.

- The action is legal for the stage.
- `modified` is set if and only if `action == "modify"`, with the right type for the stage.
- The decision is not weaker than any authoritative decision from a child of this layer.

The check runs at every layer of a nested configuration.

### Two compositions

| | `concurrent()` | `chain()` |
|---|---|---|
| Runs | every child, concurrently | children in order, until one decides |
| Decides | strongest decision | first non-`escalate` |
| monitor children | recorded; the observations are available to a parent | recorded; fall through |
| `escalate` | does not count; all-escalate is `continue` | handed to the next link in `step.escalations`; all-escalate is `continue` |
| `modify` | honoured only if it was the only decision; otherwise `reject` naming the modifier | honoured; only one link decides |
| `terminate` | cancels the other children | ends the loop |
| Use for | independent guards that must all be satisfied | a cheap rule ahead of an expensive judge; a human at the end |

`concurrent` is the default. A list or mapping containing a protocol in `Task(sentinel=)` compiles to it. `chain` is one explicit word.

Rules:

- **Use `chain()` when there is a person at the end.** A `human()` in a concurrent group prompts on every call. The framework warns at configuration time and suggests `chain()`.
- **Do not expect ordered composition by default.** Ordered-by-default silences children: if A approves, B never runs, and B might have terminated. That is the defect #5423 reported against approval. Concurrent fails safe; its cost is latency and tokens.
- **Escalations never cross layers.** A link's `escalate` goes to the next link in its own chain. A chain whose last link escalates returns `continue` if any link participated, else abstains.
- **An uncovered call continues in a chain.** This matches review. The approval adapter keeps approval's `reject` for an uncovered call on its own path. A chain that wants fail-closed ends with a rejecting rule.

`chain()` as ordinary code over the runner:

```python
@protocol
def chain(children: Children) -> ControlProtocol:
    async def run(context: Context, step: Step) -> Decision | None:
        escalations: list[Reported[Decision]] = []
        participated = False
        for name, child in named(children):
            current = replace(step, escalations=tuple(escalations))
            if is_monitor(child):
                if await run_monitor(child, context, current, name=name) is not None:
                    participated = True      # recorded; falls through
                continue
            reported = await run_protocol(child, context, current, name=name)
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

### Humans

`human()` is a rule (a protocol with no children) for `BeforeToolCall`. It prompts through the existing human approval surfaces, renders `step.escalations` above the call, and returns with `authoritative=True`. Human surfaces queue requests, so two chains that both end in a person prompt one after the other, and the stricter answer wins.

### Static checking

mypy and pyright check the structural claims before the runtime pass does. `@scorer` already works this way: it is typed `Callable[P, Scorer] -> Callable[P, Scorer]`.

| Claim | Static check |
|---|---|
| A monitor returns `Observation \| None` | `@monitor` is typed `Callable[P, Monitor] -> Callable[P, Monitor]`; a `Decision`-returning body matches no member of `Monitor` |
| A protocol returns `Decision \| None` | the same with `ControlProtocol`; an `Observation`-returning body matches no member |
| The inner function's second parameter is a stage type | `Callable` parameters are contravariant; `Step` matches the `Step` variant, `BeforeToolCall` matches that variant, an unannotated parameter matches nothing |
| `threshold` takes monitors; `chain` takes children | the parameter types; `threshold(human())` is a type error because a rule has no score |
| The declared kind matches the body | `return Decision(...)` in a function annotated `-> Observation \| None` is a type error at that line |

Runtime only: per-stage action legality, the authority rule, whether a body went through the runner, and YAML configuration.

### Combining reports

Rules:

These rules describe the concurrent composition, which `concurrent()` implements and which is the default.

- **Every child configured for a stage runs.** No child is skipped because another already formed a view. `chain()` is the explicit exception.
- **Every report is recorded,** including the ones that lost.
- **Aggregate suspicion by max.** Per-dimension max when scores are structured. Weighted combinations and requiring agreement are protocol policy.
- **Aggregate decisions by strength:** `terminate` > `reject` > `modify` > `continue`. `escalate` does not count. If every child escalates, the result is `continue`. One ordering covers all four stages; it is `Decisions.strongest()`.
- **`terminate` cancels siblings.** Nothing outranks it and the sample is ending. `run_protocols` and `run_children` do this.
- **Child decisions are advisory to the parent.** A parent protocol may honour or override them, and the log records both; see [Transcript](#transcript).
- **Authoritative decisions are a floor.** A protocol's return may not be weaker than an authoritative child decision. The dispatcher enforces this at every layer.
- **Run children concurrently.** Sequential dispatch triples latency with three LLM monitors, and it lets a colluding monitor see the others' conclusions. TraceGuard's result (95% safety versus 0%) depends on independence. Use `tg_collect()`, not `asyncio.gather`. The runner does this for you.
- **A `modify` with more than one participant is a rejection.** Concurrent children cannot see each other's rewrites, and the others approved the original arguments. `concurrent()` returns `reject` with an explanation naming the modifier. A `modify` that was the only decision is honoured.
- **Decide on the protocol whether monitors block the agent or run alongside it.** Blocking costs latency. Running alongside means the agent may spend tokens or take a step before a violation is caught. This is a deployment judgement, so the knob belongs on the protocol, not the monitor.

### The top level

Every `Task(sentinel=)` configuration compiles to a protocol, so one layer always owns the outcome and records it.

| Configured | Compiles to |
|---|---|
| a monitor, or a list or mapping of monitors only | `observe(...)`: every observation is recorded; nothing acts |
| a protocol, or any list or mapping containing a protocol | `concurrent(...)`: protocols decide, monitors are recorded |

A bare monitor records and does not act. There is no default threshold, because no one has calibrated one. Recording is also the first step of a control experiment: run the monitors over known-benign tasks with nothing acting, and the recorded scores become the benign distribution.

A bare protocol acts. The author chose the action explicitly, so there is no uncalibrated threshold involved. `@approver` already works this way.

The top-level protocol emits its own `SentinelEvent` only when more than one child participated. A single-child configuration logs one event per step, as approval does today.

At configuration time the framework names monitors that nothing acts on:

> `suspicion_monitor` is a monitor and nothing is configured to act on it. Wrap it in a protocol such as `threshold()` to act on its scores, or `observe()` to say that recording is intended.

### Shipped protocols

```python
Task(sentinel=observe(network_suspicion()))
Task(sentinel=threshold(network_suspicion(), reject_at=0.8))
Task(sentinel=defer_to_trusted(network_suspicion(), threshold=0.8))
Task(sentinel=resample(network_suspicion(), threshold=0.8, n=3))
```

Use one of these rather than writing threshold logic by hand. The control papers explain why each exists.

| Protocol | Where | What it does |
|---|---|---|
| `concurrent` | core | runs every child; strongest decision wins; what a list containing a protocol compiles to |
| `chain` | core | runs children in order; first non-`escalate` decides; hands escalations forward |
| `observe` | core | records every observation, acts on none; what a bare monitor compiles to |
| `threshold` | core | `reject` above one constant, `terminate` above another; what calibration feeds |
| `defer_to_trusted` | core | above a threshold, substitutes the trusted model's action; returns `modify`. `AfterGenerate` only |
| `resample` | core | above a threshold, draws `n` further completions, executes the least suspicious; `escalate` if none clears. `AfterGenerate` only |
| `trusted_monitoring` | extension candidate | thresholds scores and spends a human-review budget; the budget is a deployment-economics idea that eval operators tend not to want |
| `trusted_editing` | extension candidate | has a trusted model rewrite the untrusted output; returns `modify` |
| honeypotting, paraphrasing, collusion-resistant monitoring | extension | pipeline stages wrapped around `run_monitors` |

`resample`, which shows how a protocol regenerates:

```python
@protocol
def resample(monitors: Monitors, threshold: float, n: int = 3) -> ControlProtocol:
    async def decide(context: Context, step: AfterGenerate) -> Decision | None:
        observations = await run_monitors(monitors, context, step)
        score = observations.max_suspicion()
        if score is None or score < threshold:
            return Decision.clear()
        best_score, best_message = score, step.output.message
        for _ in range(n):
            output = await context.host.generate(
                step.input, model=step.model, tools=step.tools, config=step.config
            )
            observations = await run_monitors(monitors, context, replace(step, output=output))
            candidate = observations.max_suspicion() or 0.0
            if candidate < best_score:
                best_score, best_message = candidate, output.message
        if best_score >= threshold:
            return Decision.escalate("no resample cleared the threshold")
        return Decision(action="modify", modified=best_message)

    return decide
```

Rules for protocols that generate:

- **Annotate `AfterGenerate`.** Regeneration needs the request, and only that stage carries `input`, `tools`, `tool_choice` and `config` beside the `output`.
- **Regenerate with `step.tools` and `step.config`.** The candidate must be a completion the agent could have produced.
- **Run candidates through the runner.** Every draw's scores are then in the log, not only the winner's.
- **`defer_to_trusted` defaults to the `trusted` model role.** `--model-role trusted=...` configures it without touching code.
- **Protocol inference is a separate usage bucket.** Recorded under `protocol` in `ModelUsage`, not charged to the agent's limits.

A third party ships a protocol the same way it ships a monitor: a decorated factory in a package, with no core change. Research-grade machinery lives outside core until there is demand.

## Configuration

```python
Task(sentinel=...)
eval(sentinel=...)
inspect eval task.py --sentinel sentinel.yaml
```

`Task(sentinel=)` takes one monitor or protocol, a list, or a mapping of instance names to either. Monitors alone compile to `observe(...)`; anything containing a protocol compiles to `concurrent(...)`.

```python
Task(sentinel=no_curl())
Task(sentinel=[no_curl(), no_rm_rf()])
Task(sentinel={
    "attempt": chain([internet_attempt(), human()]),   # a rule that escalates, then a person
    "escape": sandbox_escape(),                          # a rule; runs on every call regardless
})
```

`no_curl`, `no_rm_rf`, `internet_attempt`, and `sandbox_escape` are rules. The mapping keys are instance names. They reach the log as `attempt/internet_attempt`, `attempt/human`, and `escape`.

Flat list in YAML, like approval:

```yaml
sentinel:
  - name: no_curl
  - name: no_rm_rf
    tools: ["bash", "python"]
```

Named, as a mapping:

```yaml
sentinel:
  attempt:
    name: chain
    children:
      - name: internet_attempt
      - name: human
  escape:
    name: sandbox_escape
```

Nested, when a protocol wraps monitors:

```yaml
sentinel:
  - name: threshold
    params:
      reject_at: 0.8
    monitors:
      - name: suspicion_monitor
        params:
          model: openai/gpt-4o-mini
      - name: network_suspicion
  - name: no_curl
```

Rules:

- **A nested key is the factory's parameter name.** `monitors:` under `threshold`, `children:` under `chain` or `concurrent`. The top-level key is `sentinel:`, so it cannot be confused with the nested `monitors:`. A nested key under a factory with no such parameter, including every rule and every monitor, is a configuration error. The schema must not parse it silently.
- **Instance names are unique within a layer.** A duplicate is a configuration error. Registry names are the default when no mapping key is given.
- **`tools` scopes only the tool stages.** A `BeforeGenerate` monitor fires regardless of it. Read it as "which tools this applies to, if it watches a tool stage at all". A separate `stages:` key, or dropping globs and filtering inside the monitor on `step.call.function`, are the alternatives.

## Failures

An exception in a protocol ends the sample. An exception in a monitor ends the sample unless the monitor is under `observe()`.

| Where the exception is | On exception |
|---|---|
| a protocol | propagate; the sample ends |
| a monitor whose scores a protocol reads | propagate; the sample ends |
| a monitor under `observe()` | warn and continue |

Transient model errors are already retried below this layer by `GenerateConfig.max_retries` and `timeout`. An exception that reaches the monitor boundary is a persistent outage or a bug. Neither is swallowed.

To tolerate failure on purpose, declare it per function: `@monitor(fail="open")` or `@protocol(fail="open")`. The choice then appears in code review and the registry. There is no configuration that makes anything fail open silently.

Whether a monitor that fails on 3 samples in 500 should fail the eval is open; see [Open questions](#open-questions) item 15.

## Transcript

```python
class SentinelEvent(BaseEvent):
    event: Literal["sentinel"] = "sentinel"
    name: str             # registry name of the factory, monitor or protocol
    path: str             # instance path, e.g. "attempt/internet_attempt"
    step_id: str          # triggering message id, assistant message id, or tool call id
    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    kind: Literal["observation", "decision"]
    suspicion: Suspicion | None
    decision: Action | None
    audit: bool
    authoritative: bool
    outcome: Action | None
    explanation: str | None
    metadata: dict[str, Any] | None
```

Rules:

- **One event per report, including observations.** A monitor that scores every step and intervenes twice in a hundred samples is the common case. The steps with no intervention are the data a protocol calibrates against.
- **One event per layer in a nested configuration.** Each participating child and each protocol above it emits one:

  ```
  name="internet_attempt",  path="attempt/internet_attempt",  kind="decision",  decision="escalate"
  name="human",             path="attempt/human",             kind="decision",  decision="reject",  authoritative=True
  name="chain",             path="attempt",                   kind="decision",  decision="reject"
  name="sandbox_escape",    path="escape",                    kind="decision",  decision="continue"
  name="concurrent",        path="",                          kind="decision",  decision="reject"
  ```

  The last line is the summary event. The top-level protocol emits it only when more than one child participated, and its explanation lists each child's decision.

- **`name` is which code ran. `path` is which configured instance it was.** Two chains built from the same factory differ only in `path`. `kind` says which family it belongs to, and agrees with the registry type by construction.
- **`step_id` is what a label matches.** For `BeforeGenerate` it is the id of the message that triggered the generate, with an ordinal suffix on a regenerate; for `AfterGenerate` the assistant message id; for the tool stages the tool call id. All three exist before the monitor runs, so recorded events and replayed steps share ids. See `sentinel-development.md`.
- **`decision` is what the child decided. `outcome` is what the parent protocol did.** Both are needed to tell an overridden decision from one never made.
- **There is no `strategy` field.** The protocol's name says what it did. "How often did this protocol defer" is `monitor == "defer_to_trusted" and decision == "modify"`. A protocol that takes several different actions should be composed from nested protocols, or record the detail in `metadata`.
- **One flat event type across both families and all four stages.** The renderer, the dataframe, and the log schema all read it, and a split would push a union into `generated.ts`.

Whether `SentinelEvent` replaces `ApprovalEvent` and `ReviewEvent` when the decision came from a protocol, sits beside them, or those events gain a `monitor` field, is open.

## Bridged agents and proxies

A sentinel can run outside the eval process, in a proxy in front of a model API, where the agent cannot bypass it. `sentinel-deployment.md` covers this. An agent that runs its own tool loop (`claude_code`, `codex`) is the same case running in-process: it never reaches `execute_tools()`, so monitors reach its tool calls by projection from the model response, the way `apply_bridge_tool_approval` already applies approval today.

What each stage sees:

| Stage | Under a proxy or bridged agent | Fidelity |
|---|---|---|
| `BeforeGenerate` | the request | full |
| `AfterGenerate` | the response | full |
| `BeforeToolCall` | projected from `tool_use` blocks in the response | good |
| `AfterToolCall` | the result appears only in the next request; the last step of a trajectory is never seen | lossy |

Rules for portable monitors:

- **Prefer `BeforeGenerate`, `AfterGenerate`, and `BeforeToolCall`.** `AfterToolCall` should decline to fire under a proxy or bridged agent and say why, rather than run on lossy data.
- **Expect `view` and `output` to be absent.** A proxy has wire types, not registered tool definitions. The [rendering helpers](#view) name an absent surface in the prompt rather than omitting it.
- **Expect `terminate` to be best-effort.** In an eval it is total and synchronous. Under a proxy it is an error response plus an out-of-band `host.terminate()`, the same shape as `bridge.request_terminate()`, and the host may not support it. There is no separate set of portable actions. Whether `terminate` works is a property of the host.
- **Take state from `context.store_as`,** never from an ambient accessor. A proxy has nothing to bind an ambient accessor to.
- **Keep the module's imports light.** Bundling is per-module because the import closure is a module property. One `import requests` at the top of a file disqualifies every monitor in it. A bundler finds monitors with `ast` alone, which works because monitors are top-level functions.

Everything `sentinel-deployment.md` establishes for proxies applies to bridged agents: the five restrictions in `_bridge/_approval.py`, `reject` as a replay rather than a response edit, the bound on rejections, `modify` narrowing to arguments, and `terminate` as a side call.

## Relationship to approval and review

`Reviewer` merged 2026-09-11 (#5356). Three concepts now exist for one idea:

```python
ApprovalDecision = Literal["approve",  "modify", "reject", "terminate", "escalate"]
ReviewDecision   = Literal["continue",                     "terminate", "escalate"]
Action           = Literal["continue", "modify", "reject", "terminate", "escalate"]
```

**Decisions:**

- **Protocol replaces `Reviewer`.** A rule at `AfterToolCall` has the same fields and a superset of the decisions. `@reviewer` is deprecated with a warning pointing at `@protocol`. The 413 lines of parallel policy machinery in `review/` retire with it.
- **`@approver` stays.** It has been public for years and is used in shipped evals and extension packages. Whether it eventually becomes a rule at `BeforeToolCall` is deferred until protocols have users.
- **`approve` and `continue` both stay.** They mean different things. The adapter maps `continue` to `approve` at the boundary.

  | Word | Where | Means |
  |---|---|---|
  | `approve` | approver, pre-execution | I authorize this action |
  | `continue` | reviewer, post-execution | nothing to authorize; the tool already ran |
  | `continue` | protocol, nested | I decline to object |

- **`Task(approval=)` accepts a protocol.** Both forms compile down to an `Approver` that `apply_tool_approval` calls:

  ```python
  Task(approval=[ApprovalPolicy(...)])                       # today, unchanged
  Task(approval=threshold(..., reject_at=0.8))               # protocol-mediated
  ```

  The list form keeps its current code path. The `ApprovalPolicy` list is shorthand for an honour-everything protocol. Human approvers stay authoritative under any protocol. `Approval` does not gain a score field; an approver that wants to score should be a monitor under `threshold()`. This is probably a separate PR.

### The reviewer group's requirements (#5423)

Issue #5423 proposed that `approval` and `review` accept a dict of named policy chains, every chain running on every matching call, each with today's first-non-`escalate` semantics inside. The motivating defect: one ordered chain silences independent monitors, and the workaround loses per-monitor events, invents a severity order, and gives an inner monitor nowhere to escalate. The group has agreed to build on sentinels instead, so the proposal's requirements are requirements here.

| #5423 asked for | Here |
|---|---|
| independent chains that all run | concurrent is the default composition |
| per-monitor events | one `SentinelEvent` per participating child, from the runner |
| a framework severity order | `terminate > reject > modify > continue` in `Decisions.strongest()` |
| an ordered chain inside each group; `escalate` stays inside it | `chain()`; escalations never cross layers |
| a human at the end who sees who escalated and why | `human()`, reading `step.escalations` |
| named chains, and the name in the log | mapping keys as instance names; `SentinelEvent.path` |
| a summary event when several chains participated | the top-level `concurrent` event |
| `terminate` cancels the other chains | `run_protocols` |
| `modify` with several participants is a rejection naming the chain | `concurrent()` |
| an uncovered call rejects, as a lone policy list does | on the approval adapter path only; a chain returns `continue`, matching review |
| concurrent by default | yes |

Two deliberate differences. #5423 used "monitor" for a bundle registering an approver and a reviewer together; here a monitor or rule is one function at one stage and the bundle is a `chain()`. And `Task(approval=)` does not gain the dict form; named parallel chains live in `Task(sentinel=)`, with approvers usable inside a chain through the adapter.

## Design rationale

Why the design is the way it is, grouped by topic. Nothing in this section is needed to write a monitor.

### Why one object for four points

What exists today and where it falls short:

| Point in the loop | What exists | Limits |
|---|---|---|
| Before a tool call | `@approver` | Sees only the call. Fires only when the model calls a tool. |
| After a tool result | `@reviewer` (#5356) | `continue` / `terminate` / `escalate` only. No score, no rewrite. Separate policy machinery from approval (413 lines, 20 to 62% textually similar). |
| Before generate | `Hooks.on_before_model_generate` | Process-global, enabled by environment variable, so not per-eval. Exceptions swallowed. No transcript record. Cannot terminate. |
| After generate | nothing | |

State is the biggest gap. An approver is constructed once and called from every sample at once, so `self` is shared across samples. The `Hooks` docstring warns about the same hazard with the same workaround: key a dict by `sample_id` and remember to evict. Nothing carries across the four points either.

### Why the signature is `(context, step)`

The two arguments separate what should be happening (context) from what just happened (step). `Solver(state, generate)` and `Scorer(state, target)` are two-argument callbacks, and OpenAI's guardrails also take context first.

The split is also the injection boundary. Everything in `step` is agent-influenced. Nothing in `context` is. Making that a property of the signature rather than of field ordering is the framework's main defence against prompt injection, and it has no runtime cost.

Each argument is one dataclass rather than positional fields because adding a dataclass field breaks nothing, while adding a positional parameter breaks every monitor. The concern is with many positional parameters. Two fixed arguments are fine.

The parameter is named `step` because all four payloads describe one step in the agent's trajectory, and `step.call`, `step.output`, and `step.history` read naturally. The payloads are named before/after rather than for the object they wrap because `BeforeToolCall` has a `call` field and `AfterGenerate` has an `output` field, which would collide.

Context is passed on every call rather than once per sample because a monitor that has to hold its assignment is stateful, and `sentinel-deployment.md` depends on monitors being pure functions of one exchange.

### Why `Context` rather than `Task` and `Sample`

Passing the framework objects ties every monitor to Inspect. A proxy has neither. `Context` holds the same information stated in terms of the agent, so both deployments can fill it.

### Why `target` is opt-in

A deployment monitor does not know the right answer. An AI control eval measures how well a monitor would do in deployment, so a monitor given the target scores better than its deployed counterpart could, and the eval stops measuring what it claims to. If `target` were present by default, most monitors would read it without anyone deciding they should. Recording the request in the log lets a reader tell the two cases apart.

### Why monitors observe and protocols decide

The control literature and shipped guardrails disagree about what a monitor emits. Ctrl-Z and TraceGuard emit a score for a protocol to threshold. Claude Code hooks, OpenAI's tripwire, Guardrails AI, and NeMo emit a decision. Both are valid, and an earlier draft let one decorator return either, choosing the kind from the return annotation.

That draft needed: kind detection from annotations at configuration time, a ten-shape `Monitor` alias with a narrower `ControlProtocol` beside it, a rule that a leaf's decision is advisory when wrapped and applied when bare, three configuration-time warnings about mixed kinds, and a top-level table with four rows. Every one of those was a symptom of letting a leaf decide.

Making the report type the registry type removes them. A monitor cannot act, so it has nothing to threshold for, and the reviewer rule "a constant compared to a score is a threshold" becomes structural. A protocol always decides, so its decision is never advisory by kind, only by position under a parent. What was "two report types in one decorator" is now two decorators with one return type each.

The decision-emitting tradition is served by rules: a protocol with no children is today's `Decision` monitor under an accurate name. The score-emitting tradition is served by monitors plus `threshold()`.

The name `Decision.action` rather than the earlier draft's `Recommendation.recommend`: with leaves out of the picture, a protocol's return is a decision at every position. A nested protocol's decision may be overridden by its parent, and the event's `decision` and `outcome` fields carry that, but what the protocol returned was still what it decided.

### Why not return a bare number

`Scorer` returns a required `Score | None` with the flexible value inside as `Score.value`. Copying that keeps the return type fixed. A bare `return 0.9` has no name, so a reader cannot tell suspicion from confidence that the step is safe. It saves a few characters and costs a coercion branch in the dispatcher and ambiguity in every monitor.

### Why `None` means abstain

`Scorer` returns `Score | None`. A monitor with an early exit writes `if step.call.function != "bash": return`, which yields `None` whatever the signature says. A placeholder value like `Report.none()` would either accept `None` anyway, giving two spellings for one state, or force a constructor call on the most common path. An empty report recorded as a no-op observation was rejected because it is a fourth state indistinguishable in effect from `None` that still produces a transcript record.

### Why one `Action` across stages

Six places handle actions and would each need per-stage special cases: the precedence rule, the escalation chain's fall-through, `SentinelEvent`'s decision fields, config parsing, the TUI renderer, and `analysis` dataframe columns. With per-stage vocabularies the event fields would have to be a union of Literals correlated with `stage`, which neither the JSON schema nor the generated TypeScript can express, so consumers would get `string`.

A generic `Decision[A]` parameterised on the action set would keep per-stage legality statically checked. It was rejected because no serialized Pydantic model in `inspect_ai` is generic today, and parameterised generics produce mangled names like `Decision_ObserveAction_` in `components/schemas`, which flow to `generated.ts`. `design/type-generation-pipeline.md` exists to keep those out. A subclass widening the `recommend` Literal is an unsound override that mypy flags.

So the dispatcher validates legality at runtime and raises. An illegal action is a bug in the monitor, not agent input, so failing loudly follows the AGENTS.md rule on invalid states.

Sharing the return type does not reintroduce the `stage` flag #5355 rejected. That argument was against a runtime flag the caller branches on. Here the payload type is the stage, and `Report` has no stage in it.

### Why `modified` at `AfterGenerate` is a message, not a `ModelOutput`

`ModelOutput` carries `usage`, `time`, and `model`, which describe the call that happened. If a protocol draws three completions and executes the least suspicious, three completions' worth of tokens were spent. Swapping the whole `ModelOutput` would discard or falsify that. Only `choices[0].message` is substitutable content, and only `choices[0]` is monitored, matching the `n = 1` restriction in `_bridge/_approval.py` that exists to prevent unmonitored tool calls in alternate choices.

### Why return replacements rather than mutate

`Hooks.on_before_model_generate` mutates its payload, which works because frozen dataclasses protect the binding and not the contents of `input: list[ChatMessage]`. Monitors do not copy this. A mutating monitor has a side effect, so it is no longer a pure function of `(context, step)`. A proxy deserializes the payload and cannot see an in-place mutation; it can only see what was returned.

### Why a protocol may have no children

Deciding is what makes something a protocol, not having children. `human()` decides and consults nothing. `no_curl` decides and consults nothing. Requiring a `monitors` parameter would force both into a shape that does not fit, or force them back into `@monitor`, which is the bundling this design rejects.

With children, a protocol is a combinator. Inspect already implements this shape three times, as `chain`, `multi_scorer`, and `policy_approver`, and none of them is a new registry type. `multi_scorer` is the closest analogue: runs children in parallel, reduces, returns one `Score`, and is a `Scorer`. Here the combinator returns a `Decision` and is a protocol.

What separate registry types buy: `registry_create`, YAML, and the log say which of the two things ran; `threshold(human())` is a type error; the top-level table has two rows; and a reader never has to ask whether a given function can act.

What it costs: one more registry type, and the composition helpers accept a union (`Children`) where a single type would have done. Nested YAML is unchanged; `Task(solver=chain(...))` already has this shape, approval config already nests, and only a tree can express nested pipeline stages.

### Why `@protocol` is a decorator and not a constructor

An earlier draft had the pattern rest on a parameter named `monitors`, which is a name convention of the kind this design rejects elsewhere. A decorator replaces the convention with a declaration the framework checks: the result is `Decision`-kind, checkable statically because the decorator is typed with `ControlProtocol`.

A constructor, `protocol(monitors, decide=...)`, with the framework invoking the children and the author supplying only the reduction, was tried and dropped. It was less expressive than writing the body: a chain decides between links, not after them, so it could not be written; paraphrasing needed a `transform` parameter added back. And the factory still held the children, so it could still call them directly. The enforcement it seemed to buy was not real.

### Why concurrent is the default

Many people will want a chain, and a chain is what approval users know. But ordered-by-default silences monitors: if A approves, B never runs, and B might have terminated. That is the defect #5423 reported. Concurrent fails safe, with latency and tokens as the cost. A default is hard to change later without silently changing every configuration, so the safe one is chosen now and `chain()` is one explicit word. The most common mistake the wrong default would produce, a `human()` in a concurrent group, is caught at configuration time.

### Why `escalations` is on the step

A chain hands earlier escalations to the next link so a human sees who is asking and why. #5423 did this by appending to `view.context`, but `view` exists only on the tool stages and is absent under a proxy. A field on all four payloads works everywhere. It is on `step` rather than `Context` because it changes per step, and `Context` is constant for the sample. It is the one field on `step` that monitors wrote rather than the agent, so the injection rule names it as the exception.

### Why `authoritative` is a field

"A protocol may never override a human" was a prose rule. As a field on the report, the dispatcher can enforce it at every layer boundary by reading the child reports the runner recorded, with no cooperation from the protocol. It is on the report rather than the monitor because the combiner reads reports, and because the log should show which decisions were a person's.

### Why the top level always compiles to a protocol

Without it, a bare list combined decisions by severity but no layer owned the outcome, so nothing recorded it. Compiling to `concurrent()` gives the summary event #5423 asked for and gives the `modify` rule and the authority check one place to live. Compiling bare monitors to `observe()` makes recording-only an explicit configuration rather than a silent one.

### Why the protocol calls the monitors

Paraphrasing and minification transform agent output before the monitor sees it. Honeypots inject synthetic inputs into the monitor's stream. Neither is possible if the framework has already called the monitors and handed over finished reports. So the framework's responsibilities are in `run_monitors()`, and a protocol is ordinary Python around it. That is what lets third parties write protocols without changing core: honeypotting wraps the call, paraphrasing transforms the input, and neither needs a framework hook.

A design where core executes the control actions, with `defer` and `resample` as legal return values, was rejected on scope. Core would need to know about trusted models, resampling, and budget arithmetic. Every new technique would be a core change, and `run_monitors` would no longer be the only integration point.

### Why a bare monitor records only

A monitor produces a score, acting on a score needs a threshold, and a default threshold would be uncalibrated. Since a monitor cannot act, there is nothing to choose between: a bare monitor can only be recorded, and `observe()` is the name for that. The configuration-time warning exists so that nobody mistakes recording for acting.

There is no equivalent question for a bare protocol. Its author chose the action, so it applies, as `@approver` does today. A nested protocol's decision is advisory to its parent for the ordinary reason: if a child's `terminate` bypassed the configured parent, `observe()` around it would not be observe-only.

### Why the audit budget is per-sample

Ctrl-Z's budget is 1% of actions per episode, and an episode is one trajectory, which is one sample. So `context.store_as(BudgetState)` handles it and per-task state is not needed for it. A budget pooled across samples is a different, defensible design that the literature does not specify.

`audit` lives on `Decision` rather than `Observation` because "spend human review on this" is a policy statement. A scorer flags something by scoring it high.

### Why monitors are functions, not classes

Monitors watching more than one stage are rare. All four motivating cases are single-stage. Correlating a call with its result collapses to one `AfterToolCall`, which already carries both. OpenAI's Agents SDK registers guardrails individually and Claude Code hooks are per-event.

Functions make each monitor's stage and portability visible per function rather than per class, and they let a deployment bundler enumerate monitors with `ast` alone, since `parse_decorators` walks top-level `FunctionDef` nodes and would not see methods inside a `ClassDef`.

Name conventions (`suspicion_on_tool_call`) and glob selection were rejected. A name convention encodes what the annotation already says and can disagree with it. Glob selection solves a problem that only exists if grouping does; if listing gets tedious, a package exports `acme.all_monitors()`.

Functions do not fix the shared-state hazard. A closure captures state as readily as `self`, once per configuration. That is why `context.store_as()` is the rule.

### Why a factory decorator

Every registry decorator in Inspect is factory-based. A dual form for monitors alone would make use sites inconsistent, with a bare monitor listed as `no_curl` and a configured one as `suspicion_monitor("openai/gpt-4o-mini")`. The zero-config case pays one nested `def`.

### Why the stage comes from the annotation

This is the `@tool` contract: `tool/_tool_info.py:118` builds the entire `ToolInfo` from `get_type_hints(func)` with no override. A string `on="tool_call"` can disagree with the annotation and then something has to adjudicate. A type-valued `on=BeforeToolCall` restates what is there. Deduction at factory-call time is how `@scorer` already works.

The known failure is PEP 563: under `from __future__ import annotations`, `get_type_hints()` fails for types imported under `TYPE_CHECKING`. `_control/eval_state.py:40-45` documents it. The mitigation is an error that names the fix, not an override.

### Why no global accessors

Ambient accessors exist in Inspect for call boundaries you do not control: a tool invoked by the model, a scorer invoked by the framework. A monitor controls its own helper call sites, so helpers take parameters. `StoreModel` falls back to a global `ContextVar` that a proxy cannot provide; `context.store_as()` passes the store explicitly so that path is never taken. A `monitor_host()` global would reopen the property that `context.host` is the only route out of a monitor. `get_model()` is the leak that already exists, which is why the portability check bans it.

### Where the decorator lives

`_util/registry.py` is already a leaf: stdlib, pydantic, and four small `_util` modules at runtime, with every heavy type imported under `TYPE_CHECKING`. So the registry primitives move to `inspect_core` alongside the wire types, and `@monitor` defined there registers for real, with one shared registry dict because `inspect_ai` imports the same module. `ensure_entry_points()` must be injectable or a no-op in the leaf, since it imports third-party packages. Parameter capture reuses `extract_named_params`, which carries the VAR_KEYWORD flattening from #4374.

### Why fail loud

`apply_tool_approval` and review's `_apply.py` each have one `try/except`, around the viewer. An approver or reviewer that raises ends the sample. Only `Hooks` swallows, and `Hooks` is process-global and outside any eval's control. Transients are retried below the monitor boundary, so an exception arriving there is persistent or a bug. The no-consumer exception applies the same "safety mechanism with no consumer" analysis that drives the config-time warnings.

### Why protocol replaces reviewer and not approver

The reason is adoption. `review` is days old and `@approver` has been public for years. Deprecating a newly merged contribution has a cost, but a third parallel subsystem would cost more. Keeping both and adapting into each keeps the duplicate machinery forever. Replacing both would deprecate a mature API for a uniformity benefit no user has asked for.

Renaming `approve` to `continue` was rejected. Every `@approver` says `decision="approve"`, accepting both leaves two legal spellings, and existing logs contain `approve` and cannot change. The words also mean different things. `approve` authorizes. `continue` declines to object, or notes there is nothing left to authorize. `Reviewer` chose `continue` on its own for a post-execution decision, which supports the distinction. It is also why merging review into protocol is clean and merging approval is not.

Adding a protocol slot to `Task(approval=)` matters because someone running an LLM approver today cannot express "reject only the top 1% most suspicious". The threshold is baked inside the approver, where it cannot be calibrated or traded against a budget.

### Why `continue` and not `accept`

A nested protocol returning `continue` under a parent did not authorize anything. It declined to object. An outermost protocol returning the same value is authorizing. One word has to be accurate at both positions. `continue` describes what happens to the exchange. `accept` implies the monitor authorized the step, but authority comes from the configuration, not the monitor. This also settles #5356's open question the same way.

### Why the control vocabulary does not appear in `Action`

The literature's terms name mechanisms. `Action` names outcomes. Deferral, resampling, and trusted editing all produce a `modify`, so the two lists do not map one to one. The control terms appear as protocol names, which is where someone would search for them.

| Control term | Where it lives |
|---|---|
| `accept` | `Action.continue` |
| `audit` | `Decision.audit`, a flag |
| `defer_to_trusted` | a protocol name; returns `modify` |
| `trusted_editing` | a protocol name; returns `modify` |
| `resample` | a protocol name; returns `modify` or `continue` |

Three near-synonyms that are not the same:

- `defer` is not `escalate`. `escalate` passes the decision on and leaves the action alone. `defer_to_trusted` passes the action to a weaker model and leaves the decision made. The longer name matters because bare "defer" reads as "postpone", which is `escalate`.
- `trusted_edit` is not `modify`. It is one way to produce a modification. Stripping `--force` is another, with no trusted model.
- `reject` is not `block`. Inspect's `reject` appends a synthetic result and regenerates so the model learns. Control's `block` means the action does not execute and the protocol substitutes or escalates.

### Why there is no `strategy` field on the event

The protocol's name already says which strategy produced a `modify`. A `strategy` field on `Decision` would be one every rule carries and never sets. The remaining case, one protocol taking several different actions, is served by composition or `metadata`.

### Why suspicion is structured

TraceGuard reports 95% safety for five independent dimensions scored by parallel calls versus 0% for a single score when the monitor is colluding with the agent. Splitting the evaluation across independent models means no single compromised model sees the whole assessment. This is also why concurrent dispatch matters for safety and not only for latency.

### Why two audiences for explanations

Claude Code hooks separate `additionalContext` (model sees it) from `systemMessage` (operator sees it). If the agent learns why it was flagged, it can learn to avoid being flagged.

### Keeping the surface small

Someone who only wants to block bad `bash` calls should never need most of this document. There are two kinds of user:

- **Blocking bad tool calls.** A rule: a protocol with no monitors. The same experience as `@approver` with more stages.
- **Running a control experiment.** Monitors, a protocol over them, calibration against a benign distribution.

The first kind becomes the second when their rule starts computing a score and comparing it to a constant, at which point the score moves into a monitor and the constant into `threshold()`.

What keeps the simple case simple:

1. Every control action lives in the protocol. `defer`, `resample`, `audit`-as-action, `trusted_edit`, honeypots, paraphrasing, and multi-sample payloads are not on the monitor surface. Apply the same test to anything added later.
2. Every optional field has a default.
3. Protocols ship named and configured.
4. Zero configuration does something sensible for each kind: a rule acts, a monitor records.
5. "Monitor" and "protocol" are two types, and the decorator says which you are writing. The "write your first rule" page contains no control vocabulary.
6. Research machinery goes in extensions, per AGENTS.md.

## Background: prior art

**OpenAI Agents SDK.** It ships four decorators: `@input_guardrail`, `@output_guardrail`, `@tool_input_guardrail`, `@tool_output_guardrail`. Those are the four stages here. It uses a different return type per stage, which this design does not. Its input guardrails take a `run_in_parallel` flag: run concurrently with the agent (cheaper wall-clock, the agent may burn tokens before cancellation) or block first.

**Ctrl-Z.** [Ctrl-Z](https://arxiv.org/abs/2504.10374) formalises deployment as a protocol that observes each action and may accept, resample, defer, or audit it. The audit budget is 1% of actions per episode, allocated by exponential decay so scrutiny is stricter early. Two thresholds sit over one score, a lower deferral threshold and a higher auditing threshold, both calibrated against known-benign distributions and adjusted for remaining budget. Resampling draws up to two further samples and executes the least suspicious that clears the deferral threshold. Incrimination exploits multi-sample variance: a malicious policy attacks consistently, an honest one varies, and a three-strikes rule audits when suspicion crosses threshold three times. Deferral substitutes the trusted model's action outright. The original AI Control paper adds trusted editing, where the trusted model rewrites the untrusted output. This design takes from it that the monitor should produce a score, and that thresholds, deferral, resampling, and auditing belong in a protocol that can see the budget and the position in the episode.

**TraceGuard.** [TraceGuard](https://arxiv.org/html/2604.03968v1) scores five independent dimensions (goal alignment, constraint adherence, reasoning coherence, safety awareness, action-trace consistency) with parallel independent LLM calls, and reports 95% safety versus 0% for single-score monitoring when the untrusted monitor is also the agent.

**Untrusted monitoring safety cases.** [This paper](https://arxiv.org/html/2602.20628v1) lists the ways an agent and a monitor can collude: passive self-recognition (the monitor recognises its own writing style), active causal collusion (a pre-agreed signal), active acausal collusion (Schelling points), and combinations. In their results, passive self-recognition trained by fine-tuning was the most effective attack. That means the attack that needs no coordination between agent and monitor is the hardest to stop. Countermeasures are honeypotting, signal jamming (minification, variable normalisation, summarisation), and auditing. All of these are transforms around the monitor rather than logic inside it.

**Chain-of-thought monitorability.** [This paper](https://arxiv.org/abs/2507.11473) argues that reasoning traces are a useful safety signal and that training choices can make them less useful. TraceGuard makes a related point: an agent's outputs can look fine while its reasoning does not. Inspect has `ContentReasoning`, so whether a monitor sees it is a decision to make. The evidence says monitors should see it and score it separately from actions.

**Shipped products.**

- Claude Code hooks: `PreToolUse` returns `allow` / `deny` / `ask`, plus `updatedInput`, `additionalContext` (model sees it), and `systemMessage` (operator sees it). All matching hooks run in parallel; any `deny` blocks. `PostToolUse` can read the result but cannot block or modify it, the gap #5355 identified.
- Guardrails AI runs a standalone Guard Server over HTTP, which is why it is the easiest to use from languages other than Python. `sentinel-deployment.md` reaches the same conclusion.
- NeMo Guardrails uses Colang, a rule DSL, at 100 to 300ms added latency.
- Portkey integrates external guardrails by webhook, which is what the host ABI's `fetch` is for.
- Output guardrails under streaming are an open problem in the OpenAI SDK too.

**Taken from this survey:** the monitor/protocol split, structured scores, `audit` as a flag, prepackaged protocols, separate model-facing and operator-facing explanation channels, the `run_in_parallel` knob, reasoning visibility, and rules as the home for decision-emitting guardrails.

**Deliberately not in core:** honeypots, paraphrasing, resampling payloads, collusion-resistant untrusted monitoring. These serve a small audience and can be built as extensions.

## Open questions

1. **Does `@approver` eventually become a rule?** Protocol replaces `Reviewer` and `@approver` stays for now. A rule at `BeforeToolCall` is what it would become; deferred until protocols have users.
2. **Who owns the budget when protocols nest?** Outermost wins is the obvious answer. Whether an inner budget owner should be an error is open.
3. **Which protocols ship in core?** Settled: `concurrent`, `chain`, `observe`, `threshold`, `defer_to_trusted`, `resample`. `trusted_monitoring`, `trusted_editing`, and the collusion-resistant variants are extension candidates.
4. **Score aggregation default.** Max, per-dimension when structured, is the obvious default. The framework has to pick one and document it.
5. **Where does calibration get its benign distribution?** Answered in `sentinel-development.md`: replay the monitor over a benign corpus as a Scout scanner and take percentiles of the score column. Holding the calibration corpus out of the validation split is the open hygiene question.
6. **Does anything in v1 need per-task state?** The audit budget does not. Cross-sample gating ("terminate once 3 samples are flagged") does, and it resets in the unsafe direction. If nothing in v1 needs it, per-task state can be deferred whole. If something does, its scope needs deciding between task, run, and eval-set.
7. **What is the default protocol called?** Settled: `concurrent`. It names the execution shape, as `chain` does; the reduction lives in `Decisions.strongest()`.
8. **Should a protocol be able to add to recorded usage?** `modified` at `AfterGenerate` leaves `usage` untouched. `resample` records its draws under a `protocol` usage bucket. Open is whether that bucket shows in the eval's headline token count.
9. **Does the monitor see `ContentReasoning`?** Answered by [View](#view): rendered by default at whatever fidelity exists, excluded via the preprocessor, and a protocol withholds it from a child by transforming `step`.
10. **Lifecycle stages.** `SampleStart` and `SampleEnd` payloads would give state a place to initialise and a monitor a place to file a final verdict. Cheap now that a stage is a payload type, but it overlaps `Hooks`, and neither travels to a proxy.
11. **Can a monitor produce a `Score`?** Yes: `as_scorer(as_scanner(monitor, unit="transcript"))`, in `sentinel-development.md`. Scoring is untouched.
12. **Does `AfterToolCall` get a bridged-agent fallback?** Reconstructing a result from the next request, or declining to fire and saying why.
13. **Does `Task` / `Sample` grow a `description` field?** A public API change for a general-purpose field monitors need first. If not, the assignment comes from `metadata` by convention and is undiscoverable.
14. **Which stages can `human()` serve?** `BeforeToolCall` is what the human surfaces render today. `AfterGenerate` is plausible and needs a new rendering. `BeforeGenerate` is hard to make meaningful to a person.
15. **Failure tolerance across many samples.** Whether a monitor failing on 3 of 500 samples should fail the eval, and whether that reuses `fail_on_error`'s shape (`True` / `False` / proportion / count) or needs its own knob.
16. **Should reading an eval-only surface be recorded?** `target` is opt-in and logged. `step.output` and `step.view` raise the same validity question and get no such treatment. A declared view was judged heavier than the problem; explicit flags on `step_as_str` are the lighter option.
17. **Default history window in `monitor_prompt`.** Full history is safe; `new_since_last_report` is the incremental shape the design argues for elsewhere.
18. **Is the rendered prompt part of the recorded decision?** `host.generate` records a `ModelEvent`, so it is in the log already. Whether replay should check its rendering against the recorded one is open.
19. **`ControlProtocol` or `Protocol`?** The alias avoids `typing.Protocol`, which the codebase imports constantly, at the cost of the `tool` / `Tool` symmetry that `protocol` / `Protocol` would have had. A monitor author's file rarely imports `typing.Protocol`, so the collision may be tolerable.
20. **Should `chain` and `concurrent` accept monitors at all?** They do here, recorded and falling through, so that a mixed top-level list has a meaning and a chain can carry a scorer beside its rules. The alternative is protocols only, with `observe()` as the way to record a monitor.
