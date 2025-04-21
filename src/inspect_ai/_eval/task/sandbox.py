import base64
import contextlib
from random import random
from typing import AsyncGenerator, Callable, NamedTuple, cast

import anyio
import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._eval.task.task import Task
from inspect_ai._eval.task.util import task_run_dir
from inspect_ai._util.file import file, filesystem
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai._util.path import chdir
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.url import data_uri_to_base64, is_data_uri, is_http_url
from inspect_ai.dataset import Sample
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._sandbox.context import (
    cleanup_sandbox_environments_sample,
    init_sandbox_environments_sample,
)
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    TaskInitEnvironment,
)
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv


@contextlib.asynccontextmanager
async def sandboxenv_context(
    task_name: str,
    sandbox: SandboxEnvironmentSpec | None,
    max_sandboxes: int | None,
    cleanup: bool,
    sample: Sample,
) -> AsyncGenerator[None, None]:
    # resolve sandbox
    sandbox = await resolve_sandbox(sandbox, sample)
    if not sandbox:
        raise ValueError("sandboxenv_context called with no sandbox specified")

    # get sandboxenv_type
    sandboxenv_type = registry_find_sandboxenv(sandbox.type)

    # see if there is a max_sandboxes in play (passed or from type)
    if max_sandboxes is None:
        default_concurrency_fn = cast(
            Callable[[], int | None], getattr(sandboxenv_type, "default_concurrency")
        )
        max_sandboxes = default_concurrency_fn()

    # if we are enforcing max_sandboxes, then when samples are scheduled they may
    # not get interleaved properly across tasks (because the first task will come
    # in and grab all of the sandboxes). Therefore, in this case we wait a random
    # delay so that all tasks/samples have an equal shot at getting scheduled.
    if max_sandboxes is not None:
        await anyio.sleep(random())

    # enforce concurrency if required
    sandboxes_cm = (
        concurrency(sandbox.type, max_sandboxes, f"sandboxes/{sandbox.type}")
        if max_sandboxes is not None
        else contextlib.nullcontext()
    )

    async with sandboxes_cm:
        # read files from sample
        files: dict[str, bytes] = {}
        if sample.files:
            for path, contents in sample.files.items():
                files[path] = await read_sandboxenv_file(contents)

        # read setup script from sample (add bash shebang if necessary)
        setup: bytes | None = None
        if sample.setup:
            setup = await read_sandboxenv_file(sample.setup)
            setup_str = setup.decode(encoding="utf-8")
            if not setup_str.strip().startswith("#!"):
                setup_str = f"#!/usr/bin/env bash\n\n{setup_str}"
                setup = setup_str.encode(encoding="utf-8")

        interrupted = False
        environments: dict[str, SandboxEnvironment] | None = None
        try:
            # initialize sandbox environment,
            environments = await init_sandbox_environments_sample(
                sandboxenv_type=sandboxenv_type,
                task_name=registry_unqualified_name(task_name),
                config=sandbox.config,
                files=files,
                setup=setup,
                metadata=sample.metadata if sample.metadata else {},
            )

            # run sample
            yield

        except anyio.get_cancelled_exc_class() as ex:
            interrupted = True
            raise ex

        finally:
            # cleanup sandbox environment
            if environments and cleanup:
                await cleanup_sandbox_environments_sample(
                    type=sandbox.type,
                    task_name=task_name,
                    config=sandbox.config,
                    environments=environments,
                    interrupted=interrupted,
                )


async def read_sandboxenv_file(contents: str) -> bytes:
    if is_data_uri(contents):
        contents_base64 = data_uri_to_base64(contents)
        file_bytes = base64.b64decode(contents_base64)
    elif is_http_url(contents):
        file_bytes = await _retrying_httpx_get(contents)
    else:
        # try to read as a file (if it doesn't exist or has a path not cool w/
        # the filesystem then we fall back to contents)
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


class TaskSandboxEnvironment(NamedTuple):
    sandbox: SandboxEnvironmentSpec
    run_dir: str
    env: tuple[tuple[str, str], ...]


async def resolve_sandbox_for_task_and_sample(
    eval_sandbox: SandboxEnvironmentSpec | None,
    task: Task,
    sample: Sample,
) -> TaskSandboxEnvironment | None:
    # eval_sandbox overrides task or sample sandbox
    sandbox = eval_sandbox or await resolve_sandbox(task.sandbox, sample)
    if sandbox is not None:
        # see if there are environment variables required for init of this sample
        run_dir = task_run_dir(task)
        with chdir(run_dir):
            sandboxenv_type = registry_find_sandboxenv(sandbox.type)
            task_init_environment = cast(
                TaskInitEnvironment, getattr(sandboxenv_type, "task_init_environment")
            )
            env = await task_init_environment(sandbox.config, sample.metadata or {})

        return TaskSandboxEnvironment(
            sandbox=sandbox, run_dir=run_dir, env=tuple(sorted(env.items()))
        )
    else:
        return None


async def resolve_sandbox(
    sandbox: SandboxEnvironmentSpec | None,
    sample: Sample,
) -> SandboxEnvironmentSpec | None:
    # resolve sandbox (task type overrides sample type, but sample config
    # file overrides task config file if they have the same type)
    task_sandbox = sandbox
    if task_sandbox is not None:
        if (
            sample.sandbox
            and sample.sandbox.type == task_sandbox.type
            and sample.sandbox.config is not None
        ):
            sandbox_config: SandboxEnvironmentConfigType | None = sample.sandbox.config
        else:
            sandbox_config = task_sandbox.config
        return SandboxEnvironmentSpec(task_sandbox.type, sandbox_config)
    elif sample.sandbox is not None:
        return sample.sandbox
    else:
        return None


async def _retrying_httpx_get(
    url: str,
    client: httpx.AsyncClient = httpx.AsyncClient(),
    timeout: int = 30,  # per-attempt timeout
    max_retries: int = 10,
    total_timeout: int = 120,  #  timeout for the whole retry loop. not for an individual attempt
) -> bytes:
    @retry(
        wait=wait_exponential_jitter(),
        stop=(stop_after_attempt(max_retries) | stop_after_delay(total_timeout)),
        retry=retry_if_exception(httpx_should_retry),
        before_sleep=log_httpx_retry_attempt(url),
    )
    async def do_get() -> bytes:
        response = await client.get(
            url=url,
            follow_redirects=True,
            timeout=(timeout, timeout, timeout, timeout),
        )
        response.raise_for_status()
        return response.content

    return await do_get()
