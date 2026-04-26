# Deep Agent Harness for Inspect

## Design

We're planning on adding a `deepagent()` to Inspect as a peer to `react()`. This would be an alternate top-level agent that bundles the patterns popularized by Claude Code, OpenAI Codex CLI, LangChain deepagents, and Pydantic AI deepagents into a single batteries-included entry point. This RFC describes the proposed design and asks for community feedback before we commit to an API.

### Background

The `react()` loop — model + tools + scaffolding — handles short-horizon tasks well, but tends to flatten under longer horizons: agents lose the plot, exhaust their context window with intermediate tool output, and don't reliably plan or decompose work. The "deep agent" pattern, which emerged from Claude Code and was generalized by LangChain and others, addresses this with four ingredients:

1. **A planner / todo tool:** Explicit, model-managed task decomposition.

2. **A persistent scratchpad:** Place to offload large intermediate results out of the message history (a virtual filesystem in LangChain/Pydantic, real files in CC and Codex).

3. **Subagent delegation:** Spawn isolated workers with their own context windows; only their summary returns to the parent.

4. **A detailed system prompt:** Opinionated instructions that teach the model when to use each of the above.

Inspect already has the underlying machinery for most of this: `react()` provides the agent loop, the `memory()` tool plus skills handle context engineering, sandboxes provide a real filesystem, `as_tool(agent)` turns any agent into a tool, `update_plan()` is a todo-style planner, and limits/spans/compaction are wired through. What's missing is the opinionated assembly: a single entry point, the canonical subagent set, the default system prompt, and a couple of naming alignments with the broader deep-agent vocabulary.

### Proposed API

``` python
from inspect_ai.agent import deepagent, research, plan, general

agent = deepagent(
    tools=[...],                      # additional tools beyond defaults
    subagents=[                       # default subagents
        research(), plan(), general()
    ],  
    todo_write=True,                  # planner tool
    memory=True,                      # context-engineering tool
    skills=[...],                     # additional skills
    instructions="...",               # additional sysprompt instructions
)
```

`deepagent()` is a factory that returns an agent — usable anywhere `react()` is usable, including as a solver, as a subagent inside another `deepagent()`, or as a tool via `as_tool()`.

### Key Design Decisions

#### Three built-in subagents: `research()`, `plan()`, `general()`

``` python
subagents=[
    research(),   # read-only information gathering
    plan(),       # structured planning, no execution
    general(),    # full tools, isolated context for noisy work
]
```

Each is a factory function that returns a `subagent()` configured with appropriate tools, prompt, and permissions. All three accept additive customization (`instructions=`, `extra_tools=`, `model=`).

**Comparison to prior art:**

| Framework              | Built-in subagents                        |
|------------------------|-------------------------------------------|
| Claude Code            | `Explore`, `Plan`, `general-purpose`      |
| LangChain `deepagents` | `general-purpose` only                    |
| Pydantic `deepagents`  | `research` only                           |
| Codex CLI              | None — user defines via `[agents]` config |
| **Inspect (proposed)** | `research`, `plan`, `general`             |

**Naming notes:**

- `research()` over `explore()`: we expect a meaningful share of evals built on `deepagent()` to be AI-Scientist-flavored (literature synthesis, web research) rather than codebase-flavored. `explore` reads awkwardly there. Pydantic-deep also blesses `research` as its single default. The underlying behavior — read-only delegation for information gathering — is the same as CC's Explore.
- `plan()` matches CC directly.
- `general()` is the shorter form of CC/LangChain's `general_purpose`. No semantic loss; consistent with the other one-word factories.

#### The `subagent()` primitive

For fully custom subagents:

``` python
from inspect_ai.agent import subagent

def reviewer(model="anthropic/claude-sonnet-4"):
    return subagent(
        name="reviewer",
        description="Reviews code for security and correctness.",
        prompt="...",
        tools=[grep(), read_file()],
        model=model,
    )

agent = deepagent(subagents=[research(), plan(), general(), reviewer()])
```

Internally, `subagent()` returns a `Subagent` configuration object — a typed blueprint analogous to how `ToolDef` relates to `Tool`. The actual `Agent` is constructed fresh by the `task()` multiplexer at dispatch time via `react()`. The `Subagent` type captures name/description metadata for `task()` multiplexing, fork mode, tool subset, and other dispatch configuration.

#### Subagent dispatch: isolated vs forked

Subagents support two dispatch modes, corresponding to Inspect's existing `as_tool()` and `handoff()` primitives:

- **Isolated** (default) — the subagent runs with a fresh message history. The parent sends a prompt; only the subagent's summary returns. This is the standard CC/LangChain pattern and is what `as_tool()` provides.

- **Forked** — the subagent inherits the parent's full message history including the system prompt. The trailing assistant message (in-flight tool call) is stripped, and the subagent's instructions (if any) plus the task prompt are appended as a user message. This preserves the provider prompt cache on all providers since the message prefix is unchanged. Only the subagent's final output returns to the parent. `prompt` is optional for forked subagents — omit it for a transparent fork that continues as the parent. Use the same model or model family when forking.

Claude Code recently added fork semantics to its general-purpose agent. We expose the same choice on `subagent()`:

``` python
def reviewer():
    return subagent(
        name="reviewer",
        description="Reviews code for security and correctness.",
        prompt="...",
        tools=[grep(), read_file()],
        fork=False,  # default: isolated context
    )
```

The `fork` parameter controls which dispatch primitive is used under the hood. When `fork=False` (the default), the subagent runs with isolated context via `run()` — only the summary returns. When `fork=True`, the subagent inherits the parent's full message history (including system prompt) with only the trailing assistant message stripped. The subagent's instructions (if any) are prepended to the task prompt in a user message appended after the cached prefix, preserving the prompt cache on all providers. `prompt` is optional for forked subagents. The child runs via `react(prompt=None)` so it doesn't add its own system message. Use the same model or model family when forking.

The built-in subagents default as follows:

| Subagent       | Default `fork` | Rationale |
|----------------|----------------|-----------|
| `research()`   | `False`        | Information gathering is self-contained; isolated context keeps the parent lean. |
| `plan()`       | `False`        | Planning from a clean slate avoids anchoring on noisy intermediate output. |
| `general()`    | `False`        | Isolated by default — avoids context rot and provides predictable behavior. |

All three accept `fork=True` as an override.

**Why isolated is the default for `general()`:** Claude Code, LangChain deep agents, and Codex CLI all default to isolated subagents. Isolation prevents context rot (quality degradation after ~200k tokens of accumulated history), enables true parallelism, and provides predictable behavior. For eval workloads — which are batch jobs where reproducibility matters — isolation is the safer baseline.

**When to use `fork=True`:** Forked dispatch is valuable when the subagent needs substantial background from the parent conversation without re-explanation, when the parent context is still fresh (well under context window limits), and when using the same model family (to preserve prompt cache). In forked mode, the parent's system prompt and full message history are preserved verbatim, and the subagent's instructions (if any) are appended as a user message — keeping the provider prompt cache intact on all providers. Use `general(fork=True)` to opt into this behavior.

#### The `task()` tool

`deepagent()` exposes subagents to the model via a single multiplexer tool (`task`), matching CC and Pydantic-deep convention. The tool takes `(description, subagent_type, prompt)` and dispatches to the named subagent. This keeps the model's tool list small as more subagents are added — the enumeration grows in the `subagent_type` parameter description, not the tool list itself.

