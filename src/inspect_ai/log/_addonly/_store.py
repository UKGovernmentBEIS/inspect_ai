"""Client for the add-only store: an S3 bucket that refuses overwrites.

PROTOTYPE (tamper-evident eval logs, step 1). See
design/prototype-tamper-evident-logs-findings.md.
"""

from itertools import count
from typing import Any, NamedTuple
from urllib.parse import quote

import anyio
import anyio.to_thread
from botocore.exceptions import ClientError, ConnectionError, HTTPClientError

PUT_RETRY_SECONDS = 60.0
"""How long a put is retried before the write fails (the plan leaves the limit open)."""

_TRANSIENT_CODES = {
    "ConditionalRequestConflict",
    "InternalError",
    "RequestTimeout",
    "ServiceUnavailable",
    "SlowDown",
    "Throttling",
    "ThrottlingException",
}


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


def sample_key_part(sample_id: str | int, epoch: int) -> str:
    """``<sample-id>.<epoch>`` with the sample id URL-encoded.

    ``quote`` leaves ``.`` alone, so it is encoded too: a ``.`` in a sample
    id must not look like the epoch separator.
    """
    return f"{quote(str(sample_id), safe='').replace('.', '%2E')}.{epoch}"


def s3_client(sdk_retries: bool = True) -> Any:
    """A boto3 S3 client (honours ``AWS_ENDPOINT_URL`` and the usual credentials).

    From a fresh session: the default session caches the credentials it
    first resolved. The pool is large enough for the eval's puts at once:
    when it is full, urllib3 logs a warning in the put's worker thread, which
    goes into the sample's transcript from that thread, and the transcript
    then skips the sample buffer for events recorded at the same time.
    """
    import boto3
    from botocore.config import Config

    config = Config(
        max_pool_connections=50,
        retries=None if sdk_retries else {"max_attempts": 0},
    )
    return boto3.session.Session().client("s3", config=config)


def error_code(ex: ClientError) -> str:
    return str(ex.response.get("Error", {}).get("Code", ""))


def _transient(ex: Exception) -> bool:
    """A network error, throttling or a 5xx: the put may succeed if tried again."""
    if isinstance(ex, ClientError):
        status = ex.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return status >= 500 or error_code(ex) in _TRANSIENT_CODES
    return isinstance(ex, (ConnectionError, HTTPClientError))


class AddOnlyStore:
    """Puts records with ``If-None-Match: *``, so an existing key is never replaced.

    Uses the synchronous boto3 client in a worker thread, so it works under
    both asyncio and trio (raw boto3, not fsspec, so no fsspec event loop).
    """

    def __init__(self, location: StoreLocation, client: Any | None = None) -> None:
        self.location = location
        self._client = client if client is not None else s3_client(sdk_retries=False)

    async def put(self, key: str, body: bytes) -> None:
        """Put a record, retrying transient errors for up to ``PUT_RETRY_SECONDS``.

        The client has SDK retries off, so this loop sees every attempt. Any
        412 fails the write, also one after a retried put: the host cannot
        read the store to tell its own lost put from a record another writer
        added first.
        """
        deadline = anyio.current_time() + PUT_RETRY_SECONDS
        for attempt in count(1):
            try:
                await anyio.to_thread.run_sync(self._put, key, body)
                return
            except Exception as ex:
                if _transient(ex) and anyio.current_time() < deadline:
                    await anyio.sleep(min(0.1 * 2**attempt, 5.0))
                    continue
                raise AddOnlyStoreError(_put_error(key, ex, attempt)) from ex

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


def _put_error(key: str, ex: Exception, attempts: int) -> str:
    if not isinstance(ex, ClientError):
        return (
            f"Add-only store write failed for '{key}' after {attempts} attempt(s): {ex}"
        )
    lost_put = (
        " The record may be this eval's own earlier put whose response was lost."
        if error_code(ex) == "PreconditionFailed" and attempts > 1
        else ""
    )
    return (
        f"Add-only store refused record '{key}' after {attempts} attempt(s): "
        f"{error_code(ex)} ({ex}).{lost_put}"
    )
