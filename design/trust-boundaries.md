# Trust boundaries for data handling

This document names the trust boundaries inspect crosses when it handles
content — media references, sample files, dynamically created samples and
tasks, bridged-agent requests, provider responses — and says where each
boundary is enforced in code and what authority crossing it grants. It
generalizes the pattern established by PR #4362 ("Restrict runtime media
references to inline data"). Code references are to that PR's branch
(`fix/runtime-media-authority`); until it merges, some symbols named here do
not exist on `main`.

The point of writing this down: several past issues came from code treating
"a string that looks like a path or URL" as permission to read or fetch it.
Whether that permission exists depends on *who wrote the string*, and that
depends on *when* it entered the eval. Future changes to media, samples,
tasks, or provider serialization should be checked against these boundaries.

## The core rule

Content that exists in the fixed task definition **before execution starts**
is evaluator-authored configuration. It may carry file paths and URLs that
inspect will read or fetch on the host. Concretely, "fixed task definition"
means:

- the task's dataset (including a `SampleSource.initial_samples()` seed,
  which becomes the dataset at task creation — see
  `Task` dataset resolution in `src/inspect_ai/_eval/task/task.py`)
- tasks resolved before the run, including a `TaskSource.initial_tasks()`
  seed (resolved in `eval_resolve_tasks`, `src/inspect_ai/_eval/eval.py`)

Content introduced **after execution starts** is untrusted: model output,
tool results, solver-added content, samples added via
`SampleSource.next_samples()` / `enqueue_sample()`, tasks added via
`enqueue_task()`, and requests from bridged agents. Untrusted content must
already contain its bytes inline (a `data:` URI); inspect refuses to
dereference a path or URL found in it.

Authority is not granted where content is *used*; it is granted where content
is *captured*, and the use site only honors references that were captured.
That is what makes the rule enforceable at a single chokepoint.

## Boundaries

### 1. Fixed task input vs. runtime content

- **Trusted side:** samples in the resolved dataset at the moment the task
  run is prepared.
- **Untrusted side:** everything that appears in a conversation afterwards,
  including runtime-injected samples and any mutation solvers make.
- **Enforced at:**
  - Capture: `capture_task_input_media()`
    (`src/inspect_ai/_eval/task/images.py`), called once per task in
    `src/inspect_ai/_eval/run.py` over `task.dataset` — only when the task's
    `input_media_policy` is `"trusted_pre_run"`.
  - Grant: `materialize_sample_input()`
    (`src/inspect_ai/_eval/task/images.py`), called at sample start in
    `task_run_sample` (`src/inspect_ai/_eval/task/run.py`). It dereferences
    a reference only if the exact tuple (sample id, message index, content
    index, kind, reference string) was captured.
  - Backstop: `_validate_model_input_media()` at the top of
    `Model._generate` (`src/inspect_ai/model/_model.py`) — see mechanism
    inventory below.
- **Authority granted:** host filesystem read (any fsspec path, including
  `s3://` etc. via registered `media_resolver`s) and outbound HTTP fetch,
  performed by the host process. For sandboxed evals this is a
  sandbox-escaping read: the bytes land in the model conversation.

### 2. Model provider responses

- **Trusted side:** none — provider output is untrusted even though inspect
  initiated the request. Providers can return URLs (e.g. Mistral generated
  images), and a compromised or confused provider could return
  `file:///etc/passwd` or an internal-network URL.
- **Untrusted side:** anything in the provider's response.
- **Enforced at:** `provider_image_data_uri()`
  (`src/inspect_ai/_util/images.py`), used by the Mistral providers
  (`src/inspect_ai/model/_providers/mistral.py`,
  `mistral_conversation.py`). It never touches the trusted fetch path:
  HTTPS-only on port 443, DNS resolved and pinned to public IP addresses
  (so a hostname can't rebind to a private address between check and
  connect), redirects re-validated and capped, response streamed with a
  20 MiB cap, and the bytes must sniff as a recognized raster image.
- **Authority granted:** a narrowly constrained outbound HTTPS fetch —
  deliberately less than the trusted path grants.

