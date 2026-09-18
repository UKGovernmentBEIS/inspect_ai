# Inspect Monitors

## Overview

Inspect Monitors is a package for defining, developing, and deploying monitors: functions that watch agents and intervene in their execution. Key design elements include:

1.  A single interface that encompasses monitoring tool calls and model generations, with execution either before or after steps.
2.  Monitors report either a suspicion score (for a protocol to threshold and act on) or a direct action similar to the current Inspect tool call approval interface (e.g. continue, modify, reject, escalate, terminate).
3.  Support for layering control protocols (thresholds, audit budgets, resampling, defer to trusted, human review, etc.) on top of monitors.
4.  Core interfaces decoupled from the Inspect runtime so that monitors can be deployed elsewhere (e.g. in network proxies).
5.  Development tools for validating, calibrating, and backtesting monitors on test or production transcripts.

The purpose of this document is to solicit feedback on the core concepts and Python API used to implement monitors and protocols.

## Monitor Interface

Monitor is a new registerable type that returns a monitor function. For example, here is a monitor that prohibits the use of `curl` in any tool call:

``` python
@monitor
def no_curl() -> Monitor:
    async def check(context: Context, step: BeforeToolCall):
        if "curl" in str(step.call.arguments):
            return Recommendation(
                recommend="reject", 
                explanation="network access is not allowed"
            )
        return None

    return check
```

Note that this monitor runs before the tool call executes (the `step` it takes is `BeforeToolCall`). There are four different steps that a monitor could choose to target:

| Step | Fires |
|------------------------------------|------------------------------------|
| `BeforeGenerate` | Before each generate, before the cache lookup |
| `AfterGenerate` | After each generate, before the output reaches the agent |
| `BeforeToolCall` | Before a tool call executes |
| `AfterToolCall` | After a tool call executes, before the model sees the result |

### Actions

Each of the steps can specify various actions:

| Action      | Effect                                                       |
|------------------------------------|------------------------------------|
| `continue`  | No change to the exchange                                    |
| `modify`    | Replace the step's subject with `modified`                   |
| `reject`    | Reject the action, notifying the agent that it was rejected. |
| `terminate` | End the sample                                               |
| `escalate`  | Pass the decision to the next decider                        |

