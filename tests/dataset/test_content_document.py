from unittest.mock import patch

import pytest
from pydantic import ValidationError

from inspect_ai._util.content import ContentDocument
from inspect_ai._util.url import data_uri_mime_type


def test_file_path_auto_detection():
    """Test automatic name and mime_type detection from file paths."""
    doc = ContentDocument(document="/path/to/report.pdf")
    assert doc.document == "/path/to/report.pdf"
    assert doc.filename == "report.pdf"
    assert doc.mime_type == "application/pdf"


def test_file_path_with_explicit_name():
    """Test that explicit name is preserved with auto mime_type."""
    doc = ContentDocument(document="/path/to/file.pdf", filename="Q4 Financial Report")
    assert doc.filename == "Q4 Financial Report"
    assert doc.mime_type == "application/pdf"


def test_file_path_with_explicit_mime_type():
    """Test that explicit mime_type is preserved with auto name."""
    doc = ContentDocument(
        document="/path/to/report.pdf", mime_type="application/x-custom-pdf"
    )
    assert doc.filename == "report.pdf"
    assert doc.mime_type == "application/x-custom-pdf"


def test_file_path_all_explicit():
    """Test that all explicit values are preserved."""
    doc = ContentDocument(
        document="/path/to/file.bin",
        filename="Custom Name",
        mime_type="application/custom",
    )
    assert doc.filename == "Custom Name"
    assert doc.mime_type == "application/custom"


def test_unknown_file_extension():
    """Test fallback mime_type for unknown extensions."""
    doc = ContentDocument(document="/path/to/file.xyz")
    assert doc.filename == "file.xyz"
    assert (
        doc.mime_type == "chemical/x-xyz"
    )  # mimetypes.guess_type returns this for .xyz


def test_data_uri_auto_detection():
    """Test automatic detection from data URI."""
    doc = ContentDocument(
        document="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    assert doc.filename == "document.png"
    assert doc.mime_type == "image/png"


def test_data_uri_pdf():
    """Test data URI with PDF mime type."""
    doc = ContentDocument(document="data:application/pdf;base64,JVBERi0xLjQKJcfs...")
    assert doc.filename == "document.pdf"
    assert doc.mime_type == "application/pdf"


def test_data_uri_with_explicit_name():
    """Test data URI with explicit name."""
    doc = ContentDocument(
        document="data:image/jpeg;base64,/9j/4AAQSkZJRg...",
        filename="profile_photo.jpg",
    )
    assert doc.filename == "profile_photo.jpg"
    assert doc.mime_type == "image/jpeg"


def test_data_uri_with_explicit_mime_type():
    """Test data URI with explicit mime_type."""
    doc = ContentDocument(
        document="data:image/png;base64,iVBORw0KGgo...", mime_type="image/x-custom-png"
    )
    assert doc.filename == "document.x-custom-png"
    assert doc.mime_type == "image/x-custom-png"


def test_data_uri_no_mime_type_in_uri():
    """Test data URI without mime type falls back to default."""
    with patch("inspect_ai._util.content.data_uri_mime_type", return_value=None):
        doc = ContentDocument(document="data:,Hello%20World")
        assert doc.filename == "document.octet-stream"
        assert doc.mime_type == "application/octet-stream"


def test_data_uri_complex_mime_type():
    """Test data URI with complex mime type."""
    doc = ContentDocument(
        document="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,UEsDBA..."
    )
    # The extension is extracted from the last part after the last dot
    assert (
        doc.filename
        == "document.vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert (
        doc.mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_missing_document_field():
    """Test that missing document field raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        ContentDocument(filename="test.pdf", mime_type="application/pdf")

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("document",)
    assert errors[0]["type"] == "missing"


def test_type_field_default():
    """Test that type field has correct default value."""
    doc = ContentDocument(document="/path/to/file.pdf")
    assert doc.type == "document"


def test_type_field_cannot_be_changed():
    """Test that type field must be 'document'."""
    with pytest.raises(ValidationError):
        ContentDocument(
            type="image",  # Should only accept "document"
            document="/path/to/file.pdf",
        )


# Test edge cases for file paths
def test_file_path_with_multiple_dots():
    """Test file with multiple dots in name."""
    doc = ContentDocument(document="/path/to/file.name.with.dots.pdf")
    assert doc.filename == "file.name.with.dots.pdf"
    assert doc.mime_type == "application/pdf"


def test_file_path_no_extension():
    """Test file without extension."""
    doc = ContentDocument(document="/path/to/README")
    assert doc.filename == "README"
    assert doc.mime_type == "application/octet-stream"


def test_file_path_hidden_file():
    """Test hidden file (starting with dot)."""
    doc = ContentDocument(document="/path/to/.gitignore")
    assert doc.filename == ".gitignore"
    assert doc.mime_type == "application/octet-stream"


def test_relative_file_path():
    """Test relative file path."""
    doc = ContentDocument(document="./documents/report.docx")
    assert doc.filename == "report.docx"
    assert (
        doc.mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_windows_file_path():
    """Test Windows-style file path."""
    # On Unix systems, Windows paths are treated as a single filename
    doc = ContentDocument(document=r"C:\Users\Documents\report.xlsx")
    # On Unix, the entire path becomes the filename
    assert doc.filename == r"C:\Users\Documents\report.xlsx"
    # mimetypes can still extract .xlsx extension from the string
    assert (
        doc.mime_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# Test common mime types
@pytest.mark.parametrize(
    "extension,expected_mime",
    [
        ("txt", "text/plain"),
        ("html", "text/html"),
        ("css", "text/css"),
        ("json", "application/json"),
        ("xml", "application/xml"),
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("png", "image/png"),
        ("gif", "image/gif"),
        ("svg", "image/svg+xml"),
        ("mp3", "audio/mpeg"),
        ("mp4", "video/mp4"),
        ("zip", "application/zip"),
        ("tar", "application/x-tar"),
        # Note: .gz returns None from mimetypes.guess_type, defaults to octet-stream
        ("gz", "application/octet-stream"),
    ],
)
def test_common_mime_types(extension, expected_mime):
    """Test common file extensions are mapped to correct MIME types."""
    doc = ContentDocument(document=f"/path/to/file.{extension}")
    assert doc.filename == f"file.{extension}"
    assert doc.mime_type == expected_mime


# Test data_uri_mime_type function
def test_data_uri_mime_type_function():
    """Test the data_uri_mime_type helper function."""
    assert data_uri_mime_type("data:image/png;base64,abc") == "image/png"
    assert data_uri_mime_type("data:application/pdf;base64,xyz") == "application/pdf"
    # data_uri_mime_type expects a semicolon after mime type
    assert data_uri_mime_type("data:text/plain,Hello") is None
    assert data_uri_mime_type("data:,Hello") is None
    assert data_uri_mime_type("not-a-data-uri") is None
    assert data_uri_mime_type("") is None


# Integration test with model serialization
def test_model_serialization():
    """Test that the model serializes correctly."""
    doc = ContentDocument(document="/path/to/report.pdf")
    data = doc.model_dump()

    assert data == {
        "internal": None,  # ContentBase includes internal field
        "type": "document",
        "document": "/path/to/report.pdf",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
    }


def test_model_deserialization():
    """Test that the model deserializes correctly."""
    data = {
        "type": "document",
        "document": "/path/to/report.pdf",
        "filename": "Custom Report",
        "mime_type": "application/pdf",
    }
    doc = ContentDocument.model_validate(data)

    assert doc.document == "/path/to/report.pdf"
    assert doc.filename == "Custom Report"
    assert doc.mime_type == "application/pdf"
