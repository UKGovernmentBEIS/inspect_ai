# LiteLLM Proxy provider

> **Status: proposed.** Branch `feature/litellm-proxy`. A minimal provider
> (`litellm-proxy/<alias>`, a thin `OpenAICompatibleAPI` subclass) and
> Docker-based tests exist. This document plans the next phases: model
> metadata from the proxy, upstream model resolution, a model info gate, and
> reasoning effort normalization. Findings are against LiteLLM 1.104.0 (the
> `ghcr.io/berriai/litellm:main-latest` image pulled 2026-09-23).

## Summary

A LiteLLM proxy serves models under operator-chosen aliases. The alias tells
Inspect nothing about the model behind it, so the provider cannot look up a
context window or cost, cannot apply model-family request adjustments, and
cannot keep `reasoning_effort` within what the upstream model accepts.

The proxy publishes per-deployment metadata at `GET /v1/model/info`, including
the upstream model string. The plan:

1. Fetch `/v1/model/info` once per process when the provider is constructed,
   and fail construction if the fetch fails.
2. Resolve each alias to its upstream model and match it strictly against
   Inspect's model database. That gives `canonical_name()` and `family`.
3. Register model info from Inspect's database, with the proxy's metadata
   filling fields the database lacks.
4. By default, fail when the alias resolves to no model info. A model
   argument turns this off.
5. Normalize `reasoning_effort` so that an unsupported value never produces an
   error, using the proxy's reported support first and then per-vendor rules
   factored out of the native providers into a shared module.

## Background: the provider today

`src/inspect_ai/model/_providers/litellm_proxy.py`:

