from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, cast
from urllib.parse import urlparse

import anyio.to_thread
import boto3
from botocore.config import Config
from typing_extensions import override

from inspect_ai._util._async import current_async_backend
from inspect_ai._util.file import file


class AsyncFilesystem(AbstractAsyncContextManager["AsyncFilesystem"]):
    """Interface for reading/writing files that uses differnet interfaces depending on context

    1. Use aioboto3 when accessing s3 under the asyncio backend
    2. Use boto3 with anyio.to_thread when using s3 under the trio backend
    3. Use fsspec when using any other filesystem

    Call close() when finished with the filesystem (or use it as a context manager)
    """

    # create clients on demand
    _s3_client: Any | None = None
    _s3_client_async: Any | None = None

    async def read_file(self, filename: str) -> bytes:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).get_object(
                    Bucket=bucket, Key=key
                )
                return cast(bytes, await response["Body"].read())
            else:
                return await anyio.to_thread.run_sync(
                    s3_read_file, self.s3_client(), bucket, key
                )
        else:
            with file(filename, "rb") as f:
                return f.read()

    async def read_file_bytes(self, filename: str, start: int, end: int) -> bytes:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                response = await (await self.s3_client_async()).get_object(
                    Bucket=bucket, Key=key, Range=f"bytes={start}-{end - 1}"
                )
                return cast(bytes, await response["Body"].read())
            return await anyio.to_thread.run_sync(
                s3_read_file_bytes, self.s3_client(), bucket, key, start, end
            )
        else:
            with file(filename, "rb") as f:
                f.seek(start)
                return f.read(end - start)

    async def write_file(self, filename: str, content: bytes) -> None:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if current_async_backend() == "asyncio":
                await (await self.s3_client_async()).put_object(
                    Bucket=bucket, Key=key, Body=content
                )
            else:
                await anyio.to_thread.run_sync(
                    s3_write_file, self.s3_client(), bucket, key, content
                )
        else:
            with file(filename, "wb") as f:
                f.write(content)

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(
        self,
    ) -> None:
        if self._s3_client_async is not None:
            await self._s3_client_async.__aexit__()
            self._s3_client_async = None

    def s3_client(self) -> Any:
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3",
                config=Config(
                    max_pool_connections=50,
                    retries={"max_attempts": 10, "mode": "adaptive"},
                ),
            )

        return self._s3_client

    async def s3_client_async(self) -> Any:
        if self.s3_client_async is None:
            import aioboto3

            session = aioboto3.Session()
            self._s3_client_async = await session.client(
                "s3",
            ).__aenter__()

        return self._s3_client_async


def s3_read_file(s3: Any, bucket: str, key: str) -> bytes:
    response = s3.get_object(Bucket=bucket, Key=key)
    return cast(bytes, response["Body"].read())


def s3_read_file_bytes(s3: Any, bucket: str, key: str, start: int, end: int) -> bytes:
    range_header = f"bytes={start}-{end - 1}"
    response = s3.get_object(Bucket=bucket, Key=key, Range=range_header)
    return cast(bytes, response["Body"].read())


def s3_write_file(s3: Any, bucket: str, key: str, content: bytes) -> None:
    s3.put_object(Bucket=bucket, Key=key, Body=content)


def s3_bucket_and_key(filename: str) -> tuple[str, str]:
    parsed = urlparse(filename)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def is_s3_filename(filename: str) -> bool:
    return filename.startswith("s3://")
