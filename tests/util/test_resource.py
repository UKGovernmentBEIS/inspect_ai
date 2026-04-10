import os
import tempfile

import pytest

from inspect_ai.util._resource import resource


class TestResourceAutoMode:
    """Tests for resource() with type='auto' (the default)."""

    def test_plain_text_returned_as_is(self) -> None:
        """Plain text strings should be returned unchanged."""
        text = "You are an expert Python programmer."
        assert resource(text) == text

    def test_plain_text_with_template_placeholders(self) -> None:
        """Strings with {placeholders} should be returned as plain text."""
        text = "Hello {name}, solve this {task} using Python."
        assert resource(text) == text

    def test_long_template_string_with_braces(self) -> None:
        """Long template strings with curly braces should not be treated as files.

        This is the core scenario from issue #3574 — on Windows, a long
        inline prompt containing {placeholder} variables was incorrectly
        routed into file resolution, where fsspec interpreted { and } as
        glob patterns.
        """
        text = (
            "You are an expert Python programmer. You will be given a "
            "function signature and docstring by the user. Write the "
            "body of the function. Use {language} and make sure to handle "
            "edge cases. Return the result as {format}."
        )
        assert resource(text) == text

    def test_empty_string(self) -> None:
        assert resource("") == ""

    def test_multiline_text(self) -> None:
        text = "Line 1\nLine 2\nLine 3"
        assert resource(text) == text

    def test_existing_local_file(self) -> None:
        """An existing local file path should be read and its contents returned."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("file contents here")
            f.flush()
            path = f.name
        try:
            assert resource(path) == "file contents here"
        finally:
            os.unlink(path)

    def test_nonexistent_local_file_returns_string(self) -> None:
        """A path-like string that doesn't exist should be returned as-is."""
        result = resource("/nonexistent/path/to/file.txt")
        assert result == "/nonexistent/path/to/file.txt"

    def test_relative_path_nonexistent(self) -> None:
        """A relative path that doesn't exist should be returned as-is."""
        result = resource("no_such_file.txt")
        assert result == "no_such_file.txt"

    def test_relative_path_existing_file(self) -> None:
        """A relative path to an existing file should read the file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir="."
        ) as f:
            f.write("relative file contents")
            f.flush()
            basename = os.path.basename(f.name)
        try:
            assert resource(basename) == "relative file contents"
        finally:
            os.unlink(basename)

    def test_file_uri_reads_file(self) -> None:
        """file:// URIs should be read as files."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("file uri contents")
            f.flush()
            path = f.name
        try:
            uri = f"file://{path}"
            assert resource(uri) == "file uri contents"
        finally:
            os.unlink(path)

    def test_invalid_scheme_url_returns_string(self) -> None:
        """A URL with an unrecognized scheme that can't be read returns as-is."""
        text = "fakescheme://not/a/real/resource"
        assert resource(text) == text

    def test_windows_drive_letter_not_treated_as_scheme(self) -> None:
        """Windows-style paths like C:\\file should not have 'C' treated as a URL scheme.

        urlparse('C:\\\\file') parses 'C' as the scheme. The fix ensures
        we require '://' in the string to treat it as a schemed URL.
        """
        # This path doesn't exist, so it should be returned as-is
        # regardless of platform.
        path = "C:\\Users\\test\\nonexistent_file.txt"
        assert resource(path) == path

    def test_text_containing_colon_not_treated_as_scheme(self) -> None:
        """Text with a colon (but no ://) should not be treated as a URL."""
        text = "Note: this is important"
        assert resource(text) == text

    def test_text_with_embedded_url(self) -> None:
        """Text that contains a URL but isn't itself a URL should return as-is."""
        text = "Visit https://example.com for more information"
        assert resource(text) == text


class TestResourceFileMode:
    """Tests for resource() with type='file'."""

    def test_file_mode_reads_existing_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("explicit file content")
            f.flush()
            path = f.name
        try:
            assert resource(path, type="file") == "explicit file content"
        finally:
            os.unlink(path)

    def test_file_mode_raises_on_nonexistent(self) -> None:
        """type='file' should raise when the file doesn't exist."""
        with pytest.raises((FileNotFoundError, OSError)):
            resource("/nonexistent/path.txt", type="file")