Any new provider that returns media by reference must go through this
function (or an equivalently hardened one), never through
`materialize_media`.

### 3. Sandboxed agent vs. host (sandbox agent bridge)

- **Trusted side:** the host process running the eval.
- **Untrusted side:** the agent running inside the sandbox. A media URI in a
  bridged model request is a confused-deputy vector: the sandboxed agent
  asks the host to read a file or fetch a URL the sandbox itself cannot
  reach.
- **Enforced at:** `validate_bridge_media()`
  (`src/inspect_ai/agent/_bridge/util.py`), gated by
  `AgentBridge.allow_remote_media`. `sandbox_agent_bridge()` defaults it to
  `False` (`src/inspect_ai/agent/_bridge/sandbox/types.py`): non-inline
  references are rejected with `BridgePolicyError`. When an evaluator
  explicitly enables it, the bridge itself materializes each reference (via
  `materialize_media`) before the request reaches the model, so provider
  serialization stays inline-only either way. Opaque OpenAI Responses
  "agent message" replay items are separately fail-closed by
  `validate_agent_message()` (`src/inspect_ai/model/_agent_message.py`):
  only known scalar fields and non-media content parts pass through.
- **Authority granted (when enabled):** sandbox-escaping host filesystem
  read and outbound fetch.

### 4. In-process bridged scaffold

The in-process `agent_bridge()` defaults `allow_remote_media=True`
(`src/inspect_ai/agent/_bridge/types.py`). This is a deliberate judgment
that an in-process scaffold is *inside* the host trust domain — it already
shares the host's filesystem and network, so refusing to dereference on its
behalf defends nothing. The boundary here is nominal; it exists in code only
so the same `validate_bridge_media` path serves both bridges. If that
judgment changes (e.g. scaffolds running third-party plugins), flip the
default rather than adding a second mechanism.

### 5. Embedding API (who declares tasks trusted)

`resolve_tasks()` (`src/inspect_ai/_eval/loader.py`) takes an
`input_media_policy` parameter (`"trusted_pre_run" | "inline_only"`, defined
in `src/inspect_ai/_eval/task/resolved.py`). This is where the "fixed task
definition" designation is actually conferred:

- Pre-run resolution (`eval_resolve_tasks`, retry resolution) passes or
  defaults to `"trusted_pre_run"`.
- `enqueue_task()` resolution (`src/inspect_ai/_eval/eval.py`) passes
  `"inline_only"` — and additionally forces it with `replace(...)` on the
  results, so a future default change can't silently re-grant authority to
  runtime-enqueued tasks.
- The `ResolvedTask` dataclass field itself defaults to `"inline_only"`
  (fail-closed at the type level).

**Authority granted:** everything boundary 1 grants — calling
`resolve_tasks` with `"trusted_pre_run"` is the act of vouching for the
task's dataset.

### 6. Logs and the viewer

Logs record what happened; they never grant dereference authority. An
unresolved reference (e.g. a path in a runtime sample that was rejected)
is stored as the opaque string it was, not fetched at logging or viewing
time. `log_images` controls only *retention* — whether inline base64 is
kept in the log or replaced with `BASE_64_DATA_REMOVED`
(`sample_without_base64_content` and friends in
`src/inspect_ai/_eval/task/images.py`, condensation in
`src/inspect_ai/log/_condense.py`). Before PR #4362, `log_images` also
*triggered* dereferencing (`sample_with_base64_content` /
`states_with_base64_content`); that overload is gone and must not return.

## Mechanism inventory

- **The chokepoint.** `_validate_model_input_media()` runs at the top of
  `Model._generate` (`src/inspect_ai/model/_model.py`), immediately before
  provider serialization, for every generate call regardless of origin. It
  is synchronous and incapable of I/O: it calls `inline_media_data_uri()`
  (`src/inspect_ai/_util/images.py`), which validates a `data:` URI and
  raises `UnresolvedMediaError` for anything else. Because it cannot fetch,
  a bug in it can reject wrongly but cannot grant wrongly. Providers
  downstream use the I/O-free `inline_media_data` / `inline_media_data_uri`
  helpers rather than the old fetching helpers.

