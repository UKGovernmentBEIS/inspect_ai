"""Phase 5 unit tests: TUI ``consume_score_event`` + chip-window rotation.

Covers:

- ``SessionState.consume_score_event`` mounts a ``ScoreChip`` at the
  current end-of-transcript position.
- Score chips evict alongside their surrounding message groups when
  the conversation window cap (``_MAX_ASSISTANT_TURNS``) rotates.
- ``consume_inspect_event`` routes the ``"score"`` discriminator.

The chip-widget pilot (mounting a chip and verifying the rendered
text in a Textual screen) is left as a slower follow-on; pure-state
coverage is what this Phase 5 wiring needs.
"""

from __future__ import annotations

from typing import Any

from acp.schema import (
    AgentMessageChunk,
    SessionNotification,
    TextContentBlock,
    UserMessageChunk,
)

from inspect_ai.agent._acp.tui.state import (
    _MAX_ASSISTANT_TURNS,
    MessageGroup,
    ScoreChip,
    SessionState,
)


def _score_payload(
    *,
    value: object = "C",
    explanation: str | None = "passed test",
    scorer: str | None = "exact-match",
) -> dict[str, object]:
    """Build a serialized ``ScoreEvent`` payload as the wire would deliver it."""
    score: dict[str, object] = {"value": value}
    if explanation is not None:
        score["explanation"] = explanation
    payload: dict[str, object] = {"event": "score", "score": score}
    if scorer is not None:
        payload["scorer"] = scorer
    return payload


def _agent_chunk(
    text: str, *, message_id: str = "mid-1", model: str = "phase5/model"
) -> SessionNotification:
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.model": model},
    )
    return SessionNotification(session_id="sid", update=chunk)


def _user_chunk(text: str, *, message_id: str = "mu-1") -> SessionNotification:
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.user_source": "input"},
    )
    return SessionNotification(session_id="sid", update=chunk)


# ---------------------------------------------------------------------------
# consume_score_event: chip mounting + decoding
# ---------------------------------------------------------------------------


def test_consume_score_event_mounts_chip_at_end_of_items() -> None:
    """A score event lands as a ``ScoreChip`` at the current end of items."""
    state = SessionState()
    state.consume(_user_chunk("hello"))
    state.consume(_agent_chunk("hi"))
    assert isinstance(state.items[0], MessageGroup)
    assert isinstance(state.items[1], MessageGroup)

    state.consume_score_event(
        _score_payload(value="C", explanation="exact match", scorer="exact")
    )
    assert len(state.items) == 3
    chip = state.items[-1]
    assert isinstance(chip, ScoreChip)
    assert chip.scorer == "exact"
    assert chip.value == "C"
    assert chip.passed is True
    assert chip.reason == "exact match"


def test_consume_score_event_marks_incorrect_score_as_failed() -> None:
    """``"I"`` value resolves to ``passed=False``."""
    state = SessionState()
    state.consume_score_event(_score_payload(value="I", explanation="wrong"))
    chip = state.items[-1]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is False
    assert chip.value == "I"


def test_consume_score_event_numeric_value_has_no_pass_fail() -> None:
    """Numeric scores yield ``passed=None`` — no binary verdict to render."""
    state = SessionState()
    state.consume_score_event(_score_payload(value=0.5, explanation=None))
    chip = state.items[-1]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is None
    assert chip.value == "0.5"
    assert chip.reason is None


def test_consume_score_event_unique_chip_ids() -> None:
    """Each chip gets a fresh client-side id so the transcript widget can key it."""
    state = SessionState()
    state.consume_score_event(_score_payload(scorer="s1"))
    state.consume_score_event(_score_payload(scorer="s2"))
    ids = [c.chip_id for c in state.items if isinstance(c, ScoreChip)]
    assert len(ids) == 2
    assert ids[0] != ids[1]


def test_consume_inspect_event_routes_score_discriminator() -> None:
    """``consume_inspect_event`` branches by ``event`` — score lands as a chip."""
    state = SessionState()
    state.consume_inspect_event(_score_payload())
    assert any(isinstance(item, ScoreChip) for item in state.items)


