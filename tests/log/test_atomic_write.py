"""Tests for atomic write utilities."""

import os
from pathlib import Path
from unittest import mock

import pytest

from inspect_ai._util.atomic_write import atomic_write, atomic_write_bytes


class TestAtomicWriteBasics:
    """Test basic atomic write functionality."""

    def test_atomic_write_success(self, tmp_path: Path) -> None:
        """Test successful atomic write creates file with correct content."""
        target = tmp_path / "test.dat"
        data = b"Hello, World!"

        with atomic_write(str(target)) as f:
            f.write(data)

        assert target.exists()
        assert target.read_bytes() == data

    def test_atomic_write_bytes_convenience(self, tmp_path: Path) -> None:
        """Test atomic_write_bytes convenience function."""
        target = tmp_path / "test.dat"
        data = b"Test data"

        atomic_write_bytes(str(target), data)

        assert target.read_bytes() == data

    def test_atomic_write_replaces_existing(self, tmp_path: Path) -> None:
        """Test atomic write replaces existing file."""
        target = tmp_path / "test.dat"
        target.write_bytes(b"Old data")

        new_data = b"New data"
        with atomic_write(str(target)) as f:
            f.write(new_data)

        assert target.read_bytes() == new_data

    def test_atomic_write_empty_file(self, tmp_path: Path) -> None:
        """Test atomic write with no data creates empty file."""
        target = tmp_path / "empty.dat"

        with atomic_write(str(target)) as f:
            pass  # Don't write anything

        assert target.exists()
        assert target.stat().st_size == 0


class TestAtomicWriteFailureHandling:
    """Test atomic write failure scenarios and cleanup."""

    def test_temp_file_cleaned_up_on_success(self, tmp_path: Path) -> None:
        """Test temp files are removed after successful write."""
        target = tmp_path / "test.dat"

        with atomic_write(str(target)) as f:
            f.write(b"data")

        # No temp files should remain
        temp_files = list(tmp_path.glob(".inspect_tmp_*"))
        assert len(temp_files) == 0

    def test_temp_file_cleaned_up_on_exception(self, tmp_path: Path) -> None:
        """Test temp files are removed when exception raised."""
        target = tmp_path / "test.dat"

        with pytest.raises(ValueError):
            with atomic_write(str(target)) as f:
                f.write(b"partial data")
                raise ValueError("Simulated error")

        # Temp file should be cleaned up
        temp_files = list(tmp_path.glob(".inspect_tmp_*"))
        assert len(temp_files) == 0

        # Target file should not exist (write didn't complete)
        assert not target.exists()

    def test_target_unchanged_on_exception(self, tmp_path: Path) -> None:
        """Test original file unchanged if write fails."""
        target = tmp_path / "test.dat"
        original_data = b"Original data"
        target.write_bytes(original_data)

        with pytest.raises(RuntimeError):
            with atomic_write(str(target)) as f:
                f.write(b"New data")
                raise RuntimeError("Simulated failure")

        # Original file should be unchanged
        assert target.read_bytes() == original_data

    def test_disk_full_simulation(self, tmp_path: Path) -> None:
        """Test behavior when disk fills during write (simulated)."""
        target = tmp_path / "test.dat"

        # Mock os.replace to simulate disk full
        with mock.patch(
            "os.replace", side_effect=OSError(28, "No space left on device")
        ):
            with pytest.raises(OSError) as exc_info:
                with atomic_write(str(target)) as f:
                    f.write(b"data")

            assert "No space left on device" in str(exc_info.value)

        # Target file should not exist
        assert not target.exists()


class TestAtomicWriteDurability:
    """Test fsync and durability guarantees."""

    def test_fsync_called_when_enabled(self, tmp_path: Path) -> None:
        """Test fsync is called when fsync=True."""
        target = tmp_path / "test.dat"

        with mock.patch("os.fsync") as mock_fsync:
            with atomic_write(str(target), fsync=True) as f:
                f.write(b"data")

            # fsync should have been called
            assert mock_fsync.called

    def test_fsync_not_called_when_disabled(self, tmp_path: Path) -> None:
        """Test fsync is not called when fsync=False."""
        target = tmp_path / "test.dat"

        with mock.patch("os.fsync") as mock_fsync:
            with atomic_write(str(target), fsync=False) as f:
                f.write(b"data")

            # fsync should NOT have been called
            assert not mock_fsync.called


class TestAtomicWriteEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_large_file(self, tmp_path: Path) -> None:
        """Test atomic write with moderately large file."""
        target = tmp_path / "large.dat"
        size = 10 * 1024 * 1024  # 10 MB

        # Write in chunks to avoid memory issues
        with atomic_write(str(target)) as f:
            chunk = b"x" * (1024 * 1024)  # 1 MB chunk
            for _ in range(10):
                f.write(chunk)

        assert target.stat().st_size == size

    def test_unicode_filename(self, tmp_path: Path) -> None:
        """Test atomic write with unicode filename."""
        target = tmp_path / "test_文件_data.dat"

        with atomic_write(str(target)) as f:
            f.write(b"data")

        assert target.exists()

    def test_relative_path(self, tmp_path: Path) -> None:
        """Test atomic write with relative path."""
        # Change to tmp_path
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            target = "test.dat"
            with atomic_write(target) as f:
                f.write(b"data")

            assert Path(target).exists()
        finally:
            os.chdir(original_cwd)


class TestAtomicWriteInvalidInputs:
    """Test error handling for invalid inputs."""

    def test_invalid_mode(self, tmp_path: Path) -> None:
        """Test error raised for non-wb mode."""
        target = tmp_path / "test.dat"

        with pytest.raises(ValueError, match="only supports binary write mode"):
            with atomic_write(str(target), mode="rb"):
                pass

    def test_nonexistent_parent_directory(self, tmp_path: Path) -> None:
        """Test error when parent directory doesn't exist."""
        target = tmp_path / "nonexistent" / "test.dat"

        with pytest.raises(FileNotFoundError):
            with atomic_write(str(target)) as f:
                f.write(b"data")


class TestAtomicWriteInterruption:
    """Test interruption handling."""

    def test_exception_during_write(self, tmp_path: Path) -> None:
        """Test exception raised during write to temp file."""
        target = tmp_path / "test.dat"

        with pytest.raises(RuntimeError):
            with atomic_write(str(target)) as f:
                f.write(b"partial")
                raise RuntimeError("Simulated crash")

        # No corruption
        assert not target.exists()
        temp_files = list(tmp_path.glob(".inspect_tmp_*"))
        assert len(temp_files) == 0

    def test_keyboard_interrupt_during_write(self, tmp_path: Path) -> None:
        """Test KeyboardInterrupt during write.

        Note: KeyboardInterrupt is a BaseException, not Exception, so it
        bypasses the normal exception handler. Temp file may remain after
        KeyboardInterrupt, which is acceptable (user interrupted the process).
        """
        target = tmp_path / "test.dat"

        with pytest.raises(KeyboardInterrupt):
            with atomic_write(str(target)) as f:
                f.write(b"partial")
                raise KeyboardInterrupt()

        # Target file should not exist
        assert not target.exists()