- `LITELLM_PROXY_API_KEY` (the variable LiteLLM's own SDK uses) or `api_key`.
- `LITELLM_PROXY_BASE_URL` or `base_url`. There is no default because the
  proxy is always self-hosted.
- Everything else comes from `OpenAICompatibleAPI`: `responses_api` (off by
  default), `stream`, `emulate_tools`, `strict_tools`.

`tests/model/providers/test_litellm_proxy.py` runs the proxy image in Docker
with a `mock_response` config. The tests are marked `slow` and skip unless
Docker and the image are present locally. They never pull the image, so they
work offline. The proxy runs in its own container because `litellm` pins
`openai<3.0`; the provider never imports `litellm`.

## Findings

### What `/v1/model/info` returns

One row per deployment:

| Field | Meaning |
|---|---|
| `model_name` | The alias clients send. |
| `litellm_params.model` | Upstream model string (e.g. `anthropic/claude-sonnet-4-5`, `bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0`). Credentials are removed or masked; `model`, `custom_llm_provider`, `api_base` and `model_id` are returned as is. |
| `model_info.base_model` | Set by the operator. Returned for any deployment. LiteLLM itself only uses it to fill model info for Azure deployments. |
| `model_info.key` | The LiteLLM model database key the deployment matched, if any. |
| `model_info.litellm_provider` | LiteLLM's model database category (e.g. `vertex_ai-anthropic_models`), not the routing provider. |
| `model_info.max_input_tokens`, `max_output_tokens` | Limits. |
| `model_info.input_cost_per_token`, `output_cost_per_token`, `cache_read_input_token_cost`, `cache_creation_input_token_cost` | Prices per token. |
| `model_info.supports_reasoning`, `default_reasoning_effort`, `supports_{none,minimal,xhigh,max}_reasoning_effort` | Reasoning support. Filled in only for some models. |

For a model LiteLLM knows, `model_info` comes from LiteLLM's model database
with the config's `model_info` merged over it. For an unknown model, only the
configured fields are present.

Verified behavior:

- `?model=` is ignored; every deployment is returned. v1 accepts
  `litellm_model_id`, `include_team_models`, `teamId` and `healthy_only`.
  `/v2/model/info?model=<name>` filters by exact name (source only, not tested
  live).
- `litellm_params.base_model` is not returned. A Bedrock ARN deployment with
  `litellm_params.base_model` set came back without it.
- One alias can have several deployments with different specs (load
  balancing). In one test a single alias had deployments with 1M and 200K
  input windows.
- `/model_group/info` filters by name and combines deployments by taking the
  maximum. It also reports `supported_reasoning_efforts`, but it drops the
  upstream model string.

From reading the source (not tested live):

- `/v1/model/info` is open to any key and filtered to the models that key can
  use. A key with no model restriction sees every model.
- `litellm_params` is not stripped for non-admin keys beyond credential
  masking.

### Name forms

Only the first `/` segment is LiteLLM's provider; the rest is the
provider-native id, which can contain more slashes. The name forms we need to
handle (source citations are in the research notes):

- **`custom_llm_provider`.** When it differs from the model's first segment,
  LiteLLM prepends it, e.g. `hosted_vllm/meta-llama/Llama-3.3-70B-Instruct`.
- **Bare names.** The provider is inferred: `gpt-*` → openai, `claude-*` →
  anthropic, `gemini-*` → vertex_ai, `anthropic.*` → bedrock.
- **Aggregators.** `openrouter/`, `together_ai/`, `deepinfra/`, `nebius/`,
  `novita/` and `vercel_ai_gateway/` carry a `vendor/model` path in the
  aggregator's spelling (OpenRouter uses `claude-sonnet-4.5`).
- **Fireworks.** `fireworks_ai/accounts/fireworks/models/<slug>` (also
  `routers/`), or the short `fireworks_ai/<slug>`.
- **Bedrock.**
  - Route segments: `converse/`, `invoke/`, `converse_like/`,
    `claude_platform/`, `agent/`, `agentcore/`, `async_invoke/`, `openai/`,
    `mantle/`, `nova/`, `nova-2/`.
  - Invoke vendor segments: `llama/`, `deepseek_r1/`, `qwen3/`, and others.
  - Cross-region prefixes: `us.`, `eu.`, `apac.`, `jp.`, `au.`, `global.`,
    `us-gov.`.
  - Suffixes: `:NNk` and `[1m]`, plus version suffixes like `-v1:0`.
  - ARNs: the last path segment is the model id, except for opaque ARNs
    (below).
  - Vendor ids such as `meta.llama3-3-70b-instruct-v1:0` do not map
    mechanically to HF names.
- **Vertex.**
  - Claude uses `@date` where Anthropic uses `-date`.
  - Gemini has `-001`-style stable suffixes.
  - Partner paths: `meta/`, `mistral*@2407`, `openai/gpt-oss-*`, `moonshotai/`.
  - `vertex_ai_beta/` is an alias of `vertex_ai/`.
- **Azure.** `azure/<deployment>` with optional `responses/`, `o_series/` or
  `gpt5_series/` segments, and `us/` / `eu/` / `global/` region segments.
  `gpt-35-turbo` spellings. `azure_ai/<name>`.
- **OpenAI.** `responses/` segment; fine-tunes `ft:<base>:<org>::<id>`.
- **Wildcard routes** (`anthropic/*`). `/v1/model/info` expands them to one
  row per known model, rewriting both `model_name` and `litellm_params.model`.
  Exact matching works for provider-prefixed wildcards. A custom prefix
  (`llmengine/*` → `openai/*`) loses the upstream name.
- **Aliases that never appear in `/v1/model/info`:** key, team and
  `model_alias_map` aliases.
- **`router_settings.model_group_alias`** rows are listed as copies of the
  target deployments.

**Cannot be identified unless the operator sets `model_info.base_model`:**

- arbitrary Azure and Azure AI Foundry deployment names;
- Bedrock application-inference-profile, provisioned-throughput and
  imported-model ARNs;
- numeric Vertex endpoint ids and Model Garden endpoints;
- `litellm_proxy/` chaining;
- `openai/`, `hosted_vllm/` and `ollama/` with arbitrary served names;
- custom-prefix wildcards;
- key, team and `model_alias_map` aliases.

### Matching against Inspect's database

`_lookup_in_db` tries an exact match, then a case-insensitive match, then a
fuzzy substring match that accepts a score of 60 or more. We ran a prototype
normalizer over all 3,270 chat and Responses entries in LiteLLM's model
database:

- The fuzzy stage often picks the wrong model: `gpt-5-pro`→`gpt-5`,
  `gpt-5.1-codex-mini`→`gpt-5.1-codex`, `gpt-4-32k`→`gpt-4`,
  `o3-deep-research`→`o3`, `gemini-2.5-pro-preview-tts`→`gemini-2.5-pro`,
  `minimax-m2.1`→`MiniMax-M2`, `deepseek-v3`→`deepseek-chat`.
- Strict matching after normalization resolves most first-party models in
  Inspect's database: anthropic 20/20, vertex Claude 32/34, fireworks
  240/299, xai 37/43, azure 156/200, openai 63/102. Most of the remaining
  misses are models Inspect's database does not contain (audio models,
  `-latest` aliases, fine-tunes).
