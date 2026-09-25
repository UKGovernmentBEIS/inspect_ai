# LiteLLM proxy: server-side web search

> **Status:** deferred until the initial `litellm-proxy` PR lands; not started.
> Background: [litellm-proxy.md](litellm-proxy.md).

## Context

Through `litellm-proxy`, Inspect never uses a vendor's built-in (server-side)
search today:

- **Chat path:** it sends every tool as a function tool. A plain `web_search()`
  (built-in providers only) sent to Claude fails at execution with "No valid
  provider found.", although the same task works on `anthropic/…`.
- **Responses path:** OpenAI search works, but that path is off by default.

LiteLLM 1.104 can carry Anthropic and Gemini server tools on its chat API, but
lossily:

- **Anthropic calls:** server calls come back as ordinary `tool_calls` (only the
  `srvtoolu_` id marks them).
- **Anthropic results:** results go in `provider_specific_fields`, text is
  flattened, and block order is lost.
- **Replay:** LiteLLM rebuilds order heuristically ("interleaved mode", #23047),
  and Anthropic checks thinking signatures by position.
- **`pause_turn`:** mapped to "stop".
- **Streaming:** the stream re-sends result lists without `index`, which crashes
  the OpenAI SDK accumulator (`openai/lib/streaming/_deltas.py:40-47`; checked).
- **Gemini:** search maps to `googleSearch`. Mixed with function tools it needs
  `include_server_side_tool_invocations` (Gemini 3+), and the invocations are
  replayed from `provider_specific_fields`.
- **Bedrock Converse:** silently drops hosted tools.

Decisions (user): **web search only**; vendors **Anthropic (direct, Vertex) +
Gemini + Responses as the default for OpenAI upstreams**; ships **in this PR
as a new phase** (before finishing docs).

## Phase 0: Spike (go/no-go; scratchpad scripts, reusable fakes in tests/test_helpers)

- **S1 Offline, fake upstream + proxy (`run_litellm_proxy(capture=True)`,
  custom router in `stubs.py`).**
  - **Fixture turn:** thinking(sig1), server_tool_use A, result A,
    thinking(sig2), text + citation, server_tool_use B, result B, text.
  - **Variants:** redacted_thinking, trailing client tool_use, unanswered
    server_tool_use (paused), `caller` fields.
  - **Record:**
    - (a) the non-streamed client message: `tool_calls` index/ids, psf keys,
      finish_reason;
    - (b) raw streamed chunks: is `delta.provider_specific_fields` forwarded,
      are lists re-sent, is chunk order = block order; reproduce the SDK
      RuntimeError;
    - (c) the replayed upstream request for mode A and mode B (below): exact
      block order, what list mode drops (redacted_thinking, citations,
      `caller`), and the unanswered-`srvtoolu_` fallback to a plain `tool_use`.
- **S2 Live, direct Anthropic SDK (model behavior).**
  - **Setup:** Opus 5.5 and Sonnet 5 at high/max, Sonnet 4.5 with a thinking
    budget; web_search 20250305 and 20260209; ~30 multi-search prompts plus 5
    prompts that force >10 searches.
  - **Measure per response:**
    - number of thinking blocks and searches;
    - whether LiteLLM's interleave heuristic (re-implemented from
      factory.py:2610-2645) reproduces the original order;
    - `pause_turn` rate;
    - whether results are adjacent to their calls;
    - redacted_thinking rate.
- **S3 Live replay acceptance.** For S2 responses where the heuristic order
  differs, replay each three ways: original, heuristic, all-thinking-first.
  - **Contexts:** a user follow-up, and a trailing client tool_use +
    tool_result.
  - **Record:** any 400s.
- **S4 Live through the proxy.**
  - **Claude:** Anthropic direct and Vertex, streamed and not: psf present in
    SSE, `pause_turn`, web_fetch accepted on Vertex.
  - **Gemini 3.x:** googleSearch + a function tool +
    `include_server_side_tool_invocations`. Is AUTO accepted, how are
    invocations streamed (full or increments), is the replay accepted.
  - **Gemini 2.5:** search only.
  - **OpenAI:** gpt-5.5 on Responses, streamed and not: `web_search_call`
    items, citations, replay accepted.

| Result | Decision |
|---|---|
| S3 heuristic order ever rejected | Mode B required for thinking turns; streaming forced when Claude web search is claimed; non-streamed turns with ≤1 thinking block → mode A, else warn |
| S3 always accepted | Mode A safe everywhere; mode B still the default when order is known |
| S1b psf stripped from SSE | Force non-streaming + mode A for web search turns |
| S2 results not adjacent to their calls | Store one block per content item instead of one pair per search |
| S2 `pause_turn` > ~1% | Continuation loop required |
| S4 Gemini rejects AUTO with mixed tools | Pass tool_config via extra_body, or allow search-only on Gemini 3 |