`as_tool(agent)` remains available as a primitive for users who prefer per-subagent tool exposure (better when there are 1–2 specialized subagents and you want maximum descriptive room).

#### State inheritance

Default behavior matches the convergent pattern across CC, LangChain, and Pydantic-deep:

- **Sandbox** — shared (already true per-sample in Inspect).
- **Memory** — shared, read by default, write opt-in per subagent. `research()` and `plan()` get `memory(readonly=True)`; `general()` gets full read-write `memory()`. Custom subagents declare explicitly. Note: `memory(readonly=True)` is a new mode that must be implemented — the current `memory()` tool supports all CRUD operations.
- **Skills** — composable across parent and subagents. `deepagent(skills=[...])` defines parent skills available to the top-level agent. Each subagent can also define its own skills via `skills=`. At dispatch time, parent and subagent skills are merged into a single `skill()` tool with instance-scoped storage (no store contention). A subagent with `skills=[C]` and a parent with `skills=[A, B]` sees all three skills.
- **Message history** — isolated (this is what subagents are *for*).
- **Tools** — subset declared by the subagent's definition.

#### Subagent excursions

Inspect's `span(type="agent")` already renders subagent work as swimlanes in the log viewer. The `task()` tool dispatch will open a span automatically — no new viewer work needed. Limits (`token_limit`, `message_limit`, `time_limit`, `cost_limit`) apply globally across the parent and all subagent excursions.

#### System prompt

The system prompt is the spine of the deep-agent pattern. It lives as string constants in a dedicated module (`prompt.py`) with assembly logic that composes layers based on configuration. Users can extend additively with `instructions=` (90% case) or fully replace with `prompt=` (escape hatch).

The subsections below analyze the system prompts shipped by Claude Code, Codex CLI, LangChain deepagents, and Pydantic AI deepagents — what they share, where they diverge, and implications for Inspect.

##### Scale and structure

The four frameworks span a wide range of prompt size and modularity:

| Framework   | Approx. size | Structure |
|-------------|-------------|-----------|
| Claude Code | Very large (~160 component files) | Modular: assembled at runtime from categorized markdown fragments (core behavior, tool descriptions, agent dispatch, memory, git safety, formatting). Subagent prompts are separate files. |
| Codex CLI   | ~200 lines | Single monolithic markdown file. Focused and concise. |
| LangChain   | ~60 lines (base) + ~80 lines (task dispatch) | Two constants: `BASE_AGENT_PROMPT` for core behavior, `TASK_SYSTEM_PROMPT` for subagent dispatch instructions. |
| Pydantic AI | ~100 lines | Single `BASE_PROMPT` constant. Comprehensive but self-contained. |

##### What they all share

Despite significant differences in scope, all four converge on a core set of behavioral instructions:

1. **Action bias.** All four tell the model to act rather than narrate intent. "Don't say 'I'll now do X' — just do it" appears nearly verbatim in LangChain, Pydantic, and CC. Codex expresses this through its "just do it" task execution style.

2. **Verify-iterate loops.** All four include some form of "your first attempt is rarely correct — iterate." The loop structure varies (CC: implicit in tool usage; Codex: implicit; LangChain: understand→act→verify; Pydantic: research→understand→implement→verify→retry) but the principle is universal.

3. **Conciseness.** Every prompt instructs the model to be direct and avoid preamble. CC and Codex add specific formatting rules; LangChain and Pydantic keep it to a general directive.

4. **Batched tool calls.** All four instruct the model to batch independent tool calls into a single response rather than making sequential round-trips.

5. **Don't over-ask.** All four tell the model to use reasonable defaults rather than asking clarifying questions for every detail. Only ask when genuinely blocked.

##### Where they diverge

| Concern | Claude Code | Codex CLI | LangChain | Pydantic AI |
|---------|------------|-----------|-----------|-------------|
| **Workflow prescription** | Implicit — behavior emerges from many small rules | Minimal — "understand, act, verify" is implied but not codified | Explicit 3-step: understand → act → verify | Explicit 5-step: research → understand → implement → verify → retry |
| **Domain specificity** | Heavily code/git oriented (git safety protocol, commit conventions, PR creation) | Code-oriented (editing constraints, dirty worktree handling, `rg` preference) | Domain-agnostic | Code-oriented but less so than CC/Codex (file reading pagination, code quality rules) |
| **Tool-specific rules** | Extensive — dedicated instructions per tool (Read vs cat, Edit vs sed, Bash constraints) | Moderate — `apply_patch` guidance, `rg` preference | Minimal — "use tools" | Moderate — prefer specialized tools over shell equivalents, file reading pagination |
| **Formatting/presentation** | Detailed rules (markdown, code references, line numbers) | Very detailed (plain text, bullet structure, monospace rules, file reference format, final answer structure) | Minimal | Minimal — "be concise, include file:line references" |
| **Safety guardrails** | Extensive (git safety, destructive operation warnings, security vulnerability awareness, OWASP top 10) | Moderate (never revert uncommitted changes, no destructive git commands) | None | Minimal (security vulnerability awareness) |
| **Subagent dispatch** | Detailed per-agent-type instructions in the `task()` tool description | N/A (no built-in subagents) | Separate `TASK_SYSTEM_PROMPT` with lifecycle rules, when-to/when-not-to guidance, and worked examples | Brief "delegate specialized subtasks to subagents" |
| **Memory/context** | Elaborate file-based memory system with types, lifecycle rules, and anti-patterns | None | None | None |
| **Planning** | Dedicated plan mode with structured workflow | "Skip for easy tasks; don't make single-step plans; update after each step" | None (planning is a subagent concern) | None |

##### Model-adaptive prompting: lessons from Codex CLI

Codex CLI maintains separate system prompts per model generation, and the differences are instructive. The repository contains five prompt files:

| File | Model | Lines | Content |
|------|-------|-------|---------|
| `gpt_5_codex_prompt.md` | GPT-5 (Codex-tuned) | ~80 | Concise: editing constraints, plan tool (3 rules), formatting guidelines. |
| `gpt-5.1-codex-max_prompt.md` | GPT-5 (Codex Max) | ~90 | Same as above + frontend design section. |
| `gpt_5_1_prompt.md` | GPT-5.1 (generic) | ~500 | Expansive: personality, AGENTS.md spec, autonomy/persistence, user update spec with examples, detailed planning with good/bad plan examples, task execution, validation, ambition vs precision, progress updates, full formatting rules, tool documentation. |
| `gpt_5_2_prompt.md` | GPT-5.2 (generic) | ~480 | Similar to 5.1, slightly trimmed (responsiveness section emptied). |
| `gpt-5.2-codex_prompt.md` | GPT-5.2 (Codex-tuned) | ~80 | Same concise format as GPT-5 base. Adds frontend tasks. |

The pattern is stark: **models post-trained for agentic coding (the `-codex` variants) get ~80-line prompts. Generic models of the same generation get ~500-line prompts.** The Codex-tuned models have already internalized planning behavior, task execution workflow, progress updates, and tool usage patterns during post-training — the system prompt only needs to provide tool-specific constraints and domain rules. Generic models need the full behavioral scaffolding taught in-context.

Specific sections that appear only in the generic-model prompts:

- **Autonomy and persistence** — "Persist until the task is fully handled end-to-end."
- **User update spec** — detailed rules for progress updates with 8 worked examples.
- **Planning guidance** — when to plan, high-quality vs low-quality plan examples, status management rules.
- **Task execution** — "keep going until the query is completely resolved."
- **Ambition vs precision** — "be ambitious for new tasks, surgical for existing codebases."
- **Validation** — when to run tests proactively vs wait for approval.
- **Tool documentation** — `apply_patch` format specification, `update_plan` usage.

