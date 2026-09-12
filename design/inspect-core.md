# `inspect_core`: extracting the wire types

Exploratory design. Status: measured where marked, reasoned elsewhere.

## Goal

Make Inspect's core data types — `ChatMessage`, `Content`, `ToolCall`,
`ToolInfo`, `ModelOutput` — depend on almost nothing, so they can be

- imported by lightweight consumers (log readers, dataframe/analysis code,
  sibling packages) without paying for the eval framework,
- compiled into a WASM module of tolerable size (see
  `monitor-deployment.md`),
- published as a versioned cross-language schema that hosts written in Go,
  Rust or TypeScript can target.

This came out of the monitor design, but nothing here is monitor-specific.

## The measurement

Importing a data model today:

```
import pydantic                                         27 ms,    65 modules
from inspect_ai.model._chat_message import ChatMessage 1678 ms,  1501 modules
```

The 1,501 modules include `textual` (a TUI framework), `botocore`, `trio`,
`tornado`, `starlette`, `opentelemetry`, `psutil`, `sqlite3`, `curses`,
`readline`, `zstandard`, `mmh3`.

`_chat_message.py` itself imports `hashlib`, `json`, `logging`, `typing`,
`pydantic`, `shortuuid`, and a handful of `inspect_ai._util` leaves. The type
is nearly a leaf already. Everything else arrives through package `__init__`
side effects.

### Where it comes from

Static analysis of the transitive closure of the candidate wire-type modules
(`_chat_message`, `_util.content`, `tool._tool_call`, `tool._tool_info`,
`tool._tool_choice`, `model._model_output`, `model._generate_config`),
counting only module-level, non-`TYPE_CHECKING` imports:

| | inspect_ai modules | third-party |
|---|---|---|
| As written today | 505 | 30 |
| With package imports rewritten as module imports | **27** | **12** |

The entire cascade traces to **one line**. `_chat_message.py:14`:

```python
from inspect_ai.tool import ToolCall          # package import
```

That runs `inspect_ai/tool/__init__.py`, which pulls the web browser,
computer, MCP and skill tools, and from there `inspect_ai.util` → checkpoint →
restic → sandbox → everything. Rewritten as
`from inspect_ai.tool._tool_call import ToolCall`, the closure collapses to 27
modules.

### The floor

After that fix the remaining third-party set is:

```
anyio, dateutil, docstring_parser, jsonlines, jsonpatch, jsonpointer,
platformdirs, pydantic, pydantic_core, rich, shortuuid, typing_extensions
```

Most arrive incidentally through utility modules the types reach for —
`rich` via `_util.logger` and `_util.trace`, `platformdirs` via
`_util.appdirs`, `anyio` via `util._concurrency` — because `_chat_message`
calls `warn_once`. Decoupling those leaves:

```
pydantic, pydantic_core, shortuuid, typing_extensions
```

One native extension (`pydantic-core`, Rust), three pure-Python packages.

## Proposed layering

| Package | Contents | Dependencies |
|---|---|---|
| `inspect_core` | wire data models + registry substrate | pydantic, shortuuid, typing_extensions |
| `inspect_api` | provider payload ↔ core type conversions | + provider SDK *type* modules |
| `inspect_ai` | clients, execution, eval machinery, viewer | everything |

`inspect_core` rather than `inspect_types` because the registry primitives
belong in it — see below. It is "what both a monitor author and `inspect_ai`
need", not only the models.

### Cut line 1: data models, not construction machinery

`docstring_parser` arrives via `tool/_tool_info`, which builds `ToolInfo` from
Python function signatures. That is an *authoring* concern. A wire-level
`ToolInfo` is the JSON-schema shape and needs none of it.

So: models that describe the wire go down; "build a model from a Python
object" (`tool_to_tool_info` and friends) stays up. This is the principle that
keeps the bottom layer leaf-like rather than an arbitrary boundary.

### Cut line 2: descriptive vs executable tools

The conversion layer's portability blocker is visible in a return type
(`agent/_bridge/anthropic_api_impl.py`):

```python
def tools_from_anthropic_tools(...) -> list[ToolInfo | Tool]:
```

Plain tool definitions become `ToolInfo` — descriptive, portable. Native
Anthropic tools (computer, bash, text_editor, web_search, code_execution)
become `Tool` — executable, dragging `_tools._computer`, `_tools._execute`,
`_tools._web_search` and their sandbox dependencies.

That it is severable is visible too: `messages_from_anthropic_input(input,
tools)` immediately resolves tools to tool info internally. It only ever
needed the descriptive half.

A consumer that never executes a tool — a monitor, a log reader, a proxy —
needs to know *that* a bash tool is available, not to be able to run it. So a
`tool_info_from_anthropic_tools() -> list[ToolInfo]` belongs in `inspect_api`
and the `Tool`-producing variant stays in `inspect_ai` for the bridge that
actually dispatches.

