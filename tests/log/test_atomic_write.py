"""Tests for atomic write utilities."""

import os
import stat
import sys
from pathlib import Path
from typing import Literal
from unittest import mock

import pytest

from inspect_ai._util.atomic_write import atomic_write, atomic_write_bytes
from inspect_ai.log import EvalLog, read_eval_log, write_eval_log


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

        with atomic_write(str(target)):
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

    def test_creates_missing_parent_directory(self, tmp_path: Path) -> None:
        """Parent directories are auto-created (matches fsspec's local writer)."""
        target = tmp_path / "a" / "b" / "c.dat"

        with atomic_write(str(target)) as f:
            f.write(b"data")

        assert target.read_bytes() == b"data"

    def test_remote_path_rejected(self) -> None:
        """Remote paths must be rejected — use AsyncFilesystem instead."""
        with pytest.raises(ValueError, match="local"):
            with atomic_write("s3://bucket/some/key.bin"):
                pass


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits don't apply on Windows",
)
class TestAtomicWriteFileMode:
    """Test mode preservation (POSIX only).

    On Windows os.chmod only honours the read-only bit, so these
    assertions are skipped there.
    """

    def test_preserves_existing_file_mode(self, tmp_path: Path) -> None:
        """Overwriting an existing file preserves its prior mode."""
        target = tmp_path / "existing.dat"
        target.write_bytes(b"old")
        os.chmod(target, 0o664)

        with atomic_write(str(target)) as f:
            f.write(b"new")

        assert stat.S_IMODE(target.stat().st_mode) == 0o664
        assert target.read_bytes() == b"new"

    def test_new_file_uses_umask_default(self, tmp_path: Path) -> None:
        """New files use 0o666 & ~umask (matches open(..., 'wb'))."""
        target = tmp_path / "new.dat"
        umask = os.umask(0)
        os.umask(umask)
        expected = 0o666 & ~umask

        with atomic_write(str(target)) as f:
            f.write(b"x")

        assert stat.S_IMODE(target.stat().st_mode) == expected


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
        """KeyboardInterrupt propagates AND the temp file is cleaned up.

        The cleanup handler catches BaseException (not just Exception) so a
        Ctrl-C mid-write doesn't leave an orphaned .inspect_tmp_* file beside
        the log — eval runs are interrupted often. The interrupt still
        propagates and the target is left untouched.
        """
        target = tmp_path / "test.dat"

        with pytest.raises(KeyboardInterrupt):
            with atomic_write(str(target)) as f:
                f.write(b"partial")
                raise KeyboardInterrupt()

        assert not target.exists()
        temp_files = list(tmp_path.glob(".inspect_tmp_*"))
        assert len(temp_files) == 0, "Ctrl-C should not leak a temp file"


class TestAtomicWriteSymlinks:
    """Writing through a symlinked target updates the referent."""

    @pytest.mark.skipif(
        not hasattr(os, "symlink") or sys.platform == "win32",
        reason="symlink creation is unreliable/privileged on Windows",
    )
    def test_write_through_symlink_updates_referent(self, tmp_path: Path) -> None:
        # A symlinked log path should behave like open(path, "wb") did:
        # follow the link and update the real file, not replace the link
        # with a regular file.
        real = tmp_path / "real.log"
        real.write_bytes(b"old")
        link = tmp_path / "link.log"
        link.symlink_to(real)

        atomic_write_bytes(str(link), b"new")

        assert link.is_symlink(), "the symlink itself must be preserved"
        assert real.read_bytes() == b"new", "the referent must be updated"
        assert link.read_bytes() == b"new"
        # temp file lands next to the real target and is cleaned up
        assert not list(tmp_path.glob(".inspect_tmp_*"))


class TestRecorderIntegration:
    """Local recorder writes must route through the atomic-write path.

    The recorders branch on ``filesystem(...).is_local()`` to pick atomic
    vs. remote writes; a regression in that branching would pass the
    unit tests above silently. Spying on ``os.replace`` proves the local
    write actually went temp-file-then-rename.
    """

    @pytest.fixture
    def sample_log(self) -> EvalLog:
        log_file = Path(__file__).parent / "test_eval_log" / "log_formats.json"
        return read_eval_log(str(log_file))

    @pytest.mark.parametrize("format", ["eval", "json"])
    def test_local_write_is_atomic(
        self, sample_log: EvalLog, tmp_path: Path, format: Literal["eval", "json"]
    ) -> None:
        target = tmp_path / f"log.{format}"

        with mock.patch("os.replace", wraps=os.replace) as replace_spy:
            write_eval_log(sample_log, str(target), format=format)

        renamed_to = [
            Path(call.args[1]).resolve() for call in replace_spy.call_args_list
        ]
        assert target.resolve() in renamed_to, (
            f"local {format} write did not go through the atomic rename path"
        )

        # content survives the atomic path and no temp files leak
        written = read_eval_log(str(target), format=format)
        assert written.model_dump(exclude={"location"}) == sample_log.model_dump(
            exclude={"location"}
        )
        assert not list(tmp_path.glob(".inspect_tmp_*"))
