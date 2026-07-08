import base64
import contextlib
import os
from logging import getLogger
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
from inspect_ai._util.file import FileSystem, file, filesystem
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai._util.logger import warn_once
from inspect_ai._util.path import chdir
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.url import data_uri_to_base64, is_data_uri, is_http_url
from inspect_ai.dataset import Sample
from inspect_ai.util._concurrency import (
    concurrency,
    get_or_create_semaphore,
    register_sandbox_limiter,
)
from inspect_ai.util._sandbox.compose import (
    is_docker_compatible_config,
    is_docker_compatible_sandbox_type,
)
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

logger = getLogger(__name__)


async def ensure_sandbox_limiter(
    sandboxenv_type: type[SandboxEnvironment],
    sandbox_type: str,
    max_sandboxes: int | None,
) -> int | None:
    """Resolve a sandbox type's concurrency limit and pre-register its limiter.

    The effective limit is ``max_sandboxes`` (the eval config value) or the
    provider's ``default_concurrency()``; when one is in effect, the
    process-global ``sandboxes/<type>`` semaphore is created (or fetched — the
    registry coalesces on key) and tracked for the control channel. Called
    *eagerly* by the run-level sandbox startup — before ``task_init``'s image
    pulls — so a ``ctl limits --max-sandboxes`` issued during startup lands
    instead of being dropped, and idempotently by the per-sample acquire path
    (covering per-sample sandbox overrides the startup pass can't see).
    Returns the resolved limit, or ``None`` when no limit is in effect.
    """
    if max_sandboxes is None:
        default_concurrency_fn = cast(
            Callable[[], int | None], getattr(sandboxenv_type, "default_concurrency")
        )
        max_sandboxes = default_concurrency_fn()
    if max_sandboxes is not None:
        semaphore = await get_or_create_semaphore(
            sandbox_type,
            max_sandboxes,
            f"sandboxes/{sandbox_type}",
            True,
            resizable=True,
        )
        register_sandbox_limiter(sandbox_type, semaphore)
    return max_sandboxes


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

    # per-sample sandbox overrides aren't visible to the run-level startup
    # pass, so they get their limiter registered here on first use
    max_sandboxes = await ensure_sandbox_limiter(
        sandboxenv_type, sandbox.type, max_sandboxes
    )

    # if we are enforcing max_sandboxes, then when samples are scheduled they may
    # not get interleaved properly across tasks (because the first task will come
    # in and grab all of the sandboxes). Therefore, in this case we wait a random
    # delay so that all tasks/samples have an equal shot at getting scheduled.
    if max_sandboxes is not None:
        await anyio.sleep(random())

    # enforce concurrency if required. `resizable=True` backs it with a
    # ResizableLimiter so the control channel's modify-limits directive can
    # retune max_sandboxes mid-eval (see design/control-channel.md phase 3).
    sandboxes_cm = (
        concurrency(
            sandbox.type,
            max_sandboxes,
            f"sandboxes/{sandbox.type}",
            resizable=True,
        )
        if max_sandboxes is not None
        else contextlib.nullcontext()
    )

    async with sandboxes_cm:
        # read files from sample
        files: dict[str, bytes] = {}
        if sample.files:
            resolved_files = resolve_sample_files(sample.files)
            for path, contents in resolved_files.items():
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
            # initialize sandbox environment
            metadata = dict(sample.metadata) if sample.metadata else {}
            metadata["__sample_id__"] = sample.id

            environments = await init_sandbox_environments_sample(
                sandboxenv_type=sandboxenv_type,
                task_name=registry_unqualified_name(task_name),
                config=sandbox.config,
                files=files,
                setup=setup,
                metadata=metadata,
            )

            # run sample
            yield

        except anyio.get_cancelled_exc_class() as ex:
            interrupted = True
            raise ex

        finally:
            # cleanup sandbox environment
            if environments and cleanup:
                with anyio.CancelScope(shield=interrupted):
                    await cleanup_sandbox_environments_sample(
                        type=sandbox.type,
                        task_name=task_name,
                        config=sandbox.config,
                        environments=environments,
                        interrupted=interrupted,
                    )