The Codex-tuned prompts assume the model already knows all of this. They only teach what the model *can't* know from training: the specific tool names available in this session, editing constraints for this environment, and presentation formatting rules.

##### Implications for Inspect

Inspect's `deepagent()` prompt must navigate two tensions the coding assistants don't face:

1. **Task-agnostic.** CC and Codex can hard-code git workflows and file-editing conventions because they know they're coding tools. Inspect agents run evals that might involve coding, research, math, web browsing, or domain-specific tool use. The prompt cannot assume the task domain.

2. **Model-agnostic.** Inspect must work well with models at very different levels of agentic post-training — from frontier models that have been heavily tuned for agentic tool use to models with minimal agentic post-training that need guidance. The prompt cannot assume a specific level of model capability.

The Codex evidence shows that what harms capable models is **prescriptive workflow** — rigid step-by-step procedures ("1. Research, 2. Understand, 3. Implement...") that constrain the model's natural decision-making and can override better-trained instincts. What *doesn't* harm them is goal-oriented framing, environmental descriptions, and tool-level documentation. This suggests a single prompt can serve both populations if written in the right style.

Key design principles for Inspect's system prompt:

1. **Layer the prompt.** Follow CC's modular approach — not its scale. Separate the prompt into composable layers:
   - **Core behavior** (action bias, verify-iterate, conciseness, batched tool calls) — always included.
   - **Tool dispatch** (when to use `task()`, how to delegate, when not to) — included when subagents are configured.
   - **Domain-specific instructions** — provided by the user via `instructions=`, not baked in.

2. **Write goals, not procedures.** The scaffolding that weaker models need (planning, persistence, verification) can be included without harming capable models if framed as expectations rather than prescribed steps. Compare:

   - *Prescriptive (harms capable models):* "Follow these steps: 1. Research the environment. 2. Read relevant files. 3. Understand patterns. 4. Implement changes. 5. Verify. 6. Retry on failure."
   - *Goal-oriented (safe for all):* "Complete tasks autonomously. Plan when the task is complex or multi-step. Verify your work before finishing. If verification fails, diagnose and retry rather than declaring done."

   The first constrains a well-trained model into a rigid loop it doesn't need. The second gives weaker models the right signals (plan, verify, retry) while letting capable models apply their own judgment about when and how.

3. **Push detail into tool descriptions.** Even Codex-tuned models — which need almost no behavioral scaffolding — still get tool-specific instructions. Tool descriptions are read by every model regardless of training. This is the right place for worked examples, usage heuristics, and dispatch guidance. In particular, the `task()` tool description should carry the subagent dispatch logic: when to delegate (complex, independent, context-heavy work), when not to (trivial lookups, dependent steps), and examples of good vs. unnecessary delegation. This follows LangChain's `TASK_SYSTEM_PROMPT` pattern but places it where models naturally look.

