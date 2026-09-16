# Developing monitors

How a monitor gets built, measured and calibrated before it is trusted to act. The mechanism is Inspect Scout: a monitor becomes a scanner over the steps of a transcript, and Scout's validation sets, metrics and viewer become the monitor's feedback loop.

Status: design sketch. The Python is illustrative. Scout facts are measured against `inspect_scout` at 2026-09-09; Inspect facts against this branch.

**Related design documents.** `monitor.md` defines the protocol this document develops against, and `monitor-reference.md` is its reference form. `monitor-deployment.md` defines the proxy deployment, whose view of a transcript turns out to be the same one offline replay has. `inspect-core.md` covers the package split this document depends on.

## Goal

A monitor is a classifier, and nobody should trust a classifier they have not measured. Concretely, the things a monitor author needs to do before configuring one to act:

- run it over a corpus of transcripts and see what it flags
- label a set of steps or trajectories as should-flag / should-not-flag, and get precision, recall and F1 against them
- change the prompt and see whether the numbers moved
- collect the score distribution over known-benign runs, and turn a budget ("audit the top 1%") into a threshold
- check how the monitor actually behaved in an eval it was attached to, without re-running it

Scout already does the first four for *scanners* — validation sets with splits, balanced accuracy, precision, recall and F1, Scout View for labelling, a results dataframe, and scanner versioning to compare prompts — over Inspect logs and over transcripts from other sources. The design problem is therefore small: make a monitor look enough like a scanner that all of that applies, without either package growing a second copy of anything.

## The shape

**A monitor is a scanner over steps.** Scout scans a `Transcript` and returns a `Result`; a monitor takes `(Context, Step)` and returns a `Report`. Everything a step needs is already in a transcript, so a transcript can be re-walked into the steps the monitor would have seen and the monitor run against each in order.

``` python
from inspect_scout import scan, transcripts_from
from inspect_scout.monitor import as_scanner

validation = "exfil-steps.csv"

scan(
    scanners=[as_scanner(suspicion_monitor("openai/gpt-4o-mini"))],
    transcripts=transcripts_from("./logs").for_validation(validation),
    validation=validation,
)
```

Protocols are monitors, so `as_scanner(trusted_monitoring(...))` back-tests a whole configuration the same way, and the recorded per-layer reports go along with it.

Three things fall out of this that the rest of the document works through:

- **Offline replay is a third deployment**, beside the eval and the proxy, and it has a fidelity table like the other two. Reconstruction from a messages-only transcript is *the same projection* the proxy and the bridged agent already use, so one function serves all three.
- **The recorded reports finally have a consumer.** `monitor.md` records every report, including the ones a protocol ignored, on the argument that they are the benign distribution calibration needs. Scout is where that distribution gets read.
- **Threshold calibration is a scan plus a percentile.** `monitor.md`'s open question 5 — where a protocol's thresholds come from — has an answer that needs no new machinery.

## Packages

`inspect_monitor` is its own distribution depending only on `inspect_core` (see `inspect-core.md`). The chain is:

```
inspect_core  ←  inspect_monitor  ←  inspect_ai  ←  inspect_scout
```

Scout already depends on Inspect, so it gets `inspect_monitor` transitively and the adapter lives in Scout with no new dependency. What goes where:

| Where | What | Why there |
|------------------------|------------------------|------------------------|
| `inspect_monitor` | `steps_from_messages()`; the `ReplayStep` record; `Context` from a transcript's info; an in-process `Host`; `replay_monitor()` | needs only core types, and is also what a monitor's unit tests want |
| `inspect_ai` | `steps_from_events()` — enrichment of the messages-only reconstruction with `view`, truncation, `tools`, `config` from `ModelEvent` and `ToolEvent` | the event types are not in core today |
| `inspect_scout` | `as_scanner()`; the `subject` field on `Result` and row expansion; the read-mode scanner over recorded `MonitorEvent`s; `calibrate()`; viewer work | consumes monitors; owns validation and the view |

The middle row is pressure on `inspect-core.md`'s first open question. If `ModelEvent` and `ToolEvent` move down, the events-based reconstruction moves down with them and `inspect_monitor` can replay an eval log at full fidelity on its own. Nothing in this document requires that; it only gets tidier.