### Cut line 3: SDK types, not SDK clients

`model/_openai.py` does:

```python
from openai import APIError, RateLimitError, ...      # package import
```

Those are all exception classes, but the top-level import runs
`openai/__init__.py` and pulls the whole client. `from openai._exceptions
import ...` sidesteps it — the same package-`__init__` problem as
`from inspect_ai.tool import ToolCall`, in a third-party dependency.

`anthropic_api_impl.py` similarly reaches into `model/_providers/anthropic.py`
for `is_bash_tool`, `is_tool_param`, `assistant_message_blocks`,
`content_and_tool_calls_from_assistant_content_blocks`. Those are pure
classification and conversion functions living in the client module; they move
down a layer.

On weight: the `anthropic` and `openai` SDKs are pure Python whose only native
dependency is `pydantic-core`, which `inspect_core` already needs — tolerable
in a constrained build. `google-genai` reaches for google-auth, requests and
possibly grpc, and may need to be an optional extra.

### The registry is already a leaf

`_util/registry.py` runtime imports are `inspect`, `sys`, `typing`,
`pydantic`, `pydantic_core`, `typing_extensions`, plus `_util.json`,
`_util.package`, `_util.constants`, `_util.entrypoints`. Every reference to
`Task`, `Agent`, `Approver`, `Hooks`, `ModelAPI`, `Metric`, `Scorer`,
`Solver`, `Tool` and `SandboxEnvironment` is `TYPE_CHECKING`-only — they exist
for `registry_create`'s overload signatures. `registry_tag` is two `setattr`
calls; `extract_named_params` is stdlib `inspect.signature().bind()`.

So `RegistryInfo`, `registry_add`, `registry_tag`, `registry_info`,
`registry_lookup` and `extract_named_params` can live in `inspect_core`. A
decorator defined there registers for real — no marker attributes, no deferred
drain, no import-ordering hazard, no dependency inversion. Module identity
gives a shared singleton registry for free: `inspect_ai` imports the same
module object, so there is one dict, not two to keep coherent.

Three details:

- **`ensure_entry_points()` is a hazard.** It is called from `registry.py` and
  loads plugin entry points, so it can import arbitrary third-party packages
  at runtime — silently defeating the dependency discipline in a constrained
  build. It needs to be injectable or a no-op in `inspect_core`, with
  `inspect_ai` installing the real implementation.
- **`registry_create` stays up.** The leaf needs tag/add/info/lookup; the
  typed overloads are about constructing heavy objects.
- **`RegistryType`** enumerates `"solver"`, `"scorer"`, … Either move the
  Literal down (harmless — it is strings) or type the leaf's field as `str`
  and keep the Literal in `inspect_ai` for checking.

## Compatibility

Prefer re-export shims over relocation: `inspect_ai.model.ChatMessage` keeps
working with the definition moving underneath. This matters beyond politeness
— `inspect_scout` imports `inspect_ai` privates directly, so a bare move
breaks a sibling package.

`_util.registry` is more central than the rest of the leaf set; worth checking
whether the types genuinely need it or whether that is another incidental
reach.

## The wire contract

Once the types are extractable they can be published as a schema that hosts in
other languages target directly, rather than something only Python can
construct.

**The host renders Inspect-shaped JSON.** A proxy, a sidecar, or any other
producer normalizes provider payloads into the core schema; the consumer
validates and works with typed models. `inspect_api` becomes optional rather
than required — needed only where the producer happens to be Python.

Three consequences to design for now, because they are cheap now and expensive
later:

**Unrecognized content must be representable, not droppable.** Moving
normalization to N host implementations means provider churn (a new content
block type, reasoning blocks, a changed tool_calls shape) reaches consumers as
silent loss: a monitor or reader cannot distinguish "the agent did not do X"
from "this host's normalizer does not know about X yet". A passthrough content
type carrying the raw provider block closes that — the consumer can see that
something was there and fail closed if it cares.

**A conformance corpus is what makes the contract real.** Provider payload →
expected core JSON, as fixtures any implementation can run. Inspect's own
Python conversions become the *oracle* that generates the corpus rather than
the code everyone imports — which is most of the reason to keep them
well-factored even when consumers no longer ship them.

**Version the payload on the wire from day one.** Once hosts target the schema
independently, producer and consumer drift, and there must be a defined
behavior for a payload from an older or newer normalizer. Trivial now; painful
once implementations exist.

## Cross-language codegen

The pipeline is two thirds built: `design/type-generation-pipeline.md`
documents Python → OpenAPI (`inspect-openapi.json`) → `openapi-typescript`,
including RootModel wrappers and stub endpoints for stable schema names, and
the `field_is_required` override making `required = !is_noneable` to match
`exclude_none=True` serialization. Adding Go (`oapi-codegen`) and Rust
(`typify` / `progenitor`) is plumbing off the same artifact.

