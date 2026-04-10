# Type Generation Pipeline: Python → OpenAPI → TypeScript

How `inspect_ai` Pydantic models become TypeScript types, and every
customization we make along the way.

## Pipeline overview

| Step | Input | Tool | Output |
|---|---|---|---|
| Python → OpenAPI | FastAPI endpoints | FastAPI / Pydantic | OpenAPI JSON schema<br/>(`inspect-openapi.json`) |
| OpenAPI → TypeScript | OpenAPI JSON schema | openapi-typescript | TypeScript types<br/>(`generated.ts`) |
| TypeScript → Consumers | TypeScript types | barrel `index.ts` | Consumer-facing types |

## Python → OpenAPI

#### Customization 1. Extra inlined types

All types enter the schema through FastAPI endpoints. Inlined types would
otherwise only appear as inline definitions with auto-generated, unstable
names. To give them stable, meaningful names in `components/schemas`, they
are wrapped in `RootModel` subclasses and added via stub endpoints that exist
only for schema generation — they are not implemented by the server.
`build_openapi_schema()` in `_openapi.py` orchestrates the generation and
applies post-processing fixes.

> **What gets inlined?** Classes (Pydantic models, dataclasses) get their
> own entry in `components/schemas` keyed by class name. Type aliases —
> regardless of syntax (`Foo = A | B`, `Foo: TypeAlias = A | B`, or bare
> inline `A | B`) — are invisible to Pydantic at runtime and get inlined at
> each usage site. `RootModel` wrappers give these types a class identity.

#### Customization 2. Field requiredness based on Noneability rather than defaults

Pydantic bases the JSON Schema `required` list on whether a field has a
default value — essentially `required = !has_default`. But `inspect_ai`
serializes with `exclude_none=True`, which omits fields from JSON when their
value is `None`. This makes defaults the wrong signal — a Noneable field may
be absent at runtime regardless of its default, and a non-Noneable field with
a default is always present.

We fix this with `_CustomJsonSchemaGenerator`, a custom `GenerateJsonSchema`
subclass (a FastAPI extension point) that overrides `field_is_required` to
`required = !is_noneable` instead:

| Field | Pydantic default | Our override |
|---|---|---|
| `field: str` | required | required |
| `field: str = "foo"` | not required | **required** |
| `field: str \| None` | required | **not required** |
| `field: str \| None = None` | not required | not required |


## OpenAPI → TypeScript

We use `openapi-typescript` (v7+) with two customizations configured in
`packages/inspect-common/scripts/openapi-ts-options.js`.

#### Customization 3. Defaults shouldn't imply presence in TypeScript

By default, `openapi-typescript` treats fields with a `"default"` value as
required in TypeScript (`defaultNonNullable: true`) — they get `field: T`
instead of `field?: T`. We set `defaultNonNullable: false` so that having a default doesn't remove
the `?` optional marker. This matches `exclude_none=True` behavior where
Noneable fields may be absent at runtime.

| Schema | `openapi-typescript`<br/>default | Our override |
|---|---|---|
| required | `field: T` | `field: T` |
| not required, no default | `field?: T` | `field?: T` |
| not required, has default | `field: T` | **`field?: T`** |

This also ensures structural compatibility between inspect-common's exports
and scout's `generated.ts` types, since both use the same setting.

#### Customization 4. JsonValue `postTransform`

Pydantic can't represent `JsonValue` as JSON Schema (it's recursive), so the
OpenAPI schema contains an empty `{}` for it. Left alone, `openapi-typescript`
would generate `unknown`. A `postTransform` intercepts any schema path ending
in `/JsonValue` and replaces it with a reference to a hand-written recursive
TypeScript type from `@tsmono/util`:

```typescript
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonArray
  | JsonObject;
export interface JsonArray extends Array<JsonValue> {}
export interface JsonObject { [key: string]: JsonValue }
```

The `interface extends Array` pattern sidesteps TypeScript's depth limit on
recursive type aliases (TS2502).

## TypeScript → Consumers

The barrel `index.ts` in `packages/inspect-common/src/types/` plucks named
types out of `generated.ts` and re-exports them as the public API.

## Appendix

### Runtime context: `exclude_none=True`

`inspect_ai` serializes with `exclude_none=True` as standard (`to_json_safe` →
`jsonable_python`). This applies to log writing, API responses, and most
serialization. A field with value `None` is **omitted from the JSON entirely**.

Pydantic has no way to express this in its schema — it's a runtime choice
invisible to OpenAPI. Our pipeline encodes this reality through two
coordinated settings:

- `field_is_required` → nullable fields not in `required`
- `defaultNonNullable: false` → defaults don't imply presence in TS

The result: nullable fields become `field?: T | null` in TypeScript. The `?`
means the type is `T | null | undefined`, so `field !== null` doesn't narrow
away `undefined` — the compiler forces a proper check (`!= null` or truthiness).

### Structural typing and cross-package compatibility

TypeScript uses structural (not nominal) typing. Scout's `generated.ts`
contains duplicates of `inspect_ai` types (unavoidable from FastAPI transitive
dependencies). This is harmless because both pipelines use the same
`build_openapi_schema` code and `defaultNonNullable: false`, producing
identical shapes. Scout's barrel re-exports `inspect_ai` types from
`@tsmono/inspect-common`; duplicates in scout's `generated.ts` are unused.
