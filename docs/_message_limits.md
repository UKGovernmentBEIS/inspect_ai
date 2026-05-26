Message limits enforce a limit on the number of messages in any conversation (e.g. a `TaskState`, `AgentState`, or any input to `generate()`).

Message limits are checked:

* Whenever you call `generate()` on any model. A `LimitExceededError` will be raised if the number of messages passed in `input` parameter to `generate()` is equal to or exceeds the limit. This is to avoid proceeding to another (wasteful) generate call if we're already at the limit.

* Whenever `TaskState.messages` or `AgentState.messages` is mutated, but a `LimitExceededError` is only raised if the count exceeds the limit.

If `message_limit` is unset, Inspect does not impose a default cap. It will warn once when an unbounded conversation reaches 1,000 messages so that runaway loops are easier to notice before they continue consuming model calls.
