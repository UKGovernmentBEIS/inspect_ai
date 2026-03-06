# Timezone Handling Architecture

## Principles & Assumptions

### Core Principles

**1. UTC Everywhere**
- All temporal data in dataframes MUST be timezone-aware AND in UTC
  - Mixed timezones in same column lead to a dtype of `object`, breaking datetime introspection via `is_datetime64_any_dtype()`
- Internal datetime objects created in UTC (`datetime_now_utc()`)
- Convert to UTC before storage

**2. External & Persisted Data**
- Persisted log files may contain TZ-less ISO strings (e.g., `"2024-01-01T12:00:00"`)
- These MUST remain readable

**3. Never Consult Local Timezone**
- Inspect operates entirely in UTC, never queries system timezone
- TZ-less strings interpreted as UTC (not local timezone)
- Rationale:
  - Consulting local timezone is unnecessary since all temporal data is stored/processed in UTC
  - Querying system timezone can be expensive (OS-dependent, can degrade by multiple orders of magnitude with certain process models such as forking)

**4. Defense in Depth**
- Static analysis (DTZ lint rules) - prevents naive datetime creation at compile-time
- Type system enforcement (`UtcDatetime`) - documents intent, enables runtime validation
- Runtime validation (Pydantic `@field_validator`) - validates at model boundaries
- Coercion layer safeguards (`import_record()`) - final safeguard for dataframe ingestion
- Never silently accept naive datetimes without explicit handling

---

## Type System Strategy

Inspect needs runtime validation for datetime fields that:
1. Coerces TZ-less strings from external data (e.g., `"2024-01-01T12:00:00"`)
2. Normalizes all timezones to UTC
3. Rejects naive datetime objects (programming errors)

Pydantic's `AwareDatetime` provides a foundation, but requires customization to meet our needs.

### Starting Point: `AwareDatetime`

`AwareDatetime` is a Pydantic type alias that provides **runtime validation** and type coercion for datetime objects:

### Coercion Behavior

**`AwareDatetime`** coerces several input types but requires that the input material be timezone aware:

```python
# ✅ ACCEPTS & COERCES
"2024-01-01T12:00:00Z"                     # TZ-aware ISO string
"2024-01-01T12:00:00+05:00"                # ISO with offset (preserves +05:00)
datetime(2024, 1, 1, 12, tzinfo=timezone.utc)  # Aware datetime object
1704110400                                 # Unix timestamp (int) → UTC
1704110400.5                               # Unix timestamp (float) → UTC
1704110400000                              # Millisecond timestamp → UTC

# ❌ REJECTS
"2024-01-01T12:00:00"                      # TZ-less ISO string
"2024-01-01"                               # Date-only string
datetime(2024, 1, 1, 12)                   # Naive datetime object
date(2024, 1, 1)                           # Date object
```

### Key Characteristics

1. **Runtime validation only** - No static type checking benefits
2. **Coerces multiple types** - TZ-aware ISO strings, aware datetime objects, numeric timestamps (UTC implied)
3. **Preserves original timezone** - Does NOT convert to UTC (e.g., +05:00 stays +05:00)
4. **Rejects naive input** - TZ-less strings and naive datetime objects fail validation
5. **Numeric timestamps in UTC** - Int/float timestamps interpreted as UTC
6. **Works with validators** - Can add `@field_validator(mode="before")` to customize coercion

### Usage Pattern Without UtcDatetime (Verbose)

Using `AwareDatetime` alone requires per-field validators:

```python
class Event(BaseModel):
    timestamp: AwareDatetime
    completed: AwareDatetime | None

    @field_validator("timestamp", "completed", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """Coerce strings to aware datetime with UTC fallback."""
        if isinstance(v, str):
            return datetime_from_iso_format_safe(v)  # Backward compat
        return v

    @field_validator("timestamp", "completed", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        """Convert all timezones to UTC."""
        return v.astimezone(timezone.utc) if v else None
```

