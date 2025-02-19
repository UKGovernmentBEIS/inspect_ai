import logging


def setup_logger(level=logging.INFO):
    """
    This logger emits all of its output to PID 1's stdout.

    This makes it so that logging from invocations of the computer_tool cli show up in `docker logs` output.
    """
    new_logger = logging.getLogger("computer_tool")
    new_logger.setLevel(level)

    stdout_handler = logging.FileHandler("/proc/1/fd/1", mode="w")
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(
        logging.Formatter("%(name)s(pid=%(process)d) - %(levelname)s - %(message)s")
    )

    if not new_logger.handlers:
        new_logger.addHandler(stdout_handler)

    return new_logger
