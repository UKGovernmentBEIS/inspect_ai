import os
from typing import Literal

import anyio

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import exists, filesystem
from inspect_ai.log import resolve_sample_attachments
from inspect_ai.log._file import (
    log_files_from_ls,
    read_eval_log,
    read_eval_log_async,
    write_eval_log,
)
from inspect_ai.log._recorders import create_recorder_for_location
from inspect_ai.log._recorders.create import recorder_type_for_location


def convert_eval_logs(
    path: str,
    to: Literal["eval", "json"],
    output_dir: str,
    overwrite: bool = False,
    resolve_attachments: bool | Literal["full", "core"] = False,
    stream: int | bool = False,
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
        resolve_attachments (bool): Resolve attachments (duplicated content blocks)
            to their full content.
        stream (int | bool): Stream samples through the conversion process instead of
            reading the entire log into memory. Useful for large logs.
    """
    from inspect_ai._display import display

    # confirm that path exists
    fs = filesystem(path)
    if not fs.exists(path):
        raise PrerequisiteError(f"Error: path '{path}' does not exist.")

    # normalise output dir and ensure it exists
    output_fs = filesystem(output_dir)
    if output_dir.endswith(fs.sep):
        output_dir = output_dir[:-1]
    output_fs.mkdir(output_dir, exist_ok=True)

    # convert a single file (input file is relative to the 'path')
    def convert_file(input_file: str) -> None:
        # compute input and ensure output dir exists
        input_name, _ = os.path.splitext(input_file)
        input_dir = os.path.dirname(input_name.replace("\\", "/"))

        # Compute paths, handling directories being converted
        # and files being converted specially
        path_is_dir = fs.info(path).type == "directory"
        if path_is_dir:
            target_dir = f"{output_dir}{output_fs.sep}{input_dir}"
            input_file = f"{path}{fs.sep}{input_file}"
            output_file_basename = input_name
        else:
            target_dir = output_dir
            output_file_basename = os.path.basename(input_name)

        output_fs.mkdir(target_dir, exist_ok=True)

        # compute full output file and enforce overwrite
        output_file = f"{output_dir}{output_fs.sep}{output_file_basename}.{to}"
        if exists(output_file) and not overwrite:
            raise FileExistsError(
                f"Output file {output_file} already exists (use --overwrite to overwrite existing files)"
            )

        # do a full read/write (normalized deprecated constructs and adds sample summaries)
        if stream:
            run_coroutine(
                _stream_convert_file(
                    input_file,
                    output_file,
                    output_dir,
                    resolve_attachments,
                    stream,
                )
            )
        else:
            write_eval_log(
                read_eval_log(input_file, resolve_attachments=resolve_attachments),
                output_file,
            )

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


async def _stream_convert_file(
    input_file: str,
    output_file: str,
    output_dir: str,
    resolve_attachments: bool | Literal["full", "core"],
    stream: int | Literal[True],
) -> None:
    input_recorder = recorder_type_for_location(input_file)
    output_recorder = create_recorder_for_location(output_file, output_dir)

    sample_map = await input_recorder.read_log_sample_ids(input_file)

    concurrent_limit = len(sample_map) if stream is True else stream
    semaphore = anyio.Semaphore(concurrent_limit)
    samples_processed = 0

    async def _convert_sample(sample_id: str | int, epoch: int) -> None:
        async with semaphore:
            sample = await input_recorder.read_log_sample(input_file, sample_id, epoch)
            if resolve_attachments:
                sample = resolve_sample_attachments(sample, resolve_attachments)
            await output_recorder.log_sample(
                log_header.eval,
                sample,
            )

            nonlocal samples_processed
            samples_processed += 1
            # Flush periodically to avoid too much buffering
            if samples_processed % concurrent_limit == 0:
                await output_recorder.flush(log_header.eval)

    log_header = await read_eval_log_async(
        input_file, header_only=True, resolve_attachments=resolve_attachments
    )
    await output_recorder.log_init(log_header.eval, location=output_file)
    await output_recorder.log_start(log_header.eval, log_header.plan)

    async with anyio.create_task_group() as tg:
        for sample_id, epoch in sample_map:
            tg.start_soon(_convert_sample, sample_id, epoch)

    await output_recorder.log_finish(
        log_header.eval,
        log_header.status,
        log_header.stats,
        log_header.results,
        log_header.reductions,
        invalidated=log_header.invalidated,
    )