**Problem:** Must repeat validators for every datetime field.

### Our Solution: UtcDatetime

`AwareDatetime` is insufficient for our needs because it rejects naive data. However, naive data will inevitably be encountered from external sources - we can't prevent this at compile-time.

`UtcDatetime` extends `AwareDatetime` by embracing this reality: it transforms naive data to UTC rather than rejecting it. It adds a `BeforeValidator` that provides:

- **Coerce TZ-less strings to UTC** - handles external data by interpreting as UTC
- **Coerce naive datetime objects to UTC** - treats naive datetimes as UTC (via `datetime_safe()`)
- **Normalize all timezones to UTC** - converts +05:00, -08:00, etc. to UTC
- **Automatic validation** - no per-field `@field_validator` boilerplate needed

**Result:** Clean, declarative datetime fields:

```python
class Event(BaseModel):
    timestamp: UtcDatetime  # That's it - no validators!
    completed: UtcDatetime | None
```

### Type Hierarchy and Usage Guidance

**Preferred → Fallback:**

1. **UtcDatetime** (preferred) - For datetime fields in Pydantic models
   - Provides rich datetime operations
   - Automatic UTC normalization and validation
   - Best developer experience

2. **UtcDatetimeStr** (fallback) - For legacy string fields in public API
   - When existing public API fields are typed as `str`
   - Cannot convert to `UtcDatetime` without breaking compatibility
   - Provides UTC normalization while maintaining `str` runtime type
   - Guarantees UTC-normalized ISO format strings

3. **Plain `str`** (avoid for new code) - Only if no UTC normalization needed

**When to use each type:**

**Use `UtcDatetime` for:**
- New Pydantic model fields (preferred)
- Function return types producing UTC datetimes (documentation + static analysis)
- Internal fields that can be migrated without breaking API

**Use `UtcDatetimeStr` for:**
- Existing public API fields typed as `str` that cannot be changed
- Provides UTC normalization without breaking API compatibility
- Runtime type stays `str`, but guarantees UTC-normalized ISO format

**Use plain `datetime` for:**
- Local variables (unnecessary verbosity)
- Function parameters accepting any aware datetime (more flexible)

**Key insight:** Type annotations have no runtime cost outside Pydantic validation contexts. Using `UtcDatetime` as a return type documents intent and enables static analysis without any performance penalty or Pydantic coupling.

### UtcDatetimeStr Details

`UtcDatetimeStr` addresses a specific migration challenge: existing public API fields typed as `str` that store ISO datetime strings. Converting these to `UtcDatetime` would be a breaking API change (runtime type changes from `str` to `datetime`).

**Behavior:**
```python
# Accepts ISO strings, normalizes to UTC, returns as string
field: UtcDatetimeStr

# Input with timezone offset → normalized to UTC
"2025-01-24T12:00:00-05:00"  →  "2025-01-24T17:00:00+00:00"

# Input without timezone → treated as UTC
"2025-01-24T12:00:00"  →  "2025-01-24T12:00:00+00:00"
```

**Use case example:**
```python
# Public API - cannot change str to UtcDatetime
class EvalSpec(BaseModel):
    created: UtcDatetimeStr  # Was: str, now normalized to UTC
```

**Runtime compatibility:**
- `isinstance(eval.created, str)` → `True` (still a string)
- String operations work: `eval.created.split("T")`, `eval.created[0:10]`
- No breaking changes to user code

---

## Architecture Summary

The timezone architecture follows a layered defense:

1. **Compile-time:** DTZ lint rules prevent naive datetime creation in Python code
2. **Runtime boundaries:** `UtcDatetime` validates/coerces at Pydantic model boundaries
3. **Dataframe ingestion:** `import_record()` ensures all temporal columns have UTC-aware datetime64 dtype

Once data passes these layers, all datetimes are guaranteed UTC-aware. This enables safe dataframe operations and reliable serialization.