Monitors can be fully self contained (process and make a `Recommendation`) or they can merely scan and record an `Observation` to be acted on by a parent monitor (see [Protocols](#protocols) below).

### Context

In addition to the data associated with a tool call or generation, Monitors are passed a `Context` that includes task and sample information, a place to store state, and an interface to the monitor host (which could either be Inspect AI or a proxy server):

``` python
@dataclass(frozen=True)
class Context:
    task: str | None
    """Task name, or the deployed agent's identifier."""

    task_description: str | None
    """What agents in this setting are asked to do."""

    sample_id: str | int | None
    """Dataset sample identifier."""

    sample_description: str | None
    """What is distinctive about this instance."""

    input: str | list[ChatMessage]
    """The prompt this agent was given."""

    metadata: dict[str, Any]
    """Task metadata merged with sample metadata."""

    store: Store
    """This monitor's per-sample state."""

    def store_as(
        self,
        model_cls: Type[SMT],
        *,
        scope: Scope = "sample"
    ) -> SMT:
        """Typed view of this monitor's state."""

    # -- effects
    host: Host
    """Interface to host for inference, logging, etc."""

    target: Target | None = None
    """The expected answer (opt-in; absent by default)."""
```

## Protocols {#protocols}

A protocol is a monitor that takes other monitors as arguments, runs them, and turns their reports into a single `Recommendation`. Protocols own:

- **Thresholds**, calibrated against benign score distributions.
- **The audit budget** for human review (e.g. Ctrl-Z spends 1% of actions per episode, allocated with exponential decay so early steps are scrutinized harder).
- **Aggregation** of reports from several monitors.
- **Control actions**: accept, audit, defer to a trusted model, trusted edit, resample. These are things a protocol does with a score, not values a monitor can return.
- **Pipeline stages** such as paraphrasing agent output before monitors see it, or injecting honeypot inputs to catch a colluding monitor.

Two built-in protocols cover most compositions:

|   | `concurrent()` | `chain()` |
|------------------------|------------------------|------------------------|
| Runs | Every child, concurrently | Children in order, until one decides |
| Decides | Strongest recommendation (`terminate` \> `reject` \> `modify` \> `continue`) | First non-`escalate` |
| `escalate` | Does not count | Handed to the next link, so a human at the end sees who asked and why |
| Use for | Independent guards that must all be satisfied | A cheap rule ahead of an expensive judge; a human at the end |

### Writing a Protocol

A protocol's body is ordinary code around `run_monitors()`, which runs the children concurrently, records their reports, and returns them split into observations and recommendations. Thresholds, budget arithmetic, and aggregation are up to the protocol.

For example, trusted monitoring: a trusted model scores each step; above a deferral threshold the untrusted model's action is replaced with the trusted model's; the most suspicious slice, up to the audit budget, is sent to human review:

``` python
@protocol
def trusted_monitoring(
    monitors: Monitors,
    audit_budget: float = 0.01,
    defer_threshold: float = 0.8,
    audit_threshold: float = 0.95,
) -> ProtocolMonitor:
    async def decide(context: Context, step: Step):
        reports = await run_monitors(monitors, context, step)
        score = max_suspicion(reports.observations)
        budget = context.store_as(AuditBudget)

        if score >= audit_threshold and budget.take():
            return Recommendation(
                recommend="modify", 
                audit=True,
                modified=await trusted_action(context, step)
            )
        if score >= defer_threshold:
            return Recommendation(
                recommend="modify",
                modified=await trusted_action(context, step)
            )
        return Recommendation.clear()

    return decide
```

## Deployment

Monitors can be developed, refined, and deployed within Inspect AI, and for many applications this will be sufficient. However, in some scenarios you may want to run monitors in a network proxy in front of the model API, where the agent cannot bypass them and where they cover all agent traffic (e.g. coding agents). A proxy has no `Task`, no sample, and no `Store`, and the traffic is not necessarily Inspect's, so the monitor interface is designed so that the same monitor runs in both places.

### Proxy Steps

A proxy sits on one HTTP exchange: a request and a response. It never sees a tool execute, because tools run client-side after the response is delivered. So two of the four steps are exact, and the tool steps are projections:

| Step | In a proxy | Fidelity |
|------------------------|------------------------|------------------------|
| `BeforeGenerate` | The request body | Full |
| `AfterGenerate` | The response body | Full |
| `BeforeToolCall` | `tool_use` blocks in the response | Good (no `view`) |
| `AfterToolCall` | `tool_result` blocks in the *next* request | Lossy (the last step is never seen) |

### Execution

The goal is to enable two deployment modes for proxy servers:

1.  Sidecar (a Python service beside the proxy); or
2.  Embedded (CPython compiled to WASM inside the proxy)

Both modes depend on monitors being lightweight. `inspect_monitor` depends only on `inspect_core`, a new package holding the wire types (`ChatMessage`, `ModelOutput`, `ToolCall`, `ToolInfo`) and the registry primitives, so that a monitor author, a proxy, or a WASM build never pulls in the full Inspect framework.

Even if you are deploying monitors inside Inspect AI to start with, the API will verify that your code will travel well to a proxy without Inspect dependencies. Note that you can opt out of this checking with `@monitor(portable=False)`.

## Development

Inspect Scout will provide a feedback loop for monitor development (validation sets with labelled cases, precision/recall/F1, a results data frame, and a viewer for labelling). This will work with both Inspect logs and transcripts from other sources (e.g. proxy servers, coding agent sessions, etc.). The `as_scanner()` function turns any monitor into a scanner that replays it over the steps of each transcript.

``` python
from inspect_scout import scan, transcripts_from
from inspect_scout.monitor import as_scanner

scan(
    scanners=[as_scanner(suspicion_monitor("openai/gpt-4o-mini"))],
    transcripts=transcripts_from("./logs"),
    validation="exfil-steps.csv",
)
```

The typical workflow:

1.  Replay the monitor over a corpus and review what it flags in Scout View.
2.  Label steps as should-flag or should-not-flag directly from the results view, building a validation set with dev and test splits. Each step has a stable id (the tool call id, or the message id), so labels apply to replayed steps and to the `MonitorEvent`s an eval recorded.
3.  Validate using precision, recall, F1, and balanced accuracy over the dev split. Change the prompt, bump the version, re-scan, compare.
4.  Calibrate by replaying an `Observation` monitor over known-benign transcripts. The score column of the results is the benign distribution, so a budget (e.g. "audit the top 1%") becomes a threshold by percentile.


