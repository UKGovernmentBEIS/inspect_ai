"""Parity oracle harness: legacy pipeline vs skeleton-fed outline rows (#23).

Differential acceptance for the skeleton (design/large-samples.md,
structural skeleton mechanism 7): the frozen legacy in-memory pipeline
(`test_helpers.outline.oracle`) vs the skeleton-fed derivation
(`test_helpers.outline.candidate`), compared row-for-row across converted
real logs and the synthetic skeleton fixtures, across collapse states.
Divergences outside the three signed-off classes (encoded in
`test_helpers.outline.compare`) fail with a row-level diff.
"""

import json
from pathlib import Path

import pytest
from test_helpers.outline.candidate import candidate_outline_rows
from test_helpers.outline.compare import diff_outline_rows, render_diff
from test_helpers.outline.oracle import CollapseState, oracle_outline_rows

from inspect_ai.event._event import Event
from inspect_ai.log import read_eval_log
from inspect_ai.log._skeleton import SampleSkeleton, sample_skeleton

_TESTS_DIR = Path(__file__).resolve().parent.parent
_FIXTURES_DIR = Path(__file__).resolve().parent / "test_skeleton"

_COLLAPSE_STATES: tuple[CollapseState, ...] = ("default", "expanded", "collapsed")


def _assert_parity(events: list[Event], skeleton: SampleSkeleton, context: str) -> None:
    assert not skeleton.overflow, f"{context}: notable overflow unsupported by harness"
    for state in _COLLAPSE_STATES:
        oracle = oracle_outline_rows(events, state)
        candidate = candidate_outline_rows(skeleton, state)
        divergences = diff_outline_rows(oracle, candidate)
        assert not divergences, (
            f"{context} [{state}]: {len(divergences)} divergence(s)\n"
            f"{render_diff(divergences)}\n"
            f"--- oracle rows ---\n" + "\n".join(map(str, oracle)) + "\n"
            "--- candidate rows ---\n" + "\n".join(map(str, candidate))
        )


def _log_paths() -> list[Path]:
    return sorted(_TESTS_DIR.rglob("*.eval"))


@pytest.mark.parametrize("log_path", _log_paths(), ids=lambda p: p.stem[:60])
def test_outline_parity_real_logs(log_path: Path) -> None:
    """Row-for-row parity over every real .eval log in the test corpus."""
    log = read_eval_log(str(log_path), resolve_attachments=False)
    for sample in log.samples or []:
        if not sample.events:
            continue
        events = list(sample.events)
        _assert_parity(
            events,
            sample_skeleton(events),
            f"{log_path.name}#{sample.id}_epoch_{sample.epoch}",
        )


def test_outline_parity_corpus_coverage() -> None:
    """The corpus exercises enough samples for the differential to mean much."""
    checked = 0
    for log_path in _log_paths():
        log = read_eval_log(str(log_path), resolve_attachments=False)
        checked += sum(1 for s in log.samples or [] if s.events)
    assert checked >= 20


@pytest.mark.parametrize(
    "fixture_path",
    sorted(_FIXTURES_DIR.glob("*.json")),
    ids=lambda path: path.stem,
)
def test_outline_parity_fixtures(fixture_path: Path) -> None:
    """Parity over the synthetic skeleton fixture suite."""
    from pydantic import TypeAdapter

    from inspect_ai._util.constants import get_deserializing_context
    from inspect_ai.event._event import DiscriminatedEvent
    from inspect_ai.log._skeleton import SkeletonPolicy

    data = json.loads(fixture_path.read_text())
    adapter: TypeAdapter[list[Event]] = TypeAdapter(list[DiscriminatedEvent])
    events = adapter.validate_python(
        data["events"], context=get_deserializing_context()
    )
    defaults = SkeletonPolicy()
    policy_data = data.get("policy", {})
    policy = SkeletonPolicy(
        notable_cap=policy_data.get("notable_cap", defaults.notable_cap),
        escape_hatch_events=policy_data.get(
            "escape_hatch_events", defaults.escape_hatch_events
        ),
    )
    skeleton = sample_skeleton(events, policy)
    if skeleton.overflow:
        # past-cap notables are omitted from the skeleton; the candidate
        # cannot reproduce their rows (outline degrades with an "N omitted"
        # marker instead — see mechanism 3)
        pytest.skip("notable overflow fixture")
    _assert_parity(list(events), skeleton, fixture_path.stem)


def test_outline_parity_per_span_collapse() -> None:
    """Toggling each span individually keeps parity (collapse-state sweep)."""
    log_path = next(
        p
        for p in _log_paths()
        if p.name.endswith("input-task_hxs4q9azL3ySGkjJirypKZ.eval")
    )
    log = read_eval_log(str(log_path), resolve_attachments=False)
    assert log.samples and log.samples[0].events
    events = list(log.samples[0].events)
    skeleton = sample_skeleton(events)
    assert skeleton.spans
    for span in skeleton.spans:
        state = frozenset({span.id})
        oracle = oracle_outline_rows(events, state)
        candidate = candidate_outline_rows(skeleton, state)
        divergences = diff_outline_rows(oracle, candidate)
        assert not divergences, (
            f"collapse={span.id} ({span.name}): {render_diff(divergences)}"
        )


def test_outline_parity_detects_injected_regression() -> None:
    """A corrupted skeleton (wrong gap_models / dropped span) fails the diff."""
    log_path = next(
        p
        for p in _log_paths()
        if p.name.endswith("input-task_hxs4q9azL3ySGkjJirypKZ.eval")
    )
    log = read_eval_log(str(log_path), resolve_attachments=False)
    assert log.samples and log.samples[0].events
    events = list(log.samples[0].events)
    skeleton = sample_skeleton(events)
    oracle = oracle_outline_rows(events, "expanded")

    # sanity: unmodified skeleton is at parity
    assert not diff_outline_rows(oracle, candidate_outline_rows(skeleton, "expanded"))

    # wrong gap_models: shift a model count into a different gap
    corrupted = skeleton.model_copy(deep=True)
    span = next(s for s in corrupted.spans if sum(s.gap_models) > 0)
    gap_index = next(i for i, g in enumerate(span.gap_models) if g > 0)
    span.gap_models[gap_index] += 5
    assert diff_outline_rows(oracle, candidate_outline_rows(corrupted, "expanded")), (
        "corrupted gap_models must produce a failing row diff"
    )

    # dropped span: remove a structural span row entirely
    dropped = skeleton.model_copy(deep=True)
    removed = dropped.spans.pop()
    dropped.spans = [
        s.model_copy(update={"parent": None}) if s.parent == len(dropped.spans) else s
        for s in dropped.spans
    ]
    assert removed is not None
    assert diff_outline_rows(oracle, candidate_outline_rows(dropped, "expanded")), (
        "dropped span must produce a failing row diff"
    )
