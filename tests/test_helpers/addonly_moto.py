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
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import httpx

from inspect_ai.log._addonly._validate import ValidationReport, validate_store

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

    def validate(self, log_dir: str | Path) -> ValidationReport:
        """Validate with the bucket policy in place (moto refuses every put under it)."""
        self.require_if_none_match_policy()
        try:
            return validate_store(
                self.url, str(log_dir), client=self.client(self.validator)
            )
        finally:
            self.client(self.admin).delete_bucket_policy(Bucket=BUCKET)


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
