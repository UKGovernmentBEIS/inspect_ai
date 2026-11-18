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
sample, or a runtime such as inspect_swarm. Suspending a kind of limit hides
that kind from the calls in the block: approval, review and sentinel calls,
which suspend token, turn and cost limits, neither charge nor check them,
and skip the sandbox bridge's refusal, as they do today.

The limit nodes' own state, not the errors they raise, is the record of what
happened. Once reached, a limit refuses every later model call dispatched in
its scope; a response served from Inspect's cache is not a dispatch and is
still served, as today.
Under a cost limit, a call to a model with no price of its own is refused
before dispatch. Failed attempts, calls cancelled in flight and responses
that report no usage are not charged, as today, so they can take spend past
a cost limit; failing calls that report no usage is left to a separate
design. A limit error that reaches its owner stands. When
none does, each owner checks its own limits when it ends normally: an
`apply_limits()` scope the limits it entered, and the sample its own limits
once all of its work, background cleanup included, has finished (except on
a resume for scoring). So, within a running attempt, a limit error that some handler
catches and drops is not lost: it comes back at the next refused call, or at
its owner's exit. A checkpoint resume is the exception: checkpoints store
usage but not the mark of a limit that refused a call, and the restore
assigns the stored usage, so a resumed sample can lose such a refusal, and
a limit that work before the restore reached and swallowed can be reopened
by it.

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
  still record into and check cost limits, so an approver's or monitor's
  spend can end the sample on its cost limit.
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

