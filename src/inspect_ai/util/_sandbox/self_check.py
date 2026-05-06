import random
import string
from typing import Any, Callable, Coroutine, Generic, Optional, Type, TypeVar
from unittest import mock

import anyio

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
    # Import this here rather than in module header in case of breakages because
    # it's internal
    from _pytest.outcomes import Failed

    try:
        await fn(sandbox_env)
        return True
    except AssertionError as e:
        return f"FAILED: [{str(e)}]"
    except Failed as e:
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
        test_exec_timeout_not_raised_on_fast_signal_death,
        test_exec_timeout_kills_process,
        test_exec_timeout_kills_child_processes,
        test_exec_permission_error,
        test_exec_env_vars,
        test_exec_input_text,
        test_exec_input_shell_special,
        test_exec_input_binary,
        test_exec_input_large,
        test_exec_as_user,
        test_exec_as_nonexistent_user,
        test_cwd_unspecified,
        test_cwd_custom,
        test_cwd_relative,
        test_cwd_absolute,
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


async def test_exec_timeout_not_raised_on_fast_signal_death(
    sandbox_env: SandboxEnvironment,
) -> None:
    # a command that dies from SIGTERM immediately (exit 143) should NOT
    # be misinterpreted as a timeout when the timeout is much longer.
    # this guards against false positives from OOM kills, external
    # signals, etc.
    result = await sandbox_env.exec(["sh", "-c", "kill -TERM $$"], timeout=30)
    assert result.returncode == 143, (
        f"Expected exit 143 from self-SIGTERM, got {result.returncode}"
    )


async def test_exec_timeout_kills_process(sandbox_env: SandboxEnvironment) -> None:
    # use a unique random marker so we can find the process later via ps,
    # avoiding PID reuse issues and conflicts with other test runs
    unique_marker = "timeout_test_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=16)
    )

    # The trailing "; :" prevents the shell from exec-optimizing into
    # `sleep 30` (which would strip the marker from the process cmdline,
    # making ps unable to detect a leaked process).
    with Raises(TimeoutError):
        await sandbox_env.exec(
            ["sh", "-c", f"echo '{unique_marker}' > /dev/null && sleep 30; :"],
            timeout=2,
        )

    # give cleanup a moment to complete
    await anyio.sleep(5)

    # the process containing our unique marker must not still be running.
    # use ps + grep so we don't depend on pgrep being installed; the
    # `grep -v grep` filter excludes the grep process itself.
    result = await sandbox_env.exec(
        ["sh", "-c", f"ps aux | grep '{unique_marker}' | grep -v grep"]
    )
    assert not result.success or result.stdout.strip() == "", (
        f"Process with marker '{unique_marker}' should have been killed after timeout, "
        f"but it's still running. ps output: [{result.stdout}]"
    )


async def test_exec_timeout_kills_child_processes(
    sandbox_env: SandboxEnvironment,
) -> None:
    # spawn a backgrounded child sleep with its own marker, then wait on
    # a parent sleep with a different marker. when the timeout fires, BOTH
    # processes must be killed (not just the parent).
    parent_marker = "timeout_parent_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=16)
    )
    child_marker = "timeout_child_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=16)
    )

    with Raises(TimeoutError):
        await sandbox_env.exec(
            [
                "sh",
                "-c",
                f"sleep 30 # {child_marker} & sleep 30 # {parent_marker}",
            ],
            timeout=2,
        )

    await anyio.sleep(5)

    for marker in (parent_marker, child_marker):
        result = await sandbox_env.exec(
            ["sh", "-c", f"ps aux | grep '{marker}' | grep -v grep"]
        )
        assert not result.success or result.stdout.strip() == "", (
            f"Process with marker '{marker}' should have been killed after timeout, "
            f"but it's still running. ps output: [{result.stdout}]"
        )


async def test_exec_permission_error(sandbox_env: SandboxEnvironment) -> None:
    with Raises(PermissionError):
        # /etc/password is not an executable file so this should fail
        await sandbox_env.exec(["/etc/passwd"])


async def test_exec_env_vars(sandbox_env: SandboxEnvironment) -> None:
    exec_result = await sandbox_env.exec(
        cmd=["sh", "-c", "echo $CUSTOM_ENV_VAR_1; echo $CUSTOM_ENV_VAR_2"],
        env={
            "CUSTOM_ENV_VAR_1": "chonko zamboodle",
            "CUSTOM_ENV_VAR_2": "zeddle_zom",
        },
    )
    assert exec_result.stdout == "chonko zamboodle\nzeddle_zom\n", (
        f"env var not passed to script; got {exec_result.stdout=}"
    )


async def test_exec_input_text(sandbox_env: SandboxEnvironment) -> None:
    # Catches implementations that silently drop the input parameter.
    content = "hello\nworld\n"
    result = await sandbox_env.exec(["cat"], input=content)
    assert result.success, f"cat failed: stderr=[{result.stderr}]"
    assert result.stdout == content, (
        f"stdin not forwarded; got {result.stdout=!r}, expected {content=!r}"
    )

    # Empty-string input is non-None and must still be handled
    # (catches `if input:` truthiness bugs).
    empty_result = await sandbox_env.exec(["cat"], input="")
    assert empty_result.success, (
        f"cat failed on empty input: stderr=[{empty_result.stderr}]"
    )
    assert empty_result.stdout == "", (
        f"empty input should produce empty stdout, got {empty_result.stdout=!r}"
    )


async def test_exec_input_shell_special(sandbox_env: SandboxEnvironment) -> None:
    # Catches implementations that embed input into a shell command without
    # proper escaping: variable expansion, command substitution, quoting,
    # backslashes, newlines must all round-trip verbatim.
    content = "$HOME `whoami` 'single' \"double\" \\backslash\nnewline\n"
    result = await sandbox_env.exec(["cat"], input=content)
    assert result.success, f"cat failed: stderr=[{result.stderr}]"
    assert result.stdout == content, (
        f"stdin should round-trip verbatim; got {result.stdout=!r}, expected {content=!r}"
    )


async def test_exec_input_binary(sandbox_env: SandboxEnvironment) -> None:
    # Bytes (including invalid UTF-8 and NULs) must round-trip unchanged.
    # Use a file as the sink because ExecResult.stdout is decoded as str.
    file_name = "test_exec_input_binary.file"
    payload = b"\xc3\x28\x00\xff\x01\x02bytes"
    result = await sandbox_env.exec(["sh", "-c", f"cat > {file_name}"], input=payload)
    assert result.success, f"cat failed: stderr=[{result.stderr}]"
    written = await sandbox_env.read_file(file_name, text=False)
    assert written == payload, (
        f"binary stdin should round-trip; got {written!r}, expected {payload!r}"
    )
    await _cleanup_file(sandbox_env, file_name)


async def test_exec_input_large(sandbox_env: SandboxEnvironment) -> None:
    # Catches command-line / pipe / transport size limits. 1 MiB is enough to
    # exceed several common limits but small enough to stay quick.
    size = 1024 * 1024
    payload = "a" * size
    result = await sandbox_env.exec(["wc", "-c"], input=payload)
    assert result.success, f"wc failed: stderr=[{result.stderr}]"
    reported = int(result.stdout.strip().split()[0])
    assert reported == size, (
        f"wc -c reported {reported} bytes from stdin, expected {size}"
    )


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
