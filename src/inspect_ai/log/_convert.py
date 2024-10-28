import os
from typing import Literal

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import copy_file, exists, filesystem
from inspect_ai.log._file import (
    log_files_from_ls,
    read_eval_log,
    write_eval_log,
)


def convert_eval_logs(
    path: str, to: Literal["eval", "json"], output_dir: str, overwrite: bool = False
) -> None:
    """Convert between log file formats.

    Convert log file(s) to a target format. If a file is already in the target
    format it will just be copied to the output dir.

    Args:
        path (str): Path to source log file(s). Should be either a single
          log file or a directory containing log files.
        to (Literal["eval", "json"]): Format to convert to. If a file is
          already in the target format it will just be copied to the output dir.
        output_dir (str): Output directory to write converted log file(s) to.
        overwrite (bool): Overwrite existing log files (defaults to `False`,
          raising an error if the output file path already exists).
    """
    from inspect_ai._display import display

    # confirm that path exists
    fs = filesystem(path)
    if not fs.exists(path):
        raise PrerequisiteError(f"Error: path '{path}' does not exist.")

    # normalise output dir and ensure it exists
    if output_dir.endswith(fs.sep):
        output_dir = output_dir[:-1]
    fs.mkdir(output_dir, exist_ok=True)

    # convert a single file (input file is relative to the 'path')
    def convert_file(input_file: str) -> None:
        # compute input and ensure output dir exists
        input_name, _ = os.path.splitext(input_file)
        input_dir = os.path.dirname(input_name.replace("\\", "/"))
        target_dir = f"{output_dir}{fs.sep}{input_dir}"
        output_fs = filesystem(target_dir)
        output_fs.mkdir(target_dir, exist_ok=True)

        # compute file input file based on path
        if fs.info(path).type == "directory":
            input_file = f"{path}{fs.sep}{input_file}"

        # compute full output file and enforce overwrite
        output_file = f"{output_dir}{fs.sep}{input_name}.{to}"
        if exists(output_file) and not overwrite:
            raise FileExistsError(
                "Output file {output_file} already exists (use --overwrite to overwrite existing files)"
            )

        # if the input and output files have the same format just copy
        if input_file.endswith(f".{to}"):
            copy_file(input_file, output_file)

        # otherwise do a full read/write
        else:
            log = read_eval_log(input_file)
            write_eval_log(log, output_file)

    if fs.info(path).type == "file":
        convert_file(path)
    else:
        root_dir = fs.info(path).name
        eval_logs = log_files_from_ls(fs.ls(path, recursive=True), None, True)
        input_files = [
            eval_log.name.replace(f"{root_dir}/", "", 1) for eval_log in eval_logs
        ]
        display().print("Converting log files...")
        with display().progress(total=len(input_files)) as p:
            for input_file in input_files:
                convert_file(input_file)
                p.update()
