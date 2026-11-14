# Limit precedence and ownership

## Overview

Inspect's token, cost, turn and message limits become nodes of one *limit
chain* per execution context, ordered by when their `with` blocks were entered,
in place of one tree per kind. A model call is recorded into every kind, its
turn included, before one check walks that chain from the root and raises the
outermost limit that has been reached, whatever its kind. Every
place that has to choose one limit error from several (an exception group, the
sandbox bridge's kept limit, the sample runner) chooses the outermost by the
same rule.

A limit error is handled only by the code that entered its limit. Tools,
handoffs and bridged host tools turn into a message only the token, cost and
turn limits entered inside the call. Every other such limit error passes
through unchanged to the scope that owns it: `run()`, `apply_limits()`, the
sample, or a runtime such as inspect_swarm. Suspending token or turn metering
hides only that kind from the calls in the block.

The limit nodes' own state, not the errors they raise, is the record of what
happened. Once reached, a limit refuses every later model call in its scope.
A call that a cost limit cannot meter (a model with no price, a response
with no usage, or an attempt that fails without usage after it was sent)
marks that cost limit as reached, so a cost limit bounds spend; only a call
cancelled in flight goes unmetered. The marks survive a checkpoint resume. A scope that owns limits checks them when it ends normally, and
the sample decides its limit outcome from its own limit nodes once all of
its work, background cleanup included, has finished. So a limit error that
some handler catches and drops is not lost: it comes back at the next refused
call, or at its owner's exit.

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
  limit and never checks one. A cost limit that a concurrent priced call has
  reached is not raised after it, and an unpriced model that the start-time
  check does not cover (a subagent, approver or monitor model) can be called
  without bound under a cost limit. So can a priced model whose provider
  returns no usage.
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
- A cost limit bounds spend: a call it cannot meter is refused before
  dispatch or, when the provider returns no usage, stops every later call
  under it.
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
  `_limit.py:787-802`, `:1214`). That is in the outer frame, after the inner
  generation has already recorded and checked its usage (`_model.py:1989`).
  If that check raises (a child token or cost limit), no turn is recorded:
  under `turn_limit(1)`, three calls that each raise a child `token_limit(1)`
  and are caught leave the turn count at 0 (spike). Native compaction records
  no turn. Turns are never checked before dispatch, so `turn_limit(N)` makes
  N+1 generations and raises after the last one. The bridge checks turns,
  with `>`, at the start of each request
  (`src/inspect_ai/agent/_bridge/sandbox/service.py:111`).