def test_consume_inspect_event_ignores_unknown_event_types() -> None:
    """Future event types that aren't yet handled silently drop."""
    state = SessionState()
    state.consume_inspect_event({"event": "interrupt", "source": "user_cancel"})
    assert state.items == []


# ---------------------------------------------------------------------------
# Per-scorer ``scoring · X…`` indicator via ``span_begin(type="scorer")``
# ---------------------------------------------------------------------------


def _scorer_span_begin(scorer_name: str) -> dict[str, Any]:
    """Build a serialized ``span_begin(type="scorer", name=X)`` payload."""
    return {
        "event": "span_begin",
        "id": f"span-{scorer_name}",
        "name": scorer_name,
        "type": "scorer",
    }


def test_scorer_span_begin_mounts_named_indicator_chip() -> None:
    """A per-scorer ``span_begin`` mounts a ``scoring · <scorer>…`` chip.

    Each scorer in the task runner's loop opens
    ``span(name=<scorer>, type="scorer")`` — that's our per-scorer
    progress signal. The indicator names the scorer so the operator
    can see what's currently running.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    chip = state.items[-1]
    assert isinstance(chip, ScoreChip)
    assert chip.reason == "scoring · includes…"
    # Indicator chip: no scorer / value / passed — distinguishes it
    # from the per-score chips that follow.
    assert chip.scorer is None
    assert chip.value == ""
    assert chip.passed is None


def test_score_event_replaces_live_indicator() -> None:
    """A ``ScoreEvent`` removes the still-mounted indicator + appends the score chip.

    Means at any moment during scoring the operator sees either
    ``scoring · X…`` (currently running) OR ``score · X · …`` (just
    finished) — never both at once for the same scorer, and never an
    idle gap.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    state.consume_score_event(
        {
            "event": "score",
            "score": {"value": "C", "explanation": "match"},
            "scorer": "includes",
        }
    )
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 1
    assert chips[0].scorer == "includes"
    assert chips[0].passed is True


def test_per_scorer_indicators_progress_through_scoring_phase() -> None:
    """Multiple scorers each produce begin → indicator → score → next.

    Pinned regression: at every step the operator has visible
    progress — the indicator names the active scorer, then the score
    chip names the result.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    # First scorer running — indicator is the only chip.
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 1
    assert chips[0].reason == "scoring · includes…"
    # First score lands — indicator replaced by real chip.
    state.consume_score_event(
        {
            "event": "score",
            "score": {"value": "C"},
            "scorer": "includes",
        }
    )
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 1
    assert chips[0].scorer == "includes"
    # Second scorer begins — fresh indicator for it, prior score stays.
    state.consume_inspect_event(_scorer_span_begin("match_accuracy"))
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 2
    assert chips[0].scorer == "includes"
    assert chips[1].reason == "scoring · match_accuracy…"
    # Second score lands — second indicator replaced.
    state.consume_score_event(
        {
            "event": "score",
            "score": {"value": 0.75},
            "scorer": "match_accuracy",
        }
    )
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 2
    assert chips[0].scorer == "includes"
    assert chips[1].scorer == "match_accuracy"


def test_span_end_clears_indicator_when_no_score_event_fired() -> None:
    """``span_end`` for the in-flight scorer clears its indicator.

    Repro: scorer returned ``None`` (legitimate — some scorers opt
    out per-sample) or raised before firing a ``ScoreEvent``. The
    span still ends cleanly; without ``span_end`` handling the
    indicator would persist past the scorer's actual lifetime,
    telling the operator "scoring · X…" is still running when
    everything has moved on.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    assert any(isinstance(it, ScoreChip) for it in state.items)
    # Same id as the begin event (`_scorer_span_begin` uses
    # ``f"span-{scorer_name}"``).
    state.consume_inspect_event({"event": "span_end", "id": "span-includes"})
    assert not any(isinstance(it, ScoreChip) for it in state.items)


