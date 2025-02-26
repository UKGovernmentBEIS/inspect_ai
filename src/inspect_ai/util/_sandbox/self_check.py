from typing import Any, Callable, Coroutine, Generic, Optional, Type, TypeVar
from unittest import mock

import pytest

from inspect_ai.util import (
    OutputLimitExceededError,
    SandboxEnvironment,
    SandboxEnvironmentLimits,
)

# If you're wondering these tests are not using pytest fixtures,
# see the discussion https://github.com/UKGovernmentBEIS/inspect_ai/pull/347
# It's not ideal, so a PR to fix this would be welcome.
#
# If you are struggling to debug a failing one of these, two tips:
# 1. Comment out everything apart from the failing test in the list in the `self_check` function
# 2. Get rid of the try/catch in check_test_fn (the body can just be `await fn(sandbox_env); return True`


async def check_test_fn(
    fn: Callable[[SandboxEnvironment], Coroutine[Any, Any, None]],
    sandbox_env: SandboxEnvironment,
) -> bool | str:
    try:
        await fn(sandbox_env)
        return True
    except AssertionError as e:
        return f"FAILED: [{str(e)}]"
    except Exception as e:
        return f"ERROR: [{repr(e)}]"


async def self_check(sandbox_env: SandboxEnvironment) -> dict[str, bool | str]:
    # Note that these tests reuse the same sandbox environment. This means that
    # if a test fails to clean up after itself, it may affect other tests.

    results = {}

    for fn in [
        test_read_and_write_file_text,
        test_read_and_write_file_binary,
        test_read_and_write_large_file_binary,
        test_write_file_text_utf,
        test_read_and_write_file_including_directory_absolute,
        test_read_and_write_file_including_directory_relative,
        test_read_file_zero_length,
        test_read_file_not_found,
        test_read_file_not_allowed,
        test_read_file_is_directory,
        test_read_file_nonsense_name,
        test_read_file_limit,
        test_write_text_file_zero_length,
        test_write_text_file_space,
        test_write_text_file_is_directory,
        test_write_text_file_without_permissions,
        test_write_text_file_exists,
        test_write_binary_file_zero_length,
        test_write_binary_file_space,
        test_write_binary_file_is_directory,
        test_write_binary_file_without_permissions,
        test_write_binary_file_exists,
        test_exec_output,
        test_exec_stderr,
        test_exec_returncode,
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
        print(f"self_check: running {fn.__name__}")
        results[fn.__name__] = await check_test_fn(fn, sandbox_env)

    return results


async def _cleanup_file(sandbox_env: SandboxEnvironment, filename: str) -> None:
    res = await sandbox_env.exec(["rm", "-f", "--", filename])
    assert res.success


async def test_read_and_write_file_text(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_read_and_write_file_text.file"
    await sandbox_env.write_file(file_name, "great #content\nincluding newlines")
    written_file_string = await sandbox_env.read_file(file_name, text=True)
    assert "great #content\nincluding newlines" == written_file_string, (
        f"unexpected content: [{written_file_string}]"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_file_text_utf(sandbox_env: SandboxEnvironment) -> None:
    utf_content = "✨☽︎✨🌞︎︎✨🚀✨"
    file_name = "test_write_file_text_utf.file"
    await sandbox_env.write_file(file_name, utf_content)
    file_with_utf_content = await sandbox_env.read_file(file_name, text=True)
    assert isinstance(file_with_utf_content, str), (
        f"Expected file content to be a string, got {type(file_with_utf_content)}"
    )
    assert file_with_utf_content == utf_content, (
        f"UTF-8 content should match, got {file_with_utf_content=}; expected {utf_content=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_read_and_write_file_binary(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_read_and_write_file_binary.file"
    await sandbox_env.write_file(
        file_name, b"\xc3\x28"
    )  # invalid UTF-8 from https://stackoverflow.com/a/17199164/116509

    written_file_bytes = await sandbox_env.read_file(file_name, text=False)
    assert b"\xc3\x28" == written_file_bytes, "Binary content should match"
    await _cleanup_file(sandbox_env, file_name)


async def test_read_and_write_large_file_binary(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_read_and_write_large_file_binary.file"
    long_bytes = b"\xc3" * 5_000_000
    await sandbox_env.write_file(file_name, long_bytes)
    written_file_bytes = await sandbox_env.read_file(file_name, text=False)
    assert long_bytes == written_file_bytes, "Large binary content should match"
    await _cleanup_file(sandbox_env, file_name)


async def test_read_and_write_file_including_directory_absolute(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "/tmp/test_rw_including_directory_absolute/test.file"
    await sandbox_env.write_file(file_name, "absolutely enjoying being in a directory")
    written_file_string = await sandbox_env.read_file(file_name, text=True)
    assert "absolutely enjoying being in a directory" == written_file_string, (
        f"Absolute directory content should match, got {written_file_string=}"
    )
    await _cleanup_file(sandbox_env, file_name)
    await sandbox_env.exec(["rmdir", "/tmp/test_rw_including_directory_absolute"])


async def test_read_and_write_file_including_directory_relative(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_rw_including_directory_relative/test.file"
    await sandbox_env.write_file(file_name, "relatively enjoying being in a directory")
    written_file_string = await sandbox_env.read_file(file_name, text=True)
    assert "relatively enjoying being in a directory" == written_file_string, (
        f"Relative directory content should match, got {written_file_string=}"
    )
    await _cleanup_file(sandbox_env, file_name)
    await sandbox_env.exec(["rmdir", "test_rw_including_directory_relative"])


async def test_read_file_zero_length(sandbox_env: SandboxEnvironment) -> None:
    file_name = "zero_length_file.file"
    await sandbox_env.exec(["touch", file_name])
    zero_length = await sandbox_env.read_file(file_name, text=True)
    assert isinstance(zero_length, str), (
        f"Zero-length file should return a string, got {type(zero_length)}"
    )
    assert zero_length == "", (
        f"Zero-length file should be an empty string, got {zero_length=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_read_file_not_found(sandbox_env: SandboxEnvironment) -> None:
    file_name = "nonexistent"
    with Raises(FileNotFoundError) as e_info:
        await sandbox_env.read_file(file_name, text=True)
    assert e_info is not None, "FileNotFoundError should be raised"
    assert file_name in str(e_info.value), (
        f"FileNotFoundError should contain the filename, got {e_info.value=}"
    )


async def test_read_file_not_allowed(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_read_file_not_allowed.file"
    await sandbox_env.write_file(file_name, "inaccessible #content")
    await sandbox_env.exec(["chmod", "-r", file_name])
    with Raises(PermissionError) as e_info:
        await sandbox_env.read_file(file_name, text=True)
    assert e_info is not None, "PermissionError should be raised"
    assert file_name in str(e_info.value), (
        f"PermissionError should contain the filename, got {e_info.value=}"
    )
    await sandbox_env.exec(["chmod", "+r", file_name])
    await _cleanup_file(sandbox_env, file_name)


async def test_read_file_is_directory(sandbox_env: SandboxEnvironment) -> None:
    file_name = "/etc"
    with Raises(IsADirectoryError) as e_info:
        await sandbox_env.read_file(file_name, text=True)
        assert e_info is not None, "IsADirectoryError should be raised"
    assert "directory" in str(e_info.value), (
        f"IsADirectoryError should mention 'directory', got {e_info.value=}"
    )


async def test_read_file_nonsense_name(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "https:/en.wikipedia.org/wiki/Bart%C5%82omiej_Kasprzykowski"
    with Raises(FileNotFoundError) as e_info:
        await sandbox_env.read_file(file_name, text=True)
    assert e_info is not None, "FileNotFoundError should be raised"
    assert "wikipedia" in str(e_info.value), (
        f"FileNotFoundError should contain the filename, got {e_info.value=}"
    )


async def test_read_file_limit(sandbox_env: SandboxEnvironment) -> None:
    file_name = "large.file"
    await sandbox_env.write_file(file_name, "a" * 2048)  # 2 KiB
    # Patch limit down to 1KiB for the test to save us from writing a 100 MiB file.
    with mock.patch.object(SandboxEnvironmentLimits, "MAX_READ_FILE_SIZE", 1024):
        with Raises(OutputLimitExceededError) as e_info:
            await sandbox_env.read_file(file_name, text=True)
    assert e_info is not None, "OutputLimitExceededError should be raised"
    assert "limit of 100 MiB was exceeded" in str(e_info.value), (
        f"OutputLimitExceededError should mention the limit, got {e_info.value=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_text_file_zero_length(sandbox_env: SandboxEnvironment) -> None:
    file_name = "zero_length_file.file"
    await sandbox_env.write_file(file_name, "")
    zero_length = await sandbox_env.read_file(file_name, text=True)
    assert isinstance(zero_length, str), (
        f"Zero-length file should return a string, got {type(zero_length)}"
    )
    assert zero_length == "", (
        f"Zero-length file should be an empty string, got {zero_length=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_text_file_space(sandbox_env: SandboxEnvironment) -> None:
    space = "to the moon"
    file_name = "file with space.file"
    await sandbox_env.write_file(file_name, space)
    file_with_space = await sandbox_env.read_file(file_name, text=True)
    assert isinstance(file_with_space, str), (
        f"File with space should return a string, got {type(file_with_space)}"
    )
    assert file_with_space == space, (
        f"File with space content should match, got {file_with_space=}; expected {space=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_text_file_is_directory(
    sandbox_env: SandboxEnvironment,
) -> None:
    # ensure /tmp/directory exists
    await sandbox_env.write_file(
        "/tmp/inspect_ai_test_write_text_file_is_directory/file", "unused content"
    )
    with Raises(IsADirectoryError) as e_info:
        await sandbox_env.write_file(
            "/tmp/inspect_ai_test_write_text_file_is_directory",
            "content cannot go in a directory, dummy",
        )
    assert e_info is not None, "IsADirectoryError should be raised"
    assert "directory" in str(e_info.value), (
        f"IsADirectoryError should mention 'directory', got {e_info.value=}"
    )
    await sandbox_env.exec(
        ["rm", "-rf", "/tmp/inspect_ai_test_write_text_file_is_directory"]
    )


async def test_write_text_file_without_permissions(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_write_text_file_without_permissions.file"
    await sandbox_env.write_file(file_name, "impervious #content")
    await sandbox_env.exec(["chmod", "-w", file_name])
    with Raises(PermissionError) as e_info:
        await sandbox_env.write_file(file_name, "this won't stick")
    assert e_info is not None, "PermissionError should be raised"
    assert file_name in str(e_info.value), (
        f"PermissionError should contain the filename, got {e_info.value=}"
    )
    await sandbox_env.exec(["chmod", "+w", file_name])
    await _cleanup_file(sandbox_env, file_name)


async def test_write_text_file_exists(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "file_exists.file"
    await sandbox_env.write_file(file_name, "mundane content")
    await sandbox_env.write_file(file_name, "altered content")
    altered_content = await sandbox_env.read_file(file_name, text=True)
    assert altered_content == "altered content", (
        f"Existing file content should be overwritten, got {altered_content=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_binary_file_zero_length(sandbox_env: SandboxEnvironment) -> None:
    file_name = "zero_length_file.file"
    await sandbox_env.write_file(file_name, b"")
    zero_length = await sandbox_env.read_file(file_name, text=False)
    assert isinstance(zero_length, bytes), (
        f"Zero-length file should return bytes, got {type(zero_length)}"
    )
    assert zero_length == b"", (
        f"Zero-length file should be empty bytes, got {zero_length=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_write_binary_file_space(sandbox_env: SandboxEnvironment) -> None:
    binary_content = b"\xc3\x28"
    file_name = "file with space.file"
    await sandbox_env.write_file(file_name, binary_content)
    file_with_space = await sandbox_env.read_file(file_name, text=False)
    assert isinstance(file_with_space, bytes), (
        f"File with space should return bytes, got {type(file_with_space)}"
    )
    assert file_with_space == binary_content, "File with space content should match"
    await _cleanup_file(sandbox_env, file_name)


async def test_write_binary_file_is_directory(
    sandbox_env: SandboxEnvironment,
) -> None:
    # ensure /tmp/directory exists
    await sandbox_env.write_file(
        "/tmp/inspect_ai_test_write_binary_file_is_directory/file", "unused content"
    )
    with Raises(IsADirectoryError) as e_info:
        await sandbox_env.write_file(
            "/tmp/inspect_ai_test_write_binary_file_is_directory",
            b"\xc3\x28",
        )
    assert e_info is not None, "IsADirectoryError should be raised"
    assert "directory" in str(e_info.value), (
        f"IsADirectoryError should mention 'directory', got {e_info.value=}"
    )
    await sandbox_env.exec(
        ["rm", "-rf", "/tmp/inspect_ai_test_write_binary_file_is_directory"]
    )


async def test_write_binary_file_without_permissions(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "test_write_binary_file_without_permissions.file"
    await sandbox_env.write_file(file_name, "impervious #content")
    await sandbox_env.exec(["chmod", "-w", file_name])
    with Raises(PermissionError) as e_info:
        await sandbox_env.write_file(file_name, b"\xc3\x28")
    assert e_info is not None, "PermissionError should be raised"
    assert file_name in str(e_info.value), (
        f"PermissionError should contain the filename, got {e_info.value=}"
    )
    await sandbox_env.exec(["chmod", "+w", file_name])
    await _cleanup_file(sandbox_env, file_name)


async def test_write_binary_file_exists(
    sandbox_env: SandboxEnvironment,
) -> None:
    file_name = "file_exists.file"
    await sandbox_env.write_file(file_name, b"\xc3\x28")
    await sandbox_env.write_file(file_name, b"\xc3\x29")
    altered_content = await sandbox_env.read_file(file_name, text=False)
    assert altered_content == b"\xc3\x29", "Existing file content should be overwritten"
    await _cleanup_file(sandbox_env, file_name)


async def test_exec_output(sandbox_env: SandboxEnvironment) -> None:
    exec_result = await sandbox_env.exec(["sh", "-c", "echo foo; echo bar"])
    expected = "foo\nbar\n"
    # in the assertion message, we show the actual bytes to help debug newline issues
    assert exec_result.stdout == expected, (
        f"Unexpected output:expected {expected.encode('UTF-8')!r}; got {exec_result.stdout.encode('UTF-8')!r}"
    )


async def test_exec_stderr(sandbox_env: SandboxEnvironment) -> None:
    exec_result = await sandbox_env.exec(["sh", "-c", "echo boof; echo baz >&2"])
    assert exec_result.stderr == "baz\n", (
        f"stderr output should match; got {exec_result.stderr=}, expected 'baz\n'"
    )


async def test_exec_returncode(sandbox_env: SandboxEnvironment) -> None:
    exec_result = await sandbox_env.exec(["sh", "-c", "echo foo; exit 70"])
    assert exec_result.returncode == 70, (
        f"Return code should match, got {exec_result.returncode=}, expected 70"
    )


async def test_exec_timeout(sandbox_env: SandboxEnvironment) -> None:
    with Raises(TimeoutError):
        await sandbox_env.exec(["sleep", "4"], timeout=2)


async def test_exec_permission_error(sandbox_env: SandboxEnvironment) -> None:
    with Raises(PermissionError):
        # /etc/password is not an executable file so this should fail
        await sandbox_env.exec(["/etc/passwd"])


async def test_exec_as_user(sandbox_env: SandboxEnvironment) -> None:
    username = "inspect-ai-test-exec-as-user"

    # Neither adduser nor useradd are part of POSIX, so we need some brittle logic here
    adduser_help_exec_result = await sandbox_env.exec(["adduser", "--help"])
    adduser_help_text = (
        adduser_help_exec_result.stdout + adduser_help_exec_result.stderr
    )

    if "BusyBox" in adduser_help_text:
        adduser_command = ["adduser", "-D", username]
    else:
        adduser_command = [
            "adduser",
            "--comment",
            "self_check.py",
            "--disabled-password",
            username,
        ]

    try:
        # Create a new user
        add_user_result = await sandbox_env.exec(
            adduser_command,
            user="root",
            timeout=10,  # in one case adduser decided to ask for input which caused the test to hang indefinitely
        )
        assert add_user_result.success, f"Failed to add user: {add_user_result.stderr}"

        # Test exec as different users
        root_result = await sandbox_env.exec(["whoami"], user="root")
        assert root_result.stdout.strip() == "root", (
            f"Expected 'root', got '{root_result.stdout.strip()}'"
        )
        myuser_result = await sandbox_env.exec(["whoami"], user=username)
        assert myuser_result.stdout.strip() == username, (
            f"Expected '{username}', got '{myuser_result.stdout.strip()}'"
        )
    finally:
        # Clean up
        await sandbox_env.exec(["userdel", "-r", username], user="root")


async def test_exec_as_nonexistent_user(sandbox_env: SandboxEnvironment) -> None:
    nonexistent_username = "nonexistent"
    result = await sandbox_env.exec(["whoami"], user=nonexistent_username)
    assert not result.success, "Command should have failed for nonexistent user"
    assert (
        nonexistent_username in result.stdout or nonexistent_username in result.stderr
    ), (
        f"Error not found in command output: '{result.stdout}' nor stderr '{result.stderr}"
    )


async def test_cwd_unspecified(sandbox_env: SandboxEnvironment) -> None:
    file_name = "test_cwd_unspecified.file"
    await sandbox_env.write_file(file_name, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls", "-1"])).stdout
    assert file_name in current_dir_contents, (
        f"File should be in current directory contents; got {current_dir_contents=}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_cwd_custom(sandbox_env: SandboxEnvironment) -> None:
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd="/usr/bin")).stdout
    assert "env" in current_dir_contents, (
        f"env should be in /usr/bin; got {current_dir_contents=}"
    )


async def test_cwd_relative(sandbox_env: SandboxEnvironment) -> None:
    cwd_subdirectory = "subdir"
    await sandbox_env.exec(["mkdir", cwd_subdirectory])
    file_name = "test_cwd_relative.file"
    file_path = cwd_subdirectory + "/" + file_name
    await sandbox_env.write_file(file_path, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd=cwd_subdirectory)).stdout
    assert file_name in current_dir_contents, (
        f"{file_name} not found in {current_dir_contents}"
    )
    await _cleanup_file(sandbox_env, file_path)


async def test_cwd_absolute(sandbox_env: SandboxEnvironment) -> None:
    cwd_directory = "/tmp/test_cwd_absolute"
    await sandbox_env.exec(["mkdir", cwd_directory])
    file_name = "/tmp/test_cwd_absolute/test_cwd_absolute.file"
    await sandbox_env.write_file(file_name, "ls me plz")
    current_dir_contents = (await sandbox_env.exec(["ls"], cwd=cwd_directory)).stdout
    assert "test_cwd_absolute.file" in current_dir_contents, (
        f"File should be in current directory contents, got {current_dir_contents=}"
    )
    await _cleanup_file(sandbox_env, file_name)
    await sandbox_env.exec(["rmdir", cwd_directory])


async def test_exec_stdout_is_limited(sandbox_env: SandboxEnvironment) -> None:
    output_size = 10 * 1024**2 + 1024  # 10 MiB + 1 KiB
    with pytest.raises(OutputLimitExceededError) as e_info:
        await sandbox_env.exec(["sh", "-c", f"yes | head -c {output_size}"])
    assert e_info is not None, "OutputLimitExceededError should be raised"
    assert "limit of 10 MiB was exceeded" in str(e_info.value), (
        "OutputLimitExceededError should mention the limit; got {e_info.value=}"
    )
    truncated_output = e_info.value.truncated_output
    # `yes` outputs 'y\n' (ASCII) so the size equals the string length.
    # some shells additionally output 'canceled\n' so we add fudge factor for that
    assert truncated_output and (len(truncated_output) - 10 * 1024**2) < 10, (
        f"output not truncated or wrong length; start of truncated output = {'' if not truncated_output else truncated_output[:10]}; len(truncated_output): {'n/a' if not truncated_output else len(truncated_output)}"
    )


async def test_exec_stderr_is_limited(sandbox_env: SandboxEnvironment) -> None:
    output_size = 10 * 1024**2 + 1024  # 10 MiB + 1 KiB
    with pytest.raises(OutputLimitExceededError) as e_info:
        await sandbox_env.exec(["sh", "-c", f"yes | head -c {output_size} 1>&2"])
    assert e_info is not None, "OutputLimitExceededError should be raised"
    assert "limit of 10 MiB was exceeded" in str(e_info.value), (
        "OutputLimitExceededError should mention the limit; got {e_info.value=}"
    )
    truncated_output = e_info.value.truncated_output
    assert (
        truncated_output
        and truncated_output[0] == "y"
        and len(truncated_output) <= 10 * 1024**2
        and len(truncated_output) > 0
    ), (
        f"output not truncated or wrong length; start of truncated output = {'' if not truncated_output else truncated_output[:10]}; len(truncated_output): {'n/a' if not truncated_output else len(truncated_output)}"
    )


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