### The precondition: discriminated unions

`Content` and `ChatMessage` are declared as plain unions, so Pydantic emits
`anyOf` with no discriminator and a generator has nothing to dispatch on. But
every member already carries a clean tag:

```
ContentText       type: Literal["text"]        ChatMessageSystem     role: Literal["system"]
ContentReasoning  type: Literal["reasoning"]   ChatMessageUser       role: Literal["user"]
ContentToolUse    type: Literal["tool_use"]    ChatMessageAssistant  role: Literal["assistant"]
ContentImage      type: Literal["image"]       ChatMessageTool       role: Literal["tool"]
...
```

And the codebase already has the pattern, including the non-breaking way to
add it (`event/_event.py`):

```python
DiscriminatedEvent: TypeAlias = Annotated[Event, Field(discriminator="event")]
```

A parallel alias leaves the existing union untouched, so nothing downstream
changes. `DiscriminatedContent` and `DiscriminatedChatMessage` follow.

This is additive annotation — no model changes — and it improves every target,
not only Go: `openapi-typescript` emits proper tagged unions, Rust gets
`#[serde(tag = "type")]`, and Python validation gets faster because tagged
dispatch beats trying each member.

**One wrinkle.** A discriminator changes failure behavior: an unknown tag
becomes "no mapping for tag" rather than "matched no member", i.e. a hard
validation error — exactly what the passthrough type exists to prevent. The
discriminated union needs a catch-all member, or a wrap validator routing
unmapped tags to it. Decide it explicitly rather than discover it when a
provider ships a new block type.

### Go is the hard target

TypeScript and Rust express tagged unions natively. **Go has no sum types**,
and `ChatMessage` / `Content` are precisely the types a host must construct.
Default generator output is `any` with manual type switches, or one fat struct
with every field.

A hand-designed representation is dramatically better and is generatable:
an interface per union with an unexported marker method, concrete structs per
member, and — the load-bearing detail — a wrapper type carrying the decoder:

```go
type ContentList []Content
func (c *ContentList) UnmarshalJSON(b []byte) error  // probe tag, dispatch, default → passthrough
```

Containing structs then get union decoding for free rather than each needing
custom logic, and the `default:` branch is where the passthrough type lands, so
forward compatibility falls out of the same switch.

For a curated set of ~30 types, writing the emitter is likely better than
customizing `oapi-codegen` templates: its union handling is weak because it
must serve sprawling REST APIs, and a direct OpenAPI-JSON → Go emitter gives
full control of output quality.

The `exclude_none` convention also lands differently per language. Rust gets
`Option<T>` and TypeScript `foo?:`, both clean. Go expresses optionality as
pointers or `omitempty` and generators differ in whether the result can
distinguish absent from zero value — which matters wherever absent and
`false`/`0`/`""` mean different things. Go needs an explicit policy.

### Schema as the product, stubs as a convenience

Publishing a Go module or a crate means owning its semver, idioms and issue
tracker — release artifacts tracking every type change. Publishing the
versioned schema plus generation instructions costs nothing ongoing, with
prebuilt artifacts added later if demand appears. Either way, stamp the schema
version into generated types so hosts assert compatibility at compile time.

And note what codegen does *not* do: it gives hosts the target shape, not the
mapping into it. The hard part of a Go host remains Anthropic-blocks-to-
`ChatMessage`. Stubs remove the boring half; the conformance corpus removes
risk from the interesting half. If only one gets built, build the corpus.

## Status

**Measured:** the import closures (1501/1678ms; 505 → 27; the 12- and
4-package floors), the `from inspect_ai.tool import ToolCall` cascade,
`registry.py`'s runtime import set and TYPE_CHECKING-only references, the
`ToolInfo | Tool` return type, the absence of discriminators on `Content` and
`ChatMessage` alongside their existing Literal tags, and the
`DiscriminatedEvent` precedent.

**Reasoned, not verified:** WASM build sizes and behavior, serialization
throughput comparisons, and how much of the `_util` decoupling to the
four-package floor is genuinely mechanical.

## Open questions

1. **Scope of `inspect_core`.** Which types exactly? The seven analyzed here
   are the monitor's needs; a log reader wants `EvalLog` and the event types,
   which reach further.
2. **Is it a separate distribution or a subpackage?** A separate wheel lets a
   Go-host author depend on it without `inspect_ai`; a subpackage is far less
   release machinery. The WASM case wants the former.
3. **How far to chase the four-package floor.** Removing `rich`,
   `platformdirs`, `anyio` and `jsonlines` means the types stop using
   `warn_once` and friends. Worth it for a constrained build, possibly not
   otherwise.
4. **Does `inspect_api` ship the Google provider conversions** given the
   heavier dependency, or are they an optional extra?
5. **Catch-all member design** for the discriminated unions, and whether the
   passthrough type is one shape or per-union.