Stop after the spike and review the results with the user before building.

## Design

**Claiming `web_search()`** (in `resolve_tools`/`tools_to_openai`; skipped when
`config.internal_tools is False`):

- **Routes:** new `upstream_routes(deployments)` in `_litellm_proxy_vendor.py`.
  It reads the real route from each deployment's `custom_llm_provider` or the
  first segment of `litellm_params.model`, not `self._resolution.upstream`,
  which `base_model` overrides.
- **Claude:** vendor `anthropic`, routes ⊆ {anthropic, vertex_ai}, options key
  `"anthropic"`. Send the native hosted dicts: `web_fetch_20250910` +
  `web_search_20250305` by default, with 20260209 dynamic filtering gated on the
  spike, because LiteLLM drops `caller` on rebuild. Codenames are eligible
  unless the model is a known legacy Claude 3.
- **Gemini:** vendor `google`, routes ⊆ {gemini, vertex_ai}, key `"gemini"`.
  Send a `{"googleSearch": camelCase(options)}` tool dict.
  - Search + function tools needs Gemini ≥3 (regex on `model_family()`), else
    the native `ValueError` text. With mixed tools, send
    `include_server_side_tool_invocations=True`.
  - Search only: no `tool_choice`, via a small new hook
    `OpenAICompatibleAPI.chat_tool_choice()` at openai_compatible.py:270.
- **OpenAI:** Responses by default. In `__init__`, when `responses_api` is
  unset, the vendor is `openai`, all routes ⊆ {openai, azure} and
  `emulate_tools` is off. Existing `maybe_web_search_tool(model_family, …)` then
  applies unchanged. Stream Responses for these routes (#43010 is Anthropic
  only).
- **Nothing claims it:** if no external key (tavily/exa/google) either, raise a
  `PrerequisiteError` before sending. The message names the reason (Bedrock
  drops hosted tools, the vendor has no built-in search, `responses_api=false`
  for OpenAI, `internal_tools=False`) and the fix (`web_search("tavily")` or a
  supported deployment).
- **SDK-free native helpers:** new `_anthropic_web_search.py` (SDK types only
  under `TYPE_CHECKING`). Move in `_supports_web_search`, `_is_claude_5`,
  `_web_search_tool_params` (plain dicts), `_cleared_result_block_param`, and a
  family-level `is_claude_frontier_family()`. `anthropic.py` re-imports them
  under the same names. Parity test; no native behavior change.

**Response mapping** (new `_litellm_proxy_server_tools.py`; hooked in
`chat_choices_from_completion`):

- **Tool calls:** `split_server_tool_calls()` removes `srvtoolu_` calls named
  web_search/web_fetch from `tool_calls` before `parse_tool_call`, so they are
  never executed and no `role:tool` is ever sent for them.
- **ContentToolUse:** one per search, with results matched by `tool_use_id`
  from `psf.web_search_results`.
  - `result` uses the native encoding (anthropic.py:4400, :4254), so logs are
    interchangeable.
  - `internal={"litellm_anthropic": {use (raw, incl. caller), result_type,
    result_extra, ordered}}`, following the Google precedent (survives logs and
    checkpoints, no ContextVar).
  - Gemini: `internal={"litellm_gemini": invocation}`.
- **Content order:**
  - streamed: the recorded block order;
  - non-streamed: LiteLLM's layout [reasoning, tool uses, text] with
    `ordered=False`.
- **Citations:**
  - Anthropic `psf.citations` `web_search_result_location` → `UrlCitation`
    (dict-based port of `_anthropic_citations.to_inspect_citation`);
  - Gemini `message.annotations` url_citation → `UrlCitation`.
- **`stop_reason`:** recompute after filtering (no client calls left →
  "stop").
- **`pause_turn`:** detected by an unanswered server call, or a stream ending
  on a server block with no client call. A continuation loop in `generate`
  merges head and tail (as anthropic.py:1145-1180), is capped at 5, and needs
  mode B. A non-streamed paused turn warns and returns `stop_reason="unknown"`.

**Streaming** (`_litellm_proxy_reasoning.py`, or a split `_litellm_proxy_stream.py`):

- **Stripping extras:** generalize `without_thinking_block_deltas` to remove
  every LiteLLM extra from deltas before the SDK accumulator sees them:
  - `thinking_blocks`;
  - psf `web_search_results`/`web_search_calls`/`tool_results`/
    `code_interpreter_results`/`citation`/`server_side_tool_invocations`;
  - `delta.annotations`.
