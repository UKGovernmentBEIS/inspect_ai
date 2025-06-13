from typing import Sequence

from google.genai.types import (
    Candidate,
    GroundingChunk,
    GroundingSupport,
    Segment,
)

from inspect_ai._util.citation import Citation, UrlCitation


def get_candidate_citations(candidate: Candidate) -> list[Citation]:
    """Extract citations from Google AI candidate grounding metadata.

    Understanding Google API Grounding Citations: `GroundingChunk`'s, `GroundingSupport`, and `Segment`'s

    1. Grounding Chunks (`GroundingChunk`)
       What they are: The raw source material that the AI retrieved to support its response.
       Structure:
         - Web (`GroundingChunkWeb`): Content from web searches
           - domain: The website domain
           - title: Page title
           - uri: Web page URL
       Think of chunks as: The library books or web pages that contain the information.

    2. Segments (`Segment`)
       What they are: Specific portions of the AI's generated response text.
       Structure:
         - start_index & end_index: Byte positions in the response text
         - text: The actual text from the response that this segment represents
       Think of segments as: Specific sentences or paragraphs in the AI's response that need citations.

    3. Grounding Support (`GroundingSupport`)
       What they are: The bridge that connects segments of the AI's response to the chunks that support them.
       Structure:
         - grounding_chunk_indices: Array of integers pointing to specific chunks (e.g., [1,3,4] means chunks 1, 3, and 4 support this claim)
         - segment: Which part of the response this support applies to
       Think of support as: The footnotes that say "this claim in my response is backed up by these specific sources."

    Args:
        candidate: The Google AI candidate response containing grounding metadata

    Returns:
        A list of `Citation` objects linking response segments to their web sources.
        Currently only handles `GroundingChunkWeb` sources.
    """
    return (
        []
        if (
            not candidate.content
            or not candidate.content.parts
            or not (metadata := candidate.grounding_metadata)
            or not (chunks := metadata.grounding_chunks)
            or not (supports := metadata.grounding_supports)
        )
        else [
            citation
            for support in supports
            for citation in _citations_from_support(support, chunks)
        ]
    )


def _create_citation_from_chunk_and_segment(
    chunk: GroundingChunk, segment: Segment
) -> UrlCitation | None:
    """Create a citation from a chunk and segment, returning None if chunk is not web-based."""
    return (
        UrlCitation(
            url=chunk.web.uri,
            title=chunk.web.title,
            cited_text=(
                (segment.start_index or 0, segment.end_index)
                if segment.end_index is not None
                else None
            ),
        )
        if (chunk.web and chunk.web.uri)
        else None
    )


def _citations_from_support(
    support: GroundingSupport, chunks: Sequence[GroundingChunk]
) -> list[Citation]:
    return (
        []
        if support.segment is None or support.grounding_chunk_indices is None
        else [
            citation
            for chunk_index in support.grounding_chunk_indices
            if chunk_index < len(chunks)
            if (
                citation := _create_citation_from_chunk_and_segment(
                    chunks[chunk_index], support.segment
                )
            )
        ]
    )