- Real normalizer gaps: Bedrock vendor ids (`meta.llama…`,
  `mistral.…`), Azure `gpt-35-turbo`, `ft:` fine-tunes.
- No realistic match: platforms with their own naming (Databricks
  `databricks-claude-opus-4-7`, OCI, Snowflake, Cloudflare, Ollama tags).

Inspect's own Bedrock, Azure AI and OpenRouter providers also depend on the
fuzzy stage, so there is no stricter logic to reuse.

### Reasoning effort through the proxy

LiteLLM converts `reasoning_effort` per provider:

- **Anthropic:** adaptive thinking, or a thinking budget on older models.
- **Gemini:** a thinking budget on 2.5, `thinkingLevel` on 3.
- **GPT-5:** `max_tokens` → `max_completion_tokens`.
- **Responses for non-OpenAI models:** `reasoning.effort` and `summary` are
  carried into the chat-style call.

It rejects values it considers unsupported rather than lowering them. We sent
every effort to each model with fake keys. A 400 `UnsupportedParamsError`
means LiteLLM rejected the request. "ok" means LiteLLM forwarded it upstream;
it does not mean the upstream provider accepts it.

Chat completions:

| Model | none | minimal | low | medium | high | xhigh | max |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5, claude-sonnet-4-5, claude-3-7-sonnet | ok | ok | ok | ok | ok | ok | ok |
| claude-3-5-haiku | reject | reject | reject | reject | reject | reject | reject |
| gemini-3-pro, gemini-2.5-pro, gemini-2.5-flash-lite | ok | ok | ok | ok | ok | reject | reject |
| gpt-5 | ok | ok | ok | ok | ok | reject | ok |
| gpt-5.5 | ok | reject | ok | ok | ok | ok | ok |
| gpt-4.1 | reject | reject | reject | reject | reject | reject | reject |
| o3, deepseek-reasoner | ok | ok | ok | ok | ok | ok | ok |
| grok-4 | reject | reject | reject | reject | reject | reject | reject |

The Responses endpoint matches except in three places:

- GPT-5 and GPT-5.5 are forwarded for every value, because OpenAI models pass
  straight through to OpenAI, which then applies its own rules.
- Grok 4 is forwarded for every value.
- Claude 3.5 Haiku and GPT-4.1 are still rejected for every value.

A per-request `drop_params: true` works through the proxy for a parameter the
model does not support at all. It does not work for an invalid value, and it
drops the setting instead of lowering it, so it is not a substitute.

`/model_group/info` `supported_reasoning_efforts` examples:

| Model | Reported efforts |
|---|---|
| gpt-5 | `[minimal, low, medium, high]` |
| gpt-5.5 | `[none, low, medium, high, xhigh]` |
| claude-opus-5-5 | all seven |
| gpt-4.1 | `[]` |
| claude-sonnet-4-5, Gemini, o3, grok-4 | `null` |

### Reasoning round trips

