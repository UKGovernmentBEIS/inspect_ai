"""Chunked-format corpora built from the repo's test `.eval` logs.

CI corpora generation for the large-samples effort: the (always-chunk)
converter runs over every `.eval` log under ``tests/``, producing logs
where every sample has the chunked per-sample shape (shell +
messages/events/calls/attachments sequences + skeleton and stats
sidecars). Later efforts' tests exercise the chunked shape against
these corpora without needing a writer. Request the corpora via the
session-scoped ``chunked_corpus`` / ``chunked_corpus_small_chunks``
fixtures in ``tests/conftest.py``.
"""

from pathlib import Path
from typing import NamedTuple

from inspect_ai.event import ModelEvent
from inspect_ai.log import read_eval_log
from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked

CORPUS_SMALL_CHUNK_SIZE = 3
"""Chunk size small enough that real test logs produce multi-chunk samples."""

_TESTS_DIR = Path(__file__).resolve().parent.parent


class ChunkedCorpus(NamedTuple):
    """Chunked-format conversions of the test `.eval` logs."""

    chunk_size: int
    logs: dict[Path, Path]
    """Original log path -> converted (all-samples-chunked) log path."""
    excluded: list[Path]
    """Logs excluded for dangling pool refs (see `_has_dangling_pool_refs`)."""


def _has_dangling_pool_refs(log_path: Path) -> bool:
    """True when pool refs survive read-time resolution (pool is gone).

    ``read_eval_log`` resolves ``events_data`` pools and clears
    ``input_refs``/``call_refs``; refs that survive have no pool to
    resolve against. The one known case is the unreleased interim
    ``message_pool`` sample shape, dropped without migration when pools
    were consolidated into ``events_data`` (#3519) — e.g. the
    ``log_message_deduplication.eval`` fixture. Such logs convert
    without error, but the converter would re-ground the stale refs
    into its new message sequence, fabricating event inputs — corrupt
    corpus data — so they are excluded.
    """
    log = read_eval_log(str(log_path), resolve_attachments=False)
    return any(
        isinstance(event, ModelEvent)
        and (event.input_refs or (event.call and event.call.call_refs))
        for sample in log.samples or []
        for event in sample.events
    )


def build_chunked_corpus(output_dir: Path, chunk_size: int) -> ChunkedCorpus:
    """Convert every `.eval` log under ``tests/`` to the chunked shape.

    Output mirrors the logs' directory structure under ``output_dir``
    (test log basenames happen to be unique today, but sibling fixture
    dirs shouldn't be able to collide). Conversion failures propagate —
    a broken converter must not silently shrink corpus coverage
    (mirroring ``test_skeleton_real_logs``' stance for the reader). The
    only exclusion is the documented dangling-pool-refs predicate.
    """

    def convert(log_path: Path) -> Path:
        target_dir = output_dir / log_path.parent.relative_to(_TESTS_DIR)
        convert_eval_logs_to_chunked(
            str(log_path), str(target_dir), chunk_size=chunk_size
        )
        return target_dir / log_path.name

    included: list[Path] = []
    excluded: list[Path] = []
    for log_path in sorted(_TESTS_DIR.rglob("*.eval")):
        (excluded if _has_dangling_pool_refs(log_path) else included).append(log_path)

    logs = {log_path: convert(log_path) for log_path in included}
    assert logs, f"no convertible .eval logs found under {_TESTS_DIR}"
    return ChunkedCorpus(chunk_size=chunk_size, logs=logs, excluded=excluded)