- The cost of a call is `model_usage_cost()` (`_model.py:3757`): `None` when
  the called model has no cost data. Before the eval starts,
  `resolve_model_costs()` (`src/inspect_ai/model/_util.py:67-98`) requires
  cost data for the task's model and its model roles when a cost limit is
  set. Models resolved later (a subagent's `get_model()`, an approver,
  review or sentinel monitor model, a swarm member's model) are not
  covered.
- `suspend_token_limit()` and `suspend_turn_limit()` stop recording *and*
  checking for their kind (`_limit.py:620-646`, `:796-820`). Cost has no
  suspension.
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
    (`src/inspect_ai/agent/_bridge/util.py:493-505`).
  - `collect()` uses `unwrap_exception_group("single")`, which unwraps only a
    one-member group, so it keeps every candidate
    (`src/inspect_ai/util/_collect.py:32`).
- In-process sentinel execution wraps any exception escaping a monitor or
  protocol in `SentinelFailure(error)` (`src/inspect_ai/_sentinel/_dispatch.py:315-316`).
  A limit reached by a monitor's model call therefore leaves `generate()` as
  a `SentinelFailure`. Native tools unwrap it when the decisive error is a
  limit (`_sentinel_exception()`, `_call_tools.py:170-177`), and so does the
  sample runner (`run.py:2913-2916`). `apply_limits()` and the bridge's
  `_forward_provider_errors()` do not, so the bridge answers it as an
  ordinary error and keeps no limit.
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
| `turn_limit(1)`, three calls each inside a child `token_limit(1)`, each error caught | three calls made, turn usage 0 |

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
   into every node that meters it (for a top-level generation, its turn
   too), then runs one check. Before a provider call, it runs the same
   check, with `>=` in place of `>`.
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
7. **The owner checks at exit.** When an `apply_limits()` scope ends
   normally, Inspect runs the check once more over the chain. A limit raises
   there if it is exceeded, or if it is reached and has already raised (a
   call it refused). When one of its own limits escapes instead, the scope
   takes the outermost of that error and the limits that count at exit. The
   sample does the same once its task group has finished, on a normal or a
   limit exit.
8. **The bridge keeps the outermost limit.** The sandbox bridge keeps the
   outermost limit any of its requests reached (generations and host tools
   alike), refuses every later model call with it, and raises it when the
   agent has unwound.
9. **A cost limit refuses what it cannot meter.** While a cost limit is on
   the chain, a provider call to a model with no cost data, a call that
   returns no usage, or an attempt that may have been billed and fails
   without usage marks every such cost limit as reached. Later calls,
   retries included, are refused by the marked limits (rule 3).

Rules 3, 7 and 9 together make node state the record. The design does not
try to carry every limit or accounting error intact through every handler
that can catch one (a fallback, a hook, a first-error reduction, a cancelled
delivery). A swallowed error costs time, not budget or correctness: the next
call under the limit is refused before dispatch, and the owner's exit check
or the sample's final decision finds the limit. Where Inspect's own code
changes how errors travel (rules 4, 6 and 8, the sentinel wrapper), it is so
that the right owner hears first, not so that the error survives.

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
    _raised: bool  # set when this node's check raises; never cleared


class _CostLimit(_Node):
    _unmetered: str | None  # why a call under it could not be metered; never cleared
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
- `first_or_outermost_limit(group) -> BaseException` returns the group's
  first leaf (depth first, in order), except that when that leaf is a
  `LimitExceededError` it returns `outermost_limit(group)`. It is the
  reduction for sites whose policy is "the first error decides": a leading
  non-limit error still decides as today, and only the choice among limits
  changes.
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


def check_limits(raise_for_equal: bool = False, at_exit: bool = False) -> None:
    """Raise the outermost reached token, cost or turn limit on the chain."""
    nodes = _chain_root_first()  # from _limit_chain via _outer
    for node in nodes:
        if isinstance(node, _TokenLimit) and token_limit_tree.is_suspended():
            continue
        if isinstance(node, _TurnLimit) and turn_limit_tree.is_suspended():
            continue
        if isinstance(node, (_TokenLimit, _CostLimit, _TurnLimit)):
            # raises (with its SampleLimitEvent) and sets node._raised
            node._check_marked(raise_for_equal or (at_exit and node._raised))
```

- `_Node._check_marked(raise_for_equal)` raises for a cost node marked
  unmetered ("Unmetered calls"), and otherwise calls
  `_check_self(raise_for_equal)`; if that raises a `LimitExceededError`, it
  sets `self._raised = True` before re-raising. Every check path goes through it: `check_limits()` and the
  per-kind `check()` methods. inspect_swarm's `_check_self()` overrides are
  therefore marked too.
- The top-level generation records, then checks, once. The inner generation
  (`_model.py:1989`) calls `record_and_check_model_usage(..., check=False)`,
  which records the call's usage and cost (`record_model_call()`) and the
  sample's usage counters but runs no check. After the inner generation
  returns, the outer frame (`_model.py:2033-2039`) calls `record_turn()`,
  which now only records (it is still a no-op while turns are suspended, and
  still runs for cache hits), and then `check_limits()`. A call that crosses a
  child token or cost limit therefore advances every enclosing turn limit
  before the child limit raises, and the next generation is refused by a
  reached turn limit. The control channel's turn count is still pushed in a
  `finally` after `record_turn()`.
- If the inner generation fails after recording (a usage hook or the cache
  store raising), no turn is recorded, as today. The recorded usage is seen
  by the next pre-dispatch check, or by the owner's exit check.
- The other callers of `record_and_check_model_usage()` record and check as
  one step, because no turn is recorded for them today: native compaction
  (`_model.py:1547`) and the billed usage of a generation a sentinel sidecar
  refused after a provider error (`_model.py:1170`).
- `_check_limits_before_dispatch(model: Model | None = None)` (`_model.py:3689`)
  calls `check_limits(raise_for_equal=True)`, then the unpriced-model check
  (rule 9, "Unmetered calls") when `model` is given, and then the
  `dispatch_guard()` checks. The guard checks always run (rule 5). It is
  still called per attempt, after the cache lookup, so a cache hit is never
  refused. The per-attempt calls in `generate()` and native compaction pass
  their model. The bridge still calls it at the start of every request,
  before compaction and the cache, without a model; the generation's own
  per-attempt call then checks the model.
- `_TurnLimit._check_self()` gains `raise_for_equal: bool = False` and raises
  when `turns > limit`, or `turns == limit` with `raise_for_equal`, with the
  message "Turn limit reached" in the second case. `turn_limit(N)` therefore
  allows N generations: the (N+1)th is refused before it is dispatched, where
  today it is made and raises after it returns (decision: Ransom,
  2026-11-12). A cache hit is not refused, so a cached (N+1)th generation
  still raises after it is recorded. Native compaction and bridged requests
  are refused once a turn limit is reached.
- `check_token_limit()`, `check_cost_limit()` and `check_turn_limit()` stay as
  checks of their own kind. Inspect still uses them where one value changes:
  the `TaskState.token_limit` and `cost_limit` setters
  (`src/inspect_ai/solver/_task_state.py:369`, `:393`). The checkpoint resume
  (`sample_runtime.py:221-225`) calls `check_limits(at_exit=True)` in place
  of its three checks (see "Checkpoints").
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
| Overlapping calls in one task group | the group's first leaf, wherever it is reduced | the outermost limit at each limit-aware reduction below |
| `_apply_response_filter()`, a group of only limits, terminations and refusals (`agent/_bridge/util.py:493-505`) | its first leaf | `first_or_outermost_limit(group)`; a mixed group is still a `ResponseFilterError` |
| In-process sentinel wrapper (`_sentinel/_dispatch.py:315-316`) | wraps every error in `SentinelFailure` | raises a deciding limit bare (see "Sentinel failures") |
| `apply_limits()` | catches a bare owned error only | catches a group whose leaves are all limit errors and whose outermost is owned (below) |
| Sample runner (`run.py:3402`) | first leaf of the group | `first_or_outermost_limit(group)`, then the sample's final decision ("The owner's exit check") |
| `decisive_tool_exception()` (`_call_tools.py:2016`) | termination, unexpected error, first limit, first leaf | termination, unexpected error, **outermost** limit, first leaf |
| `decisive_sentinel_exception()` (`_call_tools.py:180`) | termination, other error, first leaf | termination, other error, outermost limit |
| Bridge `_first_control()`, a group of only limits and refusals | its first leaf | `first_or_outermost_limit(group)`: a leading refusal still wins |
| Bridge `_first_control()`, any other group | its first limit (other errors are logged) | `outermost_limit(group)` (other errors are logged) |
| Bridge kept limit | first, replaced by a same-tree ancestor or sample root | replaced by any later limit that is outer (`_outer_than`) |

Each site keeps its existing ranking of limits against non-limit errors. Only
"which limit" changes. Ranking limits *above* other errors (or below them)
everywhere is a separate question and is left out (see "Not this design").
A limit that a non-limit error displaces at one of these sites is not lost
for good: it stays reached, so the next dispatch is refused (rule 3), and the
owner's exit check raises it if the scope ends normally (rule 7).

Generic reductions are left alone. `tg_collect()` and
`unwrap_exception_group("first")` (`src/inspect_ai/_util/_async.py:44-124`)
still raise a group's first member, and `collect()` still unwraps only a
one-member group. When `tg_collect()` drops an outer limit in favour of an
inner one, the outer limit is still reached: the next call under it is
refused, the scope that owns it finds it at exit, and the sample's final
decision ranks it (see "Not this design").

`apply_limits()` treats an escaping exception as its own only when both
hold:

- its outermost limit (`outermost_limit()`; a bare error is its own) has a
  `source` that is one of the scope's limits, and
- every leaf is a `LimitExceededError` *covered by the scope*: its `source`
  is in the chain and is one of the scope's limits or a node entered below
  one of them (walking `source._outer` reaches one of the scope's limits).

Then it sets `limit_scope.limit_error` to that outermost limit and, with
`catch_errors=True`, swallows the exception. Every swallowed leaf is the
scope's own or a descendant's, whose scope this one ends anyway. If any leaf
is not covered, the whole exception propagates unchanged: an unrelated
error, a termination, a cancellation, a limit of an enclosing or sibling
scope, or a limit error whose source is unknown. A sourceless `custom` error
(documented in `docs/setting-limits.qmd:278-288`, and raised by
inspect_swarm members) ranks after every chain node, so it can never be the
outermost, but it is never covered either: a group holding an owned token
error and a sourceless custom error propagates, as it does today. A bare
error keeps today's rule: caught only if its source is one of the scope's
limits (`src/inspect_ai/util/_limit.py:158-160`, `:181-184`).

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

### Sentinel failures

A limit reached inside a sentinel (a monitor's model call, or a call the
bridge's guard refuses) must reach its owner as a limit. The in-process
sentinel wrapper (`src/inspect_ai/_sentinel/_dispatch.py:315-316`) changes
from wrapping every error to:

```python
except Exception as ex:
    decisive = decisive_sentinel_exception(ex)
    if isinstance(decisive, LimitExceededError):
        raise_unwrapped(ex, decisive)  # the limit, bare
    raise SentinelFailure(ex) from ex
```

`decisive_sentinel_exception()` is imported inside the handler, since
`_call_tools.py` imports the sentinel modules. It keeps its order: a termination, then any
other error, then the outermost limit. So the limit is raised bare only when
every leaf is a limit. A termination or another error in the same group still
becomes a `SentinelFailure` that fails the sample, as today. Since the limit
now leaves `generate()` bare, `apply_limits()` (and so `run()`), tools, the
bridge's `_forward_provider_errors()` and the runner all see it as a limit,
with no unwrapping of their own. The existing unwrapping in
`_sentinel_exception()` and the runner's `handle_error()` stays, for
`SentinelFailure`s raised elsewhere; for a limit it no longer runs. The other
places that raise `SentinelFailure` (`_dispatch.py:167`, `:320`, `:373`,
`:409`) wrap protocol errors, never a limit, and are unchanged.

### The owner's exit check

Rule 7 has two call sites:

- `apply_limits()`, on a normal return: after the body returns, before it
  exits its limits, it calls `check_limits(at_exit=True)`. A limit that
  raises there is handled by the same `except` as one raised in the body:
  caught if owned and `catch_errors=True`, propagated otherwise. A sample
  limit raised at that point leaves `run()` and ends the sample.
- `apply_limits()`, when one of its own limits escapes: before it records
  or swallows the error ("Precedence"), it reconciles it with node state
  (below), because the error it caught need not be the outermost limit that
  counts. In `run(limits=[outer_cost, inner_token])`, one task can raise the
  inner token limit while a sibling, finishing a call in its cancellation
  cleanup, pushes the outer cost limit over; `tg_collect()` keeps only the
  first error, the token limit.
- The sample runner, as its final limit decision (below).

**Reconciling an owned exit.** `counting_limit(nodes) -> LimitExceededError
| None` (in `_limit.py`) returns the error of the outermost node in `nodes`
that counts at exit (exceeded, reached and already raised, or marked
unmetered), built as the exit check builds it, or `None`. When an exception
escapes `apply_limits()` and is its own by the test in "Precedence", with
outermost limit `owned`, it computes `final = counting_limit(own_nodes +
enclosing_nodes)`: its own limits, whose state survives their exit, and the
nodes still on the chain around it. Then:

- `final` is `None` or not outer than `owned`: `owned` is the scope's
  error, as now;
- `final` is one of the scope's own limits: `final` becomes the scope's
  error in place of `owned` (returned by `run()`, or raised when
  `catch_errors` is false);
- `final` is an enclosing limit (a sample or caller's limit that counts):
  `apply_limits()` raises `final`, with the escaped exception as its
  context, whatever `catch_errors` says, as its normal-return check would.

An exception that is not the scope's own (a foreign limit, a non-limit
error, a termination, a cancellation) is not reconciled and propagates
unchanged, as it does today. The reconciliation runs after the body's task
groups have joined (the exception cannot escape before), so usage recorded
in cancellation cleanup counts.

**The sample's final limit decision.** The sample decides its limit outcome
from its own limit nodes once everything that can still record usage has
finished, and on every exit path that ends in a limit or in normal
completion. Today the solvers run in `run()`, a task of the sample's task
group, whose `finally` cancels the group (`run.py:3361-3364`) when `plan()`
returns or raises (`run.py:3269`); the group is joined at `run.py:3391-3392`.
A `background()` worker can finish a priced call in its cancellation cleanup,
reach a sample limit there, catch the error and return, after `plan()` has
returned or after an inner limit has already escaped from it. So the
decision is made after the join, from node state:

```python
def final_sample_limit(
    roots: Sequence[Limit], escaped: LimitExceededError | None
) -> LimitExceededError | None:
    """The sample's limit outcome: the outermost of `escaped` and its exit-reached roots."""
```

`final_sample_limit()` (in `_limit.py`) takes the sample's token, cost and
turn nodes and the limit error that escaped the solvers, if any. A root
counts when the exit check would raise it: exceeded, or reached and already
raised (including a cost node marked unmetered, rule 9). It returns the
outermost (`_outer_than`) of `counting_limit(roots)` (above) and `escaped`.
A root's error is the one its `_check_marked(raise_for_equal=node._raised)`
raises, caught and returned, so it carries the same message and
`SampleLimitEvent` as an exit check's. The runner calls it in two places, both after the join, so
after all cleanup:

- **Normal completion.** `run()` sets a local `solved = True` right after
  `plan()` returns. After the `async with anyio.create_task_group()` block
  and the existing `solver_cancel` check, when `solved` is set, the runner
  raises `final_sample_limit(roots, None)` if it is not `None`. The existing
  `except LimitExceededError` (`run.py:3422`) records it.
- **A limit escaped.** In that `except LimitExceededError as ex`, before it
  builds `EvalSampleLimit`, `ex = final_sample_limit(roots, ex)`. An inner
  cost limit that escaped while a background worker's cleanup pushed the
  sample token limit over is recorded as the sample token limit, which
  outranks it. An escaped sample limit stays itself unless an outer root
  also counts.

The stated policies for everything else are unchanged. A non-limit error
(after `first_or_outermost_limit()` reduces a group, the deciding leaf is not
a limit) goes to the error handling as today, so an error still outranks a
limit at the runner. A termination keeps its own `except` clause. An
operator interrupt and a limit delivered by cancellation (the working limit,
or a limit a sandbox service routes to the sample) keep their handling
inside `run()`, which sets the outcome before the join and leaves `solved`
unset; the decision does not override them. A resume for
scoring skips the decision: it restores a spent budget on purpose, and
`restore_sample_runtime()` takes the same `check=False` switch for that
reason. The roots' state survives the exit of their `with` blocks, so the
call in the `except` clause, which runs after the sample's limit scopes have
exited, reads the same values.

`run()` must read the scope's error after the block, not return from inside
it. Today it returns `(state, None)` inside the `with` (`_run.py:103-105`). If
the exit check raises an owned limit and `apply_limits()` suppresses it, that
pending `return` would still complete, and the limit would be lost. `run()`
becomes:

```python
with apply_limits(limits or [], catch_errors=True) as limit_scope:
    agent_name = name or agent_display_name(agent)
    async with span(name=agent_name, type=AGENT_SPAN_TYPE, id=span_id):
        state = await agent(state, **agent_kwargs)

if limits is None:
    return state
return state, limit_scope.limit_error  # None when no owned limit raised
```

Synchronous deepagent subagents call `run()` and get the fix with it.
Background deepagent subagents already read the scope after their block
(`agent_tool.py:768-780`). `as_tool()`, `as_solver()` and handoffs enter
`apply_limits()` without `catch_errors`, so a limit raised at their exit
propagates.

**What raises at exit.** A node raises if it is exceeded (`> limit`), or if
it is reached (`== limit`) and has raised before (`_raised`): the exit check
passes `raise_for_equal=node._raised` for each node. So:

- A sample that used exactly its token budget, or took exactly its N turns,
  and returned without trying another call, is not recorded as limited.
- A sample in which a call was refused at exactly the limit is. This is the
  case where the refusal's error was lost on its way to the owner: a bridged
  request refused at the sample's budget and kept, then a hard stop that
  cancels the bridge before the kept limit is delivered; or a runtime that
  dropped the error.
- A limit that raised and whose budget was then increased (for example by
  a solver that catches the sample token limit and sets `state.token_limit`
  higher) is no longer reached, so it does not raise.
- A cost limit marked unmetered (rule 9) counts as reached and raised, so it
  raises at exit whatever its spend, with a message naming the unmetered
  call.

The `_raised` mark is per node and is never cleared, so it survives the
cancellation that loses the error itself. For the sample's own limits it
also survives a checkpoint resume ("Checkpoints").

### Checkpoints

A checkpoint stores the sample roots' usage, and a normal resume restores
it into fresh roots and checks them: `dump_sample_runtime()` writes the
token usage, cost and turns (`src/inspect_ai/util/_checkpoint/sample_runtime.py:47-96`),
the checkpointer stores that payload
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:624-633`), and
`restore_sample_runtime(check=True)` reseeds the roots and runs the token,
cost and turn checks (`sample_runtime.py:153-163`, `:221-225`; called for a
normal resume at `checkpointer_impl.py:147-152`). Node state that is not
usage would be lost there: a cost limit marked unmetered would come back at
its spent cost, possibly under budget, and a limit that refused a call at
exactly its budget would come back unmarked, so the resumed sample would
make calls it was refused before the checkpoint.

