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
happened. Once reached, a limit refuses every later model call in its scope.
Under a cost limit, a call to a model with no price is refused, and a
response that reports no usage fails its call, as any model failure does.
Failed attempts and calls cancelled in flight are not charged, as today, so
they can take spend past a cost limit. A limit error that reaches its owner stands. When
none does, a scope that owns limits checks them when it ends normally, and
so does the sample, once all of its work, background cleanup included, has
finished. So, within a running attempt, a limit error that some handler
catches and drops is not lost: it comes back at the next refused call, or at
its owner's exit. Checkpoints store usage but not the mark of a limit that
refused a call, so a sample resumed from a checkpoint can lose it.

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
- One suspension rule: a suspended kind is neither charged nor checked.
- One ownership rule: which code may turn a limit error into something other
  than an exception.
- A stated guarantee that a runtime can catch a sample limit, stop in an
  orderly way and re-raise it.
- A cost limit meters every call that comes back: a model with no price is
  refused before dispatch, and a response that reports no usage fails its
  call. Failed attempts and cancelled calls stay uncharged,
  as today, and that overshoot is stated.
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
  the called model has no cost data. Before the eval starts, and for each
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
- Three providers fill in zero usage when a response reports none. Mistral's `mistral_completion_from_stream()` substitutes
  `UsageInfo(0, 0, 0)` with a warning (`_providers/mistral.py:646-652`),
  which `MistralAPI.generate()` converts to a `ModelUsage` (`:366-374`).
  SageMaker's stream assembly writes a zero `usage` dictionary
  (`_providers/sagemaker.py:790-791`) before the shared OpenAI conversion.
  Grok converts its protobuf `usage` unconditionally
  (`_providers/grok.py:683`), so an absent usage message reads as zeros, on
  every route; in a stream, the SDK copies each chunk's `usage` into the
  accumulated response, so a usage-less chunk also replaces an earlier
  reported total with zeros. These outputs are indistinguishable from a
  reported zero. The other
  conversions keep a missing usage as `None` (the shared OpenAI conversion,
  `src/inspect_ai/model/_openai.py:1206-1231`; Google,
  `_providers/google.py:2606-2610`), or raise (Bedrock streaming,
  `_providers/bedrock.py:1228-1233`). Google's continuations and
  malformed-function-call retries, and the LiteLLM proxy's
  malformed-function-call retries, sum the usage of several requests with
  `sum_usage()`, which skips a request with none, so a call whose requests
  reported usage only in part returns that part as its usage (see "Usage
  summed over several requests").
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
- Several providers turn a rejection of the request into an output rather
  than an error, with no usage: OpenAI's HTTP 400 `context_length_exceeded`
  becomes a `model_length` output and its content-policy rejections a
  `content_filter` output (`openai_handle_bad_request()` and
  `openai_refusal_model_output()`, `src/inspect_ai/model/_openai.py:1666-1712`),
  which Chat Completions and Responses return to the model wrapper
  (`_providers/openai_completions.py:152-158`,
  `_providers/openai_responses.py:313-320`). ReAct relies on the
  `model_length` output to compact or truncate and retry. The same helper
  also converts errors that arrive mid-stream
  (`openai_handle_stream_error()`), after inference has started. Other
  providers have their own converters (listed under "Unmetered calls").
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
5. **A suspended call is invisible to the kinds it suspends.** Inside
   `suspend_token_limit()`, `suspend_turn_limit()` or `suspend_cost_limit()`
   (or `suspend_limits()`, all of them), limits of that kind neither record
   nor check the calls made in the block, and the cost rules for unmetered
   calls (rule 9) skip a call while cost is suspended. The `dispatch_guard()`
   checks are skipped while token limits are suspended, as today, so
   `suspend_token_limit()` and `suspend_limits()` skip them and
   `suspend_turn_limit()` or `suspend_cost_limit()` alone does not.
   Approval, review and sentinel calls run under `suspend_limits()`, so they
   skip the bridge guard. Message limits are still checked.
6. **The owner handles its error.** Code that did not enter a token, cost or
   turn limit never turns that limit's error into a message, a tool error, a
   reply or a return value. It lets the error propagate. Message limits keep
   today's handling (see "Ownership").
7. **The owner checks at exit.** A limit error that reaches its owner
   stands. When an `apply_limits()` scope ends normally, Inspect runs the
   check once more over the chain. A limit raises there if it is exceeded,
   or if it is reached and has already raised (a call it refused). The
   sample does the same once its task group has finished, when its solvers
   returned normally.
8. **The bridge keeps the outermost limit.** The sandbox bridge keeps the
   outermost limit any of its requests reached (generations and host tools
   alike), refuses every later model call with it, and raises it when the
   agent has unwound.
9. **A cost limit refuses what it cannot meter.** While a cost limit is on
   the chain and cost is not suspended, a call to a model with no cost data
   is refused before dispatch, and a response whose usage is missing or
   totals zero (other than an output Inspect built from the provider's
   rejection of the request) fails its call with a non-retryable error, as
   any model failure does. Nothing is marked. Failed attempts and cancelled
   calls are not charged.

Rules 3 and 7 together make node state the record of limits. The design
does not try to carry every limit error intact through every handler that
can catch one (a fallback, a hook, a first-error reduction, a cancelled
delivery). A swallowed limit error costs time, not budget: the next call
under the limit is refused before dispatch, and if no limit error reaches
the owner, its exit check finds the limit. That holds within one attempt: a
checkpoint resume keeps usage but drops the mark of a limit that refused a
call ("Checkpoints"). An unmetered-call error (rule 9) is a model failure,
not a limit: a handler that swallows one and calls again gets one more call
that no limit counts ("Unmetered calls"). Where Inspect's own
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
    _raised: bool  # set when this node's check raises; never cleared


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


def check_limits(raise_for_equal: bool = False, at_exit: bool = False) -> None:
    """Raise the outermost reached token, cost or turn limit on the chain."""
    nodes = _chain_root_first()  # from _limit_chain via _outer
    for node in nodes:
        if isinstance(node, _TokenLimit) and token_limit_tree.is_suspended():
            continue
        if isinstance(node, _TurnLimit) and turn_limit_tree.is_suspended():
            continue
        if isinstance(node, _CostLimit) and cost_limit_tree.is_suspended():
            continue
        if isinstance(node, (_TokenLimit, _CostLimit, _TurnLimit)):
            # raises (with its SampleLimitEvent) and sets node._raised
            node._check_marked(raise_for_equal or (at_exit and node._raised))
```

- `_Node._check_marked(raise_for_equal)` calls
  `_check_self(raise_for_equal)`; if that raises a `LimitExceededError`, it
  sets `self._raised = True` before re-raising. Every check path goes
  through it: `check_limits()` and the
  per-kind `check()` methods. inspect_swarm's `_check_self()` overrides
  therefore set `_raised` too.
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
  `dispatch_guard()` checks, which are skipped while token limits are
  suspended, as today (`_model.py:3689-3701`, rule 5). It is
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
for good: it stays reached, so the next dispatch is refused (rule 3), and the
owner's exit check raises it if the scope ends normally (rule 7).

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
(suspension wins over nested limits, as for tokens today). The rules for
unmetered calls skip them too (rule 9): an unpriced approver, reviewer or
monitor model is not refused, and a response without usage does not fail.
For that exemption to hold, the start-time price check no longer requires
prices for role models, which it cannot tell apart by use ("No price:
refused before dispatch"). Their spend is still recorded in model and role
usage and in the sample's reported cost.

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
handling: the wrapper turns it into a `SentinelFailure`, which in a bridge
becomes an ordinary error reply with no kept limit, and which a native tool
or the runner unwraps as today (`_sentinel_exception()`,
`_call_tools.py:170-177`; `run.py:2913-2916`). Message limits are outside
the chain's exit checks, so nothing records it later. This design does not
change it.

### The owner's exit check

A limit error that reaches its owner stands: `apply_limits()` and the sample
runner record the error they receive (after the reductions in "Precedence")
and do not compare it with node state. Rule 7 covers the other case, where
no limit error reaches the owner because a handler swallowed it. It has two
call sites:

- `apply_limits()`, on a normal return: after the body returns, before it
  exits its limits, it calls `check_limits(at_exit=True)`. A limit that
  raises there is handled by the same `except` as one raised in the body:
  caught if owned and `catch_errors=True`, propagated otherwise. A sample
  limit raised at that point leaves `run()` and ends the sample.
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
`check_limits(at_exit=True)`. The sample's roots are the chain's only nodes
at that point, so it raises the outermost root that counts at exit, with
its `SampleLimitEvent`, and the existing `except LimitExceededError`
(`run.py:3422`) records it.

Everything else is unchanged. A limit error that escapes the solvers is
recorded as it is today. A non-limit error (after
`first_or_outermost_limit()` reduces a group, the deciding leaf is not a
limit) goes to the error handling as today, so an error still outranks a
limit at the runner. A termination keeps its own `except` clause. An
operator interrupt and a limit delivered by cancellation (the working limit,
or a limit a sandbox service routes to the sample) keep their handling
inside `run()`, which sets the outcome before the join and leaves `solved`
unset. A resume for scoring skips the check: it restores a spent budget on
purpose, and `restore_sample_runtime()` takes the same `check=False` switch
for that reason.

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

The `_raised` mark is per node and is never cleared, so it survives the
cancellation that loses the error itself. A checkpoint does not store it
("Checkpoints").

Plain `with token_limit(...)` blocks get no exit check. Their author enters
and owns them, and may catch their errors on purpose. Their nodes are no
longer on the chain when an enclosing owner checks at exit, so a mark on them
has no effect there.

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

Checkpoints are unchanged, and do not store the `_raised` mark (decision:
Ransom, 2026-11-16). A checkpoint stores the sample roots' usage, and a
normal resume restores it into fresh roots and checks them:
`dump_sample_runtime()` writes the token usage, cost and turns
(`src/inspect_ai/util/_checkpoint/sample_runtime.py:47-96`), the
checkpointer stores that payload
(`src/inspect_ai/util/_checkpoint/checkpointer_impl.py:624-633`), and
`restore_sample_runtime(check=True)` reseeds the roots and runs the token,
cost and turn checks, in that order, with `>` (`sample_runtime.py:153-163`,
`:221-225`; called for a normal resume at `checkpointer_impl.py:147-152`).
An exceeded root therefore still ends the resumed attempt before it makes a
call. A resume for scoring (`check=False`) runs no check, as today.

The fresh roots carry no `_raised` mark, so the exit check's handling of a
limit reached exactly holds within one attempt. A limit that refused a call
at exactly its budget is restored at that usage, so any further call is
refused by the pre-dispatch check (`>=`), which raises it and sets `_raised`
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
- Host-tool requests get the same entry refusal. Today `call_tool()`
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
  carries the `_raised` mark. It refuses every later call under it (rule
  3), and when no other limit error reaches its owner, rule 7 raises it
  when that owner ends normally: an `apply_limits()` scope, or the sample's
  exit check when the solvers return, whether the limit is exceeded or was
  reached exactly by a refused request: for example a swarm that
  hard-stopped the member and then returned.
- An unmetered call (`UnmeteredCallError`, see "Unmetered calls") in a
  bridged generation fails the sample through `bridge.request_fail()`, as a
  `ModelRefusalError` or `ResponseFilterError` does, so the sample fails with
  the error's message. If a cancellation displaces that failure before it is
  delivered, nothing records it, and a retried request to a model whose
  responses report no usage is made and fails again: one uncounted call per
  displaced failure ("Unmetered calls").

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
   (a fallback, a hook, `tg_collect()` keeping another error), it arrives
   instead at the next call any agent makes under the sample, which is
   refused with it (guarantee 2).
2. **A reached limit stays reached.** Every later dispatch under that
   sample, including the runtime's own model calls, native compaction and
   bridged requests, is refused with the same node's error. Approval,
   review and sentinel calls are the exception: they run with token, turn
   and cost limits suspended and skip the bridge guard, so a reached limit
   of those kinds, or a bridge's kept limit, does not refuse them.
   Calls already dispatched complete, are recorded, and raise the same error
   after recording.
3. **The runtime may hold the error.** It can catch it, stop its agents
   (close levers, wait for in-flight calls within its grace, cancel the
   rest), write its ledger and re-raise the error, bare or in a group. The
   runner records it as the sample's limit (`EvalSampleLimit` of that type).
   During the stop, no model call can succeed under the reached limit, so
   the runtime's final step must make none.
4. **Losing it is not silent.** When the solvers return normally, the
   sample's exit check records the outermost sample limit that counts at
   exit (rule 7): one that is exceeded, or reached exactly after refusing a
   call. That covers a runtime, or a bridged agent
   cancelled before its CLI exited, that drops the error. It runs after
   background cleanup, so usage recorded there counts. A limit error that
   reaches the runner is recorded as it is: it can differ from the
   outermost sample limit that counts when a limit is pushed over in
   cleanup after another escaped, or when an adapter's state copy raises a
   different limit (see "What the owner can miss"). An exit decided by a non-limit error, a
   termination or an operator interrupt keeps that outcome.
5. **A cost limit meters every call that comes back.** No model without
   cost data is dispatched under a sample or swarm cost limit, and a
   response whose usage is missing or zero (other than a rejection output)
   fails its call with `UnmeteredCallError` (rule 9). The agents' spend
   under a cost limit is therefore at most the limit, plus the calls
   already in flight when it was reached, plus what the limit does not see:
   one call for each time code catches a no-usage `UnmeteredCallError` and
   calls again, failed attempts, which the retry policy bounds
   (`max_retries`, unlimited by default), and every dispatched call that is
   cancelled before its usage is recorded (one cancelled scope can cancel
   several, such as a bridge's concurrent requests or a member's background
   work). Approval, review and sentinel spend is not counted at all
   (rule 5).

Guarantees 2 and 4 rest on node state, which lives for one attempt. A
checkpoint resume restores usage but not the `_raised` mark, so a refusal at
exactly the budget from before the checkpoint is not carried into the
resumed attempt ("Checkpoints").

The sample's time limit (a cancel scope around the solvers) and working limit
(a sample-wide cancellation) are outside these guarantees. They end the sample
by cancellation, which the runtime cannot hold.

Message limits are per conversation: a sample message limit reached in a
member's own conversation (one with no message limit of its own) is raised
there like any other foreign error, and reaches the runtime the same way.

### Unmetered calls

Under a cost limit, every call that comes back must be metered (decision:
Ransom, 2026-11-12, refusing unpriced models; scope: Ransom, 2026-11-16,
calls that came back). Two things make such a call unmetered: the model has
no cost data, or the provider's response reports no usage, so there is
nothing to price. Both fail the call with one error, as any model failure
does, and mark nothing (decision: Ransom, 2026-11-17). Neither applies while
cost is suspended (rule 5), so approval, review and sentinel calls are
exempt.

Calls that do not come back are not charged, as today: an attempt that
fails (an error response, a timeout, a connection reset, an empty stream)
and a call cancelled in flight (decision: Ransom, 2026-11-16). A provider
may still bill some of them. Spend under a cost limit can therefore exceed
it by the cost of failed attempts, which Inspect retries up to
`max_retries` (unlimited by default) and `timeout`, and by the cost of every
dispatched call that is cancelled before its usage is recorded; one
cancelled scope can cancel several calls at once (the bridge's sandbox
service runs one task per pending request,
`src/inspect_ai/util/_sandbox/service.py:441-449`). The retry policy is the
only bound on failed attempts.

**The error.** `UnmeteredCallError(PrerequisiteError)`, a private error
defined in `_limit.py` beside the cost limit. Its message says which case
it is and what to do:

- no price: "cost_limit requires cost data for every model called under it.
  No cost data for '<model>'. Use set_model_cost() or --model-cost-config to
  configure pricing." For a model not in the model database the last
  sentence is the one `model_usage_cost()` already uses: "It is not in the
  model database, so use set_model_info() with a ModelInfo that includes
  cost." `resolve_model_costs()` (`src/inspect_ai/model/_util.py:67-98`)
  and this error share one helper for this text.
- no usage: "cost_limit requires usage from every call made under it.
  '<model>' returned no token usage, so the cost of the call is unknown."

It is never retried: `Model.should_retry()` (`_model.py:2066`) returns
`False` for it before any other test, so a provider's `should_retry()` never
sees it. It is not a `LimitExceededError`, so no limit owner catches it.
When it reaches the sample runner the sample fails with it, as a sample
error. Native tools do not map it (`tool_call_error()` returns `None` for
it), and a bridged host tool treats it as an unexpected error, which fails
the sample (`host_tool.py:450-452`); a bridged generation fails the sample
with it through `bridge.request_fail()` (see "The sandbox bridge").

Nothing is marked, so the cost limit is not reached by the error. Code that
catches it and calls again (a compaction fallback, a hook that logs and
continues, a first-error reduction, a cancelled bridge delivery) makes
another call: a call to an unpriced model is refused again before dispatch,
with nothing spent, and a call whose response reports no usage is made and
fails again. So each catch of a no-usage error costs one call that no
limit counts.

**No price: refused before dispatch.**

- **When.** In `_check_limits_before_dispatch(model)`, after the limit check
  and before the guards: if cost is not suspended, any cost node on the
  chain has a limit (not `None`), and `_get_model_info_direct(model)` has no
  `cost`, it raises. This is the same lookup and the same test as
  `model_usage_cost()`'s "called model has no cost data" case and as the
  start-time check. It runs per attempt, for `generate()` and native
  compaction, for agent and subagent models; approver, reviewer and monitor
  models are exempt, because their calls run with cost suspended.
- **Not refused.** A cache hit (no dispatch). A priced model whose provider
  reports that an unpriced model served the call: that call is priced at the
  called model's rates with a warning, as today. A model with cost data of
  zero.
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

**No usage: the call fails.** `ModelOutput.usage` is optional
(`src/inspect_ai/model/_model_output.py:286`), and a provider can omit it,
or fill in zeros when a response reports none ("Current behaviour"). Today
the inner generation records nothing when `output.usage` is `None`
(`_model.py:1988`), and native compaction records nothing when its `usage`
is `None` (`_model.py:1546`), so such calls never advance a cost limit, and
a priced model that never reports usage can be called without bound under
one.

A real successful call always reports at least one input token, so usage
that is missing or totals zero means the provider did not report it. One
helper states the test:

```python
def require_reported_usage(usage: ModelUsage | None, model: str) -> None:
    """Raise UnmeteredCallError when a cost limit needs usage the call did not report."""
    if cost_limit_tree.is_suspended() or not _active_cost_limit():
        return
    if usage is None or (
        usage.input_tokens
        + usage.output_tokens
        + (usage.input_tokens_cache_read or 0)
        + (usage.input_tokens_cache_write or 0)
    ) <= 0:
        raise UnmeteredCallError(...)  # the no-usage message
```

`_active_cost_limit()` is true when a cost node on the chain has a limit
that is not `None`. Without an active cost limit nothing changes, and usage
of zero is recorded as zero, as today. The helper runs in two places in
`Model`, inside the attempt so that a failure is handled like any other
model failure (its `ModelEvent` completes with the error, `_model.py:1866`,
and no usage is recorded):

- in `generate()`, after `self.api.generate()` returns and its timeouts are
  checked (`_model.py:1850-1864`), on the output's usage unless the output
  is a rejection output (below);
- in native compaction's `_compact()`, after `self.api.compact()` returns
  (`_model.py:1531-1532`), on the returned usage.

A cache hit is not dispatched and not checked. The billed usage of a
sentinel-sidecar refusal (`_model.py:1170`) is recorded only when the
sidecar reports it, as today; that path follows a provider error, not a
successful response, and is left as is.

**Usage summed over several requests.** Some providers make several billed
requests for one call and return the sum of their usage with `sum_usage()`
(`src/inspect_ai/model/_model_output.py:485-497`), which skips a request
that reported none, so the sum can be non-zero although one request
reported nothing. Three paths do this for successful responses:

- **Google** continuations and malformed-function-call retries:
  `_ContinuationChain.add()` sums each response's usage
  (`_providers/google.py:254-258`), and the output carries the chain's sum
  (`:943-949`).
- **The LiteLLM proxy's** malformed-function-call retries add the usage of
  each discarded attempt to the final output's
  (`_providers/litellm_proxy.py:961`, `:970`).
- **Anthropic** continuations (`pause_turn` and other continued turns):
  `_perform_request_and_continuations()` passes the head response and each
  continuation leg through `chain.add()` (`_providers/anthropic.py:1368`),
  and `_ContinuationChain.add()` sums their usage (`:355-358`). The SDK's
  `message.usage` is required but its counts can be zero, and the
  converter keeps those zeros, so a zero leg summed with a positive one
  passes a check on the sum.

Each applies the same test to every successful request before it sums
(decision: Ransom, 2026-11-17): `_ContinuationChain.add()` calls
`require_reported_usage()` on the response's converted usage before adding
it, the proxy calls it on each attempt's output usage before adding it
to `discarded_usage` and on the final output unless that is a rejection
output, and Anthropic calls it on each leg's output usage before
`chain.add()` (`anthropic.py:1368`). Anthropic's converted errors go through
`chain.report()`, not `chain.add()`, so a rejection is never checked there. The error raised there leaves the provider's `generate()` and is
handled by `Model` as above, so the call fails and none of its requests are
charged, as for any failed attempt. The check has the same gating
everywhere: it does nothing without an active cost limit or while cost is
suspended. `sum_usage()` itself is unchanged.

Google's converted-error return must carry the usage of every response
that completed. Today it takes `attempts_usage` and
`attempts_input_context_tokens`, which advance only when a whole continued
attempt returns (`google.py:870-874`, `:905-914`), so the legs of a
continuation in progress are dropped: a continuation leg that reported 42
tokens followed by a context-length 400 returns `usage=None`, and the
rejection exemption means nothing counts it. The handled-error branch
instead sets `handled.usage = chain.usage` and
`handled.input_context_tokens = chain.input_context_tokens` (the first
request's input size); `attempts_usage` and `attempts_input_context_tokens`
go. Google's batch route makes no continuations (`google.py:1000-1003`).
Raised failures and cancellations are unchanged: they return no output, as
for any failed attempt. Anthropic's continuation chain already reports its
accumulated usage on a converted-error return (`chain.report()`,
`anthropic.py:1112-1135`), and the LiteLLM proxy sums each discarded
attempt before retrying, so neither drops completed responses.

**Grok streams keep their last reported usage.** Grok converts its
protobuf `usage` unconditionally (`_providers/grok.py:683`), and in a
stream the SDK's `Response.process_chunk()` copies every chunk's `usage`
into the accumulated response (`CopyFrom(chunk.usage)`, xai-sdk), so a
usage-less tail chunk overwrites an earlier reported total with zeros,
which the check above would turn into a false failure. The stream loop
(`grok.py:405-415`) keeps its own copy of the usage of the last raw chunk
with `chunk.proto.HasField("usage")`, and passes it to the conversion:
`_model_output_from_response(response, tools, usage: SamplingUsage | None
= None)` uses it in place of `response.usage` when given. A stream with no
reported usage converts to zero usage, as today, and fails the check under a
cost limit. The unary, structured and batch routes are unchanged: an absent
usage there reads as zeros and fails the check. The logged response
(`MessageToDict(chat_response._proto)`) is unchanged.

**Rejection outputs are exempt.** Several providers return the provider's
rejection of a request as an output with no usage (see "Current
behaviour"), and ReAct needs OpenAI's `model_length` output to compact or
truncate and retry. Such an output was built by Inspect from an error
response received in place of a completion, so no inference ran. The stop
reason alone does not show that: `model_length` and `content_filter` also
end outputs after inference or mid-stream. So the provenance travels with
the output:

- `ModelOutput` gains a private attribute, `_rejection: bool =
  PrivateAttr(default=False)`, which is not serialized, so logs, the cache
  and the viewer's types are unchanged; `model_copy()` keeps it.
  `rejection_output(output) -> ModelOutput` (in `_model_output.py`) sets it
  and returns the output.
- A converter calls `rejection_output()` only on an output it builds from an
  error *response* to the request: an HTTP status error, or a gRPC or
  Bedrock error code, received before any output. A converter reached from
  a mid-stream failure, after the provider started responding, does not.
  The shared OpenAI converter `openai_handle_bad_request()` applies it when
  its exception is an `APIStatusError` (a status response), and not for the
  status-less `APIError` that `openai_handle_stream_error()` passes it for a
  mid-stream failure.
- The check skips an output whose `_rejection` is set. Every other output
  with missing or zero usage fails, including a rejection-shaped output from
  a converter that has not been classified, which fails closed. Requests
  summed into a rejection output (Google's earlier legs, the proxy's
  earlier attempts) were each checked before they were summed.

The converters to classify, from a survey of the providers: the shared
OpenAI converter (`_openai.py:1666-1712`, used by Chat Completions,
Responses and the OpenAI-compatible providers), `anthropic.py:1120` (the 413
too-large response) and `:2206` (`handle_bad_request`), `azureai.py:544`,
`bedrock.py:933`, `cloudflare.py:82`, `deepseek.py:116`, `google.py:1454`,
`grok.py:550` and `:563`, `groq.py:545`, `mistral.py:438`, `moonshot.py:174`,
`openai_compatible.py:586`, `sglang.py:284`, `together.py:145`,
`vllm.py:699`, and the LiteLLM proxy's `litellm_error_model_output()`
(`_litellm_proxy_errors.py:65`, `:73`, called from `litellm_proxy.py:1193`),
all under `src/inspect_ai/model/_providers/`. Each builds its output from an
error raised for the request; the implementation confirms for each whether
that error can also arrive after streamed output, and leaves any that can
untagged by `rejection_output()`.

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

What the swarm must change: its `_SwarmTurnNode._check_self()` takes the new
`raise_for_equal` argument. Its other overrides (`record()`, the token and
cost `_check_self()`, the message `check()`) are called as today, through
`_check_marked()`. A member whose model has no cost data, or whose provider
returns no usage, under a swarm cost node now fails that call with
`UnmeteredCallError` (rule 9), so the swarm needs pricing and usage for
every member model wherever it uses cost nodes. The error is not a limit,
so it does not reach a cap. Uncaught, it fails the swarm: the member's
foreground classification treats it as a foreign error and calls the
member's fatal callback (`_member.py:662-688`), and
`MemberBackground._run()` contains only selected limit errors, so a
background one takes its fatal branch and is re-raised into the owning task
group (`_background.py:138-147`); the controller's fatal callback marks the
swarm failed (`_controller/_control.py:649`, `:1214-1215`). The one
uncounted call per catch applies only where agent or user code catches the
error and calls again. Approver, reviewer and monitor
spend no longer counts toward its cost caps or shares (rule 5), so a swarm
ledger that compares spend to caps must take that spend from model or role
usage. Its per-member `background_target` is what the guarantees'
prerequisite asks for, so it keeps it.

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

**Carry every limit error intact to its owner.** Make each
handler that can catch one (fallbacks around compaction, hooks, first-error
reductions such as `tg_collect()`, the sentinel wrapper, a bridge delivery
that a cancellation can displace) re-raise or forward it. Each review of
that approach found another such handler, and the list is open-ended: any
user or extension code can catch an exception. The rules here make the
nodes the record instead, so within one attempt a handler that swallows a
limit error delays it by at most one call and cannot lose it (a checkpoint
resume drops the `_raised` mark, "Checkpoints").
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

**Store `_raised` in checkpoints.** An optional payload key would carry the
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

**Mark the cost limit when a call cannot be metered.** A durable
"unmetered" mark on every cost limit the call ran under would refuse every
later call, so a handler that swallows the error gains nothing. It needed a
mark that every check honours, a notification so a swarm cap stops at once,
rules for a marked limit set to `None`, and caveats for checkpoints, and
each review found another provider path that reported missing usage as
zero or summed it away. Failing the call, like any model failure, and
treating zero usage as unreported costs one uncounted call each time code
catches the error and calls again (decision: Ransom, 2026-11-17).

**Charge usage summed over several requests as reported.** Google's
continuations and the proxy's retries would return whatever their sum says.
A request that reported nothing would then be uncounted inside a sum that
looks complete, so each successful request is checked before it is summed
instead (decision: Ransom, 2026-11-17).

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
  recorded limit. Limits the tool or handoff entered itself, and all message
  limits, behave as before.
- **Approval, review and sentinel spend leaves cost limits.** With cost
  suspended for them (the prerequisite cost suspension), model calls made by
  tool approvers, tool result reviewers and in-process sentinels, and the
  wait for a sentinel sidecar's result, no longer count toward the sample's
  cost limit, a `run()` or `apply_limits()` cost limit, or inspect_swarm's
  cost caps and shares, and a reached cost limit no longer refuses them.
  Their spend is still in model and role usage and the sample's reported
  cost, which can therefore exceed the configured cost limit. An unpriced
  approver, reviewer or monitor model under a cost limit is not refused,
  and their responses without usage do not fail. As today, they still skip
  the bridge's guard, so they run for requests already in flight after the
  bridge keeps a limit.
- **Unpriced models under a cost limit fail.** A call to a model with no
  cost data, made while a sample, agent or swarm cost limit is active, is
  refused before dispatch with an `UnmeteredCallError` (a
  `PrerequisiteError`) that names the model and how to price it. The sample
  fails with that error unless something swallows it; every later call to
  that model is refused the same way. Evals that
  pass today with a cost limit and a subagent or agent that resolves an
  unpriced model now fail on that model's first call; approver, reviewer
  and monitor models are exempt. The fix is to give the model a price with
  `set_model_cost()` or `--model-cost-config` (or `set_model_info()` for a
  model not in the database). Evals with no cost limit, and cache hits, are
  unaffected. Unpriced calls outside a cost limit now also raise a reached
  token or turn limit after they return, like any call.
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
- **Calls with no usage under a cost limit fail.** A provider response
  whose usage is missing or totals zero, under an active cost limit, now
  fails the call with a non-retryable `UnmeteredCallError`, as a model
  failure: its `ModelEvent` completes with the error and no usage is
  recorded. This affects OpenAI-compatible servers and native-compaction
  providers that omit usage, providers that fill in zeros (Mistral and
  SageMaker streams without a usage chunk, Grok responses without a usage
  message), and test models scripted to return none or zero (`mockllm`
  fills in usage by default). Google and Anthropic calls whose continuation
  (or Google malformed-function-call retry) got such a response, and
  LiteLLM proxy calls whose malformed-function-call retries did, fail the
  same way, whatever order the zero and positive responses came in, and
  none of their requests are charged. Outputs Inspect builds from a
  provider's rejection of the request (OpenAI's context-length 400, and the
  other converters under "Unmetered calls") are exempt, so ReAct's overflow
  compaction and truncation work as today. Without a cost limit nothing
  changes. Fallback handlers that catch every exception (ReAct's overflow
  recovery, `CompactionAuto`'s native-to-summary fallback) are unchanged:
  one that catches the error and calls again makes one more call that no
  limit counts.
- **OpenAI mid-stream safety blocks fail under a cost limit.** With
  streaming, OpenAI delivers a safeguard or content-filter block as an
  error event after the stream has started, and
  `openai_handle_stream_error()` (`src/inspect_ai/model/_openai.py:1715-1737`)
  converts it into a `content_filter` output with no usage. Inference had
  started, so it is not a rejection output, and under a cost limit the call
  now fails with `UnmeteredCallError`, which fails the sample unless
  something catches it; today the agent receives the `content_filter`
  output and can continue. Cyber evals, which meet OpenAI's safety blocks
  often, run with a cost limit and streaming will see such samples end in
  an error instead of a refusal turn. Without a cost limit, or without
  streaming (where the block arrives as a 400 rejection, exempt), nothing
  changes.
- **Grok streams keep their last reported usage.** A Grok stream whose last
  chunks carry no usage now reports the last usage it received, where today
  it ends at zero.
- **Google rejections during a continuation keep the completed usage.** A
  Google call whose continuation is rejected (for example a context-length
  400 after a continuation leg) now returns the usage of every response
  that completed before the rejection, where today it returns the usage of
  completed attempts only, or `None`. Token and cost limits, logged usage
  and the sample's totals count those responses; the rejected request
  itself is still not charged.
- **`apply_limits()`** catches its own limit raised in an exception group
  (when every limit in it is its own or a descendant's; any other leaf,
  including a sourceless `custom` limit, propagates the group as today),
  and at normal exit raises a limit that is exceeded, or reached after it
  refused a call. `run()` therefore returns `(state, error)` in these cases
  where today it raises or returns `(state, None)`. A limit error that
  escapes its body is handled as it is (by ownership of its outermost
  limit), not compared with node state.
- **The sample runner**, when the solvers return normally, checks the
  sample's limits after the solvers and the sample's background work have
  finished, and records an exceeded or refusing sample limit found then. A limit error that escapes the solvers is recorded as today.
  Errors, terminations, operator interrupts and limits delivered by
  cancellation are handled as today.
- **Background work.** Unchanged. Work started with `background()` in the
  sample's task group, including deepagent's default background children,
  still sends its errors to the sample, so a child's limit of its parent's
  `run()` still ends the sample rather than returning from that `run()`, as
  today. The runtime guarantees state this as a prerequisite rather than
  changing it.
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
  `_outer`, `_in_chain` and `_raised`. `ModelOutput` gains a private,
  unserialized `_rejection` attribute.
  `record_turn()` no longer checks. inspect_swarm is the only known user of
  these classes (above).
- **Persisted data and the viewer.** The checkpoint sample-runtime payload
  is unchanged and does not store the `_raised` mark, so a resumed sample
  that returns without another call after a refusal at exactly its budget
  is not recorded as limited ("Checkpoints"). `EvalSampleLimit`, `SampleLimitEvent` and `EvalConfig` limit fields keep
  their shapes, and old logs read the same. No generated TypeScript type
  changes.
- **Docs.** `docs/setting-limits.qmd` and `docs/_agent_limits.md` state the
  precedence rule, that tool-based agents return a message for their own
  limits (an enclosing limit ends the caller), the new turn semantics, the
  suspension rule, that every model called under a cost limit needs cost
  data, and that a token formula must be a non-negative weighted sum (the
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
- **Spend.** The agents' changes either refuse or fail a call sooner (a
  reached turn limit, an unpriced model, a response with no usage) or make
  a limit error propagate further; cache hits remain unrefused, as today.
  The one change that lets calls through that are refused today is the cost
  suspension for approval, review and sentinel calls, whose spend a cost
  limit no longer bounds; it is set by host code (the policies Inspect
  runs), not by a sandboxed agent or model output. With rule 9, a cost
  limit meters every agent call that comes back whatever model a sample, a
  subagent or a sandboxed agent's request selects: the check runs on the
  model a bridged request resolves to, whatever name the CLI sent. The
  rejection flag that exempts an output is set only by Inspect's provider
  converters from an error response, never from response content a model or
  sandbox controls. A sandboxed agent that retries a request whose response
  reports no usage gets one failed, uncounted call per retry; each failure
  is delivered to the sample through `bridge.request_fail()`, which ends
  it. Failed attempts and cancelled calls are outside the bound, as today.

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
    `suspend_token_limit()` and for native compaction; inside
    `suspend_cost_limit()` (as an approver's call runs) it is made; after
    the error is caught, a call to a priced model under the same limit runs
    and is charged (nothing is marked);
  - a cache hit of an unpriced model is served; with no cost limit an
    unpriced call is made;
  - under `cost_limit(1.0)` a priced model whose scripted output has
    `usage=None`, and one whose usage is all zeros (cache fields included),
    fail with `UnmeteredCallError` (message: no usage) after one provider
    call, with the `ModelEvent` completed with the error, no usage recorded
    and no retry; a native compaction (a provider stub returning `None` or
    zero usage) does the same; a response reporting only cache-read tokens
    passes; without a cost limit, or inside `suspend_cost_limit()`, all
    succeed and record what was reported;
  - rejection outputs: an OpenAI client over `httpx.MockTransport` returning
    HTTP 400 `context_length_exceeded` yields a `model_length` output with no
    usage that is returned without error; the same for a 400
    `content_policy_violation` (`content_filter`); the same rejection
    delivered mid-stream through `openai_handle_stream_error()` fails with
    `UnmeteredCallError` under the cost limit and returns the
    `content_filter` output without one; a
    provider stub returning a `model_length` output with no usage and no
    rejection flag fails; one rejection case per classified converter
    (implementation plan);
  - a swallowed error costs one call (pinned): a no-usage error caught by a
    hook that logs and continues is followed by another provider call that
    fails the same way, and nothing refuses it before dispatch;
  - summed usage, in `tests/model/providers/test_google.py` over a stubbed
    SDK client: under a cost limit, a `CONTINUATION` response with no usage
    followed by a reported response, and a `MALFORMED_FUNCTION_CALL`
    response with zero usage followed by a reported retry, each fail with
    `UnmeteredCallError` at the first response, before summing; a chain
    whose every response reports usage passes with the sum; in
    `tests/model/providers/test_litellm_proxy.py`, a malformed-call attempt
    with no usage followed by a reported recovery fails, and one with usage
    on both passes; a final rejection after reported attempts passes; in
    `tests/model/providers/test_anthropic.py` over a stubbed client, under a
    cost limit, a `pause_turn` leg with zero usage followed by a positive
    leg fails at the zero leg, and a positive leg followed by a zero
    continuation fails at the continuation, both before summing; controls
    pass with the sum: two positive legs, a leg reporting only cache-read
    tokens, the zero-then-positive chain with no cost limit, and the same
    chain inside `suspend_cost_limit()`;
  - rejection during a Google continuation, streamed and not: a
    continuation leg reporting 42 tokens followed by a context-length 400
    returns a `model_length` output with usage 42 and the first request's
    input size; a complete malformed-call attempt, then a continuation leg,
    then the 400, returns the sum of all three completed responses; under a
    cost limit both are charged and do not fail.
    `test_continuation_failing_partway_fails_like_one_request` changes its
    converted-400 expectations from `usage is None` and
    `input_context_tokens is None` to the completed legs' usage and input
    size; its raised-failure cases are unchanged;
  - Grok streams, in `tests/model/providers/test_grok.py` with protobuf
    chunk fixtures (no RPC): a stream whose reported total of 5 is followed
    by a usage-less chunk converts to 5; a stream with no reported usage
    converts to zero usage and fails under a cost limit;
  - start-time pricing, in `tests/test_sample_limits.py`: an eval with a
    cost limit, a priced task model and an unpriced `monitor` role model
    starts, and the same task enqueued during an eval is accepted
    (`tests/test_enqueue_task.py`); a stub in-process monitor that calls the
    role model with cost suspended runs; a solver that calls the same role
    model, unsuspended, fails the sample with `UnmeteredCallError`; an
    unpriced task model still fails at start;
  - failed attempts and cancellation stay uncharged (pinned): an attempt
    that raises `AttemptTimeoutError` and one that streams a chunk and then
    raises are retried under a cost limit with no usage recorded; a
    generation cancelled in flight records nothing;
  - suspension: inside `suspend_cost_limit()`, a priced call neither
    charges nor is refused by a reached `cost_limit()`, including one
    opened inside the block.
- `tests/util/test_limit_turn.py`: `turn_limit(3)` makes three generations
  and refuses the fourth before dispatch; a cache hit at the limit is served
  and then raises; native compaction is refused at the limit and records no
  turn; under `turn_limit(1)`, a call that raises a child `token_limit(1)`
  (caught) counts one turn and the next call is refused by the turn limit;
  the same with a child `cost_limit()`.
- `tests/util/test_limit_token.py`: inside `suspend_limits()`, a call is not
  refused by a reached token, turn or cost limit, nor by a
  `dispatch_guard()`, and a reached message limit still refuses it; inside
  `suspend_token_limit()` alone the guard is skipped; inside
  `suspend_turn_limit()` alone and inside `suspend_cost_limit()` alone a
  `dispatch_guard()` still refuses the call (pinned, as today);
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
  returns `(state, None)`; a sample limit swallowed inside the agent
  propagates from `run()`; a synchronous deepagent subagent's swallowed
  limit is reported as its result;
  - an escaped error stands (pinned, synchronized by an `anyio.Event`):
    `run(limits=[cost_limit(1), token_limit(1)])` over `tg_collect()`, where
    one task raises the token limit first and a sibling's call, finishing in
    its cancellation cleanup with token metering suspended, pushes the cost
    limit over, returns the token limit; the same where the sibling pushes
    an enclosing `cost_limit()` over returns the token limit, and the
    caller's next model call is refused by the enclosing cost limit;
  - own limits outside the chain: `apply_limits([time_limit(...)],
    catch_errors=True)` and `run(limits=[time_limit(...)])` still catch and
    return their own time limit error, including one raised as the limits
    exit (the existing `test_apply_limits_handles_time_limit` stays);
- `tests/checkpoint/test_sample_runtime.py`: the payload is unchanged
  (no new keys); after a dump and normal restore of a token root that
  refused a call at exactly its budget, the next call is refused before
  dispatch.
- `tests/util/test_limit.py`, sentinel: a stub in-process monitor whose
  priced model call would exceed a reached sample cost limit is made and
  not charged to it.
- `tests/agent/test_agent_execute.py`, adapter replacement (pinned, as
  today): under outer `token_limit(1)` and `message_limit(1)`, an
  `as_solver()` agent with its own `message_limit(100)` that appends a
  message and then exceeds the token limit leaves with the outer message
  limit, its context the token error; with an outer message limit of 10
  the token error leaves unchanged.
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
  with `UnmeteredCallError`;
  - exit check after cleanup (each with the worker synchronized by an
    `anyio.Event`, never a sleep): a `background()` worker makes a priced
    call in its cancellation cleanup after `plan()` returns, exceeds the
    sample cost limit, catches the error and returns: the sample ends on the
    cost limit; the same with a cleanup call refused at exactly the budget;
    `plan()` raises an inner `cost_limit()` while a worker's cleanup call
    pushes the sample token limit over and is caught: the sample records the
    inner cost limit (pinned: an escaped limit stands); `plan()` raises a
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
    `UnmeteredCallError`, and a bridged response without usage does too;
  - a kept sample token limit reached exactly by a refused request, then a
    cancellation of the bridged agent before delivery and a normal return
    from the solver, ends the sample on the token limit;
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

0. **Prerequisite: cost suspension.** `suspend_cost_limit()` and
   `suspend_limits()` in `_limit.py`, with the behaviour stated under
   "Current behaviour", used by in-process sentinel dispatch, the sidecar
   result lookup, tool approval and tool review. The steps below assume it.
1. **The chain and one check.** `src/inspect_ai/util/_limit.py`:
   `_limit_chain`, `_outer`/`_in_chain`/`_raised`, push/pop, `_chain_depth`,
   `_rank`, `outermost_limit`, `first_or_outermost_limit`, `_outer_than`,
   `_check_marked`, `check_limits`, `record_model_call`,
   `_TurnLimit._check_self(raise_for_equal)`, `record_turn` recording only,
   the affine grammar and non-negative weights in `_compile_token_formula()`,
   with metering from the reduced coefficients.
   `src/inspect_ai/model/_model.py`: `record_and_check_model_usage(check=)`,
   the inner generation recording without a check, the outer frame's
   `record_turn()` then `check_limits()`, `_check_limits_before_dispatch`.
   Tests: `tests/util/test_limit*.py`, `tests/checkpoint/test_sample_runtime.py`
   (the checkpoint code is unchanged).
2. **Unmetered calls.** `_limit.py`: `UnmeteredCallError` and
   `require_reported_usage()`. `_model.py`: the unpriced check in
   `_check_limits_before_dispatch(model)` and the model passed by
   `generate()`'s and compaction's per-attempt calls;
   `require_reported_usage()` inside the generate attempt after
   `self.api.generate()` returns (skipping rejection outputs) and inside
   `_compact()`; `Model.should_retry()` returns `False` for
   `UnmeteredCallError`. `src/inspect_ai/model/_model_output.py`: the
   private `_rejection` attribute and `rejection_output()`. The rejection
   converters listed under "Unmetered calls": `openai_handle_bad_request()`
   in `_openai.py` for `APIStatusError` only, and each provider's converter
   in `src/inspect_ai/model/_providers/` that builds its output from an
   error response received before any output. Summed usage:
   `require_reported_usage()` per successful request in
   `_ContinuationChain.add()` (`src/inspect_ai/model/_providers/google.py`)
   and per attempt in `src/inspect_ai/model/_providers/litellm_proxy.py`,
   and per leg before `chain.add()` in
   `src/inspect_ai/model/_providers/anthropic.py`;
   Google's `handle_client_error()` outputs take `chain.usage` and
   `chain.input_context_tokens` in place of `attempts_usage` and
   `attempts_input_context_tokens`. `src/inspect_ai/model/_providers/grok.py`:
   the stream loop keeps the last raw chunk's reported usage and passes it
   to `_model_output_from_response()`.
   `src/inspect_ai/model/_util.py`: `resolve_model_costs()` checks the task
   model only, with the shared message helper.
   `src/inspect_ai/agent/_bridge/sandbox/service.py`: `UnmeteredCallError`
   fails the sample. Tests: `tests/util/test_limit_cost.py`,
   `tests/test_eval.py`, `tests/test_sample_limits.py`,
   `tests/test_enqueue_task.py`, `tests/agent/test_bridge_provider_errors.py`,
   `tests/model/providers/test_google.py`,
   `tests/model/providers/test_litellm_proxy.py`,
   `tests/model/providers/test_grok.py`,
   `tests/model/providers/test_anthropic.py`, and one rejection case per
   classified converter in that provider's existing test file under
   `tests/model/providers/` (mocked transport, no API key).
3. **Suspension.** `_limit.py`: `check_limits()` skips suspended cost
   nodes. The guard checks stay skipped while token limits are suspended,
   as today, and run under turn-only or cost-only suspension.
   Tests in `tests/util/test_limit_token.py`,
   `tests/util/test_limit_cost.py` and
   `tests/agent/test_bridge_provider_errors.py`.
4. **Owners and reductions.** `_limit.py`: `apply_limits()` covered exits
   and its exit check on a normal return.
   `src/inspect_ai/agent/_run.py`: the return after the block. `src/inspect_ai/_eval/task/run.py`: `first_or_outermost_limit`
   for the escaping group, and `check_limits(at_exit=True)` after the
   sample task group has joined when the solvers returned (skipped on a
   resume for scoring).
   `src/inspect_ai/model/_call_tools.py`: `decisive_tool_exception`,
   `decisive_sentinel_exception`. Tests: `run()` and sentinel tests in
   `tests/util/test_limit.py`, `tests/test_eval.py`,
   `tests/agent/test_agent_overflow_compaction.py`.
5. **Ownership in tools.** `_call_tools.py`: the call leaf and ownership test
   in `call_tool_task`, `agent_handoff` through `apply_limits(catch_errors=True)`.
   `src/inspect_ai/agent/_bridge/sandbox/host_tool.py`: `_raised` ownership,
   `keep_limit` for foreign limits. Tests: `tests/agent/test_agent_execute.py`,
   `tests/agent/test_agent_handoff.py`, `tests/tools/test_tools_bridge.py`.
6. **The bridge.** `src/inspect_ai/agent/_bridge/sandbox/service.py`: entry
   simplification, the host-tool entry refusal in `call_tool()`,
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

inspect_swarm adapts in its own repository, alongside step 2: its
`_SwarmTurnNode._check_self()` takes `raise_for_equal` ("What
inspect_swarm can delete or simplify").

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
  exit check. Spend stays bounded and the sample limit is not lost. An
  unmetered-call error swallowed there costs one uncounted call each time
  the handler calls again. Making each re-raise these errors would only
  make them arrive sooner.
- Routing `background()` work to the `run()` or runtime that started it.
  Default deepagent background children keep their sample-scoped lifetime
  and report to the sample; a runtime that needs their errors installs a
  background target (see "What a runtime can rely on").
