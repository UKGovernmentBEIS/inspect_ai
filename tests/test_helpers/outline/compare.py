"""Row-for-row comparison of oracle vs candidate outline rows.

Divergences outside the three signed-off classes fail with a row-level
diff. The signed-off classes (`design/large-samples.md`, structural
skeleton mechanism 7) are encoded as explicit allowances:

1. **Structural tool/subtask rows** — legacy elevates the tool/subtask
   event over its span (absorbing tool rows into turns, dropping bare
   ones); the skeleton's structural row wins. Subtask spans elevate
   identically (``unwrap_subtasks``), so they ride under this class.
   Allowed: a candidate-only ``span`` row of type ``tool``/``subtask``,
   and matching a candidate tool/subtask span row against the legacy
   elevated event row (anchors differ by the span-begin offset). Turn
   counts split by an allowed extra row reconcile by sum. The reverse
   direction is the ratified leaf-tool exclusion itself (mechanism 1:
   dissolved leaf tool spans carry no skeleton row) — legacy keeps a
   span node when the tool span holds no direct tool event to elevate.
2. **Cross-span consecutive score merging** — legacy merges adjacent
   score rows across span boundaries; the candidate merges per span.
   Allowed: one oracle ``scoring`` row matches a run of candidate
   ``scoring`` rows whose counts sum to it (and vice versa).
3. **"N turns" click anchor = gap lower bound** — turn-row anchors are
   exempt from comparison (legacy anchors at the first model event; the
   candidate anchors at the gap's lower bound).

Every class-1 allowance is gated on `ParityFacts` — span facts derived
**independently from the raw events** (never from the skeleton under
test), so a defective skeleton cannot satisfy its own allowance: a
candidate-only tool/subtask row must name a real span at its anchor
(fabricated spans fail), and an oracle-only tool row must anchor a span
the exclusion predicate legitimately dissolves (a wrongly dropped
escape-hatch span fails).

New divergence classes must be added here deliberately (with a spec
sign-off note), never silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.event._tree import EventTreeSpan, event_tree

from .oracle import OutlineRow


class ParityFacts(NamedTuple):
    """Event-derived span facts gating the class-1 allowances."""

    structural_spans: dict[int, tuple[str | None, str | None]]
    """Tool/subtask span begin index -> (type, name)."""

    excluded_tool_begins: frozenset[int]
    """Begin indexes of tool spans the leaf-tool exclusion predicate
    (mechanism 1) legitimately dissolves: no child spans, no models, no
    notables, under the escape-hatch threshold."""


class _SpanAggregate(NamedTuple):
    events: int
    models: int
    notable: bool


def parity_facts(
    events: Sequence[Event], escape_hatch_events: int = 1000
) -> ParityFacts:
    """Compute allowance-gating facts directly from the event sequence.

    Deliberately independent of ``sample_skeleton`` (whose output is the
    artifact under test): the exclusion predicate is re-derived here over
    ``event_tree`` so allowances cannot be satisfied by a defective
    skeleton.

    Args:
        events: Complete event sequence for a sample.
        escape_hatch_events: The skeleton policy's escape-hatch threshold
            (pass the same value the skeleton was produced with).
    """
    index_of = {id(ev): i for i, ev in enumerate(events)}
    structural: dict[int, tuple[str | None, str | None]] = {}
    excluded: set[int] = set()

    def visit(span: EventTreeSpan) -> _SpanAggregate:
        count = 1 + (1 if span.end is not None else 0)
        models = 0
        notable = False
        has_child_span = False
        for child in span.children:
            if isinstance(child, EventTreeSpan):
                has_child_span = True
                child_agg = visit(child)
                count += child_agg.events
                models += child_agg.models
                notable = notable or child_agg.notable
            else:
                count += 1
                models += isinstance(child, ModelEvent)
                notable = notable or child.event in ("score", "checkpoint")
        if span.type in ("tool", "subtask"):
            structural[index_of[id(span.begin)]] = (span.type, span.name)
        if (
            span.type == "tool"
            and not has_child_span
            and models == 0
            and not notable
            and count < escape_hatch_events
        ):
            excluded.add(index_of[id(span.begin)])
        return _SpanAggregate(events=count, models=models, notable=notable)

    for node in event_tree(events):
        if isinstance(node, EventTreeSpan):
            visit(node)
    # legacy step-shaped tool/subtask spans (skeleton folds step pairs)
    for i, ev in enumerate(events):
        if (
            isinstance(ev, StepEvent)
            and ev.action == "begin"
            and ev.type in ("tool", "subtask")
        ):
            structural[i] = (ev.type, ev.name)

    return ParityFacts(
        structural_spans=structural, excluded_tool_begins=frozenset(excluded)
    )


class Divergence(NamedTuple):
    """One unexplained row-level difference."""

    oracle_index: int
    candidate_index: int
    oracle_row: OutlineRow | None
    candidate_row: OutlineRow | None

    def render(self) -> str:
        """One-line description for the failure diff."""
        return (
            f"oracle[{self.oracle_index}]={self.oracle_row} != "
            f"candidate[{self.candidate_index}]={self.candidate_row}"
        )


class _RunSum(NamedTuple):
    """Result of summing a run of mergeable rows."""

    consumed: int
    total: int


def _rows_equal(oracle: OutlineRow, candidate: OutlineRow) -> bool:
    if oracle.kind != candidate.kind or oracle.depth != candidate.depth:
        return False
    if oracle.kind == "turns":
        # class 3: anchors exempt
        return oracle.total == candidate.total
    if oracle.kind == "scoring":
        return oracle.total == candidate.total and oracle.anchor == candidate.anchor
    return (
        oracle.name == candidate.name
        and oracle.type == candidate.type
        and oracle.anchor == candidate.anchor
        and oracle.total == candidate.total
    )


def diff_outline_rows(
    oracle_rows: list[OutlineRow],
    candidate_rows: list[OutlineRow],
    facts: ParityFacts,
) -> list[Divergence]:
    """Compare row streams; returns unexplained divergences (empty == parity)."""

    def is_real_structural_row(row: OutlineRow) -> bool:
        return (
            row.kind == "span"
            and row.type in ("tool", "subtask")
            and row.anchor is not None
            and facts.structural_spans.get(row.anchor) == (row.type, row.name)
        )

    def class1_row_match(oracle: OutlineRow, candidate: OutlineRow) -> bool:
        """Legacy elevated tool/subtask event row == candidate span row."""
        return (
            oracle.kind == "event"
            and oracle.type in ("tool", "subtask")
            and candidate.type == oracle.type
            and oracle.depth == candidate.depth
            and is_real_structural_row(candidate)
            and oracle.anchor is not None
            and candidate.anchor is not None
            and candidate.anchor <= oracle.anchor
        )

    def turns_run(
        rows: list[OutlineRow], start: int, depth: int, budget: int
    ) -> _RunSum:
        """Sum consecutive turns rows at ``depth``, up to ``budget``.

        Class-1 candidate span rows inside the run are stepped over.
        """
        index = start
        total = 0
        while index < len(rows) and total < budget:
            row = rows[index]
            if row.kind == "turns" and row.depth == depth and row.total is not None:
                total += row.total
                index += 1
            elif is_real_structural_row(row) and row.depth >= depth:
                index += 1
            else:
                break
        return _RunSum(consumed=index - start, total=total)

    def scoring_run(rows: list[OutlineRow], start: int, budget: int) -> _RunSum:
        index = start
        total = 0
        while index < len(rows) and total < budget:
            row = rows[index]
            if row.kind == "scoring" and row.total is not None:
                total += row.total
                index += 1
            else:
                break
        return _RunSum(consumed=index - start, total=total)

    divergences: list[Divergence] = []
    o = 0
    c = 0
    while o < len(oracle_rows) or c < len(candidate_rows):
        oracle = oracle_rows[o] if o < len(oracle_rows) else None
        candidate = candidate_rows[c] if c < len(candidate_rows) else None

        if oracle is not None and candidate is not None:
            if _rows_equal(oracle, candidate):
                o += 1
                c += 1
                continue
            if class1_row_match(oracle, candidate):
                o += 1
                c += 1
                continue
            # class 1: turn counts split by allowed extra rows — reconcile
            # a run of candidate turns (± tool/subtask span rows) against
            # one oracle turns row by sum, and vice versa
            if oracle.kind == "turns" and oracle.total is not None:
                run = turns_run(candidate_rows, c, oracle.depth, oracle.total)
                if run.consumed > 1 and run.total == oracle.total:
                    o += 1
                    c += run.consumed
                    continue
            if candidate.kind == "turns" and candidate.total is not None:
                run = turns_run(oracle_rows, o, candidate.depth, candidate.total)
                if run.consumed > 1 and run.total == candidate.total:
                    o += run.consumed
                    c += 1
                    continue
            # class 2: cross-span score merging — sums must reconcile
            if oracle.kind == "scoring" and oracle.total is not None:
                run = scoring_run(candidate_rows, c, oracle.total)
                if run.consumed > 1 and run.total == oracle.total:
                    o += 1
                    c += run.consumed
                    continue
            if candidate.kind == "scoring" and candidate.total is not None:
                run = scoring_run(oracle_rows, o, candidate.total)
                if run.consumed > 1 and run.total == candidate.total:
                    o += run.consumed
                    c += 1
                    continue

        # class 1: candidate-only structural tool/subtask span row (must
        # name a real span at its anchor — fabricated spans fail)
        if candidate is not None and is_real_structural_row(candidate):
            c += 1
            continue
        # class 1 (reverse): oracle-only tool span row for a span the
        # exclusion predicate legitimately dissolves (mechanism 1); a
        # wrongly dropped escape-hatch span is NOT in the excluded set
        if (
            oracle is not None
            and oracle.kind == "span"
            and oracle.type == "tool"
            and oracle.anchor in facts.excluded_tool_begins
        ):
            o += 1
            continue

        divergences.append(Divergence(o, c, oracle, candidate))
        o += 1 if oracle is not None else 0
        c += 1 if candidate is not None else 0

    return divergences


def render_diff(divergences: list[Divergence]) -> str:
    """Render divergences one per line for assertion messages."""
    return "\n".join(d.render() for d in divergences)
