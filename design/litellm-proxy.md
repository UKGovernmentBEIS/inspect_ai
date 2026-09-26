# LiteLLM Proxy provider

> **Status: implemented** (#5559; the Responses API default and key/team
> aliases in §9 followed). Server-side web search was spiked and not pursued;
> see [litellm-proxy-server-tools.md](litellm-proxy-server-tools.md).
> Findings are against LiteLLM 1.104.0 (the
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
5. Make an unsupported `reasoning_effort` never produce an error: recognize
   the proxy's rejection, lower the value (or drop it) with a warning, and
   retry.

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
  `model_alias_map` aliases (key and team aliases are resolved separately;
  see §9).
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
- `model_alias_map` aliases (which have no deployment row to set it on).

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

**LiteLLM bugs (reported upstream; not worked around):**
6. **Streaming Responses with Anthropic doubles the thinking text**
   ([#43010](https://github.com/BerriAI/litellm/issues/43010)) in
   `encrypted_content`. Anthropic accepts the doubled text; with Claude 4+ the
   reasoning state travels in the signature, so the impact is likely small.
   The same join runs over every block of a message, so interleaved thinking
   may merge text between blocks (not verified).
7. **Bedrock loses redacted thinking**
   ([#43009](https://github.com/BerriAI/litellm/issues/43009)).
   `translate_thinking_blocks_to_reasoning_content_blocks`
   (`prompt_templates/factory.py:4594`) has no `redactedContent` branch, on
   both paths (on chat completions the redacted block becomes empty text,
   which is then dropped). When
   redacted blocks alternate with signed ones, Bedrock rejects the replayed
   turn (`Invalid signature in thinking block`), so the conversation fails
   rather than only losing reasoning.
8. **The Responses bridge drops Gemini text-part thought signatures**
   ([#43011](https://github.com/BerriAI/litellm/issues/43011)). The
   same Gemini 2.5 tool-loop impact as gap 5.
9. **`reasoning_effort` is rejected** for some deployments (Together
   DeepSeek V4.1 raises `UnsupportedParamsError`). Covered by §6: the
   parameter is dropped with a warning.

**Block order within a Claude turn.** Chat completions has separate fields
for text, thinking and tool calls, so LiteLLM flattens a response's content
blocks: text blocks are joined with no separator, thinking and redacted
blocks go to `thinking_blocks` in order, and `tool_use` and `server_tool_use`
blocks become `tool_calls` (`extract_response_content` in
`llms/anthropic/chat/transformation.py`). On replay
(`anthropic_messages_pt` in `prompt_templates/factory.py`) it rebuilds the
turn as all thinking, then text, then `tool_use`, except when the turn has
server tool calls (`srvtoolu_` ids, e.g. web search): it then interleaves
each thinking block with one server tool call and its result, since
Anthropic checks thinking signatures by position (LiteLLM #23047). Assistant
`content` sent as a list with thinking blocks inline keeps its order, but a
chat response carries no order to rebuild it from.

The provider's chat path sends only function tools, so only the first form
applies. In a live run (Sonnet 5 and Opus 5.5, high and max effort, 34
responses in multi-step tool loops with parallel calls) every response was
ordered thinking, text, then tool calls, and every replayed thinking block
and signature was identical to the response. The run also found that the
base conversion puts a newline before each text part on replay; the
provider now joins text parts as LiteLLM does, so replayed text is
unchanged. (Every `openai-api` provider has the leading newline; not changed
here.)

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

### Errors, retries and refusals

Inspect retries rate limit and transient errors, and turns context window
and content policy errors into model output (`model_length`,
`content_filter`) rather than failing the sample. The proxy's errors were
probed with a fake upstream that returns each provider's native errors
(Anthropic, OpenAI, Gemini, Bedrock, DeepSeek, Moonshot, Azure), across chat
and Responses, streaming and not, with the proxy's own retries off
(`test_litellm_proxy_error_handling` in `test_litellm_proxy.py`).

- **Retries work unchanged.** 429s arrive as `RateLimitError` (streaming
  Responses: `response.failed` with `rate_limit_exceeded`), 5xx including
  Anthropic 529 as `InternalServerError` (`server_error`), and a mid-stream
  Anthropic `overloaded_error` as an `APIError` with code `"500"`. The base
  class classifies all of them correctly. The proxy renames upstream
  `retry-after` to `llm_provider-retry-after`, which does not matter because
  Inspect does not use `retry_after` to decide how long to wait. The proxy's
  router retries 408/409/429/5xx itself (`num_retries`, default 2), on top of
  Inspect's retries.
- **Bad request classification needs the provider.** LiteLLM sets the error
  `code` to the HTTP status (`"400"`), so the base class's code matching
  never fires. The mapped error class survives only as a message prefix
  (`litellm.ContextWindowExceededError:`,
  `litellm.ContentPolicyViolationError:`). Some upstream errors reach the
  client without it: messages LiteLLM does not recognize (OpenAI's current
  "exceeds the context window", Moonshot's "exceeded model token limit") and
  Gemini chat streaming errors, which skip LiteLLM's mapping and carry the
  raw upstream body. `_litellm_proxy_errors.py` matches the prefixes and the
  upstream wording, and records the upstream message (without LiteLLM's
  wrapping) as the output. The provider applies it in `handle_bad_request`
  and in a new `handle_stream_error` hook on `OpenAICompatibleAPI`, which
  covers Responses streaming failures (`response.failed`) and mid-stream chat
  errors.
- **200 refusals work.** Anthropic `refusal`, Gemini `SAFETY` and blocked
  prompts, and Bedrock `guardrail_intervened` arrive as `finish_reason:
  "content_filter"`.
- **LiteLLM bugs (reported upstream):**
  - Anthropic's `model_context_window_exceeded` stop reason is unmapped and
    becomes `stop` ([#43012](https://github.com/BerriAI/litellm/issues/43012);
    strict xfail).
  - OpenAI's current context window message and Moonshot's are not mapped to
    `ContextWindowExceededError`
    ([#43013](https://github.com/BerriAI/litellm/issues/43013)).
  - Gemini chat streaming errors skip exception mapping
    ([#43014](https://github.com/BerriAI/litellm/issues/43014)).

  The provider's matcher covers the last two until they are fixed.

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
| API key | `api_key`, `LITELLM_PROXY_API_KEY`, then `LITELLM_API_KEY` | required |
| Base URL | `base_url`, `LITELLM_PROXY_BASE_URL`, `LITELLM_PROXY_API_BASE` (alias used by LiteLLM's SDK), then `LITELLM_BASE_URL` | required |
| `stream` | model arg | on for chat completions (§8) |
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
  unparsable body. The error names the URL and the status, and points at
  `model_info=False`. A failure at construction stops an eval at startup
  rather than partway through a run. LiteLLM's `{"error": {"message"}}` text
  is shown when present. A proxy without a database cannot check virtual
  keys and answers any key but the master key with `400 No connected db.`;
  one with a database returns 401, which the error reports as a rejected key.
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

The normalizer (a pure function in `_providers/_litellm_proxy_names.py`) turns
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

Several deployments: if every deployment that resolves gives the same Inspect
key, that key is used (a deployment that does not resolve, such as an opaque
ARN, does not block it). If they disagree, the first deployment's key is used
and a warning is logged once.

`model_family()` returns the model part of the canonical name (`gpt-5`, not
`openai/gpt-5`, because checks such as `is_o_series_model` match anywhere in
the name), unless the user registered a `family` with `set_model_info` under
the alias, `litellm-proxy/<alias>` or the canonical name. So request shaping
(`max_completion_tokens`, reasoning parameters) follows the upstream model.

Implementation notes (phase 2):

- A first segment that is not a LiteLLM provider and is followed by an
  `org/model` path is also tried without it, which covers hosts LiteLLM
  configures by name only (`replicate/`, `gmi/`, `crusoe/`).
- A bare `base_model` in Bedrock form (`anthropic.claude-sonnet-4-5`,
  `us.anthropic.…`) goes through the Bedrock rules.
- Bedrock candidates try the model's own key before the Bedrock id alias, so
  `anthropic/claude-3-5-haiku-20241022` wins over
  `anthropic/anthropic.claude-3-5-haiku-20241022-v1:0`.
- OpenRouter variant suffixes (`:free`, `:exacto`) are removed.
- Against the 3,270 chat and Responses entries in LiteLLM 1.104's model
  database, 1,692 resolve (the prototype: 1,298), with no entry the prototype
  resolved lost or changed. The only hits whose key does not textually
  contain the upstream name come from the explicit Bedrock id table.

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
| `max_input_tokens` | `context_length` (LiteLLM's value is input capacity: it equals Inspect's `input_tokens` for every compared model, e.g. 272k for gpt-5, whose context window is 400k) |
| `max_output_tokens` | `output_tokens` |
| `supports_reasoning` | `reasoning` |
| `default_reasoning_effort` | `reasoning_effort_default` |
| prices per token × 1e6 | `ModelCost` |

`family` is not registered. `model_family()` already returns the upstream
model's name (without the organization, since checks such as
`is_o_series_model` match anywhere in the name), so model-family checks
(`needs_max_completion_tokens`, `is_gpt_5_plus`, `supports_max_reasoning_effort`
and so on) see the upstream model instead of the alias. A user-registered
`family` still wins.

With several deployments, limits take the minimum, since the router can send
a request to any of them, and prices take the maximum.

Cost is registered only when input and output prices are both present. A
missing cache read or write price uses the input price. Inspect's database
has no prices (0 of 808 models), so the proxy is usually the only automatic
source of cost.

Implementation notes (phase 3):

- Precedence applies field by field: a user registration for
  `litellm-proxy/<alias>` (e.g. only `family`) is merged with, not replaced
  by, the database and proxy fields. The user's original is kept, so
  constructing the model again merges from it again. A user registration for
  the canonical name (e.g. `set_model_cost("openai/gpt-5", ...)`) comes in
  through the database lookup.
- A database input limit below the context window (gpt-5) is kept.
- An alias that resolves to nothing still gets an empty registration (with
  `require_model_info=false`), and `input_tokens_name()` returns the
  registered key, so lookups stop there instead of fuzzy matching the alias.
- `model_info=false` skips registration and the gate.
- Limitations: the registry is keyed by model string, so two proxies
  serving the same alias in one process share an entry (the last constructed
  wins). `get_model_info("litellm-proxy/<alias>")` before the model is
  constructed cannot reach the proxy (it runs with a placeholder key) and
  still uses the database's fuzzy matching.

### 5. The model info gate

With `require_model_info=True` (the default), construction fails unless the
alias resolves to model info, meaning either:

- the canonical key matched Inspect's database strictly, or
- at least one deployment reported `max_input_tokens`.

The error lists the three fixes:

- add `model_info` (with `base_model` or `max_input_tokens`) to the proxy
  config. When the upstream is an Anthropic, OpenAI, Google or xAI model, the
  error suggests `base_model` set to that vendor's current frontier model (in
  LiteLLM's naming, e.g. `anthropic/claude-opus-5-5`); otherwise it shows a
  `max_input_tokens`/`max_output_tokens` template. There is no automatic
  fallback to the frontier model's info: an unrecognized model stops with the
  error, because without `base_model` LiteLLM also lacks the model's
  capabilities (see §8);
- call `set_model_info("litellm-proxy/<alias>", …)`;
- pass `-M require_model_info=false`.

LiteLLM fills `max_input_tokens` for every model in its own database, so the
gate mainly catches unreleased models without configured `model_info`,
opaque deployments without `base_model`, and aliases that `/v1/model/info`
does not list.

### 6. Reasoning effort

**Goal:** the same guarantee as the native providers. A `reasoning_effort`
the upstream model does not support never causes an error. It is lowered to
the closest supported value, or dropped, with a warning.

**Why not per-vendor rules.** An earlier version of this design moved the
native providers' effort predicates into a shared module and chose values
from per-vendor tables. Capturing what LiteLLM 1.104 does with each effort
(fake upstreams, chat completions) showed that most rejections come from
LiteLLM's own gates, not the upstream provider's:

| Model | LiteLLM rejects |
|---|---|
| claude-3-5-haiku, gpt-4.1 | the parameter |
| grok-4, grok-3-mini, grok-4-fast-reasoning | the parameter (its map lacks `supports_reasoning`; xAI accepts effort on grok-3-mini) |
| claude-opus-4-6 | `xhigh` |
| gemini-2.5, gemini-3 | `xhigh`, `max` |
| gpt-5 | `xhigh` (forwards `none` and `max`, which OpenAI rejects) |
| gpt-5.5 | `minimal` |
| any model its map does not mark as reasoning, on Responses | the parameter |

LiteLLM also maps values itself (its own Claude thinking budgets, Gemini
budgets and levels), so the native providers' mapping tables do not apply.
Tables would have to replicate LiteLLM's map and gates, which change between
versions, and the native predicates are instance methods over
`model_family()` with no shared lowering logic to reuse. So the provider
detects rejections instead (see "Working around LiteLLM behavior").

**Detection** (`_litellm_proxy_reasoning_effort.py`). LiteLLM answers 400
before calling upstream, and OpenAI answers 400 for values LiteLLM forwards.
The messages name what was rejected:

- the parameter: `<provider> does not support parameters:
  ['reasoning_effort']` (chat), `<model> doesn't support \`reasoning.effort\``
  (Responses);
- a value: `reasoning_effort=xhigh is not supported` (OpenAI, Azure),
  ``Invalid `reasoning_effort`: 'max'`` (Gemini), `effort='xhigh' is not
  supported` (Anthropic), and from OpenAI `Unsupported value:
  'reasoning_effort' does not support 'max'` (chat) or `Unsupported value:
  'max' is not supported with the 'gpt-5' model` with `param:
  reasoning.effort` (Responses).

A value rejection counts only when it names the value sent.

**Handling** (`LiteLLMProxyAPI.generate`). On a rejection the provider records
it for the model (per provider instance), picks the next value, and retries:
the strongest accepted value at or below the requested one, otherwise the
weakest above it; a rejected `none` or parameter is dropped, leaving the
model's default. One warning names the requested and the sent value. Later
requests use the recorded result without a failed attempt. Rejections are
fast 400s (LiteLLM's before any upstream call). `supports_max_reasoning_effort()`
is true, so `max` is sent rather than lowered by the family check (which only
recognizes OpenAI models, and would lower Claude's `max`).

**Limitation.** LiteLLM refuses effort entirely for models its map does not
mark as reasoning models (e.g. grok-3-mini, and any unknown model on the
Responses path), so the effort is dropped with a warning. Operators can set
`supports_reasoning: true` in the deployment's `model_info`.

**Native provider inconsistencies found** (separate from this work): Bedrock
Converse gives Claude 5 no adaptive thinking from `reasoning_effort`, and has
no effort-to-budget bridge before 4.6; OpenAI chat completions send `max` raw
while Responses lower it to `xhigh`; `none` is dropped silently on Grok and on
Anthropic models that cannot disable thinking.

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
  generate through the provider against fake upstreams, on chat completions
  and Responses, and assert that it succeeds; check the value sent upstream
  for the lowered cases, including a fake OpenAI upstream that rejects values
  with OpenAI's wording.
- **Live (`--runapi`):** a proxy with real keys for Anthropic, OpenAI and
  Gemini, covering generate, multi-turn reasoning and the effort extremes, to
  confirm the upstream providers accept the lowered values.
- **Non-admin keys:** a Postgres-backed proxy (docker compose) to confirm that
  a virtual key sees `litellm_params.model` in `/v1/model/info`.

### 8. Claude requests and defaults

A deployment running Claude codenames through the generic `openai-api`
provider showed replies cut at 4096 tokens, no prompt caching, 600s
timeouts, assistant-prefill 400s and stripped tool schemas. LiteLLM 1.104
decides several of these from its model map, which does not know codenames.
The provider now recognizes the vendor from the upstream model string, then
the alias (`_litellm_proxy_vendor.py`: an `anthropic`/`xai` provider segment,
or `claude`, `gemini`, `grok`, or an OpenAI model name), and for Claude:

- **max_tokens.** Without one, LiteLLM sends 4096, even with `base_model`
  set. The provider sends the native Anthropic default (32000, plus the
  reasoning effort's increment, at least 64000 for `xhigh`/`max`), capped by
  the registered output limit. The constants live in
  `_anthropic_max_tokens.py`, shared with the native provider.
- **Prompt caching.** LiteLLM adds breakpoints only for models its map marks
  `supports_prompt_caching`, but forwards the client's `cache_control` for any
  model (as `cachePoint` for Bedrock, including tool results). Unless
  `cache_prompt` is false the provider marks the system prompt, the last tool
  and the last two messages, as the native provider does. LiteLLM reports
  cache writes in `prompt_tokens_details.cache_write_tokens` and their split
  by TTL in `cache_creation_token_details`; cost uses the reported TTL, since
  a proxy can rewrite the TTL of forwarded breakpoints. There is no TTL model
  arg. A response with cache writes but no split warns once and is costed at
  the 5-minute rate.
- **Tool schemas** keep `pattern`, `minLength` and the other extended fields,
  which LiteLLM forwards to Anthropic and Bedrock.
- **Empty assistant text.** An assistant turn with tool calls and no text is
  sent with `content: null`. LiteLLM replaces empty text sent to Anthropic
  with `[System: Empty message content sanitised to satisfy protocol]`, which
  the model then reads.
- **Assistant prefill.** A 400 naming assistant prefill becomes a
  `PrefillNotSupportedError` saying the conversation must end with a user or
  tool message (not retried).

For every model, chat completions stream by default (`-M stream=false` opts
out); the Responses path does not, because of LiteLLM #43010, except to
OpenAI (see §9).

What `base_model` adds: for a codename, LiteLLM rejects `thinking`, maps
`reasoning_effort` to a small fixed thinking budget (4096 at `high`) when
forced with `allowed_openai_params`, and for Bedrock rejects `tool_choice`,
so every request with tools fails. With `base_model: anthropic/claude-opus-5-5`
the deployment gets that model's capabilities, including adaptive thinking
and `xhigh`/`max` effort. So the provider does not try
`allowed_openai_params` (plan item 6, dropped); the gate points the operator
at `base_model` instead.

Verified in 1.104: with a Postgres-backed proxy, `/model/info` called with a
virtual key returns `litellm_params.model` and `base_model` for the models
the key may use, and omits the others. OpenAI's `prompt_cache_key` passes
through `extra_body`, and the native provider sets it only from a model arg,
so the provider does nothing for it.

### 9. Responses API default and key/team aliases

Follow-ups to #5559, verified against LiteLLM 1.104.

**Responses API default.** On Chat Completions, OpenAI returns none of a
reasoning model's reasoning, so tool loops lose it between turns. When
`responses_api` is not passed, the provider uses the Responses API if:

- every deployment of the alias has the `openai` route
  (`_litellm_proxy_vendor.deployment_route`: `custom_llm_provider`, else the
  first segment of `litellm_params.model`, else OpenAI name inference for
  bare names; never `base_model`), and an `api_base` that is unset or an
  `api.openai.com` host (`/model/info` returns `api_base`, also to virtual
  keys);
- the model family is GPT-5 or later, o-series or Codex (the native
  provider's rule, via `is_gpt_5_model`/`is_o_series_model`);
- model info was fetched, `num_choices` is unset and `emulate_tools` is off.

Unrecognized names are not treated as frontier codenames (unlike the native
provider): a proxy can send every `openai/` deployment to another server with
`OPENAI_API_BASE`, which `/model/info` does not show. A codename qualifies
through `model_info.base_model`, which the model info gate asks for. Azure is
excluded until verified. Responses to the OpenAI route streams by default
(#43010 affects Anthropic only).

Verified live (gpt-5-mini, gpt-5.5, gpt-6-astra): encrypted reasoning
replays across a tool loop, streamed and not; `store` is false; built-in web
search works; `none` is dropped, `xhigh`/`max` are lowered to `high` for
gpt-5-mini; cost includes cache reads at the cache rate; the request body
matches `openai/gpt-5.5` except `stream`. Encrypted reasoning from one OpenAI
account is accepted by another (turn 1 on one account, turn 2 on another,
through the proxy and directly), so a proxy pooling keys from several
accounts under one alias is fine.

Of OpenAI's hosted tools, only web search is used through the proxy
(`LiteLLMProxyAPI._as_function_tool`): code interpreter, computer use,
remote MCP and tool search were not verified through LiteLLM, so they are
sent as function tools, as on Chat Completions. `computer()` is always sent
verbatim, because the Responses code otherwise requires `store=True` for any
`computer()` tool; a verbatim tool no longer triggers that
(`openai_responses.py`).

**Key and team aliases.** Probed with a Postgres-backed proxy:

- `/key/info` (the calling key) returns `info.aliases` and `info.team_id`;
  `/team/info?team_id=…` returns
  `team_info.litellm_model_table.model_aliases`. Both are served only at the
  proxy root (`/v1/key/info` is 404).
- LiteLLM applies aliases before routing: a key alias with the name of a
  listed model routes to the alias target, a team alias wins over a key alias
  of the same name, and aliases chain.
- The master key has no key record (404); a proxy without a database answers
  500 "Database not connected" (master key) or 400 `no_db_connection`.

So the provider fetches the aliases whenever it fetches `/model/info`
(cached per base URL and key), merges `{**key, **team}`, follows chains with
a cycle guard, and then selects deployments for the resulting name. 404 and
no-database responses mean no aliases; other failures don't stop
construction and are reported in the gate error when the alias is
unresolved. `model_alias_map` aliases appear in no listing, even for the
master key; `set_model_info` or `require_model_info=false` remain the fixes
for those.

## Phases

Each phase ends with review and approval before the next starts.

1. **Configuration and fetch.** `LITELLM_PROXY_API_BASE` alias, the
   `model_info` argument, the sync fetch with its error behavior, and the
   cache.
2. **Resolution.** The normalizer and its unit table; `canonical_name()`;
   deployment selection.
3. **Registration and gate.** `set_model_info` registration with the
   precedence and combining rules, `family`, `require_model_info`, and cost.
4. **Reasoning effort.** Rejection detection, lowering and retry, and the
   offline effort guarantee test (the shared-module refactor was dropped;
   see §6).
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
   matrix, and report LiteLLM bugs 6–8 upstream with captured payloads
   (done: #43009–#43011).
6. **Deployment findings.** §8: vendor detection, Claude `max_tokens`,
   prompt caching and cache-write cost, full tool schemas, null content for
   text-less tool call turns, the prefill error, default streaming, the
   environment variable fallbacks, the gate's `base_model` suggestion, and
   the virtual key check.
7. **Docs, CHANGELOG, live tests.** Provider docs (including `base_model`
   guidance for opaque deployments), the CHANGELOG entry, and adding the
   provider to the `slow-tests` skill.

   **PR description:** list the LiteLLM issues filed from this work, with
   links, and the behavior each one causes (strict xfail, or covered by the
   provider):
   [#43009](https://github.com/BerriAI/litellm/issues/43009),
   [#43010](https://github.com/BerriAI/litellm/issues/43010),
   [#43011](https://github.com/BerriAI/litellm/issues/43011),
   [#43012](https://github.com/BerriAI/litellm/issues/43012),
   [#43013](https://github.com/BerriAI/litellm/issues/43013),
   [#43014](https://github.com/BerriAI/litellm/issues/43014).

## Open questions

- Server-side tools (built-in web search) through the proxy: not pursued; see
  [litellm-proxy-server-tools.md](litellm-proxy-server-tools.md).
- ~~Does `/v2/model/info?model=` behave as the source suggests?~~ Answered
  (1.104, Postgres-backed proxy): `?model=` filters by exact `model_name` and
  returns 403 for a model the key may not use, but unfiltered it ignores the
  key's allowlist, it returns wildcard routes unexpanded (`anthropic/*`), and
  it omits `model_group_alias` rows. v1 stays.
- ~~Key and team aliases~~: implemented; see §9.
- ~~Default for `responses_api`~~: on for OpenAI reasoning models; see §9.
