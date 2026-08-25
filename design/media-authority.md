# Media Reference Authority

## Security invariant

A string that names media is not permission to read it. Before a model provider
receives a request, every image, audio, video, and document value must be inline
data. Provider serializers must not read files, fetch URLs, or invoke media
resolvers.

Inspect grants non-inline media authority only at explicit host-side boundaries:

- selected samples from the fixed dataset may be materialized before sample
  execution;
- the in-process agent bridge may materialize client media because the client
  already shares the evaluator's filesystem and network;
- trusted runtime code may call `materialize_media()` explicitly; and
- selected provider output, such as Mistral-generated images, may use a separate
  restricted public-network fetcher.

The supported `Model` entry points enforce the invariant centrally. `generate()`
validates after request-shaping and again after before-generate hooks;
`count_tokens()` and `compact()` validate before provider code. Built-in provider
serializers also accept inline media only as defense in depth.

## Source and policy table

| Source | Default policy | Reason |
|---|---|---|
| Selected fixed-dataset sample | Captured, then materialized | The evaluator chose this input before execution. |
| `SampleSource.initial_samples()` | Captured, then materialized | It is the fixed seed for the run. |
| `SampleSource.next_samples()` / `sample_complete()` / `enqueue_sample()` | Inline only | These samples are created while the task is running. |
| `TaskSource` follow-up / `enqueue_task()` | Inline only | These tasks are created while the eval is running. |
| Solver, tool, hook, replayed history, or direct model call | Inline only | Runtime-controlled strings must not grant host I/O. |
| In-process `agent_bridge()` | Explicit materialization | The bridged code already runs with host authority. |
| Direct `AgentBridge(...)` or sandbox bridge | Inline only | New or sandboxed bridge code must opt in to host I/O. |
| Mistral-generated image URL | Restricted public-network fetch | Provider output is untrusted but must remain replayable. |

## Fixed-dataset capture

Inspect captures media authority after dataset slicing, so excluded samples do
not contribute references to the run. The capture binds the selected sample id,
message and content positions, message role, media kind, exact reference, and
MIME/format hint. Materialization occurs only when those fields still match.
Adjacent text and unrelated content are not part of the grant.

All ids from the original seed dataset remain reserved for the run. A dynamic
sample cannot reuse an id that filtering or slicing excluded and inherit its
identity or media authority.

## Trusted materialization is an operator decision

"Fixed dataset" means Inspect treats the dataset as evaluator-authorized; it
does not mean Inspect proved the dataset safe. `materialize_media()` can read
local and remote files, use configured filesystem backends, and fetch HTTP URLs.
Trusted HTTP fetching follows redirects and does not currently apply the
private-address, port, or response-size restrictions used for untrusted provider
output.

Selecting a third-party dataset that contains URLs can therefore cause requests
to destinations reached through those URLs or redirects. Operators should review
or constrain untrusted datasets and run them with appropriate host network and
filesystem isolation. Hardening trusted dataset fetching is tracked separately;
the runtime media policy is not reused for it because the two paths represent
different authority decisions.

## Deliberate residual risks and exclusions

- An unresolved runtime reference may remain as an opaque string in an eval log.
  Inspect does not dereference it, but the string itself can contain a sensitive
  local path or URL. Boundary error messages omit the reference value.
- A captured reference grants the locator, not a snapshot of its bytes. Its file
  or HTTP contents can change between capture and materialization.
- Direct calls to the low-level `ModelAPI` object bypass `Model` policy. That API
  is an extension boundary for provider implementations, not the safe model-call
  interface.
- `Sample.files`, `Sample.setup`, sandbox configuration, and other host-I/O
  features are outside this media-reference boundary. Dynamic-sample authority
  for those fields requires separate analysis and hardening.
- Code already running in the evaluator process can call filesystem, network, or
  `materialize_media()` APIs directly. This design prevents accidental confused-
  deputy behavior; it is not a sandbox for evaluator Python code.

## Maintenance rules

- Keep filesystem, network, and resolver calls out of model input serializers.
- Add new model submission paths to the central validation boundary.
- Add new dynamic task or sample sources with an inline-only policy by default.
- Make every permissive bridge or task-resolution policy explicit at its trusted
  call site.
- Treat logging and fetching as separate decisions: retaining media must not
  grant permission to retrieve it.
