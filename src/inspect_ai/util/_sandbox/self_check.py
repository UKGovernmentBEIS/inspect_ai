from typing import Any, Callable, Coroutine, Generic, Optional, Type, TypeVar
from unittest import mock

import pytest

from inspect_ai.util import (
    OutputLimitExceededError,
    SandboxEnvironment,
    SandboxEnvironmentLimits,
)


async def check_test_fn(
    fn: Callable[[SandboxEnvironment], Coroutine[Any, Any, None]],
    sandbox_env: SandboxEnvironment,
) -> bool | str:
    try:
        await fn(sandbox_env)
        return True
    except AssertionError as e:
        return f"FAILED: {str(e)}"
    except Exception as e:
        return f"ERROR: {str(e)}"


async def self_check(sandbox_env: SandboxEnvironment) -> dict[str, bool | str]:
    # Note that these tests reuse the same sandbox environment. This means that
    # if a test fails to clean up after itself, it may affect other tests.

    results = {}

    for fn in [
        test_read_and_write_file_text,
        test_read_and_write_file_binary,
        test_read_and_write_file_including_directory_absolute,
        test_read_and_write_file_including_directory_relative,
        test_read_file_zero_length,
        test_read_file_not_found,
        test_read_file_not_allowed,
        test_read_file_is_directory,
        test_read_file_nonsense_name,
        test_read_file_limit,
        test_write_file_zero_length,
        test_write_file_space,
        test_write_file_is_directory,
        test_write_file_without_permissions,
        test_exec_output,
        test_exec_timeout,
        test_exec_permission_error,
        test_exec_as_user,
        test_exec_as_nonexistent_user,
        test_cwd_unspecified,
        test_cwd_custom,
        test_cwd_relative,
        test_cwd_absolute,
        test_exec_stdout_is_limited,
        test_exec_stderr_is_limited,
    ]:
        results[fn.__name__] = await check_test_fn(fn, sandbox_env)

    return results


async def _cleanup_file(sandbox_env: SandboxEnvironment, filename: str) -> None:
    res = await sandbox_env.exec(["rm", filename])
    assert res.success


async def test_read_and_write_file_text(sandbox_env: SandboxEnvironment) -> None:
    await sandbox_env.write_file(
        "test_read_and_write_file_text.file", "great #content\nincluding newlines"
    )
    written_file_string = await sandbox_env.read_file(
        "test_read_and_write_file_text.file", text=True
    )
    assert (
        "great #content\nincluding newlines" == written_file_string
    ), f"unexpected content: [{written_file_string}]"
    await _cleanup_file(sandbox_env, "test_read_and_write_file_text.file")


async def test_read_and_write_file_binary(sandbox_env: SandboxEnvironment) -> None:
    await sandbox_env.write_file(
        "test_read_and_write_file_binary.file", b"\xc3\x28"
    )  # invalid UTF-8 from https://stackoverflow.com/a/17199164/116509

    written_file_bytes = await sandbox_env.read_file(
        "test_read_and_write_file_binary.file", text=False
    )
    assert b"\xc3\x28" == written_file_bytes
    await _cleanup_file(sandbox_env, "test_read_and_write_file_binary.file")