def test_span_end_after_score_event_is_a_noop() -> None:
    """Score event resolved the indicator; the trailing span_end has nothing to do."""
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    state.consume_score_event(
        {
            "event": "score",
            "score": {"value": "C"},
            "scorer": "includes",
        }
    )
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 1
    assert chips[0].scorer == "includes"  # the real score chip, not the indicator
    # span_end for the same span id — must not remove the real score chip.
    state.consume_inspect_event({"event": "span_end", "id": "span-includes"})
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(chips) == 1
    assert chips[0].scorer == "includes"


def test_span_end_for_unrelated_span_id_does_nothing() -> None:
    """Only the matching span id clears — agent / tool / outer span_ends ignored.

    The wire firehose delivers every ``span_end``; if any of them
    cleared the indicator the in-flight scorer signal would vanish
    mid-scorer whenever an unrelated nested span happened to close.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    state.consume_inspect_event({"event": "span_end", "id": "some-other-span"})
    assert any(isinstance(it, ScoreChip) for it in state.items)


def test_span_end_without_active_indicator_is_a_noop() -> None:
    """No indicator mounted → span_end can't clear anything; no notify."""
    state = SessionState()
    fires: list[None] = []
    state.subscribe(lambda: fires.append(None))
    state.consume_inspect_event({"event": "span_end", "id": "any"})
    assert state.items == []
    assert len(fires) == 0


def test_mark_complete_clears_stranded_scoring_indicator() -> None:
    """Session-ending while an indicator is still mounted drops it.

    Repro: the connection drops between ``span_begin(type="scorer")``
    and the matching ``ScoreEvent`` (or the ScoreEvent itself never
    reaches the client). Without this, the operator sees ``scoring ·
    X…`` pinned forever next to a lifecycle pill that's already
    flipped to ``complete``.
    """
    from inspect_ai.agent._acp.tui.state import ScoreChip as _ScoreChip

    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("includes"))
    assert any(isinstance(it, _ScoreChip) for it in state.items)
    state.mark_complete()
    # Indicator gone — postmortem view shows no phantom in-progress
    # scorer.
    assert not any(isinstance(it, _ScoreChip) for it in state.items)
    assert state.lifecycle == "complete"


def test_mark_complete_no_indicator_is_a_noop() -> None:
    """No stranded indicator → mark_complete leaves items untouched."""
    state = SessionState()
    state.mark_complete()
    assert state.items == []
    assert state.lifecycle == "complete"


def test_completed_scores_survive_mark_complete() -> None:
    """Real score chips (not indicators) stay in the postmortem view."""
    state = SessionState()
    state.consume_score_event(_score_payload(value="C", scorer="includes"))
    chips_before = [it for it in state.items if isinstance(it, ScoreChip)]
    state.mark_complete()
    chips_after = [it for it in state.items if isinstance(it, ScoreChip)]
    assert chips_after == chips_before


def test_indicator_persists_when_scorer_fails_before_emitting_score() -> None:
    """If a scorer raises before its ``ScoreEvent`` lands, the indicator stays.

    The indicator becomes the last-recorded "what was running" signal —
    exactly what the operator needs to attribute the failure. The
    next scorer's begin replaces it cleanly.
    """
    state = SessionState()
    state.consume_inspect_event(_scorer_span_begin("flaky_scorer"))
    # No score for flaky_scorer — second scorer kicks off.
    state.consume_inspect_event(_scorer_span_begin("includes"))
    chips = [it for it in state.items if isinstance(it, ScoreChip)]
    # First indicator was removed by the defensive cleanup, second is
    # the only one mounted.
    assert len(chips) == 1
    assert chips[0].reason == "scoring · includes…"


def _scorers_outer_span_begin() -> dict[str, Any]:
    """Outer scoring-phase boundary span as it lands on the wire.

    ``span(name="scorers")`` is opened without a ``type`` argument,
    but ``util._span.span`` defaults ``type`` to ``name`` when
    omitted — so the wire payload carries ``type="scorers"``. Tests
    must mirror this or they pass against a state-shape that doesn't
    match production (the bug we hit first time around).
    """
    return {
        "event": "span_begin",
        "id": "span-outer",
        "name": "scorers",
        "type": "scorers",
    }


