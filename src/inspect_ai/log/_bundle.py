import logging
import math
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import filesystem

from ._file import log_files_from_ls, write_log_dir_manifest

# INSPECT_VIEW_BUNDLE_OUT_DIR

logger = logging.getLogger(__name__)


DIST_DIR = os.path.join(Path(__file__).parent, "..", "_view", "www", "dist")


def bundle_log_dir(
    log_dir: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
    fs_options: dict[str, Any] = {},
) -> None:
    r"""Bundle a log_dir into a statically deployable viewer

    Args:
        log_dir: (str | None): The log_dir to bundle
        output_dir: (str | None): The directory to place bundled output. If no directory
            is specified, the env variable `INSPECT_VIEW_BUNDLE_OUTPUT_DIR` will be used.
        overwrite: (bool): Optional. Whether to overwrite files in the output directory.
            Defaults to False.
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through
            to the filesystem provider (e.g. `S3FileSystem`).
    """
    # resolve the log directory
    log_dir = log_dir if log_dir else os.getenv("INSPECT_LOG_DIR", "./logs")

    # resolve the output directory
    output_dir = (
        output_dir if output_dir else os.getenv("INSPECT_VIEW_BUNDLE_OUTPUT_DIR", "")
    )
    if output_dir == "":
        raise PrerequisiteError("You must provide an 'output_dir'")

    # ensure output_dir doesn't exist
    if filesystem(output_dir, fs_options).exists(output_dir) and not overwrite:
        raise PrerequisiteError(
            f"The output directory '{output_dir}' already exists. Choose another output directory or use 'overwrite' to overwrite the directory and contents"
        )

    from inspect_ai._display import display

    display().print(f"Creating view bundle in '{output_dir}'")
    with display().progress(total=500) as p:
        # Work in a temporary working directory
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as working_dir:
            # copy dist to output_dir
            copy_dir_contents(DIST_DIR, working_dir)
            p.update(25)

            # create a logs dir
            log_dir_name = "logs"
            view_logs_dir = os.path.join(working_dir, log_dir_name)
            os.makedirs(view_logs_dir)
            p.update(25)

            # Copy the logs to the log dir
            copy_log_files(log_dir, view_logs_dir, p.update, fs_options)

            # Always regenerate the manifest
            write_log_dir_manifest(view_logs_dir)
            p.update(25)

            # update the index html to embed the log_dir
            inject_configuration(
                os.path.join(working_dir, "index.html"), log_dir=log_dir_name
            )
            write_robots_txt(working_dir)
            p.update(25)

            # Now move the contents of the working directory to the output directory
            move_output(working_dir, output_dir, p.update, fs_options)
            p.complete()
    display().print(f"View bundle '{output_dir}' created")


def copy_dir_contents(source_dir: str, dest_dir: str) -> None:
    for root, _dirs, files in os.walk(source_dir):
        # Calculate the relative path from the source directory
        relative_path = os.path.relpath(root, source_dir)

        # Create the corresponding directory in the destination
        dest_path = os.path.join(dest_dir, relative_path)
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)

        # Copy all files in the current directory
        for file in files:
            src_file_path = os.path.join(root, file)
            dest_file_path = os.path.join(dest_path, file)
            shutil.copy2(src_file_path, dest_file_path)


def inject_configuration(html_file: str, log_dir: str) -> None:
    # update the index html to embed the log_dir
    with open(html_file, "r") as file:
        index_contents = file.read()

    # inject the log dir information into the viewer html
    # so it will load directly
    content = index_contents.replace(
        "</head>",
        f'  <script id="log_dir_context" type="application/json">{{"log_dir": "{log_dir}"}}</script>\n  </head>',
    )

    # Open the file for writing to save the updated content
    with open(html_file, "w") as file:
        file.write(content)


def write_robots_txt(dir: str) -> None:
    # Full path to the robots.txt file
    file_path = os.path.join(dir, "robots.txt")

    # Content for the robots.txt file
    content = """User-agent: *
Disallow: /
"""

    # Write the content to the file
    with open(file_path, "w") as f:
        f.write(content)


def copy_log_files(
    log_dir: str,
    target_dir: str,
    p: Callable[[int], None],
    fs_options: dict[str, Any] = {},
) -> None:
    log_fs = filesystem(log_dir, fs_options)
    if log_fs.exists(log_dir):
        eval_logs = log_files_from_ls(
            log_fs.ls(log_dir, recursive=True), ["json", "eval"], True
        )
        if len(eval_logs) == 0:
            raise PrerequisiteError(
                f"The log directory {log_dir} doesn't contain any log files."
            )

        base_log_dir = log_fs.info(log_dir).name
        with progress_adapter(p, 200, len(eval_logs)) as tick:
            for eval_log in eval_logs:
                relative_path = os.path.relpath(eval_log.name, base_log_dir)
                output_path = os.path.join(target_dir, relative_path)

                # Make directories containing output_path if they don't exist.
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                # Copy log to output_path
                log_fs.get_file(eval_log.name, output_path)
                tick()

    else:
        raise PrerequisiteError(f"The log directory {log_dir} doesn't exist.")


def move_output(
    from_dir: str,
    to_dir: str,
    p: Callable[[int], None],
    fs_options: dict[str, Any] = {},
) -> None:
    output_fs = filesystem(to_dir, fs_options)

    # remove any existing target directory
    if output_fs.exists(to_dir):
        output_fs.rm(to_dir, recursive=True)

    # Now copy the files
    dir_contents = list(os.walk(from_dir))

    # count the title files to copy
    total_count = 0
    for root, dirs, files in dir_contents:
        total_count += len(dirs) + len(files)

    with progress_adapter(p, 200, total_count) as tick:
        for root, _dirs, files in dir_contents:
            # The relative path of the file to move
            relative_dir = os.path.relpath(root, from_dir)

            # make sure the directory exists
            dir_path = os.path.join(to_dir, relative_dir)
            if not output_fs.exists(dir_path):
                output_fs.mkdir(dir_path)
            tick()

            # Copy the files
            for working_file in files:
                target_path = (
                    os.path.join(relative_dir, working_file)
                    if relative_dir != "."
                    else working_file
                )

                src = os.path.join(root, working_file)
                dest = os.path.join(to_dir, target_path)
                output_fs.put_file(src, dest)
                tick()


@contextmanager
def progress_adapter(
    p: Callable[[int], None], units: int, total_ticks: int
) -> Iterator[Callable[[], None]]:
    # Allocate 'units' ticks to represent the progress in
    # in 'total_ticks', adjusting the size of the increments based
    # upon the total ticks
    ticks = 0.0
    increment = units / total_ticks

    def tick() -> None:
        nonlocal ticks
        ticks = ticks + increment
        tick_value = math.floor(ticks)
        if tick_value >= 1:
            # increment the count
            p(tick_value)

            # hang on to 'leftover' ticks to accumulate with the next increment
            ticks = ticks - tick_value

    yield tick