async def test_read_and_write_file_including_directory_absolute(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "/tmp/test_rw_including_directory_absolute/test.file"
    await sandbox_env.write_file(file_name, "absolutely enjoying being in a directory")
    written_file_string = await sandbox_env.read_file(file_name, text=True)
    assert "absolutely enjoying being in a directory" == written_file_string
    await _cleanup_file(sandbox_env, file_name)


async def test_read_and_write_file_including_directory_relative(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_rw_including_directory_relative/test.file"
    await sandbox_env.write_file(file_name, "relatively enjoying being in a directory")
    written_file_string = await sandbox_env.read_file(file_name, text=True)
    assert "relatively enjoying being in a directory" == written_file_string
    await _cleanup_file(sandbox_env, file_name)


async def test_read_file_zero_length(sandbox_env: SandboxEnvironment) -> None:
    await sandbox_env.exec(["touch", "zero_length_file.file"])
    zero_length = await sandbox_env.read_file("zero_length_file.file", text=True)
    assert isinstance(zero_length, str)
    assert zero_length == ""


async def test_read_file_not_found(sandbox_env: SandboxEnvironment) -> None:
    file = "nonexistent"
    with Raises(FileNotFoundError) as e_info:
        await sandbox_env.read_file(file, text=True)
    assert file in str(e_info.value)


async def test_read_file_not_allowed(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_read_file_not_allowed.file"
    await sandbox_env.write_file(file_name, "inaccessible #content")
    await sandbox_env.exec(["chmod", "-r", file_name])
    with Raises(PermissionError) as e_info:
        await sandbox_env.read_file(file_name, text=True)
    assert file_name in str(e_info.value)
    await _cleanup_file(sandbox_env, file_name)


async def test_read_file_is_directory(sandbox_env: SandboxEnvironment) -> None:
    file = "/etc"
    with Raises(IsADirectoryError) as e_info:
        await sandbox_env.read_file(file, text=True)
    assert "directory" in str(e_info.value)


async def test_read_file_nonsense_name(
    sandbox_env: SandboxEnvironment,
) -> None:
    file = "https:/en.wikipedia.org/wiki/Bart%C5%82omiej_Kasprzykowski"
    with Raises(FileNotFoundError) as e_info:
        await sandbox_env.read_file(file, text=True)
    assert "wikipedia" in str(e_info.value)


async def test_read_file_limit(sandbox_env: SandboxEnvironment) -> None:
    file_name = "large.file"
    await sandbox_env.write_file(file_name, "a" * 2048)  # 2 KiB
    # Patch limit down to 1KiB for the test to save us from writing a 100 MiB file.
    with mock.patch.object(SandboxEnvironmentLimits, "MAX_READ_FILE_SIZE", 1024):
        with Raises(OutputLimitExceededError) as e_info:
            await sandbox_env.read_file("large.file", text=True)
        assert "limit of 100 MiB was exceeded" in str(e_info.value)
    await _cleanup_file(sandbox_env, file_name)


async def test_write_file_zero_length(sandbox_env: SandboxEnvironment) -> None:
    await sandbox_env.write_file("zero_length_file.file", "")
    zero_length = await sandbox_env.read_file("zero_length_file.file", text=True)
    assert isinstance(zero_length, str)
    assert zero_length == ""


async def test_write_file_space(sandbox_env: SandboxEnvironment) -> None:
    space = "✨☽︎✨🌞︎︎✨🚀✨"
    await sandbox_env.write_file("file with space.file", space)
    file_with_space = await sandbox_env.read_file("file with space.file", text=True)
    assert isinstance(file_with_space, str)
    assert file_with_space == space


async def test_write_file_is_directory(
    sandbox_env: SandboxEnvironment,
) -> None:
    # ensure /tmp/directory exists
    await sandbox_env.write_file(
        "/tmp/inspect_ai_test_write_file_is_directory/file", "unused content"
    )
    with Raises(IsADirectoryError) as e_info:
        await sandbox_env.write_file(
            "/tmp/inspect_ai_test_write_file_is_directory",
            "content cannot go in a directory, dummy",
        )
    assert "directory" in str(e_info.value)


async def test_write_file_without_permissions(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_write_file_without_permissions.file"
    await sandbox_env.write_file(file_name, "impervious #content")
    await sandbox_env.exec(["chmod", "-w", file_name])
    with Raises(PermissionError) as e_info:
        await sandbox_env.write_file(file_name, "this won't stick")
    assert file_name in str(e_info.value)


async def test_exec_output(sandbox_env: SandboxEnvironment) -> None:
    exec_result = await sandbox_env.exec(["sh", "-c", "echo foo; echo bar"])
    expected = "foo\nbar\n"
    # in the assertion message, we show the actual bytes to help debug newline issues
    assert (
        exec_result.stdout == expected
    ), f"Unexpected output:expected {expected.encode('UTF-8')!r}; got {exec_result.stdout.encode('UTF-8')!r}"


async def test_exec_timeout(sandbox_env: SandboxEnvironment) -> None:
    with Raises(TimeoutError):
        await sandbox_env.exec(["sleep", "2"], timeout=1)


async def test_exec_permission_error(sandbox_env: SandboxEnvironment) -> None:
    with Raises(PermissionError):
        # /etc/password is not an executable file so this should fail
        await sandbox_env.exec(["/etc/passwd"])


async def test_exec_as_user(sandbox_env: SandboxEnvironment) -> None:
    username = "inspect-ai-test-exec-as-user"
    try:
        # Create a new user
        add_user_result = await sandbox_env.exec(
            ["adduser", "--disabled-password", username], user="root"
        )
        assert add_user_result.success, f"Failed to add user: {add_user_result.stderr}"

        # Test exec as different users
        root_result = await sandbox_env.exec(["whoami"], user="root")
        assert (
            root_result.stdout.strip() == "root"
        ), f"Expected 'root', got '{root_result.stdout.strip()}'"
        myuser_result = await sandbox_env.exec(["whoami"], user=username)
        assert (
            myuser_result.stdout.strip() == username
        ), f"Expected '{username}', got '{myuser_result.stdout.strip()}'"
    finally:
        # Clean up
        await sandbox_env.exec(["userdel", "-r", username], user="root")


async def test_exec_as_nonexistent_user(sandbox_env: SandboxEnvironment) -> None:
    result = await sandbox_env.exec(["whoami"], user="nonexistent")
    assert not result.success, "Command should have failed for nonexistent user"
    expected_error = (
        "unable to find user nonexistent: no matching entries in passwd file"
    )
    assert (
        expected_error in result.stdout
    ), f"Error string '{expected_error}' not found in error output: '{result.stdout}'"


async def test_cwd_unspecified(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_cwd_unspecified.file"
    await sandbox_env.write_file(file_name, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls", "-1"])).stdout
    assert file_name in current_dir_contents
    await _cleanup_file(sandbox_env, file_name)


async def test_cwd_custom(sandbox_env: SandboxEnvironment) -> None:
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd="/usr/bin")).stdout
    assert "env" in current_dir_contents


async def test_cwd_relative(sandbox_env: SandboxEnvironment) -> None:
    cwd_subdirectory = "subdir"
    await sandbox_env.exec(["mkdir", cwd_subdirectory])
    file_name = "test_cwd_relative.file"
    file_path = cwd_subdirectory + "/" + file_name
    await sandbox_env.write_file(file_path, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd=cwd_subdirectory)).stdout
    assert (
        file_name in current_dir_contents
    ), f"{file_name} not found in {current_dir_contents}"
    await _cleanup_file(sandbox_env, file_path)


async def test_cwd_absolute(sandbox_env: SandboxEnvironment) -> None:
    cwd_directory = "/tmp/test_cwd_absolute"
    await sandbox_env.exec(["mkdir", cwd_directory])
    file_name = "/tmp/test_cwd_absolute/test_cwd_absolute.file"
    await sandbox_env.write_file(file_name, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd=cwd_directory)).stdout
    assert "test_cwd_absolute.file" in current_dir_contents
    await _cleanup_file(sandbox_env, file_name)


async def test_exec_stdout_is_limited(sandbox_env: SandboxEnvironment) -> None:
    output_size = 1024**2 + 1024  # 1 MiB + 1 KiB
    with pytest.raises(OutputLimitExceededError) as e_info:
        await sandbox_env.exec(["sh", "-c", f"yes | head -c {output_size}"])
    assert "limit of 1 MiB was exceeded" in str(e_info.value)
    truncated_output = e_info.value.truncated_output
    # `yes` outputs 'y\n' (ASCII) so the size equals the string length.
    assert truncated_output and len(truncated_output) == 1024**2


async def test_exec_stderr_is_limited(sandbox_env: SandboxEnvironment) -> None:
    output_size = 1024**2 + 1024  # 1 MiB + 1 KiB
    with pytest.raises(OutputLimitExceededError) as e_info:
        await sandbox_env.exec(["sh", "-c", f"yes | head -c {output_size} 1>&2"])
    assert "limit of 1 MiB was exceeded" in str(e_info.value)
    truncated_output = e_info.value.truncated_output
    assert truncated_output and len(truncated_output) == 1024**2


# TODO: write a test for when cwd doesn't exist

# Generic type variable for exceptions
E = TypeVar("E", bound=BaseException)


class Raises(Generic[E]):
    def __init__(self, expected_exception: Type[E]):
        self.expected_exception = expected_exception
        self.value: Optional[E] = None  # Store the caught exception

    def __enter__(self) -> "Raises[E]":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[Any],
    ) -> bool:
        if exc_type is None:
            raise AssertionError(
                f"Expected exception {self.expected_exception.__name__} but no exception was raised."
            )
        if not issubclass(exc_type, self.expected_exception):
            raise AssertionError(
                f"Expected exception {self.expected_exception.__name__}, but got {exc_type.__name__}."
            )
        self.value = exc_value  # type: ignore
        return True