So the payload carries the marks of the sample's roots, as three optional
keys beside the usage:

```python
{
    ...,  # token_usage, cost, turns: unchanged
    "cost_unmetered": "<reason>" | None,  # the cost root's _unmetered
    "limits_raised": ["token", "cost", "turn"],  # roots whose _raised is set
}
```

`dump_sample_runtime()` writes them from the roots. `restore_sample_runtime()`
sets `_unmetered` and `_raised` on the fresh roots when the keys are
present, before its check, and the check becomes `check_limits(at_exit=True)`
over the restored roots: a marked cost root, an exceeded root and a root
that refused a call and is still reached all raise at resume, so the
resumed attempt ends on that limit before making a call. A payload written
before this change has neither key and restores as today, with no marks:
the marks did not exist when it was written, so nothing is lost. A newer
payload read by an older Inspect has two keys it does not read, which the
restore ignores (it reads only the keys it knows, with `payload.get()`).
A resume for scoring (`check=False`) restores the marks too but runs no
check, as it runs none today: it restores a spent budget on purpose.

Only the sample's roots are stored: scoped limits (`run()`, a swarm's
nodes) are re-entered fresh by the resumed agents, as their usage is
today.

Plain `with token_limit(...)` blocks get no exit check. Their author enters
and owns them, and may catch their errors on purpose. Their nodes are no
longer on the chain when an enclosing owner checks at exit, so a mark on them
has no effect.

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
        ...  # refusals, response filter errors, unmetered calls: fail the sample
        ...  # other errors: unchanged
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
  limit is not raised there. Its node raised when it was reached, so it
  carries the `_raised` mark, and rule 7 raises it when its owner ends: an
  `apply_limits()` scope that ends normally, or the sample's final decision
  however the solvers ended, whether the limit is exceeded or was reached
  exactly by a refused request: for example a swarm that hard-stopped the
  member and then returned.
