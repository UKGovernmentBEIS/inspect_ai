from typing import Sequence

from google.genai.types import (
    Candidate,
    GroundingChunk,
    GroundingSupport,
    Segment,
)

from inspect_ai._util.citation import Citation, UrlCitation
from inspect_ai._util.content import Content, ContentText


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


def distribute_citations_to_text_parts(
    content: list[Content],
    global_citations: list[Citation],
) -> list[Content]:
    """Distribute citations with global text indexes to individual ContentText parts.

    Google's API returns citations with start_index/end_index that refer to positions
    in a global concatenation of all text content (via response.text). This is
    documented here:

    https://ai.google.dev/gemini-api/docs/google-search#attributing_sources_with_inline_citations

    This is in turn a global aggregation of all ContentText parts, as implemented here:

    https://github.com/googleapis/python-genai/blob/88db6445255c4fe16b1360571ea04e7ebd811d81/google/genai/types.py#L6090-L6130

    This function redistributes those citations to the individual ContentText
    parts they reference, adjusting the indexes to be relative to each part's text.

    The global text is constructed by concatenating only ContentText.text values,
    in order, skipping any ContentReasoning parts.

    Args:
        content: List of content parts (ContentText and ContentReasoning mixed)
        global_citations: Citations with indexes relative to global text concatenation

    Returns:
        The same content list with ContentText.citations populated (mutated in place)
    """
    if not global_citations:
        return content

    # Build offset mapping: track start/end positions of each ContentText in global text
    text_part_offsets: list[tuple[int, int, int]] = []  # (start, end, content_index)
    global_offset = 0

    for i, part in enumerate(content):
        if isinstance(part, ContentText):
            text_length = len(part.text)
            text_part_offsets.append((global_offset, global_offset + text_length, i))
            global_offset += text_length

    # Distribute citations to appropriate ContentText parts
    for citation in global_citations:
        # Only process citations with tuple-based cited_text (start, end)
        if (
            not isinstance(citation, UrlCitation)
            or citation.cited_text is None
            or not isinstance(citation.cited_text, tuple)
        ):
            continue

        cite_start, cite_end = citation.cited_text

        # Find which ContentText part contains this citation
        for part_start, part_end, content_idx in text_part_offsets:
            # Citation starts within or at the boundary of this part
            if part_start <= cite_start < part_end:
                # Adjust citation indexes to be relative to this part
                adjusted_citation = UrlCitation(
                    url=citation.url,
                    title=citation.title,
                    cited_text=(cite_start - part_start, cite_end - part_start),
                    internal=citation.internal,
                )

                # Add to this part's citations (mutate in place)
                text_part = content[content_idx]
                assert isinstance(text_part, ContentText)
                if text_part.citations is None:
                    text_part.citations = []
                else:
                    # Convert to list if it's a tuple/sequence
                    text_part.citations = list(text_part.citations)
                text_part.citations.append(adjusted_citation)
                break

    return content