- **The escape hatch.** `materialize_media()`
  (`src/inspect_ai/_util/images.py`, re-exported from `inspect_ai.util`)
  is the single named function that turns a reference into bytes with full
  trusted authority (resolver, HTTP fetch, filesystem read). It exists so
  that granting authority is a greppable act. Production call sites are
  deliberately few: `materialize_sample_input()` (fixed input) and
  `validate_bridge_media()` (explicitly enabled bridge media). Trusted
  user/solver code may also call it directly to convert a reference it
  vouches for. Adding a call site is a trust decision — review it as one.

- **Capture-then-materialize.** Fixed input is not dereferenced at
  resolution time. `capture_task_input_media()` records the exact
  references present per sample id; `materialize_sample_input()`
  dereferences only exact matches at sample start. This keeps eval startup
  cheap (no upfront fetch of a large dataset's media) and keeps the
  authority record explicit. Note the capability captured is the *locator*,
  not the bytes (see residual risks).

- **The bridge split.** One function, `validate_bridge_media()`, implements
  both postures: reject (sandbox bridge default) or materialize-on-behalf
  (explicit grant). There is no third posture where the reference passes
  through to serialization and gets fetched later.

- **The hardened provider path.** `provider_image_data_uri()` with its
  `_PublicNetworkBackend` (DNS-pinned, public-IP-only) is the only sanctioned
  way to fetch media referenced by provider output.

- **Custom schemes.** `media_resolver()` (`src/inspect_ai/_util/images.py`)
  registers per-scheme resolvers (e.g. `s3`). Resolvers run only inside the
  trusted materialize path; the chokepoint and the hardened provider path
  never invoke them.

## Deliberate residual risks

These are accepted trade-offs. Don't "fix" them in passing; if one needs to
change, it's a design decision.

- **The trusted fetch path is a full-authority fetch.** `file_as_data()`
  follows redirects and has no private-IP or size guard. Choosing a dataset
  (or calling `materialize_media`) is treated as an authority decision by
  the evaluator, equivalent to running code that reads those locations.
  Hardening it would break legitimate datasets (internal artifact stores,
  large media) to defend against an evaluator attacking themselves.

- **Unresolved references stay in logs as opaque strings.** A runtime sample
  that carried `/etc/passwd` as an image reference fails at the chokepoint,
  and the string appears in the log as-is. That is intentional: the log is
  a faithful record, and nothing at log-write or view time dereferences it.

- **Capture is time-of-check, use is time-of-use.** The capture plan stores
  reference strings, not bytes. A file can change between task resolution
  and sample start, and each epoch re-materializes. Runtime code cannot
  *add* a reference, but content behind an authorized locator is read live.
  Capturing bytes upfront would fix this at the cost of eval startup time
  and memory; so far the locator is the accepted capability.

## Known gaps

Surfaced during review of PR #4362. Each needs its own issue; listed here so
the boundary definition is honest about where it currently leaks.

### Dataset is not the same as evaluator-authored

Boundary 1 labels the dataset "evaluator-authored configuration", but
datasets are routinely third-party (HuggingFace, shared benchmarks). A
malicious dataset sample can carry `file:///...` or internal URLs and the
trusted path will read them. The mechanism for a middle tier already exists
— `input_media_policy="inline_only"` skips capture entirely — but it is not
reachable by users; it is only set internally for enqueued tasks.

**Recommendation:** keep two tiers (a per-reference allowlist tier isn't
worth its complexity yet), but expose the policy as a user-facing eval/task
option so an evaluator running an unvetted dataset can opt out of granting
it host read/fetch authority. Document plainly that the default means "you
vouch for this dataset the way you'd vouch for code you run."

### The duplicate-id guard and the capture plan disagree about identity

The capture plan is keyed by sample id over the **full** dataset
(`capture_task_input_media(task.dataset)` in `src/inspect_ai/_eval/run.py`),
but the runtime duplicate-id guard is seeded from the **sliced** dataset
(`seen_ids = {str(id) for id in sample_ids}` in
`src/inspect_ai/_eval/task/run.py`, where `sample_ids` comes from
`slice_dataset(...)`). Under a positional `--limit`, a runtime-injected
sample can reclaim the id of a sliced-out sample: the guard doesn't know the
id, so the sample is accepted, and `materialize_sample_input` then finds its
id in the plan. Exploitation requires reproducing a captured reference at
the captured message/content position, but that's exactly the authority the
boundary says runtime content must never have — the injected sample gets the
host to read that locator and hand it the bytes.

This is the worked example of why a boundary must be defined precisely:
"fixed vs. runtime" is really a claim about an identity space (sample ids,
compared in `str()` form) and every mechanism keyed on it must use the same
space over the same population. The plan and the guard use the same key form
but different populations (full vs. sliced dataset).

**Recommendation:** make the populations agree. Either seed `seen_ids` from
the full dataset's ids, or restrict the capture plan to the sliced ids that
will actually run. The second is strictly safer (authority for samples that
can't run shouldn't exist at all) and also covers retry/resume paths that
rebuild the slice.

### `Sample.files` / `Sample.setup` is an unguarded parallel path

`sandboxenv_context` / `resolve_sample_files` / `read_sandboxenv_file`
(`src/inspect_ai/_eval/task/sandbox.py`) host-read paths (including
recursive directory listings), fetch URLs, and copy the results into the
sandbox — for *any* sample, including runtime-injected ones. There is no
inline-only rule here. This is arguably wider than the media hole PR #4362
closed: it grants host read **plus** write-into-sandbox, and its fallback
behavior (unreadable path becomes literal file content) makes tightening it
a behavior change. A `SampleSource.next_samples()` sample with
`files={"x": "/home/user/.aws/credentials"}` delivers host secrets into the
sandbox today.

**Recommendation:** in scope — bring it inside boundary 1. Apply the same
pattern: capture `files`/`setup` references for pre-run samples, and require
inline (data URI or literal) content for runtime-injected samples. This
needs a deprecation path because of the literal-content fallback, but the
end state should be that no runtime sample can name a host path.

### Fail-open defaults

Two places default to granting authority:

- `AgentBridge.allow_remote_media=True`
  (`src/inspect_ai/agent/_bridge/types.py`). Defensible today (boundary 4's
  same-trust-domain argument), and the sandbox bridge overrides it to
  `False` where it matters.
- `resolve_tasks` / `eval_resolve_tasks` default `input_media_policy` to
  `"trusted_pre_run"` (`src/inspect_ai/_eval/loader.py`), even though
  `eval_resolve_tasks` is an entry point for external embedders
  (inspect-flow calls it directly). An embedder resolving tasks from a less
  trusted source inherits the grant silently.

**Recommendation:** the direction should be deny-by-default at every
*entry-point* signature; permissive values belong at the call sites that
actually decide trust. Concretely: make `input_media_policy` a required
(or `"inline_only"`-defaulted) parameter on the externally callable
`eval_resolve_tasks`, with inspect's own pre-run path passing
`"trusted_pre_run"` explicitly. Leave the in-process bridge default as-is,
but any *new* boundary-adjacent knob should default to deny.

## Principles

- **A knob controls one thing.** `log_images` used to be both a retention
  switch and a dereference trigger; PR #4362 split them. A setting that
  controls logging, display, or serialization must not silently grant read
  or fetch authority as a side effect.
- **Authority is granted at capture, checked at a chokepoint, and spent at
  named sites.** The chokepoint can only reject (it cannot do I/O), and the
  granting function (`materialize_media`) is greppable. New code should
  extend this shape, not add a parallel one.
- **Origin, not shape, decides trust.** A well-formed URL from a provider
  response, a bridged agent, or a runtime sample is still untrusted. When a
  new content source appears, the first question is which boundary it enters
  through — and if none fits, this document needs a new entry before the
  code ships.
- **Boundaries are defined over an identity space.** Saying "pre-run content
  is trusted" is meaningless until the keying (sample id as `str()`, full
  vs. sliced population, slice/retry interactions) is pinned down; the
  `seen_ids` gap above is what happens otherwise.