- An unmetered call (`UnmeteredCallError`, see "Unmetered calls") in a
  bridged generation fails the sample through `bridge.request_fail()`, as a
  `ModelRefusalError` or `ResponseFilterError` does, so the sample fails with
  the error's message. If a cancellation displaces that failure before it is
  delivered, the marked cost limit still refuses every later request and is
  found by the sample's final decision.

Every bridged request and host tool runs in the bridge's service task, which
inherits the agent's chain. So two limits reached by different requests are
either on one path from the root, where depth matches nesting, or in branches
that a request's filter entered below the bridge, which are deeper than every
limit enclosing the bridge. Comparing depth is therefore enough.

### What a runtime can rely on

For a runtime such as inspect_swarm, which runs several agents inside the
sample's limits, Inspect guarantees the following, given one prerequisite.

**Prerequisite: the runtime owns its agents' tasks.** Limit errors travel
with tasks, not with the chain. Work started with `background()` runs in the
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
lifetime and its errors keep reaching the sample, where the final decision
ranks them. The guarantees below are about work in tasks the runtime owns.

1. **A sample limit reaches the runtime.** A sample token, cost or turn
   limit reached by any of its agents' model calls, native or bridged, in a
   tool, a handoff, a subagent, a filter or an approval, reaches the runtime's
   code as a `LimitExceededError` whose `source` is the sample's node
   (`sample_limits().token`, `.cost`, `.turn`). It arrives bare, or in a
   group where `outermost_limit()` returns it. No Inspect code between the
   model call and the runtime converts it (rule 6) or wraps it (a sentinel
   raises it bare), and no inner limit reached by the same call or a
   concurrent one replaces it (rules 3, 4, 8). For a bridged agent it
   arrives when the agent's CLI exits. If a handler on the way swallows it
   (a fallback, a hook, `tg_collect()` keeping another error), it arrives
   instead at the next call any agent makes under the sample, which is
   refused with it (guarantee 2).
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
4. **Losing it is not silent.** On normal completion, or an exit whose
   deciding exception is a `LimitExceededError`, the sample's final decision
   records the outermost sample limit that counts at exit (rule 7): one that
   is exceeded, reached exactly after refusing a call, or marked unmetered.
   That covers a runtime, or a bridged agent cancelled before its CLI
   exited, that drops the error, and an inner limit that ends the solvers
   first. It decides after background cleanup, so usage recorded there
   counts. An exit decided by a non-limit error, a termination or an
   operator interrupt keeps that outcome.
5. **A cost limit bounds spend.** No model without cost data is dispatched
   under a sample or swarm cost limit, and a call that returns no usage, or
   an attempt that may have been billed and fails without usage, marks
   every cost limit it ran under as reached (rule 9). Spend under a cost
   limit is therefore at most the limit, plus the calls already in flight
   when it was reached or marked, plus one call for each in-flight call that
   is cancelled (cancelled calls are not marked; "Unmetered calls").

The sample's time limit (a cancel scope around the solvers) and working limit
(a sample-wide cancellation) are outside these guarantees. They end the sample
by cancellation, which the runtime cannot hold.

Message limits are per conversation: a sample message limit reached in a
member's own conversation (one with no message limit of its own) is raised
there like any other foreign error, and reaches the runtime the same way.

### Unmetered calls

Under a cost limit, a call must not run unless its cost can be metered
(decision: Ransom, 2026-11-12, refusing unpriced models). Three things make a
call unmetered: the model has no cost data, the provider returns a response
with no usage, or an attempt that may have been billed fails without usage.
All are handled the same way: they mark the cost limits the call ran under
as reached. The first two raise one error; the third lets the attempt's own
error propagate, and the marked limit refuses its retry.

**Marking.** `mark_unmetered(reason: str)` (in `_limit.py`) sets
`_unmetered = reason` and `_raised = True` on every `_CostLimit` on the
chain whose limit is not `None`: the cost limits the call would have been
charged to. A marked node raises in every check: `_check_marked()` raises
`LimitExceededError("cost", value=<its cost>, limit=<its limit>,
source=node)` with the message "Cost limit reached: <reason>" before it
calls `_check_self()`, so inspect_swarm's `_check_self()` overrides need no
change. Every later dispatch under the node is therefore refused before it
is sent (rule 3), in any task that shares the node, whatever happened to the
error that marked it; a call already in flight raises it after recording;
and the exit check and the sample's final decision raise it (rule 7). The
mark is never cleared, as the `_raised` mark is not, and a sample's cost root
keeps it across a checkpoint resume ("Checkpoints").