def test_outer_scorers_span_does_not_mount_a_chip() -> None:
    """The outer scoring-phase boundary span doesn't produce a chip.

    Only the inner per-scorer ``type="scorer"`` spans drive the
    indicator — the outer is the scoring-phase boundary, not a
    per-scorer progress signal.
    """
    state = SessionState()
    state.consume_inspect_event(_scorers_outer_span_begin())
    assert state.items == []


def test_outer_scorers_span_clears_plan_strip() -> None:
    """Entering the scoring phase drops a still-mounted plan strip.

    The agent loop has finished by the time the outer scoring boundary
    fires — leaving the plan visible during scoring reads as "still
    working on the plan" even though we've moved on.
    """
    from acp.schema import AgentPlanUpdate, PlanEntry

    state = SessionState()
    state.consume(
        SessionNotification(
            session_id="sid",
            update=AgentPlanUpdate(
                session_update="plan",
                entries=[
                    PlanEntry(content="step 1", status="completed", priority="medium"),
                    PlanEntry(content="step 2", status="completed", priority="medium"),
                ],
            ),
        )
    )
    assert state.plan_entries is not None
    fires: list[None] = []
    state.subscribe(lambda: fires.append(None))
    state.consume_inspect_event(_scorers_outer_span_begin())
    assert state.plan_entries is None
    # Subscribers fire so the plan strip widget re-evaluates and hides.
    assert len(fires) == 1


def test_outer_scorers_span_no_plan_still_latches_scoring_started() -> None:
    """No plan → scoring boundary still latches ``_scoring_started`` and notifies once.

    Even without a plan to clear, the boundary flips the
    ``_scoring_started`` latch (so any later replayed
    ``AgentPlanUpdate`` gets suppressed instead of resurrecting the
    plan). One subscriber fire — second redundant boundary doesn't
    re-notify.
    """
    state = SessionState()
    fires: list[None] = []
    state.subscribe(lambda: fires.append(None))
    state.consume_inspect_event(_scorers_outer_span_begin())
    assert state.plan_entries is None
    assert state._scoring_started is True
    assert len(fires) == 1
    # Idempotent — second boundary doesn't re-notify.
    state.consume_inspect_event(_scorers_outer_span_begin())
    assert len(fires) == 1


def test_late_replayed_plan_update_after_scoring_is_suppressed() -> None:
    """Late-attach race: raw replay → scoring boundary; semantic replay → stale plan.

    Repro for the late-attach replay ordering bug. Session router
    replays all raw events first, then all semantic. If the operator
    attaches mid- or post-scoring, the raw firehose clears the plan
    via the scorers boundary, then the semantic firehose would
    replay the historical ``AgentPlanUpdate`` from earlier in the
    sample — leaving the operator with a "plan resurrects after
    scoring" view of a session that has clearly moved on.

    Once ``_scoring_started`` latches, any plan update is stale.
    """
    from acp.schema import AgentPlanUpdate, PlanEntry

    state = SessionState()
    # Raw replay phase — clear the plan.
    state.consume_inspect_event(_scorers_outer_span_begin())
    assert state.plan_entries is None
    # Semantic replay phase — would normally re-mount the plan.
    state.consume(
        SessionNotification(
            session_id="sid",
            update=AgentPlanUpdate(
                session_update="plan",
                entries=[
                    PlanEntry(content="stale", status="completed", priority="medium")
                ],
            ),
        )
    )
    # Plan stays cleared — the scoring-started latch suppressed the
    # stale update.
    assert state.plan_entries is None


def test_plan_updates_before_scoring_boundary_apply_normally() -> None:
    """Plan updates pre-scoring are accepted; the latch only fires from the boundary."""
    from acp.schema import AgentPlanUpdate, PlanEntry

    state = SessionState()
    state.consume(
        SessionNotification(
            session_id="sid",
            update=AgentPlanUpdate(
                session_update="plan",
                entries=[
                    PlanEntry(content="step 1", status="in_progress", priority="medium")
                ],
            ),
        )
    )
    assert state.plan_entries is not None
    assert len(state.plan_entries) == 1


