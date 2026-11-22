"""Tamper-evident logs: what moto server enforces for the add-only store.

Checks If-None-Match, compliance-mode Object Lock, a bucket policy that
requires If-None-Match, and IAM limits on the eval host's user. Each line
prints what real S3 does (from the AWS documentation) and what moto did.

Usage (from the repo root): PYTHONPATH=tests python scripts/addonly_moto_probe.py
"""

import datetime
from typing import Any, Callable

from botocore.exceptions import ClientError
from test_helpers.addonly_moto import BUCKET, moto_addonly_store


def outcome(fn: Callable[[], Any]) -> str:
    try:
        fn()
        return "allowed"
    except ClientError as ex:
        return f"refused ({ex.response['Error']['Code']})"


def main() -> None:
    rows: list[tuple[str, str, str]] = []

    def check(name: str, aws: str, fn: Callable[[], Any]) -> None:
        rows.append((name, aws, outcome(fn)))

    with moto_addonly_store() as store:
        admin = store.client(store.admin)
        host = store.client(store.evalhost)

        def put(client: Any, key: str, **kwargs: Any) -> Any:
            return client.put_object(Bucket=BUCKET, Key=key, Body=b"x", **kwargs)

        check(
            "host: put new key, If-None-Match",
            "allowed",
            lambda: put(host, "a", IfNoneMatch="*"),
        )
        check(
            "host: put same key, If-None-Match",
            "refused (412)",
            lambda: put(host, "a", IfNoneMatch="*"),
        )
        check(
            "host: put same key, no If-None-Match (no bucket policy)",
            "allowed, adds a version",
            lambda: put(host, "a"),
        )
        versions = admin.list_object_versions(Bucket=BUCKET, Prefix="a")["Versions"]
        rows.append(("  versions of 'a' now", "2", str(len(versions))))
        oldest = min(versions, key=lambda v: v["LastModified"])["VersionId"]
        check(
            "host: get",
            "refused (role)",
            lambda: host.get_object(Bucket=BUCKET, Key="a"),
        )
        check(
            "host: delete",
            "refused (role)",
            lambda: host.delete_object(Bucket=BUCKET, Key="a"),
        )
        check(
            "host: list (moto setup grants s3:ListBucket)",
            "refused (role)",
            lambda: host.list_objects_v2(Bucket=BUCKET),
        )
        check(
            "host: read Object Lock settings (moto: needs s3:ListBucket)",
            "allowed",
            lambda: host.get_object_lock_configuration(Bucket=BUCKET),
        )
        check(
            "admin: delete a locked version",
            "refused (compliance)",
            lambda: admin.delete_object(Bucket=BUCKET, Key="a", VersionId=oldest),
        )
        check(
            "admin: delete a locked version, bypass governance",
            "refused (compliance)",
            lambda: admin.delete_object(
                Bucket=BUCKET, Key="a", VersionId=oldest, BypassGovernanceRetention=True
            ),
        )
        check(
            "admin: shorten compliance retention",
            "refused (compliance)",
            lambda: admin.put_object_retention(
                Bucket=BUCKET,
                Key="a",
                VersionId=oldest,
                Retention={
                    "Mode": "COMPLIANCE",
                    "RetainUntilDate": datetime.datetime(
                        2020, 1, 1, tzinfo=datetime.timezone.utc
                    ),
                },
            ),
        )
        check(
            "admin: delete that version after shortening",
            "refused (never shortened)",
            lambda: admin.delete_object(Bucket=BUCKET, Key="a", VersionId=oldest),
        )
        check(
            "admin: suspend versioning on an Object Lock bucket",
            "refused (InvalidBucketState)",
            lambda: admin.put_bucket_versioning(
                Bucket=BUCKET, VersioningConfiguration={"Status": "Suspended"}
            ),
        )
        admin.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )

        store.require_if_none_match_policy()
        check(
            "policy Deny if s3:if-none-match is Null: put without header",
            "refused (403)",
            lambda: put(host, "b"),
        )
        check(
            "policy Deny if s3:if-none-match is Null: put with header",
            "allowed",
            lambda: put(host, "c", IfNoneMatch="*"),
        )
        admin.delete_bucket_policy(Bucket=BUCKET)

        check(
            "validator: list versions, Prefix with '/'",
            "allowed",
            lambda: store.client(store.validator).list_object_versions(
                Bucket=BUCKET, Prefix="evals/"
            ),
        )
        check("host: put key with '%' in it", "allowed", lambda: put(host, "s%2E1.1"))

    width = max(len(name) for name, _, _ in rows)
    print(f"{'action'.ljust(width)}  {'real S3 (docs)':28}  moto")
    for name, aws, moto in rows:
        print(f"{name.ljust(width)}  {aws:28}  {moto}")


if __name__ == "__main__":
    main()
