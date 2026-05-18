# Event-Store Transcript Decisions

## 2026-05-18: `Transcript.materialize_events()` Must Not Pretend To Read Full History

**Decision:** Use the conservative option: `Transcript.materialize_events()` should only return resident events when the transcript has not been truncated. If `events_truncated` is true and no full-history source is attached, it should fail loudly rather than silently returning a partial transcript.

**Status:** Implemented. Truncated transcripts now raise instead of returning the resident window.

**Rationale:** The current architecture keeps the full history in the buffer DB and exposes it through `SampleBufferDatabase.open_sample_history()` / `SampleHistory`, not through `Transcript`. Critical full-history consumers already use `SampleHistory` directly. A `materialize_events()` method that returns `list(self._events)` on a bounded transcript is misleading because `self._events` is only the resident window.

**Implementation Guidance:**

- `Transcript.materialize_events()` may return `list(self._events)` when `events_truncated` is false.
- If `events_truncated` is true, raise a clear error such as `RuntimeError("Full transcript history is not available from this Transcript")`.
- Do not use `materialize_events()` for completion writing, scanner/sample-end full-history reconstruction, or other full-history paths; use `SampleHistory` instead.
- Keep `Transcript.events`, `recent_events()`, `last_event`, and `event_count` as resident/live-view APIs.

**Future Option:** If a later design attaches a full-history provider to `Transcript`, `materialize_events()` can be extended to read through that provider. Until then, failing loudly is safer than returning partial history under a full-history-sounding API.

## 2026-05-18: Bounded Retry Errors Should Not Silently Pretend To Have Full Suffix History

**Decision:** Retry errors should use buffer-backed `SampleHistory` when available so bounded transcript eviction does not remove retry diagnostic context. Returning an empty suffix remains the no-store fallback for truncated transcripts.

**Status:** Implemented for buffer-backed retries. `_eval_retry_error()` now opens sample history before retry buffer cleanup and constructs the suffix from the latest `ModelEvent` in full logical history.

**Rationale:** The spec target was store-backed retry suffix construction: find the most recent `ModelEvent` in the full sample history and include events from that point onward, even when the live transcript resident window has evicted the relevant events. Returning `[]` under `events_truncated` avoids misleading partial retry context only when no buffer history is available.

**Behavioral Impact:** Buffer-backed bounded samples preserve retry diagnostics. Non-buffer truncated transcripts still omit retry event suffixes rather than returning an arbitrary resident tail.

**Implementation Guidance:**

- Document the no-store fallback: bounded/truncated retry errors omit event suffixes unless store-backed retry reconstruction is available.
- Do not change `_eval_retry_error()` to use `Transcript.events_since_last()` when `events_truncated` is true; that would return a potentially arbitrary resident suffix.
- Keep tests covering both buffer-backed full-history suffix reconstruction and no-store conservative empty-suffix behavior.


## 2026-05-18: Bounded Transcript Rollout Is Opt-In Initially

**Decision:** `INSPECT_TRANSCRIPT_BOUNDED` should default to off. Users must opt in explicitly for bounded live transcript retention during the initial rollout.

**Rationale:** The implementation is designed to preserve final `.eval` logs through buffer-backed `SampleHistory`, but bounded mode still changes live/resident transcript semantics and has conservative fallbacks for cases such as truncated retry diagnostics. Defaulting off reduces rollout risk while keeping the feature available for memory-sensitive users and test environments.

**Implementation Guidance:**

- `Transcript.default_bounded()` should return `False` when `INSPECT_TRANSCRIPT_BOUNDED` is unset.
- Treat `1`, `true`, `yes`, and `on` as opt-in true values.
- Other values, including `0`, `false`, `no`, and `off`, should leave bounded mode disabled.
- A future PR can flip the default after broader validation and release-note coverage.
