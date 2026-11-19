"""Client for the add-only store: an S3 bucket that refuses overwrites.

PROTOTYPE (tamper-evident eval logs, step 1). See
docs/prototype-tamper-evident-logs-findings.md.
"""

import os
from typing import Any, NamedTuple
from urllib.parse import quote

import anyio.to_thread
from botocore.exceptions import ClientError

ADDONLY_STORE_ENV = "INSPECT_ADDONLY_STORE"
"""``s3://bucket/prefix`` of the add-only store the eval writes to."""


class AddOnlyStoreError(Exception):
    """A write to the add-only store failed, or the store is set up wrong.

    Stops the eval: the sample cannot continue past a boundary whose write
    the store did not confirm.
    """


class StoreLocation(NamedTuple):
    bucket: str
    prefix: str

    @classmethod
    def parse(cls, url: str) -> "StoreLocation":
        if not url.startswith("s3://"):
            raise ValueError(f"Add-only store must be an s3:// URL: {url}")
        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        return cls(bucket, prefix.strip("/"))

    def key(self, *parts: str) -> str:
        return "/".join([self.prefix, *parts] if self.prefix else parts)


def addonly_store_location() -> StoreLocation | None:
    url = os.environ.get(ADDONLY_STORE_ENV)
    return StoreLocation.parse(url) if url else None


def sample_key_part(sample_id: str | int, epoch: int) -> str:
    """``<sample-id>.<epoch>`` with the sample id URL-encoded.

    ``quote`` leaves ``.`` alone, so it is encoded too: a ``.`` in a sample
    id must not look like the epoch separator.
    """
    return f"{quote(str(sample_id), safe='').replace('.', '%2E')}.{epoch}"


def s3_client() -> Any:
    """A boto3 S3 client (honours ``AWS_ENDPOINT_URL`` and the usual credentials).

    From a fresh session: the default session caches the credentials it
    first resolved.
    """
    import boto3

    return boto3.session.Session().client("s3")


def error_code(ex: ClientError) -> str:
    return str(ex.response.get("Error", {}).get("Code", ""))


class AddOnlyStore:
    """Puts records with ``If-None-Match: *``, so an existing key is never replaced.

    Uses the synchronous boto3 client in a worker thread, so it works under
    both asyncio and trio (raw boto3, not fsspec, so no fsspec event loop).
    """

    def __init__(self, location: StoreLocation, client: Any | None = None) -> None:
        self.location = location
        self._client = client if client is not None else s3_client()

    async def put(self, key: str, body: bytes) -> None:
        try:
            await anyio.to_thread.run_sync(self._put, key, body)
        except ClientError as ex:
            raise AddOnlyStoreError(
                f"Add-only store refused record '{key}': {error_code(ex)} ({ex})"
            ) from ex
        except Exception as ex:
            raise AddOnlyStoreError(
                f"Add-only store write failed for '{key}': {ex}"
            ) from ex

    def _put(self, key: str, body: bytes) -> None:
        self._client.put_object(
            Bucket=self.location.bucket,
            Key=self.location.key(key),
            Body=body,
            IfNoneMatch="*",
        )

    async def put_start_and_check(self, key: str, body: bytes) -> None:
        """Write the start record, then try what the store must refuse.

        The eval host's role cannot read the bucket policy, so it tries the
        actions that must fail: the same put again (412), and reading and
        deleting the record (denied). It also reads the Object Lock settings.
        This catches setup mistakes; it is not a security check (a
        compromised host can report anything).
        """
        await self.put(key, body)
        await anyio.to_thread.run_sync(self._check, key, body)

    def _check(self, key: str, body: bytes) -> None:
        full_key = self.location.key(key)
        bucket = self.location.bucket

        def refused(action: str, codes: set[str], fn: Any, **kwargs: Any) -> None:
            try:
                fn(Bucket=bucket, Key=full_key, **kwargs)
            except ClientError as ex:
                if error_code(ex) in codes:
                    return
                raise AddOnlyStoreError(
                    f"Add-only store check: {action} failed with "
                    f"{error_code(ex)}, expected {sorted(codes)}"
                ) from ex
            raise AddOnlyStoreError(
                f"Add-only store check: {action} succeeded but must be refused"
            )

        refused(
            "overwrite with If-None-Match",
            {"PreconditionFailed"},
            self._client.put_object,
            Body=body,
            IfNoneMatch="*",
        )
        refused("read", {"AccessDenied"}, self._client.get_object)
        refused("delete", {"AccessDenied"}, self._client.delete_object)

        try:
            lock = self._client.get_object_lock_configuration(Bucket=bucket)[
                "ObjectLockConfiguration"
            ]
        except ClientError as ex:
            raise AddOnlyStoreError(
                f"Add-only store check: cannot read Object Lock settings: {ex}"
            ) from ex
        mode = lock.get("Rule", {}).get("DefaultRetention", {}).get("Mode")
        if lock.get("ObjectLockEnabled") != "Enabled" or mode != "COMPLIANCE":
            raise AddOnlyStoreError(
                f"Add-only store check: bucket '{bucket}' needs Object Lock with "
                f"default retention in COMPLIANCE mode (found {lock})"
            )
