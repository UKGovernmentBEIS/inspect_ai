"""A local add-only store on moto server, for the tamper-evident logs prototype.

Runs moto server in a subprocess with IAM enforcement on (moto reads
``INITIAL_NO_AUTH_ACTION_COUNT`` once per process, so it cannot share the
in-process server other tests use). Creates three users:

- ``admin``: everything; creates the bucket (Object Lock, COMPLIANCE).
- ``evalhost``: ``s3:PutObject`` only, plus the Object Lock settings read.
  moto files ``GET ?object-lock`` under ``s3:ListBucket`` (real S3:
  ``s3:GetBucketObjectLockConfiguration``), so the user also gets
  ``s3:ListBucket`` here.
- ``validator``: read-only.

moto does not evaluate the ``s3:if-none-match`` condition key: a bucket
policy that denies a put without the header denies every put. So
``require_if_none_match_policy`` is applied only after the eval has written,
so the validator's settings check has a policy to read.
"""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, get_args

import boto3
import httpx

from inspect_ai.log._addonly._validate import (
    FindingKind,
    ValidationReport,
    validate_store,
)

BUCKET = "addonly-store"
REGION = "us-east-1"

# create_user, put_user_policy, create_access_key for `admin`
_UNAUTHENTICATED_ACTIONS = 3


@dataclass(frozen=True)
class Keys:
    access_key_id: str
    secret_access_key: str

    def env(self) -> dict[str, str]:
        return {
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
        }


class CliResult(NamedTuple):
    """Exit code and output (stdout and stderr) of `inspect validate`."""

    command: list[str]
    exit_code: int
    output: str

    def findings(self) -> list[tuple[FindingKind, str]]:
        """(kind, rest of line) for each finding line."""
        kinds: tuple[FindingKind, ...] = get_args(FindingKind)
        return [
            (kind, rest)
            for kind, _, rest in (
                line.partition(" ") for line in self.output.splitlines()
            )
            if kind in kinds
        ]

    def kinds(self) -> set[str]:
        return {kind for kind, _ in self.findings()}


@dataclass(frozen=True)
class MotoStore:
    endpoint: str
    admin: Keys
    evalhost: Keys
    validator: Keys
    url: str = f"s3://{BUCKET}/evals"

    @property
    def prefix(self) -> str:
        return self.url.removeprefix(f"s3://{BUCKET}/")

    def client(self, keys: Keys) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=REGION,
            aws_access_key_id=keys.access_key_id,
            aws_secret_access_key=keys.secret_access_key,
        )

    def env(self, keys: Keys) -> dict[str, str]:
        return {
            "AWS_ENDPOINT_URL": self.endpoint,
            "AWS_DEFAULT_REGION": REGION,
            **keys.env(),
        }

    def require_if_none_match_policy(self) -> None:
        self.client(self.admin).put_bucket_policy(
            Bucket=BUCKET,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "RequireIfNoneMatch",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:PutObject",
                            "Resource": f"arn:aws:s3:::{BUCKET}/*",
                            "Condition": {"Null": {"s3:if-none-match": "true"}},
                        }
                    ],
                }
            ),
        )

    @contextmanager
    def _policy_in_place(self) -> Iterator[None]:
        """The bucket policy, for the validator's settings check.

        moto refuses every put while it is in place, so it is removed after.
        """
        self.require_if_none_match_policy()
        try:
            yield
        finally:
            self.client(self.admin).delete_bucket_policy(Bucket=BUCKET)

    def validate(self, log_dir: str | Path) -> ValidationReport:
        """Validate in process, with the validator's keys."""
        with self._policy_in_place():
            return validate_store(
                self.url, str(log_dir), client=self.client(self.validator)
            )

    def validate_cli(
        self, log_dir: str | Path, *options: str, policy: bool = True
    ) -> CliResult:
        """Run `inspect validate LOG_DIR --store URL` in a subprocess, with the validator's keys.

        Without ``policy``, the bucket has no policy that requires If-None-Match.
        """
        command = [
            sys.executable,
            "-m",
            "inspect_ai",
            "validate",
            str(log_dir),
            "--store",
            self.url,
            *options,
        ]
        with self._policy_in_place() if policy else nullcontext():
            result = subprocess.run(
                command,
                env={**os.environ, **self.env(self.validator), "COLUMNS": "200"},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
        return CliResult(command, result.returncode, result.stdout)

    def remove_version(self, key: str) -> None:
        """Delete the only version of a record for good (no delete marker).

        Real S3 refuses this under COMPLIANCE retention, for every user. moto
        lets the admin shorten the retention first, so the tests use it to show
        what the validator sees when a record is gone.
        """
        s3 = self.client(self.admin)
        full_key = f"{self.prefix}/{key}"
        (version,) = [
            v
            for v in s3.list_object_versions(Bucket=BUCKET, Prefix=self.prefix)[
                "Versions"
            ]
            if v["Key"] == full_key
        ]
        s3.put_object_retention(
            Bucket=BUCKET,
            Key=full_key,
            VersionId=version["VersionId"],
            Retention={
                "Mode": "COMPLIANCE",
                "RetainUntilDate": datetime(2020, 1, 1, tzinfo=timezone.utc),
            },
        )
        s3.delete_object(Bucket=BUCKET, Key=full_key, VersionId=version["VersionId"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _policy(*statements: dict[str, Any]) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


@contextmanager
def moto_addonly_store() -> Iterator[MotoStore]:
    port = _free_port()
    endpoint = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)],
        env={
            **os.environ,
            "INITIAL_NO_AUTH_ACTION_COUNT": str(_UNAUTHENTICATED_ACTIONS),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                httpx.get(f"{endpoint}/moto-api/", timeout=1)
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "moto server did not start"
                time.sleep(0.1)

        def iam(keys: Keys | None = None) -> Any:
            keys = keys or Keys("bootstrap", "bootstrap")
            return boto3.client(
                "iam",
                endpoint_url=endpoint,
                region_name=REGION,
                aws_access_key_id=keys.access_key_id,
                aws_secret_access_key=keys.secret_access_key,
            )

        def user(client: Any, name: str, policy: str) -> Keys:
            client.create_user(UserName=name)
            client.put_user_policy(
                UserName=name, PolicyName=name, PolicyDocument=policy
            )
            key = client.create_access_key(UserName=name)["AccessKey"]
            return Keys(key["AccessKeyId"], key["SecretAccessKey"])

        admin = user(
            iam(), "admin", _policy({"Effect": "Allow", "Action": "*", "Resource": "*"})
        )
        evalhost = user(
            iam(admin),
            "evalhost",
            _policy(
                {
                    "Effect": "Allow",
                    "Action": "s3:PutObject",
                    "Resource": f"arn:aws:s3:::{BUCKET}/*",
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketObjectLockConfiguration", "s3:ListBucket"],
                    "Resource": f"arn:aws:s3:::{BUCKET}",
                },
            ),
        )
        validator = user(
            iam(admin),
            "validator",
            _policy(
                {
                    "Effect": "Allow",
                    "Action": ["s3:Get*", "s3:List*"],
                    "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
                }
            ),
        )
        store = MotoStore(endpoint, admin, evalhost, validator)
        s3 = store.client(admin)
        s3.create_bucket(Bucket=BUCKET, ObjectLockEnabledForBucket=True)
        s3.put_object_lock_configuration(
            Bucket=BUCKET,
            ObjectLockConfiguration={
                "ObjectLockEnabled": "Enabled",
                "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": 1}},
            },
        )
        yield store
    finally:
        server.terminate()
        server.wait(timeout=10)