4. **Keep the core small.** The shared patterns (action bias, verify-iterate, conciseness, batched tool calls, don't over-ask) are ~20-30 lines in goal-oriented style. That's the floor. Everything above it should earn its place.

5. **Don't embed domain knowledge.** CC's git safety rules and Codex's editing constraints are valuable for coding — but they belong in the user's `instructions=` parameter or in tool-level descriptions, not in the base prompt. Inspect's prompt should teach the *pattern* (plan, delegate, verify) without assuming what the tools do.

6. **Provide the escape hatch.** The `prompt=` parameter allows full replacement for users who need complete control — researchers running novel agent architectures, or teams with heavily customized system prompts from prior work. Custom prompts can include named placeholders that `deepagent()` will inject at assembly time. Placeholders are optional — if omitted, the corresponding content is simply not included. This lets users control both *what* is included and *where* it appears in their prompt. Placeholder names and the content they expand to will be documented; likely candidates include:

   - `{core_behavior}` — the core behavior layer.
   - `{subagent_dispatch}` — subagent names, roles, and delegation guidance (generated from the `Subagent` list).
   - `{memory_instructions}` — memory/plan coordination guidance.
   - `{instructions}` — the user's `instructions=` text.

7. **Tools communicate through descriptions, not prompt injection.** When users pass tools to `deepagent()` — including custom subagents created with `handoff()` or `as_tool()` — we won't always know their capabilities (e.g., whether fork is enabled). Rather than adding an API for tools to inject content into the system prompt, we rely on the tool's own `description` field. The person who creates the tool controls its description and can communicate relevant behavior ("this agent sees your full conversation history" vs "this agent starts with a fresh context"). This is consistent with principle #3 above and avoids prompt bloat from many tools each injecting content. Cross-tool coordination guidance (e.g., "use memory to offload large findings, use the plan to track high-level progress") belongs in the core prompt layer, which `deepagent()` assembles.

### Additional Capabilities

The following capabilities emerged from a survey of LangChain deepagents, Pydantic AI deepagents, Codex CLI, and the broader multi-agent research literature. Some are already present in Inspect's existing primitives; others represent gaps in the current RFC. We assess each for relevance to `deepagent()` and recommend whether to include, defer, or exclude.

#### Context management and compaction

The reference frameworks implement a mix of context-management strategies to keep long-running agents within their context window:

1. **Tool output caps / truncation.** Claude Code and Codex CLI rely primarily on bounded tool output, truncation, and targeted follow-up reads. This keeps any single command or file read from flooding context, at the cost of sometimes requiring the model to issue narrower follow-up tool calls.

2. **Tool output eviction.** LangChain and Pydantic AI go further by evicting large tool outputs (>20K tokens) to the filesystem, replacing them with a short preview and a reference path. The agent can retrieve the full content later via filesystem tools if needed. This preserves more information but adds artifact lifecycle, security, and retrieval semantics.

3. **Summarization / compaction.** When the context window approaches capacity (~85-90% in LangChain/Pydantic), the frameworks trigger an LLM-generated summary that compresses the conversation while preserving key facts, then continues from the summary.

4. **Mid-turn compaction.** Codex CLI supports compaction during a streaming model response — injecting a summary mid-turn when the context limit is hit during generation.

**Inspect status:** Inspect already bounds tool output via `max_tool_output` (default 16 KiB), which prevents runaway tool results from saturating context. `deepagent()` v1 should lean into this existing behavior: read-only filesystem tools should support explicit ranges/limits, `grep()` should be bounded, and truncation messages should make it clear how to retrieve narrower context. Inspect also has compaction infrastructure (`CompactionEdit`, `CompactionTrim`, `CompactionSummary`, native provider compaction) wired through `react()`, and `deepagent()` exposes compaction configuration via the existing `compaction=` parameter. Durable large-output eviction can be considered later if capped outputs prove too lossy, but it is not a v1 requirement.

#### Parallel subagent execution

LangChain's `TASK_SYSTEM_PROMPT` heavily emphasizes launching multiple subagents in parallel: "Whenever you have independent steps to complete — kick off tasks in parallel to accomplish them faster." Claude Code does the same — models can invoke the `task()` tool multiple times in a single response.

**Inspect status:** Inspect's current `execute_tools` processes tool calls sequentially, but `task()` is marked `parallel=True` (the default). Multiple `task()` calls in one response execute one at a time in v1 but are architecturally safe — forked dispatch strips the trailing assistant message entirely (rather than repairing specific tool calls), so each child sees the same clean conversation prefix regardless of sibling calls. When parallel tool execution lands, `task()` will benefit without changes.

#### Async / background subagents

Claude Code, Codex CLI, LangChain, and Pydantic Deep Agents all support some form of background or async subagent work: launch a long-running worker, continue in the parent, inspect status, and optionally steer or cancel the child.

**Inspect status:** Out of scope for v1. `deepagent()` dispatch is synchronous: the parent blocks until the child returns its summary. Async/background subagents require new lifecycle concepts (task handles, status, cancellation, UI/log presentation, and possibly durable state) and should be designed as a separate feature.

#### Cost-aware model routing

The RFC mentions `model=` per subagent but doesn't frame it as cost-aware routing. In practice, this is one of the highest-leverage features: route simple subtasks (file reading, grep, summarization) to cheaper/faster models and reserve expensive models for complex reasoning. Research reports 85% cost reduction while maintaining 95% quality.

**Inspect status:** Already supported — `subagent(model=...)` and `research(model=...)` etc. allow per-subagent model selection. Each built-in subagent has different cognitive demands (e.g., `research()` might use a cheaper model, `plan()` a stronger one, `general()` the main agent model), so routing is best configured per-subagent rather than with a blanket default.

#### Limits and budgets

Long-horizon agents need hard resource limits: message counts, tokens, wall-clock time, working time, and cost. LangChain and Pydantic expose these through middleware/capabilities; Inspect already has them as core task and agent primitives.

**Inspect status:** Covered. Sample-level limits apply across the parent and all subagent excursions, and `subagent(limits=[...])` can apply additional scoped limits to a child agent. This gives authors both a global budget for the whole sample and per-subagent budgets for expensive or exploratory workers.

#### Tool call repair

Pydantic AI's `PatchToolCallsCapability` detects orphaned tool calls (calls with no matching result) and orphaned tool results (results with no matching call), injecting synthetic responses to keep the conversation well-formed. This matters when models produce malformed tool-use sequences or when errors interrupt tool execution.

**Inspect status:** Inspect's `react()` loop already handles tool execution errors, but orphaned-call repair is a resilience feature worth considering. If models occasionally produce tool calls that fail silently, the conversation history becomes inconsistent. Lower priority but worth noting for robustness.

#### Checkpointing integration

The separate [Inspect Checkpointing design](../design/checkpointing.md) proposes mid-sample durability for long-running evals. `deepagent()` is a primary consumer of this capability — deep agent evals are exactly the ones that run for hours or days and need crash recovery.

**Inspect status:** The checkpointing design is proceeding in parallel. `deepagent()` should accept a `checkpoint=CheckpointConfig(...)` parameter, consistent with `react()`. The integration is straightforward — checkpoints fire at turn boundaries in the agent loop, which `deepagent()` inherits from `react()`.

#### Reflection and self-critique

Recent research (Multi-Agent Reflexion, dual-loop reflection) shows that having agents critique their own output before returning it to the parent can improve quality. The pattern: agent produces a result, a critic (possibly the same model, possibly a cheaper one) evaluates it, and if the critique identifies issues, the agent revises.

**Inspect status:** Not in the RFC. This is an interesting pattern but may be better left to users who can implement it as a custom subagent (e.g., a `reviewer()` subagent) rather than baked into `deepagent()` defaults. The `subagent()` primitive is flexible enough to support this. We should mention it as a documented pattern rather than a built-in feature.

#### Hooks and middleware

LangChain implements a composable middleware pipeline (PlanningMiddleware, FilesystemMiddleware, SubAgentMiddleware, SummarizationMiddleware, etc.). Pydantic AI has 8 lifecycle hook events (PRE_TOOL_USE, POST_TOOL_USE, BEFORE_RUN, AFTER_RUN, etc.). Codex CLI has a hook system that can inject context back into the prompt.

**Inspect status:** Inspect does not have a middleware system for agents, and adding one would be a significant new abstraction. However, many of the use cases that middleware serves in other frameworks are already covered by Inspect's existing primitives: compaction handles context management, spans handle observability, limits handle resource control, and tool-level logic handles approval. We should not add middleware to `deepagent()` — it would add complexity without clear benefit given Inspect's existing architecture.

#### Human-in-the-loop

LangChain provides granular `interrupt_on` configuration per tool, allowing agents to pause for human approval before destructive actions. Codex CLI has a Guardian approval system with 7 approval types.

**Inspect status:** Less relevant for eval workloads, where the goal is typically autonomous execution. Inspect's sandbox isolation provides the safety boundary. If needed, users can implement approval logic at the tool level. Not recommended for `deepagent()` defaults.

### Open Questions

We'd particularly value input on:

1. **Built-in subagent set.** Are `research`, `plan`, `general` the right three? Should we ship more (e.g., `reviewer`, `tester`)? Fewer? Different names?

2. **`research()` vs `explore()`.** Our reasoning is above — does this match the use cases you'd build on `deepagent()`?

3. **What's missing.** Are there deep-agent patterns you've found valuable in other frameworks that aren't covered above?

#### Resolved

- **Memory write defaults.** `research()` and `plan()` are read-only; `general()` gets read-write. Custom subagents declare explicitly.
- **Recursion depth.** Default cap at 1 level (matching CC and Codex), configurable via `max_depth=`.
- **`task()` vs `as_tool()`.** `task()` multiplexer is the default. `as_tool()` remains available for users who prefer per-subagent tool exposure.
- **Naming.** `deepagent()`.

### Prior Art

- [Claude Code subagents documentation](https://code.claude.com/docs/en/sub-agents)
- [LangChain `deepagents`](https://github.com/langchain-ai/deepagents) and [docs](https://docs.langchain.com/oss/python/deepagents/overview)
- [Pydantic `deepagents`](https://github.com/vstorm-co/pydantic-deepagents)
- [OpenAI Codex CLI subagents](https://developers.openai.com/codex/subagents)
- ["Deep Agents" — LangChain blog post](https://blog.langchain.com/deep-agents/)

## Implementation Blueprint

### Outline

Sections are ordered by dependency — each builds on the ones above it.

#### 1. `Subagent` type and `subagent()` factory

`subagent()` returns a `Subagent` — a typed configuration object, not an `Agent` or `Tool`. This is analogous to how `ToolDef` relates to `Tool`: `Subagent` is a blueprint; the actual `Agent` is constructed fresh by `task()` at dispatch time via `react()`.

``` python
from inspect_ai.agent import subagent
from inspect_ai.util import token_limit

reviewer = subagent(
    name="reviewer",
    description="Reviews code for security and correctness.",
    prompt="...",
    tools=[grep(), read_file()],
    model="anthropic/claude-sonnet-4",
    limits=[token_limit(50_000)],
    memory="readonly",  # "readwrite", "readonly", or False
    fork=False,
)
```

`Subagent` holds: name, description, prompt, tools, model, fork, limits, memory mode, and compaction. The memory parameter is `memory: Literal["readwrite", "readonly", False] = "readonly"` — `"readonly"` gives the subagent `memory(readonly=True)`, `"readwrite"` gives full `memory()`, and `False` disables memory entirely. **Precedence:** if `deepagent(memory=False)` is set, memory is disabled for the top-level agent and all subagents regardless of their individual `memory` setting. The optional `limits` parameter takes scoped Inspect limits (e.g. `token_limit`, `message_limit`, `time_limit`, `cost_limit`) that apply to the child agent invocation. Skills compose across parent and subagents: parent skills from `deepagent(skills=...)` merge with subagent-specific skills from `sa.skills` at dispatch time, with instance-scoped `skill()` tool stores to avoid contention. The `task()` tool reads this metadata to build its parameter schema and to configure `react()` at dispatch time.

**Recursion guard.** Depth is tracked via closure — the current depth is closed over when constructing the child agent's tool set, so each dispatch path carries its own depth counter. This is parallel-safe: sibling subagents dispatched concurrently (in a future parallel v2) won't interfere with each other's depth tracking. Default cap at 1 level, matching CC and Codex. Configurable via `deepagent(max_depth=...)`. Enforcement is by omission: when constructing the `react()` agent at max depth, the `task()` tool is simply not included in the tool list. The model never sees a tool it can't use.

#### 2. `task()` tool

The multiplexer. Takes a list of `Subagent` objects at construction time and exposes them to the model as a single tool.

``` python
# Constructed internally by deepagent():
task_tool = task(subagents=[research(), plan(), general(), reviewer()])
```

**Parameters exposed to the model:** `(description: str, subagent_type: str, prompt: str)`. The `subagent_type` enum is generated dynamically from the `Subagent` names and descriptions.

**Description generation.** A standalone function `subagent_dispatch_description(subagents: list[Subagent]) -> str` generates the `task()` tool description from the registered subagents. It produces the enumeration of available `subagent_type` values with their descriptions, plus when-to/when-not-to dispatch guidance and worked examples. The `task()` constructor calls this to set its description, keeping the tool description always in sync with the actual subagent list.

**Dispatch mechanics:**
- Look up the `Subagent` by `subagent_type`.
- Construct a `react()` agent from the `Subagent` config.
- If `fork=False`: invoke via `as_tool()` semantics — isolated context, summary returns as tool result.
- If `fork=True`: the `task()` tool keeps the parent's full message history (including system prompt), strips only the trailing assistant message, and appends the subagent's instructions + task prompt as a user message. The child runs via `react(prompt=None)` and `run()`, preserving the prompt cache on all providers. Only the final output returns via `_extract_result()`. Wrapped in `timeline_branch()` for log viewer rendering.
- The `task()` tool creates `span(type="agent")` for each dispatch explicitly. (Unlike `as_tool()`/`handoff()` which create spans automatically, `task()` manages its own dispatch lifecycle.)
- V1 dispatches subagents sequentially. Both isolated and forked dispatch are architecturally safe for future parallel execution — forked subagents receive a copy of the parent's messages and only their filtered result returns. See section 8 for the deferred parallel execution plan.

#### 3. Built-in subagent factories: `research()`, `plan()`, `general()`

Each returns a `Subagent` with opinionated defaults. All accept additive customization via `instructions=`, `extra_tools=`, `model=`, `fork=`, and `limits=`.

**`research()`** — Read-only information gathering.
- Tools: read-only defaults (see below).
- Fork: `False` (isolated context).
- Memory: read-only.
- Skills: does not inherit top-level skills.
- Prompt: goal-oriented, emphasizes gathering and synthesizing information.

**`plan()`** — Structured planning, no execution.
- Tools: same read-only defaults as `research()`.
- Fork: `False`.
- Memory: read-only.
- Skills: does not inherit top-level skills.
- Prompt: goal-oriented, emphasizes decomposing work and producing a structured plan.

**`general()`** — Full tools, isolated context for noisy work.
- Tools: inherits parent tools (including skills) by default.
- Fork: `False` (user can opt into `True` for CC-style fork behavior).
- Memory: read-write.
- Prompt: goal-oriented, emphasizes autonomous task completion.

**Default tool sets.** `research()` and `plan()` share the same read-only tool defaults: `grep()`, `read_file()`, and `list_files()` — new standalone read-only tools to be added to Inspect's toolset. These tools are always constructible regardless of whether a sandbox is configured; they fail clearly at runtime if no sandbox is available. (These are useful beyond `deepagent()` — any eval that wants read-only filesystem access currently requires `bash()` or `text_editor()`, both of which are read-write.)

User tools passed to `deepagent(tools=[...])` are available to the top-level agent and flow down to `general()`, but do **not** automatically flow to `research()` or `plan()`. This preserves their read-only-by-default posture — if the user passes `bash()` or `text_editor()`, those mutating tools must not reach read-only subagents. Users can explicitly extend `research()` or `plan()` with additional tools via `extra_tools=`, but doing so overrides the read-only default at the user's discretion. All built-in subagents accept `extra_tools=` for additive customization.

This is a default capability boundary, not a hard security guarantee. If a user explicitly gives a read-only subagent mutating tools through `extra_tools=` or gives it read-write memory, the subagent can mutate through those capabilities. Hard isolation should be enforced through sandboxing, approval policies, or task-specific tool design.

`general()` inherits the `deepagent()`'s parent tool list (user tools + skills), minus the `task()` tool itself at max depth per the recursion guard. Memory and todo_write are added by `_resolve_tools()` at dispatch time.

**`todo_write()` tool.** A new `todo_write()` tool replaces the existing `update_plan()`, aligning with the deep-agent vocabulary used by CC and LangChain. The implementation is largely the same — a planning tool that tracks steps and progress — but renamed for consistency. `update_plan()` will be deprecated with an alias pointing to `todo_write()`.

#### 4. `deepagent()` function

The top-level assembly. Returns an `Agent` usable anywhere `react()` is usable.

``` python
@agent
def deepagent(
    *,
    tools: Sequence[Tool | ToolDef | ToolSource] | None = None,
    subagents: list[Subagent] | None = None,       # default: [research(), plan(), general()]
    todo_write: bool = True,
    memory: bool = True,                             # top-level kill switch; False disables memory everywhere
    skills: list[Skill] | None = None,
    instructions: str | None = None,
    prompt: str | None = None,                      # full replacement with placeholders
    compaction: CompactionStrategy | None = None,
    max_depth: int = 1,                             # max subagent recursion depth
    model: str | Model | None = None,
    submit: AgentSubmit | bool | None = None,
    attempts: int | AgentAttempts = 1,
    # ... other react() passthrough parameters
) -> Agent:
```

**Assembly sequence:**
1. Resolve subagents: use provided list or default `[research(), plan(), general()]`.
2. Construct `task()` tool from the subagent list.
3. Collect tools: user tools + `task()` + (optionally) `memory()` + (optionally) `todo_write()` + (optionally) skill tools.
4. Assemble the system prompt from layers (or expand placeholders if `prompt=` is provided).
5. Delegate to `react()` with the assembled tools, prompt, compaction, and other parameters.

#### 5. System prompt text asset

Stored as string constants in `prompt.py`, with assembly logic that composes the layers based on `deepagent()` configuration.

**Layers assembled by `deepagent()`:**
- **Core behavior** (~20-30 lines). Goal-oriented: action bias, verify-iterate, conciseness, batched tool calls, don't over-ask. Written as expectations, not procedures.
- **Subagent dispatch** (included when subagents are configured). Generated from the `Subagent` list — names each available subagent, its role, and provides high-level guidance on when to delegate vs. do the work directly. This gives subagent awareness more weight than the tool description alone. The detailed dispatch mechanics (parameter usage, worked examples) remain in the `task()` tool description.
- **Memory/plan coordination** (included when memory and/or todo_write are enabled). Cross-tool guidance: "Use memory to offload large intermediate results. Use the plan to track high-level task decomposition."
- **User instructions** (`instructions=` text appended at the end).

**`prompt=` full replacement.** When provided, `deepagent()` expands named placeholders and uses the result as the complete system prompt. Documented placeholders:
- `{core_behavior}` — the core behavior layer.
- `{subagent_dispatch}` — subagent names, roles, and delegation guidance (generated from the `Subagent` list).
- `{memory_instructions}` — memory/plan coordination guidance.
- `{instructions}` — the user's `instructions=` text.

Placeholders are optional — if omitted, that content is excluded.

#### 6. Public API surface

New exports from `inspect_ai.agent`:
- `deepagent` — the top-level factory.
- `subagent` — the custom subagent factory.
- `Subagent` — the typed configuration object.
- `research`, `plan`, `general` — built-in subagent factories.

The `task()` tool factory is **not** exported — it is internal to `_deepagent/task_tool.py` and constructed by `deepagent()`. This avoids a naming collision with Inspect's existing `@task` decorator. The model-facing tool is still named `"task"` in its tool definition.

No changes to existing `react()`, `as_tool()`, `handoff()`, or `Agent` APIs.

#### 7. File layout

New directory `src/inspect_ai/agent/_deepagent/`:
- `__init__.py` — package init.
- `deepagent.py` — `deepagent()` function.
- `subagent.py` — `Subagent` type and `subagent()` factory.
- `research.py` — `research()` built-in subagent factory.
- `plan.py` — `plan()` built-in subagent factory.
- `general.py` — `general()` built-in subagent factory.
- `task_tool.py` — `task()` multiplexer tool.
- `prompt.py` — system prompt text constants and assembly logic.

New tools in `src/inspect_ai/tool/_tools/`:
- `_grep.py` — `grep()` read-only search tool.
- `_read_file.py` — `read_file()` read-only file reading tool.
- `_list_files.py` — `list_files()` read-only directory listing tool.
- `_todo_write.py` — `todo_write()` planning tool (replaces `update_plan()`).

Modified files:
- `src/inspect_ai/agent/__init__.py` — add new exports.
- `src/inspect_ai/tool/_tools/__init__.py` — add new tool exports.
- `src/inspect_ai/tool/_tools/_update_plan.py` — deprecate with alias to `todo_write()`.
- `src/inspect_ai/tool/_tools/_memory.py` — add `readonly=True` mode that exposes only read operations.

#### 8. Parallel tool execution (deferred)

The current `_execute_tools_impl` in `src/inspect_ai/model/_call_tools.py:300` processes tool calls sequentially. Parallel tool execution would benefit all agents — including `react()` — and would unblock concurrent subagent dispatch for `deepagent()`.

However, this is a significant infrastructure change with nontrivial risks:

- **Breaking change.** `@tool` defaults `parallel=True` and `ToolDef` defaults unspecified tools to parallel-capable, but current execution is sequential. Flipping to concurrent would silently change behavior for existing tools whose authors never had to consider races.
- **Output conflicts.** Current execution tracks a single `result_output`. Parallel batches with multiple tools returning `ExecuteToolsResult.output` need conflict resolution semantics.
- **Approval flows.** Approval policies and interactive tools may not be safe to run concurrently even if the underlying tool is marked `parallel=True`.

**Decision.** Defer parallel tool execution to a separate project. `deepagent()` v1 dispatches subagents sequentially. Both isolated and forked dispatch are architecturally safe to parallelize (forked subagents receive a copy of the parent's messages), so when parallel execution lands, `task()` can opt in without design changes.

#### 9. Testing strategy

- **Unit tests:** `Subagent` construction, `task()` parameter schema generation, system prompt assembly and placeholder expansion, recursion depth tracking (verify closure-based depth is parallel-safe).
- **Integration tests:** `deepagent()` end-to-end with `mockllm` — verify tool wiring, subagent dispatch (both isolated and forked), system prompt content.
- **Tool inheritance tests:** verify `research()`/`plan()` do not receive user-provided mutating tools; verify `general()` inherits the full parent tool set; verify `extra_tools=` works on all subagents.
- **Skill composition tests:** verify parent + subagent skills merge correctly; verify instance-scoped stores don't collide.
- **Memory ACL tests:** verify `research()`/`plan()` get `memory(readonly=True)` and cannot write; verify `general()` gets full read-write memory.
- **Limit tests:** verify sample-level limits apply across parent and child agents; verify `subagent(limits=[...])` applies additional scoped limits to child invocations.
- **Sandbox/no-sandbox tests:** verify read-only tools are constructible without a sandbox and fail clearly at runtime; verify they work correctly with a sandbox.

#### 10. Documentation

New documentation file: `docs/deep-agent.qmd` — a standalone guide covering:

- Overview of the deep agent pattern and when to use `deepagent()` vs `react()`.
- API reference for `deepagent()`, `subagent()`, and built-in subagents (`research()`, `plan()`, `general()`).
- Configuring subagents: custom subagents, per-subagent model routing, fork mode.
- System prompt customization: `instructions=` for the common case, `prompt=` with placeholders for full control.
- Tool configuration: default tool sets, adding `web_search()`, `extra_tools=`.
- Examples: basic usage, custom subagents, cost-aware model routing, fork mode.

## Implementation

### Guidelines

1. **One phase at a time.** Create a dedicated plan for the phase. Do not proceed with implementation or exit plan mode until the user has approved the plan. Implement, test, and verify each phase before moving to the next.
2. **Review before commit.** After tests pass, pause and review the code together before committing. Do not auto-commit.
3. **Full tests at each step.** Every phase produces both implementation and tests.
4. **Update this document.** After completing a phase but before committing, replace the phase's overview section below with a summary of what was actually built and tested — files created/modified, key design decisions made during implementation, and test coverage.

### Phase 1: `Subagent` type and `subagent()` factory (063553f62)

Created the `Subagent` dataclass and `subagent()` factory function.

**Files created:**
- `src/inspect_ai/agent/_deepagent/__init__.py` — package exports.
- `src/inspect_ai/agent/_deepagent/subagent.py` — `Subagent` dataclass (`@dataclass(kw_only=True)`) and `subagent()` factory with input validation.
- `tests/agent/deepagent/test_subagent.py` — 15 unit tests covering construction, defaults, field validation (name, description, prompt, memory).

**Files modified:**
- `src/inspect_ai/agent/__init__.py` — added `Subagent` and `subagent` to public API.

**Design decisions:**
- Used `@dataclass(kw_only=True)` (not Pydantic) to match agent module conventions and allow required fields after fields with defaults.
- Dropped `output_filter` parameter — forked subagents always use `last_message`. Simplifies the API; can be added later if needed.
- Dropped `instructions` from `Subagent` — only `prompt` is stored. Built-in factories (`research()`, `plan()`, `general()`) accept `instructions=` and merge it with their default prompt before constructing the `Subagent`.
- Field order: `name`, `description`, `prompt` (identity), then `tools`, `extra_tools` (adjacent), `model`, `fork`, `memory`, `limits`, `compaction`.

### Phase 2: `todo_write()` tool (713c8ea0c)

Created `todo_write()` as a new tool alongside `update_plan()`.

**Files created:**
- `src/inspect_ai/tool/_tools/_todo_write.py` — `TodoStep` model (with `content`/`status` fields, status as `Literal` enum) and `todo_write()` tool using standard `@tool` pattern.
- `tests/tools/test_todo_write.py` — basic + mockllm integration tests.

**Files modified:**
- `src/inspect_ai/tool/__init__.py` — added `todo_write` export.
- `docs/tools-standard.qmd` — renamed section to "Todo Write", updated examples.

**Design decisions:**
- Surveyed tool descriptions from Claude Code (`TodoWrite`), LangChain (`write_todos`), and Codex CLI (`update_plan`). Synthesized best practices: when-to/when-not-to guidance from CC/LangChain, quality examples from Codex, real-time status rules from LangChain.
- Renamed `step` field to `content` and `plan` param to `todos` to match CC/LangChain vocabulary.
- `status` typed as `Literal["pending", "in_progress", "completed"]` (validated, not free-form string).
- `update_plan()` left completely unchanged — no deprecation, no warnings. Removed from docs but existing harnesses continue to work silently.
- `TodoStep` not exported in public API — it's internal; models and tests pass dicts.
- Used standard `@tool` pattern (not `ToolDef().as_tool()`).

### Phase 3: Read-only tools (`grep`, `read_file`, `list_files`) (40da3105f)

Created three standalone read-only sandbox tools for `research()` and `plan()` subagents.

**Files created:**
- `src/inspect_ai/tool/_tools/_read_file.py` — `read_file()` tool using `SandboxEnvironment.read_file()` with line numbers and `offset`/`limit` pagination.
- `src/inspect_ai/tool/_tools/_list_files.py` — `list_files()` tool using `find` with optional `depth` control.
- `src/inspect_ai/tool/_tools/_grep.py` — `grep()` tool using `grep -rn` with `glob` filter, `fixed_strings`, and `output_mode` ("content" / "files_with_matches" / "count").
- `tests/tools/test_read_file.py`, `test_list_files.py`, `test_grep.py` — constructibility + Docker integration tests.

**Files modified:**
- `src/inspect_ai/tool/__init__.py` — added `read_file`, `list_files`, `grep` exports.
- `docs/tools-standard.qmd` — added Read-Only Tools section with examples.
- `docs/reference/inspect_ai.tool.qmd` — added reference entries.
- `CHANGELOG.md` — added Unreleased section with entries for read-only tools and `todo_write()`.

**Design decisions:**
- Surveyed Claude Code and LangChain deep agents for parameter naming conventions. Aligned: `file_path` (not `file`), `offset`/`limit` (not `start_line`/`end_line`), `glob` (not `include`), `output_mode` with three enum values.
- All three tools accept `timeout`, `user`, and `sandbox` parameters matching `bash()`.
- Tools are always constructible without a sandbox; `sandbox()` raises `ProcessLookupError` at runtime if none is available.
- No additional output limiting needed — existing `max_tool_output` (16 KiB default) handles large results; models can use `offset`/`limit` to paginate.

### Phase 4: `memory(readonly=True)` mode (ccf86a82a)

Added read-only mode to the existing `memory()` tool.

**Files modified:**
- `src/inspect_ai/tool/_tools/_memory.py` — added `readonly: bool = False` parameter. When `True`, returns a separate `execute_readonly` function with `command: Literal["view"]` and only `path`/`view_range` parameters, so the model's tool schema only advertises read operations. Also fixed `/memories` root to always be treated as existing in `_path_exists`/`_is_dir`.
- `tests/tools/test_memory.py` — added 3 readonly tests (view file, view directory, no write params accepted).
- `docs/tools-standard.qmd` — added Read-Only Mode section to memory documentation.
- `CHANGELOG.md` — added entry.

**Design decisions:**
- Used a separate inner function (not a runtime guard) so the model sees only `command: Literal["view"]` in the tool schema — write commands are never advertised.
- Readonly memory naturally sidesteps Anthropic native tool auto-binding because the parameter set doesn't match the 10-parameter signature check.
- Initial data seeding still works in readonly mode (it's setup, not a model action).

### Phase 5: `task()` tool (8c2bb0315)

Built the multiplexer tool that dispatches to subagents.

**Files created:**
- `src/inspect_ai/agent/_deepagent/task_tool.py` — `task_tool()` factory creating a `@tool`-decorated `task` function. Dispatches via `run()` for both modes: isolated (string prompt) and forked (parent messages with system stripped and tool call repaired + prompt). Includes `_build_task_description()` for dynamic tool description, `_resolve_tools()` for child tool assembly with recursion guard, `_dispatch()` for unified limit handling, and `_extract_result()` for output extraction.
- `tests/agent/deepagent/test_task_tool.py` — tests for description generation, constructibility, mockllm dispatch, invalid subagent_type error, general dispatch, recursion guard, forked dispatch, and forked input preparation.

**Files modified:**
- `src/inspect_ai/agent/_deepagent/__init__.py` — added `task_tool` export (internal only).

**Design decisions:**
- Used `run()` for both isolated and forked dispatch — handles string→messages, limit application with `catch_errors=True`, span creation with `name=sa.name`, and returns `AgentState` + optional `LimitExceededError`.
- For forked dispatch, parent messages are passed with minimal filtering (system stripped, tool call repaired) to preserve prompt cache. Parent messages accessed via `get_messages` callback (wired by `deepagent()` in Phase 8).
- Recursion guard: `_resolve_tools()` includes a recursive `task_tool` at `depth < max_depth`, omits it at `depth >= max_depth`. Depth tracked via closure.
- `subagent_type` parameter has a dynamic `enum` constraint in the JSON schema for structured model guidance.
- Tool named `"task"` internally — no conflict with `@task` decorator (separate registries). Not publicly exported to avoid API confusion.
- `task_description` parameter name (not `description`) to avoid shadowing.

### Phase 6: Built-in subagent factories (`research`, `plan`, `general`) (630a40397)

Implemented the three opinionated subagent factories plus related improvements.

**Files created:**
- `src/inspect_ai/agent/_deepagent/research.py` — `research()` factory with task-agnostic prompt, `tools="default"` → `None` (resolved at dispatch time to read-only tools if sandbox available).
- `src/inspect_ai/agent/_deepagent/plan.py` — `plan()` factory, same pattern.
- `src/inspect_ai/agent/_deepagent/general.py` — `general()` factory, `memory="readwrite"`, inherits parent tools.
- `tests/agent/deepagent/test_factories.py` — 27 tests covering defaults, instructions merge, custom/empty/extra tools, overrides, and task-agnostic prompt verification.

**Files modified:**
- `src/inspect_ai/agent/_deepagent/__init__.py` — added `research`, `plan`, `general` exports.
- `src/inspect_ai/agent/__init__.py` — added public exports.
- `docs/reference/inspect_ai.agent.qmd` — added Deep Agent section with `subagent`, `Subagent`, `research`, `plan`, `general`.
- `src/inspect_ai/agent/_deepagent/task_tool.py` — forked dispatch now uses `timeline_branch()` for proper log viewer rendering; removed `content_only` filtering on forked input to preserve prompt cache and avoid incompatible format errors.
- `src/inspect_ai/agent/_deepagent/subagent.py` — removed fork+model validation (documented guidance instead); updated fork docstrings across all factories to recommend same model/family for cache and compatibility.

**Additional test coverage added:**
- `tests/tools/test_read_file.py` — offset, limit, offset+limit, file-not-found error (Docker/slow).
- `tests/tools/test_list_files.py` — depth parameter (Docker/slow).
- `tests/tools/test_grep.py` — glob, fixed_strings, no matches, files_with_matches mode, count mode (Docker/slow).
- `tests/agent/deepagent/test_task_tool.py` — forked dispatch via mockllm.

**Design decisions:**
- All factories accept `tools: Sequence[...] | Literal["default"] = "default"` — allows replacing defaults entirely or passing empty list.
- Prompts are task-agnostic — no references to "codebase", "code review", etc. Works for coding, cyber, AI scientist, literature synthesis, and other domains.
- Forked dispatch passes messages through as-is (no `content_only` filter) to preserve prompt cache. Documentation recommends same model/family when forking.
- Forked dispatch wrapped in `timeline_branch()` with `BranchEvent` for proper log viewer swimlane rendering.

### Phase 7: System prompt assembly (07e8d96d2)

Built the prompt composition logic.

**Files created:**
- `src/inspect_ai/agent/_deepagent/prompt.py` — String constants (`CORE_BEHAVIOR`, `MEMORY_INSTRUCTIONS`, `MEMORY_ONLY_INSTRUCTIONS`, `PLAN_ONLY_INSTRUCTIONS`) plus `build_system_prompt()` for layered assembly, `build_subagent_dispatch()` for dynamic subagent listing, and `expand_prompt_placeholders()` for the `prompt=` escape hatch using `str.replace()`.
- `tests/agent/deepagent/test_prompt.py` — 19 tests covering default assembly, subagent inclusion/exclusion, memory/todo_write combinations, user instructions ordering, placeholder expansion (all/partial/missing/cleared), and task-agnostic verification.

**Design decisions:**
- Surveyed CC (~160 component files), Codex (~500 lines for generic models, ~80 for tuned), LangChain (~60 lines), Pydantic (~100 lines). Our approach: ~30 lines of goal-oriented core behavior (not prescriptive procedures) that works across capability levels.
- `CORE_BEHAVIOR` covers: action bias, persistence ("keep going until fully resolved"), error recovery ("diagnose what went wrong"), conciseness, batched tool calls, planning/verification, don't over-ask.
- Memory instructions include recovery prompt: "Check your memory at the start of your work to recover any earlier progress" — complements the compaction system's pre-compaction memory warning with post-compaction recovery guidance.
- Subagent dispatch section includes delegation prompt guidance: "Include all necessary context — the subagent cannot see your conversation history."
- Placeholder expansion uses `str.replace()` (not `.format()`) to avoid conflicts with other braces in custom prompts.
- Also beefed up subagent factory prompts (`research.py`, `plan.py`, `general.py`) with persistence, error recovery, and verification guidance (~12-15 lines each, up from ~8).

### Phase 8: `deepagent()` function (a94c56eba)

Wired everything together.

**Files created:**
- `src/inspect_ai/agent/_deepagent/deepagent.py` — `deepagent()` top-level assembly function decorated with `@agent`. Assembly sequence: resolve subagents (defaults to research/plan/general), inject web_search, apply memory kill switch, propagate compaction, set general's tools to parent tools, construct task_tool with get_messages callback, collect top-level tools, build system prompt (or expand placeholders), suppress react() defaults via `AgentPrompt`, delegate to `react()`.
- `tests/agent/deepagent/test_deepagent.py` — 7 unit tests: constructibility, basic e2e, memory kill switch, instructions, custom prompt, extra tools, default subagents.
- `tests/agent/deepagent/test_deepagent_e2e.py` — 15 comprehensive e2e tests using mockllm: multi-step delegation, memory write + subagent read, todo_write plan tracking, submit tool, custom subagents, instructions in system message, memory kill switch, full workflow (memory → plan → delegate → submit), plan subagent dispatch, general inherits parent tools, todo_write disabled, multiple calls to same subagent, interleaved tool use and delegation, custom prompt with placeholders, unknown tool graceful error.

**Files modified:**
- `src/inspect_ai/agent/_deepagent/task_tool.py` — `_resolve_tools` now provides sandbox-aware default read-only tools when `sa.tools is None`, injects `memory()`/`memory(readonly=True)` based on `sa.memory`, and passes `compaction=sa.compaction` to child `react()`.
- `src/inspect_ai/agent/_deepagent/subagent.py` — added `compaction: CompactionStrategy | None = None` field.
- `src/inspect_ai/agent/_deepagent/__init__.py` — added `deepagent` export.
- `src/inspect_ai/agent/__init__.py` — added `deepagent` to public API.
- `docs/reference/inspect_ai.agent.qmd` — added `### deepagent` to Deep Agent section.

**Design decisions:**
- `web_search: Tool | bool = False` — accepts `True` for defaults or a pre-configured `web_search()` instance. Off by default (evals value reproducibility and controlled environments).
- Default subagents: `None` → `[research(), plan(), general()]`. The whole point of `deepagent()` is the opinionated assembly; users who don't want subagents use `react()`.
- Suppressed react() default prompts via `AgentPrompt(instructions=prompt, assistant_prompt=None, submit_prompt=None, handoff_prompt=None)` — `CORE_BEHAVIOR` already covers what react's defaults provide.
- Forked dispatch `get_messages` callback uses a mutable `_state_ref` that points to `state.messages` once the agent starts executing. Since react modifies messages in-place, the reference stays current.
- Compaction propagation: parent's `CompactionStrategy` propagates to subagents that don't set their own. Safe because each `react()` creates its own `Compact` instance from the strategy.
- `general()` subagent inherits parent tools via name-based check in `_apply_parent_tools_to_general`.
- All e2e tests use `submit=True` and terminate via `_submit()` helper to avoid mockllm output exhaustion from react's continue prompts.

### Phase 9: Public API and exports

Already complete — exports were added incrementally in each preceding phase. Verified:

- `inspect_ai.agent`: `deepagent`, `subagent`, `Subagent`, `research`, `plan`, `general` all exported.
- `inspect_ai.tool`: `read_file`, `list_files`, `grep`, `todo_write` all exported. `update_plan` still exported (undocumented backward compat).
- `task_tool` is internal only (not in public API, no naming collision with `@task` decorator — separate registries).
- `docs/reference/inspect_ai.agent.qmd`: Deep Agent section with all entries.
- `docs/reference/inspect_ai.tool.qmd`: read_file, list_files, grep entries added.

### Phase 10: Documentation

Write `docs/deep-agent.qmd`.

- Overview of the deep agent pattern and when to use `deepagent()` vs `react()`.
- API reference for `deepagent()`, `subagent()`, and built-in subagents (`research()`, `plan()`, `general()`).
- **Isolated vs forked dispatch guide** — explain the tradeoff clearly:
  - Default is isolated (`fork=False`): subagent gets fresh context with only the task prompt. Prevents context rot, enables parallelism, predictable behavior. All major frameworks (Claude Code, LangChain, Codex) default to this.
  - Forked (`fork=True`): subagent inherits parent's full conversation history. Preserves prompt cache on all providers (system prompt and message prefix unchanged). Best when subagent needs substantial background context and parent history is fresh. Use same model/family. Instructions appended as user message after cached prefix.
  - When to choose each, with examples.
- Configuring subagents: custom subagents, per-subagent model routing, fork mode.
- System prompt customization: `instructions=` for the common case, `prompt=` with placeholders for full control.
- Tool configuration: default tool sets, `web_search=`, `extra_tools=`.
- Memory and planning: `memory=`, `todo_write=`, `memory=False` kill switch.
- Examples: basic usage, custom subagents, forked dispatch, cost-aware model routing.
- Update inspect_ai.agent.qmd with reference sections.
