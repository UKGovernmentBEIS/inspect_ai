A "turn" is a single model generation (one call to the model that produces an assistant message). Turn limits are distinct from message limits, which count *all* messages in the conversation (user, assistant, and tool messages). One turn often results in several messages (e.g. an assistant message plus the tool messages from its tool calls).

A turn is recorded once per top-level `generate()` call (after retries and fallbacks have resolved, and including cache hits). Generations made via `model.compact()` do not count as turns. Turn limits are checked whenever a turn is recorded.