- One precedence rule for which limit error wins: within one check, across
  overlapping calls, for a request refused before dispatch, inside exception
  groups, and in the sandbox bridge.
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
- The cost of a call is `model_usage_cost()` (`_model.py:3757-3819`). When
  the provider reports that other models served the call
  (`ModelAPI.served_model_usage()`), and each of them has cost data, the
  call is priced from them before the called model's own cost data is
  consulted (`:3786-3816`). OpenRouter reports this for routers such as
  `openrouter/auto` (`_providers/openrouter.py:190-200`), which have no
  entry in the model database, so a router call is priced today from its
  serving models alone. Otherwise the cost is `None` when the called model
  has no cost data. Before the eval starts, and for each
  task enqueued later, `resolve_model_costs()`
  (`src/inspect_ai/model/_util.py:67-98`, called at
  `src/inspect_ai/_eval/eval.py:879` and `:1352`) requires cost data for the
  task's model and every model of its model roles when a cost limit is set,
  and raises `PrerequisiteError` otherwise. A role can serve suspended calls
  only: the in-process sentinel host resolves its monitor model from the
  `monitor` role (`_HostNative._resolve()`,
  `src/inspect_ai/_sentinel/_dispatch.py:416-421`). Models
  resolved later (a subagent's `get_model()`, an approver or review model
  given by name, a swarm member's model) are not covered.
- A call whose usage is missing records nothing into token or cost
  limits: the inner generation records usage only when `output.usage` is
  set (`_model.py:1988`), and native compaction only when its `usage` is
  (`:1546`). Some providers read usage a response left out as zero:
  Mistral's streams without a usage chunk (`_providers/mistral.py:646-652`),
  SageMaker's stream assembly (`_providers/sagemaker.py:790-791`) and Grok's
  protobuf conversion (`_providers/grok.py:683`), which record zero.
- `suspend_token_limit()` and `suspend_turn_limit()` stop recording *and*
  checking for their kind (`_limit.py:620-646`, `:796-820`). Cost has no
  suspension in the code read for this design; approval, review and
  sentinel calls suspend token, turn and working limits only. The design
  requires a cost suspension (implementation plan, step 0):
  `suspend_cost_limit()`, under which `record_model_cost()` records nothing
  and `check_cost_limit()` does nothing, also for `cost_limit()` scopes
  opened inside the block, and `suspend_limits()`, which suspends cost,
  token, turn and working limits together and is used by in-process
  sentinel dispatch, the sentinel sidecar's result lookup, tool approval
  and tool review. Model and role usage still record the suspended spend.
- Failed attempts are not charged. When an attempt raises (an HTTP error
  response, a timeout, a connection reset, a cancellation), the attempt's
  `ModelEvent` is completed with the error and no usage is recorded
  (`_model.py:1865-1907`); timeouts are always retried, other errors as
  `should_retry()` decides, and the retry policy has no attempt limit unless
  `max_retries` or `timeout` is set (`_model.py:2066-2081`,
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
   check, with `>=` in place of `>`. A generation served from the cache
   makes no provider call and records no usage: it records its turn and
   checks only turn limits, so it is served under a reached token or cost
   limit, as today ("Cache hits").
3. **One check.** The check walks the chain from the root and raises the
   first token, cost or turn limit that has been reached: the outermost,
   whatever its kind. A turn limit takes part in the pre-dispatch check too.
   Message limits keep their own check.
4. **Outermost wins.** Wherever Inspect has to choose one limit error from
   several, it chooses the one with the smallest depth. A limit error with no
   node in the chain (a `custom` limit, a time limit, a node never entered)
   ranks after every node that has one.
5. **A suspended call is invisible to the kinds it suspends.** Inside
   `suspend_token_limit()`, `suspend_turn_limit()` or `suspend_cost_limit()`
   (or `suspend_limits()`, all of them), limits of that kind neither record
   nor check the calls made in the block, and the unpriced-model refusal
   (rule 9) skips a call while cost is suspended. The `dispatch_guard()`
   checks are skipped while token limits are suspended, as today, so
   `suspend_token_limit()` and `suspend_limits()` skip them and
   `suspend_turn_limit()` or `suspend_cost_limit()` alone does not.
   Approval, review and sentinel calls run under `suspend_limits()`, so they
   skip the bridge guard. Message limits are still checked.
6. **The owner handles its error.** Code that did not enter a token, cost or
   turn limit never turns that limit's error into a message, a tool error, a
   reply or a return value. It lets the error propagate. Message limits keep
   today's handling (see "Ownership").
7. **Each owner checks its own limits at exit.** A limit error that
   reaches its owner stands. When an `apply_limits()` scope ends normally,
   Inspect checks the token, cost and turn limits that scope entered, and
   no others. A limit raises there if it is exceeded, or if it is reached
   and has already raised at that budget (a call it refused). The sample
   does the same for its own limits once its task group has finished, when
   its solvers returned normally and the attempt is not a resume for
   scoring. An enclosing limit is left to its own owner.
8. **The bridge keeps the outermost limit.** The sandbox bridge keeps the
   outermost limit any of its requests reached (generations and host tools
   alike), refuses every later model call with it, and raises it when the
   agent has unwound.
9. **A cost limit refuses an unpriced model.** While a cost limit is on the
   chain and cost is not suspended, a call to a model with no cost data of
   its own, a router included, is refused before dispatch. Nothing is
   marked. Failed attempts, cancelled calls and responses that report no
   usage are not charged, as today.

Rules 3 and 7 together make node state the record of limits. The design
does not try to carry every limit error intact through every handler that
can catch one (a fallback, a hook, a first-error reduction, a cancelled
delivery). A swallowed limit error costs time, not budget: the next call
under the limit is refused before dispatch, and if no limit error reaches
the limit's owner, that owner's exit check finds it. A plain `with token_limit()`
block has no owner but its author and no exit check, so its limit is found
only by a call made while the block is open ("The owner's exit check").
That holds within one attempt, up to its checkpoint restore: a checkpoint
resume keeps usage but drops the mark of a limit that refused a call, and
its assigning restore can reopen a limit that work before it reached and
swallowed ("Checkpoints", "Limits swallowed before a checkpoint
restore"). An unpriced-model refusal (rule 9) is not a limit
error, and nothing marks it: a handler that swallows one and calls the model
again is refused again, with nothing spent ("Unpriced models"). Where
Inspect's own
code changes how errors
travel (rules 4, 6 and 8), it is so that the right owner hears first, not so
that the error survives.

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
    _raised_at: float | None  # the greatest effective limit at which its check raised


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
        record_model_cost(cost)  # cost nodes; a no-op while cost is suspended


def check_limits(raise_for_equal: bool = False, *, turns_only: bool = False) -> None:
    """Raise the outermost reached token, cost or turn limit on the chain.

    With turns_only (after a cache hit), only turn nodes are checked.
    """
    for node in _chain_root_first():  # from _limit_chain via _outer
        if _counted(node) and (not turns_only or isinstance(node, _TurnLimit)):
            # raises (with its SampleLimitEvent) and sets node._raised_at
            node._check_marked(raise_for_equal)


def check_own_limits(limits: Sequence[Limit]) -> None:
    """At an owner's normal exit: raise the outermost of its own limits that counts."""
    own = [n for n in limits if n._in_chain and _counted(n)]
    for node in sorted(own, key=_chain_depth):  # root first
        node._check_marked(node._refused_at_budget())


def _counted(node: Limit) -> bool:
    """A token, cost or turn node whose kind is not suspended."""
    if isinstance(node, _TokenLimit):
        return not token_limit_tree.is_suspended()
    if isinstance(node, _CostLimit):
        return not cost_limit_tree.is_suspended()
    if isinstance(node, _TurnLimit):
        return not turn_limit_tree.is_suspended()
    return False
```

- `_Node._check_marked(raise_for_equal)` calls
  `_check_self(raise_for_equal)`; if that raises a `LimitExceededError`, it
  sets `self._raised_at` to the greater of its current value and
  `self.limit` (the effective limit, a live override included) before re-raising. Every check path goes through it:
  `check_limits()` and the per-kind `check()` methods. inspect_swarm's
  `_check_self()` overrides therefore set the mark too.
- `_Node._refused_at_budget() -> bool` is `self._raised_at is not None and
  self._raised_at == self.limit`: the node raised under the budget in force
  now. It reads the effective limit, so any way the budget changes (a
  `limit` setter, a live override set or cleared through
  `set_sample_limit_override()`) is covered without hooking the change.
  Keeping the greatest refused budget, not the last, is what makes this
  hold across an intervening lower budget: `TaskState`'s `token_limit` and
  `cost_limit` setters check the node with `>`
  (`src/inspect_ai/solver/_task_state.py:358-370`, `:392`), so a node
  refused at 10, lowered to 5 (which raises there) and restored to 10 must
  still count its refusal at 10. Usage never decreases (token metering is
  non-decreasing, cost and turns only add), so a refusal at a budget above
  the current one already means usage exceeds it, and the greatest refused
  budget is the only one equality can depend on. The one place a counter
  goes down is a checkpoint restore, which assigns a root's counter and
  clears that root's mark ("Checkpoints"). A
  node whose limit is `None` is never reached by count, so the mark does not
  matter for it (an inspect_swarm lever raises on its own state).
- The top-level generation records, then checks, once. The inner generation
  (`_model.py:1989`) calls `record_and_check_model_usage(..., check=False)`,
  which records the call's usage and cost (`record_model_call()`) and the
  sample's usage counters but runs no check. After the inner generation
  returns, the outer frame (`_model.py:2033-2039`) calls `record_turn()`,
  which now only records (it is still a no-op while turns are suspended, and
  still runs for cache hits), and then `check_limits()` (for a cache hit,
  `check_limits(turns_only=True)`, below). A call that crosses a
  child token or cost limit therefore advances every enclosing turn limit
  before the child limit raises, and the next generation is refused by a
  reached turn limit. The control channel's turn count is still pushed in a
  `finally` after `record_turn()`.
- The inner generation's usage hooks (`emit_model_usage()`), legacy
  telemetry and `cache_store()` follow its usage record
  (`_model.py:1989-2004`). Today the record's check raises before them, so
  an output that crosses a limit is neither reported to usage hooks nor
  cached. With the check moved to the outer frame, such an output is
  reported to the hooks and cached before the check raises. A later cache
  hit of it is served, as any cache hit is.
- **Cache hits.** Today a cached response returns from the inner
  generation before any token or cost check (`_model.py:1744-1773`), so it
  is served even when an enclosing token or cost limit is already exceeded,
  and only the outer frame's turn record and check run. That stays: the
  outer frame reads the cache-hit flag the inner generation already sets
  (`_request_was_cache_hit`, `_model.py:1765-1767`, read at `:2055`) and,
  for a hit, calls `check_limits(turns_only=True)` after `record_turn()`.
  A hit records no usage or cost, so the token and cost nodes it skips are
  unchanged by it; a reached one refuses the next dispatch (`>=`) or is
  found by its owner's exit check. Turn limits count and check a cached
  generation as any other: a cached (N+1)th generation under
  `turn_limit(N)` records its turn and raises. This is the native cache
  only: a bridged request is checked at entry, before compaction and the
  cache, and the bridge's kept limit refuses it, as today ("The sandbox
  bridge").
- If the inner generation fails after recording (a usage hook or the cache
  store raising), no turn is recorded, as today, and that error leaves the
  call; it is not compared with a limit the recorded usage reached (a limit
  error that reaches its owner stands, and so does any other error). The
  reached limit refuses the next pre-dispatch check, or is found by its
  owner's exit check.
- Native compaction (`_model.py:1547`) records and checks as one step, since
  it records no turn.
- A top-level generation a sentinel sidecar recovers as a refusal after a
  provider error returns normally from `_generate_prepared()`
  (`_model.py:1153-1188`), but `_generate()` raised, so its turn was never
  recorded there, and today the billed usage is recorded with a check and no
  turn at all. It now follows the same record, turn, check order, exactly
  once: when `refusal_after_error()` returns an output, the billed usage
  (`refused_usage()`) is recorded without a check
  (`record_and_check_model_usage(..., check=False)`), then `record_turn()`
  runs with the control channel's count pushed in its `finally`, then
  `check_limits()`, with the existing `except LimitExceededError` that
  records the sidecar's reports around it. So repeated recovered turns
  advance a turn limit, and the next generation is refused before dispatch
  once it is reached. When `refusal_after_error()` returns `None` or raises,
  the outcome is unchanged: the billed usage is recorded and checked as one
  step, no turn is recorded, and the error stands.
- `_check_limits_before_dispatch(model: Model | None = None)` (`_model.py:3689`)
  calls `check_limits(raise_for_equal=True)`, then the unpriced-model check
  (rule 9, "Unpriced models") when `model` is given, and then the
  `dispatch_guard()` checks, which are skipped while token limits are
  suspended, as today (`_model.py:3689-3701`, rule 5). It is
  still called per attempt, after the cache lookup, so a native cache hit
  is never refused ("Cache hits"). The per-attempt calls in `generate()` and native compaction pass
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
  (`src/inspect_ai/solver/_task_state.py:369`, `:393`), and the checkpoint
  resume, which keeps its three checks (`sample_runtime.py:221-225`, see
  "Checkpoints").
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
| Pre-dispatch check | token, cost, then guards (guards skipped while tokens are suspended) | chain root first (turns included), then guards (still skipped while tokens are suspended) |
| Overlapping calls in one task group | the group's first leaf, wherever it is reduced | the outermost limit at each limit-aware reduction below |
| `_apply_response_filter()`, a group of only limits, terminations and refusals (`agent/_bridge/util.py:493-505`) | its first leaf | `first_or_outermost_limit(group)`; a mixed group is still a `ResponseFilterError` |
| `apply_limits()` | catches a bare owned error only | catches a group whose leaves are all limit errors and whose outermost is owned (below) |
| Sample runner (`run.py:3402`) | first leaf of the group | `first_or_outermost_limit(group)` |
| `decisive_tool_exception()` (`_call_tools.py:2016`) | termination, unexpected error, first limit, first leaf | termination, unexpected error, **outermost** limit, first leaf |
| `decisive_sentinel_exception()` (`_call_tools.py:180`) | termination, other error, first leaf | termination, other error, outermost limit |
| Bridge `_first_control()`, a group of only limits and refusals | its first leaf | `first_or_outermost_limit(group)`: a leading refusal still wins |
| Bridge `_first_control()`, any other group | its first limit (other errors are logged) | `outermost_limit(group)` (other errors are logged) |
| Bridge kept limit | first, replaced by a same-tree ancestor or sample root | replaced by any later limit that is outer (`_outer_than`) |

Each site keeps its existing ranking of limits against non-limit errors. Only
"which limit" changes. Ranking limits *above* other errors (or below them)
everywhere is a separate question and is left out (see "Not this design").
A limit that a non-limit error displaces at one of these sites is not lost
for good: it stays reached, so the next dispatch is refused (rule 3), and its
owner's exit check raises it if that owner ends normally (rule 7).

Generic reductions are left alone. `tg_collect()` and
`unwrap_exception_group("first")` (`src/inspect_ai/_util/_async.py:44-124`)
still raise a group's first member, and `collect()` still unwraps only a
one-member group. When `tg_collect()` drops an outer limit in favour of an
inner one, the outer limit is still reached: the next call under it is
refused, and if its owner ends normally, its exit check finds it (see "Not
this design").

`apply_limits()` handles an exception escaping its body in two steps:

1. **Covered or not.** The exception is a *covered exit* when every leaf is
   a `LimitExceededError` covered by the scope: its `source` is one of the
   scope's limits (of any kind, in the chain or not: a `time_limit()` or
   `working_limit()` passed to `run()` or `apply_limits()` is the scope's
   own, as today), or a chain node entered below one of the scope's chain
   limits (walking `source._outer` reaches one of them). Anything else
   propagates unchanged: an unrelated error, a termination, a
   cancellation, a limit of an enclosing or sibling scope, or a limit error
   whose source is unknown. A sourceless `custom` error (documented in
   `docs/setting-limits.qmd:278-288`, and raised by inspect_swarm members)
   is never covered, so a group holding a covered token error and a
   sourceless custom error propagates, as it does today.
2. **Ownership of the outermost.** For a covered exit, the deciding limit
   is its outermost (`outermost_limit()`; a bare error is its own; a time
   or working limit, outside the chain, ranks after every chain limit, rule
   4). If it is one of the scope's own limits, `limit_scope.limit_error` is
   set to it and, with `catch_errors=True`, the exception is swallowed
   (raised as that limit otherwise). If it is a descendant's limit, the
   exception propagates unchanged, as it does today.

Every swallowed leaf is the scope's own or a descendant's, whose scope this
one ends anyway. A bare error from one of the scope's own limits, a time
limit included, is caught as today (`src/inspect_ai/util/_limit.py:158-160`,
`:174-187`), also when it is raised as the limits exit (a time limit raises
from its cancel scope's exit, inside the `ExitStack`), so
`run(limits=[time_limit(...)])` and the deepagent callers of
`apply_limits()` keep returning their own time limit error. A bare error
from a descendant still propagates. The error that escaped is not compared
with node state: a limit error that reaches its owner stands ("The owner's
exit check").

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

Rule 5 replaces the separate paths for suspended calls with one rule: a
suspended kind is neither charged nor checked, and the bridge guard is
skipped while token limits are suspended, as today.
Approval, review and in-process sentinel calls, and the wait for a sentinel
sidecar's result, run under `suspend_limits()`, so they record into and
check no token, turn or cost limit. That includes the pre-dispatch check, so
a reached sample cost limit does not refuse an approver's call, and a
`cost_limit()` opened inside the suspended block is not enforced either
(suspension wins over nested limits, as for tokens today). The
unpriced-model refusal skips them too (rule 9): an unpriced approver,
reviewer or monitor model is not refused. For that exemption to hold, the
start-time price check no longer requires prices for role models, which it
cannot tell apart by use ("Unpriced models"). Their spend is still recorded
in model and role usage and in the sample's reported cost.

A consumer's own check on a node of a suspended kind is skipped with it,
since `check_limits()` skips the node. inspect_swarm's lever closes a stop
gate on a cost node when it stops a member; a callback already running at
the stop can then make further calls, uncounted, until it returns or is
cancelled ("What inspect_swarm can delete or simplify").

Calls made while token limits are suspended also skip `dispatch_guard()`,
as they do today (`_model.py:3689-3701`); approval, review and sentinel
calls suspend tokens through `suspend_limits()`, so they skip it. Turn or
cost suspension alone does not skip the guard, as today: the suspension
contexts are independent, and only the token one gates the guard. Message
limits, which suspension never covered, are still checked as today
(decision: Ransom, 2026-11-17). The
bridge's guard is the only guard. The cost: once the bridge has kept a
limit, an approval, review or monitor call made for a request already in
flight still runs, and its spend counts against no limit. Every later
request is refused at entry, before any tool or policy code runs: a
generation request before its generation, and a host-tool request before
the tool executes ("The sandbox bridge"), so before any approval or
monitor call. The agent still ends on the kept limit.

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
- **Handoffs.** `agent_handoff()` captures `call_leaf = _limit_chain.get()`
  before it enters the handoff's limits, and its `except LimitExceededError`
  (`_call_tools.py:1272-1281`) applies the same test as `execute_tools()`:
  a token, cost or turn limit whose source is in the chain but not below
  `call_leaf` is foreign and is re-raised. Every other limit error keeps
  today's handoff result, the handed-off agent's new messages followed by
  the "exceeded its <type> limit" message (`:1309-1316`): the handoff's own
  limits, a descendant's limit (a `with token_limit()` or `run()` limit
  entered inside the handed-off agent), message limits (see below), and
  errors outside the chain (a time limit entered inside the agent, a
  sourceless `custom` limit). As today, only a bare error is caught; a group
  propagates.
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

The in-process sentinel wrapper is unchanged: it still wraps any exception
escaping a monitor or protocol in `SentinelFailure`
(`src/inspect_ai/_sentinel/_dispatch.py:315-316`). Under rule 5 a monitor's
own model calls run with token, turn and cost limits suspended and skip the
bridge guard, so they cannot reach one of those limits or be refused by a
kept one. The one limit a monitor can reach is a message limit: suspension
leaves message limits active, and `generate()` checks the innermost message
limit before dispatch (`src/inspect_ai/model/_model.py:1041-1044`,
`src/inspect_ai/util/_limit.py:744-758`), so a monitor whose own prompt
reaches an inherited message cap raises a message limit. It keeps today's
handling: the wrapper turns it into a `SentinelFailure`, which a native tool
or the runner unwraps as today (`_sentinel_exception()`,
`_call_tools.py:170-177`; `run.py:2913-2916`). In a bridge the outcome
depends on the request:

- In a bridged generation, it becomes an ordinary error reply, with no kept
  limit.
- In a bridged host tool, `tool_call_error()` does not map it, so
  `_raised()` treats it as an unexpected error, which requests sample failure
  (`src/inspect_ai/agent/_bridge/sandbox/host_tool.py:438-453`, `:400-401`).
  When the agent unwinds, `_error_after_unwind()` selects a requested
  failure ahead of the kept limit (`sandbox/bridge.py:377-396`). So a
  monitor in an in-flight host tool that reaches a message limit ends the
  sample in an error, even when the bridge has already kept a token, cost
  or turn limit. That is the exception guarantee 4 makes for an exit
  decided by a non-limit error ("What a runtime can rely on"), and the
  priority is unchanged.

Message limits are outside the chain's exit checks, so nothing records the
message limit later. This design does not change it.

### The owner's exit check

A limit error that reaches its owner stands: `apply_limits()` and the sample
runner record the error they receive (after the reductions in "Precedence")
and do not compare it with node state. Rule 7 covers the other case, where
no limit error reaches the owner because a handler swallowed it. It has two
call sites:

- `apply_limits()`, on a normal return: after the body returns, before it
  exits its limits, it calls `check_own_limits(limits)` over the limits it
  was given. Only its own limits can raise there, so one that does is
  caught when `catch_errors=True` (`run()`) and propagates otherwise
  (`as_solver()`, `as_tool()`, handoffs), as one raised in the body.
  Enclosing limits are not checked there. A sample limit that a handler
  inside a `run()` agent swallowed does not leave `run()` at its exit: it
  is refused at the caller's next call, or found by the sample's exit
  check, one step later, as for any swallowed error.
- The sample runner, when its solvers return normally (below).

**The sample's exit check.** Today the solvers run in `run()`, a task of the
sample's task group, whose `finally` cancels the group (`run.py:3361-3364`)
when `plan()` returns or raises (`run.py:3269`); the group is joined at
`run.py:3391-3392`, inside the `with` block that holds the sample's limits
(`run.py:3186-3198`). A `background()` worker can finish a priced call in
its cancellation cleanup, reach a sample limit there, catch the error and
return, after `plan()` has returned. So the check runs after the join:
`run()` sets a local `solved = True` right after `plan()` returns, and after
the `async with anyio.create_task_group()` block and the existing
`solver_cancel` check, when `solved` is set, the runner calls
`check_own_limits()` over the sample's token, cost and turn roots
(`sample_limits()`). It raises
the outermost root that counts at exit, with its `SampleLimitEvent`, and
the existing `except LimitExceededError` (`run.py:3422`) records it.

Everything else is unchanged. A limit error that escapes the solvers is
recorded as it is today. A non-limit error (after
`first_or_outermost_limit()` reduces a group, the deciding leaf is not a
limit) goes to the error handling as today, so an error still outranks a
limit at the runner. A termination keeps its own `except` clause. An
operator interrupt and a limit delivered by cancellation (the working limit,
or a limit a sandbox service routes to the sample) keep their handling
inside `run()`, which sets the outcome before the join and leaves `solved`
unset.

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
stands, the recorded limit can differ from the outermost limit that counts
when something replaces the error on its way out. Two cases do this:

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

**What raises at exit.** Each of the owner's own nodes raises if it is
exceeded (`> limit`), or if
it is reached (`== limit`) and was refused at that same budget
(`_refused_at_budget()`): `check_own_limits()` passes
`raise_for_equal=node._refused_at_budget()` for each node. So:

- A sample that used exactly its token budget, or took exactly its N turns,
  and returned without trying another call, is not recorded as limited.
- A sample in which a call was refused at exactly the limit is. This is the
  case where the refusal's error was lost on its way to the owner: a bridged
  request refused at the sample's budget and kept, then a hard stop that
  cancels the bridge before the kept limit is delivered; or a runtime that
  dropped the error.
- A limit that raised and whose effective budget then changed counts only
  by the budget in force at exit. The budget can change through a `limit`
  setter (a solver that catches the sample token limit and sets
  `state.token_limit` higher) or through a live override of the sample's
  token or message limit (`inspect ctl`, `set_sample_limit_override()`,
  `src/inspect_ai/util/_limit_overrides.py:71-100`), which the root node's
  `limit` getter reads on every access (`src/inspect_ai/util/_limit.py:1083-1086`)
  without calling the setter. Because the mark stores the budget it was
  refused at, both paths are handled the same way: a node refused at 10 whose
  budget becomes 20 (by the setter, by setting an override, or by clearing an
  override back to a launch budget of 20) and that ends at exactly 20 without
  a refusal at 20 does not raise; one refused at 20 does. A budget changed
  back to 10 after a refusal at 10 counts that refusal again, also when a
  check at a lower budget (5) raised in between.

The `_raised_at` mark is per node and survives the cancellation that loses
the error itself; a change of the node's effective budget makes it not
count, without clearing it. A checkpoint does not store it ("Checkpoints").

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

**Limits swallowed during a resume for scoring.** The same principle holds
for a scoring resume, which has no sample exit check. A limit reached and
swallowed during that attempt is not recorded: by a sample-start or
attempt-start hook, which the runner calls before the agent runs and so
before the checkpoint is restored (`run.py:3372-3392`; the hook may catch
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
hooks (`run.py:3372-3392`) and any solver that runs before the agent. The
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
setup (`run.py:3097`). Spend is bounded by the caller's retries (decision:
Ransom, 2026-11-18). The restore also
clears the root's `_raised_at` mark ("Checkpoints"), so a refusal before
the restore is part of the same loss. Model work before the restore is not
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

The checkpoint payload is unchanged, and does not store the `_raised_at`
mark (decision: Ransom, 2026-11-16). A checkpoint stores the sample roots'
usage, and a normal resume restores it into the roots and checks them:
`dump_sample_runtime()` writes the token usage, cost and turns
(`src/inspect_ai/util/_checkpoint/sample_runtime.py:47-96`), the
checkpointer stores that payload
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:624-633`), and
`restore_sample_runtime(check=True)` reseeds the roots and runs the token,
cost and turn checks, in that order, with `>` (`sample_runtime.py:153-163`,
`:221-225`; called for a normal resume at `checkpointer_impl.py:147-152`).
An exceeded root therefore still ends the resumed attempt before it makes a
call. A resume for scoring (`check=False`) runs no check, as today, and
the runner skips the sample's exit check on that attempt ("The owner's exit
check").

The restore assigns the stored token usage, cost and turns to the roots
and clears and refills the sample's model and role usage, as today
(`sample_runtime.py:153-163`, `:259-266`). It is idempotent: a
checkpointer entry that fails part-way and is entered again sets the same
values. Work the attempt charged before the restore is overwritten; what
that loses is under "Limits swallowed before a checkpoint restore".

The restore also sets `_raised_at = None` on each root whose counter it
assigns, before its checks run. The mark keeps the greatest budget at which
the node raised, which is right only while usage never decreases ("Recording
and checking"); an assigned counter can be lower than the usage
the mark was set against. Without the reset, a root refused at 20 before
the restore, lowered to 10 (before the restore or in `on_resume` after
it) and restored to 0 would keep a mark of 20: a fresh refusal after it
consumed 10 would not count at the exit check, since `_refused_at_budget()`
compares the mark with the budget of 10. After the reset, the mark again
records only refusals at or after the restored usage, and the
greatest-budget rule holds from there. A root the payload does not assign
(its key is missing) keeps its counter and its mark.

The roots of a resumed attempt carry no `_raised_at` mark from the
previous attempt, so the exit check's handling of a limit reached exactly
holds within one attempt. A limit that refused a call
at exactly its budget is restored at that usage, so any further call is
refused by the pre-dispatch check (`>=`), which raises it and sets `_raised_at`
again, with nothing spent. If the resumed sample makes no further call and
returns, it is not recorded as limited, as for a sample that used exactly
its budget.

Only the sample's roots are stored: scoped limits (`run()`, a swarm's
nodes) are re-entered fresh by the resumed agents, as their usage is today.

### The sandbox bridge

`_forward_provider_errors()` becomes:

```python
async def generate_forwarding_errors(json_data, headers=None):
    try:
        with _refuse_after_a_recorded_limit(bridge):
            _check_limits_before_dispatch()  # outermost reached limit, then the guard
            if bridge.generation_limit is not None:  # whatever is suspended
                return {PROVIDER_ERROR_KEY: provider_error_payload(bridge.generation_limit)}
            return await generate(json_data, headers)
    except Exception as ex:
        ...  # terminations and sample failures: unchanged
        control = _first_control(ex)  # refusal if first, else outermost_limit(ex)
        if isinstance(control, LimitExceededError):
            bridge.keep_limit(control)
            _warn_other_errors(ex)
            return {PROVIDER_ERROR_KEY: provider_error_payload(ex)}
        ...  # refusals, response filter errors, UnmeteredCallError: fail the sample
        ...  # other errors: unchanged
```

- `SandboxAgentBridge.keep_limit(error)` sets `generation_limit = error` when
  nothing is kept or `_outer_than(error, generation_limit)`. Host tools call
  it for a foreign limit. The field keeps its name, and its docstring now says
  it holds the outermost limit reached by the bridge's generations or host
  tools.
- The entry check now covers turns with `>=` (rule 3), so the separate
  `check_turn_limit()` call goes away. The "a limit is already kept" branch
  stays, after the pre-dispatch check: that check runs first, so an outer
  reached limit raises and replaces the kept one, and then any request
  that arrives while a limit is kept gets the kept limit's error reply
  without a generation. The branch does not rely on the guard, which is
  skipped while token limits are suspended (rule 5): a service task
  inherits the context `sandbox_agent_bridge()` starts it in
  (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:295-303`), so if that
  context suspends tokens, the guard is skipped for every request, and a
  kept message limit (which `check_limits()` does not cover) would
  otherwise let a fresh request with a shorter prompt reach the provider.
  Inside a request already admitted, the guard is still skipped for
  suspended calls, as decided.
- Host-tool requests get the same unconditional entry refusal. Today `call_tool()`
  (`service.py:452-463`) only wraps `execute_host_tool()` in the guard, so
  a host tool admitted after the bridge kept a limit still runs; an
  `as_tool()` child or a tool calling `run()` enters an agent span, and its
  sentinel runs before the child's own pre-dispatch check
  (`_model.py:1088-1098`), with token limits suspended, so the monitor's
  priced call is made and counted by no limit. A scaffold can repeat this
  until it exits. `call_tool()`'s `execute` therefore checks
  `bridge.generation_limit` first: when a limit is kept, it raises
  `ToolError` with the message `_raised()` maps that limit to (the `limit`
  tool error text), without calling `execute_host_tool()`, so no tool,
  approval or monitor code runs and the scaffold gets the ordinary
  tool-error reply. The kept limit is unchanged. Host-tool requests admitted
  before the limit was kept keep the decided bypass for their suspended
  calls (rule 5).
- `_encloses()`, `_sample_roots()` and `_in_tree()` are deleted. The
  `solving()` dependency goes with them. Comparing positions in one chain
  works the same during the solve and in scorers.
- `sandbox_agent_bridge()` still raises the kept limit only once the agent
  has unwound or returned, after a pending enclosing cancellation
  (`bridge.py:340-395`, unchanged). If the agent is cancelled first, the kept
  limit is not raised there. Its node raised when it was reached, so it
  carries the `_raised_at` mark. It refuses every later call under it (rule
  3), and when no other limit error reaches its owner, rule 7 raises it
  when that owner ends normally: the `apply_limits()` scope that entered
  it, or the sample's exit check when the solvers return, whether the limit is exceeded or was
  reached exactly by a refused request: for example a swarm that
  hard-stopped the member and then returned.
- A refused unpriced model (`UnmeteredCallError`, see "Unpriced models")
  in a bridged generation fails the sample through `bridge.request_fail()`,
  as a `ModelRefusalError` or `ResponseFilterError` does, so the sample
  fails with the error's message. If a cancellation displaces that failure
  before it is delivered, nothing records it; a retried request is refused
  again before dispatch, with nothing spent.

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
lifetime and its errors keep reaching the sample runner. The guarantees below are about work in tasks the runtime owns.

1. **A sample limit reaches the runtime.** A sample token, cost or turn
   limit reached by any of its agents' model calls, native or bridged, in a
   tool, a handoff, a subagent or a filter, reaches the runtime's
   code as a `LimitExceededError` whose `source` is the sample's node
   (`sample_limits().token`, `.cost`, `.turn`). It arrives bare, or in a
   group where `outermost_limit()` returns it. No Inspect code between the
   model call and the runtime converts it (rule 6), and no inner limit reached by the same call or a
   concurrent one replaces it (rules 3, 4, 8). For a bridged agent it
   arrives when the agent's CLI exits. If a handler on the way swallows it
   (and no checkpoint restore reopens it in between, below)
   (a fallback, a hook, `tg_collect()` keeping another error), it arrives
   instead at the next call any agent makes under the sample, which is
   refused with it (guarantee 2).
2. **A reached limit stays reached.** Within the attempt (but see the
   restore exception below), every later dispatch under that
   sample, including the runtime's own model calls, native compaction and
   bridged requests, is refused with that node's error, or with the error
   of an outer node that has since been reached too (rule 3: the next
   check raises the outermost). Approval,
   review and sentinel calls are the exception: they run with token, turn
   and cost limits suspended and skip the bridge guard, so a reached limit
   of those kinds, or a bridge's kept limit, does not refuse them.
   Calls already dispatched complete, are recorded, and raise after
   recording the error of the outermost reached node, which is that node
   or an outer one their usage has since pushed over (rules 3 and 8; the
   bridge's kept limit is promoted the same way).
3. **The runtime may hold the error.** It can catch it, stop its agents
   (close levers, wait for in-flight calls within its grace, cancel the
   rest), write its ledger and re-raise the error, bare or in a group. The
   runner records it as the sample's limit (`EvalSampleLimit` of that type).
   During the stop, no model call can succeed under the reached limit, so
   the runtime's final step must make none.
4. **Losing it is not silent.** When the solvers return normally (on
   any attempt but a resume for scoring, and with the restore exception
   below), the sample's exit check records
   the outermost sample limit that counts at exit (rule 7): one that is exceeded, or reached exactly after refusing a
   call. That covers a runtime, or a bridged agent
   cancelled before its CLI exited, that drops the error. It runs after
   background cleanup, so usage recorded there counts. A limit error that
   reaches the runner is recorded as it is: it can differ from the
   outermost sample limit that counts when a limit is pushed over in
   cleanup after another escaped, or when an adapter's state copy raises a
   different limit (see "What the owner can miss"). An exit decided by a non-limit error, a
   termination or an operator interrupt keeps that outcome.
5. **No unpriced model runs under an active cost limit.** While cost is
   not suspended and a cost node on the chain has a limit (not `None`), no
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

Guarantees 1, 2 and 4 rest on node state, which lives for one attempt
and which a checkpoint restore overwrites. A checkpoint resume restores
usage but not the `_raised_at` mark (it clears a mark set earlier in the
attempt), so a refusal at exactly the budget from before the checkpoint is
not carried into the resumed attempt ("Checkpoints"). And because the
restore assigns the stored usage, a limit that work before the restore
(startup hooks, solvers before the agent) reached and swallowed can be
reopened by it ("Limits swallowed before a checkpoint restore").

The sample's time limit (a cancel scope around the solvers) and working limit
(a sample-wide cancellation) are outside these guarantees. They end the sample
by cancellation, which the runtime cannot hold.

Message limits are per conversation: a sample message limit reached in a
member's own conversation (one with no message limit of its own) is raised
there like any other foreign error, and reaches the runtime the same way.

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
(`_model.py:2066`) returns `False` for it before any other test, so a
provider's classifier never sees it. A sample configured with
`retry_on_error` is still retried, as for any sample error: only
`SampleRefusedError` is exempt from sample retries
(`src/inspect_ai/_eval/task/run.py:2917-2920`, `:2937-2942`), and no
exception is added for this one. Each sample retry repeats the sample's
priced work before it fails on the same call. A
sentinel sidecar does not recover it as a refusal: each generate attempt
first forgets the sidecar's record of the previous attempt
(`begin_attempt()`, `_model.py:1685`;
`src/inspect_ai/_sentinel/_sidecar/_received.py:98-105`), and
`refused_output()` and `refusal_after_error()` ask nothing of an attempt
whose request was not sent (`src/inspect_ai/_sentinel/_sidecar/_act.py:76`,
`:97`). It is not a `LimitExceededError`, so no limit owner catches it.
When it reaches the sample runner the sample fails with it, as a sample
error. Native tools do not map it (`tool_call_error()` returns `None` for
it), and a bridged host tool treats it as an unexpected error, which fails
the sample (`host_tool.py:450-452`); a bridged generation fails the sample
with it through `bridge.request_fail()` (see "The sandbox bridge").

Nothing is marked, so the cost limit is not reached by the error. Code that
catches it and calls the same model again (a compaction fallback, a hook
that logs and continues, a first-error reduction) is refused again before
dispatch, with nothing spent.

**When.** In `_check_limits_before_dispatch(model)`, after the limit check
and before the guards: if cost is not suspended, any cost node on the chain
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
  Without a cost limit, or with cost suspended, nothing changes.
- **At start.** `resolve_model_costs()` keeps requiring cost data for the
  task's own model, which the sample's agent calls by default, so the
  common misconfiguration still fails before any sample runs. It no longer
  requires cost data for model-role models, at eval start or for an
  enqueued task (`src/inspect_ai/_eval/eval.py:879`, `:1352`): a role can be
  used only by suspended calls (the sentinel host's `monitor` role, an
  approver's role), and the start-time check cannot tell how a role will be
  used. An unpriced role model called with cost suspended runs; the same
  model called by an agent, unsuspended, under the cost limit is refused at
  that call by the per-dispatch check above. A role cannot be exempted by
  name either, since any code can resolve any role.

After a call, the one check runs whatever the call's cost (rule 2). An
unpriced call that is admitted (cost suspended, or no cost node with a
limit) records no cost. Token and turn limits were already checked after
such calls; what is new is that unsuspended cost nodes are checked after
them too, so a node whose own check raises without a limit, such as
inspect_swarm's closed lever gate, raises after the call where today it
raises at the next dispatch.

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
  cost data cannot run under a swarm cost node that has a limit, while cost
  is not suspended (rule 9).
- **Bridged members of a nested swarm.** A cost-tree error no longer hides a
  later token-tree error from the outer swarm: the bridge keeps the outermost
  of the two whatever their kinds (rule 8).
- **Bridged losses.** A filter's parallel calls that raise a swarm limit and
  the sample limit in one group raise the sample limit (rule 4 and the
  filter's reduction). A bridged host tool's model call that reaches the
  sample limit after the bridge kept a member limit makes the sample limit
  the kept one (rule 6, host tools). A kept sample limit lost to a
  cancellation before the CLI exits is recorded by the sample's exit check
  when the solvers return, whether it was exceeded or reached exactly by a
  refused request (rule 7).
- **Promotions.** A retry or in-flight request that replaces a kept member
  limit with an enclosing swarm limit is rule 8 itself, so it needs no
  separate case.
- **Limit errors inside tools.** A swarm cap or lever reached in a member's
  foreground, inside a tool or a synchronous deepagent subagent, now reaches
  the member wrapper at once instead of at the member's next model call. The
  cap node's `stop_swarm` call in `_check_self` stays, and is still needed
  for correctness: errors from a member's background work are contained by
  the member's background owner (`MemberBackground._run()`,
  `inspect_swarm/src/inspect_swarm/_background.py:138`), and the member
  runner classifies only an exception that escapes the member
  (`_member.py:637`, `:662`). A background call that crosses a cap is
  therefore never classified by the wrapper, and only the callback starts
  the swarm's stop. Removing the callback would need the swarm to reconcile
  its caps when a member returns or drains, which is the swarm's own
  change, not a consequence of this design.
- **The reserve.** Guarantees 1 to 3 let the runtime catch a sample limit and
  stop its members in an orderly way, so the 5% reserve no longer has to
  keep the stop orderly. It would still leave room for a final step that
  makes model calls, which is the swarm's own decision.
- **Sentinel.** inspect_sentinel's runner keeps the first limit of a group
  (`_runner.py:414-416`). It could use `outermost_limit()` (private, so on
  the same terms as the swarm's other internals).

What the swarm must change:

- **The turn override.** Its `SwarmTurnNode._check_self()`
  (`inspect_swarm/src/inspect_swarm/_budget.py:606`) takes the new
  `raise_for_equal` argument, before or with the Inspect change that passes
  it (implementation plan, step 1). Its other overrides (`record()`, the
  token and cost `_check_self()`, the message `check()`) are called as
  today, through `_check_marked()`.
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
  marks the swarm failed (`_controller/_control.py:649`, `:1214-1215`).
- **Policy spend.** Approver, reviewer and monitor spend no longer counts
  toward its cost caps or shares (rule 5), so a swarm ledger that compares
  spend to caps must take that spend from model or role usage.
- **The lever's stop gate and running callbacks.** When the swarm stops a
  member, its lever closes a stop gate on its cost node, whose
  `_check_self()` then raises on every check
  (`inspect_swarm/src/inspect_swarm/_budget.py:530-536`). Today Inspect
  checks cost before every dispatch even while token metering is
  suspended, so an approval or review callback running when the stop
  arrives can finish its dispatched call but cannot start another, which
  inspect_swarm's `design/swarm-limits.md` promises. Under rule 5 those
  callbacks run with cost suspended, and `check_limits()` skips suspended
  cost nodes, the gate included. A callback already running when a member
  stops may therefore make further model calls until it returns or is
  cancelled, and those calls count against no limit (decision: Ransom,
  2026-11-17). Every unsuspended call still meets the gate. The swarm's
  design drops its promise that a callback cannot start another call after
  the stop.

Its per-member `background_target` is what the guarantees' prerequisite
asks for, so it keeps it.

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

**`apply_limits()` checks the whole chain at exit.** A scope's exit check
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
checkpointer's construction) and is entered again, as the transcript-store
recovery does, would add the snapshot twice, so it would need a once-only
accounting lifecycle separate from the entry cache. Refusing model work
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

**A non-strict exit check (`>=` for every node).** It would catch a refusal
at exactly the budget without a mark, but would also record as limited every
sample that used exactly its budget, or took exactly its N turns, and
returned. The `_raised_at` mark separates the two.

**Carry every limit error intact to its owner.** Make each
handler that can catch one (fallbacks around compaction, hooks, first-error
reductions such as `tg_collect()`, the sentinel wrapper, a bridge delivery
that a cancellation can displace) re-raise or forward it. Each review of
that approach found another such handler, and the list is open-ended: any
user or extension code can catch an exception. The rules here make the
nodes the record instead, so within one attempt a handler that swallows a
limit error delays it by at most one call and cannot lose it, except
across a checkpoint restore, which drops the `_raised_at` mark and can
reopen a limit swallowed before it ("Checkpoints", "Limits swallowed
before a checkpoint restore").
Inspect still changes its own handlers where that decides *which owner*
hears first (rules 4, 6 and 8), not merely whether the error survives.

**Reconcile an escaped limit with node state at its owner.** When a limit
error reaches `apply_limits()` or the sample runner, compare it with the
outermost limit that counts at that point and report that one instead. It
would close the cases under "What the owner can miss", where only the
recorded limit differs, but each review of it found another exit
path to cover (owned errors, descendants' errors, time limits outside the
chain). An error that reaches its owner stands (decision: Ransom,
2026-11-16).

**Store `_raised_at` in checkpoints.** An optional payload key would carry the
mark across a resume, so a resumed sample that returns without another call
is still recorded as limited after a refusal at exactly its budget. The key
was cut (decision: Ransom, 2026-11-16).

**Raise a monitor's limit bare from the sentinel wrapper.** With token,
turn and cost suspended for monitors and the bridge guard skipped, a
monitor can reach only a message limit, which keeps today's
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

**Keep the swarm's stop gate for suspended calls.** A swarm-owned gate
checked outside the suspended kinds would keep inspect_swarm's promise that
a callback running at a member's stop starts no further call. It would add
a check that suspension does not cover, a separate path of the kind rule 5
removes. Callbacks running at the stop may continue until they return or
are cancelled (decision: Ransom, 2026-11-17).

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

**Charge approval, review and sentinel calls to cost limits.** Keeps one
budget for everything the sample spends, but a policy's spend then ends
the agent's sample, and an unpriced policy model would be refused. They are
suspended like tokens and turns (decision: Ransom, 2026-11-16).

**Warn about unpriced calls instead of refusing them.** Keeps evals with an
unpriced approver, monitor or subagent model running, but a cost limit then
does not bound their spend: their calls never advance it, so its checks
never fail. Refusal was chosen (decision: Ransom, 2026-11-12).

**Refuse suspended calls with the bridge guard too.** Approval, review and
monitor calls inside a bridged request would stop once the bridge kept a
limit, saving their spend. But a monitor refused that way raises the kept
limit inside the sentinel wrapper, which turns it into a `SentinelFailure`;
from a bridged host tool that failure then displaces the kept limit and
fails the sample. Suspended calls keep skipping the guard, as today, at the
cost of the policy calls for requests already in flight (decision: Ransom,
2026-11-17).

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
  recorded limit. Limits the tool or handoff entered itself or entered below
  it, limits outside the chain (time limits, sourceless `custom` limits),
  and all message limits, behave as before; a handoff still returns the
  handed-off agent's new messages and its limit message for them.
- **Approval, review and sentinel spend leaves cost limits.** With cost
  suspended for them (the prerequisite cost suspension), model calls made by
  tool approvers, tool result reviewers and in-process sentinels, and the
  wait for a sentinel sidecar's result, no longer count toward the sample's
  cost limit, a `run()` or `apply_limits()` cost limit, or inspect_swarm's
  cost caps and shares, and a reached cost limit no longer refuses them.
  Their spend is still in model and role usage and the sample's reported
  cost, which can therefore exceed the configured cost limit. An unpriced
  approver, reviewer or monitor model under a cost limit is not refused,
  As today, they still skip the bridge's guard, so they run for requests
  already in flight after the bridge keeps a limit.
- **inspect_swarm's stop gate no longer stops running callbacks.** An
  approval or review callback already running when the swarm stops its
  member can make further model calls until it returns or is cancelled,
  where today the lever's stop gate refuses them; those calls count against
  no limit. inspect_swarm's design drops its promise that a callback cannot
  start another call after the stop ("What inspect_swarm can delete or
  simplify").
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
  task model already fails at start today.
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
- **`apply_limits()`** catches its own limit raised in an exception group
  (when every limit in it is its own or a descendant's; any other leaf,
  including a sourceless `custom` limit, propagates the group as today),
  and at normal exit raises one of its own limits that is exceeded, or
  reached after it refused a call; it does not check enclosing limits. `run()` therefore returns `(state, error)` in these cases
  where today it raises or returns `(state, None)`. A limit error that
  escapes its body is handled as it is (by ownership of its outermost
  limit), not compared with node state.
- **The sample runner**, when the solvers return normally, checks the
  sample's limits after the solvers and the sample's background work have
  finished, and records an exceeded or refusing sample limit found then.
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
- **Usage hooks and the cache see limit-crossing outputs.** A generation
  whose usage crosses a limit is now reported to usage hooks and legacy
  telemetry and stored in the cache before the limit raises, where today
  the check raised first ("Recording and checking"). A hook that raises
  there decides the call's error, and the reached limit refuses the next
  call. A native cache hit is still served when an enclosing token or cost
  limit is already exceeded, as today; it records and checks its turn
  only ("Cache hits").
- **Sidecar-recovered generations count as turns.** A generation that a
  sentinel sidecar recovers as a refusal after a provider error now records
  a turn, as every other top-level generation does.
- **A refusal counts only at the budget it was refused at.** After a node
  is retuned (`state.token_limit`, `state.cost_limit`, a node's `limit`, or
  a live `inspect ctl` override of the sample's token limit, set or
  cleared), the exit check judges it by the budget then in force; an
  earlier refusal at a lower budget does not make it count at equality.
- **Plain `with` blocks keep no exit check.** As today, a limit reached in
  a plain `with token_limit()` block whose error a handler inside the block
  swallowed is lost if no further call under the block follows; deliberate
  catches inside the block behave as today.
- **Bridge.** A bridged agent's kept limit is now the outermost of every
  limit its requests and host tools reached, whatever their kinds.
- **Token limit formulas.** A token limit `type` formula must now be a
  non-negative weighted sum of `input` and `output` ("Token metering must
  not decrease"); `token_limit(10, type="input - output")` and formulas
  that multiply or divide the two counts raise `ValueError` when the limit
  is built, including when an eval with such a formula is retried from its
  log. No such formula was found in use. `all`, `output`, `input` and
  weighted sums such as `(input * 0.1) + output` are unchanged.
- **Private internals.** `_encloses()`, `_sample_roots()` and `_in_tree()`
  are removed. `_TurnLimit._check_self()` gains a parameter. Chain nodes gain
  `_outer`, `_in_chain` and `_raised_at`; `restore_sample_runtime()` clears
  `_raised_at` on the roots it assigns. `record_turn()` no longer checks. inspect_swarm is the only known user of
  these classes (above).
- **Persisted data and the viewer.** The checkpoint sample-runtime payload
  is unchanged and does not store the `_raised_at` mark, so a resumed sample
  that returns without another call after a refusal at exactly its budget
  is not recorded as limited ("Checkpoints"). `EvalSampleLimit`, `SampleLimitEvent` and `EvalConfig` limit fields keep
  their shapes, and old logs read the same. No generated TypeScript type
  changes.
- **Docs.** `docs/setting-limits.qmd` and `docs/_agent_limits.md` state the
  precedence rule, that tool-based agents return a message for their own
  limits (an enclosing limit ends the caller), the new turn semantics, the
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
- **A sandboxed agent cannot change the outcome.** The chain, depths, the
  kept limit and the ownership test live in the host process and depend only
  on which `with` blocks the host entered. A CLI that floods requests after a
  limit gets the kept limit's error reply with no model call (rules 3 and 8),
  as today.
- **Error text** forwarded to the CLI is the existing `provider_error_payload`
  of the limit error (its type, value and limit), unchanged.
- **Spend.** The agents' changes either refuse a call sooner (a reached
  turn limit, an unpriced model) or make a limit error propagate further;
  native cache hits remain unrefused, as today. A bridged request is
  checked at entry, before the cache, so the bridge refuses it under a
  reached limit or its kept limit, cached or not, as today.
  The one change that lets calls through that are refused today is the cost
  suspension for approval, review and sentinel calls, whose spend a cost
  limit no longer bounds; it is set by host code (the policies Inspect
  runs), not by a sandboxed agent or model output. With rule 9, no
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
    priced from its serving model, as today;
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
    unpriced task model still fails at start;
  - suspension: inside `suspend_cost_limit()`, a priced call neither
    charges nor is refused by a reached `cost_limit()`, including one
    opened inside the block.
- `tests/util/test_limit_turn.py`, sidecar recovery: with `max_retries=0`
  and a sentinel sidecar whose judgment recovers each provider error as a
  refusal turn, under `turn_limit(1)` the first generation returns the
  recovered output and records one turn, and the second is refused before
  dispatch; a recovered turn whose billed usage crosses a child
  `token_limit()` (and, separately, a child `cost_limit()`) records the
  usage and the turn before the child limit raises; when the sidecar
  recovers nothing, the error stands and no turn is recorded (as today).
- `tests/util/test_limit_turn.py`: `turn_limit(3)` makes three generations
  and refuses the fourth before dispatch; a cache hit at the limit is served
  and then raises (it records its turn); native compaction is refused at the limit and records no
  turn; under `turn_limit(1)`, a call that raises a child `token_limit(1)`
  (caught) counts one turn and the next call is refused by the turn limit;
  the same with a child `cost_limit()`.
- `tests/util/test_limit_token.py`, cache hits (next to
  `test_generate_cache_hit_served_when_token_limit_reached`, which pins
  equality): under `token_limit(1)`, an uncached call reporting 2 tokens
  raises and is cached; the same input is then served from the cache with
  no provider call and no error, and an uncached call is refused before
  dispatch; the same under `cost_limit()` with a priced model; under an
  exceeded `token_limit()` inside `turn_limit(1)`, a cached generation
  records its turn and raises the turn limit.
- `tests/util/test_limit_token.py`: inside `suspend_limits()`, a call is not
  refused by a reached token, turn or cost limit, nor by a
  `dispatch_guard()`, and a reached message limit still refuses it; inside
  `suspend_token_limit()` alone the guard is skipped; inside
  `suspend_turn_limit()` alone and inside `suspend_cost_limit()` alone a
  `dispatch_guard()` still refuses the call (pinned, as today); inside
  `suspend_limits()`, a `_CostLimit` subclass whose `_check_self()` always
  raises (as inspect_swarm's closed stop gate does) is not checked, and the
  same node refuses an unsuspended call;
  `token_limit()` and `TokenLimit` (including the `"input-output:10"`
  string form) refuse `input - output`, `input / output`
  and `input * output` with the family message, and accept `all`, `output`,
  `input`, `(input * 0.1) + output`, `input / 10 + output` and
  `2 * input - input`; a polynomial in `input` such as
  `input + input * (input - 1)` is refused.
- `tests/util/test_limit.py`, `run()` and `apply_limits()`: an owned limit
  raised inside the agent's task group is returned; a group with a foreign
  leaf propagates; a group of an owned token limit and a sourceless `custom`
  limit propagates as a group; a group of an owned limit and a limit of a
  node entered below it is caught and returns the owned one; a bare
  descendant limit propagates; an owned token
  limit exceeded and swallowed inside the
  agent is returned as `(state, error)` by the exit check (the return path
  of `run()`); an owned limit reached exactly and swallowed after a refused
  call is returned; an owned limit reached exactly with no refused call
  returns `(state, None)`; a sample limit swallowed inside the agent does
  not leave `run()` at its exit (`run()` returns `(state, None)`), the
  caller's next model call is refused with it, and if the solver instead
  returns, the sample is recorded as limited by it; a synchronous deepagent
  subagent's swallowed limit is reported as its result;
  - retuned limits: a `run()` token limit that raised at 10, retuned to 20
    through its `limit` setter, that ends at exactly 20 without a refusal at
    20 returns `(state, None)`; the same limit refused at 20 returns its
    error; a sample whose token limit, and separately cost limit, is refused
    at 10, lowered through `state.token_limit` (or `state.cost_limit`) to 5,
    where the setter's check raises and is caught, and restored to 10, ends
    at exactly 10 recorded as limited;
  - plain blocks: inside `with token_limit(n)`, after a call exceeds the
    block's limit and the error is caught inside the block, a further call
    made inside the block is refused with that limit; a catch inside the
    block is not raised again at its close;
  - own limits outside the chain: `apply_limits([time_limit(...)],
    catch_errors=True)` and `run(limits=[time_limit(...)])` still catch and
    return their own time limit error, including one raised as the limits
    exit (the existing `test_apply_limits_handles_time_limit` stays);
- `tests/_control/test_limits.py`, live overrides and the exit check: a
  sample whose root token limit is refused at 10 ends normally at exactly
  20 and is not recorded as limited, both when an override of 20 is set
  through `set_sample_limit_override()` after the refusal and when an
  override of 10 is cleared back to a launch budget of 20; in each case a
  call refused at 20 (fresh refusal at the new threshold) records the
  sample as limited by its token limit; an override set back to 10
  after a refusal at 10 records it as limited at exactly 10; and an
  override of 5 set after a refusal at 10, raised at the next check and
  then cleared back to a launch budget of 10 records it as limited at
  exactly 10.
- `tests/checkpoint/test_sample_runtime.py`: the payload is unchanged
  (no new keys); after a dump and normal restore of a token root that
  refused a call at exactly its budget, the next call is refused before
  dispatch; after a scoring-only restore of spent token, cost and turn
  roots, `as_solver(react(...))` returns normally with no model call and
  the sample is scored and not recorded as limited (the no-call control),
  on asyncio and Trio;
  - the restore clears the mark, for token, cost and turn roots each, on
    asyncio and Trio: a root refused at 20 by a sample-start hook (error
    caught), lowered to 10 and restored to 0 has `_raised_at` cleared;
    a call that then reaches exactly 10 followed by a refused call, with
    the solver returning, records the sample as limited by that root; the
    same with the budget lowered in `on_resume` after the restore; without
    the refused call (exactly 10 used) the sample is not recorded as
    limited; a control with the budget left at 20 and a fresh refusal at
    20 after the restore is recorded as limited; a payload without the
    root's key leaves its mark in place.
- `tests/util/test_limit.py`, sentinel: a stub in-process monitor whose
  priced model call would exceed a reached sample cost limit is made and
  not charged to it.
- `tests/agent/test_agent_execute.py`: a sample token limit reached inside an
  `as_tool()` agent ends the sample with `limit.type == "token"` and no
  further generation; `as_tool()`'s own token limit is still a tool error;
  `test_agent_as_tool_respects_sample_limits` (message) is unchanged; a
  handoff passes on a foreign token limit and still answers its own; a
  handoff whose agent exceeds a `with token_limit()` entered inside it, and
  one whose agent exceeds a `time_limit()` entered inside it, return the
  agent's new messages and the handoff limit message, as today.
- `tests/test_eval.py` (or the existing sample-limit tests): a solver that
  swallows a sample token limit and returns is recorded as limited; a solver
  whose call was refused at exactly the sample token budget, which swallows
  the refusal and returns, is recorded as limited; a solver that uses exactly
  the budget and returns is not; a solver that catches the limit and raises
  `state.token_limit` is not; a resume for scoring over a spent budget is
  not; a sample with a cost limit whose solver calls an unpriced model fails
  with `UnmeteredCallError`;
  - exit check after cleanup (each with the worker synchronized by an
    `anyio.Event`, never a sleep): a `background()` worker makes a priced
    call in its cancellation cleanup after `plan()` returns, exceeds the
    sample cost limit, catches the error and returns: the sample ends on the
    cost limit; the same with a cleanup call refused at exactly the budget;
    `plan()` raises a
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
  - a bridged sentinel monitor call and an approval call made for a
    request in flight after the bridge kept a limit still run (pinned, as
    today), and the agent ends on the kept limit when it unwinds; a host
    tool whose `as_tool()` child runs a monitor while a limit is kept
    during its execution gets no `SentinelFailure`, and the sample ends on
    the kept limit;
  - after a limit is kept, two fresh sequential host-tool requests, one to
    an `as_tool()` agent and one to a tool calling `run()` with a monitor
    configured, each get the `limit` tool-error reply and make no tool,
    monitor or provider call, and the kept limit is unchanged;
  - an unpriced bridged model under a cost limit fails the sample with
    `UnmeteredCallError`, with no provider call;
  - a kept sample token limit reached exactly by a refused request, then a
    cancellation of the bridged agent before delivery and a normal return
    from the solver, ends the sample on the token limit;
  - a request after a reached turn limit makes no generation;
  - the kept-limit entry refusal holds under suspension: with the bridge's
    service task started inside `suspend_token_limit()`, and again inside
    `suspend_limits()`, a request whose three-message prompt reaches
    `message_limit(2)` keeps the message limit, and a fresh request with a
    one-message prompt gets the kept limit's error reply with no provider
    call; the same with no suspension; a newly reached outer token limit at
    the next request's entry replaces the kept limit;
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

0. **Prerequisite: cost suspension.** `suspend_cost_limit()` and
   `suspend_limits()` in `_limit.py`, with the behaviour stated under
   "Current behaviour", used by in-process sentinel dispatch, the sidecar
   result lookup, tool approval and tool review. The steps below assume it.
1. **The chain and one check.** `src/inspect_ai/util/_limit.py`:
   `_limit_chain`, `_outer`/`_in_chain`/`_raised_at`, push/pop, `_chain_depth`,
   `_rank`, `outermost_limit`, `first_or_outermost_limit`, `_outer_than`,
   `_check_marked`, `check_limits`, `_counted`, `record_model_call`,
   `_TurnLimit._check_self(raise_for_equal)`, `_refused_at_budget()` (no
   setter or override-store change), `record_turn` recording only,
   the affine grammar and non-negative weights in `_compile_token_formula()`,
   with metering from the reduced coefficients.
   `src/inspect_ai/util/_checkpoint/sample_runtime.py`:
   `restore_sample_runtime()` sets `_raised_at = None` on each root whose
   counter it assigns (no payload change).
   `src/inspect_ai/model/_model.py`: `record_and_check_model_usage(check=)`,
   the inner generation recording without a check, the outer frame's
   `record_turn()` then `check_limits()` (`turns_only=True` for a cache
   hit), the same order in
   `_generate_prepared()` for an output `refusal_after_error()` recovers,
   `_check_limits_before_dispatch`.
   Tests: the node-level cases in `tests/util/test_limit*.py` (chain,
   precedence, recording, pre-dispatch refusal, `_raised_at` and
   `_refused_at_budget()` across setters and overrides), and in
   `tests/checkpoint/test_sample_runtime.py` that a restore clears the mark
   of each root it assigns.
2. **Unpriced models.** `_limit.py`: `UnmeteredCallError`. `_model.py`:
   the unpriced check in `_check_limits_before_dispatch(model)` and the
   model passed by `generate()`'s and compaction's per-attempt calls;
   `Model.should_retry()` returns `False` for `UnmeteredCallError`.
   `src/inspect_ai/model/_util.py`: `resolve_model_costs()` checks the task
   model only, with the shared message helper.
   `src/inspect_ai/agent/_bridge/sandbox/service.py`: `UnmeteredCallError`
   fails the sample. Tests: `tests/util/test_limit_cost.py`,
   `tests/model/test_model_info.py`, `tests/test_eval.py`,
   `tests/test_sample_limits.py`, `tests/test_enqueue_task.py`,
   `tests/agent/test_bridge_provider_errors.py`.
3. **Suspension.** `_limit.py`: `check_limits()` skips suspended cost
   nodes. The guard checks stay skipped while token limits are suspended,
   as today, and run under turn-only or cost-only suspension.
   Tests in `tests/util/test_limit_token.py`,
   `tests/util/test_limit_cost.py` and
   `tests/agent/test_bridge_provider_errors.py`.
4. **Owners and reductions.** `_limit.py`: `apply_limits()` covered exits
   and `check_own_limits()` over its own limits on a normal return.
   `src/inspect_ai/agent/_run.py`: the return after the block.
   `src/inspect_ai/_eval/task/run.py`: `first_or_outermost_limit` for the
   escaping group, and `check_own_limits()` over the sample's roots after
   the sample task group has joined when the solvers returned, skipped
   when the attempt is `resume_for_scoring`.
   `src/inspect_ai/model/_call_tools.py`: `decisive_tool_exception`,
   `decisive_sentinel_exception`. Tests: the owner-exit cases, which need
   these checks: `run()` and sentinel tests in `tests/util/test_limit.py`,
   `tests/test_eval.py`, `tests/agent/test_agent_overflow_compaction.py`,
   the live-override sample outcomes in `tests/_control/test_limits.py`,
   and the restore and scoring-resume outcomes in
   `tests/checkpoint/test_sample_runtime.py` (the checkpoint change is in
   step 1).
5. **Ownership in tools.** `_call_tools.py`: the call leaf and ownership test
   in `call_tool_task`, and the same test in `agent_handoff()`'s `except`.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: `_raised` ownership,
   `keep_limit` for foreign limits. Tests: `tests/agent/test_agent_execute.py`,
   `tests/agent/test_agent_handoff.py`, `tests/tools/test_tools_bridge.py`.
6. **The bridge.** `src/inspect_ai/agent/_bridge/sandbox/service.py`: entry
   simplification (the separate turn check goes; the kept-limit branch
   stays, after the pre-dispatch check), the host-tool entry refusal in
   `call_tool()`,
   `_first_control` outermost, `keep_limit`, deletion of
   `_encloses`/`_sample_roots`/`_in_tree`. `src/inspect_ai/agent/_bridge/util.py`:
   `_apply_response_filter()`'s reduction.
   `src/inspect_ai/agent/_bridge/sandbox/types.py`: `keep_limit()`, the
   `generation_limit` docstring. Tests:
   `tests/agent/test_bridge_provider_errors.py`.
7. **Docs.** `docs/setting-limits.qmd`, `docs/_agent_limits.md`,
   `docs/_turn_limits.md`, and the docstrings of `token_limit()`,
   `cost_limit()`, `turn_limit()`, `suspend_token_limit()`, `apply_limits()`
   and `run()`.

inspect_swarm adapts in its own repository ("What inspect_swarm can delete
or simplify"). Its `SwarmTurnNode._check_self()` takes `raise_for_equal`
before or with step 1, which passes that argument to every `_check_self()`
through `_check_marked()`; an override without it raises `TypeError` there.
Its pricing, ledger and stop-gate changes go with steps 2 and 3.

## Open questions

None.

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
  limit error swallowed there costs: it surfaces one step later, at the
  next call under the limit, which is refused at no cost, or at the owner's
  exit check; a plain `with` block's limit surfaces only at a call made
  while the block is open. Spend stays bounded and the sample limit is not
  lost. An
  unpriced-model refusal swallowed there is refused again at the handler's
  next call to that model, with nothing spent. Making each re-raise these
  errors would only make them arrive sooner.
- Routing `background()` work to the `run()` or runtime that started it.
  Default deepagent background children keep their sample-scoped lifetime
  and report to the sample; a runtime that needs their errors installs a
  background target (see "What a runtime can rely on").
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