- **New per-choice state:**
  - `ServerToolsAccumulator`: de-duplicates re-sent lists by `tool_use_id`/`id`
    and attaches citations to the current text segment;
  - `BlockOrderRecorder`: records slots in chunk order.
- **Final message:** `with_streamed_thinking_blocks` → `with_streamed_extras`
  sets the fields and the block order on the final message.

**Replay** (`_litellm_message_to_openai`):

- **Mode B (default when every server item is `ordered` and no reasoning is
  redacted):** list-form `content` in `message.content` order: thinking blocks,
  use + rebuilt result, text. No `thinking_blocks` field. Client `tool_calls`
  are appended after the list (correct).
- **Mode A (otherwise):** string content + `thinking_blocks`, plus
  `tool_calls` for the `srvtoolu_` ids and rebuilt results in
  `psf.web_search_results`. Warn once if more than one thinking block and S3
  showed the heuristic is unsafe.
- **Gemini:** rebuild `psf.server_side_tool_invocations`, merged with
  `thought_signatures`.
- **Cleared results** (`is_result_cleared`): rebuilt in cleared form (shared
  helper).
- **ContentToolUse without our `internal` key:** dropped with `warn_once`
  (today's behavior).
- **Caching:** `_litellm_proxy_caching.py`:
  - add server blocks to cacheable types, and skip thinking blocks in `_mark`;
  - order tools hosted first and function tools last;
  - with only hosted tools, put `cache_control` on the dict directly.

## Implementation phases (after spike approval; pause for review after each)

1. SDK-free Anthropic helpers + parity test; routes, claiming, request tool
   dicts, Gemini params, `chat_tool_choice` hook, prerequisite error, OpenAI
   Responses default + streaming.
2. Non-streamed mapping + mode A replay (Anthropic, Gemini), citations,
   `stop_reason`.
3. Streaming extras stripper, accumulators, block order, mode B replay,
   `pause_turn` continuation, caching block types.
4. Docs (providers.qmd LiteLLM section: server tools; remove the limitation
   note), design doc section, CHANGELOG wording, slow-tests skill.

## Critical files

- `src/inspect_ai/model/_providers/litellm_proxy.py`, `_litellm_proxy_reasoning.py`,
  `_litellm_proxy_vendor.py`, `_litellm_proxy_caching.py`
- new `_litellm_proxy_server_tools.py`, new `_anthropic_web_search.py`
  (moved from `anthropic.py`, re-imported there)
- `openai_compatible.py` (one `chat_tool_choice` hook)
- tests: new `tests/model/providers/test_litellm_proxy_web_search.py`;
  `tests/test_helpers/litellm_proxy/stubs.py`, `artifacts.py`
  (`check_anthropic_server_tool_replay`); `test_litellm_proxy_reasoning.py`
  live matrix

## Verification

- **Unit (no Docker):**
  - claiming table (vendor × route × options × `internal_tools`);
  - prerequisite error text;
  - hosted dicts equal the native `_web_search_tool_params` output;
  - `split_server_tool_calls`/`stop_reason`;
  - citations;
  - the stream stripper on hand-built chunks: re-sent lists, no RuntimeError,
    block order;
  - mode A/B message building: redacted blocks force A, cleared results,
    foreign `ContentToolUse`;
  - Responses default (`None`→True only for openai/azure; explicit False kept).
- **Offline Docker:** the S1 fixtures as a matrix (stream × plain / redacted /
  client-tool mix / pause), asserting the exact upstream request order. Strict
  xfails where LiteLLM loses data (redacted in list mode, `caller`). Gemini
  fake with groundingMetadata and toolCall/toolResponse parts.
- **Live (`--runapi`, proxy image):**
  - web search tool loops for Opus 5.5, Sonnet 5, Vertex Claude,
    gemini-3.1-pro (mixed tools), gemini-2.5-flash (search only), and gpt-5.5
    on Responses (streamed and not);
  - Bedrock asserts the prerequisite error.
- **Regression:** `test_anthropic_web_search.py`,
  `test_anthropic_dynamic_filtering.py`,
  `tests/model/test_compaction_edit_server_tools.py`, the full litellm suites
  (`--runslow`), trio for the async changes; mypy over src+tests, ruff.

## Risks

- **Positional signatures (S3):** if the heuristic order is rejected,
  non-streamed Claude web search with several thinking blocks is best-effort
  and streaming becomes effectively required.
- **LiteLLM drift:** detect behavior, not versions; keep strict xfails.
- **Dynamic filtering (20260209) deferred:** frontier Claude gets simpler
  search than on the native provider (documented).
- **Search cost:** search request cost (`usage.server_tool_use`) is recorded in
  metadata only; not added to cost.
- **Load-balanced mixed routes / `model_info=false`:** conservative claiming;
  the error says how to proceed.