## Reconstructing steps

### From messages

The canonical reconstruction works from `list[ChatMessage]` alone, because that is what every source has — an eval log, a Scout transcript from another agent framework, a proxy request. It is exactly the projection `agent/_bridge/_approval.py` performs on a model response and `monitor-deployment.md` describes for a proxy:

| Stage | Reconstructed from | Fidelity |
|------------------------|------------------------|------------------------|
| `BeforeGenerate` | every message before an assistant message is that generate's `input` | `tools`, `tool_choice`, `config` absent |
| `AfterGenerate` | the assistant message is `output.choices[0].message`; `usage`, `time` absent | good |
| `BeforeToolCall` | each `tool_calls[i]` on an assistant message, with the message text and history to that point | `view` absent |
| `AfterToolCall` | the `ChatMessageTool` whose `tool_call_id` matches, as `result`; history to that point | `output` (untruncated) absent |

`view` and `output` being absent is the case `monitor.md` already requires monitors to tolerate for proxies, so a portable monitor replays from messages unchanged. Note the last row is *better* than the proxy's: a proxy never sees the final step's result because no further request carries it, whereas a transcript is complete.

``` python
@dataclass(frozen=True)
class ReplayStep:
    id: str                 # the step id — see below
    stage: Stage
    context: Context
    step: Step


def steps_from_messages(
    messages: list[ChatMessage], *, context: Context
) -> Iterator[ReplayStep]: ...
```

### From events

An eval log's events restore what messages lose. `ModelEvent` carries `input`, `tools`, `tool_choice`, `config` and `output` — `BeforeGenerate` and `AfterGenerate` field for field. `ToolEvent` carries `function`, `arguments`, `view`, `result` and the `truncated` range, which restores `view` and lets `result` be exactly what the model saw. The one thing an eval log does not hold is the untruncated tool `output`, so `AfterToolCall.output` stays optional in replay too.

`steps_from_events()` is therefore an *enrichment* of the messages reconstruction rather than a second algorithm: it walks the same message sequence and attaches the matching event's fields where one exists. That keeps step identity (below) independent of whether events were available, which is what lets one validation set serve both kinds of source.

### `Context`, `Host` and `Store` in replay

| Member | In replay |
|------------------------|------------------------|
| `task`, `task_description` | from the log's eval spec; from Scout's `TranscriptInfo.task_set` and `metadata` for other sources |
| `sample_id`, `epoch` | `TranscriptInfo.task_id`, `task_repeat` |
| `input` | the sample input from the log; the first user turn otherwise |
| `metadata` | task and sample metadata merged, as in an eval |
| `target` | available from the log; **still opt-in**, and the adapter records that it was requested, for the same validity reason as in an eval |
| `store` | a fresh `Store` per transcript, so incremental monitors accumulate across the transcript's steps and nothing leaks between transcripts |
| `host` | in-process: `generate()` uses the scan's model and its usage lands in the scan's `model_usage`; `fetch()` resolves named endpoints from scan config; `terminate()` returns `False` |

### What replay cannot do

Replay reproduces the monitor's *reports*, not its *effects*. A `reject` in replay does not change the transcript; the agent already did what it did. This is the right limitation for measuring a classifier — precision and recall are about reports — but it means two things cannot be back-tested offline:

- **Interventions.** Whether rejecting call 7 would have led the agent somewhere better is a question for a live eval, not a replay.
- **Humans.** `human()` cannot be replayed. The useful substitute is to *replay the recorded human decision* when the transcript carries a `MonitorEvent` for that step with `authoritative=True`, so a chain can be back-tested against the answers a person actually gave; otherwise `human()` abstains in replay.

## Step ids

Per-step validation needs each step to have an id that exists in a messages-only transcript, in an events transcript, and **live, at the moment the monitor runs** — so that a label made once serves replay and also the read mode over recorded events. Message and tool-call ids satisfy that. Event uuids do not: a `BeforeGenerate` monitor runs before its `ModelEvent` exists.

| Stage | Step id |
|------------------------|------------------------|
| `BeforeGenerate` | id of the last input message — the one that triggered the generate |
| `AfterGenerate` | id of the assistant message produced |
| `BeforeToolCall` | the tool call id |
| `AfterToolCall` | the tool call id |