**The error.** Marking is followed by raising one private error,
`UnmeteredCallError(PrerequisiteError)`, defined in `_limit.py` beside the
cost limit. Its message says which case it is and what to do:

- no price: "cost_limit requires cost data for every model called under it.
  No cost data for '<model>'. Use set_model_cost() or --model-cost-config to
  configure pricing." For a model not in the model database the last
  sentence is the one `model_usage_cost()` already uses: "It is not in the
  model database, so use set_model_info() with a ModelInfo that includes
  cost." `resolve_model_costs()` (`src/inspect_ai/model/_util.py:67-98`)
  and this error share one helper for this text.
- no usage: "cost_limit requires usage from every call made under it.
  '<model>' returned no token usage, so the cost of the call is unknown."

The error is not a `LimitExceededError`, so no limit owner catches it. When
it reaches the sample runner the sample fails with it, as a sample error.
Native tools do not map it (`tool_call_error()` returns `None` for it), and a
bridged host tool treats it as an unexpected error, which fails the sample
(`host_tool.py:450-452`); a bridged generation fails the sample with it
through `bridge.request_fail()` (above). Wherever it is swallowed instead
(a compaction fallback, a hook that logs and continues, a first-error
reduction, the sentinel wrapper, a cancelled bridge delivery), the mark does
the rest: the next call under the limit is refused, and the sample records a
cost limit whose message names the unmetered call.

**No price: refused before dispatch.**

- **When.** In `_check_limits_before_dispatch(model)`, after the limit check
  and before the guards: if any cost node on the chain has a limit (not
  `None`) and `_get_model_info_direct(model)` has no `cost`, it marks and
  raises. This is the same lookup and the same test as
  `model_usage_cost()`'s "called model has no cost data" case and as the
  start-time check. It runs per attempt, for `generate()` and native
  compaction, and for every role: approver, review, sentinel monitor and
  subagent models included, suspended or not.
- **Not refused.** A cache hit (no dispatch). A priced model whose provider
  reports that an unpriced model served the call: that call is priced at the
  called model's rates with a warning, as today. A model with cost data of
  zero.
- Marking here, though nothing was spent, ends every later call under the
  limit, priced or not. An unpriced model under a cost limit is a
  configuration error, and the sample fails with it unless something
  swallows the error; the mark keeps a swallowed error from letting the
  sample continue as if the limit still metered everything.

**No usage: marked after the call returns.** `ModelOutput.usage` is optional
(`src/inspect_ai/model/_model_output.py:286`), and a provider can omit it:
the OpenAI-compatible response conversion keeps a missing `usage` as `None`
(`src/inspect_ai/model/_openai.py:1206-1231`). Today the inner generation
records nothing when `output.usage` is `None` (`_model.py:1988`), and native
compaction records nothing when its `usage` is `None` (`_model.py:1546`), so
such calls never advance a cost limit, and a priced model that never reports
usage can be called without bound under one. Now, in each of those two
places, when usage is `None` and a cost node on the chain has a limit,
Inspect marks and raises after the call's `ModelEvent` is completed (so the
transcript shows the call) and before the output is returned or cached. A
cache hit records no usage and is not affected. Usage that is present but
zero is metered as zero, as today. The billed usage of a sentinel-sidecar
refusal (`_model.py:1170`) is recorded only when the sidecar reports it, as
today; that path follows a provider error, not a successful response, and
is left as is.

**A dispatched attempt that fails without usage: marked before any retry.**
An attempt can be sent, run on the provider, and still end with an exception
instead of a response, so no usage is recorded: the failure path completes
the `ModelEvent` with the error and records nothing (`_model.py:1865-1882`).
Two of those failures are retried for every provider, and the default retry
policy has no attempt limit (`_model.py:2066-2081`, `src/inspect_ai/model/_retry.py:70-74`),
so under a cost limit today a model that keeps timing out after it starts
streaming is paid for again and again with nothing charged. Now, in the
`except Exception` of each generation attempt (`_model.py:1865`), and in a
new `except Exception` around native compaction's provider call
(`self.api.compact()` in `_compact()`, `_model.py:1534`), when a cost node on
the chain has a limit and `_attempt_may_have_been_billed(ex, stream_observer)`
is true (compaction passes no observer), Inspect marks the node before the
exception propagates to the retry loop. The retry's own pre-dispatch check
is then refused by the marked limit, so the attempt is not repeated: the
caller sees the cost limit, and the attempt's error stays recorded in its
failed `ModelEvent`. When no retry is left, the attempt's error propagates
as today, and the mark still refuses every later call.
`_attempt_may_have_been_billed()` (in `_model.py`) is true when:

- the error is an `AttemptTimeoutError`, a `StreamIdleTimeoutError` or a
  `NoStreamDataError` (each raised while, or after, the provider held an
  accepted request), or a provider SDK timeout (an `httpx.TimeoutException`
  in the error or its `__cause__` chain, which is how the OpenAI, Anthropic
  and other httpx-based SDKs raise theirs); or
- the stream observer received any chunk of output before the error.

It is false for every other failure: an error response from the provider (a
rate limit, an overload, an invalid request, a server error) that arrives
before any output, a connection that is refused or reset before any output,
and every failure before the request is sent (the pre-dispatch check, a wait
for a connection slot, the pause gate). Those are treated as unbilled, as
today, and are retried as today. The reason recorded on the node names the
model and the failure: "'<model>' failed after the request was sent
(<error>), so the cost of the call is unknown."

A cancelled attempt is not marked: cancellation of an in-flight call
(a time limit, a sibling's failure, an operator interrupt, a runtime's hard
stop) completes its event as today and records nothing. The cancelled scope
ends, so a cancelled attempt is not retried. Spend from cancelled calls is
therefore bounded by one call per cancellation of a scope with a call in
flight, not by the limit (see the open question).

After a call, the check runs for every call (rule 2), so a call with no cost
made outside any cost limit still checks token and turn limits.

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

The swarm's limits design (inspect_swarm's `design/swarm-limits.md`,
"Bridged generations", "Exhaustion and errors" and "Interactions") handles
each of these interactions as a case of its own. Under the rules above they become:

- **Calls that cross limits of different kinds.** A call that crosses a
  member's token limit and a swarm cost cap, cost share or member cost limit
  ends on the outer swarm node (rule 3). So does a member stopped by its
  lever while a call that trips its token limit is in flight. A call with no
  cost data cannot run under a swarm cost node at all (rule 9).
- **Bridged members of a nested swarm.** A cost-tree error no longer hides a
  later token-tree error from the outer swarm: the bridge keeps the outermost
  of the two whatever their kinds (rule 8).
- **Bridged losses.** A filter's parallel calls that raise a swarm limit and
  the sample limit in one group raise the sample limit (rule 4 and the
  filter's reduction). A bridged host tool's model call that reaches the
  sample limit after the bridge kept a member limit makes the sample limit
  the kept one (rule 6, host tools). Approval calls inside a bridged request
  are refused by the kept limit (rule 5). A kept sample limit lost to a
  cancellation before the CLI exits is recorded by the sample's final
  decision, whether it was exceeded or reached exactly by a refused request
  (rule 7).
- **Promotions.** A retry or in-flight request that replaces a kept member
  limit with an enclosing swarm limit is rule 8 itself, so it needs no
  separate case.
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
cost `_check_self()`, the message `check()`) are called as today, through
`_check_marked()`. A member whose model has no cost data, or whose provider
returns no usage, under a swarm cost node now marks that node and every
cost node above it (rule 9), so the swarm needs pricing and usage for every
member model wherever it uses cost nodes. Its per-member `background_target`
is what the guarantees' prerequisite asks for, so it keeps it.

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

