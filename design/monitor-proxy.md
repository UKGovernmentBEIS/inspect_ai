# Monitor Proxy (pencil sketch)

Status: early design discussion. Nothing here is committed to.

## What it is

A live safety monitor for agent evals, built as an HTTP proxy in front of the
model provider API. It watches model generate requests and responses, judges
them against a configured policy, and can deny them. It protects the operator
while running dangerous-capability evals. It is not an eval feature: it does
not score the model, and its verdicts do not enter the eval transcript.

Think of it as a network appliance (in the spirit of a WAF). Its ultimate
form is an out-of-process proxy. An in-process mode exists too, but only for
development and debugging.

This is separate from the agent bridge's sandbox model proxy
(`design/model-proxy-lifecycle.md`). The bridge pattern may inspire the
implementation, but the monitor proxy is hit whether or not the bridge is in
use.

## Premise: the proxy is a chokepoint

The whole design relies on something outboard of Inspect configuring the
network so that an eval's only path to a model is through the proxy. If the
proxy can be sidestepped, it is useless. Inspect does not enforce this; the
deployment environment does.

## What the monitor sees

- Every model generate request and its response, at the provider HTTP API
  level.
- The full conversation: agents send the whole message history on each
  generate call.
- Requested tool calls **before they execute** — they arrive inside the model
  response. Holding the response gates the action.
- Tool results one turn late, inside the next request.
- It does not see actions that skip the model: direct sandbox commands by a
  scaffold, file writes, store changes.

## Judging

Two configurable judge shapes:

1. **LLM judge** — the proxy makes a model call of its own (in the spirit of
   inspect_scout's LLM scanner) and derives proceed/reject from the result.
2. **HTTP judge** — the proxy makes a configured HTTP request; the response
   carries the proceed/reject decision.

## Verdicts ratchet; state is minimal

A stateless proxy has a fatal flaw: a persistent bad actor can probe it
repeatedly and binary-search what is allowed. So verdicts ratchet:

- Once the monitor flags a conversation, that conversation is dead. Every
  later request from it is denied, whatever its content.
- Required state reduces to a set of condemned session keys. A prober gets
  one probe per conversation.

**Session identity is derived from content.** Requests from one conversation
share a message-history prefix; the proxy hashes that prefix to make a
session key. No headers, no client trust, no cooperation needed.

**Backstop for fresh conversations.** A prober can abandon a dead
conversation and start a new one (losing all its progress). Each tenant
(port, see below) carries a budget for new conversations and/or total
denials; when exceeded, the port locks. Open: whether the lock is automatic
or an alert to a human.

## Tenancy: one port per configuration

One shared proxy serves many concurrent evals. Multitenancy is by port:

- One port = one tenant = one declarative configuration.
- Each port scopes its own policy, its own audit log, its own ratchet state,
  and its own lock budget.
- The deployment environment routes each eval's egress to its port — the
  same outboard network work that establishes the chokepoint.

Session identity (content-derived) answers "which conversation"; the port
answers "which eval run / which policy".

## Wire behavior

- **Policy deny → 403** with a short body ("blocked by monitor policy").
  Appliances (e.g. WAFs) use 403 for policy blocks; provider SDKs do not
  retry 4xx, so the scaffold fails fast; the operator sees exactly what
  happened.
- **Monitor failure → 5xx.** Fail closed: if the judge call errors or times
  out, deny — but as a 5xx, because that failure is transient and a retry is
  correct.
- Open decision: the first deny could instead be a fabricated model response
  (a refusal, or the response with tool calls stripped), which hides the
  monitor from a prober. The ratchet caps what a 403 leaks (the session is
  dead after it), and a 403 is far clearer to the operator — but this is a
  real trade-off, recorded here rather than settled.

## Audit

Verdicts do not enter Inspect transcript events, and there is no back
channel from the proxy to the Inspect process (deliberately out of scope for
now). The proxy keeps its own audit log per tenant: every request, verdict,
and reason. That log is the appliance's product for the operator.

## Reference implementation: Envoy

Ship an out-of-the-box reference implementation on Envoy. The natural fit is
Envoy's external processing filter (`ext_proc`): a gRPC service we provide
receives request/response bodies and returns allow / mutate / deny, while
Envoy handles listeners (per-port tenancy), TLS, and routing. The declarative
configuration is then Envoy config plus our judge/policy config.

## Open questions

- Streaming responses: judging a full response before delivery means
  buffering the stream (client sees slower time-to-first-token). Acceptable?
- Deny appearance: 403 vs fabricated model response (see above).
- Port lock: automatic vs human alert; what unlocks it.
- Operational mapping of eval runs to ports (who allocates, how configs are
  authored and distributed).
- Exact shape of the in-process dev/debug mode and how much code it shares
  with the Envoy path.
