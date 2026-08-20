# Evaluating structured data contracts

When an evaluation checks an agent that produces structured data, keep contract validity separate from task quality. A result can be valid JSON while still omitting required facts, and a semantically strong answer can fail because a downstream consumer cannot parse it.

A useful evaluation record includes the input case, the expected contract version, the raw model response, the parsed value, validation errors, and the semantic rubric result. Store the raw response for debugging, but redact credentials and personal data before publishing artifacts.

## Recommended failure categories

Classify failures as transport, parsing, schema, semantic, policy, or evaluator disagreement. This prevents a single aggregate score from hiding whether the model, tool, or harness needs attention.
