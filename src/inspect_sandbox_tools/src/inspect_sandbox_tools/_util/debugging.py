def print_to_proc_1(message: str, to_stderr: bool = True) -> None:
    """
    Writes a message to the file descriptor of process 1, either standard error or standard output.

    This function is useful for debugging in containerized environments where process 1
    (often the init system or container runtime) handles the main output streams.

    Args:
      message (str): The message to write to the file descriptor.
      to_stderr (bool): If True, writes to process 1's standard error (fd 2).
                If False, writes to process 1's standard output (fd 1).
    """
    fd_path = "/proc/1/fd/2" if to_stderr else "/proc/1/fd/1"
    with open(fd_path, "w", encoding="utf-8") as fd:
        fd.write(message + "\n")