LiteLLM converts reasoning in both directions, so the request Inspect records
does not show what the upstream model received. The tests in
`tests/model/providers/test_litellm_proxy_reasoning.py` capture the proxy's
upstream traffic with a LiteLLM callback (`tests/test_helpers/litellm_proxy/`).
They check that the reasoning in upstream response N comes back unchanged, and
in the right place, in upstream request N+1:

- Anthropic: thinking blocks and their signatures before `tool_use`.
- Gemini: the thought signature on the `functionCall` part.
- OpenAI: `encrypted_content`.
- Bedrock: `reasoningContent`.
- Open models: `reasoning_content`.

The tests run offline against fake upstreams and live against real providers:
Claude Sonnet 4.5, Sonnet 5, Opus 5.5 and Fable 5.1, Gemini 3.1 Pro, 3.5 Flash,
3 Flash and 2.5 Flash, GPT-6 Astra, GPT-5.5 and gpt-5-mini, Bedrock Claude
Sonnet 4.5, Kimi K2.6, and Together gpt-oss-120b and DeepSeek V4.1. Bedrock
Claude Sonnet 5 is untested: the test AWS account has no access to it. They
cover chat completions and Responses, streaming and not, and a tool loop plus
a text follow-up. The newest models show the same results as their
predecessors. Claude 5 models (adaptive thinking) and GPT-6 Astra decide per
turn whether to reason and skip it on easy prompts even at high effort, so the
test prompts are small deduction puzzles; a turn with no reasoning skips
rather than passes. Findings with LiteLLM 1.104.0:

**Round trips that work** (after the phase 5 fixes; live run: 99 passed,
15 xfailed for gaps 7–9, 4 non-strict xpasses, 2 skipped with no reasoning):
- OpenAI on Responses, all cases.
- Anthropic and Bedrock on both paths, streaming or not, except Bedrock
  redacted thinking (gap 7) and doubled text on streaming Responses (gap 6).
- Gemini on chat completions, including text-part signatures; tool loops on
  both paths, including parallel calls.
- Open models (Kimi, gpt-oss) on both paths.

Before the fixes, only OpenAI on Responses, Anthropic and Bedrock on
Responses without streaming, Gemini tool loops, and open models on chat
completions worked.

**Inspect gaps (fixed in phase 5; see below):**
1. **Chat completions ignores `thinking_blocks`.** Anthropic and Bedrock signed
   and redacted thinking is never sent back.
2. **Chat streaming crashes on Claude thinking.** LiteLLM's `thinking_blocks`
   stream entries have no `index`, so the OpenAI SDK stream accumulator raises.
   Also, the chunk carrying the signature repeats the full thinking text
   (`llms/anthropic/chat/handler.py:703-716`).
3. **Responses sends text-only reasoning back empty.** Kimi, gpt-oss and
   DeepSeek reasoning is lost. LiteLLM's DeepSeek code fills in `" "`, so
   providers accept the turn and nothing reports the loss.
4. **Responses sends back an empty text item for a tool-call-only turn.**
   LiteLLM forwards it as empty text content, and Moonshot rejects that.
5. **Chat completions ignores `provider_specific_fields.thought_signatures`.**
   Gemini text-part signatures are lost. Gemini 3 signs the first function
   call, so its tool loops are unaffected. Gemini 2.5 signs the first part of
   the turn: when it writes text before its tool calls, the turn's only
   signature is on the text and is lost. Gemini does not reject the turn.

**How the Inspect gaps are fixed** (`_providers/_litellm_proxy_reasoning.py`):
- Chat completions (1, 5): each `thinking_blocks` entry becomes a
  `ContentReasoning` (signature, or `redacted` with the data), and each
  `thought_signatures` entry a redacted `ContentReasoning`, as the native
  Anthropic and Google providers represent them. `internal` records the
  field, and replay sends the same field back, with `reasoning_content` set
  to the blocks' text as LiteLLM returned it.
- Chat streaming (2): the provider takes `thinking_blocks` entries out of each
  delta before the SDK accumulator sees them and merges them itself. A
  signature entry closes the current block: its text is taken as the whole
  block when it starts with the accumulated text (current LiteLLM), appended
  otherwise, and an entry with no text only adds the signature.
