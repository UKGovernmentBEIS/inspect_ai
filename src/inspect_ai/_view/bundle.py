import logging
import math
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from inspect_ai._display import display
from inspect_ai._display._display import Progress
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import filesystem
from inspect_ai.log._file import (
    log_files_from_ls,
    write_log_dir_manifest,
)

# move to log
# INSPECT_VIEW_BUNDLE_OUT_DIR
# fully replace output directory
# add norobots file


logger = logging.getLogger(__name__)


WWW_DIR = os.path.abspath((Path(__file__).parent / "www" / "dist").as_posix())


# TODO: Test S3
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
            is specified, the env variable `INSPECT_BUNDLE_DIR` will be used. If that is
            not specified, a directory named `bundle` will be used as the output directory.
        overwrite: (bool ): Optional. Whether to overwrite files in the output directory.
            Defaults to False.
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through
            to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
            if you are accessing a public S3 bucket with no credentials.
    """
    # resolve the log directory
    log_dir = log_dir if log_dir else os.getenv("INSPECT_LOG_DIR", "./logs")

    # resolve the output directory
    output_dir = (
        output_dir if output_dir else os.getenv("INSPECT_BUNDLE_DIR", "./bundle")
    )

    # ensure output_dir doesn't exist
    if filesystem(output_dir, fs_options).exists(output_dir) and not overwrite:
        raise PrerequisiteError(
            f"The output directory {output_dir} already exists. Choose another output directory or use `overwrite` to overwrite the directory and contents"
        )

    display().print(f"Bundling log directory: {log_dir}")
    with display().progress(total=100) as p:
        # Work in a temporary working directory
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as working_dir:
            # copy dist to output_dir
            display().print("\u2022 Adding viewer")
            copy_dir_contents(WWW_DIR, working_dir)
            p.update(5)

            # create a logs dir
            display().print("\u2022 Copying logs")
            log_dir_name = "logs"
            view_logs_dir = os.path.join(working_dir, log_dir_name)
            os.makedirs(view_logs_dir)
            p.update(5)

            # Copy the logs to the log dir
            copy_log_files(log_dir, view_logs_dir, p, fs_options)

            # Always regenerate the manifest
            display().print("\u2022 Updating manifest")
            write_log_dir_manifest(view_logs_dir)
            p.update(5)

            # update the index html to embed the log_dir
            inject_configuration(
                os.path.join(working_dir, "index.html"), log_dir=log_dir_name
            )
            p.update(5)

            # Now move the contents of the working directory to the output directory
            display().print("\u2022 Copying to output directory")
            move_output(working_dir, output_dir, p, fs_options)
            p.complete()
    display().print(f"Bundle Directory: {output_dir}")


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


def copy_log_files(
    log_dir: str, target_dir: str, p: Progress, fs_options: dict[str, Any] = {}
) -> None:
    log_fs = filesystem(log_dir, fs_options)
    if log_fs.exists(log_dir):
        eval_logs = log_files_from_ls(
            log_fs.ls(log_dir, recursive=True), [".json"], True
        )

        base_log_dir = log_fs.info(log_dir).name
        with progress_adapter(p, 40, len(eval_logs)) as tick:
            for eval_log in eval_logs:
                relative_path = os.path.relpath(eval_log.name, base_log_dir)
                log_fs.get_file(eval_log.name, os.path.join(target_dir, relative_path))
                tick()

    else:
        raise PrerequisiteError(f"The log directory {log_dir} doesn't exist.")


def move_output(
    from_dir: str, to_dir: str, p: Progress, fs_options: dict[str, Any] = {}
) -> None:
    output_fs = filesystem(to_dir, fs_options)
    for root, _dirs, files in os.walk(from_dir):
        # The relative path of the file to move
        relative_dir = os.path.relpath(root, from_dir)

        # make sure the directory exists
        dir_path = os.path.join(to_dir, relative_dir)
        if not output_fs.exists(dir_path):
            output_fs.mkdir(dir_path)

        # Copy the files
        with progress_adapter(p, 40, len(files)) as tick:
            for working_file in files:
                target_path = os.path.join(relative_dir, working_file)
                src = os.path.join(root, working_file)
                dest = os.path.join(to_dir, target_path)
                output_fs.put_file(src, dest)
                tick()


@contextmanager
def progress_adapter(
    p: Progress, units: int, total_ticks: int
) -> Iterator[Callable[[], None]]:
    # Allocate 'units' ticks to represent the progress in
    # in 'total_ticks', adjusting the size of the increments based
    # upon the total ticks
    ticks = 0.0
    increment = units / total_ticks

    def tick() -> None:
        nonlocal ticks
        ticks = ticks + increment
        p.update(math.floor(ticks))

    yield tick
