from anthropic.types import (
    CitationCharLocation,
    CitationCharLocationParam,
    CitationContentBlockLocation,
    CitationContentBlockLocationParam,
    CitationPageLocation,
    CitationPageLocationParam,
    CitationsWebSearchResultLocation,
    CitationWebSearchResultLocationParam,
    TextCitation,
    TextCitationParam,
)

from inspect_ai._util.citation import (
    Citation,
    DocumentBlockCitation,
    DocumentCharCitation,
    DocumentPageCitation,
    UrlCitation,
)


def to_inspect_citation(input: TextCitation) -> Citation:
    match input:
        case CitationsWebSearchResultLocation(
            cited_text=cited_text,
            title=title,
            url=url,
            encrypted_index=encrypted_index,
        ):
            # Sanitize a citation to work around https://github.com/anthropics/anthropic-sdk-python/issues/965.
            return UrlCitation(
                cited_text=cited_text,
                title=title
                if title is None or len(title) <= 255
                else title[:254] + "…",
                url=url,
                internal={"encrypted_index": encrypted_index},
            )

        case CitationCharLocation(
            cited_text=cited_text,
            document_index=document_index,
            document_title=title,
            end_char_index=end_char_index,
            start_char_index=start_char_index,
        ):
            return DocumentCharCitation(
                cited_text=cited_text,
                title=title,
                char_range=(start_char_index, end_char_index),
                internal={"document_index": document_index},
            )

        case CitationPageLocation(
            cited_text=cited_text,
            document_index=document_index,
            document_title=title,
            end_page_number=end_page_number,
            start_page_number=start_page_number,
        ):
            return DocumentPageCitation(
                cited_text=cited_text,
                title=title,
                page_range=(start_page_number - 1, end_page_number - 1),
                internal={"document_index": document_index},
            )

        case CitationContentBlockLocation(
            cited_text=cited_text,
            document_index=document_index,
            document_title=title,
            end_block_index=end_block_index,
            start_block_index=start_block_index,
        ):
            return DocumentBlockCitation(
                cited_text=cited_text,
                title=title,
                block_range=(start_block_index, end_block_index),
                internal={"document_index": document_index},
            )

    assert False, f"Unexpected citation type: {input.type}"


def to_anthropic_citation(input: Citation) -> TextCitationParam:
    cited_text = input.cited_text
    assert isinstance(cited_text, str), (
        "anthropic citations must have a string cited_text"
    )

    match input:
        case UrlCitation(title=title, url=url, internal=internal):
            assert internal, "UrlCitation must have internal field"
            encrypted_index = internal.get("encrypted_index", None)
            assert isinstance(encrypted_index, str), (
                "URL citations require encrypted_index in internal field"
            )

            return CitationWebSearchResultLocationParam(
                type="web_search_result_location",
                cited_text=cited_text,
                title=title,
                url=url,
                encrypted_index=encrypted_index,
            )

        case DocumentCharCitation(
            title=title, char_range=char_range, internal=internal
        ):
            assert internal, "DocumentCharCitation must have internal field"
            document_index = internal.get("document_index", None)
            assert isinstance(document_index, int), (
                "DocumentCharCitation require encrypted_index in internal field"
            )

            start_char_index, end_char_index = char_range
            return CitationCharLocationParam(
                type="char_location",
                cited_text=cited_text,
                document_title=title,
                document_index=document_index,
                start_char_index=start_char_index,
                end_char_index=end_char_index,
            )

        case DocumentPageCitation(
            title=title, page_range=page_range, internal=internal
        ):
            assert internal, "DocumentPageCitation must have internal field"
            document_index = internal.get("document_index", None)
            assert isinstance(document_index, int), (
                "DocumentPageCitation require encrypted_index in internal field"
            )

            # Convert from 0-indexed to 1-indexed page numbers
            start_page, end_page = page_range or (0, 0)
            return CitationPageLocationParam(
                type="page_location",
                cited_text=cited_text,
                document_title=title,
                document_index=document_index,
                start_page_number=start_page + 1,
                end_page_number=end_page + 1,
            )

        case DocumentBlockCitation(
            title=title, block_range=block_range, internal=internal
        ):
            assert internal, "DocumentPageCitation must have internal field"
            document_index = internal.get("document_index", None)
            assert isinstance(document_index, int), (
                "DocumentPageCitation require encrypted_index in internal field"
            )

            start_block, end_block = block_range or (0, 0)
            return CitationContentBlockLocationParam(
                type="content_block_location",
                cited_text=cited_text,
                document_title=title,
                document_index=document_index,
                start_block_index=start_block,
                end_block_index=end_block,
            )

    # If we can't handle this citation type, raise an error
    raise ValueError(f"Unsupported citation type: {input.type}")
