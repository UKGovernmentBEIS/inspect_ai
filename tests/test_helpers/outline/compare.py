"""Row-for-row comparison of oracle vs candidate outline rows.

Divergences outside the three signed-off classes fail with a row-level
diff. The signed-off classes (`design/large-samples.md`, structural
skeleton mechanism 7) are encoded as explicit allowances:

1. **Structural tool/subtask rows** — legacy elevates the tool/subtask
   event over its span (absorbing tool rows into turns, dropping bare
   ones); the skeleton's structural row wins. Allowed: a candidate-only
   ``span`` row of type ``tool``/``subtask``, and matching a candidate
   tool/subtask span row against the legacy elevated event row (anchors
   differ by the span-begin offset). Turn counts split by an allowed
   extra row reconcile by sum. The reverse direction is the ratified
   leaf-tool exclusion itself (mechanism 1: dissolved leaf tool spans
   carry no skeleton row): an oracle-only ``span`` row of type ``tool``
   is allowed — legacy keeps a span node when the tool span holds no
   direct tool event to elevate.
2. **Cross-span consecutive score merging** — legacy merges adjacent
   score rows across span boundaries; the candidate merges per span.
   Allowed: one oracle ``scoring`` row matches a run of candidate
   ``scoring`` rows whose counts sum to it (and vice versa).
3. **"N turns" click anchor = gap lower bound** — turn-row anchors are
   exempt from comparison (legacy anchors at the first model event; the
   candidate anchors at the gap's lower bound).

New divergence classes must be added here deliberately (with a spec
sign-off note), never silently.
"""

from __future__ import annotations

from typing import NamedTuple

from .oracle import OutlineRow


class Divergence(NamedTuple):
    """One unexplained row-level difference."""

    oracle_index: int
    candidate_index: int
    oracle_row: OutlineRow | None
    candidate_row: OutlineRow | None

    def render(self) -> str:
        return (
            f"oracle[{self.oracle_index}]={self.oracle_row} != "
            f"candidate[{self.candidate_index}]={self.candidate_row}"
        )


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


def _class1_row_match(oracle: OutlineRow, candidate: OutlineRow) -> bool:
    """Legacy elevated tool/subtask event row == candidate structural span row."""
    return (
        oracle.kind == "event"
        and candidate.kind == "span"
        and oracle.type in ("tool", "subtask")
        and candidate.type == oracle.type
        and oracle.depth == candidate.depth
        and oracle.anchor is not None
        and candidate.anchor is not None
        and candidate.anchor <= oracle.anchor
    )


def _class1_candidate_only(candidate: OutlineRow) -> bool:
    """Candidate structural span row legacy absorbed into a turn or dropped."""
    return candidate.kind == "span" and candidate.type in ("tool", "subtask")


def diff_outline_rows(
    oracle_rows: list[OutlineRow], candidate_rows: list[OutlineRow]
) -> list[Divergence]:
    """Compare row streams; returns unexplained divergences (empty == parity)."""
    divergences: list[Divergence] = []
    o = 0
    c = 0

    def turns_run(
        rows: list[OutlineRow], start: int, depth: int, budget: int
    ) -> tuple[int, int]:
        """Sum consecutive turns rows at ``depth``, up to ``budget``.

        Class-1 candidate span rows inside the run are stepped over.
        Returns (rows consumed, models summed).
        """
        index = start
        total = 0
        while index < len(rows) and total < budget:
            row = rows[index]
            if row.kind == "turns" and row.depth == depth and row.total is not None:
                total += row.total
                index += 1
            elif _class1_candidate_only(row) and row.depth >= depth:
                index += 1
            else:
                break
        return index - start, total

    def scoring_run(rows: list[OutlineRow], start: int, budget: int) -> tuple[int, int]:
        index = start
        total = 0
        while index < len(rows) and total < budget:
            row = rows[index]
            if row.kind == "scoring" and row.total is not None:
                total += row.total
                index += 1
            else:
                break
        return index - start, total

    while o < len(oracle_rows) or c < len(candidate_rows):
        oracle = oracle_rows[o] if o < len(oracle_rows) else None
        candidate = candidate_rows[c] if c < len(candidate_rows) else None

        if oracle is not None and candidate is not None:
            if _rows_equal(oracle, candidate):
                o += 1
                c += 1
                continue
            if _class1_row_match(oracle, candidate):
                o += 1
                c += 1
                continue
            # class 1: turn counts split by allowed extra rows — reconcile
            # a run of candidate turns (± tool/subtask span rows) against
            # one oracle turns row by sum, and vice versa
            if oracle.kind == "turns" and oracle.total is not None:
                consumed, total = turns_run(
                    candidate_rows, c, oracle.depth, oracle.total
                )
                if consumed > 1 and total == oracle.total:
                    o += 1
                    c += consumed
                    continue
            if (
                candidate is not None
                and candidate.kind == "turns"
                and candidate.total is not None
            ):
                consumed, total = turns_run(
                    oracle_rows, o, candidate.depth, candidate.total
                )
                if consumed > 1 and total == candidate.total:
                    o += consumed
                    c += 1
                    continue
            # class 2: cross-span score merging — sums must reconcile
            if oracle.kind == "scoring" and oracle.total is not None:
                consumed, total = scoring_run(candidate_rows, c, oracle.total)
                if consumed > 1 and total == oracle.total:
                    o += 1
                    c += consumed
                    continue
            if candidate.kind == "scoring" and candidate.total is not None:
                consumed, total = scoring_run(oracle_rows, o, candidate.total)
                if consumed > 1 and total == candidate.total:
                    o += consumed
                    c += 1
                    continue

        # class 1: candidate-only structural tool/subtask span row
        if candidate is not None and _class1_candidate_only(candidate):
            c += 1
            continue
        # class 1 (reverse): oracle-only tool span row for a leaf-excluded
        # tool span (ratified mechanism 1 — the dissolved row)
        if oracle is not None and oracle.kind == "span" and oracle.type == "tool":
            o += 1
            continue

        divergences.append(Divergence(o, c, oracle, candidate))
        o += 1 if oracle is not None else 0
        c += 1 if candidate is not None else 0

    return divergences


def render_diff(divergences: list[Divergence]) -> str:
    return "\n".join(d.render() for d in divergences)
