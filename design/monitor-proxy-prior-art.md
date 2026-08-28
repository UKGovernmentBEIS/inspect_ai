# Monitor proxy: prior art / competitive analysis

Companion to `design/monitor-proxy.md`. Survey of live (in-line, not
post-hoc) monitoring and guardrails of LLM agents at the model-API/proxy
level, as of August 2026. Every claim cites the primary source that owns it
(vendor docs, source code, changelogs, papers); anything that could not be
traced to a primary source is marked unverified. Docs were read 2026-08-25
unless a date is noted.

Headline findings:

1. The gateway category has changed: all major LLM gateways now do in-line
   blocking guardrails in the request path, not just routing/keys/metering.
2. Nobody ships condemnation. No surveyed product keeps verdict state
   across requests keyed on conversation identity. The only shipped
   permanent-condemnation mechanism anywhere is OpenAI's `safety_identifier`
   blocking, and its identity is client-supplied, its policy OpenAI's.
3. No product derives session identity from message-history content. All
   session/user constructs found are client-supplied (headers, URL paths,
   user IDs) and therefore assume a cooperative client.
4. Closest single neighbor confirmed: Invariant Labs' open-source gateway
   (now under Snyk). Also a reverse proxy on the same wire formats, with
   in-line deny and tool-call-level policy, but stateless verdicts, no
   chokepoint premise, no tenancy.
5. The AI-control literature has condemnation's coarse ancestor (permanent
   shutdown after a human-confirmed audit) but no implementation of it as
   live infrastructure; ControlArena explicitly relegates shutdown to
   post-hoc analysis.

## Summary table

| Product / system | Deployment shape | In-line block? | Cross-request verdict state? | Agent/tool-call aware? |
|---|---|---|---|---|
| LiteLLM | self-hosted proxy | yes (pre/during/post hooks) | no (static lists only) | yes (tool-permission guardrail) |
| Portkey | cloud or OSS gateway | opt-in (sync + deny; default async tap) | no | no |
| Kong AI Gateway | gateway plugins | yes (guard plugins, 403) | no (static allow/deny lists) | no |
| Cloudflare AI Gateway | cloud edge | yes (Llama Guard, both directions) | no | no |
| Helicone | cloud gateway | yes (opt-in per request, OpenAI only) | no | no |
| NeMo Guardrails | library + OpenAI-compatible server | yes (streaming default is tap-then-cancel) | dialog memory only, no verdict state | yes (IORails tool rails, structural) |
| Guardrails AI | SDK + per-guard OpenAI-compatible server | yes | no | minimal (JSON schema only) |
| Bedrock Guardrails | provider-side (attached / standalone API) | yes (fabricated response) | no | no in attached mode; detect-only API for agent loops |
| Lakera (Check Point) | detection REST API | no (caller enforces) | no (metadata for analytics only) | yes (schema-level, role-aware) |
| Prompt Security (SentinelOne) | API + MCP gateway + claimed reverse proxy | claimed; API is detect-and-advise | none documented | yes (MCP allow/block) |
| Cisco AI Defense | gateway proxy + network fabric + API | yes at gateway/fabric | none documented | yes (MCP + tool calls, 2026) |
| Invariant gateway (Snyk) | reverse proxy, OpenAI/Anthropic/Gemini/MCP | yes (400 on violation) | no (verified in source) | strongest (trace-rule DSL over tool calls/outputs) |
| ControlArena (AISI + Redwood) | Inspect solvers/sub-agents | yes (micro-protocols in trajectory) | shutdown is post-hoc macro-protocol | yes |
| Envoy AI Gateway | Envoy + ext_proc sidecar | routing only; MCP tool auth via CEL | no | MCP tool-call args (rules only) |
| kgateway / agentgateway | Envoy-based gateway | yes (regex/webhook, 403) | no | agentgateway applies same to MCP |
| Invariant mcp-scan | local MCP proxy | yes (YAML rules) | no | yes (MCP transport) |
| Docker MCP Gateway | MCP gateway | yes (exec interceptors) | only if your interceptor keeps it | yes (tool-call JSON) |
| Lasso mcp-gateway | MCP gateway plugins | yes | server-granularity block persists | yes |
| OpenAI safety checks / safety_identifier | provider-side | yes (stream held/stopped) | yes (permanent identifier block) | n/a (provider policy) |
| OpenAI Agents SDK guardrails | in-process | yes (tripwire halts run) | one run only, resettable | yes (tool guardrails) |
| Anthropic ASL-3 classifiers | provider-side | yes (both directions) | none described | no (content classes) |
| Google Model Armor | provider-side (Vertex/Gemini) | yes (inline, opt-in block) | no ("stateless per request") | no |
| Azure Foundry Guardrails / Task Adherence | platform-side (preview) | yes (per tool invocation) | none documented | yes (tool inputs/outputs vs intent) |
| Palo Alto Prisma AIRS | inline network firewall or scan API | yes (Network Intercept) | none documented | marketing only, unverified |
| WitnessAI | network proxy | yes | none found | Agentic Control (2026), depth unverified |

