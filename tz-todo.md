# Temporal Data Migration Plan

This document outlines concrete steps to bring the codebase into compliance with [design/temporal-data-handling.md](design/temporal-data-handling.md).

**Status:** In Progress
**Last Updated:** 2025-01-24

---

## Temporal Field Audit

### Category A: Serialized to JSON Logs (6 datetime fields)

| Model | Field | Type | Current Default | Serializer | File |
|-------|-------|------|-----------------|------------|------|
| BaseEvent | timestamp | datetime | datetime_now_utc | ✓ | event/_base.py:19 |
| ModelEvent | completed | datetime \| None | None | ✓ | event/_model.py:56 |
| ToolEvent | completed | datetime \| None | None | ✓ | event/_tool.py:52 |
| SubtaskEvent | completed | datetime \| None | None | ✓ | event/_subtask.py:45 |
| SandboxEvent | completed | datetime \| None | None | ✓ | event/_sandbox.py:37 |
| ProvenanceData | timestamp | datetime | datetime_now_utc | ✗ | scorer/_metric.py:66 |

**Recommendation**: Convert all to `UtcDatetime` / `UtcDatetime | None`

### Category B: Internal Only (4 date fields)

| Model | Field | Type | File |
|-------|-------|------|------|
| BaseModelDefinition | release_date | date \| None | analysis/_prepare/model_data/model_data.py:85 |
| BaseModelDefinition | knowledge_cutoff_date | date \| None | analysis/_prepare/model_data/model_data.py:88 |
| ModelInfo | release_date | date \| None | analysis/_prepare/model_data/model_data.py:13 |
| ModelInfo | knowledge_cutoff_date | date \| None | analysis/_prepare/model_data/model_data.py:14 |

**Recommendation**: Convert to `UtcDate | None` (or plain `date` - see Unresolved)

### Category C: String Fields (5 fields)

| Model | Field | Current Type | Set Via | File |
|-------|-------|--------------|---------|------|
| EvalStats | started_at | str | iso_now() | log/_log.py:859 |
| EvalStats | completed_at | str | iso_now() | log/_log.py:862 |
| EvalSpec | created | str | - | log/_log.py:711 |
| LogOverview | started_at | str | - | log/_file.py:71 |
| LogOverview | completed_at | str | - | log/_file.py:72 |

**Recommendation**: Convert to `UtcDatetime` with validators + serializers for backward compat

---

## Implementation Plan

### Phase 0: Fix iso_now() (CRITICAL)

**File**: `src/inspect_ai/_util/dateutil.py`

**Issue**: Current implementation violates "never query local timezone" principle from design:
```python
# Current (WRONG):
def iso_now(timespec: str = "auto") -> str:
    return datetime.now().astimezone().isoformat(timespec=timespec)
```

**Fix**:
```python
def iso_now(timespec: str = "auto") -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec=timespec)
```

**Rationale**: Querying system timezone is expensive and violates design principle that "Inspect operates entirely in UTC, never queries system timezone."

### Phase 1: Create Type Aliases & Update Function Signatures

**File**: `src/inspect_ai/_util/dateutil.py`

**Step 1: Add type aliases**
```python
from typing import Annotated, Any
from pydantic import BeforeValidator, AwareDatetime
from datetime import datetime, date, time, timezone

def _coerce_to_utc_aware(v: Any) -> datetime:
    """
    Coerce to UTC-aware datetime.
    - Strings: Parse with UTC fallback (legacy logs)
    - Aware datetimes: Convert to UTC
    - Naive datetimes: Coerce to UTC (treats as UTC per design)
    - Numeric: Pass through to AwareDatetime (handles int/float timestamps)
    """
    if isinstance(v, str):
        return datetime_from_iso_format_safe(v).astimezone(timezone.utc)
    if isinstance(v, datetime):
        # Design requirement: "transforms naive data to UTC rather than rejecting it"
        return datetime_safe(v, timezone.utc).astimezone(timezone.utc)
    return v  # Let AwareDatetime handle numeric timestamps

def _coerce_to_utc_date(v: Any) -> date:
    """Coerce to date."""
    if isinstance(v, str):
        return date.fromisoformat(v)
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return v

def _coerce_to_utc_time(v: Any) -> time:
    """Coerce to time."""
    if isinstance(v, str):
        return time.fromisoformat(v)
    if isinstance(v, datetime):
        return v.timetz() if v.tzinfo else v.time()
    if isinstance(v, time):
        return v
    return v

UtcDatetime = Annotated[AwareDatetime, BeforeValidator(_coerce_to_utc_aware)]
UtcDate = Annotated[date, BeforeValidator(_coerce_to_utc_date)]
UtcTime = Annotated[time, BeforeValidator(_coerce_to_utc_time)]
```