One wrinkle: a rejected call followed by a regenerate produces two `BeforeGenerate` steps behind the same last message. That stage takes an ordinal suffix on repeat — `{message_id}:2` — and the other three stages are clean. Within one monitor's stage, ids are unique per transcript; a `BeforeToolCall` monitor and an `AfterToolCall` monitor both key by tool call id, but validation sets are per scanner so there is no collision.

**Consequence for `monitor.md`:** `MonitorEvent` gains `step_id: str`, recorded by the runner live, so the read-mode scanner emits results with the same subjects the replay scanner does.

## The scan unit and the validation unit

Three grains of label are in play, and they do not need three scan units:

| Grain | The label answers | Keyed by |
|------------------------|------------------------|------------------------|
| step | did this tool call or generate deserve a flag | step id |
| transcript | did this trajectory contain an attack | transcript id |
| protocol | did the configuration reach the right decision at this step | step id; the result is the outermost layer's |

Four ways of getting the step grain into Scout were considered:

- **A `Step` scanner input type.** First-class, and the view could render it natively. But `monitor.md` says monitors should be incremental, so nearly every real monitor is stateful across steps and needs its transcript's steps *in order with one store*. Scout's input model does not promise sequential in-order invocation within a transcript, so the new type would also need a new ordering guarantee. It buys less than it looks.
- **A `Sequence[Step]` input per transcript.** Preserves order, but the ids on a sequence input are the whole list, so validation cannot address one step.
- **A resultset per transcript, validated by label.** No Scout change, but label validation is presence-or-absence per label, so "step 7 was flagged and should not have been" is not expressible.
- **Keep the transcript as the scan unit; make the result the validation unit.** Chosen.

### The chosen shape

The adapter is a `Scanner[Transcript]`. It walks the steps itself, in order, with its own store, and returns one `Result` per eligible step. Each result carries a **subject** — the step id. A validation case whose id is a step id matches the result with that subject.

``` python
as_scanner(monitor, unit="step")        # one Result per step; subject = step id
as_scanner(monitor, unit="transcript")  # one Result; transcript id, as today
```

State stays where `monitor.md` already puts it; Scout's parallelism across transcripts is untouched; and the transcript-grain form is the same adapter reducing to one result by max suspicion or strongest recommendation, with `references` to the flagged steps.

### What Scout changes

Two things, both small, and deliberately not a new input type or a new matching path.

**`subject` on `Result`.** A reference says what a result *cites as evidence*; a subject says what a result *is about*. A step result routinely has both — it is about tool call X and cites messages M3 and M7. They differ in cardinality (references are a list; a subject is exactly one thing, and validation must match exactly one), in id kind (`Reference.type` is `message` or `event`; a tool call id is neither), and in what the viewer does with them (references render as links from cite text; a subject drives row identity and navigation). So `references` stays for what an LLM monitor's explanation points at, and `subject` is new:

``` python
class Result(BaseModel):
    ...
    subject: str | None = Field(default=None)
    """Id of the thing this result is about, when narrower than the scanner
    input. Each subject-bearing result is recorded and validated as its own row."""
```

**Expansion into rows.** Today `_validate_scan` matches a case id against the input ids of one `ResultReport`, and a scanner returning a list is folded into a single resultset report. When a scanner returns results carrying a `subject`, each becomes its own `ResultReport` with `input_ids=[subject]`. Matching, the dataframe, the summary metrics and the results view all already work per report, so per-step behaviour falls out. A result with no subject is recorded exactly as today.

One rule keeps matching unambiguous: **subjects are unique within one scanner's results for one input.** The adapter emits one result per step for the monitor being validated; a protocol's child reports go in that result's metadata. To validate a leaf inside a protocol, wrap the leaf directly.

What `input` holds on an expanded row is a recorder decision rather than a design one: the parent transcript id plus the subject is the honest content, the view navigates to the transcript and highlights the message or tool call, and the pooled-dedup path already exists to avoid copying a transcript per step.

## Mapping `Report` to `Result`

