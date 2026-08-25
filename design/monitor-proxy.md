# Monitor proxy (pencil sketch)

Status: early design discussion. Nothing here is committed to.

## Glossary

- **Monitor proxy.** An HTTP proxy in front of a model provider API that
  judges traffic against a policy and can deny it.
- **The spec.** The behavior contract Inspect delivers. Any proxy meeting
  it is a monitor proxy. Implementations are a separate concern.
- **Chokepoint.** The deployment premise that the proxy is an eval's only
  network path to a model, established outboard of Inspect.
- **Exchange.** One generate request and its response.
- **Outbound / inbound judging.** The two judgment points: blocking a
  request before it reaches the provider, and blocking a response before it
  reaches the scaffold.
- **Judge.** The configured component that decides proceed/reject for an
  exchange. Either an LLM judge (scanner-like question, boolean answer,
  explanation) or an HTTP judge (a configured HTTP call).
- **Verdict.** The judge's decision as applied by the proxy.
- **Condemnation.** Once the monitor flags a conversation, the proxy denies
  every later request from it. Permanent and automatic.
- **Session.** One agent conversation, identified by a session key. How
  the key is derived is open; the candidate mechanism is hashing the
  message-history prefix (content-derived, no client trust).
- **Condemned session.** A session the monitor has flagged. The proxy
  denies all its later requests.
- **Tenant / port.** One port on the shared proxy = one tenant = one
  declarative configuration. A port scopes policy, audit log, condemnation
  state, and lock budget.
- **Port lock.** The per-tenant limit of last resort: after a budget of
  denials or new sessions is exceeded, the whole port refuses traffic.
- **Sanction.** The per-eval statement of what the eval permits. The
  monitor judges "outside the sanction", not "scary".
- **Part selection.** Config naming which parts of provider payloads to
  judge (e.g. requested tool calls, tool results). Parts are located per
  provider format; content is never converted.
- **Fail closed.** When the judge itself fails, the proxy denies (as 5xx,
  since that failure is transient).
- **Audit log.** The proxy's own per-tenant record of every request,
  verdict, and explanation. Verdicts do not enter the Inspect transcript.

## What it is

What Inspect delivers is a spec: the behavior contract for a live safety
monitor built as an HTTP proxy in front of the model provider API. A
conforming monitor watches model generate requests and responses, judges
them against a configured policy, and can deny them, per the rules in this
document (judging, condemnation, tenancy, wire behavior, audit).

Concrete implementations are a separate concern. We may provide a reference
implementation on Envoy, and we may provide a development-time in-process
implementation for debugging. Neither is the deliverable; any proxy that
meets the spec is a monitor proxy.

The monitor protects the operator while running dangerous-capability evals.
It is not an eval feature: it does not score the model, and its verdicts do
not enter the eval transcript. Think of it as a network appliance, in the
spirit of a WAF.

This is separate from the agent bridge's sandbox model proxy
(`design/model-proxy-lifecycle.md`). The bridge pattern may inspire the
implementation, but the monitor proxy is hit whether or not the bridge is in
use.

## Premise: the proxy is a chokepoint

The whole design relies on something outboard of Inspect configuring the
network so that an eval's only path to a model is through the proxy. If the
proxy can be sidestepped, it is useless. Inspect does not enforce this; the
deployment environment does.

## Threat model

The adversary is the agent: the model and its scaffold acting together.

Dangerous-capability evals *ask* the agent to do scary things inside the
sandbox. So the monitor does not judge "is this scary?" It judges "is this
outside what this eval sanctions?" Outside means real targets instead of
fixtures, exfiltration of real credentials, attempts to leave the sandbox
or reach the monitor itself. The sanction is per-eval and lives in the
per-port policy config; for an LLM judge it is typically prose in the judge
prompt.

The spec makes no judgment calls about what is acceptable. No built-in
rules, no mandatory floor. Content policy is entirely operator
configuration (shipped example policies can encode recommendations such as
"never allow requests targeting the monitor"). The spec governs how
verdicts behave once made: condemnation, fail-closed, tenancy scoping, and
audit.

## What the monitor sees

- Every model generate request and its response, at the provider HTTP API
  level.
- The full conversation: agents send the whole message history on each
  generate call.
- Requested tool calls *before they execute*. They arrive inside the model
  response, so holding the response gates the action.
- Tool results one turn late, inside the next request.
- It does not see actions that skip the model: direct sandbox commands by a
  scaffold, file writes, store changes.

## Judging

### Two judgment points

The monitor judges at two distinct points, each enablable per port:

- **Outbound (request) blocking** stops content from ever reaching the model
  provider: sandbox secrets or real credentials stuffed into a prompt, or
  the model API used as an exfiltration or communication channel.
- **Inbound (response) blocking** stops the model's intent from reaching the
  scaffold: requested tool calls and instructions, before anything executes.

Condemnation applies to both. The proxy denies a condemned conversation in
both directions.

### Judge shapes

Two configurable judge shapes:

1. **LLM judge.** The proxy makes a model call of its own, shaped like
   inspect_scout's `llm_scanner`: a question, a boolean answer, and a rich
   explanation (which goes to the audit log, not into the verdict). Unlike a
   scout scanner it judges an in-progress exchange, not a finished
   transcript, so the judge input distinguishes "conversation so far" from
   "candidate content being judged".
2. **HTTP judge.** The proxy makes a configured HTTP request; the response
   carries the proceed/reject decision. This covers whatever the
   declarative form cannot, analogous to writing a custom scout scanner in
   Python.

### Provider-specific domain; no canonical format

What crosses the wire is model-provider-specific (OpenAI, Anthropic, Google
API JSON), and that is the domain the spec deals in. The spec does not
define a canonical normalized format. A particular implementation may
normalize internally, even reusing inspect's provider translation code;
that is an implementation detail, not spec. The consequence: policy
portability across implementations and providers is not a spec guarantee.
This is an open question, and we are soliciting input from potential users
on whether it matters.

### Part selection

The spec's analog of scout's message/event filters is a part-selection
vocabulary. The three major provider APIs differ in field names but share
the same parts. Config names the parts, and each implementation locates
them in each provider's format. Content is never converted; the bytes
handed to the judge stay provider-native.

Request-side parts: system prompt; message history with roles; tool
definitions; tool results; new user content. Response-side parts: assistant
text; requested tool calls (name + arguments); thinking blocks; stop reason.

Example policies this enables:

- Judge only requested tool calls ("does this command target anything
  outside the fixture network?"). Tiny judge input, and the biggest cost
  reduction available.
- Judge tool results outbound, to catch real credentials or exfiltrated
  data in tool outputs.
- Run a rules tier on extracted parts: regex IPs/domains/URLs out of tool
  call arguments, no LLM needed.
- Watch tool definitions and flag if the set of tools changes mid-session.
- Check the system prompt once per session to verify the sanction statement
  is intact.
- Include or exclude thinking blocks from judge input.
- Judge only the delta since the last judged exchange.

Part selection partly rescues portability without normalization: "judge
requested tool calls with this question" carries across providers because
every provider has requested tool calls. Whether the part vocabulary is
spec or per-implementation is open (lean: spec).

## A deny is permanent; state is minimal

A stateless proxy has a fatal flaw: a persistent bad actor can probe it
repeatedly and binary-search what is allowed. So a deny condemns:

- Once the monitor flags a conversation, the proxy denies every later
  request from it, whatever its content.
- Required state reduces to a set of condemned session keys. A prober gets
  one probe per conversation.

**Session identity (open, to be discussed further).** The candidate
mechanism: requests from one conversation share a message-history prefix,
and the proxy hashes that prefix to make a session key. No headers, no
client trust, no cooperation needed. Known weakness: history compaction
changes the prefix, so one conversation can look like a new session, and
condemnation may not follow the agent across a compaction. Whether
prefix-hashing is sufficient session identity is not settled.

**Limit on fresh conversations.** A prober can abandon a condemned
conversation and start a new one (losing all its progress). Each tenant
(port, see below) carries a budget for new conversations and/or total
denials; when exceeded, the port locks. Open: whether the lock is automatic
or an alert to a human.

## Tenancy: one port per configuration

One shared proxy serves many concurrent evals. Multitenancy is by port:

- One port = one tenant = one declarative configuration.
- Each port scopes its own policy, its own audit log, its own condemnation
  state, and its own lock budget.
- The deployment environment routes each eval's egress to its port, the
  same outboard network work that establishes the chokepoint.

Session identity (content-derived) answers "which conversation"; the port
answers "which eval run, which policy".

## Wire behavior

- **A policy deny returns 403** with a short body ("blocked by monitor
  policy"). Appliances (e.g. WAFs) use 403 for policy blocks; provider SDKs
  do not retry 4xx, so the scaffold fails fast and the operator sees
  exactly what happened.
- **A monitor failure returns 5xx.** Fail closed: if the judge call errors
  or times out, deny. But deny as a 5xx, because that failure is transient
  and a retry is correct.
- Open decision: the first deny could instead be a fabricated model response
  (a refusal, or the response with tool calls stripped), which hides the
  monitor from a prober. Condemnation caps what a 403 leaks (the session is
  condemned after it), and a 403 is far clearer to the operator. This is a
  real trade-off, recorded here rather than settled.

## Cost and latency

An LLM judge that reads every full exchange with a same-class model roughly
doubles a run's token bill (agents resend full history each call), and an
in-line judge call adds seconds to every turn. None of the mitigations
below are spec (the spec requires judging and condemnation; speed and cost
are implementation and config concerns), though the reference
implementation should demonstrate the first three:

- A cheaper judge model.
- Tiering: cheap rules first, LLM only on what rules can't clear.
- Delta judging: judge only new content, trusting earlier verdicts. Uses
  the same per-session state as condemnation, and cuts quadratic cost to
  linear.
- Prompt caching on the judge's own calls (the history prefix is stable).

The spec's promise is in-line: no exchange is forwarded unjudged.

## Audit

Verdicts do not enter Inspect transcript events, and there is no back
channel from the proxy to the Inspect process (deliberately out of scope for
now). The proxy keeps its own audit log per tenant: every request, verdict,
and reason. That log is what the appliance delivers to the operator.

## Implementations (separate concern from the spec)

Candidate implementations we may ship, neither of which is the deliverable:

- **Envoy reference implementation.** The natural fit is Envoy's external
  processing filter (`ext_proc`): a gRPC service we provide receives
  request/response bodies and returns allow / mutate / deny, while Envoy
  handles listeners (per-port tenancy), TLS, and routing. The declarative
  configuration is then Envoy config plus our judge/policy config.
- **In-process implementation**, for development and debugging only.

Anyone can implement the spec on another proxy.

## Known limits

Stated up front because users will (and should) probe them:

- **It only sees model traffic.** Actions that skip the model, such as a
  scaffold's direct sandbox commands and file writes, are invisible. The
  monitor sees what the agent says to and hears from the model, not what
  it does in the sandbox. Sandbox-level controls remain necessary; the
  proxy complements them.
- **An LLM judge is a model, so it can be attacked.** Agent-authored
  content passes through the judge's prompt, and a capable agent can craft
  text aimed at the judge. Part selection shrinks what the judge is exposed
  to, and condemnation limits retries, but the risk is inherent. The
  AI-control framing applies: use a trusted (smaller, non-colluding) judge
  model. An HTTP judge has whatever failure modes its implementation has.
- **A false positive is expensive, and condemnation makes it stick.** One
  wrong deny condemns the session of a long, costly, legitimate run.
  Inspect's checkpointing mitigates somewhat (resume from before the deny).
  The broader open question is the policy development loop: how operators
  learn and adjust configuration until it is practical in the real world.
  The in-process development-time implementation is certainly part of the
  answer.
- **The chokepoint is assumed, not verified.** If the outboard network
  config is wrong, the monitor is silently useless. Two spitball ideas
  (may or may not make sense, not fleshed out):
  - A canary. At run start, send a known-bad request through the eval's
    path and confirm it is denied. That proves the path through the proxy
    works; it cannot prove no path around it exists.
  - Keep provider credentials off the Inspect host entirely. Only the
    proxy holds real API keys. Then a direct call to a provider fails on
    authentication even if a network path around the proxy exists.

## Prior art / competitive analysis

Full survey with primary-source citations: `monitor-proxy-prior-art.md`.
Verified highlights: no product keeps verdict state keyed on conversation
identity, so condemnation is the differentiator. The closest shipped
analog, OpenAI's `safety_identifier`, condemns permanently but trusts
client-supplied identity. The closest overall neighbor is Invariant Labs'
gateway: also a proxy on the same wire formats, with a tool-call-aware
policy DSL, but stateless with client-controlled tenancy. AWS Bedrock ships
the fabricated-response deny (prior art for the deny-appearance question).
The research literature calls this category "fully-synchronous monitoring".

The categories to place the monitor proxy against:

- **LLM gateways** (LiteLLM, Portkey, Kong AI Gateway, Cloudflare AI
  Gateway): also HTTP proxies in front of provider APIs, and all now do
  in-line blocking guardrails in the request path, so in-line blocking at
  this position is standard. Still not eval-aware, no condemnation, no
  adversarial-client assumption.
- **Guardrails / "AI firewall" products** (NeMo Guardrails, Bedrock
  Guardrails, Lakera, Prompt Security, Cisco/Robust Intelligence): judge
  content, but built to defend a production app from its users. Per-request
  and stateless, which is the probing failure mode condemnation exists to
  close.
- **AI-control literature** (Redwood Research trusted monitoring): the
  research frame this productizes as a network appliance. Terms: trusted /
  untrusted model, control protocol, audit budget.
- **Classic security appliances** (WAF, IDS/IPS, egress proxy, DLP): the
  source of the design vocabulary (in-line vs tap, fail-closed, ban lists,
  listeners). The monitor proxy is a WAF where the protected asset is the
  outside world and the attacker is inside.
- Closest single neighbor: Invariant Labs (agent trace analysis + gateway).

## Open questions

- Policy portability: does the absence of a canonical judge-input format
  matter to users? (Soliciting input in early conversations.)
- Is the part-selection vocabulary spec or per-implementation? (Lean: spec.)
- Session identity: is prefix-hashing sufficient, or is something else
  needed? (Compaction weakness above; to be discussed further.)
- The policy development loop: how operators tune a policy to be practical
  (dry-run/log-only modes? replay against recorded traffic? the in-process
  implementation's role?).
- Streaming responses: judging a full response before delivery means
  buffering the stream (client sees slower time-to-first-token). Acceptable?
- Deny appearance: 403 vs fabricated model response (see above).
- Port lock: automatic vs human alert; what unlocks it.
- Operational mapping of eval runs to ports (who allocates, how configs are
  authored and distributed).
- Exact shape of the in-process dev/debug mode and how much code it shares
  with the Envoy path.
