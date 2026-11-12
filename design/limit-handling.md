# Limit precedence and ownership

## Overview

Inspect's token, cost, turn and message limits become nodes of one *limit
chain* per execution context, ordered by when their `with` blocks were entered,
in place of one tree per kind. Every check walks that chain from the root and
raises the outermost limit that has been reached, whatever its kind. Every
place that has to choose one limit error from several (an exception group, the
sandbox bridge's kept limit, the sample runner) chooses the outermost by the
same rule.

A limit error is handled only by the code that entered its limit. Tools,
handoffs and bridged host tools turn into a message only the token, cost and
turn limits entered inside the call. Every other such limit error passes
through unchanged to the scope that owns it: `run()`, `apply_limits()`, the
sample, or a runtime such as inspect_swarm. Once reached, a limit refuses every
later model call in its scope. Suspending token or turn metering hides only
that kind from the calls in the block. A scope that ends normally while a limit
on its chain is exceeded raises that limit when it exits, so a sample limit
cannot be silently lost.

Together these rules let a runtime that runs several agents catch the sample's
limit error, stop its agents in an orderly way, and re-raise the error.

## Why

inspect_swarm builds its cost caps, cost shares, member limits and stop levers
as nodes in Inspect's limit trees (inspect_swarm's `design/swarm-limits.md`).
Each review of that code finds another edge case, and each comes from the same
few interactions in Inspect:

- **Token before cost.** After a call, Inspect records the call into both
  trees, then checks the token tree, then the cost tree. A call that crosses a
  token limit and a cost limit always raises the token error. The cost limit
  is checked only at the next pre-dispatch check, even when it encloses the
  token limit. For example, a swarm member whose own token limit and the
  swarm's cost cap are crossed by one call ends on its token limit, and the
  cap stops nobody until another member calls a model
  (meridianlabs-ai/inspect_swarm#200, Compatibility).
- **No order between trees.** Inside a tree, the outermost reached node
  raises (root first). Between trees there is no order, because the trees do
  not know about each other. The swarm used to work around this with "pairs"
  (a token-tree node and a cost-tree node sharing one accumulator), and
  still lists a known gap that it cannot work around (below).
- **Suspended calls take another path.** Approval, review and sentinel model
  calls run inside `suspend_token_limit()` and `suspend_turn_limit()`. They
  still record into and check cost limits, but skip token checks and the
  `dispatch_guard()` checks. So the bridge's refusal after a kept limit lets
  them through.
- **The bridge compares limits within one tree.** The sandbox bridge keeps
  the first limit error its generations reach. A later one replaces it only
  if it comes from an ancestor in the *same* tree, or from one of the sample's
  own limits. A cost-tree error therefore hides a later token-tree error from
  an enclosing `run()` limit, token share or cap, and the other way round.
  From an exception group it takes the *first* limit before comparing at
  all.
- **Unpriced calls skip cost checks.** An unpriced call never adds to a cost
  limit and never checks one, so a cost limit that a concurrent priced call
  has reached is not raised after it.
- **Limit errors are consumed by code that does not own them.** A tool maps
  any `LimitExceededError` to a tool error, a handoff catches any, and a
  bridged host tool answers any as a tool error. A sample limit reached inside
  a tool is raised again only at the next model call. If no call follows, the
  sample completes normally with the limit's event in its transcript but no
  limit recorded.

Each rule is local and each fix is local, so consumers can only learn the
combined behaviour case by case. The swarm's design document lists more than a
dozen accepted losses and promotions, each with its own dated decision. The
aim here is a small set of rules that a consumer can rely on without studying
these interactions.

## Goals and non-goals

### Goals

- One precedence rule for which limit error wins: within one check, across
  overlapping calls, for a request refused before dispatch, inside exception
  groups, and in the sandbox bridge.
- One rule for the order in which usage is recorded and checked, for every
  kind of model call: ordinary, suspended (approval, review, sentinel),
  unpriced, native compaction, bridged.
- One ownership rule: which code may turn a limit error into something other
  than an exception.
- A stated guarantee that a runtime can catch a sample limit, stop in an
  orderly way and re-raise it.
- A list of what inspect_swarm can then delete or simplify.
- Keep `token_limit()`, `cost_limit()`, `turn_limit()`, `message_limit()`,
  `apply_limits()`, `run(limits=...)` and their signatures.

### Non-goals

- Hard limits, or reserving budget for calls in flight. A limit is still
  overshot by the calls already dispatched when it is reached.
- Time and working limits. A time limit is a cancel scope that raises where
  it was entered. A working limit is polled at the sample's root and ends the
  sample by cancellation. Neither joins the chain (see "Other limit kinds").
- Changing message limits' leaf-only, per-conversation check.
- A public API for custom limit nodes, or a multi-kind limit object.
- Changing what `SampleLimitEvent` is emitted for (see "Not this design").

## Current behaviour

### Who enters limits

A survey of this repository, inspect_swarm, inspect_swe, inspect_sentinel,
inspect_petri and inspect_evals finds these sources of limit nodes:

- The sample runner enters the sample's limits in this order: token, cost,
  message, turn, time, working (`src/inspect_ai/_eval/task/run.py:3186-3198`).
- `apply_limits()` enters a list of limits in list order
  (`src/inspect_ai/util/_limit.py:151-187`). `run()` uses it with
  `catch_errors=True` (`src/inspect_ai/agent/_run.py:96-111`), as do
  background deepagent subagents
  (`src/inspect_ai/agent/_deepagent/agent_tool.py:768-780`). `as_tool()`
  (`src/inspect_ai/agent/_as_tool.py:76`), `as_solver()`
  (`src/inspect_ai/agent/_as_solver.py:72`) and handoffs
  (`src/inspect_ai/model/_call_tools.py:1277`) use it without catching.
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
  (`_call_tools.py:1999-2005`).
- **Handoffs.** `agent_handoff()` catches any `LimitExceededError` and appends
  a user message (`_call_tools.py:1272-1281`, `:1309-1316`).
- **Bridged host tools.** A deciding limit becomes a `ToolError`
  (`src/inspect_ai/agent/_bridge/sandbox/host_tool.py:438-462`).
- **Other sandbox services.** A raw limit error from a sandbox service method
  is routed to the sample with `ActiveSample.limit_exceeded()`
  (`src/inspect_ai/util/_sandbox/service.py:595-616`); only the human agent's
  service uses this path.
- **Other packages.** inspect_sentinel's runner and inspect_petri let limit
  errors propagate. inspect_evals' `core_bench` tool re-raises them.

### Trees, recording and checking

- Each of the six kinds has its own `_Tree`: a ContextVar holding the leaf,
  with each node pointing to its parent of the same kind
  (`_limit.py:979-1025`). Nodes of different kinds have no link to each other.
- Token, cost and turn usage is recorded into the leaf and every ancestor
  (`_TokenLimit.record`, `_CostLimit.record`, `_TurnLimit.record`). Checks run
  from the root to the leaf, so the outermost exceeded node of that tree
  raises (`_limit.py:1104-1113`, `:1191-1200`, `:1275-1284`).
- Message limits check only the innermost node, against the length of the
  conversation being checked (`_limit.py:744-758`, `:1358-1379`).
- After a provider call, `record_and_check_model_usage()` records the call
  into the token tree (unless suspended) and its cost into the cost tree (when
  priced). It then runs `check_token_limit()` and, only for a priced call,
  `check_cost_limit()` (`src/inspect_ai/model/_model.py:3739-3754`).
- Before each provider attempt, `_check_limits_before_dispatch()` runs
  `check_token_limit(raise_for_equal=True)`, then
  `check_cost_limit(raise_for_equal=True)`, then the `dispatch_guard()`
  checks. The guard checks are skipped while token limits are suspended
  (`_model.py:3689-3701`). Callers: each generate attempt, after the cache
  lookup (`:1778`, `:1838`), native compaction (`:1532`), and the start of
  every bridged request (`src/inspect_ai/agent/_bridge/util.py:1283`).
- A turn is recorded once per top-level `generate()`, after it completes and
  including cache hits, and is then checked with `>` (`_model.py:2033-2039`,
  `_limit.py:787-802`, `:1214`). Turns are never checked before dispatch, so
  `turn_limit(N)` makes N+1 generations and raises after the last one. The
  bridge checks turns, with `>`, at the start of each request
  (`src/inspect_ai/agent/_bridge/sandbox/service.py:111`).
- `suspend_token_limit()` and `suspend_turn_limit()` stop recording *and*
  checking for their kind (`_limit.py:620-646`, `:796-820`). Cost has no
  suspension.
- `apply_limits()` catches only a bare error whose `source` is one of its
  limits (`_limit.py:181-187`).
- The sample runner flattens an escaping exception to its first leaf
  (`run.py:3402`, `src/inspect_ai/util/_anyio.py:8-9`). It records any
  `LimitExceededError` as the sample's limit, whatever its source
  (`run.py:3422-3429`).
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

### The sandbox bridge

- Each bridged request runs `_forward_provider_errors()`
  (`service.py:106-168`). It checks turns. If a limit is already kept, it runs
  the pre-dispatch check, so that a reached enclosing limit can replace the
  kept one, and replies with the kept limit. Otherwise it runs the generation
  under `_refuse_after_a_recorded_limit()`, a `dispatch_guard()` that raises a
  copy of the kept limit (`service.py:171-192`).
- On a limit error, `_first_control()` takes the first limit of an exception
  group (`service.py:240-259`). The bridge keeps it if nothing is kept yet, or
  if `_encloses()` says it encloses the kept one: it is an ancestor in the
  same tree, or a sample root while solvers run (`service.py:195-237`).
- `sandbox_agent_bridge()` raises the kept limit after the agent unwinds or
  returns. If an enclosing cancellation is pending, it is delivered first
  and the kept limit is lost
  (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:349-395`).
- Bridged host tools run under the same guard (`service.py:450-465`). A limit
  their model calls reach is answered as a tool error and never kept
  (`host_tool.py:438-462`).

## Design

### The rules

1. **One chain.** Token, cost, turn and message limits are nodes of one
   chain per execution context, in the order their `with` blocks were
   entered. A task inherits its parent's chain, as it inherits the trees
   today. Each node's position is its *depth*: its number of ancestors in the
   chain.
2. **Record, then check.** After a provider call, Inspect records the call
   into every node that meters it, then runs one check. Before a provider
   call, it runs the same check, with `>=` in place of `>`.
3. **One check.** The check walks the chain from the root and raises the
   first token, cost or turn limit that has been reached: the outermost,
   whatever its kind. A turn limit takes part in the pre-dispatch check too.
   Message limits keep their own check.
4. **Outermost wins.** Wherever Inspect has to choose one limit error from
   several, it chooses the one with the smallest depth. A limit error with no
   node in the chain (a `custom` limit, a time limit, a node never entered)
   ranks after every node that has one.
5. **Suspension hides one kind.** Inside `suspend_token_limit()`, token
   limits neither record nor check the calls made in the block, and the same
   holds for turn limits inside `suspend_turn_limit()`. Every other check,
   cost limits and `dispatch_guard()` checks included, runs as for any call.
6. **The owner handles its error.** Code that did not enter a token, cost or
   turn limit never turns that limit's error into a message, a tool error, a
   reply or a return value. It lets the error propagate. Message limits keep
   today's handling (see "Ownership").
7. **The owner checks at exit.** When `apply_limits()` or the sample's
   solvers end normally, Inspect runs the check once more (strict, `>`) over
   the chain. An exceeded limit raises there.
8. **The bridge keeps the outermost limit.** The sandbox bridge keeps the
   outermost limit any of its requests reached (generations and host tools
   alike), refuses every later model call with it, and raises it when the
   agent has unwound.

The sections below specify each rule.

### The limit chain

`src/inspect_ai/util/_limit.py` gains one ContextVar for the chain leaf and
one field on each chain node:

```python
_limit_chain: ContextVar[_Node | None] = ContextVar("limit_chain", default=None)


class _Node:
    parent: Self | None  # nearest ancestor of the same kind (unchanged)
    _outer: _Node | None  # nearest ancestor of any kind in the chain
    _in_chain: bool  # set when pushed; never cleared
```

- `_Tree.push()` for the token, cost, turn and message trees also sets
  `node._outer = _limit_chain.get()`, sets `node._in_chain = True` and moves
  `_limit_chain` to the node. `_Tree.pop()` checks that the chain leaf is the
  node being popped (the same stack discipline as today) and moves the chain
  leaf back to `node._outer`. The time and working trees do not touch the
  chain.
- The per-kind trees stay as views: `token_limit_tree.get()` is still the
  innermost token node, `_tree_root(token_limit_tree)` the outermost, and
  `parent` still links nodes of one kind. `sample_limits()`,
  `token_limit_usage()`, the checkpoint code and inspect_swarm's
  `record()` overrides keep working.
- `_chain_depth(node) -> int | None` counts `_outer` hops, or returns `None`
  for a node that was never pushed. Pointers survive exit, so a node's depth
  is fixed once it is entered and can be compared after its block has
  closed.
- `_rank(error) -> float` is `_chain_depth(error.source)` for a source in the
  chain, otherwise `math.inf`.
- `outermost_limit(ex: BaseException) -> LimitExceededError | None` returns
  the `LimitExceededError` leaf of `ex` (itself, or a member of a group,
  recursively, not causes or context) with the smallest rank. Ties go to the
  first in group order.
- `_outer_than(a, b) -> bool` is `_rank(a) < _rank(b)`.

In the sample, the sample's own limits are the chain's first nodes (token at
depth 0, cost 1, message 2, turn 3), so they outrank every agent or scoped
limit. Among themselves they rank in entry order, so a call that crosses both
the sample's token and cost limits raises the token limit, as it does today.
For limits passed to `run()` or `apply_limits()` the list order decides, which
does not matter, because one owner catches both.

### Recording and checking

```python
def record_model_call(usage: ModelUsage, cost: float | None) -> None:
    """Record one provider call into every limit that meters it (no check)."""
    if not token_limit_tree.is_suspended():
        record_model_usage(usage)  # token nodes, leaf to root (unchanged)
    if cost is not None:
        record_model_cost(cost)  # cost nodes (unchanged)


def check_limits(raise_for_equal: bool = False) -> None:
    """Raise the outermost reached token, cost or turn limit on the chain."""
    nodes = _chain_root_first()  # from _limit_chain via _outer
    for node in nodes:
        if isinstance(node, _TokenLimit) and token_limit_tree.is_suspended():
            continue
        if isinstance(node, _TurnLimit) and turn_limit_tree.is_suspended():
            continue
        if isinstance(node, (_TokenLimit, _CostLimit, _TurnLimit)):
            node._check_self(raise_for_equal)  # raises (with its SampleLimitEvent)
```

- `record_and_check_model_usage()` (`_model.py:3704`) calls
  `record_model_call(usage, total_cost)` and then `check_limits()`, for every
  call. Priced or unpriced, it always checks.
- `_check_limits_before_dispatch()` (`_model.py:3689`) calls
  `check_limits(raise_for_equal=True)` and then the `dispatch_guard()` checks.
  The guard checks always run (rule 5). It is still called per attempt, after
  the cache lookup, so a cache hit is never refused. The bridge still calls it
  at the start of every request, before compaction and the cache.
- `record_turn()` records the turn as today and then calls `check_limits()`
  in place of the turn tree's own check.
- `_TurnLimit._check_self()` gains `raise_for_equal: bool = False` and raises
  when `turns > limit`, or `turns == limit` with `raise_for_equal`.
  `turn_limit(N)` therefore allows N generations: the (N+1)th is refused
  before it is dispatched, where today it is made and raises after it
  returns. A cache hit is not refused, so a cached (N+1)th generation still
  raises after it is recorded. Native compaction is refused once a turn limit
  is reached. This is a behaviour change (open question 1).
- `check_token_limit()`, `check_cost_limit()` and `check_turn_limit()` stay as
  checks of their own kind. Inspect still uses them where one value changes:
  the `TaskState.token_limit` and `cost_limit` setters
  (`src/inspect_ai/solver/_task_state.py:369`, `:393`). The checkpoint resume
  (`sample_runtime.py:222-224`) calls `check_limits()` in place of its three
  checks.
- Message limits are unchanged: the innermost message node is checked at the
  start of `generate()` (`_model.py:1044`) and on every append to a limited
  conversation. A message check sees only that node, so precedence does not
  arise inside it. A message limit and a reached token limit at the same
  `generate()` raise the message limit first. That is fail-safe: the token
  limit stays reached and refuses the next dispatch (rule 3), or raises at its
  owner's exit (rule 7).

### Precedence

Rule 3 makes one call's result independent of kind: the outermost reached
limit raises. Rule 4 extends that to every place that combines errors:

| Where | Today | Now |
|---|---|---|
| One check after a call | token tree, then cost tree (priced calls only) | chain root first, every call |
| Pre-dispatch check | token, cost, then guards (guards skipped when suspended) | chain root first (turns included), then guards |
| Overlapping calls in one task group | the group's first leaf, wherever it is reduced | `outermost_limit()` at each reduction below |
| `apply_limits()` | catches a bare owned error only | catches a group whose leaves are all limit errors and whose outermost is owned (below) |
| Sample runner | first leaf of the group | first leaf, except that a limit leaf is replaced by `outermost_limit()` of the group |
| `decisive_tool_exception()` (`_call_tools.py:2016`) | termination, unexpected error, first limit, first leaf | termination, unexpected error, **outermost** limit, first leaf |
| `decisive_sentinel_exception()` (`_call_tools.py:180`) | termination, other error, first leaf | termination, other error, outermost limit |
| Bridge `_first_control()` | the group's first limit or refusal | the refusal if the group's first leaf is one, otherwise `outermost_limit()` |
| Bridge kept limit | first, replaced by a same-tree ancestor or sample root | replaced by any later limit that is outer (`_outer_than`) |

Each site keeps its existing ranking of limits against non-limit errors. Only
"which limit" changes. Ranking limits *above* other errors (or below them)
everywhere is a separate question and is left out (see "Not this design").

`apply_limits()` reduces the escaping exception with `outermost_limit()`. It
treats the error as its own when the exception is a bare limit error, or a
group whose every leaf is a `LimitExceededError`, and the outermost of them
has a `source` among its limits. Then it sets `limit_scope.limit_error` to
that leaf and, with `catch_errors=True`, swallows the exception. Any other
leaf (an unrelated error, a termination, a cancellation) leaves the group to
propagate unchanged. If the outermost leaf is owned, every other leaf is
owned too or belongs to a limit entered below it, so nothing outside the
scope is swallowed.

A request refused before dispatch, for example one that was queued for a
connection slot, the pause gate or a retry while another call reached a limit,
raises from the same check as a fresh call: the outermost limit reached at that
moment. In a bridged request the guard then raises a copy of the kept limit
when nothing outer has been reached.

Why outermost: the outermost error propagates past every inner owner, because
`apply_limits()` and the tool rules below catch only their own limits, so the
widest scope that must end does end. An inner limit reached by the same call
is not raised, but its scope is unwound by the outer error anyway, so no owner
is left waiting for it. Innermost-first would let an inner owner catch its
error and continue, and the outer limit would then depend on a later check
(see Alternatives).

### Suspension

Rule 5 replaces the separate paths for suspended calls. Today they already
neither record nor check token and turn limits, and they still record and check
cost limits. The one change is that `dispatch_guard()` checks now run for
suspended calls too. The bridge's guard is the only guard. Once the bridge has
kept a limit, its agent is ending, so an approval, review or sentinel call made
inside one of its requests is refused like any other model call. The approval
fails with the kept limit's copy, the request gets the kept limit's error
reply, and the proposed tool call does not run. `dispatch_guard()`'s
docstring loses the sentence about suspension.

Suspended calls still meet the outermost reached limit among the kinds they
see. A sample cost limit reached by an approval call raises the cost limit
ahead of a nested swarm cost cap, as for any call.

### Ownership

Rule 6, for token, cost and turn limits:

- **`execute_tools()`.** When `call_tool_task` starts a call, it captures
  `call_leaf = _limit_chain.get()`. A `LimitExceededError` (bare, or deciding
  a group) is *owned by the call* when its source is in the chain strictly
  below `call_leaf`: walking `source._outer` reaches `call_leaf` (or, with
  `call_leaf` `None`, the source is in the chain). Such an error is mapped to
  the `limit` tool error as today. That covers `as_tool()` limits and any
  `with token_limit()` inside a tool. An error that is not owned is handled
  like a termination raised in a tool: its `ToolEvent` is completed, its
  siblings in the stage are cancelled, and it propagates out of
  `execute_tools()` (`tool_exception` at `_call_tools.py:310-327`).
  `tool_call_error()` itself is unchanged; the per-call `except` decides
  before calling it.
- **Handoffs.** `agent_handoff()` catches only its own limits, through
  `apply_limits(..., catch_errors=True)`, plus message limits (see below). A
  foreign token, cost or turn limit propagates.
- **Bridged host tools.** `_raised()` (`host_tool.py:438`) uses the same test
  as `execute_tools()`, with the leaf captured when the host tool starts. An
  owned limit becomes a `ToolError` as today. A foreign one is offered to the
  bridge's kept limit (the next section), and the CLI receives the same tool
  error text, so the scaffold sees no difference.
- **Message limits.** A message limit measures the conversation it was
  checked against, and inside a tool that is the tool's own conversation (an
  `as_tool()` agent's messages). So a message limit error in a tool or handoff
  stays a tool error or handoff message whichever node raised it, as
  `test_agent_as_tool_respects_sample_limits` pins today.
- **Errors outside the chain** (a `custom` limit with no source, a time limit
  entered inside a tool) keep today's mapping too.

`run()`, `as_solver()`, deepagent and `background()` already let foreign
limits through. The sandbox service's route of a raw limit error to the sample
is unchanged: the bridge never raises one through it.

### The owner's exit check

Rule 7 has two call sites:

- `apply_limits()`: after the body returns normally, before it exits its
  limits, it calls `check_limits()` (strict). An exceeded limit raises there
  and is handled by the same `except` as one raised in the body: caught if
  owned and `catch_errors=True`, propagated otherwise. So `run()` returns
  `(state, error)` for its own exceeded limit even when something swallowed
  the error. A sample limit exceeded at that point leaves `run()` and ends
  the sample.
- The sample runner: after `plan()` returns, still inside the sample's limit
  scopes (`run.py:3269`), it calls `check_limits()` (strict). The existing
  `except LimitExceededError` records it. A resume for scoring skips this
  check: it restores a spent budget on purpose, and `restore_sample_runtime()`
  takes the same `check=False` switch for that reason.

The check is strict (`>`). A sample that used exactly its token budget, or
took exactly its N turns, and returned is not recorded as limited. The cost of
that choice: a pre-dispatch refusal at exactly the limit, swallowed by code
that does not own it, is not caught by this backstop. Rule 6 removes
Inspect's own swallowers, and the refusal repeats at every later model call.

Plain `with token_limit(...)` blocks get no exit check. Their author enters
and owns them, and may catch their errors on purpose.

### The sandbox bridge

`_forward_provider_errors()` becomes:

```python
async def generate_forwarding_errors(json_data, headers=None):
    try:
        with _refuse_after_a_recorded_limit(bridge):
            _check_limits_before_dispatch()  # outermost reached limit, then the kept copy
            return await generate(json_data, headers)
    except Exception as ex:
        ...  # terminations and sample failures: unchanged
        control = _first_control(ex)  # refusal if first, else outermost_limit(ex)
        if isinstance(control, LimitExceededError):
            bridge.keep_limit(control)
            _warn_other_errors(ex)
            return {PROVIDER_ERROR_KEY: provider_error_payload(ex)}
        ...  # refusals and other errors: unchanged
```

- `SandboxAgentBridge.keep_limit(error)` sets `generation_limit = error` when
  nothing is kept or `_outer_than(error, generation_limit)`. Host tools call
  it for a foreign limit. The field keeps its name, and its docstring now says
  it holds the outermost limit reached by the bridge's generations or host
  tools.
- The entry check now covers turns with `>=` (rule 3). The separate
  `check_turn_limit()` call and the "a limit is already kept" branch go away:
  with a kept limit, the pre-dispatch check raises any outer reached limit
  first (which then replaces the kept one), and the guard otherwise raises
  the kept copy, which does not replace itself.
- `_encloses()`, `_sample_roots()` and `_in_tree()` are deleted. The
  `solving()` dependency goes with them. Comparing positions in one chain
  works the same during the solve and in scorers.
- `sandbox_agent_bridge()` still raises the kept limit only once the agent
  has unwound or returned, after a pending enclosing cancellation
  (`bridge.py:340-395`, unchanged). If the agent is cancelled first, the kept
  limit is not raised there. Rule 7 then raises an exceeded sample or
  `apply_limits()` limit when its owner ends normally (for example a swarm
  that hard-stopped the member and then returned).

Every bridged request and host tool runs in the bridge's service task, which
inherits the agent's chain. So two limits reached by different requests are
either on one path from the root, where depth matches nesting, or in branches
that a request's filter entered below the bridge, which are deeper than every
limit enclosing the bridge. Comparing depth is therefore enough.

### What a runtime can rely on

For a runtime such as inspect_swarm, which runs several agents inside the
sample's limits, Inspect guarantees:

1. **A sample limit reaches the runtime.** A sample token, cost or turn
   limit reached by any of its agents' model calls, native or bridged, in a
   tool, a handoff, a subagent, a filter or an approval, reaches the runtime's
   code as a `LimitExceededError` whose `source` is the sample's node
   (`sample_limits().token`, `.cost`, `.turn`). It arrives bare, or in a
   group where `outermost_limit()` returns it. No Inspect code between the
   model call and the runtime converts it (rule 6), and no inner limit
   reached by the same call or a concurrent one replaces it (rules 3, 4, 8).
   For a bridged agent it arrives when the agent's CLI exits.
2. **A reached limit stays reached.** Every later dispatch under that
   sample, including the runtime's own model calls, native compaction,
   bridged requests and calls in their approval callbacks (token and turn
   limits excepted while suspended), is refused with the same node's error.
   Calls already dispatched complete, are recorded, and raise the same error
   after recording.
3. **The runtime may hold the error.** It can catch it, stop its agents
   (close levers, wait for in-flight calls within its grace, cancel the
   rest), write its ledger and re-raise the error, bare or in a group. The
   runner records it as the sample's limit (`EvalSampleLimit` of that type).
   During the stop, no model call can succeed under the reached limit, so
   the runtime's final step must make none.
4. **Losing it is not silent.** If the runtime, or a bridged agent cancelled
   before its CLI exited, drops the error and returns normally, the solvers'
   exit check raises an exceeded sample limit (rule 7).

The sample's time limit (a cancel scope around the solvers) and working limit
(a sample-wide cancellation) are outside these guarantees. They end the sample
by cancellation, which the runtime cannot hold.

Message limits are per conversation: a sample message limit reached in a
member's own conversation (one with no message limit of its own) is raised
there like any other foreign error, and reaches the runtime the same way.

### Unpriced calls

An unpriced call (no cost data for the model that served it, see
`model_usage_cost()`) still adds nothing to cost limits, because its cost is
unknown. It is now checked like every call (rule 2), so it raises a cost limit
that a concurrent priced call has reached. When an unpriced call is recorded
while a cost node is on the chain, Inspect logs a warning once per model:
"`<model>` has no cost data; cost limits do not meter its calls". This uses
the same `warn_once` helper as the served-model warning. The sample's
start-time requirement of cost data for the task's models and roles is
unchanged. Whether to refuse such calls outright is open question 2.

### Other limit kinds

- **Time.** Stays out of the chain. A time limit's error is raised where it
  was entered, by its cancel scope. A group reduction ranks it after every
  chain limit (rule 4), so a member's time limit and the sample's token limit
  in one group resolve to the token limit.
- **Working.** Stays out of the chain. The sample's working limit is enforced
  by the monitor's cancellation. Nested working limits are not enforced today
  (see "Not this design").
- **Message.** In the chain for ranking (rules 4 and 8), with its own check.

### What inspect_swarm can delete or simplify

This list is for the swarm's maintainers. Nothing here depends on it.

- **Compatibility cases of inspect_swarm#200 that go away.** Both of these now
  end on the outer swarm node: a call that crosses a member's token limit and
  a swarm cost cap, cost share or member cost limit, and a member stopped by
  its lever while a call that trips its token limit is in flight. An unpriced
  call in flight when a lever closes now raises the lever after it returns.
  The known gap for bridged members of a nested swarm (a cost-tree error
  hiding a later token-tree error from the outer swarm) is closed by rule 8.
- **Accepted bridged losses that go away.** First, a filter's parallel calls
  raising a swarm limit and the sample limit in one group now raise the
  sample limit (rule 4; the decision of 2026-11-04 in the swarm design).
  Second, a bridged host tool's model call reaching the sample limit after the
  bridge kept a member limit now promotes the sample limit (rule 6, host
  tools; the decision of 2026-11-11). Third, approval calls inside a bridged
  request are now refused by the kept limit (rule 5). Finally, a kept sample
  limit lost to a cancellation before the CLI exits is now raised at the
  solvers' exit check, when the limit is exceeded and not just reached
  (rule 7; the decision of 2026-11-04).
- **Promotions that become the rule.** Retries or in-flight requests that
  replace a kept member limit with an enclosing swarm limit (the decisions
  of 2026-11-06 and 2026-11-09) are rule 8 itself, so they need no separate
  entries.
- **Limit errors inside tools.** A swarm cap or lever reached inside a
  member's tool, or inside a synchronous deepagent subagent, now reaches the
  member wrapper at once instead of at the member's next model call. The cap
  node's `stop_swarm` call in `_check_self` is then needed only for timing,
  not correctness, and the wrapper could start the stop when it classifies
  the error.
- **The reserve.** Guarantees 1 to 3 let the runtime catch a sample limit and
  stop its members in an orderly way, so the 5% reserve no longer has to
  keep the stop orderly. It would still leave room for a final step that
  makes model calls, which is the swarm's own decision.
- **Sentinel.** inspect_sentinel's runner keeps the first limit of a group
  (`_runner.py:414-416`). It could use `outermost_limit()` (private, so on
  the same terms as the swarm's other internals).

What the swarm must change: its `_SwarmTurnNode._check_self()` takes the new
`raise_for_equal` argument. Its other overrides (`record()`, the token and
cost `_check_self()`, the message `check()`) are called as today.

## Alternatives considered

**Check cost before token.** It swaps which kind is late: a call that crosses a
token limit enclosing a cost limit would then raise the inner cost limit. It
fixes nothing structurally.

**Innermost limit wins.** The inner owner (a swarm cap, a member limit) then
always sees its own error first and can stop in order. But the outer limit
depends on a later check to be raised. If the inner owner catches its error
and returns without another model call, the outer limit is lost, and the
sample completes normally over its budget. Outermost-first fails safe instead:
the inner scope is unwound by the stronger error, and guarantee 3 gives a
runtime its orderly stop anyway.

**Raise every reached limit as a group.** It loses nothing, but every
consumer that catches `LimitExceededError` bare (`apply_limits()`, tools, the
runner, user code) would have to learn groups. Rejected for compatibility.

**One node carrying several kinds** (for example `usage_limit(tokens=...,
cost=...)`). A new public API that still needs an order between nodes. With
one chain, a token node and a cost node entered together are adjacent, and
the order is already defined. Rejected as unnecessary. It could still be
added later on top of the chain.

**Keep separate trees, compare by a global entry counter.** Stamping every
node with a sequence number at entry orders nodes that are on one path, but
does not tell ancestry from "entered earlier in a sibling task". A chain
pointer gives both depth and ancestry, at the same cost.

**Make every limit node check itself at exit.** One rule instead of two call
sites (rule 7), but it changes plain `with token_limit()` blocks whose author
catches the error inside on purpose, and it would fire at the sample roots
during a resume for scoring. The two owner sites cover what Inspect relies
on.

**Refuse dispatch when the bridge has kept a limit only for non-suspended
calls (today).** Keeps approvals running for an agent that is ending. That
costs money and leaves one more path to describe, for no benefit to the
ending agent.

## Compatibility and migration

No migration is required for code that uses the public limit API as
documented. Behaviour changes:

- **Which limit raises.** When one call crosses limits of different kinds,
  the outermost now raises. Within one kind nothing changes. For the sample's
  own limits nothing changes either (token, then cost, by entry order).
  Inside `run()` or `apply_limits()` the list order decides between the
  scope's own limits, and either is caught.
- **`turn_limit(N)`** now allows N generations and refuses the (N+1)th before
  dispatch. Today the (N+1)th is made and raises after it returns. The error
  type and message are the same ("Turn limit exceeded" becomes "Turn limit
  reached" when raised before dispatch, as token and cost messages already
  read). Native compaction and bridged requests are refused once a turn limit
  is reached. Logs of the same eval show one fewer `ModelEvent` for a
  turn-limited sample.
- **Limit errors in tools and handoffs.** A sample, `run()` or other
  enclosing token, cost or turn limit reached inside a native tool, handoff
  or bridged host tool now ends the owning scope at once. Before, the model
  saw a `limit` tool error or handoff message and the scope ended at its next
  model call. If no model call followed, the sample completed without a
  recorded limit. Limits the tool or handoff entered itself, and all message
  limits, behave as before.
- **Approval, review and sentinel calls** inside a bridged request are refused
  once the bridge has kept a limit. Outside the bridge nothing changes for
  them.
- **Unpriced calls** raise a reached limit after they return, and a warning
  names an unpriced model used under a cost limit.
- **`apply_limits()`** catches its own limit raised in an exception group,
  and raises an exceeded limit at normal exit. `run()` therefore returns
  `(state, error)` in both cases where today it raises or returns
  `(state, None)`.
- **The sample runner** records an exceeded sample limit found after the
  solvers return, and the outermost limit of an escaping group.
- **Bridge.** A bridged agent's kept limit is now the outermost of every
  limit its requests and host tools reached, whatever their kinds.
- **Private internals.** `_encloses()`, `_sample_roots()` and `_in_tree()`
  are removed. `_TurnLimit._check_self()` gains a parameter. Chain nodes gain
  `_outer` and `_in_chain`. inspect_swarm is the only known user of these
  classes (above).
- **Persisted data and the viewer.** None. `EvalSampleLimit`,
  `SampleLimitEvent`, `EvalConfig` limit fields and checkpoint payloads keep
  their shapes, and old logs read the same. No generated TypeScript type
  changes.
- **Docs.** `docs/setting-limits.qmd` and `docs/_agent_limits.md` state the
  precedence rule, that tool-based agents return a message for their own
  limits (an enclosing limit ends the caller), the new turn semantics, and the
  suspension rule.

## Security

- **What reaches this code.** Usage numbers and prices from providers, which
  set how far a node advances. Requests and host tool calls from a sandboxed
  CLI through the bridge, which are untrusted and can be sent in any number
  and order. No model output or tool argument decides precedence or
  ownership.
- **A sandboxed agent cannot change the outcome.** The chain, depths, the
  kept limit and the ownership test live in the host process and depend only
  on which `with` blocks the host entered. A CLI that floods requests after a
  limit gets the kept limit's error reply with no model call (rules 3 and 8),
  as today, and now also when an approval callback would have called a model.
- **Error text** forwarded to the CLI is the existing `provider_error_payload`
  of the limit error (its type, value and limit), unchanged.
- **Spend.** Every change either raises a reached limit sooner or makes a
  limit error propagate further. None lets a call through that is refused
  today, except that cache hits remain unrefused, as today.

## Testing

All tests use mockllm with scripted usage and `set_model_info()` prices (as
`tests/util/test_limit_cost.py` does). They need no network, Docker or
provider, so the default PR test job runs them. Their async tests also run
under trio with `--runtrio`.

- `tests/util/test_limit.py`, precedence:
  - one call crossing an inner token limit and an outer cost limit raises the
    cost limit, and the reverse nesting raises the token limit;
  - a turn limit outer to a token limit raises first;
  - the sample's token and cost limits keep entry order;
  - `outermost_limit()` over nested groups, non-chain sources and ties;
  - depth survives exit;
  - per-kind views (`get()`, `_tree_root()`) unchanged under interleaved
    entry;
  - popping out of order raises.
- `tests/util/test_limit_cost.py`: an unpriced call raises a cost limit
  reached by a priced call before it; the unpriced-model warning is logged
  once; a suspended call raises an outer cost limit ahead of an inner one
  (existing behaviour, pinned).
- `tests/util/test_limit_turn.py`: `turn_limit(3)` makes three generations
  and refuses the fourth before dispatch; a cache hit at the limit is served
  and then raises; native compaction is refused at the limit.
- `tests/util/test_limit_token.py`: a suspended call is not refused by a
  reached token limit, but is refused by a reached cost limit and by a
  `dispatch_guard()`.
- `tests/util/test_limit.py`, `run()` and `apply_limits()`: an owned limit
  raised inside the agent's task group is returned; a group with a foreign
  leaf propagates; an owned limit swallowed inside the agent is returned by
  the exit check; a sample limit swallowed inside the agent propagates from
  `run()`.
- `tests/agent/test_agent_execute.py`: a sample token limit reached inside an
  `as_tool()` agent ends the sample with `limit.type == "token"` and no
  further generation; `as_tool()`'s own token limit is still a tool error;
  `test_agent_as_tool_respects_sample_limits` (message) is unchanged; a
  handoff passes on a foreign token limit and still answers its own.
- `tests/test_eval.py` (or the existing sample-limit tests): a solver that
  swallows a sample token limit and returns is recorded as limited; a resume
  for scoring over a spent budget is not.
- `tests/agent/test_bridge_provider_errors.py`:
  - replace the `_encloses()` tests (`keeps_the_first_of_limits_in_different_trees`,
    `keeps_the_first_beside_an_unentered_limit` and the enclosing cases) with
    outermost-by-depth cases across kinds: a kept inner cost limit replaced
    by an outer token limit, and the reverse kept;
  - `test_first_limit_in_a_bridged_filter_group_is_raised` becomes
    outermost-of-group;
  - a refusal first in a group still fails the sample;
  - an approval call inside a request is refused once a limit is kept;
  - a request after a reached turn limit makes no generation;
  - a host tool whose model call reaches the sample limit after a member
    limit was kept makes the sample limit the kept one;
  - through `_run_bridged_agent()` (a one-sample eval with a served scaffold,
    no Docker), overlapping generations that reach a `run()` cost limit and
    then an outer `run()` token limit (`outer_limit`) return the outer token
    limit from the outer `run()`, and the same with the sample's token limit
    end the sample on it.
- `tests/tools/test_tools_bridge.py`: a bridged host tool's own limit is
  still the `limit` tool error text (the existing cases at `:1592` and
  `:1982`).

## Implementation plan

Each step is one PR, in this order. Each keeps the suite green.

1. **The chain and one check.** `src/inspect_ai/util/_limit.py`:
   `_limit_chain`, `_outer`/`_in_chain`, push/pop, `_chain_depth`, `_rank`,
   `outermost_limit`, `_outer_than`, `check_limits`, `record_model_call`,
   `_TurnLimit._check_self(raise_for_equal)`, `record_turn` calling
   `check_limits`. `src/inspect_ai/model/_model.py`:
   `record_and_check_model_usage`, `_check_limits_before_dispatch`.
   `src/inspect_ai/util/_checkpoint/sample_runtime.py`: `check_limits()`.
   Unpriced warning in `_model.py`. Tests: `tests/util/test_limit*.py`.
2. **Suspension.** `_model.py`: guard checks always run; `dispatch_guard()`
   docstring. Tests in `tests/util/test_limit_token.py` and
   `tests/agent/test_bridge_provider_errors.py`.
3. **Owners.** `_limit.py`: `apply_limits()` group handling and exit check.
   `src/inspect_ai/_eval/task/run.py`: solvers' exit check (skipped on a
   resume for scoring) and outermost limit in the escaping group.
   `src/inspect_ai/model/_call_tools.py`: `decisive_tool_exception`,
   `decisive_sentinel_exception`. Tests: `run()` tests, `tests/test_eval.py`.
4. **Ownership in tools.** `_call_tools.py`: the call leaf and ownership test
   in `call_tool_task`, `agent_handoff` through `apply_limits(catch_errors=True)`.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: `_raised` ownership,
   `keep_limit` for foreign limits. Tests: `tests/agent/test_agent_execute.py`,
   `tests/agent/test_agent_handoff.py`, `tests/tools/test_tools_bridge.py`.
5. **The bridge.** `src/inspect_ai/agent/_bridge/sandbox/service.py`: entry
   simplification, `_first_control` outermost, `keep_limit`, deletion of
   `_encloses`/`_sample_roots`/`_in_tree`.
   `src/inspect_ai/agent/_bridge/sandbox/types.py`: `keep_limit()`, the
   `generation_limit` docstring. Tests:
   `tests/agent/test_bridge_provider_errors.py`.
6. **Docs.** `docs/setting-limits.qmd`, `docs/_agent_limits.md`,
   `docs/_turn_limits.md`, and the docstrings of `token_limit()`,
   `turn_limit()`, `suspend_token_limit()`, `apply_limits()` and `run()`.

## Open questions

1. **Should `turn_limit(N)` refuse the (N+1)th generation before dispatch?**
   It makes turns follow the same reached/exceeded rule as tokens and cost,
   and stops paying for a generation whose output is discarded. It also
   removes the bridge's separate turn check. The cost is a visible change of
   one generation per turn-limited sample.
   Recommendation: yes, as designed.
   Confidence: high

2. **Should an unpriced call under an active cost limit be refused rather
   than warned about?** Refusing fails closed: a cost limit would then bound
   spend whatever model is called. But it would break evals that work today
   with a sample cost limit and an unpriced approver, sentinel monitor or
   subagent model, which the start-time check does not cover.
   Recommendation: warn once per model, as designed. Refusal can be added
   later behind the same test.
   Confidence: low. You may prefer to fail closed for cost limits.

## Not this design

- `SampleLimitEvent` is emitted by every token, cost, turn and message node
  that raises, scoped or not, so the viewer shows an agent's limit as a sample
  limit. inspect_swarm subclasses nodes to avoid it.
- Nested `working_limit()` scopes are never enforced; only the sample's root
  is polled.
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