| Report | `value` | `answer` | `metadata` | `label` | `subject` |
|------------------------|------------------------|------------------------|------------------------|------------------------|------------------------|
| `Observation` | `suspicion` — float or dict | — | monitor metadata | instance path | step id |
| `Recommendation` | flagged: `recommend` in `reject`, `modify`, `terminate` | `recommend` | `audit`, `authoritative`, `modified`, child reports | instance path | step id |
| abstained | `None` | `None` | — | instance path | step id |

Three things the table encodes:

- **A dict suspicion validates per key** through Scout's existing dict-target path, so a multi-dimension monitor gets per-dimension precision and recall without any adapter logic.
- **The boolean flagged value is what makes binary labels work.** A per-step validation set will label steps the monitor abstained on, and abstention produces no report. The adapter emits a result for every step at the monitor's stage, `None` on abstain, and a label of `false` compares equal to "not flagged" only if the value is boolean. Teaching the `eq` predicate that `None` is negative was the alternative; mapping to a boolean keeps the predicate honest and leaves the action in `answer` for anyone sweeping on it.
- **`escalate` is not flagged.** It is "I decline to decide", not a verdict. Inside a chain it also means "worth a person's look", which a reviewer might want to count; `answer` carries it for that. This is a default that is cheap to get wrong, and it is recorded as a decision rather than left implicit.

The `explanation` maps directly, and `references` are whatever the monitor put in its report's metadata under a well-known key — an LLM monitor using Scout's `message_numbering` in its prompt gets cites for free.

## Two modes: replay and read

Both consume the same validation set, because both key results by step id.

| Mode | What runs | When |
|------------------------|------------------------|------------------------|
| **replay** | reconstruct steps, run the monitor, one result per step | you changed the prompt, the model, or the monitor's logic |
| **read** | walk the transcript's recorded `MonitorEvent`s, one result per event | you want to know how the monitor behaved in the run it was attached to |

Read mode costs no inference and is what makes "run the eval observe-only, then look" a real workflow rather than a slogan. It is also the only mode that sees `outcome` — what the protocol actually did with the report — so "how often did `defer_to_trusted` defer" is a read-mode query. Scout's `EventType` literal gains `"monitor"` so the transcript loader can filter for these events.

Read mode also gives the honest check on replay itself: replay the monitor over a log it was attached to, and the two modes should agree wherever the monitor is deterministic. Where they do not, the reconstruction is wrong, and that is a test worth shipping.

## The workflow

1. **Write** the monitor as `monitor.md` describes. Its unit tests use `replay_monitor()` from `inspect_monitor` over a handful of message lists — no Scout, no eval.
2. **Replay** it over a corpus with `as_scanner()` and look at what it flags in Scout View.
3. **Label** from the results view — each step is a row — building a validation set with `dev` and `test` splits. Scout's existing case editor does this; steps appear as results rows, so no new labelling gesture is required for the first version.
4. **Validate**: precision, recall, F1, balanced accuracy over the `dev` split. Change the prompt; bump the monitor's version; re-scan; compare. This is Scout's existing loop.
5. **Calibrate** thresholds (below) if the monitor is an `Observation`.
6. **Configure** the protocol with those thresholds and attach it to the eval — observe-only first.
7. **Read** the resulting logs in read mode to confirm the deployed behaviour matches the replayed one, then let it act.

Steps 2–4 are exactly what a scanner author does today. The monitor-specific parts are the adapter in step 2 and calibration in step 5.

## Calibration

`monitor.md` insists thresholds live in protocols, not monitors, because a threshold needs a benign score distribution and a monitor looking at one step has never seen one. This is where the distribution comes from.

**From a benign corpus.** Replay an `Observation` monitor over transcripts known to be benign. The results dataframe's `value` column *is* the benign distribution. A budget becomes a threshold by percentile: "audit the top 1%" is the 99th percentile of that column, per dimension when suspicion is structured.

**From a labelled corpus.** Replay over a corpus with numeric or boolean step labels. Scout's `gte` predicate against a numeric target is a threshold; sweeping it gives the precision–recall curve, and the operating point is a choice the author makes with the curve in front of them rather than a constant in a prompt.

A helper closes the loop:

``` python
thresholds = calibrate(results, budget=0.01)          # percentile per dimension
thresholds = calibrate(results, target_recall=0.95)   # from labels
Task(monitor=trusted_monitoring(suspicion_monitor(), audit_threshold=thresholds["sabotage"]))
```

It is ordinary pandas over a Scout results dataframe and lives in Scout. What matters more than the helper is that the *inputs* to it — recorded scores, including ones a protocol ignored — are produced by the runner as a matter of course, which is why `monitor.md` records them.

The calibration corpus should be held out from the validation set's `test` split, and a threshold derived from one model's scores is not a threshold for another model's; both are ordinary ML hygiene rather than framework concerns, but the docs should say them.

## Monitors as scores

`monitor.md`'s open question 11 asks whether a monitor can produce a `Score` beside the task's own scores. It can, without touching scoring:

``` python
Task(scorer=[my_task_scorer(), as_scorer(as_scanner(suspicion_monitor(), unit="transcript"))])
```

`as_scorer()` already turns a transcript scanner into an Inspect scorer. The transcript-grain adapter reduces the monitor's per-step reports to one value, so the monitor's suspicion appears in the log as a score with the usual metrics, and the flagged steps travel as `scanner_references` in the score metadata, which Inspect View already renders. Nothing in `inspect_ai.scorer` changes.

## Cost and parallelism

An LLM monitor over a corpus is one inference call per eligible step, which is many more calls than one per transcript. Three things keep it tolerable:

- **Incremental monitors are cheaper to replay**, not just to run — the design's insistence on classifying the newest turn and folding into state means replay cost is linear in steps rather than quadratic, and the adapter's per-transcript store is what makes that work.
- **Stage filtering happens before loading.** A `BeforeToolCall` monitor's scanner declares the content it needs from the monitor's stage annotation, so Scout loads only what the stage reads.
- **Parallelism is across transcripts**, as it is for any transcript scanner, and within a transcript the walk is sequential by necessity. A stateless monitor could fan out within a transcript, but declaring statelessness is a claim the framework cannot verify, so the first version does not offer it.

Monitor inference in replay is charged to the scan, never to anything resembling an agent limit, which is the replay form of the budget exemption approvers have in an eval.

## What this asks of the other documents

- **`monitor.md` and `monitor-reference.md`:** `MonitorEvent.step_id`, recorded live by the runner. Open question 5 (calibration) and open question 11 (monitors as scores) are answered here and retire there.
- **`inspect-core.md`:** the events-based reconstruction wants `ModelEvent` and `ToolEvent` in core. Not required, but it is a concrete consumer for the first open question.
- **Scout:** `Result.subject`; expansion of subject-bearing results into rows; `"monitor"` in `EventType`; the read-mode scanner; `calibrate()`; and, later, a step-level labelling gesture in the transcript view.

## Open questions

1. **Does `subject` belong on `Result` or on `ResultReport`?** The result is what a scanner author constructs, so it is the natural home; but expansion is a recorder concern, and a subject the recorder then copies into `input_ids` is a small duplication. Result, unless the recorder has a reason.
2. **What does an expanded row's `input` hold?** Parent transcript id plus subject is the proposal; whether the view needs the step's messages materialised for rendering is a viewer question.
3. **Should `unit="transcript"` reduce by max or by strongest?** Max suspicion for observations and strongest recommendation are the obvious defaults and match `monitor.md`'s composition rules; a protocol may want the outermost layer's decision instead, which the adapter can take from its own report.
4. **Replaying a bridged agent's log.** A `claude_code` or `codex` transcript has no `ToolEvent`s of Inspect's own, so replay is messages-only even from an eval log. That is fine — it is the deployment those monitors face anyway — but the fidelity table should say so.
5. **Does replay honour `portable=True`?** Running a portable monitor through the same restricted `Host` the proxy would use is the enforcement `monitor-deployment.md` argues for, and replay is the cheapest place to do it. Probably yes, as an option on `as_scanner()`.
6. **Step-level labelling in the transcript view.** Results rows suffice for a first version; a "this tool call was bad" gesture on the transcript itself is the natural way to build step sets and needs Scout View work.
7. **Splits and calibration.** Whether `calibrate()` should refuse to read a split that is also used for validation, or merely document the hygiene.