**A non-strict exit check (`>=` for every node).** It would catch a refusal
at exactly the budget without a mark, but would also record as limited every
sample that used exactly its budget, or took exactly its N turns, and
returned. The `_raised` mark separates the two.

**Carry every limit and accounting error intact to its owner.** Make each
handler that can catch one (fallbacks around compaction, hooks, first-error
reductions such as `tg_collect()`, the sentinel wrapper, a bridge delivery
that a cancellation can displace) re-raise or forward it. Each review of
that approach found another such handler, and the list is open-ended: any
user or extension code can catch an exception. The rules here make the
nodes the record instead, so a handler that swallows a limit or an
unmetered-call error delays it by at most one call and cannot lose it.
Inspect still changes its own handlers where that decides *which owner*
hears first (rules 4, 6 and 8, the sentinel wrapper), not merely whether
the error survives.

**Fail an unmetered call without marking the cost limit.** Raising the
error alone fails the sample when the error arrives, but a handler that
swallows it lets the next unmetered call through, and the one after, so
spend under the limit is unbounded. The mark costs one field.

**Route background work to the `run()` that started it.** Every
`background()` call would need an owner per limit scope, which changes the
sample-scoped lifetime that deepagent's default children rely on and that
`background()` documents. A runtime that needs its agents' background errors
installs a target for them, as inspect_swarm does.

**Warn about unpriced calls instead of refusing them.** Keeps evals with an
unpriced approver, monitor or subagent model running, but a cost limit then
does not bound their spend: their calls never advance it, so its checks
never fail. Refusal was chosen (decision: Ransom, 2026-11-12).

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
  type is the same; its message reads "Turn limit reached" when raised before
  dispatch, as token and cost messages already do. Native compaction and
  bridged requests are refused once a turn limit is reached. Logs of the same
  eval show one fewer `ModelEvent` for a turn-limited sample.
- **Turns of calls that cross a child limit.** A generation whose token or
  cost check raises now counts as a turn of every enclosing turn limit. Code
  that catches a child limit and calls again reaches its turn limit sooner
  than today, where such calls were never counted.
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
- **Unpriced models under a cost limit fail.** A call to a model with no
  cost data, made while a sample, agent or swarm cost limit is active, is
  refused with an `UnmeteredCallError` (a `PrerequisiteError`) that names the
  model and how to price it, and marks the cost limits it ran under as
  reached. The sample fails with that error, or, if something swallows it,
  ends on the marked cost limit at its next call or at exit. Evals that
  pass today with a cost limit and an unpriced approver, review or sentinel
  monitor model, or a subagent that resolves an unpriced model, now fail on
  that model's first call. The fix is to give the model a price with
  `set_model_cost()` or `--model-cost-config` (or `set_model_info()` for a
  model not in the database). Evals with no cost limit, and cache hits, are
  unaffected. Unpriced calls outside a cost limit now also raise a reached
  token or turn limit after they return, like any call.
- **Timeouts after dispatch under a cost limit stop spending.** Under an
  active cost limit, an attempt that times out after it was sent (attempt,
  stream-idle or SDK timeout, or an empty 200 stream), or fails after
  streaming any output, now marks the cost limits it ran under, so it is not
  retried and no later call runs under them: the sample ends on its cost
  limit. Today such an attempt is retried, without limit by default, with
  nothing charged. Provider error responses and connection failures before
  any output are retried as today. Without a cost limit nothing changes.
