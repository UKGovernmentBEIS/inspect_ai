<!--
DRAFT / HELD — NOT posted. Proposed comment for issue #2286
(UKGovernmentBEIS/inspect_ai). Do not post without operator sign-off.
Target issue: https://github.com/UKGovernmentBEIS/inspect_ai/issues/2286
-->

We ran into the gap this issue describes and prototyped a fix — sharing in case it's
useful before we propose anything formally.

**The gap.** The eval log records the sandbox *recipe* (`EvalSpec.sandbox` — provider +
config path, `revision=None`), but never the runtime that recipe resolved to. Because
most sandbox recipes pin mutable tags (`:latest`), a tag silently repointed at a
different image leaves the log **byte-identical** across two genuinely different
environments. When a score moves, the log can't tell you whether the model or the
environment changed.

This isn't marginal for agentic evals. WAREX ([arXiv:2510.03285](https://arxiv.org/abs/2510.03285))
reports 70%+ agent-success swings from environment variance; Sober Look
([arXiv:2504.07086](https://arxiv.org/abs/2504.07086)) and EleutherAI lm-eval
([#3357](https://github.com/EleutherAI/lm-evaluation-harness/issues/3357)) point the
same direction.

**Prototype.** A small auto-on (opt-out) `Hooks` subclass probes each live sandbox at
`SampleStart` and records a typed `sandbox_fingerprint` per environment — resolved image
id/digest, OS, kernel, package versions, network profile. Stable public API only
(`sandbox().connection()` + `docker inspect` host-side; `sandbox().exec()` in-container);
it degrades gracefully on non-docker providers and never fails an eval. We validated it
across several sandboxed evals (including `class_eval` and the OSWorld base image) and
have a regression test that drives a mutable tag at two different images and confirms the
recipe stays identical while the fingerprint diverges.

Before we put up a PR: would the maintainers be open to capturing resolved sandbox
runtime in the log this way, and is an auto-on hook with an opt-out env var the shape
you'd want — or would you prefer it gated/off by default? Happy to align on the field
schema and the extension seam for per-port signals.
