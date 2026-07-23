from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from test_helpers.chunked_corpus import ChunkedCorpus


# Chunked-format corpora (large-samples effort): converted once per
# session; imports are function-local so conftest stays light for runs
# that never request them.


@pytest.fixture(scope="session")
def chunked_corpus(tmp_path_factory: pytest.TempPathFactory) -> "ChunkedCorpus":
    """Chunked conversions of every test `.eval` log (default chunk size).

    Realistic writer-policy corpus: most samples fit a single chunk.
    """
    from test_helpers.chunked_corpus import build_chunked_corpus

    from inspect_ai.log._recorders.chunked.format import DEFAULT_CHUNK_SIZE

    return build_chunked_corpus(
        tmp_path_factory.mktemp("chunked_corpus"), DEFAULT_CHUNK_SIZE
    )


@pytest.fixture(scope="session")
def chunked_corpus_small_chunks(
    tmp_path_factory: pytest.TempPathFactory,
) -> "ChunkedCorpus":
    """Chunked conversions with a tiny chunk size (multi-chunk samples)."""
    from test_helpers.chunked_corpus import (
        CORPUS_SMALL_CHUNK_SIZE,
        build_chunked_corpus,
    )

    return build_chunked_corpus(
        tmp_path_factory.mktemp("chunked_corpus_small"), CORPUS_SMALL_CHUNK_SIZE
    )