- Responses (3, 4): two `ResponsesModelInfo` options, off for native OpenAI
  and on for this provider, send text-only reasoning back as reasoning
  `content` and leave out empty text on tool-call turns.

**LiteLLM bugs (report upstream; not worked around):**
6. **Streaming Responses with Anthropic doubles the thinking text** in
   `encrypted_content`. Anthropic accepts the doubled text; with Claude 4+ the
   reasoning state travels in the signature, so the impact is likely small.
   The same join runs over every block of a message, so interleaved thinking
   may merge text between blocks (not verified).
7. **Bedrock loses redacted thinking.**
   `translate_thinking_blocks_to_reasoning_content_blocks`
   (`prompt_templates/factory.py:4594`) has no `redactedContent` branch, on
   both paths (on chat completions the redacted block becomes empty text,
   which is then dropped). When
   redacted blocks alternate with signed ones, Bedrock rejects the replayed
   turn (`Invalid signature in thinking block`), so the conversation fails
   rather than only losing reasoning.
8. **The Responses bridge drops Gemini text-part thought signatures.** The
   same Gemini 2.5 tool-loop impact as gap 5.
9. **`reasoning_effort` is rejected** for some deployments (Together
   DeepSeek V4.1 raises `UnsupportedParamsError`). This is covered by §6
   below.

Live streaming runs can only check that the provider accepts the replayed
turn, because LiteLLM keeps no raw streamed responses. The offline fakes check
streamed replays exactly.

### Working around LiteLLM behavior

Users run many LiteLLM versions, and LiteLLM fixes bugs over time. Handling of
LiteLLM behavior therefore follows these rules:

- **Rely on LiteLLM's documented fields.** For example, `thinking_blocks`,
  `provider_specific_fields`, and reasoning `content` on Responses input.
  These are not workarounds.
- **Handle quirks in a way that is correct before and after a fix, and detect
  behavior, not versions.** For example, treat a streamed signature chunk as
  the full block only when its text starts with the text accumulated so far;
  attach the signature to the accumulated text when the chunk has no text;
  otherwise append. The fake upstreams emit the current behavior and the
  likely fixed ones.
- **Do not rewrite LiteLLM's opaque data** (`encrypted_content`) to undo its
  bugs. Report them upstream and keep them as strict xfails, so a LiteLLM fix
  shows up as an unexpected pass. Where it matters, steer users to a
  combination that works rather than patching around the bug.
- **Watch for LiteLLM changes.** An occasional job pulls the latest proxy
  image and runs the offline matrix. A change in LiteLLM's conversions shows
  up as a strict xfail passing or a new failure.

### Where Inspect reads model attributes

These are all sync:

- `canonical_name()` and `model_family()`.
- `_get_model_info_direct(model)`, used by per-call cost and by the
  `cost_limit` pricing check, which runs at eval start before any generate
  call.
- `get_model_input_tokens()`, used by compaction.
- `get_model_info("litellm-proxy/x")` given a model string. It constructs the
  provider with the dummy key `MODEL_INFO_LOOKUP_API_KEY` and treats any
  exception as "no info".

Nothing calls into a `ModelAPI` at eval start; `verify_model_apis()` runs
inside generate.

## Proposal

### 1. Configuration

