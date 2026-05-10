import pytest

from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.filestore import (
    Manifest,
    SampleManifest,
    Segment,
    segments_for_sample_cursor,
)


def _manifest(segs: list[Segment], sample_segs: list[int]) -> Manifest:
    return Manifest(
        metrics=[],
        samples=[
            SampleManifest(
                summary=EvalSampleSummary(id="s", epoch=0, input="i", target="t"),
                segments=sample_segs,
            )
        ],
        segments=segs,
    )


def test_segments_for_sample_cursor_returns_all_when_cursor_is_minus_one() -> None:
    # Real ids start at 1 (SQL AUTOINCREMENT), so test data uses 1..3.
    segs = [
        Segment(id=i, last_event_id=i + 1, last_attachment_id=i + 1) for i in range(3)
    ]
    m = _manifest(segs, [0, 1, 2])
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=-1,
        after_attachment_id=-1,
        after_message_pool_id=-1,
        after_call_pool_id=-1,
    )
    assert [s.id for s in out] == [0, 1, 2]


def test_segments_for_sample_cursor_returns_all_when_cursor_is_none() -> None:
    segs = [
        Segment(id=i, last_event_id=i + 1, last_attachment_id=i + 1) for i in range(3)
    ]
    m = _manifest(segs, [0, 1, 2])
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=None,
        after_attachment_id=None,
        after_message_pool_id=None,
        after_call_pool_id=None,
    )
    assert [s.id for s in out] == [0, 1, 2]


def test_segments_for_sample_cursor_prunes_by_event_id() -> None:
    # All cursors set high enough that only the event-id dimension gates.
    segs = [
        Segment(id=0, last_event_id=5, last_attachment_id=0),
        Segment(id=1, last_event_id=10, last_attachment_id=0),
        Segment(id=2, last_event_id=15, last_attachment_id=0),
    ]
    m = _manifest(segs, [0, 1, 2])
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=10,
        after_attachment_id=100,
        after_message_pool_id=100,
        after_call_pool_id=100,
    )
    # Only segment 2 has last_event_id > 10; others have no dimension above
    # any cursor so the OR-filter excludes them.
    assert [s.id for s in out] == [2]


def test_segments_for_sample_cursor_or_logic_across_cursor_types() -> None:
    # Segment 0 qualifies via the attachment dimension only; segment 1 has
    # no dimension above any cursor and is excluded.
    segs = [
        Segment(id=0, last_event_id=5, last_attachment_id=100),
        Segment(id=1, last_event_id=5, last_attachment_id=5),
    ]
    m = _manifest(segs, [0, 1])
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=10,
        after_attachment_id=50,
        after_message_pool_id=50,
        after_call_pool_id=50,
    )
    assert [s.id for s in out] == [0]


@pytest.mark.parametrize(
    "empty_pool_id",
    [
        pytest.param(0, id="legacy-default"),
        # The schema default is 0; -1 covers writers that adopt an explicit
        # sentinel in the future. The floor handles both.
        pytest.param(-1, id="explicit-no-data"),
    ],
)
def test_segments_for_sample_cursor_excludes_empty_pool_segments(
    empty_pool_id: int,
) -> None:
    # Regression for the streaming viewer infinite-loop bug. A segment
    # with no pool entries leaves the pool fields at the writer's
    # "no items of this type" sentinel (0 in the current schema). The
    # initial client cursor is -1, so without the floor at 0 the filter
    # evaluates `0 > -1 = True` and pins every empty-pool segment in
    # the response. Combined with `max-segments=25` the viewer loops on
    # the first 25 segments forever.
    segs = [
        Segment(
            id=0,
            last_event_id=10,
            last_attachment_id=10,
            last_message_pool_id=empty_pool_id,
            last_call_pool_id=empty_pool_id,
        ),
        Segment(
            id=1,
            last_event_id=20,
            last_attachment_id=20,
            last_message_pool_id=empty_pool_id,
            last_call_pool_id=empty_pool_id,
        ),
    ]
    m = _manifest(segs, [0, 1])
    out = segments_for_sample_cursor(
        m,
        m.samples[0],
        after_event_id=20,
        after_attachment_id=20,
        after_message_pool_id=-1,
        after_call_pool_id=-1,
    )
    assert out == []


def test_segments_for_sample_cursor_returns_in_id_order() -> None:
    # Manifest stores segments out of insertion order; consumers concatenate
    # results so id order must be preserved regardless.
    segs = [
        Segment(id=2, last_event_id=3, last_attachment_id=0),
        Segment(id=0, last_event_id=1, last_attachment_id=0),
        Segment(id=1, last_event_id=2, last_attachment_id=0),
    ]
    m = _manifest(segs, [0, 1, 2])
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=-1,
        after_attachment_id=-1,
        after_message_pool_id=-1,
        after_call_pool_id=-1,
    )
    assert [s.id for s in out] == [0, 1, 2]


def test_segments_for_sample_cursor_ignores_segments_not_in_sample() -> None:
    segs = [
        Segment(id=i, last_event_id=i + 1, last_attachment_id=i + 1) for i in range(3)
    ]
    m = _manifest(segs, [0, 2])  # sample excludes segment 1
    sample = m.samples[0]
    out = segments_for_sample_cursor(
        m,
        sample,
        after_event_id=-1,
        after_attachment_id=-1,
        after_message_pool_id=-1,
        after_call_pool_id=-1,
    )
    assert [s.id for s in out] == [0, 2]