def resolve_sample_files(files: dict[str, str]) -> dict[str, str]:
    # if the source path is a directory then add its files recursively
    resolved_files: dict[str, str] = dict()
    for key, contents in files.items():
        fs = filesystem_for_file(contents)
        if (
            fs is not None
            and fs.exists(contents)
            and fs.info(contents).type == "directory"
        ):
            root_uri = fs.path_as_uri(contents)
            for file in fs.ls(contents, recursive=True):
                if file.type == "file":
                    file_uri = fs.path_as_uri(file.name)
                    file_relative = file_uri.removeprefix(root_uri)[1:]
                    resolved_files[os.path.join(key, file_relative)] = file.name
        else:
            resolved_files[key] = contents

    return resolved_files


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


def filesystem_for_file(contents: str) -> FileSystem | None:
    if is_data_uri(contents):
        return None
    elif is_http_url(contents):
        return None
    else:
        try:
            return filesystem(contents)
        except Exception:
            return None


class TaskSandboxEnvironment(NamedTuple):
    sandbox: SandboxEnvironmentSpec
    run_dir: str
    env: tuple[tuple[str, str], ...]


async def resolve_sandbox_for_task_and_sample(
    sandbox: SandboxEnvironmentSpec | None,
    task: Task,
    sample: Sample,
) -> TaskSandboxEnvironment | None:
    # `sandbox` is the task's already-resolved sandbox (i.e. `ResolvedTask.sandbox`),
    # which has had any eval-level override (`--sandbox <provider>`) and implicit
    # config-file resolution applied by resolve_task_sandbox(). We layer the
    # per-sample sandbox on top exactly as the execution path does
    # (sandboxenv_context() -> resolve_sandbox()), so that the set of sandboxes we
    # initialize here matches what each sample actually uses at runtime -- including
    # docker-compatible per-sample configs (e.g. a per-sample ComposeConfig).
    sandbox = await resolve_sandbox(sandbox, sample)
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
    # resolved sandbox
    resolved_sandbox: SandboxEnvironmentSpec | None = None

    # resolve sandbox (task type overrides sample type, but sample config
    # file overrides task config file if they have the same type or if
    # the sample has a docker compatible config)
    task_sandbox = sandbox
    if task_sandbox is not None:
        if (
            sample.sandbox
            and sample.sandbox.config is not None
            and (
                # share the same type
                (sample.sandbox.type == task_sandbox.type)
                # have a docker compatible config => docker compatible sandbox type
                or (
                    is_docker_compatible_config(sample.sandbox.config)
                    and is_docker_compatible_sandbox_type(task_sandbox.type)
                )
            )
        ):
            sandbox_config: SandboxEnvironmentConfigType | None = sample.sandbox.config
        else:
            sandbox_config = task_sandbox.config
            if (
                sample.sandbox is not None
                and sample.sandbox.config is not None
                and sample.sandbox.type != task_sandbox.type
                and is_docker_compatible_config(sample.sandbox.config)
                and not is_docker_compatible_sandbox_type(task_sandbox.type)
            ):
                # the sample declares a Dockerfile/compose.yaml config, but the
                # effective sandbox type doesn't understand it (either the task
                # itself uses an incompatible type, or an eval-level override
                # does) -- the sample's config is silently dropped otherwise.
                warn_once(
                    logger,
                    f"A sample declares sandbox '{sample.sandbox.type}' with a "
                    "Dockerfile/compose.yaml configuration, but the effective "
                    f"sandbox type is '{task_sandbox.type}', which does not "
                    "support that configuration. The sample's compose services, "
                    "packages, and tools will not be available in the "
                    f"'{task_sandbox.type}' sandbox.",
                )
        resolved_sandbox = SandboxEnvironmentSpec(task_sandbox.type, sandbox_config)
    elif sample.sandbox is not None:
        resolved_sandbox = sample.sandbox

    return resolved_sandbox


async def _retrying_httpx_get(
    url: str,
    client: httpx.AsyncClient | None = None,
    timeout: int = 30,  # per-attempt timeout
    max_retries: int = 10,
    total_timeout: int = 120,  #  timeout for the whole retry loop. not for an individual attempt
) -> bytes:
    client = client or httpx.AsyncClient()
    async with client:

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
