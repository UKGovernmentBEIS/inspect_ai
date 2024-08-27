import base64
import contextlib
from typing import AsyncGenerator

from inspect_ai._eval.task.task import Task
from inspect_ai._eval.task.util import task_run_dir
from inspect_ai._util.file import file, filesystem
from inspect_ai._util.url import data_uri_to_base64, is_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.util._sandbox.context import (
    cleanup_sandbox_environments_sample,
    init_sandbox_environments_sample,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment


@contextlib.asynccontextmanager
async def sandboxenv_context(
    task_name: str,
    sandbox: tuple[str, str | None] | None,
    cleanup: bool,
    sample: Sample,
) -> AsyncGenerator[None, None]:
    # resolve sandbox
    sandbox = resolve_sandbox(sandbox, sample)
    if not sandbox:
        raise ValueError("sandboxenv_context called with no sandbox specified")

    # read files from sample
    files: dict[str, bytes] = {}
    if sample.files:
        for path, contents in sample.files.items():
            files[path] = read_sandboxenv_file(contents)

    # read setup script from sample (add bash shebang if necessary)
    setup: bytes | None = None
    if sample.setup:
        setup = read_sandboxenv_file(sample.setup)
        setup_str = setup.decode(encoding="utf-8")
        if not setup_str.strip().startswith("#!"):
            setup_str = f"#!/usr/bin/env bash\n\n{setup_str}"
            setup = setup_str.encode(encoding="utf-8")

    interrupted = False
    environments: dict[str, SandboxEnvironment] | None = None
    try:
        # initialize sandbox environment,
        environments = await init_sandbox_environments_sample(
            type=sandbox[0],
            task_name=task_name,
            config=sandbox[1],
            files=files,
            setup=setup,
            metadata=sample.metadata if sample.metadata else {},
        )

        # run sample
        yield

    except BaseException as ex:
        interrupted = True
        raise ex

    finally:
        # cleanup sandbox environment
        if environments and cleanup:
            await cleanup_sandbox_environments_sample(
                type=sandbox[0],
                task_name=task_name,
                config=sandbox[1],
                environments=environments,
                interrupted=interrupted,
            )


def read_sandboxenv_file(contents: str) -> bytes:
    if is_data_uri(contents):
        contents_base64 = data_uri_to_base64(contents)
        file_bytes = base64.b64decode(contents_base64)
    else:
        # try to read as a file (if it doesn't exist or has a path not cool w/
        # the fileystem then we fall back to contents)
        try:
            fs = filesystem(contents)
            if fs.exists(contents):
                with file(contents, "rb") as f:
                    file_bytes = f.read()
            else:
                file_bytes = contents.encode("utf-8")
        except Exception:
            file_bytes = contents.encode("utf-8")

    return file_bytes


def resolve_sandbox_for_task(
    task: Task,
    sample: Sample,
) -> tuple[str, str | None, str] | None:
    sandbox = resolve_sandbox(task.sandbox, sample)
    if sandbox is not None:
        return sandbox + (task_run_dir(task),)
    else:
        return None


def resolve_sandbox(
    sandbox: tuple[str, str | None] | None,
    sample: Sample,
) -> tuple[str, str | None] | None:
    # resolve sandbox (task type overrides sample type, but sample config
    # file overrides task config file if they have the same type)
    sample_sandbox = (
        (sample.sandbox, None) if isinstance(sample.sandbox, str) else sample.sandbox
    )
    task_sandbox = sandbox
    if task_sandbox is not None:
        sandbox_type = task_sandbox[0]
        if (
            sample_sandbox
            and sample_sandbox[0] == sandbox_type
            and isinstance(sample_sandbox[1], str)
        ):
            sandbox_config: str | None = sample_sandbox[1]
        else:
            sandbox_config = task_sandbox[1]
        return (sandbox_type, sandbox_config)
    elif sample_sandbox is not None:
        return sample_sandbox
    else:
        return None