- **Calls with no usage under a cost limit fail.** A provider response with
  no usage, under an active cost limit, now raises an `UnmeteredCallError`
  after the call and marks the cost limits it ran under as reached, so no
  later call runs under them. This affects OpenAI-compatible servers and
  native-compaction providers that omit usage, and test models scripted to
  return none (`mockllm` fills in usage by default). Without a cost limit
  nothing changes. Fallback handlers that catch every exception (ReAct's
  overflow recovery, `CompactionAuto`'s native-to-summary fallback) are
  unchanged: one that catches the error falls back once, and its next model
  call is refused by the marked limit.
- **Sentinel monitors.** A limit reached inside an in-process sentinel now
  leaves `generate()` as the bare `LimitExceededError`, not a
  `SentinelFailure` wrapping it, when no other error decides. Code that
  caught `SentinelFailure` to find a limit sees the limit directly.
- **`apply_limits()`** catches its own limit raised in an exception group
  (when every limit in it is its own or a descendant's; any other leaf,
  including a sourceless `custom` limit, propagates the group as today),
  and at normal exit raises a limit that is exceeded, or reached after it
  refused a call. When its own limit escapes, it reports the outermost
  limit that counts at that point instead, which can be another of its own
  limits or an enclosing one it then raises. `run()` therefore returns `(state, error)` in both cases
  where today it raises or returns `(state, None)`.
- **The sample runner** decides the sample's limit after the solvers and
  the sample's background work have finished: it records an exceeded, marked
  or refusing sample limit found then, on a normal return, and records it in
  place of an escaped inner limit that it outranks. Errors, terminations,
  operator interrupts and limits delivered by cancellation are handled as
  today.
- **Background work.** Unchanged. Work started with `background()` in the
  sample's task group, including deepagent's default background children,
  still sends its errors to the sample, so a child's limit of its parent's
  `run()` still ends the sample rather than returning from that `run()`, as
  today. The runtime guarantees state this as a prerequisite rather than
  changing it.
- **Bridge.** A bridged agent's kept limit is now the outermost of every
  limit its requests and host tools reached, whatever their kinds.
- **Private internals.** `_encloses()`, `_sample_roots()` and `_in_tree()`
  are removed. `_TurnLimit._check_self()` gains a parameter. Chain nodes gain
  `_outer`, `_in_chain` and `_raised`, and cost nodes `_unmetered`.
  `record_turn()` no longer checks. inspect_swarm is the only known user of
  these classes (above).
- **Persisted data and the viewer.** The checkpoint sample-runtime payload
  gains two optional keys, `cost_unmetered` and `limits_raised`
  ("Checkpoints"). Payloads without them restore as today, and an older
  Inspect ignores them. A sample resumed from a checkpoint taken after its
  cost limit was marked, or after a limit refused a call at exactly its
  budget, now ends on that limit at resume instead of continuing.
  `EvalSampleLimit`, `SampleLimitEvent` and `EvalConfig` limit fields keep
  their shapes, and old logs read the same. No generated TypeScript type
  changes.
- **Docs.** `docs/setting-limits.qmd` and `docs/_agent_limits.md` state the
  precedence rule, that tool-based agents return a message for their own
  limits (an enclosing limit ends the caller), the new turn semantics, the
  suspension rule, and that every model called under a cost limit needs cost
  data.

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
- **Spend.** Every change either refuses a call sooner (a reached turn
  limit, an unpriced model or a marked cost limit, an approval after the
  bridge kept a limit) or makes a limit error propagate further. None lets a
  call through that is refused today; cache hits remain unrefused, as today.
  With rule 9, a cost limit bounds spend (plus the calls in flight when it
  is reached or marked, and one call per cancellation of an in-flight call) whatever model a sample, a subagent, an approver or
  a sandboxed agent's request selects: the check runs on the model a bridged
  request resolves to, whatever name the CLI sent. Because the bound comes
  from node state, a handler that swallows the error, in Inspect or in user
  code, cannot extend it.

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
    `first_or_outermost_limit()` with a leading non-limit error and with a
    leading inner limit;
  - depth survives exit;
  - per-kind views (`get()`, `_tree_root()`) unchanged under interleaved
    entry;
  - popping out of order raises.
- `tests/util/test_limit_cost.py`:
  - under `cost_limit(1.0)` a call to an unpriced mockllm model is refused
    before dispatch with `UnmeteredCallError` whose message names the model
    and the missing price, with no provider call made; the same inside
    `suspend_token_limit()` (an approver's call) and for native compaction;
  - a cache hit of an unpriced model is served; with no cost limit an
    unpriced call is made;
  - under `cost_limit(1.0)` a priced model whose scripted output has
    `usage=None` raises `UnmeteredCallError` (message: no usage) after one
    call; a native compaction (a provider stub returning `None` usage) does
    the same; without a cost limit both succeed;
  - marking: after either error is caught and dropped, the next call to a
    priced model under the same `cost_limit()` makes no provider call and
    raises the cost limit with the unmetered reason; the same from a sibling
    task under the shared node; an enclosing and an inner cost limit are
    both marked;
  - containment: a missing-usage error swallowed by a hook that logs and
    continues, by `tg_collect()` beside an owned token limit that `run()`
    catches, and by a stub in-process sentinel monitor (wrapped in
    `SentinelFailure`) each leaves the cost limit marked, so the next call
    is refused;
  - failed attempts (a priced provider stub, `max_retries` unset): an
    attempt that streams a chunk and then raises `StreamIdleTimeoutError`,
    and one that raises `AttemptTimeoutError`, each make one provider call,
    mark the cost limit and are not retried (the retry is refused by the
    cost limit); a native compaction whose provider raises an
    `httpx.TimeoutException` is marked the same way; an error response
    before any output (a stub raising a 429) is not marked and is retried
    as today; a generation cancelled in flight is not marked; without a cost
    limit every case is retried as today;
  - a suspended call raises an outer cost limit ahead of an inner one
    (existing behaviour, pinned).
- `tests/util/test_limit_turn.py`: `turn_limit(3)` makes three generations
  and refuses the fourth before dispatch; a cache hit at the limit is served
  and then raises; native compaction is refused at the limit and records no
  turn; under `turn_limit(1)`, a call that raises a child `token_limit(1)`
  (caught) counts one turn and the next call is refused by the turn limit;
  the same with a child `cost_limit()`.
- `tests/util/test_limit_token.py`: a suspended call is not refused by a
  reached token limit, but is refused by a reached cost limit and by a
  `dispatch_guard()`.
- `tests/util/test_limit.py`, `run()` and `apply_limits()`: an owned limit
  raised inside the agent's task group is returned; a group with a foreign
  leaf propagates; a group of an owned token limit and a sourceless `custom`
  limit propagates as a group; a group of an owned limit and a limit of a
  node entered below it is caught and returns the owned one; an owned token limit exceeded and swallowed inside the
  agent is returned as `(state, error)` by the exit check (the return path
  of `run()`); an owned limit reached exactly and swallowed after a refused
  call is returned; an owned limit reached exactly with no refused call
  returns `(state, None)`; a sample limit swallowed inside the agent
  propagates from `run()`; a synchronous deepagent subagent's swallowed
  limit is reported as its result;
  - owned-exit reconciliation (each synchronized by an `anyio.Event`):
    `run(limits=[cost_limit(1), token_limit(1)])` over `tg_collect()`, where
    one task raises the token limit first and a sibling's call, finishing in
    its cancellation cleanup with token metering suspended, pushes the cost
    limit over, returns the cost limit; the same where the sibling pushes an
    enclosing `cost_limit()` over raises that enclosing limit from `run()`;
    the same with a foreign or non-limit error escaping is unchanged.
- `tests/checkpoint/test_sample_runtime.py`: dump and restore round-trip a
  marked cost root (`cost_unmetered`) and a token root that refused a call
  at exactly its budget (`limits_raised`); a normal resume
  (`restore_sample_runtime(check=True)`) of either raises that limit before
  any call; a scoring resume (`check=False`) restores the marks and does not
  raise; a payload without the new keys restores unmarked, as today.
- `tests/util/test_limit.py`, sentinel: with a stub in-process monitor whose
  model call reaches an owned `run()` cost limit, `run()` returns that limit
  (not a `SentinelFailure`); a monitor that raises a `RuntimeError` beside a
  limit still fails with `SentinelFailure`.
- `tests/agent/test_agent_execute.py`: a sample token limit reached inside an
  `as_tool()` agent ends the sample with `limit.type == "token"` and no
  further generation; `as_tool()`'s own token limit is still a tool error;
  `test_agent_as_tool_respects_sample_limits` (message) is unchanged; a
  handoff passes on a foreign token limit and still answers its own.
- `tests/test_eval.py` (or the existing sample-limit tests): a solver that
  swallows a sample token limit and returns is recorded as limited; a solver
  whose call was refused at exactly the sample token budget, which swallows
  the refusal and returns, is recorded as limited; a solver that uses exactly
  the budget and returns is not; a solver that catches the limit and raises
  `state.token_limit` is not; a resume for scoring over a spent budget is
  not; a sample with a cost limit whose solver calls an unpriced model fails
  with `UnmeteredCallError`; a solver that swallows that error and returns
  ends on the marked cost limit;
  - final decision after cleanup (each with the worker synchronized by an
    `anyio.Event`, never a sleep): a `background()` worker makes a priced
    call in its cancellation cleanup after `plan()` returns, exceeds the
    sample cost limit, catches the error and returns: the sample ends on the
    cost limit; the same with a cleanup call refused at exactly the budget;
    `plan()` raises an inner `cost_limit()` while a worker's cleanup call
    pushes the sample token limit over and is caught: the sample ends on the
    sample token limit, not the inner cost limit; `plan()` raises a
    `RuntimeError` while a worker's cleanup exceeds a sample limit: the
    sample errors as today; an operator interrupt with an exceeded sample
    limit keeps its operator outcome.
- `tests/agent/test_agent_overflow_compaction.py`: a forced compaction whose
  summary call reaches the sample token limit falls back to the overflow
  filter as today, and the agent's next generation is refused with the
  sample token limit (the sample ends on it); if the overflow filter cannot
  shorten the conversation and the agent ends, the sample's final decision
  records the limit.
- `tests/agent/test_bridge_provider_errors.py`:
  - replace the `_encloses()` tests (`keeps_the_first_of_limits_in_different_trees`,
    `keeps_the_first_beside_an_unentered_limit` and the enclosing cases) with
    outermost-by-depth cases across kinds: a kept inner cost limit replaced
    by an outer token limit, and the reverse kept;
  - `test_first_limit_in_a_bridged_filter_group_is_raised` becomes
    outermost-of-group, with the inner limit first in the filter's group, so
    that it covers `_apply_response_filter()`'s reduction as well as
    `_first_control()`;
  - a refusal first in a group of only limits and refusals still fails the
    sample; a group `[ModelRefusalError, ValueError, LimitExceededError]`
    keeps the limit and logs the others, as today;
  - a bridged sentinel monitor whose model call reaches a limit keeps that
    limit;
  - an unpriced bridged model under a cost limit fails the sample with
    `UnmeteredCallError`, and a bridged response without usage does too;
    with the bridged agent cancelled before the failure is delivered, a
    retried request is refused by the marked cost limit and the sample ends
    on it;
  - a kept sample token limit reached exactly by a refused request, then a
    cancellation of the bridged agent before delivery and a normal return
    from the solver, ends the sample on the token limit;
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
   `_limit_chain`, `_outer`/`_in_chain`/`_raised`, push/pop, `_chain_depth`,
   `_rank`, `outermost_limit`, `first_or_outermost_limit`, `_outer_than`,
   `_check_marked`, `check_limits`, `counting_limit`, `final_sample_limit`,
   `record_model_call`,
   `_TurnLimit._check_self(raise_for_equal)`, `record_turn` recording only.
   `src/inspect_ai/model/_model.py`: `record_and_check_model_usage(check=)`,
   the inner generation recording without a check, the outer frame's
   `record_turn()` then `check_limits()`, `_check_limits_before_dispatch`.
   `src/inspect_ai/util/_checkpoint/sample_runtime.py`:
   `check_limits(at_exit=True)` at restore, and the `limits_raised` key.
   Tests: `tests/util/test_limit*.py`, `tests/checkpoint/test_sample_runtime.py`.
2. **Unmetered calls.** `_limit.py`: `_CostLimit._unmetered`,
   `mark_unmetered()`, `UnmeteredCallError`, the marked-node raise in
   `_check_marked()`. `_model.py`: the unpriced check in
   `_check_limits_before_dispatch(model)` and the model passed by
   `generate()`'s and compaction's per-attempt calls; marking and raising
   where the inner generation (`:1988`) and native compaction (`:1546`)
   find no usage under a cost limit; `_attempt_may_have_been_billed()` and
   marking in the generation attempt's `except Exception` (`:1865`) and
   around native compaction's provider call (`:1534`).
   `src/inspect_ai/util/_checkpoint/sample_runtime.py`: the
   `cost_unmetered` key. `src/inspect_ai/model/_util.py`: the
   shared message helper used by `resolve_model_costs()`.
   `src/inspect_ai/agent/_bridge/sandbox/service.py`: `UnmeteredCallError`
   fails the sample. Tests: `tests/util/test_limit_cost.py`,
   `tests/test_eval.py`, `tests/agent/test_bridge_provider_errors.py`,
   `tests/checkpoint/test_sample_runtime.py`.
3. **Suspension.** `_model.py`: guard checks always run; `dispatch_guard()`
   docstring. Tests in `tests/util/test_limit_token.py` and
   `tests/agent/test_bridge_provider_errors.py`.
4. **Owners and reductions.** `_limit.py`: `apply_limits()` group handling,
   exit check and owned-exit reconciliation. `src/inspect_ai/agent/_run.py`: the return after the
   block. `src/inspect_ai/_eval/task/run.py`: `first_or_outermost_limit`
   for the escaping group, and the final decision after the sample task
   group has joined (on a normal return, and in `except
   LimitExceededError`; skipped on a resume for scoring).
   `src/inspect_ai/model/_call_tools.py`: `decisive_tool_exception`,
   `decisive_sentinel_exception`. `src/inspect_ai/_sentinel/_dispatch.py`:
   a deciding limit raised bare. Tests: `run()` and sentinel tests in
   `tests/util/test_limit.py`, `tests/test_eval.py`,
   `tests/agent/test_agent_overflow_compaction.py`.
5. **Ownership in tools.** `_call_tools.py`: the call leaf and ownership test
   in `call_tool_task`, `agent_handoff` through `apply_limits(catch_errors=True)`.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: `_raised` ownership,
   `keep_limit` for foreign limits. Tests: `tests/agent/test_agent_execute.py`,
   `tests/agent/test_agent_handoff.py`, `tests/tools/test_tools_bridge.py`.
6. **The bridge.** `src/inspect_ai/agent/_bridge/sandbox/service.py`: entry
   simplification, `_first_control` outermost, `keep_limit`, deletion of
   `_encloses`/`_sample_roots`/`_in_tree`. `src/inspect_ai/agent/_bridge/util.py`:
   `_apply_response_filter()`'s reduction.
   `src/inspect_ai/agent/_bridge/sandbox/types.py`: `keep_limit()`, the
   `generation_limit` docstring. Tests:
   `tests/agent/test_bridge_provider_errors.py`.
7. **Docs.** `docs/setting-limits.qmd`, `docs/_agent_limits.md`,
   `docs/_turn_limits.md`, and the docstrings of `token_limit()`,
   `cost_limit()`, `turn_limit()`, `suspend_token_limit()`, `apply_limits()`
   and `run()`.

## Open questions

1. **Should cancelling an in-flight call mark the cost limit?** A cancelled
   call may have been billed, and nothing is charged for it. Marking would
   make the bound strict (the limit plus calls in flight), but a member's
   time limit, a runtime's hard stop or a sibling's failure that cancels a
   call under a sample cost limit would then end every later call in the
   sample on that cost limit, and record it as the sample's outcome: a
   swarm member's time limit under a sample cost limit would end the whole
   swarm. Not marking leaves one unmetered call per cancellation of a scope
   with a call in flight, which only code that cancels and then keeps
   calling can repeat.
   Recommendation: do not mark cancelled calls, as designed.
   Confidence: low (you may prefer the strict bound for cost limits, as for
   unpriced models)

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
- Handlers that catch every exception between a model call and its owner:
  ReAct's overflow recovery (`_handle_overflow()`,
  `src/inspect_ai/agent/_react.py:697-747`), `CompactionAuto`'s
  native-to-summary fallback (`src/inspect_ai/model/_compaction/auto.py:85-101`),
  hooks run through `_call_hook_safely()` (`src/inspect_ai/hooks/_hooks.py:1218-1236`),
  and `tg_collect()`'s first-error reduction. They are unchanged. What a
  limit or unmetered-call error swallowed there costs: it surfaces one step
  later, at the next call under the limit, which is refused at no cost, or
  at the owner's exit or the sample's final decision. Spend stays bounded and
  the sample limit is not lost. Making each re-raise these errors would only
  make them arrive sooner.
- Routing `background()` work to the `run()` or runtime that started it.
  Default deepagent background children keep their sample-scoped lifetime
  and report to the sample; a runtime that needs their errors installs a
  background target (see "What a runtime can rely on").