def test_inner_scorer_span_does_not_clear_plan() -> None:
    """Only the outer ``scorers`` boundary clears the plan.

    Inner ``type="scorer"`` spans run after the outer; by then the
    plan is already gone. Explicit per-scorer clearing would either
    no-op (plan already cleared) or — if a future code path mounts
    the plan after the outer span — silently destroy it. Keep the
    clearing tied to the one well-defined boundary.
    """
    from acp.schema import AgentPlanUpdate, PlanEntry

    state = SessionState()
    state.consume(
        SessionNotification(
            session_id="sid",
            update=AgentPlanUpdate(
                session_update="plan",
                entries=[
                    PlanEntry(content="step 1", status="completed", priority="medium")
                ],
            ),
        )
    )
    state.consume_inspect_event(_scorer_span_begin("includes"))
    assert state.plan_entries is not None


def test_other_span_begin_events_ignored() -> None:
    """Only ``type="scorer"`` spans produce an indicator chip.

    The wire firehose delivers every ``span_begin`` (agent / tool /
    sub-agent / etc.); the client filters to the spans with
    operator-meaningful rendering.
    """
    state = SessionState()
    state.consume_inspect_event(
        {
            "event": "span_begin",
            "id": "span-1",
            "name": "agent",
            "type": "agent",
        }
    )
    state.consume_inspect_event(
        {
            "event": "span_begin",
            "id": "span-2",
            "name": "bash",
            "type": "tool",
        }
    )
    assert state.items == []


def test_consume_score_event_notifies_subscribers() -> None:
    """Chip mount fires the state-change subscriber callback."""
    state = SessionState()
    fires: list[None] = []
    state.subscribe(lambda: fires.append(None))
    state.consume_score_event(_score_payload())
    assert len(fires) == 1


# ---------------------------------------------------------------------------
# Window rotation: chips evict with their surrounding turns
# ---------------------------------------------------------------------------


def test_score_chip_evicted_with_oldest_window_turn() -> None:
    """Chips anchored before the surviving window drop in the same sweep.

    Pushes one chip in among the first few assistant turns, then
    streams enough more assistants to push the window past
    :data:`_MAX_ASSISTANT_TURNS`. The early chip must be gone (it
    belongs to an evicted turn); chips inside the surviving window
    must remain.
    """
    state = SessionState()
    # Three early assistants, then an early chip, then enough turns to
    # push past the cap.
    state.consume(_user_chunk("u0", message_id="mu-0"))
    for i in range(3):
        state.consume(_agent_chunk(f"early-{i}", message_id=f"mid-early-{i}"))
    state.consume_score_event(
        _score_payload(value="I", explanation="early failed", scorer="early")
    )
    early_chip_count = sum(1 for it in state.items if isinstance(it, ScoreChip))
    assert early_chip_count == 1

    # Now fill the window past the cap.
    for i in range(_MAX_ASSISTANT_TURNS + 5):
        state.consume(_agent_chunk(f"a-{i}", message_id=f"mid-{i}"))

    # Recent chip — should survive the window.
    state.consume_score_event(
        _score_payload(value="C", explanation="recent passed", scorer="recent")
    )

    surviving_chips = [it for it in state.items if isinstance(it, ScoreChip)]
    assert len(surviving_chips) == 1, (
        "the early chip should have been evicted with its surrounding turn; "
        "the recent chip belongs to the surviving window"
    )
    assert surviving_chips[0].scorer == "recent"


def test_recent_score_chip_stays_after_one_more_turn() -> None:
    """A chip just before the survival window edge survives a single new turn."""
    state = SessionState()
    state.consume(_user_chunk("u0", message_id="mu-0"))
    for i in range(_MAX_ASSISTANT_TURNS):
        state.consume(_agent_chunk(f"a-{i}", message_id=f"mid-{i}"))
    # Chip after the most-recent assistant, well inside the window.
    state.consume_score_event(_score_payload(scorer="anchored"))
    chip = next(it for it in state.items if isinstance(it, ScoreChip))
    # One more assistant arrives but the chip still lives between
    # turns we kept (after the first surviving assistant).
    state.consume(_agent_chunk("a-extra", message_id="mid-extra"))
    assert chip in state.items