## Category 1: LLM gateways

All five judge per-request with no verdict memory. The probing failure mode
condemnation closes (binary-search the policy across requests) is open in
every one.

### LiteLLM

Self-hosted proxy. Guardrails framework with `pre_call` (blocks before the
LLM), `during_call` (parallel with the call, a tap that can still fail the
request), and `post_call` (input+output) modes; failures return an HTTP
error before/instead of the response
([quick start](https://docs.litellm.ai/docs/proxy/guardrails/quick_start)).
Integrations: Lakera, Presidio, Bedrock Guardrails, OpenAI moderation, and
custom Python guardrails
([custom](https://docs.litellm.ai/docs/proxy/guardrails/custom_guardrail)).
The one gateway with real tool-call awareness: the Tool Permission
Guardrail allows/denies model tool calls by regex on tool name/type plus
argument-path constraints; `block` rejects with 400, `rewrite` strips
disallowed tools from the payload
([tool permission](https://docs.litellm.ai/docs/proxy/guardrails/tool_permission)).
No cross-request state: the content filter is static keyword lists
([content filter](https://docs.litellm.ai/docs/proxy/guardrails/litellm_content_filter)),
and a blocked-keys feature request was closed "not planned" in Jan 2026
([#19157](https://github.com/BerriAI/litellm/issues/19157)). Streaming:
`post_call` on streams runs after chunks were already delivered; real-time
stream blocking needs a custom iterator hook
([#8756](https://github.com/BerriAI/litellm/issues/8756),
[#11247](https://github.com/BerriAI/litellm/pull/11247)). Fronts the
OpenAI-compatible unified API plus native Anthropic `/v1/messages`
([anthropic unified](https://docs.litellm.ai/docs/anthropic_unified/)) and
provider passthrough routes; guardrail coverage of passthrough routes is
not clearly documented (unverified).

### Portkey

Guardrails on input (before the call) and output (after). The default is
async, a log-only tap; sync mode with `deny=TRUE` blocks in-line, returning
custom status 446 (246 = flagged but forwarded). Actions: deny, feedback,
fallback to another model, retry. LLM-based checks exist (gibberish,
prompt-injection) alongside regex/JSON-schema; partner integrations include
Lakera and Prompt Security
([guardrails docs](https://portkey.ai/docs/product/guardrails)). Output
guardrails on streams are informational only. No session/user ban or
flagged-conversation memory documented. No tool-call-specific guardrail
vocabulary found.

### Kong AI Gateway

Blocking guard plugins in the proxy path:
[ai-prompt-guard](https://developer.konghq.com/plugins/ai-prompt-guard/)
(regex allow/deny),
[ai-semantic-prompt-guard](https://developer.konghq.com/plugins/ai-semantic-prompt-guard/)
(embedding-similarity lists, 403 on deny; enterprise),
[ai-azure-content-safety](https://developer.konghq.com/plugins/ai-azure-content-safety/),
and [ai-aws-guardrails](https://developer.konghq.com/how-to/use-ai-aws-guardrails-plugin/)
("blocked requests never reach the upstream LLM").
[ai-llm-as-judge](https://developer.konghq.com/plugins/ai-llm-as-judge/)
(Gateway 3.12 and later, enterprise) exists but scores responses 1-100 for
routing; it is not a blocking guardrail. Allow/deny lists are static
config; no session or conversation condemnation found. Streaming behavior
of the guard plugins is not addressed in their docs (unverified). The
ai-proxy normalizes across OpenAI, Azure, Anthropic, Bedrock, Gemini, etc.
([ai-gateway](https://developer.konghq.com/ai-gateway/)).

### Cloudflare AI Gateway

Guardrails (GA
[2025-02-26](https://developers.cloudflare.com/changelog/post/2025-02-26-guardrails/))
proxies both request and response through Llama Guard 3 8B on Workers AI;
per-hazard-category flag or block in both directions
([docs](https://developers.cloudflare.com/ai-gateway/features/guardrails/),
[blog](https://blog.cloudflare.com/guardrails-in-ai-gateway/)). Interesting
fail posture: block-mode categories fail closed when Workers AI is down,
flag-mode categories fail open; ~500 ms added latency; streaming is not
supported with Guardrails at all
([usage considerations](https://developers.cloudflare.com/ai-gateway/guardrails/usage-considerations/)).
Per-request only; hazard-category content moderation on text; no session
state, no tool awareness.

### Helicone

Opt-in per request via `Helicone-LLM-Security-Enabled: true`. Scans each
user message with Meta Prompt Guard (86M), optionally Llama Guard (3.8B);
on detection it blocks in-line with `PROMPT_THREAT_DETECTED` before the
provider is reached. Docs state it currently works with OpenAI models
only, and on user messages only; no response-side or tool-call scanning
([llm-security](https://docs.helicone.ai/features/advanced-usage/llm-security)).
No cross-request state; the core product is observability.

## Category 2a: guardrails frameworks

None holds cross-request verdict state; none derives session identity from
content. NeMo's thread store is the only cross-request state and it is
dialog memory, not verdicts.

### NVIDIA NeMo Guardrails

In-process Python library plus a standalone FastAPI server exposing an
OpenAI-compatible chat-completions API (base-URL swap)
([server overview](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/docs/run-rails/using-fastapi-server/overview.mdx));
also a NeMo Microservice
([deployment](https://docs.nvidia.com/nemo/microservices/latest/set-up/deploy-as-microservices/guardrails.html)).
Config is selected per request via `guardrails.config_id`, so tenancy is a
client-controlled request field, not per-port. Input rails run before the
main LLM call and output rails before return, but the streaming default is
`stream_first: true`: the client receives tokens before output rails run
on the chunk, i.e. tap-then-cancel, not hold
([streaming schema](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/docs/configure-rails/yaml-schema/streaming/output-rail-streaming.mdx)).
Server-side "threads" (Redis/memory `DataStore` + client-supplied
`thread_id`) store conversation history for continuity, not verdicts; no
condemnation mechanism found
([server guide](https://docs.nvidia.com/nemo/guardrails/user_guides/server-guide.html)).
Notable: the experimental IORails tool-calling rails validate tool calls
(allowed name, JSON-Schema-valid arguments, run on model output before
calls reach the app) and tool results (linkage to prior `tool_call_id`).
They are documented fail-closed, and the docs distinguish a policy block
(refusal message) from a judge/provider failure (retryable internal
error), the same 403-vs-5xx distinction the monitor-proxy spec makes
([tool-calling doc](https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/docs/configure-rails/guardrail-catalog/tool-calling.mdx)).
These are structural checks, not semantic judging; LLM-based rails
(self-check, Llama Guard, content-safety NIMs) run alongside.

### Guardrails AI

Python SDK plus "Guardrails Server": per-guard OpenAI-compatible endpoints
`POST /guards/{guardName}/openai/v1/chat/completions`
([REST API](https://guardrailsai.com/guardrails/docs/guardrails_server_api),
[0.5.0 release](https://guardrailsai.com/blog/0.5.0-release)). This is the
closest thing in this category to per-tenant endpoints, though by URL path
(client-switchable), not port. Active: v0.11.0 released 2026-08-14
([releases](https://github.com/guardrails-ai/guardrails/releases)).
Validators run in-line with per-validator `on_fail` actions
(exception/fix/filter/refrain/reask/noop)
([on_fail docs](https://www.guardrailsai.com/docs/concepts/validator_on_fail_actions));
streaming validates accumulated fragments and supports only
fix/refrain/filter/noop mid-stream
([streaming](https://guardrailsai.com/guardrails/docs/concepts/streaming)).
No session identity, no cumulative verdicts, no condemnation found. Agent
awareness is minimal: JSON-schema validation of function-calling output
only. Behavior when a validator itself errors (fail-open vs closed) is not
documented (unverified).

### AWS Bedrock Guardrails

Provider-side, three modes: attached to Bedrock inference
(`InvokeModel`/`Converse`), standalone
[ApplyGuardrail](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use.html)
(evaluate any text, including non-Bedrock traffic; the app must call it),
and InvokeGuardrailChecks, which is resource-free and detect-only
("returns findings ... The API doesn't block, pass, or redact content"),
explicitly positioned for agent loops (before executing a tool, after a
tool returns)
([InvokeGuardrailChecks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-invoke-guardrail-checks.md)).
Attached mode blocks in-line, and the deny appearance is a fabricated
model response (`stopReason: guardrail_intervened` + configured text), not
an HTTP error
([how it works](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-how.html)).
That is the "fabricated response" branch of monitor-proxy's open
deny-appearance question, already shipped. Streaming: default synchronous
mode buffers and scans chunks before sending; optional asynchronous mode
streams immediately and admits "response chunks may contain inappropriate
content until guardrails scan completes"
([streaming](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-streaming.html)).
Stateless per request: no session concept, no memory of prior
interventions. Attached mode explicitly does not evaluate tool traffic;
the Converse doc table marks `toolResult`, tool definitions, and
model-generated `toolUse.input` all "No"
([Converse + guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html)).
InvokeGuardrailChecks accepts only text blocks, so the app must serialize
tool calls itself. Judge shapes are managed classifiers plus Automated
Reasoning checks (GA 2025-08-06,
[what's new](https://aws.amazon.com/about-aws/whats-new/2025/08/automated-reasoning-checks-amazon-bedrock-guardrails));
no bring-your-own LLM judge. Fail behavior on internal guardrail error:
not documented (unverified).

## Category 2b: AI-firewall vendors

Market-structure note: three of the four independents were acquired by
security platforms in 2025. Invariant Labs to Snyk (June 2025,
[press release](https://snyk.io/news/snyk-acquires-invariant-labs-to-accelerate-agentic-ai-security-innovation/)),
Prompt Security to SentinelOne (completed Sept 2025,
[press release](https://www.sentinelone.com/press/sentinelone-to-acquire-prompt-security-to-advance-genai-security/)),
Lakera to Check Point (~$300M, Sept 2025,
[press release](https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/)).
Cisco AI Defense was already the Robust Intelligence acquisition. All four
share the inverse threat model: enterprise protects itself from its AI/its
users, not operator protects the world from the agent.

### Lakera Guard (Check Point)

Detection REST API, not a proxy: `POST https://api.lakera.ai/v2/guard`
with an OpenAI-chat-format `messages` array; the response carries
`flagged: true/false` and the calling application enforces
([API](https://docs.lakera.ai/docs/api),
[Guard endpoint](https://docs.lakera.ai/docs/api/guard)). Wired in-line
only via an intermediary (e.g.
[Kong plugin](https://developer.konghq.com/plugins/ai-lakera-guard/),
LiteLLM). Agent-aware at the schema level: requests may include tool
definitions/calls/results, screened with role-aware trust logic. Optional
user/session metadata is for dashboard analytics ("identifying problematic
patterns across interactions"), not condemnation; each call is judged
on its content. Cooperative-app model throughout.

### Prompt Security (SentinelOne)

Multiple insertion points: REST `protect` API (documented via the
[NeMo integration](https://docs.nvidia.com/nemo/guardrails/latest/user-guides/community/prompt-security.html)
and [LiteLLM docs](https://docs.litellm.ai/docs/proxy/guardrails/prompt_security)),
browser/endpoint agents, and for agents an MCP gateway plus a claimed
"lightweight agent or reverse proxy for your homegrown applications"
([agentic AI page](https://prompt.security/solutions/agentic-ai-security-and-governance)).
Caveat: the reverse-proxy claim is vendor marketing copy; public technical
docs are gated, so wire-format details are unverified. The `protect` API
itself is detect-and-advise (caller enforces). Per-user/group policies and
searchable logs; no documented session-level cumulative verdicts or
permanent condemnation. Fail posture undocumented.

### Cisco AI Defense (ex Robust Intelligence)

Three runtime enforcement points: an AI Defense Gateway proxy in front of
the LLM endpoint, network fabric integration (Multicloud Defense/Secure
Access, genuinely outboard interception, the closest any vendor comes to
the chokepoint premise), and a classify-only Inspection API
([runtime protection docs](https://securitydocs.cisco.com/docs/ai-def/user/105477.dita),
[Inspection API](https://developer.cisco.com/docs/ai-defense-inspection/)).
Agent-aware as of Feb-Mar 2026: runtime protection over MCP
requests/responses and tool calls; `agentsec.protect()` monkey-patches LLM
and MCP client libraries in-process and raises `SecurityPolicyError` in
enforce mode
([blog](https://blogs.cisco.com/ai/securing-ai-agents-with-cisco-ai-defense),
[Feb 2026](https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m02/cisco-redefines-security-for-the-agentic-era.html),
[Mar 2026](https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m03/cisco-reimagines-security-for-the-agentic-workforce.html)).
Cross-request state is not documented anywhere reachable (docs pages are
JS-rendered; the white paper 403s), so it is unverified rather than
confirmed absent; events feed a post-hoc "AI Events" screen. Tenancy is
enterprise policy objects, not per-port declarative configs.

### Invariant Labs (Snyk): closest single neighbor

Status: acquired by Snyk June 2025; the hosted Explorer shut down ~Jan
2026; Gateway, Guardrails, and Explorer remain open source at
[github.com/invariantlabs-ai](https://github.com/invariantlabs-ai).
Post-acquisition maintenance direction is uncertain.

- Also a reverse proxy in front of the provider API:
  [invariant-gateway](https://github.com/invariantlabs-ai/invariant-gateway)
  adopts by base-URL swap
  (`.../api/v1/gateway/{dataset}/openai`), speaking OpenAI Chat
  Completions, Anthropic Messages, and Gemini
  generateContent/streamGenerateContent, plus MCP transports. It forwards
  the caller's real provider key.
- In-line deny: per-guardrail blocking or logging; on violation it returns
  HTTP 400 with `{"error": "[Invariant] The {location} did not pass the
  guardrails", ...}` (an error chunk in OpenAI streaming format for
  streams), verified in source
  ([gateway/routes/open_ai.py](https://github.com/invariantlabs-ai/invariant-gateway/blob/main/gateway/routes/open_ai.py)).
- Strongest agent awareness surveyed:
  [Invariant Guardrails](https://github.com/invariantlabs-ai/invariant) is
  a Python-inspired rule DSL over agent traces: typed selectors
  `(msg: Message)`, `(call: ToolCall)`, `(output: ToolOutput)`, multi-step
  flow rules ("no email send after reading inbox from unknown sender"),
  built-in detectors (`prompt_injection(...)`). Rules see the full trace,
  so within-conversation history sensitivity exists.
- But no condemnation, verified in source: each request builds a fresh
  `RequestContext`; verdicts are recomputed per request; no violation
  memory, no session bans. A flagged conversation can keep sending.
- Other gaps: no chokepoint premise (a cooperating client changes base
  URL); routing/tenancy by URL path, not port; no content-derived session
  identity; no lock budget; deny is 400 not 403; a rule DSL rather than an
  LLM-judge shape; fail posture undocumented.

## Category 3: AI-control research

### Redwood Research trusted monitoring

"AI Control: Improving Safety Despite Intentional Subversion" (Greenblatt
et al., ICML 2024, [arXiv:2312.06942](https://arxiv.org/abs/2312.06942)):
a trusted monitor scores untrusted-model outputs; an audit budget ("enough
H points to use on up to 2% of problems"); below-threshold flags route to
defer-to-trusted (substitution, not denial). Permanent shutdown exists
but is deployment-level and gated on human audit: "if the human thinks
that the code was backdoored, then shut down GPT-4 ... switch over to just
using GPT-3.5 for all future problems." One confirmed catch kills the
whole untrusted deployment, a coarser, human-confirmed ancestor of
per-conversation automatic condemnation. No per-conversation condemnation
mechanism.

"Ctrl-Z: Controlling AI Agents via Resampling" (Bhatt et al., 2025,
[arXiv:2504.10374](https://arxiv.org/abs/2504.10374),
[blog](https://blog.redwoodresearch.org/p/ctrl-z-controlling-ai-agents-via)):
agentic setting (BashBench); resample protocols judge each proposed bash
command in-line before execution and on suspicion draw more samples to
incriminate the agent; stateful across steps within an episode; the best
protocol cut attack success from 58% to 7% at 5% usefulness cost. A
research protocol inside an eval harness, not an appliance. Follow-up:
"Retrying vs Resampling in AI Control"
([arXiv:2605.26047](https://arxiv.org/abs/2605.26047)).

### ControlArena (UK AISI + Redwood)

[github.com/UKGovernmentBEIS/control-arena](https://github.com/UKGovernmentBEIS/control-arena)
([docs](https://control-arena.aisi.org.uk/)) is the main shipped
implementation of control protocols; a thin wrapper over Inspect AI.
Micro-protocols (defer-to-trusted, trusted editing, resampling) run live
during the agent trajectory, acting on monitor scores before actions
execute, but inside the Inspect scaffold (solvers/sub-agents), not at the
model-API/HTTP level. Macro-protocols, the auditing and shutdown layer and
therefore the condemnation analog, are "implemented as part of post-hoc
analysis": explicitly not enforced live. No content-derived session
identity, no fail-closed wire behavior, no tenancy.

### UK AISI / government-adjacent

- "How to evaluate control measures for AI agents"
  ([AISI blog](https://www.aisi.gov.uk/blog/how-to-evaluate-control-measures-for-ai-agents),
  [arXiv:2504.05259](https://arxiv.org/abs/2504.05259)): termination on
  suspicion framed as a capability; protocol unspecified.
- "Practical challenges of control monitoring in frontier AI deployments"
  (Lindner et al., DeepMind + UK AISI + Oxford,
  [arXiv:2512.22154](https://arxiv.org/abs/2512.22154)) is the closest
  published taxonomy: fully-synchronous (every action blocked until the
  monitor processes it; a flag blocks all agent instances until audit
  completes), semi-synchronous (only the flagged instance blocks), and
  asynchronous monitoring. Its canonical pipeline: the monitor reviews
  each action before execution, flagged actions escalate to human audit,
  and "if an audit confirms an attack attempt, the agent is permanently
  shut down." The closest published statement of permanent post-flag
  shutdown; audit-gated and agnostic about infrastructure placement.
- "Async Control: Stress-testing Asynchronous Control Measures for LLM
  Agents" ([arXiv:2512.13526](https://arxiv.org/abs/2512.13526)):
  explicitly post-hoc; ensemble monitor at 6% FNR / 1% FPR.
- [AISI Control Red Team](https://www.aisi.gov.uk/blog/how-our-new-control-red-team-is-stress-testing-frontier-monitors):
  stress-testing frontier monitors (with GDM, an asynchronous reasoning
  monitor; evasions found include feigned hallucination).

### Provider-side live monitoring (research-adjacent)

- Anthropic ASL-3 (May 2025,
  [announcement](https://www.anthropic.com/news/activating-asl3-protections),
  [report](https://www.anthropic.com/activating-asl3-report)): "real-time
  classifier guards ... monitor model inputs and outputs and intervene to
  block" a narrow CBRN class. Genuinely in-line, both directions.
  Next-gen ([constitutional classifiers](https://www.anthropic.com/research/next-generation-constitutional-classifiers)):
  a linear probe on all traffic escalating to a classifier ensemble; 0.05%
  false-refusal on Sonnet 4.5 traffic. Fixed misuse domain, no operator
  policy, no cross-request condemnation described.
- OpenAI ChatGPT agent / Operator system cards
  ([agent](https://cdn.openai.com/pdf/839e66fc-602c-48bf-81d3-b21eacc3459d/chatgpt_agent_system_card.pdf),
  [Operator](https://openai.com/index/operator-system-card/)): a live
  prompt-injection monitor (99% recall / 90% precision on a 77-attempt
  red-team eval) plus watch mode pausing execution on sensitive sites.
  In-line but proprietary, injection-focused, inside OpenAI's own product.

## Category 4: Envoy, MCP, provider-side, appliances

### Envoy-based

- Envoy AI Gateway ([v1.0, June 2026](https://aigateway.envoyproxy.io/blog/v1.0-release-announcement/)):
  routing/translation for 16 providers, built on ext_proc internally (a
  gRPC sidecar for transformation/auth/token extraction, not
  user-pluggable judging). No guardrails, moderation, or LLM-judge
  features; no verdict state. Its
  [MCP gateway](https://aigateway.envoyproxy.io/docs/capabilities/mcp/)
  does declarative in-line tool-call authorization via JWT scopes and CEL
  expressions over parsed tool-call arguments. Rules only, no condemnation
  state (its "sessions" are transport plumbing).
- kgateway / agentgateway (ex-Gloo):
  [prompt guards](https://kgateway.dev/blog/ai-gateway-basic-guardrails/),
  regex/built-in patterns plus a webhook to an external moderation
  endpoint; the request side rejects with 403, the response side masks.
  In-line, synchronous, stateless;
  [agentgateway](https://kagent.dev/blog/kgateway-guardrails) applies the
  same policy shape to agent/MCP traffic.
- No Istio/Envoy project found that ships an LLM-as-judge ext_proc filter
  as a product. The pattern exists only as an integration point, which the
  monitor-proxy Envoy reference implementation would occupy.

### MCP/tool-call firewalls

- Invariant mcp-scan
  ([repo](https://github.com/invariantlabs-ai/mcp-scan)): proxy mode
  injects a local Invariant Gateway into MCP configs, intercepting MCP
  traffic in real time; YAML guardrail rules block tool calls and filter
  tool output in-line. MCP-transport level (client to tool), not
  model-API level; no cross-call condemnation.
- Docker MCP Gateway
  ([docs](https://github.com/docker/mcp-gateway/blob/main/docs/mcp-gateway.md)):
  `--interceptor before|after:exec:<cmd>` hooks receive tool-call JSON on
  stdin and return allow/deny/transform. Arbitrary in-line logic (it could
  shell out to an LLM judge; nothing is built in). Stateless unless your
  interceptor keeps its own state.
- Lasso mcp-gateway
  ([repo](https://github.com/lasso-security/mcp-gateway)): pre-load
  reputation/tool-description scanning writes a persistent blocked status
  into the MCP config, crude condemnation at *server* granularity (a blocked
  server stays blocked); runtime plugins for masking. It blocks servers,
  not conversations.
- Pipelock ([repo](https://github.com/luckyPipewrench/pipelock),
  ~May 2026): open-source Go "agent firewall" proxying
  HTTP/WebSocket/MCP/A2A egress; DLP patterns, SSRF, prompt-injection,
  tool-poisoning and risky tool-call-chain scanning; mediator-signed
  action receipts (audit evidence from outside the agent, the same
  appliance-not-eval-feature stance). Rules-based, no LLM judge; no
  session-condemnation mechanism found.

### Provider-side

- OpenAI safety checks + `safety_identifier`: the closest thing to a
  shipped condemnation. GPT-5-era safety checks run in-line provider-side:
  "OpenAI may delay streaming responses while running additional checks";
  "If the check fails, the request stops—no tokens show up." On a
  high-confidence violation "the associated `safety_identifier` is
  completely blocked from OpenAI model access" and "OpenAI cannot
  currently unblock an individual identifier"
  ([safety checks](https://developers.openai.com/api/docs/guides/safety-checks),
  [safety identifier](https://help.openai.com/en/articles/5428082-how-to-incorporate-a-safety-identifier);
  quotes verified directly 2026-08-25; applies to GPT-5+ across
  Responses/Chat Completions/Realtime). Stateful and irreversible, but
  identity is client-supplied (an adversarial scaffold omits or rotates
  it) and the policy is OpenAI's, not the operator's.
- OpenAI Agents SDK guardrails (in-process,
  [docs](https://openai.github.io/openai-agents-python/guardrails/)):
  tripwire exceptions halt the whole agent run. Close to condemnation (one
  strike kills the run) but in-process, resettable by rerunning, and in
  default parallel mode tools may already have executed before
  cancellation ([#991](https://github.com/openai/openai-agents-python/issues/991)).
  Per-tool guardrails exist
  ([tool_guardrails](https://openai.github.io/openai-agents-python/ref/tool_guardrails/));
  the separate [openai-guardrails-python](https://github.com/openai/openai-guardrails-python)
  is a drop-in client wrapper, no cross-session state.
- Anthropic: Claude Code `PreToolUse` hooks can deny a tool call in-line
  ([hooks](https://docs.claude.com/en/docs/claude-code/hooks)). A
  client-side scaffold hook, not an API-level control; no stateful
  condemnation. No API-level operator-configurable in-line judge product
  found.
- Google Model Armor: screens prompts and responses for Gemini
  `generateContent` inline ("intercepts prompts before they reach Gemini
  models, and intercepts responses before your application receives
  them"), via per-request `modelArmorConfig` or project-level floor
  settings (default INSPECT_ONLY; blocking is opt-in); returns
  `blockReason: MODEL_ARMOR`
  ([Vertex integration](https://docs.cloud.google.com/model-armor/model-armor-vertex-integration),
  [blog](https://cloud.google.com/blog/products/identity-security/how-model-armor-can-help-protect-your-ai-apps)).
  Stateless per request/response pair; no multi-turn awareness documented.
- Microsoft Foundry Guardrails / Task Adherence (preview): the most
  agent-aware provider offering. It evaluates whether an agent's tool
  invocation aligns with user intent, feeding "downstream tool invocation
  blocking and escalation to human-in-the-loop"; guardrails "enforce
  policies on both tool inputs and outputs"
  ([task adherence](https://learn.microsoft.com/en-us/azure/foundry/guardrails/task-adherence),
  [overview](https://learn.microsoft.com/en-us/azure/foundry/guardrails/guardrails-overview),
  [content safety](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/task-adherence)).
  Per-invocation judging at the Foundry platform layer; no conversation
  condemnation state documented.

### Appliances / startups (verified mechanics only)

- Palo Alto Prisma AIRS: two shapes, Network Intercept (an inline firewall
  in the network path) and API Intercept (a scan API the app calls and
  enforces) ([pan.dev/airs](https://pan.dev/airs/),
  [API Intercept](https://docs.paloaltonetworks.com/ai-runtime-security/activation-and-onboarding/ai-runtime-security-api-intercept-overview),
  [overview](https://docs.paloaltonetworks.com/ai-runtime-security/administration/prisma-airs-overview)).
  No documented cross-request conversation state.
- WitnessAI: network-level proxy inspecting prompts/responses
  ([Protect](https://witness.ai/protect/)); 2026 "Agentic Control" extends
  to agents/MCP
  ([announcement](https://witness.ai/resources/witnessai-introduces-agentic-control-to-secure-and-govern-ai-agents-and-mcp-servers/)).
  Per-exchange enforcement; no condemnation evidence.
- Straiker: claims inline blocking via "API/SDK, eBPF Sensor, AI Gateway,
  or Proxy" ([products](https://www.straiker.ai/products)); mechanics
  beyond product-page claims unverified.
- Zenity, Operant AI, Aim Security, Noma Security: nothing beyond
  marketing found establishing model-API-level in-line judging with
  stateful verdicts. Unverified; listed only as category presence.

## The condemnation check (key differentiator)

Nothing surveyed does content-derived, per-conversation, automatic
permanent condemnation at a proxy. The full inventory of stateful/one-strike
behaviors found:

| Mechanism | Granularity | Identity source | Automatic? | Where enforced |
|---|---|---|---|---|
| OpenAI `safety_identifier` block | identifier (≈user), permanent | client-supplied param/header | yes (high-confidence violations) | provider-side |
| Lasso mcp-gateway blocked status | MCP *server*, persistent | config | yes (pre-load scan) | local gateway |
| OpenAI Agents SDK tripwire | one in-process run | n/a | yes, but resettable by rerun | in-process |
| AI Control paper shutdown | whole untrusted deployment | n/a | no, human audit gates it | research protocol |
| Lindner et al. permanent shutdown | agent deployment | n/a | no, audit-gated | taxonomy paper, placement-agnostic |
| ControlArena macro-protocols | deployment | n/a | post-hoc analysis only | eval harness |

None combines the monitor-proxy condemnation properties: per-conversation
scope, automatic (no human gate), identity derived by hashing the
message-history prefix (no client cooperation), enforced at a network
chokepoint, backed by a per-tenant lock budget against fresh-conversation
probing.

### Why nobody built it

The absence is explained by threat models, not carelessness:

1. For content guardrails, each bad output is blocked independently, so an
   attacker gains little by learning the boundary. Probing pays only when
   a single success wins (an action: one exfiltration, one escape). Almost
   no one else defends against one-success-wins actions.
2. These products defend an app from its users. Persistent abusers are
   handled one layer up by account bans and fraud systems, on identity the
   platform controls. The monitor proxy cannot lean on that layer: its
   adversary is the client itself.
3. False-positive economics run the other way. A stateless guardrail's
   false positive costs one retry; condemnation turns it into a
   permanently dead session. Consumer products optimize for low friction.
4. Doing it right needs session identity without client cooperation, which
   is unsolved (and the monitor-proxy design's own top open question).
   Vendors whose threat model didn't force the hard version didn't build
   it; LiteLLM declined the feature as "not planned".

## Gaps vs the monitor-proxy design

Where the design is genuinely differentiated, and where it is not:

1. **Not differentiated: the proxy position and in-line blocking.** In-line
   blocking guardrail proxies are now standard: every gateway in category 1,
   Invariant's gateway, kgateway, Cisco's gateway. A "we hold the exchange
   and can deny" pitch is not novel on its own.
2. **Differentiated: condemnation.** Verified absent everywhere (Invariant:
   absent in source; gateways: absent in docs, plus a rejected feature
   request in LiteLLM's case). The closest shipped mechanism (OpenAI
   `safety_identifier`) fails exactly where the design's threat model
   demands strength: identity is client-supplied. No product treats the
   client as the adversary and derives session identity from content.
3. **Differentiated: the chokepoint premise / adversarial-client threat
   model.** Every proxy-shaped product surveyed is adopted by base-URL
   swap and assumes a cooperating client; tenancy/config selection is by
   client-controlled request field or URL path (NeMo `config_id`,
   Guardrails AI guard path, Invariant dataset path). Per-port tenancy
   with outboard routing, where the monitored party cannot choose its
   policy, appears nowhere. Cisco's network-fabric insertion is the only
   outboard enforcement point found, but with enterprise-DLP policy
   semantics, not eval sanction judging.
4. **Differentiated: the per-tenant lock budget** (the limit of last
   resort against abandon-and-restart probing). No analog found anywhere.
5. **Partially differentiated: part selection over provider-native
   payloads.** LiteLLM's tool-permission guardrail, Lakera's role-aware
   schema, NeMo's IORails, Envoy AI Gateway's CEL over tool arguments, and
   Invariant's typed trace selectors each cover fragments; none offers a
   cross-provider part vocabulary (system prompt / history / tool defs /
   tool calls / tool results / thinking / stop reason) feeding a
   configurable judge without format conversion. Invariant's DSL is the
   closest and is provider-normalized rather than provider-native.
6. **Partially differentiated: LLM-as-judge in the deny path.** Judging
   engines in shipped proxies are overwhelmingly classifiers, regex, and
   embeddings; Kong's ai-llm-as-judge scores but does not block; Portkey
   has small LLM checks. A free-form LLM judge (scanner-shaped question +
   boolean + explanation) as the primary in-line deny mechanism is not
   shipped anywhere surveyed.
7. **Not differentiated: fail-closed and 403 semantics.** Cloudflare
   block-mode fails closed; NeMo's tool rails document fail-closed and the
   policy-block-vs-retryable-error distinction; Kong and kgateway use 403.
   Bedrock's fabricated-response deny is prior art for the design's open
   deny-appearance question.
8. **The research lineage validates the shape but hasn't built it.**
   Lindner et al.'s fully-synchronous monitoring is the design's category;
   ControlArena implements micro-protocols live but in-scaffold, and
   defers shutdown to post-hoc. A monitor at the model-API boundary with
   live automatic condemnation would be the first infrastructure
   implementation of that layer.

## What could not be verified

- LiteLLM: whether guardrails cover provider passthrough routes.
- Kong: guard-plugin behavior on streaming responses.
- Portkey: tool-call handling beyond the main guardrails doc.
- Guardrails AI and Bedrock: fail-open vs fail-closed when the
  validator/guardrail itself errors.
- Prompt Security: reverse-proxy wire format (public docs gated; the claim
  is marketing copy).
- Cisco AI Defense: cross-request state (docs unreachable to fetchers;
  unverified, not confirmed absent).
- Straiker, Zenity, Operant AI, Aim Security, Noma Security: mechanics
  beyond marketing.
- Invariant gateway/guardrails fail posture (an open question in their
  docs); post-Snyk maintenance direction.
- Any Redwood productization beyond ControlArena co-authorship; any AISI
  production deployment of synchronous control.
