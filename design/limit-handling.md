# Limit precedence and ownership

## Overview

Inspect's token, cost, turn and message limits keep their per-kind trees,
and each limit is stamped with a global entry number when it is entered. A
model call is recorded into every kind, its turn included, before one check
over the token, cost and turn trees raises every limit that has been
reached, whatever its kind. When several
limits are reached together (by one call, by concurrent calls in a task
group, or by a sandbox bridge's requests), Inspect does not choose among
them: it raises one `LimitExceededError` whose new `limits` attribute lists
every one of them. Its ordinary fields (type, value, limit, message,
source) come from the top-ranked of them (token, cost and turn limits
first, then message limits, the earliest entered first within each), and that
ranking is used only to fill single-valued records such as the sample's
recorded limit and the error `run()` returns.

A limit error is handled only by the code that entered every limit in it.
`run()` and `apply_limits()` catch an error whose limits are all their own
or entered inside them (in the scope's own context, nested scopes
included), and return it (`run()` without a `limits` list,
which returns only the state, catches none). Tools, handoffs and bridged host tools turn into a
message an error whose token, cost and turn limits were all entered inside
the call (a message limit raised in the call measures the call's own
conversation, so it counts as the call's own, as today). Every other limit
error passes on with every limit in it (a tool passes it as one combined
error, as it already unwraps groups today) to an owner that does own all
of it: an enclosing `run()`, the sample, or a runtime such as
inspect_swarm. Suspending a kind of limit hides
that kind from the calls in the block: approval, review and sentinel calls,
which suspend token, turn and cost limits, neither charge nor check them,
as today. Once the sandbox bridge has kept a limit, it refuses every new
request and host-tool request at entry, whatever is suspended; work
already admitted stops only at reached limits on its own path.

For token, cost and turn limits, the limit nodes' own state, not the errors
they raise, is the record of what happened. Once reached, such a limit
refuses every later model call dispatched in its scope.
Under a cost limit, a call to a model with no price of its own is refused
before dispatch. Failed attempts, calls cancelled in flight and responses
that report no usage are not charged, as today, so they can take spend past
a cost limit; failing calls that report no usage is left to a separate
design. A limit error that reaches its owner stands. When
none does, each owner raises its own limits that are exceeded when it
ends normally: an
`apply_limits()` scope the limits it entered, and the sample its own limits
once all of its work, background cleanup included, has finished (except on
a resume for scoring). So, within a running attempt, a token, cost or turn
limit error that some handler catches and drops usually comes back at the
next refused call, or, if the limit is exceeded, at its owner's exit; the
design lists the cases where it does not in one place ("Recovery
boundaries").

Together these rules let a runtime that runs several agents catch the sample's
limit error, stop its agents in an orderly way, and re-raise the error.

## Why

inspect_swarm builds its cost caps, cost shares, member limits and stop levers
as nodes in Inspect's limit trees (inspect_swarm's `design/swarm-limits.md`).
Its edge cases all come from the same few interactions in Inspect:

- **Token before cost.** After a call, Inspect records the call into both
  trees, then checks the token tree, then the cost tree. A call that crosses a
  token limit and a cost limit always raises the token error. The cost limit
  is checked only at the next pre-dispatch check, even when it encloses the
  token limit. For example, a swarm member whose own token limit and the
  swarm's cost cap are crossed by one call ends on its token limit, and the
  cap stops nobody until another member calls a model.
- **No order between trees.** Inside a tree, the outermost reached node
  raises (root first). Between trees there is no order, because the trees do
  not know about each other, so a consumer whose limits span kinds cannot
  rely on the outer one raising.
- **A turn is recorded after the call's check.** A generation's turn is
  recorded only after its token and cost check passes. A caller that catches
  a child token or cost limit and calls again makes calls that never advance
  an enclosing turn limit.
- **The bridge compares limits within one tree.** The sandbox bridge keeps
  the first limit error its generations reach. A later one replaces it only
  if it comes from an ancestor in the *same* tree, or from one of the sample's
  own limits. A cost-tree error therefore hides a later token-tree error from
  an enclosing `run()` limit, token share or cap, and the other way round.
  From an exception group it takes the *first* limit before comparing at
  all.
- **Unpriced calls skip cost checks.** An unpriced call never adds to a cost
  limit and never checks one. A cost limit that a concurrent priced call has
  reached is not raised after it, and an unpriced model that the start-time
  check does not cover (a subagent's model, or any model an agent
  resolves by name) can be called without bound under a cost limit. So can a priced model whose provider
  returns no usage, which this design leaves to a separate one (see "Not
  this design").
- **Groups are reduced before they are compared.** A task group's errors
  are reduced to the first in several places before any limit-aware code
  sees them, and a sentinel wraps a limit its monitor reached in another
  error type. Either way an outer limit can be dropped in favour of an inner
  one or hidden from its owner.
- **Limit errors are consumed by code that does not own them.** A tool maps
  any `LimitExceededError` to a tool error, a handoff catches any, and a
  bridged host tool answers any as a tool error. A sample limit reached inside
  a tool is raised again only at the next model call. If no call follows, the
  sample completes normally with the limit's event in its transcript but no
  limit recorded.

Each rule is local and each fix is local, so consumers can only learn the
combined behaviour case by case: the swarm's design lists its accepted losses
and promotions one by one. The aim here is a small set of rules that a
consumer can rely on without studying these interactions.

## Goals and non-goals

### Goals

- One rule for several limits reached together, within one check, across
  overlapping calls, for a request refused before dispatch, inside
  exception groups, and in the sandbox bridge: one error that holds them
  all, with one order to fill single-valued records.
- One rule for the order in which usage is recorded and checked, for every
  kind of model call: ordinary, suspended (approval, review, sentinel),
  unpriced, native compaction, bridged.
- One suspension rule: a suspended kind is neither charged nor checked.
- One ownership rule: which code may turn a limit error into something other
  than an exception.
- A stated guarantee that a runtime can catch a sample limit, stop in an
  orderly way and re-raise it.
- A cost limit refuses a call to a model with no price before dispatch.
  Failed attempts, cancelled calls and responses that report no usage stay
  uncharged, as today, and that overshoot is stated.
- A list of what inspect_swarm can then delete or simplify.
- Keep `token_limit()`, `cost_limit()`, `turn_limit()`, `message_limit()`,
  `apply_limits()`, `run(limits=...)` and their signatures.

### Non-goals

- Hard limits, or reserving budget for calls in flight. A limit is still
  overshot by the calls already dispatched when it is reached.
- Time and working limits. A time limit is a cancel scope that raises where
  it was entered. A working limit is polled at the sample's root and ends the
  sample by cancellation. Neither gets an entry number (see "Other limit kinds").
- Changing message limits' leaf-only, per-conversation check.
- A public API for custom limit nodes, or a multi-kind limit object.
- Changing what `SampleLimitEvent` is emitted for (see "Not this design").

## Current behaviour

### Who enters limits

A survey of this repository, inspect_swarm, inspect_swe, inspect_sentinel,
inspect_petri and inspect_evals finds these sources of limit nodes:

- The sample runner enters the sample's limits in this order: token, cost,
  message, turn, time, working (`src/inspect_ai/_eval/task/run.py:3219-3232`).
- `apply_limits()` enters a list of limits in list order
  (`src/inspect_ai/util/_limit.py:151-187`). `run()` uses it with
  `catch_errors=True` (`src/inspect_ai/agent/_run.py:96-111`), as do
  background deepagent subagents
  (`src/inspect_ai/agent/_deepagent/agent_tool.py:768-780`). `as_tool()`
  (`src/inspect_ai/agent/_as_tool.py:76`), `as_solver()`
  (`src/inspect_ai/agent/_as_solver.py:72`) and handoffs
  (`src/inspect_ai/model/_call_tools.py:1313`) use it without catching.
  Synchronous deepagent subagents go through `run()`
  (`agent_tool.py:625-632`).
- User code can enter `with token_limit(...)` and the other factories
  directly.
- inspect_swarm subclasses `_TokenLimit`, `_CostLimit`, `_TurnLimit` and
  `_MessageLimit`. It overrides `record()` (token, cost), `_check_self()`
  (token, cost, turn) and `check()` (message), and it reads
  `token_limit_tree.is_suspended()`.

Errors are consumed in these places:

- **Native tools.** `tool_call_error()` maps any `LimitExceededError` to
  `ToolCallError("limit", "The tool exceeded its <type> limit of <n>.")`
  (`_call_tools.py:2035-2041`).
- **Handoffs.** `agent_handoff()` catches any `LimitExceededError` and appends
  a user message (`_call_tools.py:1308-1317`, `:1345-1352`).
- **Bridged host tools.** A deciding limit becomes a `ToolError`
  (`src/inspect_ai/agent/_bridge/sandbox/host_tool.py:517-541`).
- **Other sandbox services.** A raw limit error from a sandbox service method
  is routed to the sample with `ActiveSample.limit_exceeded()`
  (`src/inspect_ai/util/_sandbox/service.py:595-616`); only the human agent's
  service uses this path.
- **Other packages.** inspect_sentinel's runner and inspect_petri let limit
  errors propagate. inspect_evals' `core_bench` tool re-raises them.

### Trees, recording and checking

- Each of the six kinds has its own `_Tree`: a ContextVar holding the leaf,
  with each node pointing to its parent of the same kind
  (`_limit.py:1038-1084`). Nodes of different kinds have no link to each other.
- Token, cost and turn usage is recorded into the leaf and every ancestor
  (`_TokenLimit.record`, `_CostLimit.record`, `_TurnLimit.record`). Checks run
  from the root to the leaf, so the outermost exceeded node of that tree
  raises (`_limit.py:1163-1172`, `:1250-1259`, `:1334-1343`).
- Message limits check only the innermost node, against the length of the
  conversation being checked (`_limit.py:780-794`, `:1417-1438`).
- After a provider call, `record_and_check_model_usage()` records the call
  into the token tree (unless suspended) and its cost into the cost tree (when
  priced, and unless cost is suspended). It then runs `check_token_limit()` and, only for a priced call,
  `check_cost_limit()` (`src/inspect_ai/model/_model.py:3934-3947`).
- Before each provider attempt, `_check_limits_before_dispatch()` runs
  `check_token_limit(raise_for_equal=True)`, then
  `check_cost_limit(raise_for_equal=True)`, then the `dispatch_guard()`
  checks. The guard checks are skipped while token limits are suspended
  (`_model.py:3898-3910`). Callers: each generate attempt, after the cache
  lookup (`:1850`, `:1905`), native compaction (`:1581`), and the start of
  every bridged request (`src/inspect_ai/agent/_bridge/util.py:1462`).
- A turn is recorded once per top-level `generate()`, after it completes and
  including cache hits, and is then checked with `>` (`_model.py:2198-2204`,
  `_limit.py:823-838`, `:1273`). That is in the outer frame, after the inner
  generation has already recorded and checked its usage (`_model.py:2153`).
  If that check raises (a child token or cost limit), no turn is recorded:
  under `turn_limit(1)`, three calls that each raise a child `token_limit(1)`
  and are caught leave the turn count at 0 (spike). Native compaction records
  no turn. Turns are never checked before dispatch, so `turn_limit(N)` makes
  N+1 generations and raises after the last one. The bridge checks turns,
  with `>`, at the start of each request
  (`src/inspect_ai/agent/_bridge/sandbox/service.py:113`).
- The cost of a call is `model_usage_cost()` (`_model.py:3997-4059`). When
  the provider reports that other models served the call
  (`ModelAPI.served_model_usage()`), and each of them has cost data, the
  call is priced from them before the called model's own cost data is
  consulted (`:4026-4056`). OpenRouter reports this for routers such as
  `openrouter/auto` (`_providers/openrouter.py:190-200`), which have no
  entry in the model database, so a router call is priced today from its
  serving models alone. Otherwise the cost is `None` when the called model
  has no cost data. Before the eval starts, and for each
  task enqueued later, `resolve_model_costs()`
  (`src/inspect_ai/model/_util.py:67-98`, called at
  `src/inspect_ai/_eval/eval.py:883` and `:1377`) requires cost data for the
  task's model and every model of its model roles when a cost limit is set,
  and raises `PrerequisiteError` otherwise. A role can serve suspended calls
  only: the in-process sentinel host resolves its monitor model from the
  `monitor` role (`_HostNative._resolve()`,
  `src/inspect_ai/_sentinel/_dispatch.py:545-550`). Models
  resolved later (a subagent's `get_model()`, an approver or review model
  given by name, a swarm member's model) are not covered.
- A call whose usage is missing records nothing into token or cost
  limits: the inner generation records usage only when `output.usage` is
  set (`_model.py:2152`), and native compaction only when its `usage` is
  (`:1595`). Some providers read usage a response left out as zero:
  Mistral's streams without a usage chunk (`_providers/mistral.py:646-652`),
  SageMaker's stream assembly (`_providers/sagemaker.py:790-791`) and Grok's
  protobuf conversion (`_providers/grok.py:686`), which record zero.
- `suspend_token_limit()`, `suspend_turn_limit()` and
  `suspend_cost_limit()` stop recording *and* checking for their kind
  (`_limit.py:620-646`, `:832-856`, `:696-757`), including in `cost_limit()`
  scopes opened inside the block; `_check_limits_before_dispatch()` therefore
  skips cost for a cost-suspended call. `suspend_limits()` (`:963-983`)
  suspends cost, token, turn and working limits together. In-process
  sentinel dispatch (`src/inspect_ai/_sentinel/_dispatch.py:335`), the
  sentinel sidecar's result lookup
  (`src/inspect_ai/_sentinel/_sidecar/_lookup.py:197`, `:258`), tool
  approval (`src/inspect_ai/approval/_apply.py:66`) and tool review
  (`src/inspect_ai/review/_apply.py:43`) run under it, so their model
  calls are charged to and refused by no token, turn or cost limit. Model
  and role usage still record the suspended spend.
- Failed attempts are not charged. When an attempt raises (an HTTP error
  response, a timeout, a connection reset, a cancellation), the attempt's
  `ModelEvent` is completed with the error and no usage is recorded
  (`_model.py:1994-2042`); timeouts are always retried, other errors as
  `should_retry()` decides, and the retry policy has no attempt limit unless
  `max_retries` or `timeout` is set (`_model.py:2231-2246`,
  `src/inspect_ai/model/_retry.py:70-74`).
- `apply_limits()` catches only a bare error whose `source` is one of its
  limits (`_limit.py:181-187`).
- `run()` returns `(state, None)` from inside its `apply_limits()` block
  (`src/inspect_ai/agent/_run.py:97-105`) and reads
  `limit_scope.limit_error` only after the block (`:108-109`). An error
  raised as the block exits and suppressed by it would leave the pending
  `return` in force.
- Groups are reduced to their first member before any limit-aware selector
  sees them:
  - `tg_collect()` runs its tasks under `unwrap_exception_group("first")`,
    which raises the group's first member and drops the rest
    (`src/inspect_ai/_util/_async.py:44-78`, `:81-124`).
  - `_apply_response_filter()` reduces a filter's group of only limits,
    terminations and refusals to its first leaf; a group mixing them with
    any other error becomes a `ResponseFilterError`
    (`src/inspect_ai/agent/_bridge/util.py:515-527`).
  - `collect()` uses `unwrap_exception_group("single")`, which unwraps only a
    one-member group, so it keeps every candidate
    (`src/inspect_ai/util/_collect.py:32`).
- In-process sentinel execution wraps any exception escaping a monitor or
  protocol in `SentinelFailure(error)` (`src/inspect_ai/_sentinel/_dispatch.py:350-351`).
  A limit reached by a monitor's model call therefore leaves `generate()` as
  a `SentinelFailure`. Native tools unwrap it when the decisive error is a
  limit (`_sentinel_exception()`, `_call_tools.py:186-193`), and so does the
  sample runner (`run.py:2947-2949`). `apply_limits()` and the bridge's
  `_forward_provider_errors()` do not, so the bridge answers it as an
  ordinary error and keeps no limit.
- The sample runner flattens an escaping exception to its first leaf
  (`run.py:3435`, `src/inspect_ai/util/_anyio.py:8-9`). It records any
  `LimitExceededError` as the sample's limit, whatever its source
  (`run.py:3455-3462`).
- A checkpoint resume restores the sample roots' usage, then checks token,
  cost and turn in that order
  (`src/inspect_ai/util/_checkpoint/sample_runtime.py:222-225`).

*Spike* (a script in the scratch directory, mockllm priced at \$10 and 2
tokens per call, run against this branch's base):

| Case | Result |
|---|---|
| `cost_limit(5)` around `token_limit(1)`, one call | raises the token limit |
| `cost_limit(5)` around `cost_limit(1)`, one call | raises the outer cost limit |
| `token_limit(1)`, `cost_limit(5)`, call inside `suspend_token_limit()` | token usage 0, cost usage 10, raises the cost limit |
| unpriced model under `cost_limit(0.001)`, two calls | no error, cost usage 0 |
| `run(agent, limits=[token_limit(1)])`, agent calls in a task group | the owned limit escapes `run()` as an `ExceptionGroup` |
| `cost_limit(15)`, three calls each inside a child `token_limit(1)` | two calls made, \$20 charged, the third refused by the cost limit before dispatch |
| `turn_limit(1)`, three calls each inside a child `token_limit(1)`, each error caught | three calls made, turn usage 0 |

### The sandbox bridge

- Each bridged request runs `_forward_provider_errors()`
  (`service.py:107-169`). It checks turns. If a limit is already kept, it runs
  the pre-dispatch check, so that a reached enclosing limit can replace the
  kept one, and replies with the kept limit. Otherwise it runs the generation
  under `_refuse_after_a_recorded_limit()`, a `dispatch_guard()` that raises a
  copy of the kept limit (`service.py:172-193`).
- On a limit error, `_first_control()` takes the first limit of an exception
  group (`service.py:241-260`). The bridge keeps it if nothing is kept yet, or
  if `_encloses()` says it encloses the kept one: it is an ancestor in the
  same tree, or a sample root while solvers run (`service.py:196-238`).
- `sandbox_agent_bridge()` raises the kept limit after the agent unwinds or
  returns. If an enclosing cancellation is pending, it is delivered first
  and the kept limit is lost
  (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:353-405`).
- Bridged host tools run under the same guard (`service.py:451-466`). A limit
  their model calls reach is answered as a tool error and never kept
  (`host_tool.py:517-541`).

## Design

### The rules

1. **Trees and entry numbers.** Token, cost, turn and message limits stay
   nodes of their per-kind trees, as today. Each node also gets a global
   entry number when it is entered, increasing across kinds and tasks; it
   is used only to rank limits (rule 4). Each tool call, handoff, bridged
   host tool and `apply_limits()` scope sets a scope marker in a
   ContextVar while it runs; tasks started inside it inherit the marker,
   and each limit node records the marker current at its entry. Nested
   scopes keep their membership in the scopes around them, so a node
   entered in an inner scope (an `as_tool()` agent's limits inside a tool
   call, a limited adapter inside a `run()`) also counts as entered
   in each enclosing scope's context, while a sibling scope's nodes stay
   foreign. That is how ownership (rule 6) tells a node entered in a
   scope's own context from one a sibling task entered under the same
   parent; the representation is the implementation's choice.
2. **Record, then check.** After a provider call, Inspect records the call
   into every node that meters it (for a top-level generation, its turn
   too), then runs one check. Before a provider call, it runs the same
   check, with `>=` in place of `>`. A generation served from the cache
   records its turn and runs the same check after it.
3. **One check.** The check walks the token, cost and turn trees and raises
   every limit that has been reached, whatever its kind. A
   turn limit takes part in the pre-dispatch check too. Message limits keep
   their own check. After a call the check uses `>`, so it raises the nodes
   the call *exceeded*; an outer node the same call only *reached* (its
   usage now equal to its budget, or a turn limit at its Nth generation)
   does not raise there, so an inner node the call exceeded raises
   without it, and the outer one is raised by the next pre-dispatch check
   (`>=`). The message check runs before this
   check, so a reached message limit can raise ahead of a reached token,
   cost or turn limit. When the check finds several nodes to raise, it
   raises them together as one combined error (rule 4).
4. **Combine, don't choose.** Where several limit errors meet (one check
   that finds several nodes, a group of limit errors, the bridge's
   requests), Inspect raises or records one combined `LimitExceededError`
   whose `limits` lists every one of them. No owner decides by choosing one
   of them. The combined error's ordinary fields, and every other
   single-valued record (`EvalSample.limit`, the error `run()` returns, a
   tool error's text, inspect_swarm's `ended_by`), come from the top-ranked
   limit: token, cost and turn limits first, the one with the smallest
   entry number (the earliest entered) winning among them; then message
   limits, again by entry number; then limits with no entered token, cost,
   turn or message node (a `custom` limit, a time limit, a node never
   entered). Generic first-error reductions (`tg_collect()`,
   `unwrap_exception_group("first")`) are unchanged, and so is
   `decisive_sentinel_exception()`, which reduces errors escaping a
   sentinel monitor, whose calls reach no token, turn or cost limit
   (rule 5).
5. **A suspended call is invisible to the kinds it suspends.** Inside
   `suspend_token_limit()`, `suspend_turn_limit()` or `suspend_cost_limit()`
   (or `suspend_limits()`, all of them), limits of that kind neither record
   nor check the calls made in the block, and the unpriced-model refusal
   (rule 9) skips a call while cost is suspended. Message limits are
   still checked.
6. **The owner handles its error, all of it.** Code turns a limit error
   (bare, combined, or a group of limit errors) into a message, a tool
   error, a reply or a return value only when it owns every limit in it.
   Otherwise it lets the whole error propagate unchanged. `apply_limits()`
   owns its own limits and every node *inside* it: one entered in the
   scope's own context (its task and the tasks started inside it, nested
   scopes included) while it was open, whatever its kind; the node carries
   the scope's marker (rule 1). A sibling task's limit that reaches a scope belongs to the
   sibling and propagates. `run(limits=None)`, which can return only the
   state, catches nothing. A tool, handoff or bridged host tool owns the
   token, cost and turn limits entered inside the call, by the same test,
   and every message limit raised in the call, which measured the call's
   own conversation (see "Ownership").
7. **Each owner checks its own limits at exit.** A limit error that
   reaches its owner stands. When an `apply_limits()` scope ends normally,
   Inspect checks the token, cost and turn limits that scope entered, and
   no others, and raises those that are exceeded. The sample
   does the same for its own limits once its task group has finished, when
   its solvers returned normally and the attempt is not a resume for
   scoring. An enclosing limit is left to its own owner.
8. **The bridge keeps every limit it reaches.** The sandbox bridge keeps
   the set of limits any of its requests reached (generations and host
   tools alike), refuses every later request and host-tool request at entry
   with their combined error (rule 4), and raises that error when the
   agent has unwound. Work already admitted is stopped only by reached
   limits on its own path ("After a limit is kept").
9. **A cost limit refuses an unpriced model.** While a cost limit is active
   and cost is not suspended, a call to a model with no cost data of
   its own, a router included, is refused before dispatch. Nothing is
   marked. Failed attempts, cancelled calls and responses that report no
   usage are not charged, as today.

Rules 3 and 7 together make node state the record of limits. The design
does not try to carry every limit error intact through every handler that
can catch one (a fallback, a hook, a first-error reduction, a cancelled
delivery). A swallowed limit error costs time, not budget: the next call
under the limit is refused before dispatch, and if no limit error reaches
the limit's owner, that owner's exit check finds it if it is exceeded.
The cases where neither happens are listed once, under "Recovery
boundaries" ("The owner's exit check"). An unpriced-model refusal (rule 9) is not a limit
error, and nothing marks it: a handler that swallows one and calls the model
again is refused again, with nothing spent ("Unpriced models"). Where
Inspect's own
code changes how errors
travel (rules 4, 6 and 8), it is so that the right owner hears of every
limit reached, not so that the error survives.

The sections below specify each rule.

### Trees and entry numbers

`src/inspect_ai/util/_limit.py` keeps the token, cost, turn and message
trees as they are: a node's parent is the nearest enclosing node of its
kind, a task inherits its parent's trees, and the per-kind views
(`sample_limits()`, `token_limit_usage()`, the checkpoint code,
inspect_swarm's `record()` overrides) keep working. Entering a token,
cost, turn or message limit also stamps the node with a global entry
number, increasing across kinds and tasks, which it keeps after its block
closes. The number only ranks limits for single-valued records (rule 4);
ownership is decided by the trees (rule 6). Time and working limits get
no number.

The public addition is on `LimitExceededError`:

```python
class LimitExceededError(Exception):
    def __init__(self, type, *, value, limit, message=None, source=None,
                 limits: Sequence[LimitExceededError] | None = None): ...

    @property
    def limits(self) -> list[LimitExceededError]:
        """Every limit this error stands for, top-ranked first; [self] for one limit."""
```

A *combined error* is a `LimitExceededError` built from several limit
errors: its type, value, limit, message and source are the top-ranked
one's (rule 4's order; a limit with no entry number ranks last), and its
`limits` lists every one of them once, a combined member's own `limits`
flattened in, in rank order. Building one raises nothing and emits no
event; each member emitted its own `SampleLimitEvent` when it raised. The
sites that reduce an exception group whose first leaf decides (the sample
runner, the bridge's response filter and `_first_control()`) keep that
rule for a leading non-limit error and combine the group's limits when the
first leaf is a limit.

In the sample, the sample's own limits are entered first (token, cost,
message, turn), so its token, cost and turn limits rank ahead of every
agent or scoped limit in a combined error. Among themselves they rank in
entry order, so a call that crosses both the sample's token and cost
limits raises an error whose primary fields are the token limit's, as
today, with the cost limit in its `limits` too. The sample's message limit
ranks after every token, cost or turn limit, an agent's or a scoped one
included, and ahead of every message limit entered later. Two limits
entered in sibling tasks rank by whichever was entered first; that order
fills only records, never decides who handles an error. For limits passed to `run()` or `apply_limits()` the list
order sets their rank, which matters only for the primary fields.

### Recording and checking

- **Recording.** A provider call is recorded into every token and cost
  node that meters it, and a generation into every turn node, with no
  check; a suspended kind records nothing (rule 5).
- **The check.** One check walks the token, cost and turn trees, root to
  leaf, over the nodes whose kind is not suspended. After a call it raises
  every node past its budget (`>`); before a dispatch it raises every node
  at or past its budget (`>=`). One node raises its own error; several
  raise their combined error. Each node that raises emits its
  `SampleLimitEvent`, as today, where today a check stops at the first.
- inspect_swarm's token, cost and turn `_check_self()` overrides take
  part in the check; a node whose limit is `None` (an inspect_swarm lever)
  is never reached by count.
- **The owner's exit check** (rule 7) raises each of the owner's own token,
  cost and turn nodes that is exceeded; several raise their combined
  error.
- **Where it runs.** Every model call records, then checks once, where
  its accounting runs today (`src/inspect_ai/model/_model.py`):
  - A generation records its usage and its turn, then checks, in the
    retried inner call that already checks token and cost limits today, so
    usage hooks, telemetry and the response cache still see only an output
    that passed the token and cost check, as today. Turn limits move:
    today `record_turn()` checks them in the outer frame, after the hooks,
    telemetry and cache store have run (`_model.py:2157-2167`, `:2202`), so
    a generation that crosses a turn limit (for example one of two
    concurrent calls under `turn_limit(1)`) is reported to the hooks and
    cached before it raises. Now the turn check runs before them, so such a
    generation reaches no usage hook, telemetry or cache, like one that
    crosses a token or cost limit. Only one attempt succeeds, so a turn is counted
    once per generation; if the retry policy retries a successful attempt
    that failed after its check (a failing cache store), its usage and its
    turn are counted again, as usage already is today. A call that
    crosses a child token or cost limit therefore advances every enclosing
    turn limit before the child limit raises. The active sample's turn
    count, which the live control channel reports, includes every recorded
    turn, also when the check after it raises.
  - A cache hit records its turn, then checks, and is never refused before
    it is served: it records no usage, so it can raise a token or cost
    limit only if one is already exceeded (today a hit returns without
    that check), and a cached (N+1)th generation under `turn_limit(N)`
    raises, as today.
  - Native compaction records no turn; it records the usage it returns, as
    today, and then checks, also when it returns no usage, so a limit
    another call already took past its budget still raises. It does not
    fail for missing usage (a separate design, "Not this design").
  - A sentinel sidecar's recovery of a billed refusal records and checks
    only when the sidecar's judgment supplies billed usage, and records no
    turn, as today; its check is the same check.
- **Before dispatch.** The pre-dispatch check (`_check_limits_before_dispatch()`)
  runs the check with `>=`, then the unpriced-model check (rule 9). It
  runs per attempt after the cache lookup, and at the start of every
  bridged request. `dispatch_guard()` and its ContextVar
  (`_model.py:3868-3893`) are removed, with the bridge's
  `_refuse_after_a_recorded_limit()` (`service.py:173-194`), which was
  their only user in this repository, inspect_swarm, inspect_swe and
  inspect_sentinel: a request the bridge has admitted is stopped by node
  state, since every provider call it makes refuses a reached token, cost
  or turn node before dispatch.
- **Turn limits.** `turn_limit(N)` allows N generations: the (N+1)th is
  refused before it is dispatched, with the message "Turn limit reached",
  where today it is made and raises after it returns (decision: Ransom,
  2026-11-12). Native compaction and bridged requests are refused once a
  turn limit is reached.
- `check_token_limit()`, `check_cost_limit()` and `check_turn_limit()` stay
  as checks of their own kind where one value changes (the
  `TaskState.token_limit` and `cost_limit` setters) and at the checkpoint
  resume, the one exception to combined checking ("Checkpoints").
- Message limits are unchanged: the innermost message node is checked at the
  start of `generate()` (`_model.py:1062`) and on every append to a limited
  conversation. A message check sees only that node, so precedence does not
  arise inside it. A message limit and a reached token limit at the same
  `generate()` raise the message limit first. That is fail-safe: the token
  limit stays reached and refuses the next dispatch (rule 3), or raises at its
  owner's exit (rule 7).

### Precedence

Rule 3 makes one call's result independent of kind, and rule 4 keeps every
limit reached: wherever several limit errors meet, the result is one error
that lists them all. Who handles it is decided by ownership (rule 6), never
by which limit ranks first. The rank only fills single-valued records.

| Where | Today | Now |
|---|---|---|
| One check after a call | token tree, then cost tree (priced calls only); the first node that raises | token, cost and turn trees, every call; every node that raises, combined |
| Pre-dispatch check | token, cost, then guards (guards skipped while tokens are suspended) | token, cost and turn trees, combined; no guards |
| `_apply_response_filter()`, a group of only limits, terminations and refusals (`agent/_bridge/util.py:515-527`) | its first leaf | its first leaf, or, when that is a limit, the combined error of its limits; a mixed group is still a `ResponseFilterError` |
| `apply_limits()` | catches a bare owned error only | with `catch_errors=True`, catches an error, bare, combined or a group, when every leaf is a limit error and every limit in it is the scope's own or inside the scope (entered in its own context; below); its `limit_error` is their combined error; otherwise the error propagates unchanged |
| Sample runner (`run.py:3435`) | first leaf of the group | its first leaf, or, when that is a limit, the combined error of its limits; `EvalSample.limit` from the combined error's primary fields |
| `decisive_tool_exception()` (`_call_tools.py:2052`), for native tools and a bridged host tool's `_raised()` (`host_tool.py:527`) | termination, unexpected error, first limit, first leaf | termination, unexpected error, the combined error of all the limits, first leaf; the caller then applies the ownership test to every limit in it ("Ownership") |
| `decisive_sentinel_exception()` (`_call_tools.py:196`) | termination, other error, first leaf | unchanged: a monitor's calls run with token, turn and cost limits suspended, so the only limit it can reach is a message limit ("Sentinel failures") |
| Bridge `_first_control()`, a group of only limits and refusals | its first leaf | its first leaf, or, when that is a limit, the combined error of its limits: a leading refusal still wins |
| Bridge `_first_control()`, any other group | its first limit (other errors are logged) | the combined error of its limits (other errors are logged) |
| Bridge kept limit | one, replaced by a same-tree ancestor or sample root | every limit reached, kept as a set; refusals and the unwind raise their combined error |

Each site keeps its existing ranking of limits against non-limit errors.
Only the handling of several limits changes: they are combined instead of
reduced to one. Ranking limits *above* other errors (or below them)
everywhere is a separate question and is left out (see "Not this design").
A limit that a non-limit error displaces at one of these sites is not lost
for good: it stays reached, so the next dispatch is refused (rule 3), and its
owner's exit check raises it if it is exceeded and that owner ends
normally (rule 7), except in the cases under "Recovery boundaries".

Generic reductions are left alone. `tg_collect()` and
`unwrap_exception_group("first")` (`src/inspect_ai/_util/_async.py:44-124`)
still raise a group's first member, and `collect()` still unwraps only a
one-member group. When `tg_collect()` drops an outer limit in favour of an
inner one, the outer limit is still reached: the next call under it is
refused, and if its owner ends normally, its exit check finds it (see "Not
this design").

`apply_limits()` handles an exception escaping its body in one test, a
*covered exit*: every leaf of the exception is a `LimitExceededError`, and
every limit in it (each member of a combined error) is covered by the
scope. A limit is covered when it is one of the scope's own limits (of any
kind: a `time_limit()` or `working_limit()` passed to `run()` or
`apply_limits()` is the scope's own, as today), or a node inside the scope
(rule 6): one entered in the scope's own context, its task and the tasks
started inside it, while it was open, of any kind and whatever limits the
scope entered (the node carries the scope's marker, rule 1). A node a sibling task entered is not inside the scope, even when it hangs
below the same enclosing node and its error reaches the scope's body. For a
covered exit, `limit_scope.limit_error` is set to the combined error and,
with `catch_errors=True`, the exception is swallowed. With
`catch_errors=False` (`as_tool()`, `as_solver()`, handoffs) the exception
propagates unchanged, a group as a group, as today, and each receiver
handles it as below. Anything that is not a covered exit propagates
unchanged: an unrelated error, a termination, a cancellation, an error
holding a limit of an enclosing or sibling scope (even beside the scope's
own), or a limit error whose source is unknown. A sourceless `custom` error
(documented in `docs/setting-limits.qmd:278-288`, and raised by
inspect_swarm members) is never covered, so a group holding a covered token
error and a sourceless custom error propagates, as it does today.

A caught error is always observable: it is returned, never dropped.
`run()` with a `limits` list, empty or not, returns `(state, error)` with
the combined error; a deepagent background subagent reads it from the
scope after its block, as today. `run(limits=None)` returns only the state,
so it has nowhere to report an error and catches nothing: every limit
error propagates from it, as today. Which limit ranks first does not matter
for catching: a group of the scope's own token limit and a cost limit
entered inside the scope is caught like any other covered group, and
`run()` returns their combined error, also when the scope entered only a
token limit. A bare
error from one of the scope's own limits, a time limit included, is caught
as today, also when it is raised as the limits exit (a time limit raises
from its cancel scope's exit), so `run(limits=[time_limit(...)])` and the
deepagent callers of `apply_limits()` keep returning their own time limit
error. A bare error from a descendant (a plain `with token_limit()` block
or an `as_solver()` limit inside the agent, whose error escaped it) is now
caught too and returned by `run(limits=[...])`, whatever the scope's
limits, where today it propagates. The error that
escaped is not compared with node state: a limit error that reaches its
owner stands ("The owner's exit check").

A request refused before dispatch, for example one that was queued for a
connection slot, the pause gate or a retry while another call reached a limit,
raises from the same check as a fresh call: every limit reached at that
moment.

Why combine: an owner can act on an error correctly only if it can see
every limit in it. Reducing several limits to one, by any order, means some
owner sees only part of what happened. If the inner limit is kept, its
owner catches it and continues while an outer budget is spent; if the
outer limit is kept, an inner owner never learns its own limit was reached
too; and if the reduction happens before the owner sees the error (the
bridge keeps one limit, a tool picks one leaf), a limit the owner should
not have handled can be dropped on the way. With every limit in the error,
an owner handles it only when it owns all of it, so the widest scope that
must end does end, and every scope it unwinds can see its own limit in
`limits`.

**Why message limits count as a tool's own.** Token, cost and turn limits
count cumulative spend, and that spend never decreases. Once one is
crossed, its budget is gone for every later call under it (rule 3), so a
tool error that hid a foreign one would only delay it to the next call. A
message limit checks one conversation's length against the innermost
message node (`check_message_limit()`, `src/inspect_ai/util/_limit.py:780`),
and nothing accumulates on the node. Inside an `as_tool()` agent, reaching
it means that sub-conversation got too long, not that the sample is out of
budget, so a tool error is the right outcome and the calling agent can
recover. Rule 3's promise that a reached limit comes back at the next call
does not apply to a message limit: the next call in a shorter conversation
under the same node is not refused. That is why message limits stay out of
the owners' exit checks, and why a tool or handoff
owns every message limit raised in its call. It is not a reason to let a
message limit hide a spent budget: when a message limit and a foreign
token, cost or turn limit meet in one tool's error, the tool does not own
all of it, and the whole error propagates. `apply_limits()` owns only the
message limits it, or a node inside it, entered, as today: a `run()` agent
is not a tool call, and the sample's message limit reached in its
conversation is the sample's.

The rank fills single-valued records with the more significant outcome:
a spent budget before a conversation's length, the outermost before an
inner one. So when a sample's message limit and a token limit come back
combined (one error, a group of limit errors, or the bridge's kept set),
the sample records the token limit in `EvalSample.limit`, and the message
limit is in the combined error's `limits` and in the transcript's
`SampleLimitEvent`s. A message limit checked first in a native
`generate()` still raises alone (rule 3), and the sample records it; the
runner does not reconcile it with node state.

### Suspension

Rule 5 states the suspension that already exists as one rule over the
trees: a suspended kind is neither charged nor checked.
Approval, review and in-process sentinel calls, and the wait for a sentinel
sidecar's result, run under `suspend_limits()` ("Current behaviour"), so
they record into and check no token, turn or cost limit, including in the
pre-dispatch check and in a `cost_limit()` opened inside the suspended
block. The check skips a node whose kind is suspended, so it keeps
that behaviour. What is new is the
unpriced-model refusal, which skips them too (rule 9): an unpriced approver,
reviewer or monitor model is not refused. For that exemption to hold, the
start-time price check no longer requires prices for role models, which it
cannot tell apart by use ("Unpriced models"). Their spend is still recorded
in model and role usage and in the sample's reported cost.

A consumer's own check on a node of a suspended kind is skipped with it,
since the check skips the node, as the per-kind checks skip it
today: inspect_swarm's closed stop gate on a member's cost node does not
refuse a call made by an approval or review callback that is already
running.

Message limits, which suspension never covered, are still checked as today
(decision: Ransom, 2026-11-17). What suspended calls can still do after
the sandbox bridge keeps a limit is under "After a limit is kept".

### Ownership

Rule 6 at the call boundaries. A call enters no limits of its own, so a
limit is *the call's own* when it is a token, cost or turn limit entered
in the call's own context (the call's task and the tasks started inside
it, which carry its scope marker, rule 1) while the call ran, a message limit (it measured the call's own
conversation, whichever node raised it, as
`test_agent_as_tool_respects_sample_limits` pins today), or a limit with
no entry number (a `custom` limit with no source, a time limit entered
inside the call), which keeps today's mapping. A limit error is *owned by the call*
when every limit in it (each member of a combined error) is the call's own.
Nested scopes keep their membership in the scopes around them (rule 1):
the limits an `as_tool()` agent enters in its own `apply_limits()` scope
inside the call are the call's own, and a limited adapter inside a
`run()` is inside that `run()`. A sibling call's or sibling
scope's limits stay foreign. The `as_tool()` and handoff cases in
`tests/agent/test_agent_execute.py` (the tool's own token limit is still a
tool error; a handoff still answers its own limit) pin this nesting.

- **`execute_tools()`.** `decisive_tool_exception()` returns, for a group
  whose deciding leaf is a limit, the combined error of every limit in it
  (a termination and an unexpected error still decide first, as today).
  If the error is owned by the call, it is mapped to the `limit` tool
  error as today, with the combined error's message (its top-ranked
  limit's). That covers `as_tool()` limits, any `with token_limit()` inside
  a tool, and message limits. An error that is not owned is handled like a
  termination raised in a tool: its `ToolEvent` is completed, its siblings
  in the stage are cancelled, and the error propagates out of
  `execute_tools()` as the combined `LimitExceededError`, not as a group:
  the per-call handler and the stage already re-raise a group as its
  deciding error (`raise_unwrapped()` at `_call_tools.py:334` and
  `:848-850`), which is now the combined error, and every receiver already
  handles a bare limit error. `tool_call_error()` itself is unchanged; the
  per-call `except` decides before calling it.
- **Handoffs.** For `agent_handoff()` the call starts before it enters
  the handoff's limits, and its `except LimitExceededError`
  (`_call_tools.py:1308-1317`) applies the same test: an error not owned
  by the call (one of its limits is a token, cost or turn limit entered
  outside the handoff) is re-raised. An owned error keeps today's handoff
  result, the handed-off agent's new messages followed by the "exceeded
  its <type> limit" message (`:1345-1352`), with the combined error's
  type. As today, only a bare error is caught; a group propagates through
  the handoff's `apply_limits()` unchanged, so a handoff's own limit
  raised in a group reaches the enclosing tool's test.
- **Bridged host tools.** `_raised()` (`host_tool.py:517`) uses the same
  test as `execute_tools()`, the call starting when the host tool starts.
  An owned error becomes a `ToolError` as today. Every limit of an error
  that is not owned is added to the bridge's kept limits ("The sandbox
  bridge"), and the CLI receives the same tool
  error text, so the scaffold sees no difference.

The case of a tool whose group mixes a message limit with a foreign budget
follows from this test alone. An `as_tool()` agent with no message limit
of its own runs two branches in a task group: one reaches the inherited
sample message limit, the other crosses a `run()` cost limit entered above
the tool. The message limit is the call's own; the cost limit is not; so
the call does not own the error, and it leaves the tool as one combined
error holding both. With
only the message limit's error, the tool replies with the message `limit`
tool error, as today.

`run()`, `as_solver()`, deepagent and `background()` already let foreign
limits through. The sandbox service's route of a raw limit error to the sample
is unchanged: the bridge never raises one through it.

### Sentinel failures

The in-process sentinel wrapper is unchanged: it still wraps any exception
escaping a monitor or protocol in `SentinelFailure`
(`src/inspect_ai/_sentinel/_dispatch.py:350-351`). Under rule 5 a monitor's
own model calls run with token, turn and cost limits suspended, so they
cannot reach one of those limits or be refused by one. The one limit a monitor can reach is a message limit: suspension
leaves message limits active, and `generate()` checks the innermost message
limit before dispatch (`src/inspect_ai/model/_model.py:1059-1062`,
`src/inspect_ai/util/_limit.py:780-794`), so a monitor whose own prompt
reaches an inherited message cap raises a message limit. It keeps today's
handling: the wrapper turns it into a `SentinelFailure`. A native tool
unwraps it as today (`_sentinel_exception()`, `_call_tools.py:186-193`).
From a native generate stage it reaches the sample runner as a
`SentinelFailure`, not a `LimitExceededError`, so the runner's
`except LimitExceededError` does not record it: `handle_error()` only
selects the inner monitor error for reporting (`run.py:2947-2949`), and the
sample ends in an error, with the ordinary error-retry handling and no
`EvalSampleLimit`, as today. In a bridge the outcome depends on the
request:

- In a bridged generation's generate stage (the sentinel run around the
  request's own generation), it becomes an ordinary error reply, with no
  kept limit.
- In the tool-call and tool-result stages a bridged request runs (the
  tool-call stage while approving the generation's calls,
  `src/inspect_ai/agent/_bridge/_approval.py:314`; the tool-result stage at
  the request's entry, `agent/_bridge/util.py:1463`), `_guarded()`
  unwraps a deciding monitor limit and re-raises it bare
  (`src/inspect_ai/agent/_bridge/_sentinel.py:1630-1647`), so the message
  limit reaches the request's error handling and joins the bridge's kept
  limits, as any limit (rule 8), and is raised with them when the agent
  unwinds.
- In a bridged host tool, `tool_call_error()` does not map it, so
  `_raised()` treats it as an unexpected error, which requests sample failure
  (`src/inspect_ai/agent/_bridge/sandbox/host_tool.py:517-532`, `:450-451`).
  When the agent unwinds, `_error_after_unwind()` selects a requested
  failure ahead of the kept limit (`sandbox/bridge.py:385-405`). So a
  monitor in an in-flight host tool that reaches a message limit ends the
  sample in an error, even when the bridge has already kept a token, cost
  or turn limit. That is the exception guarantee 4 makes for an exit
  decided by a non-limit error ("What a runtime can rely on"), and the
  priority is unchanged.

Message limits are outside the owners' exit checks, so a message limit
turned into an error reply (the generate stage) or a sample failure (a host
tool) is not recorded later; one the bridge kept from a tool stage is
raised when the agent unwinds. This design does not change either path.

### The owner's exit check

A limit error that reaches its owner stands: `apply_limits()` and the sample
runner record the error they receive (after the reductions in "Precedence")
and do not compare it with node state. Rule 7 covers the other case, where
no limit error reaches the owner because a handler swallowed it. It has two
call sites:

- `apply_limits()`, on a normal return: after the body returns, before it
  exits its limits, it runs the exit check over the limits it was given. Only its own limits can raise there, so one that does is
  caught when `catch_errors=True` (`run()`) and propagates otherwise
  (`as_solver()`, `as_tool()`, handoffs), as one raised in the body.
  Enclosing limits are not checked there. A sample limit that a handler
  inside a `run()` agent swallowed does not leave `run()` at its exit: it
  is refused at the caller's next call, or found by the sample's exit
  check, one step later, as for any swallowed error.
- The sample runner, when its solvers return normally (below).

**Recovery boundaries.** Within an attempt, a token, cost or turn limit
error that a handler swallowed comes back at the next call under the
limit, which is refused before dispatch, or, if the limit is exceeded, at
its owner's normal exit. This is the one list of where a swallowed limit
can still be lost; every other summary in this document points here:

- **A limit at exactly its budget** whose refusal was swallowed, with no
  later call: exit checks raise only exceeded limits ("What raises at
  exit").
- **A plain `with` block**: it has no exit check, so its limit is found
  only by a call made while the block is open ("Plain `with` blocks").
- **Background work that outlives its owner**: a scope's limit swallowed
  after that scope's exit check ("Background work that outlives its
  owner").
- **A resume for scoring**: that attempt has no sample exit check
  ("Limits swallowed during a resume for scoring").
- **A checkpoint restore**: it assigns the stored usage, so a limit that
  work before it reached and swallowed can be reopened ("Limits swallowed
  before a checkpoint restore").
- **A raised or removed budget**: a node counts as reached only under its
  current effective budget, so a `limit` setter or a live override that
  raises it lets calls through again.
- **Message limits** keep no state: a swallowed message limit error is not
  recovered, and a shorter conversation under the same limit can still
  dispatch.
- **An owner that does not end normally**: an exceeded limit swallowed
  before a later non-limit failure, termination or cancellation has no
  later call under it and no normal-exit check; the abnormal outcome
  stands (guarantee 4).

A limit error that does reach its owner can still leave out another limit
reached at the same time ("What the owner can miss").

**The sample's exit check.** Today the solvers run in `run()`, a task of the
sample's task group, whose `finally` cancels the group (`run.py:3394-3397`)
when `plan()` returns or raises (`run.py:3302`); the group is joined at
`run.py:3424-3425`, inside the `with` block that holds the sample's limits
(`run.py:3219-3232`). A `background()` worker can finish a priced call in
its cancellation cleanup, reach a sample limit there, catch the error and
return, after `plan()` has returned. So the check runs after all of the
sample's work has joined, and only when the solvers returned normally: it
covers the sample's token, cost and turn roots (`sample_limits()`), and an
attempt whose solvers raised, were cancelled or were interrupted keeps its
outcome. It raises
every root that is exceeded at exit, each with its `SampleLimitEvent`, as one
combined error (rule 4), and the existing `except LimitExceededError`
(`run.py:3455`) records it, `EvalSample.limit` from its primary fields.

Everything else is unchanged. A limit error that escapes the solvers is
recorded as it is today. A non-limit error (a group whose first leaf is
not a limit) goes to the error handling as today, so an error still outranks a
limit at the runner. A termination keeps its own `except` clause. An
operator interrupt and a limit delivered by cancellation (the working limit,
or a limit a sandbox service routes to the sample) keep their handling
inside `run()`, which sets the outcome before the join, so the exit check
does not run for them.

**A resume for scoring skips the sample's exit check.** It restores a spent
budget on purpose and runs no agent work: `restore_sample_runtime(...,
check=False)` reseeds the roots without checking them, and ReAct returns at
once (`src/inspect_ai/agent/_react.py:233-234`). The runner knows the
attempt kind: `_task_run_sample_attempt()` receives the `ResumeCheckpoint`,
whose `attempt` is `"resume_for_scoring"` for a checkpoint taken when the
agent completed (`src/inspect_ai/util/_checkpoint/resume.py:33-39`). On
that attempt the runner skips its exit check, as ReAct skips the agent.
The `apply_limits()` scope around the agent (`as_solver(react(...))`)
checks only its own limits, so the restored roots are not checked there
either. Pre-dispatch checks are unchanged, as today: a call made under a
spent restored root is still refused. What this leaves unrecorded is under
"Plain `with` blocks" below.

**What the owner can miss.** Because an error that reaches its owner
stands, the recorded error can leave out a limit that counts when something
replaces the error on its way out. Two cases do this:

- **Cleanup races.** A limit escapes, and while its task group unwinds, a
  sibling's call that was already in flight finishes in cancellation
  cleanup and pushes another limit over.
- **Adapter state copies.** `as_solver()` copies the agent's messages into
  the `TaskState` in a `finally` after the agent's own limits have exited
  (`src/inspect_ai/agent/_as_solver.py:72-79`), and that assignment checks
  the sample's message limit (`TaskState.messages`,
  `src/inspect_ai/solver/_task_state.py:274-275`). An agent whose token
  limit escapes after it added messages beyond an outer message limit
  therefore leaves `as_solver()` with the message limit, the token error
  as its context. No concurrency is involved, and it does so today.

In both cases the owner records the error that arrives, as the
exceptional-exit policy says, and does not look at the earlier one. For
the races: in `run(limits=[outer_cost, inner_token])`, one task can raise the token
limit while a sibling's cleanup pushes the cost limit over; `tg_collect()`
keeps the token error and `run()` returns it. At the sample, an inner limit
can escape the solvers while a background worker's cleanup pushes a sample
limit over; the sample records the inner limit. In every case the outcome
is still a limit, nothing is spent beyond the calls already in flight, and a
limit left reached refuses every later call under it (rule 3): an enclosing
limit pushed over in the race refuses the caller's next call, and its own
owner's exit check finds it if no call follows.

`run()` reads the scope's error after its block rather than returning from
inside it, so that an error the exit check raises and the scope catches is
returned rather than lost behind a pending `return` (today it returns
`(state, None)` inside the `with`, `src/inspect_ai/agent/_run.py:97-105`).
Synchronous deepagent subagents call `run()` and get the fix with it.
Background deepagent subagents already read the scope after their block
(`agent_tool.py:768-780`). `as_tool()`, `as_solver()` and handoffs enter
`apply_limits()` without `catch_errors`, so a limit raised at their exit
propagates.

**What raises at exit.** Each of the owner's own nodes raises if it is
exceeded (`> limit`), judged by the budget in force at exit. A sample that
used exactly its token budget, or took exactly its N turns, and returned is
not recorded as limited.

The accepted loss: a limit at exactly its budget whose refusal was
swallowed, with no later call under it, is not recorded at its owner's
exit, as today. That is mainly a turn limit's refusal of the (N+1)th
generation caught by user code, and the rare inspect_swarm race in which
a bridged member's kept refusal at the sample's turn budget is cut off by
a hard stop before the bridge unwinds. Spend stays bounded: the reached
limit refuses every later call under it (decision: Ransom, 2026-11-19:
"if someone swallows a turn refusal I'm not too worried that it is
unrecorded").

**Plain `with` blocks.** A `with token_limit(...)`, `cost_limit(...)` or
`turn_limit(...)` block entered directly, not through `apply_limits()` or
`run()`, gets no exit check, as today (decision: Ransom, 2026-11-17).
Automatic recovery of a swallowed limit error covers the limits of each
`apply_limits()` scope (`run()` included) and the sample's limits. Its author owns it and may catch its
error inside the block on purpose, which an exit check would raise again;
inspect_swarm also enters its member nodes this way (`_run_member()`,
through an `ExitStack`) and handles their errors itself. The rule for a plain block is therefore: while the block is
open, its reached limit refuses every call under it (rule 3), so an error
that a handler inside the block swallowed comes back at the next call. When
the block ends normally, no Inspect code checks its node: an enclosing
owner's exit check covers only that owner's limits. A
limit error that a handler swallowed and that no later call in the block
met is then lost, as today: for example ReAct's forced-compaction fallback
(`_handle_overflow()`, `src/inspect_ai/agent/_react.py:714-736`) can consume
the block's limit, and if the agent then returns without another call, the
block ends normally. Spend stays bounded: no call under the block runs past
the limit. An author who needs the outcome either way reads the node after
the block (`limit.usage` against `limit.limit`) or uses `apply_limits()`,
whose exit check covers its own limits.

**Background work that outlives its owner.** Work started with
`background()` inside a `run()` or `apply_limits()` scope runs in the
sample's task group by default ("What a runtime can rely on") and can keep
running after the scope has returned. It inherits the scope's trees, so its
calls still record into and are checked against the scope's nodes. The
scope's exit check has already run by then, so a limit of the scope that
the worker reaches afterwards and whose error the worker swallows is lost:
for example, `run(limits=[token_limit(1)])` returns at usage 0, its
background worker then uses 2 tokens and catches the error, and nothing
checks the closed `run()` node again. The sample's exit check covers only
the sample's limits, which pass under their own budgets. This is an
exception to automatic recovery, alongside plain `with` blocks, and the
design keeps that sample-scoped background lifetime on purpose (see "Not
this design"). Spend stays bounded: every later call the worker makes
under the node is refused (rule 3), and the sample's limits still apply.
A caller that needs the outcome makes the work finish inside the scope:
it opens a task group inside the agent body, within the scope's limits,
and joins it before the body returns, so the scope's exit check sees the
work's usage. A runtime that routes `background()` there sets the private
`background_target` (`src/inspect_ai/util/_background.py:28`) to that
group, as inspect_swarm does for each member; setting the target alone
does not order the join before the exit check, and neither `run()` nor
`apply_limits()` exposes it. A caller that inspects the node instead
(`limit.usage` against `limit.limit`) does so after the background work
has finished: when `run()` returns, the node can still show usage the work
has not yet added.

**Limits swallowed during a resume for scoring.** The same principle holds
for a scoring resume, which has no sample exit check. A limit reached and
swallowed during that attempt is not recorded: by a sample-start or
attempt-start hook, which the runner calls before the agent runs and so
before the checkpoint is restored (`run.py:3404-3421`; the hook may catch
it itself, and `_call_hook_safely()` re-raises a bare limit error but logs
and drops one inside an exception group, `src/inspect_ai/hooks/_hooks.py:1218-1236`), or by the task's `on_resume`
callback, which runs after the restore
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:147-160`). A limit
error that is not caught still ends the sample, as today. Spend stays
bounded: every later call under the reached limit is refused (decision:
Ransom, 2026-11-17).

**Limits swallowed before a checkpoint restore.** The same principle holds
for work that runs before a resumed attempt restores its checkpoint. The
sample's roots are entered when the attempt starts, but the checkpoint is
restored only when the agent first enters `checkpointer()`
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:134-152`). Work
before that point charges the roots: the sample-start and attempt-start
hooks (`run.py:3404-3421`) and any solver that runs before the agent. The
restore assigns the stored usage, as today ("Checkpoints"), so a limit that
this work reached and swallowed can be reopened by it: a hook that takes a
$1 cost limit to $1.10 and catches the error is followed by a restore at
$0.50, after which the limit allows another $0.50. A limit error that is
not caught still ends the sample. Spend stays bounded: work before the
restore is refused once it reaches the limit, and work after it is refused
again once the restored value reaches it, so a resume can spend about one
extra budget at worst, per entry of the checkpointer (decision: Ransom,
2026-11-18). The entered checkpointer is cached only after the restore,
the `on_resume` callback and its construction succeed
(`checkpointer_impl.py:148-178`), so a caller that retries a failed entry
of the same setup restores again and can spend one more `on_resume` (or
other work before the cache) per retry, which the counters do not keep.
No caller does this today: ReAct and the inspect_swe CLI agents enter once
and let a failed entry escape, and an ordinary sample retry builds a fresh
setup (`run.py:3130`). Spend is bounded by the caller's retries (decision:
Ransom, 2026-11-18). Model work before the restore is not
refused: solvers before the agent run again on every resume, so refusing
them would fail ordinary resumes.

### Token metering must not decrease

The exit checks and the pre-dispatch refusal read
a node's state after its error may have been lost, so they rely on metered
usage never decreasing as calls are recorded: a limit that has been reached
stays reached. Cost and turns only grow. A token limit's `type` can today be
an arithmetic formula over cumulative `input` and `output` tokens, with `+`,
`-`, `*`, `/` and unary minus (`_compile_token_formula()` and
`_TokenMetering.value()`, `src/inspect_ai/util/_limit.py:331-453`;
`docs/setting-limits.qmd:164`, `:461`). Some formulas decrease as tokens are
used: under `token_limit(10, type="input - output")`, two returns of 20 input
and 1 output tokens, then 1 input and 20 output tokens, take metered usage
from 19 to 0, so a swallowed error leaves a limit that refuses nothing and
does not count at exit.

A survey of this repository, inspect_swarm, inspect_sentinel, inspect_swe
and inspect_petri finds only `all`, `output`, `input` and non-negative
weighted sums such as `(input * 0.1) + output` in use. So formulas are
limited to that family: a *non-negative weighted sum*,
`c + a * input + b * output` with `a >= 0` and `b >= 0` (any constant `c`).
Its floor never decreases as either count grows.

`_compile_token_formula()` enforces the family by its grammar, at
construction. Its existing AST walk becomes a reduction of the expression to
three finite coefficients `(c, a, b)`, the formula `c + a * input + b * output`:

- a numeric constant `k` is `(k, 0, 0)`; `input` is `(0, 1, 0)`; `output`
  is `(0, 0, 1)`;
- unary plus keeps the coefficients and unary minus negates them;
- `x + y` and `x - y` add and subtract them;
- `x * y` is allowed only when one side reduces to a constant (its `a` and
  `b` are 0), and scales the other side's coefficients by it;
- `x / y` is allowed only when `y` reduces to a nonzero constant, and scales
  `x`'s coefficients by `1 / y`;
- anything else (a product or quotient of two expressions that both depend
  on `input` or `output`, division by zero, a non-finite coefficient) is
  refused.

The result must have `a >= 0` and `b >= 0`. Metering then evaluates
`floor(c + a * input + b * output)` from the coefficients, so what is
accepted is exactly what is metered. There is no sampling and no tolerance:
an expression outside the grammar, such as `input * output`,
`input / output`, `input - output` or a polynomial in `input`, raises
`ValueError` when the limit is built: "token limit: formula '<formula>' must
be a non-negative weighted sum of input and output, such as '(input * 0.1)
+ output'; formulas whose value can decrease as tokens are used are not
supported." Every token limit is built through `_TokenMetering`, so the check
covers `token_limit()`, `TokenLimit` (task and eval configuration and the
`--token-limit` string form), a `TokenLimit` read back from a log for a
retry, and inspect_swarm's member limits restored with
`token_limit(value, type=...)` (`inspect_swarm/src/inspect_swarm/_member.py:980`).

### Checkpoints

The checkpoint payload is unchanged. A checkpoint stores the sample roots'
usage, and a normal resume restores it into the roots and checks them:
`dump_sample_runtime()` writes the token usage, cost and turns
(`src/inspect_ai/util/_checkpoint/sample_runtime.py:47-96`), the
checkpointer stores that payload
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:624-633`), and
`restore_sample_runtime(check=True)` reseeds the roots and runs the token,
cost and turn checks, in that order, with `>`, then the working-limit check
of the current node and its ancestors (`sample_runtime.py:153-163`,
`:221-225`; called for a normal resume at `checkpointer_impl.py:147-152`).
The working check is unchanged.
An exceeded root therefore still ends the resumed attempt before it makes a
call. These ordered per-kind checks are the one exception to combined
checking (rule 3): the restore assigns the three counters together, and
the first kind that fails raises alone, so with several roots exceeded only
that one is in the error's `limits` and gets a `SampleLimitEvent`. A resume for scoring (`check=False`) runs no check, as today, and
the runner skips the sample's exit check on that attempt ("The owner's exit
check").

The restore assigns the stored token usage, cost and turns to the roots
and clears and refills the sample's model and role usage, as today
(`sample_runtime.py:153-163`, `:259-266`). It is idempotent: a
checkpointer entry that fails part-way and is entered again sets the same
values. Work the attempt charged before the restore is overwritten; what
that loses is under "Limits swallowed before a checkpoint restore".

A limit restored at exactly its budget refuses any further call before
dispatch (`>=`), with nothing spent; a resumed sample that makes no further
call and returns is not recorded as limited, as for a sample that used
exactly its budget.

Only the sample's roots are stored: scoped limits (`run()`, a swarm's
nodes) are re-entered fresh by the resumed agents, as their usage is today.

### The sandbox bridge

A bridged generation request (`_forward_provider_errors()`,
`src/inspect_ai/agent/_bridge/sandbox/service.py`) is handled in this
order, of which only the limit handling changes:

1. At entry, the pre-dispatch check runs; then, if the bridge has kept any
   limit, the request gets the kept error's reply with no generation,
   whatever is suspended.
2. A failed request's terminations are handled as today; a sample failure
   (now including `UnmeteredCallError`, "Unpriced models") fails the sample
   through `bridge.request_fail()`, as the sidecar's failures do today;
   a refusal that leads a group of limits and refusals still wins.
3. Otherwise every limit the request's error holds is kept, other errors in
   the group are logged as today, and the scaffold gets the combined
   error's reply.

- **The kept limits.** The bridge keeps every limit its generations and
  host tools reached, once per limit node, and never replaces or drops
  one. `SandboxAgentBridge.generation_limit` keeps its name and its
  readers (the kept-limit reply, the host-tool refusal, the raise at
  unwind) and always holds the combined error of the kept
  limits. Host tools add an error their call does not own.
- The entry check now covers turns with `>=` (rule 3), so the separate
  `check_turn_limit()` call goes away. The "a limit is already kept" branch
  stays, after the pre-dispatch check: that check runs first, so a newly
  reached limit raises and joins the kept ones, and then any request that
  arrives while a limit is kept gets the kept error's reply without a
  generation, whatever is suspended, so a kept message limit (which the
  check does not cover) still refuses a fresh request with a shorter
  prompt.
- **Host-tool requests are refused once a limit is kept.** Today only the
  dispatch guard wraps a host tool's execution (`service.py:453-464`), so a host
  tool admitted after the bridge kept a limit still runs, and a monitor in
  an `as_tool()` child or a tool calling `run()` makes a priced call that
  no limit counts, as often as the scaffold asks. Once a limit is kept, a
  host-tool request runs no tool, input validation, viewer, approval or
  monitor. It is answered with the `limit` tool error for the kept error
  and recorded like any other rejected call: an unknown tool, a malformed
  request and an unproposed call are rejected as today, and a proposed
  call uses up its grant and gets a completed `ToolEvent` linked to its
  proposal. The kept limits are unchanged.
- **After a limit is kept.** This is the one statement of what still runs
  once the bridge has kept a limit; other sections point here.
  - Every new generation request and host-tool request is refused at
    entry with the kept error, whatever is suspended.
  - A generation request admitted before the limit was kept makes its
    remaining provider calls under node state alone: each refuses a
    reached token, cost or turn node on its own path and checks its own
    conversation's message limit. So it continues when the kept limit is
    a message limit, a sourceless `custom` limit, or a token, cost or turn
    limit entered only on another request's path (decision: Ransom,
    2026-11-19).
  - A host-tool request admitted before the limit was kept runs on the
    same way: its child `run()` agent (an `as_tool()` agent or a tool
    calling `run()`) can keep making unsuspended generations until its
    own limits or a reached limit on its own path stop it.
  - Suspended approval, review and monitor calls made for admitted work
    run and count against no limit (rule 5).
  - A kept limit whose budget a `limit` setter or a live override has
    since raised no longer refuses admitted work, since its node is no
    longer reached; the entry refusal still uses the kept error.

  Spend after a kept limit is therefore bounded by the work already in
  flight and the limits on its own path. No guard replaces the removed
  dispatch guard.
- `_encloses()`, `_sample_roots()` and `_in_tree()` are deleted. The
  `solving()` dependency goes with them. Keeping every limit needs no
  comparison, and the rank works the same during the solve and in scorers.
- `sandbox_agent_bridge()` still raises the kept limit only once the agent
  has unwound or returned, after a pending enclosing cancellation
  (`bridge.py:336-405`). What it raises then combines every limit: when
  the agent unwound with limit errors of its own (bare or in a group, for
  example a limit of the host process escaping beside the CLI's exit), they
  are added to the kept limits and the bridge raises the combined error of
  all of them, so a kept owned cost limit and an escaping sample token
  limit both reach the owner. Today `_error_after_unwind()` (`:385-405`)
  raises the kept limit alone and drops an escaping one. The existing
  priorities stay: a termination, a requested sample failure and a pending
  enclosing cancellation decide ahead of the limits, as today. An agent
  that unwinds with a group led by an ordinary error (an `ExceptionGroup`
  of a `RuntimeError` and a limit error), with nothing kept, still fails
  with that ordinary error, as today. A group led by a limit keeps every
  limit in it, as their combined error, whether or not the bridge kept a
  limit, where today, with nothing kept, the fallback (`bridge.py:373`)
  keeps only the first leaf: an owned cost error and a
  foreign message error both leave `run()`. If the agent is cancelled
  first, the kept limits are not raised there. Each token, cost or turn
  limit among them refuses every later call under it (rule 3), and when
  no other limit error reaches its owner, rule 7 raises it when that owner
  ends normally, if it is exceeded: the `apply_limits()` scope that
  entered it, or the sample's exit check when the solvers return. A kept
  limit reached exactly by a refused request and then cut off by a hard
  stop is the accepted loss under "What raises at exit".
- A refused unpriced model (`UnmeteredCallError`, see "Unpriced models")
  in a bridged generation fails the sample through `bridge.request_fail()`,
  so the sample fails with the error's message. It goes through the
  existing group-aware selector: `_first_sample_failure()`
  (`service.py:263-275`) matches a local tuple,
  `_BRIDGE_SAMPLE_FAILURES = (*SAMPLE_FAILURES, UnmeteredCallError)`, in
  place of the sidecar's `SAMPLE_FAILURES` (which stays the sidecar's own
  list), and finds the error bare or inside a group, nested or not, as a
  request filter that generates in a task group raises it. It is selected
  before `_first_control()`, as the sidecar's failures are today, so an
  unpriced refusal beside a limit in one group fails the sample rather
  than being kept as a limit. If a cancellation displaces that failure
  before it is delivered, nothing records it; a retried request is refused
  again before dispatch, with nothing spent.

Every bridged request and host tool runs in the bridge's service task, which
inherits the agent's trees. Because the bridge keeps
every limit, the order in which requests reach them does not change what
the bridge raises, and a bridge inside a tool hands the enclosing tool's
ownership test every limit its requests reached: a sample message limit
beside a foreign cost limit leaves the tool, whichever arrived first.

### What a runtime can rely on

For a runtime such as inspect_swarm, which runs several agents inside the
sample's limits, Inspect guarantees the following, given one prerequisite.

**Prerequisite: the runtime owns its agents' tasks.** Limit errors travel
with tasks, not with the trees. Work started with `background()` runs in the
background target in effect, by default the sample's task group, and its
errors go to that group's owner, the sample runner, not to the `run()` or
runtime that started it, even though the work inherits their limits. With
the sample's group live and no target set, deepagent's background children
run there (`BackgroundRegistry.owned_task_group()` and
`_dispatch_background()`, `src/inspect_ai/agent/_deepagent/agent_tool.py:146-167`,
`:696-701`), and `_run_background()` re-raises a limit of an enclosing scope
into that group (`:797-815`): it cancels the sample, bypassing the parent's
`run()`. A runtime whose agents' background work must report to it, or to a
particular `run()`, installs its own background target for that scope
(`background_target` in `src/inspect_ai/util/_background.py:30`), as
inspect_swarm does for each member. This design does not reroute the
sample's background group: work started there keeps its sample-scoped
lifetime and its errors keep reaching the sample runner. The guarantees below are about work in tasks the runtime owns.

1. **A sample limit reaches the runtime.** A sample token, cost or turn
   limit that raises for any of its agents' model calls, native or
   bridged, in a tool, a handoff, a subagent or a filter, reaches the
   runtime's code as a `LimitExceededError` whose `source` is the sample's node
   (`sample_limits().token`, `.cost`, `.turn`), or whose `limits` include
   that node's error (a combined error, whose primary fields are the
   sample limit's when it ranks first), bare or in a group. This holds while the limit
   remains the deciding outcome under each site's existing ranking of
   limits against other errors, which this design keeps ("Precedence"): a
   termination or an unexpected error in the same tool group decides ahead
   of it (`decisive_tool_exception()`); a response-filter group mixing it
   with an ordinary error becomes a `ResponseFilterError` and requests
   sample failure; and `_first_sample_failure()` selects a sidecar failure
   or an `UnmeteredCallError` ahead of it. The runtime then receives that
   failure, and the sample can end in an error without the limit being
   delivered or recorded, as guarantee 4 says for an exit decided by a
   non-limit error. No Inspect code between the
   model call and the runtime converts it (rule 6: no owner below the
   runtime owns all of an error that holds it), and no other limit reached
   by the same call or a concurrent one, or kept by a bridge, removes it
   (rules 3, 4 and 8 combine them), except in the cases rule 3
   names: a call that only reaches the sample limit while exceeding an
   inner one raises the inner one, and the sample limit arrives at the
   next pre-dispatch check; and a message limit is checked first. The
   check after a call reads the nodes' totals at that moment, whichever
   call put them there, and raises a limit only when its total is past its
   budget (`>`). When the totals end exactly at the budget, the call
   returns normally, the limit is then reached, and its error comes with
   the next call, which is refused before dispatch (`>=`). If no call follows, nothing
   raises and the sample ends normally, as a sample that used exactly its
   budget does (rule 7 records only an exceeded limit at exit). For a bridged agent the error arrives when the agent's
   CLI exits. If a handler on the way swallows it (a fallback, a hook,
   `tg_collect()` keeping another error), it arrives instead at the next
   call any agent makes under the sample, which is refused with it
   (guarantee 2), except in the cases listed under "Recovery boundaries".
2. **A reached limit stays reached under its current budget.** Within the
   attempt, while the node is reached under its current effective budget,
   every later dispatch under that
   sample, including the runtime's own model calls, native compaction and
   bridged requests, is refused with that node's error, or with an error
   holding it and every other node that has since been reached (rule 3: the next
   check raises every reached node, combined). Approval,
   review and sentinel calls are the exception: they run with token, turn
   and cost limits suspended, so a reached limit of those kinds does not
   refuse them (rule 5). A bridge's kept limit refuses new bridged
   requests and host-tool requests at entry, suspended or not; work already
   admitted stops only at reached limits on its own path (rule 8, "After a
   limit is kept"). Raising or removing the budget (a `limit` setter, a
   live override) lets dispatch through again; the bridge's entry refusal
   of a kept limit is separate and is not reopened by it. The other cases
   where a reached limit does not keep refusing are under "Recovery
   boundaries".
   Calls already dispatched complete and are recorded, and each then runs
   the post-call check against the nodes' current totals (rules 2 and 3):
   it raises every node whose total is past its budget, combined, whether
   this call or a concurrent one put it there (rule 8 adds them to the
   bridge's kept limits the same way). A call that adds no metered usage
   has no exemption: it raises if a node is already past its budget. A
   call returns normally only when every node's total is at or below its
   budget; a limit reached exactly then refuses the next dispatch. The
   exception is a generation a sentinel sidecar recovers in
   `_generate_prepared()` through `refusal_after_error()`, after
   `_generate()` has raised: it does not pass through the post-call frame,
   and it records and checks only when the sidecar's judgment supplies
   billed usage (`_model.py:1185-1222`). A provider error the sidecar turns
   into an output inside `_generate()` (`refused_output()`,
   `_model.py:2000-2008`, `:2057-2063`) is not this
   exception: that output takes the normal path, counts a turn and gets
   the post-call check. A recovery without billed usage returns
   normally even if another call has already taken a limit past its
   budget; the next pre-dispatch check, or the owner's exit check, still
   finds that limit ("Not this design").
3. **The runtime may hold the error.** It can catch it, stop its agents
   (close levers, wait for in-flight calls within its grace, cancel the
   rest), write its ledger and re-raise the error, bare or in a group
   whose first leaf (depth first, in order) is a limit error. The runner
   records it as the sample's limit (`EvalSampleLimit`), from the primary
   fields of the combined error of every limit in it. A group whose first leaf is another
   error, such as a cleanup failure raised ahead of the limit, is recorded
   as that error, as guarantee 4 says for an exit decided by a non-limit
   error. During the stop, no unsuspended provider dispatch can succeed
   under the reached limit, so the runtime's final step must make none.
   Suspended approval, review and sentinel calls still run (rule 5).
4. **Losing it is not silent.** When the solvers return normally, the
   sample's exit check records the sample limits that are exceeded at exit
   (rule 7), combined. That covers a runtime, or a bridged agent cancelled
   before its CLI exited, that drops the error of an exceeded limit; the
   cases it does not cover are under "Recovery boundaries". It runs after
   background cleanup, so usage recorded there counts. A limit error that
   reaches the runner is recorded as it is: it can leave out a sample
   limit that counts when a limit is pushed over in
   cleanup after another escaped, or when an adapter's state copy raises a
   different limit (see "What the owner can miss"). An exit decided by a non-limit error, a
   termination or an operator interrupt keeps that outcome.
5. **No unpriced model runs under an active cost limit.** While cost is
   not suspended and an active cost node has a limit (not `None`), no
   model without cost data of its own, a router included, is dispatched
   (rule 9). Suspended calls may use unpriced models, and so may calls
   under only cost nodes without a limit (inspect_swarm's meters and
   levers). The agents' spend under a cost limit is
   therefore at most the limit, plus the calls already in flight when it was
   reached, plus what the limit does not see: responses whose usage is
   missing or read as zero, as today, so a priced model whose provider omits
   usage is not bounded by a cost limit at all (a separate design covers
   it, see "Not this design"); failed attempts, which the retry policy
   bounds (`max_retries`, unlimited by default); and every dispatched call
   that is cancelled before its usage is recorded (one cancelled scope can
   cancel several, such as a bridge's concurrent requests or a member's
   background work). Approval, review and sentinel spend is not counted at
   all (rule 5).

Guarantees 1, 2 and 4 rest on node state, which lives for one attempt;
where it does not hold is under "Recovery boundaries".

The sample's time limit (a cancel scope around the solvers) and working limit
(a sample-wide cancellation) are outside these guarantees. They end the sample
by cancellation, which the runtime cannot hold.

Message limits are per conversation: a sample message limit reached in a
member's own conversation (one with no message limit of its own), outside a
tool or handoff, is raised there like any other foreign error, and reaches
the runtime the same way. Inside a tool or handoff it keeps today's
handling when it is the only limit in the error: a message limit error
raised in a tool's own conversation stays a tool error or handoff message,
whichever node raised it, even an inherited sample node ("Ownership"), so
the calling agent or runtime receives that reply and can continue;
guarantee 1's delivery covers token, cost and turn limits only. When a
foreign token, cost or turn limit is in the same error (in one task group,
or kept beside it by a bridge inside the tool), the call does not own the
error, and the whole of it, message limit included, propagates: the
runtime receives both limits.

The same holds at `run()`. A member whose requests reach both the sample
message limit and its own `run()` budget limit (natively in one task
group, or through a bridge, which keeps both) raises an error that
`run()` does not own, since the message limit is the sample's. So `run()`
propagates it instead of returning its budget error, and the runtime, or
the sample runner, receives both. The runner records the top-ranked one,
the `run()` budget limit, in `EvalSample.limit`; the message limit is in
the error's `limits` and in its `SampleLimitEvent`. The sample's message
limit is therefore not lost when an inner owner's budget is reached with
it.

### Unpriced models

Under a cost limit, a call to a model with no cost data is refused before
dispatch (decision: Ransom, 2026-11-12), with one error and no mark
(decision: Ransom, 2026-11-17). The refusal does not apply while cost is
suspended (rule 5), so approval, review and sentinel calls are exempt.

**What a cost limit does not see.** These calls are not charged, as today:

- An attempt that fails (an error response, a timeout, a connection reset,
  an empty stream), and a call cancelled in flight (decision: Ransom,
  2026-11-16). A provider may still bill some of them. Inspect retries
  failed attempts up to `max_retries` (unlimited by default) and `timeout`,
  the only bound on them. One cancelled scope can cancel several dispatched
  calls at once (the bridge's sandbox service runs one task per pending
  request, `src/inspect_ai/util/_sandbox/service.py:441-449`).
- A response whose usage is missing, or which the provider's conversion
  reads as zero ("Current behaviour"). A priced model whose provider omits
  usage is therefore unmetered under a cost limit, as today. Failing such
  calls is the subject of a separate design ("Not this design").

**The error.** `UnmeteredCallError(PrerequisiteError)`, a private error
defined in `_limit.py` beside the cost limit. Its message names the model
and how to price it: "cost_limit requires cost data for every model called
under it. No cost data for '<model>'. Use set_model_cost() or
--model-cost-config to configure pricing." For a model not in the model
database the last sentence is the one `model_usage_cost()` already uses:
"It is not in the model database, so use set_model_info() with a ModelInfo
that includes cost." `resolve_model_costs()`
(`src/inspect_ai/model/_util.py:67-98`) and this error share one helper for
this text.

It is raised before the attempt's request is sent, so nothing is spent. It
is never retried as a model attempt: `Model.should_retry()`
(`_model.py:2231`) returns `False` for it before any other test, so a
provider's classifier never sees it. A sample configured with
`retry_on_error` is still retried, as for any sample error: only
`SampleRefusedError` is exempt from sample retries
(`src/inspect_ai/_eval/task/run.py:2950-2954`), and no
exception is added for this one. Each sample retry repeats the sample's
priced work before it fails on the same call. A
sentinel sidecar does not recover it as a refusal: each generate attempt
first forgets the sidecar's record of the previous attempt
(`begin_attempt()`, `_model.py:1754`;
`src/inspect_ai/_sentinel/_sidecar/_received.py:348-372`), and
`refused_output()` and `refusal_after_error()` ask nothing of an attempt
whose request was not sent (`src/inspect_ai/_sentinel/_sidecar/_act.py:117`,
`:195`). It is not a `LimitExceededError`, so no limit owner catches it.
When it reaches the sample runner the sample fails with it, as a sample
error. Native tools do not map it (`tool_call_error()` returns `None` for
it), and a bridged host tool treats it as an unexpected error, which fails
the sample (`host_tool.py:529-531`); a bridged generation fails the sample
with it through `bridge.request_fail()` (see "The sandbox bridge").

Nothing is marked, so the cost limit is not reached by the error. Code that
catches it and calls the same model again (a compaction fallback, a hook
that logs and continues, a first-error reduction) is refused again before
dispatch, with nothing spent.

**When.** In `_check_limits_before_dispatch(model)`, after the limit check:
if cost is not suspended, any active cost node
has a limit (not `None`), and `_get_model_info_direct(model)` has no
`cost`, it raises. This is the start-time check's test
(`resolve_model_costs()`), applied to each call. It is not
`model_usage_cost()`'s test, which can price a call from its serving models
when the called model has no cost data ("Current behaviour"); the
difference matters only for a model with no price of its own whose
provider reports the models that served it, such as a router (below). The check runs per attempt,
for `generate()` and native compaction, for agent and subagent models;
approver, reviewer and monitor models are exempt, because their calls run
with cost suspended.

- **Not refused.** A cache hit (no dispatch). A priced model whose provider
  reports that an unpriced model served the call: that call is priced at the
  called model's rates with a warning, as today. A model with cost data of
  zero.
- **Routers need their own price.** A router such as `openrouter/auto` has
  no cost data of its own; today its calls are priced from the models
  OpenRouter reports served them. Under an active, unsuspended cost limit,
  a router without its own price is now refused before dispatch, like any
  model without cost data (decision: Ransom, 2026-11-17), as the
  start-time check already refuses it as a task model. Giving the router a
  price admits it: `set_model_cost()` or `--model-cost-config` for a router
  the model database knows, or `set_model_info()` with a `ModelInfo` that
  includes cost for one it does not, such as `openrouter/auto`. Its calls are still priced from their
  serving models when those have cost data, and the router's own price is
  the fallback `model_usage_cost()` uses when a serving model has none.
  The same holds for other names whose calls are priced today from the
  model that served them: Azure deployments reached through the OpenAI,
  Azure AI and Anthropic providers, Bedrock routing or inference-profile
  names, Fireworks routers, and LiteLLM proxy aliases that have no
  called-model price (an alias already priced by user registration, the
  model database or the proxy's metadata is admitted as today). A name the model database does not know, such
  as an Azure deployment name, needs
  `set_model_info(full_model_name, ModelInfo(cost=...))`, since
  `set_model_cost()` requires an existing entry;
  `set_model_cost()` or `--model-cost-config` works for a name that has
  one.
  Without a cost limit, or with cost suspended, nothing changes.
- **At start.** `resolve_model_costs()` keeps requiring cost data for the
  task's own model, which the sample's agent calls by default, so the
  common misconfiguration still fails before any sample runs. It no longer
  requires cost data for model-role models, at eval start or for an
  enqueued task (`src/inspect_ai/_eval/eval.py:883`, `:1377`): a role can be
  used only by suspended calls (the sentinel host's `monitor` role, an
  approver's role), and the start-time check cannot tell how a role will be
  used. An unpriced role model called with cost suspended runs; the same
  model called by an agent, unsuspended, under the cost limit is refused at
  that call by the per-dispatch check above. A role cannot be exempted by
  name either, since any code can resolve any role.

After a call, the one check runs whatever the call's cost (rule 2). An
unpriced call that is admitted (cost suspended, or no cost node with a
limit) records whatever cost `model_usage_cost()` resolves, as today: none
for a model with no cost data, but the serving model's cost when the
provider reports a priced serving model (a router), into the sample's
usage and into every cost node that is not suspended, such as an
inspect_swarm meter (`None` limit); cost suspension still keeps it off the
nodes. The admission rule for routers is unchanged. Token and turn limits were already checked after
such calls; what is new is that unsuspended cost nodes are checked after
them too, so a node whose own check raises without a limit, such as
inspect_swarm's closed lever gate, raises after the call where today it
raises at the next dispatch.

### Other limit kinds

- **Time.** Gets no entry number. A time limit's error is raised where it
  was entered, by its cancel scope. In a combined error it ranks after every
  token, cost, turn or message limit (rule 4), so a member's time limit and the sample's token
  limit in one group combine into an error whose primary fields are the
  token limit's.
- **Working.** Gets no entry number. The sample's working limit is enforced
  by the monitor's cancellation. Nested working limits are not polled
  today; they are checked only when a checkpoint is restored, which can
  fail the resume on one (see "Not this design").
- **Message.** Ranked by its entry number, with its own check,
  and out of the owners' exit checks. In a combined
  error it ranks after every token, cost and turn limit (rule 4); a tool or
  handoff owns every message limit raised in its call ("Precedence" says
  why).

### What inspect_swarm can delete or simplify

This list is for the swarm's maintainers. Nothing here depends on it.

The swarm's limits design (inspect_swarm's `design/swarm-limits.md`,
"Bridged generations", "Exhaustion and errors" and "Interactions") handles
each of these interactions as a case of its own. Under the rules above they become:

- **Calls that cross limits of different kinds.** A call that crosses a
  member's token limit and a swarm cost cap, cost share or member cost limit
  raises one error holding both, so it ends at the outer swarm node's owner
  (rules 3, 4 and 6), and the member's own token limit is in its `limits`.
  So does a member stopped by its lever while a call that trips its token
  limit is in flight. A call with no
  cost data cannot run under a swarm cost node that has a limit, while cost
  is not suspended (rule 9).
- **Bridged members of a nested swarm.** A cost-tree error no longer hides a
  later token-tree error from the outer swarm: the bridge keeps both, of
  whatever kinds (rule 8).
- **Bridged losses.** A filter's parallel calls that raise a swarm limit and
  the sample's token, cost or turn limit in one group raise one error
  holding both (rule 4 and the filter's reduction). A bridged host tool's
  model call that reaches the sample limit after the bridge kept a member
  limit adds the sample limit to the kept ones (rules 6 and 8). A member
  whose error holds a sample limit and its own limit is not caught by the
  member's scope; the wrapper receives every limit and fills `ended_by`
  from the top-ranked (rule 4) or from `limits` as it chooses. Bridged
  members that record the sample message limit in `ended_by` today can
  record a swarm or member budget limit instead when one was reached with
  it, since a budget ranks first; the message limit is still in `limits`.
  A kept sample limit lost to a
  cancellation before the CLI exits is recorded by the sample's exit check
  when the solvers return, if it is exceeded (rule 7).
- **Promotions.** A retry or in-flight request that reaches an enclosing
  swarm limit after a member limit was kept adds it to the kept limits;
  that is rule 8 itself, so it needs no separate case.
- **Limit errors inside tools.** A swarm cap or lever reached in a member's
  foreground, inside a tool or a synchronous deepagent subagent, now reaches
  the member wrapper at once instead of at the member's next model call. The
  cap node's `stop_swarm` call in `_check_self` stays, and is still needed
  for correctness: errors from a member's background work are contained by
  the member's background owner (`MemberBackground._run()`,
  `inspect_swarm/src/inspect_swarm/_background.py:138`), and the member
  runner classifies only an exception that escapes the member
  (`_member.py:662`). A background call that crosses a cap is
  therefore never classified by the wrapper, and only the callback starts
  the swarm's stop. Removing the callback would need the swarm to reconcile
  its caps when a member returns or drains, which is the swarm's own
  change, not a consequence of this design.
- **The reserve.** Guarantees 1 to 3 let the runtime catch a sample limit and
  stop its members in an orderly way, so the 5% reserve no longer has to
  keep the stop orderly. It would still leave room for a final step that
  makes model calls, which is the swarm's own decision.
- **Sentinel.** inspect_sentinel's runner keeps the first limit of a group
  (`_runner.py:414-416`). It could combine them instead, as Inspect's
  reductions do.

What the swarm must change:

- **The turn override.** Its `SwarmTurnNode._check_self()`
  (`inspect_swarm/src/inspect_swarm/_budget.py:606`) takes the new
  `raise_for_equal` argument, before or with the Inspect change that passes
  it (implementation plan, step 1). Its token and cost `_check_self()`
  overrides take part in the check; its message `check()` and its `record()` overrides are called directly,
  as today.
- **Ownership over every limit.** Its member wrapper classifies an
  escaping limit error by its `source` (`classify_errors()`, `_member.py:809`), and
  `MemberBackground._run()` contains a background limit error by its
  `source` too (`_background.py:138`). A combined error's `source` is only
  its top-ranked limit's, so both must look at every member of `limits`:
  an error whose limits include a foreign one (a sample message limit
  beside a member token limit, say) is foreign as a whole and is
  re-raised, not consumed, and `ended_by` is filled from the member's own
  limits or the top-ranked one, as the swarm chooses. Without this, a
  combined member-token and sample-message error would be treated as
  wholly the member's, and the sample's limit would be lost.
- **Pricing.** A member whose model has no cost data of its own (a router
  included), called unsuspended under a swarm cost node that has a limit (a
  cap, a share or a member cost limit; not a meter or lever, whose limit is
  `None`), now has that call refused with `UnmeteredCallError` (rule 9), so
  the swarm needs a price for every member model it runs under such a node.
  The error is not a limit, so it
  does not reach a cap. Uncaught, it fails the swarm: the member's
  foreground classification treats it as a foreign error and calls the
  member's fatal callback (`_member.py:662-688`), and
  `MemberBackground._run()` contains only selected limit errors, so a
  background one takes its fatal branch and is re-raised into the owning
  task group (`_background.py:138-147`); the controller's fatal callback
  marks the swarm failed (`_controller/_control.py:654`, `:1225-1226`).
Its per-member `background_target` is what the guarantees' prerequisite
asks for, so it keeps it.

## Alternatives considered

**Check cost before token.** It swaps which kind is late: a call that crosses a
token limit enclosing a cost limit would then raise the inner cost limit. It
fixes nothing structurally.

**Choose one limit at every reduction.** Each place where several limits
meet (the check, a tool's group, the bridge's kept limit, the response
filter, `run()`, the runner) would keep one limit by a fixed order and
drop the rest. Innermost first lets an inner owner catch its error and
continue while an outer budget is spent, so the outer limit depends on a
later check. Outermost first unwinds the widest scope, but needs more
than entry order: the sample's message node is entered before every
agent's budget nodes, so the order has to rank token, cost and turn limits ahead
of message limits, and that order has to hold at every site, because an
earlier reduction (a bridge inside a tool, a response filter) can drop a
limit before the owner that should see it does. Ownership then has to be
decided by the chosen limit: a scope catches a group only when its
deciding limit is its own, so a group of an owner's message limit and a
descendant's budget limit escapes it, and an inner owner's budget limit
that wins over the sample's message limit is caught by that owner, so the
sample's message limit is recorded nowhere. Combining keeps every limit,
lets ownership be one test over all of them, and needs the order only to
fill single-valued records; the cost is the new `limits` attribute and
that a mixed error now ends at the owner of all of it rather than at
whichever owner the chosen limit pointed to.

**Raise every reached limit as an exception group.** It loses nothing, but
every consumer that catches `LimitExceededError` bare (`apply_limits()`,
tools, the runner, user code) would have to learn groups. Rejected for
compatibility; a combined `LimitExceededError` carries the same
information and is still caught bare.

**One node carrying several kinds** (for example `usage_limit(tokens=...,
cost=...)`). A new public API that still needs an order between nodes. With
entry numbers, a token node and a cost node entered together are adjacent,
and the order is already defined. Rejected as unnecessary. It could still be
added later.

**One chain of every kind per execution context.** Pushing token, cost,
turn and message nodes onto one stack would give each node a depth and
an ancestry across kinds, and sibling tasks would never be ordered
against each other. But ownership needs only the scope marker (rule 1),
and ranking only fills single-valued records, where an
entry number orders nodes on one path the same way and an arbitrary but
fixed order between siblings does no harm. The chain would add a stack
that every limit kind pushes and pops, a new failure when blocks exit out
of order, and its own tests. Rejected as more mechanism than the rules
need.

**`apply_limits()` checks every enclosing limit at exit.** A scope's exit check
would also raise an enclosing limit that a handler inside the scope
swallowed, one scope earlier than its own owner. But every scope would then
raise limits it does not own: a default deepagent background child, which
enters `apply_limits()` with no limits of its own
(`src/inspect_ai/agent/_deepagent/agent_tool.py:768-780`), would end the
sample with its parent's `run()` limit after the parent had caught it; an
inner scope would raise an inspect_swarm lever closed on an enclosing
member node; and the sample's restored roots would need a per-node
exemption on a resume for scoring that kept missing limits reached earlier
in the same attempt. Each owner checking its own limits gives the same
"one step later" as any swallowed error (decision: Ransom, 2026-11-17).

**Restore adds to what the attempt has already charged.** Adding the
stored usage to the roots instead of assigning it would keep a limit
reached before the restore reached. But a checkpointer entry that fails
part-way (in the restore's check, `on_resume` or the entered
checkpointer's construction) and is entered again by a caller that
retries the entry would add the snapshot twice, so it would need a
once-only accounting lifecycle separate from the entry cache. No caller
retries a failed entry today ("Limits swallowed before a checkpoint
restore"), so this is a hazard of the alternative, not a current path. Refusing model work
before the restore instead would fail ordinary resumes, whose solvers
before the agent run again. The loss is stated instead ("Limits swallowed
before a checkpoint restore"; decision: Ransom, 2026-11-18).

**Make every limit node check itself at exit.** One rule instead of two call
sites (rule 7), and a plain `with token_limit()` block would find a limit
that a handler inside it swallowed. But it would raise again an error the
block's author caught inside the block on purpose, it would raise
inspect_swarm's closed levers and reached member nodes when a member ends
normally after the swarm handled them, and the sample's roots would need an exemption so that the
runner's own outcome (an operator interrupt, a resume for scoring) stands.
The two owner sites cover what Inspect relies on; a plain block's limit is
found while the block is open ("Plain `with` blocks").

**A non-strict exit check (`>=` for every node).** It would catch a
swallowed refusal at exactly the budget, but would also record as limited
every sample that used exactly its budget, or took exactly its N turns,
and returned. Recording such a refusal separately needs a per-node record
of the budget each node refused at, kept across retuned budgets, live
overrides and checkpoint restores; the loss it would close is a refusal
user code swallowed with no later call, which is accepted instead
(decision: Ransom, 2026-11-19).

**Carry every limit error intact to its owner.** Make each
handler that can catch one (fallbacks around compaction, hooks, first-error
reductions such as `tg_collect()`, the sentinel wrapper, a bridge delivery
that a cancellation can displace) re-raise or forward it. Each review of
that approach found another such handler, and the list is open-ended: any
user or extension code can catch an exception. The rules here make the
nodes the record instead, so within one attempt a handler that swallows a
limit error usually delays it by at most one call; the cases where it can
still be lost are listed under "Recovery boundaries".
Inspect still changes its own handlers where that decides *which owner*
handles the error and that it sees every limit in it (rules 4, 6 and 8),
not merely whether the error survives.

**Reconcile an escaped limit with node state at its owner.** When a limit
error reaches `apply_limits()` or the sample runner, compare it with the
limits that count at that point and report those instead. It
would close the cases under "What the owner can miss", where only the
recorded limit differs, but each review of it found another exit
path to cover (owned errors, descendants' errors, time limits, which have no
entry number). An error that reaches its owner stands (decision: Ransom,
2026-11-16).

**Raise a monitor's limit bare from the sentinel wrapper.** With token,
turn and cost suspended for monitors, a monitor can reach only a message limit, which keeps today's
`SentinelFailure` handling ("Sentinel failures") (decision: Ransom,
2026-11-16).

**Exempt role models at start by name.** Skipping the start-time price
check only for roles such as `monitor` would keep the early failure for
other roles, but a role's name does not say how it is used, and any code
can resolve any role. The per-dispatch check decides by the call's own
suspension instead.

**Mark the cost limit when a call cannot be priced.** A durable
"unmetered" mark on every cost limit the call ran under would refuse every
later call, so a handler that swallows the error gains nothing. It needed a
mark that every check honours, a notification so a swarm cap stops at once,
rules for a marked limit set to `None`, and caveats for checkpoints. An
unpriced call is refused before dispatch with nothing spent, so a handler
that swallows the refusal and calls again is refused again; no mark is
needed (decision: Ransom, 2026-11-17).

**Admit a router priced by its serving models.** Keeping `openrouter/auto`
callable under a cost limit with serving-model prices only would need a
check before dispatch that predicts whether the model that will serve the
call is priced; a serving model with no cost data would leave the call
unmetered. A router needs its own price, the same test the start-time
check applies (decision: Ransom, 2026-11-17).

**Fail calls that report no usage in this design.** A response whose usage
is missing or zero would fail its call, so a cost limit would bound every
call that comes back. Each review of it found another provider path that
reports missing usage as zero, sums it away, or converts a mid-stream
failure into an output, and it changes how safety blocks end samples. It
moves to its own design (decision: Ransom, 2026-11-17; see "Not this
design").

**Route background work to the `run()` that started it.** Every
`background()` call would need an owner per limit scope, which changes the
sample-scoped lifetime that deepagent's default children rely on and that
`background()` documents. A runtime that needs its agents' background errors
installs a target for them, as inspect_swarm does.

**Mark the cost limit for failed attempts that may have been billed.**
Classifying each failure by evidence that it was unbilled (an error
response before inference) and marking the rest would bound spend strictly,
but every review of that approach found another ambiguous failure (a
connection reset while reading a response, an empty stream), and a single
transient failure under a cost limit would end the sample. Failed attempts
and cancelled calls stay uncharged, as today, with the retry policy as
their bound (decision: Ransom, 2026-11-16).

**Warn about unpriced calls instead of refusing them.** Keeps evals with an
unpriced subagent or agent model running, but a cost limit then does not
bound that spend: the calls never advance it, so its checks never fail.
Approver, reviewer and monitor calls are not part of this argument: they
run with cost suspended, so no cost limit bounds them either way, and the
refusal skips them (rule 9). Refusal was chosen (decision: Ransom, 2026-11-12).

## Compatibility and migration

No migration is required for code that uses the public limit API as
documented. Behaviour changes:

- **One error for several limits.** When one call crosses several token,
  cost or turn limits, one `LimitExceededError` is raised for all of them
  (message limits keep their own check). Its type, value, limit, message
  and source are the top-ranked limit's: the outermost token, cost or turn
  limit, whatever its kind, where today the token tree is checked before
  the cost tree. For the sample's own limits the primary fields are as
  today (token, then cost, by entry order). Every node that raised emits
  its `SampleLimitEvent`, so a transcript can show several where today it
  shows one.
- **`LimitExceededError.limits`** is a new public attribute: every limit
  the error stands for, top-ranked first. A single limit's error lists
  itself. A combined error is raised by the checks, by owner exit checks,
  by the bridge, and returned by `run()` and the tool and runner reductions
  when several limits meet; `apply_limits()` sets `limit_scope.limit_error`
  to it. Code that reads only the existing fields sees the top-ranked
  limit, so `except LimitExceededError` and readers of `type` keep
  working. The constructor's new `limits` argument is keyword-only and
  optional. Nothing serialized changes: `EvalSample.limit`
  (`EvalSampleLimit`) and inspect_swarm's `ended_by` stay single-valued and
  take the top-ranked limit; no log or schema field becomes a list.
  Migration for code that decides ownership: `source` and the other
  ordinary fields identify only the primary member of a combined error.
  Code that catches a limit error and decides whether it is its own, or
  contains it (as `error.source is my_limit`), must consider every member
  of `limits`: matching `source` alone can swallow a foreign limit held
  beside its own, such as a sample message limit beside its token limit.
  Reporting a primary type or source from the ordinary fields stays as
  it is.
- **`turn_limit(N)`** now allows N generations and refuses the (N+1)th before
  dispatch. Today the (N+1)th is made and raises after it returns. The error
  type is the same; its message reads "Turn limit reached" when raised before
  dispatch, as token and cost messages already do. Native compaction and
  bridged requests are refused once a turn limit is reached. Logs of the same
  eval show one fewer `ModelEvent` for a turn-limited sample.
- **Turns of calls that cross a child limit.** A generation whose token or
  cost check raises now counts as a turn of every enclosing turn limit. Code
  that catches a child limit and calls again reaches its turn limit sooner
  than today, where such calls were never counted.
- **A generation that crosses a turn limit is no longer reported or
  cached.** Today the turn limit is checked after usage hooks, legacy
  telemetry and the cache store have run, so such a generation reaches
  them before it raises; now it is checked with token and cost limits,
  before them. Token- and cost-limit crossings keep today's order.
- **Limit errors in tools and handoffs.** A sample, `run()` or other
  enclosing token, cost or turn limit reached inside a native tool, handoff
  or bridged host tool now ends the owning scope at once. Before, the model
  saw a `limit` tool error or handoff message and the scope ended at its next
  model call. If no model call followed, the sample completed without a
  recorded limit. A tool's error group (or a bridge's kept limits) holding
  any such limit now leaves the tool as one combined error, with every
  other limit in it,
  including a message limit and the tool's own limits: a mixed error ends
  at the owner of all of it, where today the tool replied with its first
  limit. An error holding only limits the tool or handoff entered itself or
  entered below it, limits with no entry number (time limits, sourceless
  `custom` limits) and message limits behaves as before; a handoff still
  returns the handed-off agent's new messages and its limit message for
  them.
- **Message limits beside budgets.** A sample message limit reached in
  the same error as a token, cost or turn limit stays in the error. Where
  the sample records one limit, the budget limit ranks first, so a sample
  whose bridged agent reached both the sample message limit and a member
  or `run()` budget limit records the budget limit in `EvalSample.limit`,
  where today the bridge kept the sample message limit and recorded it.
  When the budget limit belongs to an inner owner (`run(limits=[...])`
  around that agent), the error is not all that owner's, so `run()`
  propagates it and the sample ends on it, as today, rather than `run()`
  returning the budget error. inspect_swarm's bridged tests that record a
  sample message limit in a member's `ended_by` may change: the member's or
  the swarm's budget limit ranks ahead of it. inspect_swarm will be
  adjusted, and enabling such runtime changes is this design's main
  motivation. A tool or handoff whose only limit is a message limit
  behaves as today.
- **Unpriced models under a cost limit fail.** A call to a model with no
  cost data, made while a sample, agent or swarm cost limit is active, is
  refused before dispatch with an `UnmeteredCallError` (a
  `PrerequisiteError`) that names the model and how to price it. The sample
  fails with that error unless something swallows it; every later call to
  that model is refused the same way. Evals that
  pass today with a cost limit and a subagent or agent that resolves an
  unpriced model, a router included, now fail on that model's first call;
  approver, reviewer
  and monitor models are exempt. The fix is to give the model a price with
  `set_model_cost()` or `--model-cost-config` (or `set_model_info()` for a
  model not in the database). Evals with no cost limit, and cache hits, are
  unaffected.
- **Routers need their own price under a cost limit.** A router such as
  `openrouter/auto`, whose calls are priced today from the models that
  served them, is refused before dispatch under an active, unsuspended
  cost limit unless the router itself has cost data. Configure it with
  `set_model_cost()` or `--model-cost-config`, or `set_model_info()` with a
  `ModelInfo` that includes cost for a router not in the model database
  (`openrouter/auto` is not). Calls are still priced from their serving
  models where those are priced; the router's price is the fallback
  `model_usage_cost()` uses when a serving model has none. A router as the
  task model already fails at start today. The same applies to Azure
  deployments through the OpenAI, Azure AI and Anthropic providers, to
  Bedrock routing or inference-profile names, to Fireworks routers and to
  LiteLLM proxy aliases without a called-model price, when an agent
  resolves them separately: an unknown called name needs
  `set_model_info(full_model_name, ModelInfo(cost=...))`, and
  `set_model_cost()` works for names with a database entry. A LiteLLM
  alias already priced by user registration, the model database or the
  proxy's metadata is admitted as today.
- **Unpriced role models fail per call, not at start.** Today an eval with
  a cost limit and an unpriced model-role model fails before any sample
  runs, with a `PrerequisiteError` from `resolve_model_costs()`, at eval
  start or when the task is enqueued. Now it starts: a role model used only
  by approvers, reviewers or sentinel monitors runs unpriced, and one an
  agent calls fails each sample at that call with `UnmeteredCallError`. An
  unpriced task model still fails at start, as today.
- **Failed attempts and cancelled calls stay uncharged.** Unchanged: an
  attempt that fails (an error response, a timeout, a connection reset, an
  empty stream) or is cancelled in flight records no usage, and failed
  attempts are retried as today. Spend under a cost
  limit can exceed it by the cost a provider bills for those attempts, with
  `max_retries` (unlimited by default) and `timeout` as the only bound on
  failed attempts, and by the cost of every dispatched call cancelled
  before its usage is recorded (one cancelled scope can cancel several).
- **Calls that report no usage stay unmetered.** Unchanged: a provider
  response whose usage is missing records nothing under a cost limit, and
  one whose conversion reads missing usage as zero (Mistral and SageMaker
  streams without a usage chunk, Grok responses without a usage message)
  records zero, so a cost limit does not bound a priced model whose
  provider omits usage. A separate design covers it ("Not this design").
- **`apply_limits()`**, with `catch_errors=True` (`run()`), catches an
  error, bare, combined or an exception group, when every leaf is a limit
  error and every limit in it is its own or inside it (entered in its own
  context, nested scopes included, whatever its kind); its
  `limit_error` is their combined error. Any other leaf or limit, including
  a sourceless `custom` limit, an enclosing message limit or a sibling
  task's limit, propagates the whole error unchanged, as today. A bare
  error from a limit inside the scope (a plain block's or an `as_solver()`
  limit inside the agent) is now returned by `run(limits=[...])` where
  today it raises, whatever the kinds the scope entered: a bare error from
  a plain `with cost_limit()` inside an agent under
  `run(limits=[token_limit(N)])` is now returned by `run()` instead of
  propagating. The rule for `run(limits=[...])` has no exceptions: it
  returns the limits entered inside it. `run(limits=None)`, which
  returns only the state, catches nothing, as today. With `catch_errors=False` a
  group propagates unchanged, as today. At normal exit it raises its own
  limits that are exceeded, combined;
  it does not check enclosing limits. `run()` therefore returns
  `(state, error)` in these cases where today it raises or returns
  `(state, None)`. A limit error that escapes its body is handled as it is
  (by ownership of every limit in it), not compared with node state.
- **The sample runner**, when the solvers return normally, checks the
  sample's limits after the solvers and the sample's background work have
  finished, and records an exceeded sample limit found then.
  It does not on a resume for scoring, so, as today, a limit swallowed
  during that attempt (by a sample-start or attempt-start hook or the
  `on_resume` callback) is not recorded. A limit that work before a
  checkpoint restore (startup hooks, solvers before the agent) reached and
  swallowed can be reopened by the restore, which still assigns the stored
  usage, as today. A limit error that escapes the solvers is recorded as today.
  Errors, terminations, operator interrupts and limits delivered by
  cancellation are handled as today.
- **Background work.** Its lifetime and the destination of its errors are
  unchanged. Work started with `background()` in the sample's task group,
  including deepagent's default background children, still sends its errors
  to the sample, so a child's limit of its parent's `run()` still ends the
  sample rather than returning from that `run()`, as today. The runtime
  guarantees state this as a prerequisite rather than changing it.
- **Cache hits under an exceeded limit raise.** A cached response under an
  already-exceeded token or cost limit is still served, and now raises that
  limit after it (the check that follows every generation), where today it
  returns. Under a limit only reached, not exceeded, it returns as today.
- **A swallowed refusal at exactly the budget is still unrecorded.** As
  today, a limit at exactly its budget whose refusal user code swallowed,
  with no later call, is not recorded at its owner's exit; only an
  exceeded limit is ("What raises at exit").
- **Plain `with` blocks keep no exit check.** As today, a limit reached in
  a plain `with token_limit()` block whose error a handler inside the block
  swallowed is lost if no further call under the block follows; deliberate
  catches inside the block behave as today.
- **Bridge.** A bridged agent now keeps every limit its requests and host
  tools reached, whatever their kinds, and raises their combined error;
  today it keeps one, replacing it only by a same-tree ancestor or a sample
  root.
- **The bridge's dispatch guard is gone.** Today the guard refused every
  provider call a bridged request or host tool made once the bridge had
  kept a limit, with a copy of the kept error (`service.py:172-193`,
  `:453-464`). Now admitted work is stopped by node state alone, so more
  of it can finish after a kept limit: a generation request already in
  flight when a message limit, a sourceless `custom` limit or a limit on
  another request's path is kept; an already-running host tool's child
  `run()` agent, until its own limits stop it; and admitted work under a
  kept limit whose budget a live override has since raised. The exact
  rules and their bounds are under "After a limit is kept". New requests
  and host-tool requests are still refused at entry. Today only a request
  filter that enters a limit around one request produces the off-path
  case: a host tool's own limits become tool errors and are never kept,
  and inspect_swarm enters member limits around each member's own bridged
  agent, so one member's limit never reaches another member's bridge.
  `dispatch_guard()` was private and had no other user.
- **Token limit formulas.** A token limit `type` formula must now be a
  non-negative weighted sum of `input` and `output` ("Token metering must
  not decrease"); `token_limit(10, type="input - output")` and formulas
  that multiply or divide the two counts raise `ValueError` when the limit
  is built, including when an eval with such a formula is retried from its
  log. No such formula was found in use. `all`, `output`, `input` and
  weighted sums such as `(input * 0.1) + output` are still accepted, but a
  retained formula is evaluated from its reduced coefficients, which
  regroups the floating-point arithmetic and can change the floored count
  by one: `input / 3 + output / 3` with 7 input and 2 output tokens meters
  3 today and 2 after the change (`2.9999999999999996` floored). This
  applies wherever the formula is evaluated, including when a checkpoint
  restore re-meters the same raw counts.
- **Private internals.** `_encloses()`, `_sample_roots()` and `_in_tree()`
  are removed, and so are `dispatch_guard()`, its ContextVar and the
  bridge's `_refuse_after_a_recorded_limit()`. `_TurnLimit._check_self()` gains a parameter. Token, cost,
  turn and message nodes gain an entry number and the scope marker
  current at their entry (a ContextVar each call or scope sets, inherited
  by the tasks started inside it). `record_turn()` no longer checks,
  and is called from the inner generation. `SandboxAgentBridge` keeps
  every limit reached, and `generation_limit` holds their combined error. inspect_swarm is the only known user of
  these classes (above).
- **Persisted data and the viewer.** The checkpoint sample-runtime payload
  is unchanged. `EvalSampleLimit`, `SampleLimitEvent` and `EvalConfig` limit fields keep
  their shapes, and old logs read the same; a check that raises several
  nodes records one `SampleLimitEvent` for each. Log recovery is unchanged
  and takes the last limit event of the recorded type, so when several
  limits of one kind fire together, a recovered log can name a different
  one of them than the live run did. No generated TypeScript type changes.
- **Docs.** `docs/setting-limits.qmd` and `docs/_agent_limits.md` state the
  combined error and its `limits`, which limit fills the single-valued
  records, that `source` names only the primary member so ownership checks
  must look at every member of `limits`, that tool-based agents return a message for their own limits (an
  error holding an enclosing limit ends the caller), the new turn semantics, the
  suspension rule, that every model called under a cost limit needs cost
  data of its own (routers included), that calls reporting no usage are
  not counted, and that a token formula must be a non-negative weighted sum (the
  formula paragraphs at `docs/setting-limits.qmd:164` and `:461`).

## Security

- **What reaches this code.** Usage numbers and prices from providers, which
  set how far a node advances. Requests and host tool calls from a sandboxed
  CLI through the bridge, which are untrusted and can be sent in any number
  and order. No model output or tool argument decides precedence or
  ownership.
- **A sandboxed agent cannot change the outcome.** The trees, entry numbers, the
  kept limit and the ownership test live in the host process and depend only
  on which `with` blocks the host entered. A CLI that floods requests after a
  limit gets the kept limit's error reply with no model call (rules 3 and 8),
  as today. The bridge's kept set holds one entry per limit node (sourceless
  errors by identity, and only Inspect's own code raises those into it), so
  repeated requests do not grow it.
- **Error text** forwarded to the CLI is the existing `provider_error_payload`
  of the limit error (its type, value and limit), unchanged; for a combined
  error those are the top-ranked limit's.
- **Spend.** The agents' changes either refuse a call sooner (a reached
  turn limit, an unpriced model) or make a limit error propagate further,
  with two exceptions that admit calls refused today. The start-time price
  check no longer requires prices for role models, so an eval whose
  approver, reviewer or monitor role model is unpriced, which today fails
  before any sample runs, now runs those models' suspended calls. And with
  the bridge's dispatch guard removed, work a sandboxed agent's requests
  already started can continue after the bridge keeps a limit (admitted
  requests and host-tool child agents after an off-path, message or
  `custom` limit, or after a live override raises a budget), bounded by
  the work in flight and the limits on its own path ("After a limit is
  kept"); new requests are still refused at entry. Suspension is set by
  host code (the approval, review and sentinel machinery Inspect runs), not
  by a sandboxed agent or model output. With rule 9, no
  unpriced model runs unsuspended under a cost node that has a limit,
  whatever model a sample, a
  subagent or a sandboxed agent's request selects: the check runs on the
  model a bridged request resolves to, whatever name the CLI sent, and the
  refusal is delivered to the sample through `bridge.request_fail()`, which
  ends it. Responses that report no usage, failed attempts and cancelled
  calls are outside the bound, as today; a sandboxed agent that selects a
  priced model whose provider omits usage is not bounded by a cost limit
  until the separate design for such calls ("Not this design").

## Testing

All tests use mockllm, or a stub provider, with scripted usage and
`set_model_info()` prices (as `tests/util/test_limit_cost.py` does). They need no network, Docker or
provider, so the default PR test job runs them. Their async tests also run
under trio with `--runtrio`.

- `tests/util/test_limit.py`, combined errors:
  - one call crossing an inner token limit and an outer cost limit raises
    one `LimitExceededError` whose primary fields are the cost limit's and
    whose `limits` are `[cost, token]`, each node with its own
    `SampleLimitEvent`; the reverse nesting puts the
    token limit first; a call crossing one limit raises that node's error,
    whose `limits` is `[itself]`;
  - a turn limit outer to a token limit ranks first;
  - the sample's token and cost limits keep entry order;
  - combining over nested groups, combined members, sources with no entry
    number and ties: every limit appears once, in rank order (a token, cost
    or turn limit entered later ahead of a message limit entered earlier,
    message limits by entry number, a time limit or sourceless `custom`
    limit last); a group with no limit gives none; a group reduced by its
    first leaf, with a leading non-limit error and with a leading inner
    limit;
  - entry numbers survive exit;
  - per-kind views (`get()`, `_tree_root()`) unchanged.
- `tests/util/test_limit_cost.py`:
  - under `cost_limit(1.0)` a call to an unpriced mockllm model is refused
    before dispatch with `UnmeteredCallError` whose message names the model
    and the missing price, with no provider call made; the same inside
    `suspend_token_limit()` and for native compaction; inside
    `suspend_cost_limit()` (as an approver's call runs) it is made; after
    the error is caught, a call to a priced model under the same limit runs
    and is charged (nothing is marked);
  - a cache hit of an unpriced model is served; with no cost limit an
    unpriced call is made;
  - routers, in `tests/model/test_model_info.py` beside
    `TestServedModelPricing`, with its `servedtest` stub provider (which
    reports the model that served each call, as OpenRouter does for a
    router) driven through `generate()`: under a cost limit, a called model
    with no cost data of its own whose serving model has cost data is
    refused before dispatch with `UnmeteredCallError`; after
    `set_model_info()` gives the router a cost, the same call is dispatched
    and priced from its serving model; with a serving model that has no
    cost data it is priced at the router's rates; without a cost limit, and
    inside `suspend_cost_limit()`, the unpriced router is dispatched and
    priced from its serving model, as today; under a `cost_limit(None)`
    meter, the unpriced router's call is dispatched and the meter records
    its serving model's cost, while inside `suspend_cost_limit()` the
    meter records nothing;
  - sample retries: with `retry_on_error=1`, a sample that makes a priced
    call and then calls an unpriced model is retried once, makes the priced
    call again, and fails with `UnmeteredCallError` (pinned);
  - a sidecar does not recover the refusal: with a sentinel sidecar whose
    judgment is a refusal with a withheld turn, a call to an unpriced model
    under a cost limit raises `UnmeteredCallError` with no provider request
    and no sidecar lookup;
  - start-time pricing, in `tests/test_sample_limits.py`: an eval with a
    cost limit, a priced task model and an unpriced `monitor` role model
    starts, and the same task enqueued during an eval is accepted
    (`tests/test_enqueue_task.py`); a stub in-process monitor that calls the
    role model with cost suspended runs; a solver that calls the same role
    model, unsuspended, fails the sample with `UnmeteredCallError`; an
    unpriced task model still fails at start.
- `tests/util/test_limit_turn.py`: `turn_limit(3)` makes three generations
  and refuses the fourth before dispatch; a cache hit at the limit is served
  and then raises (it records its turn); in `tests/util/test_limit_token.py`,
  a cache hit under a `token_limit()` an uncached call has already exceeded
  is served and then raises that limit, and
  `test_generate_cache_hit_served_when_token_limit_reached` (a hit at
  exactly the limit returns) still passes; a native compaction that
  returns no usage, under a `token_limit()` a concurrent call has already
  exceeded, raises that limit; native compaction is refused at the limit and records no
  turn; under `turn_limit(1)`, a call that raises a child `token_limit(1)`
  (caught) counts one turn and the next call is refused by the turn limit;
  the same with a child `cost_limit()`; a generation whose first attempt
  fails with a retried provider error and whose second succeeds counts one
  turn; in an active sample, a generation whose post-call check raises
  (a child `token_limit(1)`, and separately the turn limit itself) leaves
  the sample's reported turn count (`ActiveSample.total_turns`, which the
  control channel reads) including that turn.
- `tests/util/test_limit_token.py`: inside `suspend_limits()`, a call is not
  refused by a reached token, turn or cost limit, and a reached message
  limit still refuses it; inside `suspend_limits()`, a `_CostLimit` subclass whose `_check_self()` always
  raises (as inspect_swarm's closed stop gate does) is not checked, and the
  same node refuses an unsuspended call;
  `token_limit()` and `TokenLimit` (including the `"input-output:10"`
  string form) refuse `input - output`, `input / output`
  and `input * output` with the family message, and accept `all`, `output`,
  `input`, `(input * 0.1) + output`, `input / 10 + output` and
  `2 * input - input`; a polynomial in `input` such as
  `input + input * (input - 1)` is refused.
- `tests/util/test_limit.py`, `run()` and `apply_limits()`: an owned limit
  raised inside the agent's task group is returned; a group of an owned
  token limit and an enclosing limit (a sample message limit, or an outer
  cost limit) propagates unchanged, as a group; a group of an owned token
  limit and a sourceless `custom` limit propagates as a group; with
  `run(limits=[token_limit(...), cost_limit(...)])`, a group of its token
  limit and a cost limit entered below its cost limit is caught and
  returns their combined error (`limits` both); with
  `run(limits=[token_limit(...)])` only, a bare error from a cost limit
  entered inside the agent is caught and returned (today it propagates);
  under `run(limits=[token_limit(N)])` with a plain `cost_limit()` inside
  the agent, one call that crosses both raises their combined error, which
  `run()` returns, token-primary (today `run()` returns the token error); a bare token limit entered below the scope's token
  limit is caught and returned; `run(limits=[time_limit(...)])` and
  `run(limits=[])` catch and return a bare limit entered in the agent's
  own task or a task it started, while `run(limits=None)` lets it
  propagate; a shared-boundary sibling: with a scope that entered no
  limits, a token limit a sibling task entered under the same enclosing
  node, whose error is re-raised inside the scope's body, propagates; an
  owned token
  limit exceeded and swallowed inside the
  agent is returned as `(state, error)` by the exit check (the return path
  of `run()`); an agent that swallows an exceeded owned token limit and
  then raises `RuntimeError`: the runtime error propagates and `run()`
  returns no limit (the abnormal end stands); an owned limit reached exactly and swallowed after a refused
  call returns `(state, None)` (the accepted loss); a sample limit swallowed inside the agent does
  not leave `run()` at its exit (`run()` returns `(state, None)`), the
  caller's next model call is refused with it, and if the solver instead
  returns, the sample is recorded as limited by it; a synchronous deepagent
  subagent's swallowed limit is reported as its result;
  - plain blocks: inside `with token_limit(n)`, after a call exceeds the
    block's limit and the error is caught inside the block, a further call
    made inside the block is refused with that limit; a catch inside the
    block is not raised again at its close;
  - own limits with no entry number: `apply_limits([time_limit(...)],
    catch_errors=True)` and `run(limits=[time_limit(...)])` still catch and
    return their own time limit error, including one raised as the limits
    exit (the existing `test_apply_limits_handles_time_limit` stays); an
    `apply_limits([time_limit(60), token_limit(10)])` scope, and one with a
    `working_limit(60)`, whose body stays under budget returns normally (the
    exit check skips the time and working limits);
- `tests/_control/test_limits.py`, reopening: a sample whose token limit
  was reached and refused a call is given a higher budget through
  `set_sample_limit_override()`; the next call is dispatched; with a
  bridged agent, the bridge's kept limit still refuses a new request at
  entry after the override.
- `tests/checkpoint/test_sample_runtime.py`: the payload is unchanged
  (no new keys); after a dump and normal restore of a token root that
  refused a call at exactly its budget, the next call is refused before
  dispatch; after a scoring-only restore of spent token, cost and turn
  roots, `as_solver(react(...))` returns normally with no model call and
  the sample is scored and not recorded as limited (the no-call control),
  on asyncio and Trio; a normal restore of token, cost and turn roots all
  above budget raises the token limit alone, with only its limit event (the
  ordered-restore control).
- `tests/agent/test_agent_execute.py`: a sample token limit reached inside an
  `as_tool()` agent ends the sample with `limit.type == "token"` and no
  further generation; `as_tool()`'s own token limit is still a tool error;
  `test_agent_as_tool_respects_sample_limits` (message) is unchanged; a
  handoff passes on a foreign token limit and still answers its own; a
  handoff whose agent exceeds a `with token_limit()` entered inside it, and
  one whose agent exceeds a `time_limit()` entered inside it, return the
  agent's new messages and the handoff limit message, as today; an
  `as_tool()` agent with its own `cost_limit()`, called inside
  `run(limits=[token_limit(N)])`, whose one call crosses both limits,
  raises their combined error out of `execute_tools()`, and `run()`
  returns it, token-primary (today the tool's reply names the token limit,
  and `run()` returns the token error only if a later call is checked);
  the same agent whose
  call crosses only its own cost limit gets the tool's `limit` error, as
  today.
- `tests/tools/test_call_tools.py`, `decisive_tool_exception()` and the
  call's ownership test, beside
  `test_native_group_with_limit_leaf_is_reported_as_the_limit`: a native
  tool run under an enclosing `cost_limit()` enters a `token_limit()` and
  raises a group of that token limit's error and the enclosing cost
  limit's; the call does not own all of it, so their combined error
  (`limits` both) propagates out of `execute_tools()` (today the first
  limit decides and the tool replies with the token limit's `limit`
  error). Under a `message_limit()` entered first, then an enclosing
  `cost_limit()`, a group of the message limit's error and the cost
  limit's also propagates, as their combined error (today the message
  limit is the tool's `limit` error). A group of the message
  limit's error and a `token_limit()` entered inside the tool is owned: it
  is the `limit` tool error with the combined error's message, the token
  limit's (it ranks first). A group of two limits both entered inside the
  tool is the `limit` tool error with the outer one's message. A group
  holding only the message limit's error is still the message `limit`
  tool error. The existing
  `test_a_group_of_sentinel_limits_keeps_its_first_limit`
  (`tests/sentinel/test_sentinel_dispatch.py:3331`) stays as it is.
- `tests/test_eval.py` (or the existing sample-limit tests): a solver that
  swallows an exceeded sample token limit and returns is recorded as
  limited; a solver whose call was refused at exactly the sample token
  budget, which swallows the refusal and returns, is not (the accepted
  loss); a solver that uses exactly the budget and returns is not; a solver that catches the limit and raises
  `state.token_limit` is not; a resume for scoring over a spent budget is
  not; a sample with a cost limit whose solver calls an unpriced model fails
  with `UnmeteredCallError`;
  - the runner's reduction (`first_or_combined_limit()`): a solver that
    enters a `with token_limit()` inside the sample's cost limit and lets
    a group escape whose first leaf is that token limit's error and whose
    second is the sample cost limit's is recorded with an `EvalSampleLimit`
    of type `cost` (today `token`), the escaping error's `limits` holding
    both; the same group behind a leading `RuntimeError` ends the sample in
    that error, with no `EvalSampleLimit`; a group whose first leaf is the
    sample message limit's error and whose second is a scoped
    `token_limit()`'s is recorded as type `token`;
  - exit check after cleanup (each with the worker synchronized by an
    `anyio.Event`, never a sleep): a `background()` worker makes a priced
    call in its cancellation cleanup after `plan()` returns, exceeds the
    sample cost limit, catches the error and returns: the sample ends on the
    cost limit; `plan()` raises a
    `RuntimeError` while a worker's cleanup exceeds a sample limit: the
    sample errors as today; an operator interrupt with an exceeded sample
    limit keeps its operator outcome.
- `tests/agent/test_agent_overflow_compaction.py`: a forced compaction whose
  summary call reaches the sample token limit falls back to the overflow
  filter as today, and the agent's next generation is refused with the
  sample token limit (the sample ends on it); if the overflow filter cannot
  shorten the conversation and the agent returns, the sample's exit check
  records the limit.
- `tests/agent/test_bridge_provider_errors.py`:
  - replace the `_encloses()` tests (`keeps_the_first_of_limits_in_different_trees`,
    `keeps_the_first_beside_an_unentered_limit`, `keeps_only_the_first_limit`
    and the enclosing cases) with kept-set cases: a sample message limit
    and a member token limit kept give the same `generation_limit`
    whichever is added first (primary fields the token limit's, `limits`
    both); the same node reached by two requests is kept once;
  - limits escaping at unwind: inside `run(limits=[cost_limit(...)])`, a
    bridged agent whose request reached that cost limit (kept) unwinds
    with a sample token limit's error, bare and again inside an exception
    group; `run()` does not return, and the error that leaves it holds
    both limits, the token limit's primary fields first; a requested
    sample failure, a termination and a pending enclosing cancellation
    still decide ahead of the limits, as today; with no kept limit, an
    agent that unwinds with `ExceptionGroup([RuntimeError(...),
    owned_limit_error])` still fails with the `RuntimeError`, and `run()`
    does not return the limit; with no kept limit, an agent inside
    `run(limits=[cost_limit(...)])` that unwinds with a group of that cost
    limit's error and the sample `message_limit()`'s keeps both: their
    combined error propagates through `run()` (the message limit is not
    its own), where today the bridge keeps only the first leaf;
  - a bridge inside a tool, end to end: an `as_tool()` agent whose body
    sends two bridged requests at once, one whose prompt reaches the
    sample's `message_limit(2)` and one whose priced usage takes a
    `cost_limit()` entered above the tool past its budget (its stub
    provider holds the response until the message request has been kept,
    so both are reached), and raises the bridge's kept error when it
    unwinds; run through `execute_tools()`, the combined error (both limits
    in `limits`) leaves `execute_tools()` intact, with no message `limit`
    tool error. A message-only control, the same agent sending only the
    first request, gets the message `limit` tool error, as today;
  - group reductions: a response filter that raises a group of the sample
    message limit's error and a scoped cost limit's error raises their
    combined error from `_apply_response_filter()` (primary fields the cost
    limit's), and `_first_control()` keeps both limits;
  - `test_first_limit_in_a_bridged_filter_group_is_raised` becomes a
    combined-group case, with the inner limit first in the filter's group:
    the raised error holds both limits, the outer first, so that it covers
    `_apply_response_filter()`'s reduction as well as `_first_control()`;
  - a refusal first in a group of only limits and refusals still fails the
    sample; a group `[ModelRefusalError, ValueError, LimitExceededError]`
    keeps the limit and logs the others, as today;
  - a bridged sentinel monitor call and an approval call made for a
    request in flight after the bridge kept a limit still run (pinned, as
    today), and the agent ends on the kept limit when it unwinds; a host
    tool whose `as_tool()` child runs a monitor while a limit is kept
    during its execution gets no `SentinelFailure`, and the sample ends on
    the kept limit;
  - after a limit is kept, two fresh sequential host-tool requests, one to
    an `as_tool()` agent and one to a tool calling `run()` with a monitor
    configured, each get the `limit` tool-error reply and make no tool,
    monitor or provider call, and the kept limit is unchanged; each
    proposed request consumes its grant (a repeat of it is denied as
    unproposed), and the transcript holds one completed `ToolEvent` per
    request with a `limit` error and the proposal's event id;
  - a host tool already running when the bridge keeps a limit on another
    request's path (a sibling-path limit, and separately a message limit):
    its child `run()` agent keeps making generations until its own
    `token_limit()` stops it, and no replacement guard refuses them;
  - an unpriced bridged model under a cost limit fails the sample with
    `UnmeteredCallError`, with no provider call: from the generation
    itself, and from a request filter that generates the unpriced model
    inside a task group (the error in a single group and in a nested
    group), where the scaffold handles the error reply and returns
    normally; the sample still fails through `request_fail()`;
  - a kept sample token limit exceeded by a request, then a cancellation
    of the bridged agent before delivery and a normal return from the
    solver, ends the sample on the token limit;
  - a request after a reached turn limit makes no generation;
  - the dispatch guard's tests go with it:
    `test_nested_dispatch_guard_keeps_the_enclosing_check` is deleted, and
    `test_forward_provider_errors_refuses_model_calls_once_a_limit_is_recorded`
    keeps its outcome (a request in flight makes no further model call of
    its own, and a suspended call still runs) with a reached turn node in
    place of a sourceless kept error, since node state now does the
    refusing;
  - the kept-limit entry refusal: a request whose three-message prompt
    reaches `message_limit(2)` keeps the message limit, and a fresh request
    with a one-message prompt gets the kept limit's error reply with no
    provider call; a newly reached outer token limit at
    the next request's entry joins the kept limit, and the reply's primary
    fields are the token limit's;
  - a host tool whose model call reaches the sample limit after a member
    limit was kept adds the sample limit to the kept ones, and it ranks
    first;
  - through `_run_bridged_agent()` (a one-sample eval with a served scaffold,
    no Docker), overlapping generations that reach a `run()` cost limit and
    then an outer `run()` token limit (`outer_limit`) propagate from the
    inner `run()`, which does not own the token limit, and the outer
    `run()`, inside which the cost limit was entered, returns one error
    holding both, primary fields the token limit's; the same with the sample's token limit in place of the outer
    `run()`'s ends the sample on it;
  - the message limit is not lost behind an inner owner's budget: a bridged
    agent inside `run(limits=[token_limit(...)])` whose requests reach both
    that token limit and the sample's `message_limit()` makes `run()`
    propagate the combined error; the sample ends with `EvalSample.limit` of
    type `token` and a `SampleLimitEvent` for each limit (today the sample
    records the message limit);
- `tests/tools/test_tools_bridge.py`: a bridged host tool's own limit is
  still the `limit` tool error text (the existing cases at `:1771` and
  `:2135`). Beside `test_bridged_limit_replies_with_the_native_tool_error`,
  with the `_serve_grouped()` harness: a host tool served under a
  `message_limit()` and then an enclosing `turn_limit()`, both entered
  outside the tool, raises a group of the message limit's error and the
  turn limit's; the call does not own the turn limit, so both are added to
  the bridge's kept limits (`generation_limit` has the turn limit's primary
  fields and both in `limits`), while the scaffold gets the combined
  error's tool-error text; a group holding only the message limit's error
  gets the message tool-error text and keeps nothing.

## Implementation plan

Each step is one PR, in this order. Each keeps the suite green.

1. **Entry numbers and one check.** `src/inspect_ai/util/_limit.py`:
   entry numbers, the scope marker each node records at entry (set by
   `apply_limits()` here; by tool calls, handoffs and host tools in step
   4), the rank, `LimitExceededError.limits` and its constructor
   argument, combined errors, the check and the owner's exit check
   raising every node that raises (skipping suspended kinds, cost
   included, as the per-kind checks do), recording without a check, turn
   limits refusing at equality before dispatch,
   `record_turn` recording only,
   the affine grammar and non-negative weights in `_compile_token_formula()`,
   with metering from the reduced coefficients.
   `src/inspect_ai/model/_model.py`: each model call recording, then
   running the check once, where its accounting runs today
   (generation, cache hit, native compaction, sidecar recovery), and the
   pre-dispatch check.
   Tests: the node-level cases in `tests/util/test_limit*.py` (entry numbers,
   combined errors, recording, pre-dispatch refusal).
2. **Unpriced models.** `_limit.py`: `UnmeteredCallError`. `_model.py`:
   the unpriced check in `_check_limits_before_dispatch(model)` and the
   model passed by `generate()`'s and compaction's per-attempt calls;
   `Model.should_retry()` returns `False` for `UnmeteredCallError`.
   `src/inspect_ai/model/_util.py`: `resolve_model_costs()` checks the task
   model only, with the shared message helper.
   `src/inspect_ai/agent/_bridge/sandbox/service.py`: `UnmeteredCallError`
   fails the sample, through `_first_sample_failure()` over
   `_BRIDGE_SAMPLE_FAILURES`. Tests: `tests/util/test_limit_cost.py`,
   `tests/model/test_model_info.py`, `tests/test_eval.py`,
   `tests/test_sample_limits.py`, `tests/test_enqueue_task.py`,
   `tests/agent/test_bridge_provider_errors.py`.
3. **Owners and reductions.** `_limit.py`: `apply_limits()` covered exits
   (a limit is covered when it is the scope's own or its node carries the
   scope's marker) and the exit check over its own limits on a normal return.
   `src/inspect_ai/agent/_run.py`: the return after the block.
   `src/inspect_ai/_eval/task/run.py`: combining the limits of the
   escaping group, and the exit check over the sample's roots after
   the sample task group has joined when the solvers returned, skipped
   when the attempt is `resume_for_scoring`.
   Tests: the owner-exit cases, which need these checks: the `run()` and
   `apply_limits()` tests in `tests/util/test_limit.py`, the runner's reduction
   in `tests/test_eval.py`,
   `tests/agent/test_agent_overflow_compaction.py`, and the restore and
   scoring-resume outcomes in `tests/checkpoint/test_sample_runtime.py`.
4. **Ownership in tools.** `_call_tools.py`: `decisive_tool_exception`
   returning the combined error of a group's limits
   (`decisive_sentinel_exception` is unchanged), the call leaf and the
   ownership test over every limit in `call_tool_task`, and the same test
   in `agent_handoff()`'s `except`. The combining and the ownership test go
   together: the native-tool cases in `tests/tools/test_call_tools.py` need
   both, since a mixed error propagates only once the ownership test runs.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: `_raised` ownership,
   the limits of errors the call does not own added to the bridge's kept
   limits.
   `src/inspect_ai/agent/_bridge/sandbox/types.py`:
   the bridge's kept limits (every limit added, `generation_limit` their
   combined error) and the `generation_limit` docstring.
   Tests: `tests/tools/test_call_tools.py` (the native-tool reduction,
   with the message-limit cases), `tests/agent/test_agent_execute.py` (the
   `as_tool()` and handoff cases), `tests/tools/test_tools_bridge.py` (the
   host tool's message-limit case); the existing handoff tests in
   `tests/agent/test_agent_handoff.py` stay as regression coverage.
5. **The bridge.** `src/inspect_ai/agent/_bridge/sandbox/service.py`: entry
   simplification (the separate turn check goes; the kept-limit branch
   stays, after the pre-dispatch check), `_first_control` combining and
   generation errors added to the kept limits (step 4), deletion of
   `_encloses`/`_sample_roots`/`_in_tree` and of
   `_refuse_after_a_recorded_limit()`; `src/inspect_ai/model/_model.py`:
   deletion of `dispatch_guard()`, its ContextVar and the guard step in
   `_check_limits_before_dispatch()`. `src/inspect_ai/agent/_bridge/util.py`:
   `_apply_response_filter()`'s reduction.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: the kept-limit
   refusal of host-tool requests. Tests:
   `tests/agent/test_bridge_provider_errors.py`.
6. **Docs.** `docs/setting-limits.qmd`, `docs/_agent_limits.md`,
   `docs/_turn_limits.md`, and the docstrings of `token_limit()`,
   `cost_limit()`, `turn_limit()`, `suspend_token_limit()`, `apply_limits()`
   and `run()`.

inspect_swarm adapts in its own repository ("What inspect_swarm can delete
or simplify"). Its `SwarmTurnNode._check_self()` takes `raise_for_equal`
before or with step 1, which passes that argument to every `_check_self()`;
an override without it raises `TypeError` there. Its pricing change goes
with step 2, and its ownership over every member of `limits` with step 3
or 4.

## Open questions

None.

## Not this design

- A generation a sentinel sidecar recovers as a refusal through
  `refusal_after_error()` in `_generate_prepared()`, after `_generate()`
  has raised, is left as today: it counts no turn, so repeated recovered
  generations do not advance a turn limit, and it records and checks its
  usage in one step only when the sidecar's judgment supplies billed usage
  (`_model.py:1185-1222`); without it, nothing is recorded or checked for
  the call. An output `refused_output()` produces inside `_generate()`
  follows the normal path (a turn and the post-call check).
- `SampleLimitEvent` is emitted by every token, cost, turn and message node
  that raises, scoped or not, so the viewer shows an agent's limit as a sample
  limit. inspect_swarm subclasses nodes to avoid it.
- Nested `working_limit()` scopes are not polled: the working-limit
  monitor checks only the sample's root. A nested scope is checked only
  when a checkpoint is restored, where `restore_sample_runtime(check=True)`
  calls `check_working_limit()` (`util/_checkpoint/sample_runtime.py:225`)
  and `_WorkingLimit.check()` checks the ancestors and then the current
  node, so a resume can fail on a nested working limit.
- Ranking limits against non-limit errors in groups differs by site (tools
  rank unexpected errors first, the runner takes the first leaf). One ranking
  everywhere would be a separate change.
- A public extension point for custom limit nodes (owner, message, no sample
  event), which inspect_swarm builds today by subclassing private classes.
- The generic sandbox service's routing of a raw limit error to the sample
  with `ActiveSample.limit_exceeded()`, which ignores the error's owner. Only
  the human agent's service can reach it.
- Message limits' leaf-only check, which lets an inner `message_limit()`
  replace an outer one for a conversation.
- Handlers that catch every exception between a model call and its owner:
  ReAct's overflow recovery (`_handle_overflow()`,
  `src/inspect_ai/agent/_react.py:697-747`), `CompactionAuto`'s
  native-to-summary fallback (`src/inspect_ai/model/_compaction/auto.py:85-101`),
  hooks run through `_call_hook_safely()` (`src/inspect_ai/hooks/_hooks.py:1218-1236`),
  and `tg_collect()`'s first-error reduction. They are unchanged. What a
  limit error swallowed there costs: it surfaces one step later, at the
  next call under the limit, which is refused at no cost, or at the owner's
  exit check, except in the cases under "Recovery boundaries". Spend stays
  bounded. An
  unpriced-model refusal swallowed there is refused again at the handler's
  next call to that model, with nothing spent. Making each re-raise these
  errors would only make them arrive sooner.
- Routing `background()` work to the `run()` or runtime that started it.
  Default deepagent background children keep their sample-scoped lifetime
  and report to the sample; a runtime that needs their errors installs a
  background target (see "What a runtime can rely on"). A scope's limit
  that such work reaches and swallows after the scope has returned is not
  recovered ("Background work that outlives its owner").
- **Calls that report no usage under a cost limit**, a separate design
  (decision: Ransom, 2026-11-17). It carries over these decisions
  unchanged: a response whose usage is missing or totals zero (cache fields
  included) fails its call with a non-retryable `UnmeteredCallError`, with
  no mark; when one call sums several requests (Google's continuations and
  malformed-function-call retries, Anthropic's continuations, the LiteLLM
  proxy's malformed-function-call retries), each successful request is
  checked before it is summed; only labelled HTTP rejections are exempt,
  classified where the error originates (a status response before any
  output, not a failure delivered mid-stream), so ReAct's overflow recovery
  keeps working; and Google's converted-error output carries the usage of
  every continuation leg that completed. Cases it must settle: Azure AI
  streams that cannot request usage; OpenAI and Anthropic safety blocks,
  streamed or terminal (Anthropic streams automatically for thinking or a
  large `max_tokens`), which cyber evals meet often; Groq's mid-stream
  context overflow; converted errors that attach earlier legs' usage
  (Anthropic's `chain.report()`, Google's handled-error branch); the
  LiteLLM proxy's final-output boundary and its second converter entry,
  `handle_stream_error()`, which converts both an HTTP 403 xAI refusal and
  a stream-body error; and Grok streams, whose usage-less tail chunk
  overwrites a reported total with zeros.