| Setting | Source | Default |
|---|---|---|
| API key | `api_key`, `LITELLM_PROXY_API_KEY` | required |
| Base URL | `base_url`, `LITELLM_PROXY_BASE_URL`, `LITELLM_PROXY_API_BASE` (alias used by LiteLLM's SDK) | required |
| `model_info` | model arg | `True`: fetch `/v1/model/info`. `False` skips the fetch, the gate and proxy-derived normalization. |
| `require_model_info` | model arg | `True`: see §5. |

`model_info_timeout` could become a model arg if 30s proves wrong for some
deployments.

### 2. Fetch and cache

- `LiteLLMProxyAPI.__init__` fetches `GET {base_url}/model/info`
  synchronously, with a 30s timeout, and caches the parsed rows at module
  level keyed by (base URL, API key). The key is part of the cache key because
  the listing depends on which models the key may use.
- Every attribute method reads the cache. There is no lazy or async fetch
  path.
- Any failure raises: timeout, connection error, non-2xx status, or an
  unparseable body. The error names the URL and the status, and points at
  `model_info=False`. A failure at construction stops an eval at startup
  rather than partway through a run.
- The `get_model_info()` dummy-key path already catches exceptions and returns
  None, so it is unaffected.
- The fetch blocks the event loop once per (base URL, key) per process when
  `get_model()` runs inside an async context. We accept that.
- There is no lock. Inspect runs one event loop thread. Two constructions
  racing the same key would at worst fetch twice and store the same value.

### 3. Resolving the upstream model

Deployments for an alias are the rows whose `model_name` equals
`service_model_name()`. The upstream identity of each deployment is resolved
in this order:

1. `model_info.base_model`, when set. This is the documented way for an
   operator to identify an Azure deployment, an ARN, a vLLM served name and so
   on. It may be LiteLLM-style (`azure/gpt-5`) or Inspect/HF-style
   (`meta-llama/Llama-3.3-70B-Instruct`); both go through the normalizer.
2. `litellm_params.model`, with `litellm_params.custom_llm_provider`
   prepended if it differs from the first segment.

The normalizer (a pure function in `_providers/litellm_proxy_names.py`) turns
the string into an ordered list of candidate Inspect database keys:

- Split the LiteLLM provider segment. Map `vertex_ai_beta` to `vertex_ai`,
  `bedrock_converse` to `bedrock`, and `azure_text` to `azure`.
- Strip route and region segments for the provider:
  - **Bedrock:** route and invoke-vendor segments, AWS region path segments,
    cross-region prefixes, `:NNk` / `[1m]` / `-vN:N` suffixes, and the ARN
    last segment.
  - **Azure:** `responses/`, `o_series/`, `gpt5_series/`, `us/` / `eu/` /
    `global/`.
  - **OpenAI:** `responses/`, and the `ft:` suffix down to the base model.
  - **Fireworks:** `accounts/fireworks/(models|routers)/`.
  - **Vertex:** the `-00N` stable suffix; `@date` becomes `-date`, and the
    bare base is also tried.
- Map to an Inspect organization:
  - A provider table for bare ids: `openai`/`azure`/`chatgpt` → `openai`,
    `anthropic` → `anthropic`, `gemini`/`vertex_ai` → `google`,
    `xai` → `grok`, `mistral`/`codestral` → `mistral`,
    `deepseek` → `DeepSeek`, `moonshot` → `moonshotai`, `zai` → `z-ai`,
    `fireworks_ai` → `fireworks`.
  - A vendor table for Bedrock/OCI `vendor.model` ids and aggregator
    `vendor/model` paths.
  - Name-pattern detection when neither table applies.
  - Aggregator paths are also tried unchanged (HF-style keys such as
    `meta-llama/…`).
- Fix known spellings: Azure `gpt-35-*` → `gpt-3.5-*`; a table for Bedrock
  Meta/Mistral vendor ids.
- Add date-stripped variants after the dated candidates.

The first candidate that matches exactly or case-insensitively wins. The
fuzzy stage is never used. `canonical_name()` returns the winning Inspect key.
When nothing matches, it returns the normalized upstream name, or the alias if
there is no deployment row.

Several deployments: if every deployment resolves to the same Inspect key,
that key is used. If they disagree, the first deployment's key is used and a
warning is logged once.

### 4. Model info registration

After resolution, the provider registers a `ModelInfo` under
`litellm-proxy/<alias>` (the `str(model)` key) with `set_model_info`, the same
way vLLM registers its served context window. It never replaces an entry the
user registered.

Precedence for each field:

1. The user's `set_model_info` / `set_model_cost` / `--model-cost-config`.
2. Inspect's database entry for the resolved canonical key.
3. Proxy metadata:

| Proxy field | Inspect field |
|---|---|
| `max_input_tokens` | `context_length` (whether LiteLLM means input-only is still open) |
| `max_output_tokens` | `output_tokens` |
| `supports_reasoning` | `reasoning` |
| `default_reasoning_effort` | `reasoning_effort_default` |
| prices per token × 1e6 | `ModelCost` |

`family` is set to the resolved canonical key, so model-family checks
(`needs_max_completion_tokens`, `is_gpt_5_plus`, `supports_max_reasoning_effort`
and so on) see the upstream model instead of the alias.

With several deployments, limits take the minimum, since the router can send
a request to any of them, and prices take the maximum.

Cost is registered only when input and output prices are both present. A
missing cache read or write price uses the input price.

### 5. The model info gate

With `require_model_info=True` (the default), construction fails unless the
alias resolves to model info, meaning either:

- the canonical key matched Inspect's database strictly, or
- at least one deployment reported `max_input_tokens`.

The error lists the three fixes:

- add `model_info` (with `base_model` or `max_input_tokens`) to the proxy
  config;
- call `set_model_info("litellm-proxy/<alias>", …)`;
- pass `-M require_model_info=false`.

LiteLLM fills `max_input_tokens` for every model in its own database, so the
gate mainly catches unreleased models without configured `model_info`,
opaque deployments without `base_model`, and aliases that `/v1/model/info`
does not list.

### 6. Reasoning effort normalization

**Goal:** the same guarantee as the native providers. A `reasoning_effort`
the upstream model does not support never causes an error. It is lowered to
the closest supported value, or dropped with a warning.

**Shared module.** Add `src/inspect_ai/model/_reasoning_effort.py` with pure
functions of a model name that describe each vendor's effort support.
Candidates to move there:

- **Anthropic:** `is_claude_frontier`, `is_claude_4_7_or_later`,
  `_supports_disabling_thinking`, and the mapping in
  `effort_from_reasoning_effort`.
- **Google:** `is_gemini_2_5`, `is_gemini_3_plus`.
- **xAI:** the effort gate and mapping in `grok.py` (`is_grok_3_mini`,
  `is_at_least_grok_4`, `is_grok_4_original`).
- **OpenAI:** `supports_native_max_reasoning_effort` (already a function in
  `_openai.py`).

The native providers keep their methods but delegate to these functions, so
their behavior is unchanged and the LiteLLM provider does not import other
providers. The generic clamps in `_reasoning.py`
(`clamp_reasoning_effort_to_low_medium_high`,
`clamp_reasoning_effort_to_minimal_low_medium_high`) stay where they are.

Some predicates depend on model database state rather than only the name.
For example, `is_claude_latest` treats a Claude model that is missing from
the database as the latest one. Those take the database lookup as an explicit
argument, or keep the database check in the provider. This is decided per
predicate when moving it.

**Resolution in `LiteLLMProxyAPI.resolve_config`:** the same logic for chat
completions and Responses.

1. **The proxy's reported support.** Use `supported_reasoning_efforts` from
   `/model_group/info`, or the `supports_*_reasoning_effort` flags, when
   present. `/model_group/info` is fetched with `/v1/model/info` and cached
   the same way. An empty list means a non-reasoning model.
2. **Vendor rules** from `_reasoning_effort.py`, chosen by the resolved
   upstream vendor:

| Vendor | Rule |
|---|---|
| Not a reasoning model (neither proxy `supports_reasoning` nor the database `reasoning` is true) | Drop reasoning options and warn, using the existing "reasoning options ignored for non-reasoning model" message. |
| Gemini (`gemini/`, `vertex_ai/`) | `minimal`–`high`; `xhigh`/`max` → `high`. |
| Anthropic (native, Bedrock, Vertex) | The native provider's rules (`xhigh` → `high` before 4.7; `max` → `high` below frontier models). |
| OpenAI (native, Azure) | `max` → `xhigh` unless supported. |
| xAI | The Grok provider's effort gate and mapping. |

3. **Unknown upstream:** pass the value through unchanged. With the gate on
   this is rare.

Lowering follows Inspect's usual semantics: the highest supported level at or
below the requested one, otherwise the lowest level above it. An unsupported
`none` is dropped with a warning, leaving the model's default.

### 7. Testing

The tests extend `tests/model/providers/test_litellm_proxy.py`. Docker tests
are `slow` and use the local image with `--pull=never`.

- **Pure unit tests (no Docker)** for the normalizer, with a table of real
  LiteLLM strings and expected Inspect keys. The table covers every name form
  above and the fuzzy false positives, which must not match.
- **Fetch errors:** timeout, connection refused, 401 and a malformed body
  each raise; `model_info=False` skips the fetch. Use a local stub server,
  not Docker.
- **Proxy integration:** one multi-deployment config covering Anthropic, a
  Bedrock cross-region id, a Bedrock ARN with `base_model`, a Vertex `@date`
  model, Azure with `base_model`, a load-balanced alias with different
  windows, an unreleased model with only `model_info`, and an unknown model
  without it (the gate must fail). Assert `canonical_name()`, registered
  context window and cost, `cost_limit` accepting the model, and the gate
  error text.
- **Effort guarantee (offline):** for every (deployment, effort) pair,
  generate through the provider with fake upstream keys and assert that no
  `UnsupportedParamsError` comes back. Supported values fail later with a
  connection or authentication error. Run on both chat completions and
  Responses.
- **Refactor check:** the existing native provider tests confirm the moved
  predicates did not change behavior.
- **Live (`--runapi`):** a proxy with real keys for Anthropic, OpenAI and
  Gemini, covering generate, multi-turn reasoning and the effort extremes, to
  confirm the upstream providers accept the lowered values.
- **Non-admin keys:** a Postgres-backed proxy (docker compose) to confirm that
  a virtual key sees `litellm_params.model` in `/v1/model/info`.

## Phases

Each phase ends with review and approval before the next starts.

1. **Configuration and fetch.** `LITELLM_PROXY_API_BASE` alias, the
   `model_info` argument, the sync fetch with its error behavior, and the
   cache.
2. **Resolution.** The normalizer and its unit table; `canonical_name()`;
   deployment selection.
3. **Registration and gate.** `set_model_info` registration with the
   precedence and combining rules, `family`, `require_model_info`, and cost.
4. **Reasoning effort.** The `_reasoning_effort.py` refactor with native
   providers delegating, then proxy normalization and the offline effort
   guarantee test.
5. **Reasoning round trips.** Fix Inspect gaps 1–5 under "Reasoning round
   trips":
   - capture and send back `thinking_blocks` and
     `provider_specific_fields.thought_signatures` on chat completions;
   - handle streamed `thinking_blocks` in the chat stream path, using the
     behavior-detecting rule;
   - an opt-in for the Responses path, turned on by this provider, that sends
     text-only reasoning back as reasoning `content` and drops empty text
     items.

   Then turn the matching strict xfails into passing tests, rerun the live
   matrix, and report LiteLLM bugs 6–8 upstream with captured payloads.
6. **Docs, CHANGELOG, live tests.** Provider docs (including `base_model`
   guidance for opaque deployments), the CHANGELOG entry, and adding the
   provider to the `slow-tests` skill.

## Open questions

- Is LiteLLM's `max_input_tokens` input-only, or the whole context window?
  This decides whether it maps to `context_length` or to the private
  `_input_tokens` override.
- Does `/v2/model/info?model=` behave as the source suggests? If it does, it
  would avoid fetching every deployment on large proxies, but it skips the key
  allowlist, so v1 stays the default.
- Should key, team and `model_alias_map` aliases be resolved through
  `/key/info`? Unverified; the gate plus `set_model_info` covers them for now.
- Default for `responses_api`. It is off today. Given the translation layer
  for non-OpenAI upstreams, it could be chosen per resolved vendor. Deferred
  along with other provider-specific behavior.