**Step 2: Update function return types** (no runtime cost - documentation only)
```python
def datetime_now_utc() -> UtcDatetime:  # Was: -> datetime
    """Return current datetime in UTC with timezone info."""
    return datetime.now(timezone.utc)

def datetime_from_iso_format_safe(
    input: str, fallback_tz: timezone = timezone.utc
) -> UtcDatetime:  # Was: -> datetime
    """Parse ISO format datetime string, applying fallback timezone if none specified."""
    return datetime_safe(datetime.fromisoformat(input), fallback_tz)

def datetime_safe(dt: datetime, fallback_tz: timezone = timezone.utc) -> UtcDatetime:  # Was: -> datetime
    """Ensure datetime has timezone info, applying fallback if naive."""
    return dt if dt.tzinfo else dt.replace(tzinfo=fallback_tz)
```

**Rationale**: Type annotations document intent and enable static analysis with zero runtime overhead.

### Phase 2: Convert Category A (Event datetime fields)

**Files**: `event/_base.py`, `event/_model.py`, `event/_tool.py`, `event/_subtask.py`, `event/_sandbox.py`, `scorer/_metric.py`

**Changes**:
- Import: `from inspect_ai._util.dateutil import UtcDatetime`
- Replace: `timestamp: datetime` → `timestamp: UtcDatetime`
- Replace: `completed: datetime | None` → `completed: UtcDatetime | None`
- Keep existing `@field_serializer` decorators

### Phase 3: Convert Category C (String temporal fields)

**Files**: `log/_log.py`, `log/_file.py`

**Approach**: Use `UtcDatetimeStr` to maintain `str` runtime type while providing UTC normalization

**Changes**:
- Import: `from inspect_ai._util.dateutil import UtcDatetimeStr`
- Replace: `created: str` → `created: UtcDatetimeStr`
- Replace: `started_at: str` → `started_at: UtcDatetimeStr`
- Replace: `completed_at: str` → `completed_at: UtcDatetimeStr`
- No validators/serializers needed (built into UtcDatetimeStr)
- No code changes needed (iso_now() already returns UtcDatetimeStr)

**Benefits**:
- Zero breaking changes (runtime type stays str)
- Automatic UTC normalization via BeforeValidator
- Old logs with timezone offsets auto-convert to UTC

### Phase 4: Convert Category B (Date fields)

**File**: `analysis/_prepare/model_data/model_data.py`

**Changes**:
- Import: `from inspect_ai._util.dateutil import UtcDate`
- Replace: `release_date: date | None` → `release_date: UtcDate | None`
- Replace: `knowledge_cutoff_date: date | None` → `knowledge_cutoff_date: UtcDate | None`

### Phase 5: Fix import_record() Gaps

**Status**: ✅ COMPLETED (commit 369a6f10e)

**File**: `src/inspect_ai/analysis/_dataframe/record.py`

Both fixes have been implemented:
- ✅ YAML path now uses `datetime_safe()` for naive datetime handling
- ✅ Early return validation ensures UTC conversion via `datetime_safe()`
- ✅ Added `datetime_from_iso_format_safe()` import and `_from_iso()` helper

### Phase 6: Testing

**New test file**: `tests/analysis/test_temporal_types.py`

Test cases:
- `UtcDatetime` accepts TZ-aware ISO strings
- `UtcDatetime` accepts TZ-less ISO strings (coerces to UTC)
- `UtcDatetime` coerces naive datetime objects to UTC
- `UtcDatetime` converts non-UTC aware datetimes to UTC
- `UtcDatetime` handles numeric timestamps (int/float)
- `UtcDate` parses ISO date strings
- String fields (Category C) maintain backward compat
- `iso_now()` returns UTC string (after Phase 0)
- `import_record()` YAML path uses UTC (not local)
- `import_record()` all paths return UTC-aware datetimes
- Full eval log round-trip preserves temporal data correctly
- Existing log corpus deserializes successfully
- DTZ lint rules catch violations

**Additional verification**:
- Run `ruff check` to verify DTZ rules enabled and passing
- Audit any remaining DTZ violations that need fixing

### Phase 7: Documentation

**Tasks**:
- Document `UtcDatetime` usage guidelines in developer docs
- Document when to use `UtcDatetime` vs plain `datetime`:
  - Use `UtcDatetime` for Pydantic model fields and function return types
  - Use plain `datetime` for local variables and flexible function parameters
- Add architecture summary referencing `design/temporal-data-handling.md`
- Update CHANGELOG with migration notes and breaking changes

