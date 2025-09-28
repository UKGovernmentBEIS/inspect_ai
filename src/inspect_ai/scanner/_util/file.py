import os
from typing import Any, cast
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from inspect_ai._util.file import file

# NOTE We currently don't run any of these operations async. We were using anyio.to_thread.run_sync
# however observed deadlocks at exit when doing this so are back to sync. If we want to make this
# async we should probably condition this on the asyncio backend and use aioboto3


async def read_file_async(filename: str) -> bytes:
    if is_s3_filename(filename):
        bucket, key = s3_bucket_and_key(filename)
        return s3_read_file(s3_client(), bucket, key)
    else:
        with file(filename, "rb") as f:
            return f.read()


async def read_file_bytes_async(filename: str, start: int, end: int) -> bytes:
    if is_s3_filename(filename):
        bucket, key = s3_bucket_and_key(filename)
        return s3_read_file_bytes(s3_client(), bucket, key, start, end)
    else:
        with file(filename, "rb") as f:
            f.seek(start)
            return f.read(end - start)


async def write_file_async(filename: str, content: bytes) -> None:
    if is_s3_filename(filename):
        bucket, key = s3_bucket_and_key(filename)
        return s3_write_file(s3_client(), bucket, key, content)
    else:
        with file(filename, "wb") as f:
            f.write(content)


async def delete_files_async(filenames: list[str]) -> None:
    # Group files by S3 bucket for efficient batch deletion
    s3_files_by_bucket: dict[str, list[str]] = {}
    local_files: list[str] = []

    for filename in filenames:
        if is_s3_filename(filename):
            bucket, key = s3_bucket_and_key(filename)
            if bucket not in s3_files_by_bucket:
                s3_files_by_bucket[bucket] = []
            s3_files_by_bucket[bucket].append(key)
        else:
            local_files.append(filename)

    # Delete S3 files in batches per bucket
    for bucket, keys in s3_files_by_bucket.items():
        s3_batch_delete(s3_client(), bucket, keys)

    # Delete local files individually
    for filename in local_files:
        os.unlink(filename)


def s3_read_file(s3: Any, bucket: str, key: str) -> bytes:
    response = s3.get_object(Bucket=bucket, Key=key)
    return cast(bytes, response["Body"].read())


def s3_read_file_bytes(s3: Any, bucket: str, key: str, start: int, end: int) -> bytes:
    range_header = f"bytes={start}-{end - 1}"
    response = s3.get_object(Bucket=bucket, Key=key, Range=range_header)
    return cast(bytes, response["Body"].read())


def s3_write_file(s3: Any, bucket: str, key: str, content: bytes) -> None:
    s3.put_object(Bucket=bucket, Key=key, Body=content)


def s3_batch_delete(s3: Any, bucket: str, keys: list[str]) -> list[dict[str, Any]]:
    # S3 delete_objects can handle up to 1000 keys at once
    # Split into batches if needed
    batch_size = 1000
    responses = []

    for i in range(0, len(keys), batch_size):
        batch_keys = keys[i : i + batch_size]
        delete_request = {"Objects": [{"Key": key} for key in batch_keys]}
        response = s3.delete_objects(Bucket=bucket, Delete=delete_request)
        responses.append(response)

    return responses


def s3_bucket_and_key(filename: str) -> tuple[str, str]:
    parsed = urlparse(filename)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def is_s3_filename(filename: str) -> bool:
    return filename.startswith("s3://")


def s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            config=Config(
                max_pool_connections=50,
                retries={"max_attempts": 10, "mode": "adaptive"},
            ),
        )
    return _s3_client


_s3_client: Any | None = None