---

## Resolved Decisions

### Implementation Approach
**Decision**: Phased implementation
- Category A (events) is highest priority
- Category C (strings) has migration impact on calling code
- Category B (dates) is lowest priority

### iso_now() Strategy
**Decision**: Fix to return UTC in Phase 0, do not deprecate
- Change implementation to `datetime.now(timezone.utc).isoformat(timespec=timespec)`
- Calling code continues passing strings
- UtcDatetime validators parse strings to datetime
- Minimal disruption, backward compatible

### Type Naming
**Decision**: Use `UtcDatetime`, `UtcDate`, `UtcTime`
- Names are accurate - dates do have timezone context
- A date represents a span of real-world time that depends on the timezone
- `2025-01-24` in UTC covers different absolute time than `2025-01-24` in US/Eastern

### UtcDatetime Usage Scope
**Decision**: Use for both Pydantic fields AND function return types
- Pydantic model fields: Validation applies at runtime
- Function return types: Documentation + static analysis with zero runtime cost
- Type annotations have no runtime overhead outside Pydantic validation contexts
- Documents intent without performance penalty or Pydantic coupling

### ProvenanceData Serializer
**Decision**: No explicit `@field_serializer` needed - use Pydantic default
- Pydantic's default `AwareDatetime` serialization uses `.isoformat()` - identical to `datetime_to_iso_format_safe()`
- Round-trip tests confirm correct behavior
- Event models have explicit serializers for historical reasons (predated UtcDatetime)
- ProvenanceData benefits from simpler, standard Pydantic serialization

### Category C String Fields (Phase 3)
**Decision**: Use `UtcDatetimeStr` for public API compatibility
- **Problem**: EvalSpec.created, EvalStats.started_at/completed_at are public API fields typed as `str`
- **Cannot use UtcDatetime**: Changing `str` → `datetime` is breaking API change
- **Solution**: `UtcDatetimeStr` - validates and normalizes to UTC while keeping `str` runtime type
- **Behavior**:
  - Accepts ISO datetime strings
  - Parses and converts to UTC
  - Returns as UTC-normalized ISO string
  - `isinstance(field, str)` stays `True`
- **Benefits**: UTC normalization without breaking changes
- **Fields to convert**:
  - EvalSpec.created (public API)
  - EvalStats.started_at (public API)
  - EvalStats.completed_at (public API)
  - LogOverview.started_at (internal)
  - LogOverview.completed_at (internal)

---

## Unresolved Questions

None currently.

---

## Migration Checklist

### Phase 0
- [x] Fix `iso_now()` to use UTC (not local timezone)

### Phase 1
- [x] Create `UtcDatetime`, `UtcDate`, and `UtcTime` type aliases
- [x] Fix `_before_validate_utc_datetime()` to coerce (not reject) naive datetimes
- [x] Update function return types: `datetime_now_utc()`, `datetime_from_iso_format_safe()`, `datetime_safe()`

### Phase 2
- [x] Convert BaseEvent.timestamp
- [x] Convert *Event.completed fields (4 models)
- [x] Convert ProvenanceData.timestamp
- [x] Decided: ProvenanceData uses Pydantic default (no explicit serializer needed)

### Phase 3
- [x] Create UtcDatetimeStr type alias in dateutil.py
- [x] Convert EvalSpec.created to UtcDatetimeStr
- [x] Convert EvalStats.started_at to UtcDatetimeStr
- [x] Convert EvalStats.completed_at to UtcDatetimeStr
- [x] Convert LogOverview.started_at to UtcDatetimeStr
- [x] Convert LogOverview.completed_at to UtcDatetimeStr
- [ ] Test round-trip with old logs (mixed timezone formats)

### Phase 4
- [x] Convert Category B date fields

### Phase 5
- [x] Fix import_record() YAML path (commit 369a6f10e)
- [x] Fix import_record() early return validation (commit 369a6f10e)

### Phase 6
- [x] Add comprehensive tests (test_utc_datetime_str.py with 21 tests)
- [x] Run `ruff check` to verify DTZ rules passing (all checks passed)
- [x] Audit and fix any remaining DTZ violations (no DTZ violations found)
- [x] Verify existing log corpus compatibility (tested 4+ logs with timezone offsets, all normalized to UTC)
- [x] Full eval log round-trip test (validated via read_eval_log with old logs)

### Phase 7
- [ ] Document `UtcDatetime` usage guidelines
- [ ] Document when to use `UtcDatetime` vs plain `datetime`
- [ ] Add architecture summary to docs
- [ ] Update CHANGELOG with migration notes
