"""Tests for the inspect view server."""

import asyncio
import base64
import contextlib
import json
import logging
import math
import time
import urllib.parse
import zipfile
from io import BytesIO
from pathlib import Path
from typing import (
    IO,
    Any,
    AsyncIterator,
    Callable,
    ContextManager,
    Generator,
    TextIO,
    cast,
)

import anyio
import fastapi.testclient
import fsspec  # type: ignore
import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

import inspect_ai._eval.evalset
import inspect_ai._eval.task.resolved
import inspect_ai._util.file
import inspect_ai.dataset
import inspect_ai.log
import inspect_ai.log._recorders.buffer.filestore
import inspect_ai.model
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.event_loop_monitor import event_loop_monitor
from inspect_ai._util.json import to_json_safe
from inspect_ai._view import fastapi_server
from inspect_ai._view.common import (
    get_direct_url,
    get_log_bytes,
    normalize_uri,
    read_eval_set_info_async,
    stream_log_bytes,
)
from inspect_ai._view.fastapi_server import AccessPolicy, FileMappingPolicy
from inspect_ai.event import ScoreEvent
from inspect_ai.log import list_eval_logs_async
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.scorer import Score

FRONTEND_REQUEST_HEADERS = {
    fastapi_server.VIEW_REQUEST_HEADER: fastapi_server.VIEW_REQUEST_HEADER_VALUE,
    "Sec-Fetch-Dest": "empty",
}

# ═══════════════════════════════════════════════════════════════════════════
# Test client wrapper
# ═══════════════════════════════════════════════════════════════════════════


class SimpleResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict[str, str],
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {k.lower(): v for k, v in headers.items()}

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(
                f"HTTP {self.status_code}: {self.content[:200].decode('utf-8', errors='replace')}"
            )


class ViewTestClient:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        app = fastapi_server.view_server_app(default_dir=str(log_dir))
        self._tc = fastapi.testclient.TestClient(app)
        self._tc.__enter__()

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> SimpleResponse:
        kwargs: dict[str, Any] = {"headers": headers or {}}
        if json is not None:
            kwargs["json"] = json
        resp = self._tc.request(method, path, **kwargs)
        return SimpleResponse(resp.status_code, resp.content, dict(resp.headers))

    def frontend_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> SimpleResponse:
        return self.request(
            method,
            path,
            headers={**FRONTEND_REQUEST_HEADERS, **(headers or {})},
            json=json,
        )

    def log_path(self, filename: str) -> str:
        return str(self.log_dir / filename)

    def log_url(self, endpoint: str, filename: str) -> str:
        return f"/{endpoint}/{self.log_path(filename)}"

    def close(self) -> None:
        self._tc.__exit__(None, None, None)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def write_eval_log(base_dir: Path, filename: str, status: str = "success") -> str:
    """Write a minimal eval log to ``base_dir/filename``. Return full path.

    Defaults to a finished log (``status="success"``); tests exercising
    in-progress behavior should pass ``status="started"`` explicitly.
    """
    full_path = str(base_dir / filename)
    eval_log = inspect_ai.log.EvalLog(
        status=status,  # type: ignore[arg-type]
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="task",
            task_id="task_id",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        ),
    )
    inspect_ai.log.write_eval_log(eval_log, full_path, "eval")
    return full_path


def _create_sample_buffer(log_path: str) -> None:
    """Create a minimal sample buffer on disk for the given log file."""
    from inspect_ai.log._recorders.buffer.filestore import (
        Manifest,
        SampleBufferFilestore,
        SampleManifest,
        Segment,
        SegmentFile,
    )
    from inspect_ai.log._recorders.buffer.types import EventData, SampleData

    buf = SampleBufferFilestore(log_path, create=True)
    buf.write_segment(
        0,
        [
            SegmentFile(
                id="sample1",
                epoch=0,
                data=SampleData(
                    events=[
                        EventData(
                            id=1,
                            event_id="evt0",
                            sample_id="sample1",
                            epoch=0,
                            event={"message": "hello"},
                        )
                    ],
                    attachments=[],
                ),
            )
        ],
    )
    buf.write_manifest(
        Manifest(
            samples=[
                SampleManifest(
                    summary=inspect_ai.log.EvalSampleSummary(
                        id="sample1",
                        epoch=0,
                        input="test input",
                        target="test target",
                    ),
                    segments=[0],
                )
            ],
            segments=[Segment(id=0, last_event_id=1, last_attachment_id=0)],
        )
    )


def _create_sample_buffer_with_id(log_path: str, sample_id: int | str) -> None:
    """Create a minimal sample buffer that stores `sample_id` as written."""
    from inspect_ai.log._recorders.buffer.filestore import (
        Manifest,
        SampleBufferFilestore,
        SampleManifest,
        Segment,
        SegmentFile,
    )
    from inspect_ai.log._recorders.buffer.types import EventData, SampleData

    buf = SampleBufferFilestore(log_path, create=True)
    buf.write_segment(
        0,
        [
            SegmentFile(
                id=str(sample_id),
                epoch=0,
                data=SampleData(
                    events=[
                        EventData(
                            id=1,
                            event_id="evt0",
                            sample_id=str(sample_id),
                            epoch=0,
                            event={"message": "hello"},
                        )
                    ],
                    attachments=[],
                ),
            )
        ],
    )
    buf.write_manifest(
        Manifest(
            samples=[
                SampleManifest(
                    summary=inspect_ai.log.EvalSampleSummary(
                        id=sample_id,
                        epoch=0,
                        input="test input",
                        target="test target",
                    ),
                    segments=[0],
                )
            ],
            segments=[Segment(id=0, last_event_id=1, last_attachment_id=0)],
        )
    )


def _create_multi_segment_sample_buffer(log_path: str, num_segments: int) -> None:
    """Create a sample buffer with `num_segments` segments.

    Segment `i` carries `last_event_id = i + 1` (SQL AUTOINCREMENT ids
    start at 1) and zero entries on the other dimensions. Empty pool
    dimensions use the writer's `0` sentinel.
    """
    from inspect_ai.log._recorders.buffer.filestore import (
        Manifest,
        SampleBufferFilestore,
        SampleManifest,
        Segment,
        SegmentFile,
    )
    from inspect_ai.log._recorders.buffer.types import EventData, SampleData

    buf = SampleBufferFilestore(log_path, create=True)
    for i in range(num_segments):
        buf.write_segment(
            i,
            [
                SegmentFile(
                    id="sample1",
                    epoch=0,
                    data=SampleData(
                        events=[
                            EventData(
                                id=i + 1,
                                event_id=f"evt{i}",
                                sample_id="sample1",
                                epoch=0,
                                event={"message": f"event {i}"},
                            )
                        ],
                        attachments=[],
                    ),
                )
            ],
        )
    buf.write_manifest(
        Manifest(
            samples=[
                SampleManifest(
                    summary=inspect_ai.log.EvalSampleSummary(
                        id="sample1",
                        epoch=0,
                        input="test input",
                        target="test target",
                    ),
                    segments=list(range(num_segments)),
                )
            ],
            segments=[
                Segment(
                    id=i,
                    last_event_id=i + 1,
                    last_attachment_id=0,
                    last_message_pool_id=0,
                    last_call_pool_id=0,
                )
                for i in range(num_segments)
            ],
        )
    )


def write_eval_log_named(base_dir: Path, filename: str, task: str, task_id: str) -> str:
    """Write eval log with specific task/task_id. Return full path."""
    full_path = str(base_dir / filename)
    eval_log = inspect_ai.log.EvalLog(
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task=task,
            task_id=task_id,
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        )
    )
    inspect_ai.log.write_eval_log(eval_log, full_path, "eval")
    return full_path


# ═══════════════════════════════════════════════════════════════════════════
# Fixture
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def view_client(tmp_path: Path) -> Generator[ViewTestClient, Any, None]:
    client = ViewTestClient(tmp_path)
    yield client
    client.close()


# ═══════════════════════════════════════════════════════════════════════════
# View server tests (real local paths)
# ═══════════════════════════════════════════════════════════════════════════


def test_api_log(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("logs", fname))
    resp.raise_for_status()
    assert resp.json()["eval"]["task"] == "task"


def test_api_app_config(view_client: ViewTestClient) -> None:
    resp = view_client.request("GET", "/app-config")
    resp.raise_for_status()
    config = resp.json()
    assert config["inspect_version"] == inspect_ai.__version__
    # scout is an optional dependency: present as a string when installed,
    # otherwise null.
    assert "scout_version" in config
    assert config["scout_version"] is None or isinstance(config["scout_version"], str)


def test_api_log_info(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("log-info", fname))
    resp.raise_for_status()
    info = resp.json()
    assert "size" in info
    assert info["size"] >= 100
    assert "direct_url" not in info


def test_api_log_delete(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_del_delid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "DELETE", view_client.log_url("log-delete", fname)
    )
    resp.raise_for_status()
    assert not Path(full_path).exists()


def test_api_log_delete_get_is_side_effect_free(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_del_delid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("log-delete", fname))
    assert resp.status_code == 405
    assert Path(full_path).exists()


@pytest.mark.parametrize("fetch_dest", ["audio", "document", "image", "style", "video"])
def test_api_log_delete_rejects_passive_fetch_destinations(
    view_client: ViewTestClient, fetch_dest: str
) -> None:
    fname = "2025-01-01T00-00-00+00-00_del_delid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "DELETE",
        view_client.log_url("log-delete", fname),
        headers={"Sec-Fetch-Dest": fetch_dest},
    )
    assert resp.status_code == 403
    assert Path(full_path).exists()


def test_api_log_delete_cross_origin_metadata_still_requires_frontend_header(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_del_delid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "DELETE",
        view_client.log_url("log-delete", fname),
        headers={
            "Origin": "https://example.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert resp.status_code == 403
    assert Path(full_path).exists()


def test_api_log_edit_requires_frontend_request(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "POST",
        view_client.log_url("log-edit", fname),
        headers={"Sec-Fetch-Dest": "empty"},
        json={
            "edits": [{"type": "tags", "tags_add": ["x"], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    assert resp.status_code == 403
    assert inspect_ai.log.read_eval_log(full_path, header_only=True).tags == []


def test_api_log_edit_metadata_null_value_persists(
    view_client: ViewTestClient,
) -> None:
    # End-to-end regression for the "null keys are not being saved"
    # bug. Posts a MetadataEdit with a `null` value through the live
    # log-edit endpoint, then re-reads the eval file from disk and
    # checks the key landed with value None.
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [
                {
                    "type": "metadata",
                    "metadata_set": {"null_key": None, "ok_key": "v"},
                }
            ],
            "provenance": {"author": "alice"},
        },
    )
    resp.raise_for_status()
    body = resp.json()
    assert "null_key" in body["metadata"]
    assert body["metadata"]["null_key"] is None
    assert body["metadata"]["ok_key"] == "v"

    # Verify on disk too.
    persisted = inspect_ai.log.read_eval_log(full_path, header_only=True)
    assert persisted.metadata is not None
    assert "null_key" in persisted.metadata
    assert persisted.metadata["null_key"] is None
    assert persisted.metadata["ok_key"] == "v"


def test_api_log_edit_returns_409_for_in_progress_log(
    view_client: ViewTestClient,
) -> None:
    # The recorder owns a still-running log (status == "started") and
    # is actively appending to it. A viewer-driven header rewrite would
    # race that write loop, so the server refuses edits to such logs
    # with 409 Conflict (distinct from 412 stale-ETag and 400 bad-input
    # so the client can render the right message).
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname, status="started")
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [{"type": "tags", "tags_add": ["qa_passed"], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    assert resp.status_code == 409
    # Body conveys the reason so the UI can surface it.
    assert "in progress" in resp.text.lower()

    # Crucially, the rejected edit must not have written anything: the
    # on-disk header must still show no log_updates and the original
    # status.
    persisted = inspect_ai.log.read_eval_log(full_path, header_only=True)
    assert persisted.status == "started"
    assert not persisted.log_updates
    assert persisted.tags == []


def test_api_log_edit_tags_roundtrip(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [{"type": "tags", "tags_add": ["qa_passed"], "tags_remove": []}],
            "provenance": {"author": "alice", "reason": "QA complete"},
        },
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["tags"] == ["qa_passed"]
    assert len(body["log_updates"]) == 1
    assert body["log_updates"][0]["provenance"]["author"] == "alice"

    # Re-read the persisted file to confirm the edit was actually written.
    persisted = inspect_ai.log.read_eval_log(full_path, header_only=True)
    assert persisted.tags == ["qa_passed"]
    assert persisted.log_updates is not None
    assert persisted.log_updates[0].provenance.author == "alice"


def test_api_log_edit_noop_returns_unchanged(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            # Removing a tag that doesn't exist is a no-op.
            "edits": [
                {"type": "tags", "tags_add": [], "tags_remove": ["never_existed"]}
            ],
            "provenance": {"author": "alice"},
        },
    )
    resp.raise_for_status()
    assert resp.json().get("log_updates") is None
    persisted = inspect_ai.log.read_eval_log(full_path, header_only=True)
    assert persisted.log_updates is None


def test_api_log_edit_invalid_tag_returns_400(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            # Empty tag is rejected by edit_eval_log.
            "edits": [{"type": "tags", "tags_add": ["  "], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    assert resp.status_code == 400


def test_api_log_edit_missing_provenance_returns_422(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={"edits": [{"type": "tags", "tags_add": ["x"]}]},
    )
    assert resp.status_code == 422


def test_api_log_edit_append_preserves_prior_updates(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)

    first = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [{"type": "tags", "tags_add": ["one"], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    first.raise_for_status()

    second = view_client.frontend_request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [{"type": "tags", "tags_add": ["two"], "tags_remove": ["one"]}],
            "provenance": {"author": "bob"},
        },
    )
    second.raise_for_status()
    body = second.json()
    assert body["tags"] == ["two"]
    assert len(body["log_updates"]) == 2
    assert body["log_updates"][1]["provenance"]["author"] == "bob"

    persisted = inspect_ai.log.read_eval_log(full_path, header_only=True)
    assert persisted.tags == ["two"]
    assert persisted.log_updates is not None
    assert len(persisted.log_updates) == 2


def test_api_user_info(view_client: ViewTestClient) -> None:
    resp = view_client.request("GET", "/user-info")
    resp.raise_for_status()
    body = resp.json()
    # The endpoint is best-effort: in CI without git or a configured user,
    # both fields may be omitted. Just assert it's a well-shaped JSON object
    # with no surprise keys, and that any populated fields are strings.
    assert isinstance(body, dict)
    assert set(body.keys()).issubset({"name", "email"})
    for value in body.values():
        assert isinstance(value, str)


def test_api_log_bytes(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET", view_client.log_url("log-bytes", fname) + "?start=0&end=99"
    )
    resp.raise_for_status()
    assert len(resp.content) == 100


def test_api_log_download(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("log-download", fname))
    resp.raise_for_status()
    assert resp.headers.get("content-type") == "application/octet-stream"
    assert "content-disposition" in resp.headers
    assert ".eval" in resp.headers["content-disposition"]
    assert len(resp.content) == Path(full_path).stat().st_size


def test_api_log_dir(view_client: ViewTestClient) -> None:
    resp = view_client.request(
        "GET", f"/log-dir?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
    )
    resp.raise_for_status()
    assert "log_dir" in resp.json()


def test_api_logs_listing(view_client: ViewTestClient) -> None:
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-01-00+00-00_t2_id2.eval", "t2", "id2"
    )
    resp = view_client.request(
        "GET", f"/logs?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
    )
    resp.raise_for_status()
    body = resp.json()
    assert len(body["files"]) == 2
    tasks = {f["task"] for f in body["files"]}
    assert tasks == {"t1", "t2"}


def test_api_logs_listing_log_dir_uri(view_client: ViewTestClient) -> None:
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    resp = view_client.request(
        "GET", f"/logs?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
    )
    resp.raise_for_status()
    body = resp.json()
    # The canonical dir URI shares the file names' namespace, so names are
    # dir-prefixed identities (what the viewer's cache scoping relies on).
    assert body["log_dir_uri"]
    for f in body["files"]:
        assert f["name"].startswith(body["log_dir_uri"] + "/")


def test_api_log_headers(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname, status="started")
    encoded = urllib.parse.quote_plus(full_path)
    resp = view_client.request("GET", f"/log-headers?file={encoded}")
    resp.raise_for_status()
    headers = resp.json()
    assert len(headers) == 1
    assert headers[0]["status"] == "started"


def test_api_log_headers_multiple(view_client: ViewTestClient) -> None:
    f1 = write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    f2 = write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-01-00+00-00_t2_id2.eval", "t2", "id2"
    )
    q = f"file={urllib.parse.quote_plus(f1)}&file={urllib.parse.quote_plus(f2)}"
    resp = view_client.request("GET", f"/log-headers?{q}")
    resp.raise_for_status()
    assert len(resp.json()) == 2


def test_api_log_headers_forbidden() -> None:
    class NoReadPolicy(AccessPolicy):
        async def can_read(self, request: Request, file: str) -> bool:
            return False

        async def can_delete(self, request: Request, file: str) -> bool:
            return False

        async def can_list(self, request: Request, dir: str) -> bool:
            return False

        async def can_write(self, request: Request, file: str) -> bool:
            return False

    app = fastapi_server.view_server_app(access_policy=NoReadPolicy())
    with fastapi.testclient.TestClient(
        app, raise_server_exceptions=False
    ) as restricted_client:
        response = restricted_client.get(
            "/log-headers", params={"file": "restricted.eval"}
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.parametrize(
    ["last_eval_time", "expected"],
    [
        pytest.param("-1", ["refresh-evals"], id="refresh"),
        pytest.param("9999999999999", [], id="no-refresh"),
    ],
)
def test_api_events(
    view_client: ViewTestClient, last_eval_time: str, expected: list[str]
) -> None:
    resp = view_client.request("GET", f"/events?last_eval_time={last_eval_time}")
    resp.raise_for_status()
    assert resp.json() == expected


def test_api_events_no_param(view_client: ViewTestClient) -> None:
    resp = view_client.request("GET", "/events")
    resp.raise_for_status()
    assert resp.json() == []


@pytest.fixture
def client_log_messages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(
        logging.getLogger(fastapi_server.__name__), "warning", messages.append
    )
    return messages


def test_api_log_message(
    view_client: ViewTestClient, client_log_messages: list[str]
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        f"/log-message?log_file={urllib.parse.quote_plus(full_path)}&message=hello",
    )
    assert resp.status_code == 204
    assert any("[CLIENT MESSAGE]" in message for message in client_log_messages)


def test_api_log_message_get_is_side_effect_free(
    view_client: ViewTestClient, client_log_messages: list[str]
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET",
        f"/log-message?log_file={urllib.parse.quote_plus(full_path)}&message=hello",
    )
    assert resp.status_code == 405
    assert client_log_messages == []


@pytest.mark.parametrize("fetch_dest", ["audio", "document", "image", "style", "video"])
def test_api_log_message_rejects_passive_fetch_destinations(
    view_client: ViewTestClient,
    client_log_messages: list[str],
    fetch_dest: str,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.frontend_request(
        "POST",
        f"/log-message?log_file={urllib.parse.quote_plus(full_path)}&message=hello",
        headers={"Sec-Fetch-Dest": fetch_dest},
    )
    assert resp.status_code == 403
    assert client_log_messages == []


def test_api_log_message_cross_origin_metadata_still_requires_frontend_header(
    view_client: ViewTestClient, client_log_messages: list[str]
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "POST",
        f"/log-message?log_file={urllib.parse.quote_plus(full_path)}&message=hello",
        headers={
            "Origin": "https://example.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert resp.status_code == 403
    assert client_log_messages == []


def test_api_log_files_full_listing(view_client: ViewTestClient) -> None:
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-01-00+00-00_t2_id2.eval", "t2", "id2"
    )
    resp = view_client.request(
        "GET", f"/log-files?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["response_type"] == "full"
    assert len(body["files"]) == 2


def test_api_log_files_incremental(view_client: ViewTestClient) -> None:
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    resp1 = view_client.request(
        "GET", f"/log-files?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
    )
    resp1.raise_for_status()
    count = len(resp1.json()["files"])

    # Same count, old mtime → incremental
    etag = f"0.0-{count}"
    resp2 = view_client.request(
        "GET",
        f"/log-files?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}",
        headers={"If-None-Match": etag},
    )
    resp2.raise_for_status()
    assert resp2.json()["response_type"] == "incremental"


def test_api_log_files_count_change_gives_full(view_client: ViewTestClient) -> None:
    write_eval_log_named(
        view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1"
    )
    etag = "0.0-999"
    resp = view_client.request(
        "GET",
        f"/log-files?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}",
        headers={"If-None-Match": etag},
    )
    resp.raise_for_status()
    assert resp.json()["response_type"] == "full"


def test_api_flow_returns_yaml(view_client: ViewTestClient) -> None:
    flow_dir = view_client.log_dir / "flow_sub"
    flow_dir.mkdir()
    (flow_dir / "flow.yaml").write_bytes(b"steps:\n  - name: step1\n")
    resp = view_client.request(
        "GET",
        f"/flow?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}"
        "&dir=flow_sub",
    )
    resp.raise_for_status()
    assert "step1" in resp.text


def test_api_flow_missing_404(view_client: ViewTestClient) -> None:
    resp = view_client.request(
        "GET",
        f"/flow?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}",
    )
    assert resp.status_code == 404


def test_api_header_only_zero(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET", view_client.log_url("logs", fname) + "?header-only=0"
    )
    resp.raise_for_status()
    data = resp.json()
    assert data["eval"]["task"] == "task"
    assert data.get("samples") is None


def test_api_header_only_large_threshold(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET", view_client.log_url("logs", fname) + "?header-only=999999"
    )
    resp.raise_for_status()
    assert resp.json()["eval"]["task"] == "task"


def test_api_log_bytes_single_byte(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET", view_client.log_url("log-bytes", fname) + "?start=0&end=0"
    )
    resp.raise_for_status()
    assert len(resp.content) == 1


def test_api_log_size(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("log-size", fname))
    resp.raise_for_status()
    size = resp.json()
    assert isinstance(size, int)
    assert size == Path(full_path).stat().st_size


def test_api_pending_samples_no_buffer(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET", f"/pending-samples?log={urllib.parse.quote_plus(full_path)}"
    )
    assert resp.status_code == 404


def test_api_pending_samples_with_buffer(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)

    resp = view_client.request(
        "GET", f"/pending-samples?log={urllib.parse.quote_plus(full_path)}"
    )
    resp.raise_for_status()
    body = resp.json()
    assert "samples" in body
    assert len(body["samples"]) == 1
    assert body["samples"][0]["id"] == "sample1"
    assert "etag" in body

    # second request with etag → 304
    etag = body["etag"]
    resp2 = view_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(full_path)}",
        headers={"If-None-Match": etag},
    )
    assert resp2.status_code == 304


def test_api_pending_samples_preserves_non_finite_scores(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)
    buffer = inspect_ai.log._recorders.buffer.filestore.SampleBufferFilestore(
        full_path, create=False
    )
    manifest = buffer.read_manifest()
    assert manifest is not None
    manifest.samples[0].summary.scores = {"listy": Score(value=[float("nan"), 1.0])}
    buffer.write_manifest(manifest)

    response = view_client.request(
        "GET", f"/pending-samples?log={urllib.parse.quote_plus(full_path)}"
    )

    response.raise_for_status()
    value = response.json()["samples"][0]["scores"]["listy"]["value"]
    assert math.isnan(value[0])


def test_api_pending_sample_data_no_buffer(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(full_path)}&id=x&epoch=0",
    )
    assert resp.status_code == 404


def test_api_pending_sample_data_with_buffer(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["event"] == {"message": "hello"}


def test_api_pending_sample_data_preserves_non_finite_scores(
    view_client: ViewTestClient,
) -> None:
    from inspect_ai.log._recorders.buffer.filestore import (
        SampleBufferFilestore,
        SegmentFile,
    )
    from inspect_ai.log._recorders.buffer.types import EventData, SampleData

    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)
    buffer = SampleBufferFilestore(full_path, create=False)
    score_event = ScoreEvent(
        score=Score(value=[float("nan"), 1.0]),
        scorer="listy",
    )
    buffer.write_segment(
        0,
        [
            SegmentFile(
                id="sample1",
                epoch=0,
                data=SampleData(
                    events=[
                        EventData(
                            id=1,
                            event_id="evt0",
                            sample_id="sample1",
                            epoch=0,
                            event=score_event.model_dump(mode="json"),
                        )
                    ],
                    attachments=[],
                ),
            )
        ],
    )

    response = view_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0",
    )

    response.raise_for_status()
    value = response.json()["events"][0]["event"]["score"]["value"]
    assert math.isnan(value[0])


def test_api_eval_set_missing(view_client: ViewTestClient) -> None:
    resp = view_client.request(
        "GET",
        f"/eval-set?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}",
    )
    resp.raise_for_status()
    assert resp.json() is None


def test_api_eval_set_uses_fs_options_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_read_eval_set_info(log_dir: str, fs_options: dict[str, Any] = {}) -> None:
        calls.append((log_dir, fs_options))
        return None

    monkeypatch.setattr(fastapi_server, "read_eval_set_info", fake_read_eval_set_info)
    app = fastapi_server.view_server_app(fs_options={"anon": True})
    with fastapi.testclient.TestClient(app) as client:
        resp = client.request(
            "GET",
            f"/eval-set?dir={urllib.parse.quote_plus('s3://bucket/logs')}",
        )

    resp.raise_for_status()
    assert resp.json() is None
    assert calls == [("s3://bucket/logs", {"anon": True})]


def _patch_flat_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub common.filesystem so az:// paths don't construct a real adlfs fs."""
    from inspect_ai._view import common

    class FlatFileSystem:
        sep = "/"

    def fake_filesystem(path: str, fs_options: dict[str, Any] = {}) -> FlatFileSystem:
        return FlatFileSystem()

    monkeypatch.setattr(common, "filesystem", fake_filesystem)


async def test_read_eval_set_info_async_suppresses_azure_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_flat_filesystem(monkeypatch)

    class AzureAuthErrorFilesystem:
        async def exists(self, filename: str) -> bool:
            raise Exception("Server failed to authenticate the request")

    result = await read_eval_set_info_async(
        "az://container/logs", cast(AsyncFilesystem, AzureAuthErrorFilesystem())
    )
    assert result is None


async def test_read_eval_set_info_async_raises_non_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_flat_filesystem(monkeypatch)

    class BrokenFilesystem:
        async def exists(self, filename: str) -> bool:
            raise RuntimeError("connection reset by peer")

    with pytest.raises(RuntimeError):
        await read_eval_set_info_async(
            "az://container/logs", cast(AsyncFilesystem, BrokenFilesystem())
        )


async def test_list_eval_logs_async_uses_fsspec_path_with_fs_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util._async import current_async_backend
    from inspect_ai._util.file import FileInfo
    from inspect_ai.log import _file as log_file

    filesystem_calls: list[tuple[str, dict[str, Any]]] = []
    async_filesystem_calls: list[tuple[str, dict[str, Any]]] = []
    sync_ls_calls: list[tuple[str, bool]] = []

    class FakeFileSystem:
        def is_s3(self) -> bool:
            return True

        def is_async(self) -> bool:
            return True

        def exists(self, path: str) -> bool:
            return True

        def ls(self, path: str, recursive: bool = False) -> list[FileInfo]:
            sync_ls_calls.append((path, recursive))
            return [
                FileInfo(
                    name=f"{path}/2026-01-01T00-00-00_task_id.eval",
                    type="file",
                    size=123,
                    mtime=1710000000.0,
                    etag=None,
                )
            ]

        def _file_info(self, info: dict[str, Any]) -> FileInfo:
            return FileInfo(
                name=info["name"],
                type=info["type"],
                size=info.get("size", 0),
                mtime=info.get("mtime"),
                etag=None,
            )

    class FakeAsyncFileSystem:
        async def _exists(self, log_dir: str) -> bool:
            return True

        def invalidate_cache(self, log_dir: str) -> None:
            pass

        async def _ls(self, log_dir: str, detail: bool = True) -> list[dict[str, Any]]:
            return [
                {
                    "name": f"{log_dir}/2026-01-01T00-00-00_task_id.eval",
                    "type": "file",
                    "size": 123,
                    "mtime": 1710000000.0,
                }
            ]

    def fake_filesystem(path: str, fs_options: dict[str, Any] = {}) -> FakeFileSystem:
        filesystem_calls.append((path, fs_options))
        return FakeFileSystem()

    @contextlib.asynccontextmanager
    async def fake_async_filesystem(
        location: str, fs_options: dict[str, Any] = {}
    ) -> Any:
        async_filesystem_calls.append((location, fs_options))
        yield FakeAsyncFileSystem()

    class UnexpectedAsyncFilesystem:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("AsyncFilesystem fast path should not be used")

    monkeypatch.setattr(log_file, "filesystem", fake_filesystem)
    monkeypatch.setattr(log_file, "async_filesystem", fake_async_filesystem)
    monkeypatch.setattr(log_file, "AsyncFilesystem", UnexpectedAsyncFilesystem)

    logs = await list_eval_logs_async(
        "s3://bucket/logs", recursive=False, fs_options={"anon": True}
    )

    assert filesystem_calls == [("s3://bucket/logs", {"anon": True})]
    if current_async_backend() == "asyncio":
        assert async_filesystem_calls == [("s3://bucket/logs", {"anon": True})]
        assert sync_ls_calls == []
    else:
        # under trio the fsspec asynchronous=True path is unavailable, so the
        # listing falls back to fsspec's backend-agnostic sync API
        assert async_filesystem_calls == []
        assert sync_ls_calls == [("s3://bucket/logs", False)]
    assert len(logs) == 1
    assert logs[0].name == "s3://bucket/logs/2026-01-01T00-00-00_task_id.eval"
    assert logs[0].task == "task"
    assert logs[0].task_id == "id"


async def test_list_eval_logs_async_s3_missing_bucket_returns_empty(
    mock_s3: None,
) -> None:
    logs = await list_eval_logs_async("s3://no-such-bucket/logs")
    assert logs == []


async def test_list_eval_logs_async_s3_lists_logs(mock_s3: None) -> None:
    s3_log = (
        "s3://test-bucket/list-fast-path/2025-01-01T00-00-00+00-00_task_taskid.eval"
    )
    await _write_eval_log_to_s3_async(s3_log)
    logs = await list_eval_logs_async("s3://test-bucket/list-fast-path")
    assert [log.name for log in logs] == [s3_log]


# ═══════════════════════════════════════════════════════════════════════════
# Tests using memory:// + AccessPolicy / FileMappingPolicy
# ═══════════════════════════════════════════════════════════════════════════


def write_fake_eval_log(file_path: str) -> None:
    full_file_path = f"memory://{file_path}"
    eval_log = inspect_ai.log.EvalLog(
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="task",
            task_id="task_id",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        )
    )
    inspect_ai.log.write_eval_log(eval_log, full_file_path, "eval")


def write_fake_eval_log_buffer(
    eval_file_name: str,
    num_segments: int = 0,
) -> None:
    eval_set_id, eval_file_name = eval_file_name.split("/")
    buffer_base_path = f"memory://{eval_set_id}/.buffer/{eval_file_name.split('.')[0]}"
    samples = [
        inspect_ai.log._recorders.buffer.filestore.SampleManifest(
            summary=inspect_ai.log.EvalSampleSummary(
                id="id",
                epoch=0,
                input="hello",
                target="target",
            ),
            segments=[i for i in range(num_segments)],
        )
    ]
    segments = [
        inspect_ai.log._recorders.buffer.filestore.Segment(
            id=i,
            last_event_id=i + 1,
            last_attachment_id=i + 1,
        )
        for i in range(num_segments)
    ]
    manifest = inspect_ai.log._recorders.buffer.filestore.Manifest(
        metrics=[],
        samples=samples,
        segments=segments,
    )
    with cast(
        ContextManager[TextIO],
        fsspec.open(f"{buffer_base_path}/manifest.json", "w", encoding="utf-8"),
        # pyright: ignore[reportUnknownMemberType]
    ) as f:
        f.write(manifest.model_dump_json())
    for i in range(num_segments):
        sample = inspect_ai.log._recorders.buffer.SampleData(  # pyright: ignore[reportPrivateImportUsage]
            events=[
                inspect_ai.log._recorders.buffer.EventData(  # pyright: ignore[reportPrivateImportUsage]
                    id=1,
                    event_id="event_id",
                    sample_id="sample_id",
                    epoch=0,
                    event={"message": f"event {i}"},
                )
            ],
            attachments=[],
        )
        with cast(
            ContextManager[IO[bytes]],
            fsspec.open(f"{buffer_base_path}/segment.{i}.zip", "wb"),  # pyright: ignore[reportUnknownMemberType]
        ) as f:
            with zipfile.ZipFile(f, mode="w") as zip:
                zip.writestr("id_0.json", sample.model_dump_json())


@pytest.fixture
def mock_s3_eval_file() -> str:
    file_path = "mocked_eval_set/2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_fake_eval_log(file_path)
    return file_path


@pytest.fixture
def test_client() -> Generator[TestClient, Any, None]:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
        )
    ) as client:
        yield client


@pytest.fixture
def test_client_with_restrictive_access() -> Generator[TestClient, Any, None]:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    class access_policy(AccessPolicy):
        async def can_read(self, request: Request, file: str) -> bool:
            return True

        async def can_delete(self, request: Request, file: str) -> bool:
            return False

        async def can_list(self, request: Request, dir: str) -> bool:
            return dir is not None and dir != "" and dir != "/"

        async def can_write(self, request: Request, file: str) -> bool:
            return False

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            access_policy=access_policy(),
        )
    ) as client:
        yield client


def test_fastapi_log_delete_forbidden(
    test_client_with_restrictive_access: TestClient, mock_s3_eval_file: str
) -> None:
    response = test_client_with_restrictive_access.request(
        "DELETE",
        f"/log-delete/{mock_s3_eval_file}",
        headers=FRONTEND_REQUEST_HEADERS,
    )
    assert response.status_code == 403
    assert inspect_ai._util.file.filesystem("memory://").exists(mock_s3_eval_file)


def test_fastapi_log_edit_forbidden(
    test_client_with_restrictive_access: TestClient, mock_s3_eval_file: str
) -> None:
    response = test_client_with_restrictive_access.request(
        "POST",
        f"/log-edit/{mock_s3_eval_file}",
        headers=FRONTEND_REQUEST_HEADERS,
        json={
            "edits": [{"type": "tags", "tags_add": ["x"], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize("bad_log_dir", [None, "", "/"])
def test_fastapi_logs_forbidden(
    test_client_with_restrictive_access: TestClient, bad_log_dir: str | None
) -> None:
    response = test_client_with_restrictive_access.request(
        "GET",
        f"/logs?log_dir={bad_log_dir}" if bad_log_dir is not None else "/logs",
    )
    assert response.status_code == 403


def test_fastapi_pending_samples_no_buffer(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    assert response.status_code == 404


def test_fastapi_pending_samples_etag(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
    write_fake_eval_log_buffer(mock_s3_eval_file)
    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    response.raise_for_status()
    body = response.json()
    assert "etag" in body
    assert "samples" in body

    etag = body["etag"]
    response2 = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
        headers={"If-None-Match": etag},
    )
    assert response2.status_code == 304


def test_fastapi_sample_events(test_client: TestClient, mock_s3_eval_file: str) -> None:
    write_fake_eval_log_buffer(mock_s3_eval_file, 1)
    response = test_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(mock_s3_eval_file)}&id=id&epoch=0",
    )
    response.raise_for_status()
    assert len(response.json()["events"]) == 1


def test_fastapi_eval_set(test_client: TestClient) -> None:
    eval_set_id = "eval_set_id"
    eval_set_dir = f"memory://{eval_set_id}"
    fs = inspect_ai._util.file.filesystem(eval_set_dir)
    fs.mkdir(eval_set_dir)
    inspect_ai._eval.evalset.write_eval_set_info(
        eval_set_id=eval_set_id,
        log_dir=eval_set_dir,
        tasks=[
            inspect_ai._eval.task.resolved.ResolvedTask(
                id="task_id",
                task=inspect_ai._eval.task.Task(
                    name="task-name",
                    dataset=inspect_ai.dataset.MemoryDataset(
                        samples=[
                            inspect_ai.dataset.Sample(input="input", target="target")
                        ],
                    ),
                ),
                sandbox=None,
                checkpoint=None,
                task_file="task_file",
                task_args={},
                model=inspect_ai.model.get_model("mockllm/model"),
                model_roles={},
                sequence=0,
            )
        ],
        all_logs=[],
        eval_set_args=inspect_ai._eval.evalset.EvalSetArgsInTaskIdentifier(
            config=GenerateConfig()
        ),
    )
    response = test_client.request("GET", f"/eval-set?dir={eval_set_id}")
    response.raise_for_status()
    data = response.json()
    assert data["eval_set_id"] == eval_set_id
    assert data["tasks"][0]["name"] == "task-name"


def test_fastapi_log_download_forbidden(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
    class no_read_policy(AccessPolicy):
        async def can_read(self, request: Request, file: str) -> bool:
            return False

        async def can_delete(self, request: Request, file: str) -> bool:
            return False

        async def can_list(self, request: Request, dir: str) -> bool:
            return True

        async def can_write(self, request: Request, file: str) -> bool:
            return False

    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            access_policy=no_read_policy(),
        )
    ) as restricted_client:
        response = restricted_client.request(
            "GET", f"/log-download/{mock_s3_eval_file}"
        )
        assert response.status_code == 403


def test_fastapi_log_info_no_direct_url_for_non_s3(mock_s3_eval_file: str) -> None:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            generate_direct_urls=True,
        )
    ) as client:
        response = client.request("GET", f"/log-info/{mock_s3_eval_file}")
        response.raise_for_status()
        assert "direct_url" not in response.json()


def test_fastapi_authorization_middleware() -> None:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    api = fastapi_server.view_server_app(mapping_policy=mapping_policy())
    from fastapi import FastAPI

    inner = FastAPI()
    inner.mount("/api", api)
    app = fastapi_server.ViewAuthorizationMiddleware(inner, "Bearer secret123")

    with fastapi.testclient.TestClient(app) as client:
        assert client.request("GET", "/api/events").status_code == 401
        assert (
            client.request(
                "GET", "/api/events", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert (
            client.request(
                "GET", "/api/events", headers={"Authorization": "Bearer secret123"}
            ).status_code
            == 200
        )


def test_fastapi_nan_metric(test_client: TestClient) -> None:
    file_path = "nan_test/2025-01-01T00-00-00+00-00_nantest_nanid.eval"
    full_path = f"memory://{file_path}"
    eval_log = inspect_ai.log.EvalLog(
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="nantest",
            task_id="nanid",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        ),
        results=inspect_ai.log.EvalResults(
            scores=[
                inspect_ai.log.EvalScore(
                    name="accuracy",
                    scorer="my_scorer",
                    metrics={
                        "accuracy": inspect_ai.log.EvalMetric(
                            name="accuracy", value=float("nan")
                        ),
                        "inf_metric": inspect_ai.log.EvalMetric(
                            name="inf_metric", value=float("inf")
                        ),
                    },
                )
            ]
        ),
    )
    inspect_ai.log.write_eval_log(eval_log, full_path, "eval")
    response = test_client.request("GET", f"/logs/{file_path}")
    response.raise_for_status()
    scores = response.json()["results"]["scores"]
    assert math.isnan(scores[0]["metrics"]["accuracy"]["value"])
    assert math.isinf(scores[0]["metrics"]["inf_metric"]["value"])


def test_fastapi_only_dir_access_policy() -> None:
    policy = fastapi_server.OnlyDirAccessPolicy("/allowed/dir")
    assert asyncio.run(policy.can_read(None, "/allowed/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/other/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/allowed/directory/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/allowed/dir/../etc/passwd"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "unsupported://dir/file.eval"))  # type: ignore[arg-type]


def test_normalize_uri_preserves_windows_drive() -> None:
    windows_uri = "file://C:/Users/example/logs/run.eval"
    assert normalize_uri(windows_uri) == windows_uri
    assert normalize_uri("file:///C:/Users/example/logs/run.eval") == windows_uri
    assert normalize_uri(urllib.parse.quote(windows_uri, safe="")) == windows_uri
    assert normalize_uri("file://c:/Users/example/logs/run.eval") == (
        "file://c:/Users/example/logs/run.eval"
    )


def test_fastapi_only_dir_access_policy_accepts_listed_file_uri(
    tmp_path: Path,
) -> None:
    log_file = write_eval_log(tmp_path, "run.eval")
    fs = inspect_ai._util.file.filesystem(log_file)
    listed_uri = fs.path_as_uri(fs.fs._strip_protocol(log_file))

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            default_dir=str(tmp_path),
            access_policy=fastapi_server.OnlyDirAccessPolicy(str(tmp_path)),
        )
    ) as client:
        encoded_uri = urllib.parse.quote(listed_uri, safe="")
        response = client.get(f"/logs/{encoded_uri}")

    assert response.status_code == 200


def test_fastapi_only_dir_policy_integration(mock_s3_eval_file: str) -> None:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            access_policy=fastapi_server.OnlyDirAccessPolicy("mocked_eval_set"),
        )
    ) as client:
        assert client.request("GET", f"/logs/{mock_s3_eval_file}").status_code == 200
        assert client.request("GET", "/logs/other_dir/file.eval").status_code == 403


def test_fastapi_inspect_json_response_nan() -> None:
    resp = fastapi_server.InspectJsonResponse(
        content={"val": float("nan"), "inf": float("inf"), "neg_inf": float("-inf")}
    )
    assert isinstance(resp.body, bytes)
    body = resp.body.decode("utf-8")
    assert "NaN" in body
    assert "Infinity" in body
    assert "-Infinity" in body


def test_fastapi_log_bytes_beyond_file_size(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
    size_response = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    size_response.raise_for_status()
    file_size = size_response.json()["size"]
    response = test_client.request(
        "GET", f"/log-bytes/{mock_s3_eval_file}?start=0&end={file_size + 1000}"
    )
    response.raise_for_status()
    assert len(response.content) == file_size
    if "Content-Length" in response.headers:
        assert int(response.headers["Content-Length"]) == len(response.content)


def test_fastapi_log_bytes_start_beyond_file_size(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
    size_response = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    size_response.raise_for_status()
    file_size = size_response.json()["size"]
    response = test_client.request(
        "GET",
        f"/log-bytes/{mock_s3_eval_file}?start={file_size + 100}&end={file_size + 200}",
    )
    assert response.status_code == 416


# ═══════════════════════════════════════════════════════════════════════════
# Misc FastAPI server tests
# ═══════════════════════════════════════════════════════════════════════════


def test_log_size_endpoint(test_client: TestClient, mock_s3_eval_file: str) -> None:
    """GET /log-size/{log} returns file size as a JSON int."""
    response = test_client.request("GET", f"/log-size/{mock_s3_eval_file}")
    assert response.status_code == 200
    size = response.json()
    assert isinstance(size, int)
    assert size > 0


def test_flow_uses_map_file(test_client: TestClient) -> None:
    """/flow resolves directories through _map_file (like /eval-set)."""
    flow_dir = "memory://flow_mapped_dir"
    fs = inspect_ai._util.file.filesystem(flow_dir)
    fs.mkdir(flow_dir)
    with cast(
        ContextManager[IO[bytes]],
        fsspec.open(f"{flow_dir}/flow.yaml", "wb"),
    ) as f:
        f.write(b"steps:\n  - name: mapped_step\n")
    response = test_client.request("GET", "/flow?dir=flow_mapped_dir")
    response.raise_for_status()
    assert "mapped_step" in response.text


def test_generate_direct_urls_wired() -> None:
    """FastAPI view_server() accepts and forwards generate_direct_urls."""
    import inspect

    sig = inspect.signature(fastapi_server.view_server)
    assert "generate_direct_urls" in sig.parameters


def test_log_read_missing_file_returns_404(test_client: TestClient) -> None:
    """Reading a nonexistent log file returns 404."""
    response = test_client.request("GET", "/logs/nonexistent/file.eval")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("/log-size/{path}", id="log-size"),
        pytest.param("/log-info/{path}", id="log-info"),
    ],
)
def test_missing_file_returns_404_not_500(
    view_client: ViewTestClient, endpoint: str
) -> None:
    """Endpoints return 404 (not 500) when the log file has been deleted."""
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    Path(full_path).unlink()
    url = endpoint.replace("{path}", full_path)
    resp = view_client.request("GET", url)
    assert resp.status_code == 404


def test_get_direct_url_returns_none_for_local_path(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi")
    assert asyncio.run(get_direct_url(str(f))) is None


def test_get_direct_url_returns_url_for_s3(mock_s3: None) -> None:
    path = "s3://test-bucket/example.bin"
    with cast(
        ContextManager[IO[bytes]],
        fsspec.open(path, "wb"),
    ) as f:
        f.write(b"hi")

    url = asyncio.run(get_direct_url(path))
    assert url is not None
    assert url.startswith("http")
    assert "test-bucket" in url


# ═══════════════════════════════════════════════════════════════════════════
# /pending-sample-data-urls tests
# ═══════════════════════════════════════════════════════════════════════════


def test_api_pending_sample_data_urls_no_buffer(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=x&epoch=0",
    )
    assert resp.status_code == 404


def test_api_pending_sample_data_urls_local_has_null_direct_url(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert len(body["segments"]) >= 1
    for seg in body["segments"]:
        assert seg["direct_url"] is None
        assert seg["member_name"] == "sample1_0.json"


def test_api_pending_sample_data_urls_prunes_by_cursor(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_multi_segment_sample_buffer(full_path, num_segments=3)
    # Segments are constructed with last_event_id=i+1 and
    # last_attachment_id=0, so only segment 2 (last_event_id=3) has any
    # dimension above the cursors below.
    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0"
        "&last-event-id=2&after-attachment-id=0"
        "&after-message-pool-id=0&after-call-pool-id=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert [s["id"] for s in body["segments"]] == [2]


def test_api_pending_sample_data_urls_has_more_default_false(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer(full_path)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["has_more"] is False


def test_api_pending_sample_data_urls_truncates_to_max_segments(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_multi_segment_sample_buffer(full_path, num_segments=3)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0&max-segments=2",
    )
    resp.raise_for_status()
    body = resp.json()
    assert [s["id"] for s in body["segments"]] == [0, 1]
    assert body["has_more"] is True


def test_api_pending_sample_data_urls_max_segments_exact_fit(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_multi_segment_sample_buffer(full_path, num_segments=3)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0&max-segments=3",
    )
    resp.raise_for_status()
    body = resp.json()
    assert [s["id"] for s in body["segments"]] == [0, 1, 2]
    assert body["has_more"] is False


def test_api_pending_sample_data_urls_numeric_id_stored_as_int(
    view_client: ViewTestClient,
) -> None:
    # Sample.id is `int | str` and round-trips with whichever type was
    # written; URL params are always str. The handler must match either.
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer_with_id(full_path, sample_id=42)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=42&epoch=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["member_name"] == "42_0.json"


def test_api_pending_sample_data_urls_numeric_id_stored_as_str(
    view_client: ViewTestClient,
) -> None:
    # Counterpart of the int case: when Sample.id was constructed from a
    # numeric string, the manifest stores `"0"`. A naive `int(id)` coercion
    # would miss this and 404, sending the client to the slow proxy path.
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_sample_buffer_with_id(full_path, sample_id="0")

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=0&epoch=0",
    )
    resp.raise_for_status()
    body = resp.json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["member_name"] == "0_0.json"


def test_api_pending_sample_data_urls_tail_returns_last_n(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_multi_segment_sample_buffer(full_path, num_segments=5)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0&tail=true&max-segments=2",
    )
    resp.raise_for_status()
    body = resp.json()
    assert [s["id"] for s in body["segments"]] == [3, 4]
    assert body["has_more"] is False


def test_api_pending_sample_data_urls_tail_without_cap_returns_all(
    view_client: ViewTestClient,
) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    _create_multi_segment_sample_buffer(full_path, num_segments=3)

    resp = view_client.request(
        "GET",
        f"/pending-sample-data-urls?log={urllib.parse.quote_plus(full_path)}"
        "&id=sample1&epoch=0&tail=true",
    )
    resp.raise_for_status()
    body = resp.json()
    assert [s["id"] for s in body["segments"]] == [0, 1, 2]
    assert body["has_more"] is False


def _make_s3_eval_log(status: str = "success") -> inspect_ai.log.EvalLog:
    return inspect_ai.log.EvalLog(
        status=status,  # type: ignore[arg-type]
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="task",
            task_id="task_id",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        ),
    )


def _write_eval_log_to_s3(s3_path: str, status: str = "success") -> None:
    """Write a minimal eval log to an s3:// path. Uses the moto-mocked bucket.

    Defaults to a finished log (``status="success"``) so edit tests pass
    the in-progress gate; override for tests that need a running log.
    """
    inspect_ai.log.write_eval_log(_make_s3_eval_log(status), s3_path, "eval")


async def _write_eval_log_to_s3_async(s3_path: str, status: str = "success") -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("header.json", to_json_safe(_make_s3_eval_log(status), indent=None))
    async with AsyncFilesystem() as fs:
        await fs.write_file(s3_path, buffer.getvalue())


def test_api_log_returns_etag_header_for_s3(mock_s3: None, tmp_path: Path) -> None:
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_read.eval"
    _write_eval_log_to_s3(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        resp = client.request("GET", f"/logs/{s3_log}")
        resp.raise_for_status()
        assert resp.headers.get("etag") is not None
        assert resp.headers["etag"] != ""
    finally:
        client.close()


def test_api_log_no_etag_header_for_local(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("logs", fname))
    resp.raise_for_status()
    assert "etag" not in resp.headers


def test_api_log_info_returns_etag_for_s3(mock_s3: None, tmp_path: Path) -> None:
    """`get_log_info` should expose the S3 ETag so the client can prime `If-Match`.

    Without this, the new ETag protection is reachable only on the
    second-and-later edit (the chained-edit fallback), and a save that races
    a concurrent external edit silently last-writer-wins.
    """
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_info.eval"
    _write_eval_log_to_s3(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        info = client.request("GET", f"/log-info/{s3_log}")
        info.raise_for_status()
        body = info.json()
        assert isinstance(body.get("etag"), str) and body["etag"]
        # Should match the ETag the read endpoint returns.
        read_resp = client.request("GET", f"/logs/{s3_log}")
        read_resp.raise_for_status()
        assert body["etag"] == read_resp.headers["etag"]
    finally:
        client.close()


def test_api_log_info_no_etag_for_local(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("log-info", fname))
    resp.raise_for_status()
    body = resp.json()
    # Local filesystem has no ETag concept; the field should be omitted.
    assert "etag" not in body or body["etag"] is None


def test_api_log_edit_s3_returns_new_etag(mock_s3: None, tmp_path: Path) -> None:
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_edit.eval"
    _write_eval_log_to_s3(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        # Read once to capture current ETag.
        read_resp = client.request("GET", f"/logs/{s3_log}")
        read_resp.raise_for_status()
        original_etag = read_resp.headers["etag"]

        # Edit with matching If-Match — should succeed and return a new ETag.
        edit_resp = client.frontend_request(
            "POST",
            f"/log-edit/{s3_log}",
            headers={"If-Match": original_etag},
            json={
                "edits": [
                    {"type": "tags", "tags_add": ["qa_passed"], "tags_remove": []}
                ],
                "provenance": {"author": "alice"},
            },
        )
        edit_resp.raise_for_status()
        new_etag = edit_resp.headers.get("etag")
        assert new_etag is not None
        assert new_etag != original_etag

        # A follow-up GET should return the new ETag.
        confirm_resp = client.request("GET", f"/logs/{s3_log}")
        confirm_resp.raise_for_status()
        assert confirm_resp.headers["etag"] == new_etag
        assert confirm_resp.json()["tags"] == ["qa_passed"]
    finally:
        client.close()


def test_api_log_edit_returns_atomic_write_etag_during_race(
    mock_s3: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edit response must identify its write, not a later S3 object."""
    from inspect_ai.log._recorders import eval as eval_recorder

    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_race.eval"
    _write_eval_log_to_s3(s3_log)
    original_put = eval_recorder._s3_put_object
    later_etag = None

    async def racing_put(async_fs, bucket, key, body, etag):
        nonlocal later_etag
        write_etag = await original_put(async_fs, bucket, key, body, etag)
        if etag is not None:
            client = await async_fs.s3_client_async()
            response = await client.put_object(
                Bucket=bucket, Key=key, Body=b"concurrent writer"
            )
            later_etag = str(response["ETag"]).strip('"')
        return write_etag

    monkeypatch.setattr(eval_recorder, "_s3_put_object", racing_put)

    client = ViewTestClient(tmp_path)
    try:
        read_resp = client.request("GET", f"/logs/{s3_log}")
        read_resp.raise_for_status()
        edit_resp = client.frontend_request(
            "POST",
            f"/log-edit/{s3_log}",
            headers={"If-Match": read_resp.headers["etag"]},
            json={
                "edits": [
                    {"type": "tags", "tags_add": ["writer_a"], "tags_remove": []}
                ],
                "provenance": {"author": "alice"},
            },
        )

        edit_resp.raise_for_status()
        assert later_etag is not None
        assert edit_resp.headers["etag"] != later_etag
    finally:
        client.close()


def test_api_log_edit_s3_stale_if_match_returns_412(
    mock_s3: None, tmp_path: Path
) -> None:
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_stale.eval"
    _write_eval_log_to_s3(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        read_resp = client.request("GET", f"/logs/{s3_log}")
        read_resp.raise_for_status()
        original_etag = read_resp.headers["etag"]

        # First edit succeeds (consumes the ETag).
        first = client.frontend_request(
            "POST",
            f"/log-edit/{s3_log}",
            headers={"If-Match": original_etag},
            json={
                "edits": [{"type": "tags", "tags_add": ["a"], "tags_remove": []}],
                "provenance": {"author": "alice"},
            },
        )
        first.raise_for_status()

        # Second edit with the now-stale ETag should 412.
        second = client.frontend_request(
            "POST",
            f"/log-edit/{s3_log}",
            headers={"If-Match": original_etag},
            json={
                "edits": [{"type": "tags", "tags_add": ["b"], "tags_remove": []}],
                "provenance": {"author": "bob"},
            },
        )
        assert second.status_code == 412

        # The stale write must not have been applied.
        confirm = client.request("GET", f"/logs/{s3_log}")
        confirm.raise_for_status()
        assert confirm.json()["tags"] == ["a"]
    finally:
        client.close()


def test_api_log_edit_s3_without_if_match_succeeds(
    mock_s3: None, tmp_path: Path
) -> None:
    """Omitting If-Match falls back to last-writer-wins (no conditional check).

    Matches the existing behavior of `write_eval_log(..., if_match_etag=None)`.
    """
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_etag_optional.eval"
    _write_eval_log_to_s3(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        resp = client.frontend_request(
            "POST",
            f"/log-edit/{s3_log}",
            json={
                "edits": [{"type": "tags", "tags_add": ["x"], "tags_remove": []}],
                "provenance": {"author": "alice"},
            },
        )
        resp.raise_for_status()
        # ETag still surfaced on the response so the client can switch to
        # conditional writes on the next round-trip.
        assert resp.headers.get("etag") is not None
    finally:
        client.close()


def test_api_pending_sample_data_urls_s3_populates_direct_url(
    mock_s3: None, tmp_path: Path
) -> None:
    s3_log = "s3://test-bucket/2025-01-01T00-00-00+00-00_task_taskid.eval"
    eval_log = inspect_ai.log.EvalLog(
        eval=inspect_ai.log.EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="task",
            task_id="task_id",
            dataset=inspect_ai.log.EvalDataset(),
            model="model",
            config=inspect_ai.log.EvalConfig(),
        )
    )
    inspect_ai.log.write_eval_log(eval_log, s3_log, "eval")
    _create_sample_buffer(s3_log)

    client = ViewTestClient(tmp_path)
    try:
        resp = client.request(
            "GET",
            f"/pending-sample-data-urls?log={urllib.parse.quote_plus(s3_log)}"
            "&id=sample1&epoch=0",
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        client.close()

    assert len(body["segments"]) == 1
    direct_url = body["segments"][0]["direct_url"]
    assert direct_url is not None
    assert direct_url.startswith("http")
    assert "test-bucket" in direct_url


async def test_get_log_bytes_local_does_not_block_event_loop(tmp_path: Path) -> None:
    """A local byte-range read must not pin the event loop.

    `get_log_bytes` reads local files via asyncfiles' anyio-backed reader,
    so a large read yields to the loop instead of running to completion in
    one blocking `fs.read_bytes`. We guard that by monitoring loop lateness
    while the read runs: a blocking read stalls the loop for ~the entire
    read duration, a non-blocking one barely at all.

    The assertion is relative (stall vs. read duration) so it is
    independent of machine speed and file size. It would fail if the local
    path regressed to a synchronous read.
    """
    # Build a file large enough that a single synchronous read takes long
    # enough to dwarf scheduler jitter (a 1MB buffer reused to keep the
    # write cheap and the bytes non-sparse so the read isn't elided).
    log_file = tmp_path / "big.bin"
    size = 256 * 1024 * 1024
    chunk = b"\xa5" * (1024 * 1024)
    with open(log_file, "wb") as f:
        for _ in range(size // len(chunk)):
            f.write(chunk)

    path = log_file.as_posix()

    # Warm the page cache before monitoring: a cold first read off slow disk
    # inflates read_duration with I/O wait that also skews the stall ratio.
    with open(log_file, "rb") as f:
        while f.read(len(chunk)):
            pass

    async with event_loop_monitor(interval=0.002) as stats:
        # let the monitor establish its cadence before the read starts
        await anyio.sleep(0.02)
        start = time.monotonic()
        data = await get_log_bytes(path, 0, size - 1)
        read_duration = time.monotonic() - start
        # let the monitor wake and record the post-block tick
        await anyio.sleep(0.01)

    assert len(data) == size
    # Sanity: the read must be substantial enough for the signal to mean
    # something (guards against a no-op fast path elsewhere).
    assert read_duration > 0.01, f"read too fast to be meaningful: {read_duration:.4f}s"

    # A blocking read stalls the loop for ~100% of its duration; 0.8 keeps
    # full discriminating power while tolerating GIL/scheduler contention.
    stalled_fraction = stats.max_lateness / read_duration
    assert stats.max_lateness < read_duration * 0.8, (
        f"event loop stalled {stats.max_lateness_ms:.0f}ms during a "
        f"{read_duration * 1000:.0f}ms local read "
        f"({stalled_fraction:.0%} of it) — the read is blocking the loop"
    )


async def test_event_loop_monitor_propagates_body_exception_bare() -> None:
    """Exceptions raised in the monitored block propagate unwrapped.

    anyio task groups wrap body exceptions in an ExceptionGroup; the
    monitor unwraps so callers' `except SpecificError` keeps working.
    """
    with pytest.raises(ValueError):
        async with event_loop_monitor():
            raise ValueError("boom")


async def _consume(stream: Any) -> bytes:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


async def test_stream_log_bytes_streams_large_local_file(tmp_path: Path) -> None:
    """Local files over the stream threshold are streamed, not buffered.

    Regression guard: this path previously fell through to the S3-only
    branch and raised "Expected S3FileSystem" for any local file larger
    than the threshold (notably `/log-download` of a >50MB local log).

    A low `stream_threshold_bytes` forces the streaming branch with a
    small file. The result must be an async byte stream (not a buffered
    `BytesIO`) that yields the exact file contents.
    """
    payload = bytes(range(256)) * 4096  # 1MB of non-uniform bytes
    log_file = tmp_path / "log.bin"
    log_file.write_bytes(payload)
    path = log_file.as_posix()

    # full file, threshold below the file size -> streaming branch
    stream = await stream_log_bytes(path, stream_threshold_bytes=16)
    assert not isinstance(stream, BytesIO)
    assert await _consume(stream) == payload

    # ranged read whose size exceeds the threshold also streams, returning
    # exactly the requested (inclusive) range
    ranged = await stream_log_bytes(path, 10, 99, stream_threshold_bytes=16)
    assert not isinstance(ranged, BytesIO)
    assert await _consume(ranged) == payload[10:100]


def test_api_log_download_content_length_matches_body_when_stat_is_stale(
    view_client: ViewTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content-Length must come from the actual body, not an earlier stat.

    In-progress .eval files are rewritten in place, so the size measured
    before the read can disagree with the bytes actually read. Simulate
    that race deterministically by making the endpoint's get_log_size
    over-report: the download must still succeed with the real bytes and
    a Content-Length that matches them (previously the stale size was
    stamped on the response, producing a header/body mismatch that makes
    clients abort the download).
    """
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    actual_size = Path(full_path).stat().st_size

    async def stale_get_log_size(log_file: str) -> int:
        return actual_size + 1000

    monkeypatch.setattr(fastapi_server, "get_log_size", stale_get_log_size)

    resp = view_client.request("GET", view_client.log_url("log-download", fname))
    resp.raise_for_status()
    assert len(resp.content) == actual_size
    content_length = resp.headers.get("content-length")
    if content_length is not None:
        assert int(content_length) == len(resp.content)


async def test_stream_log_bytes_local_streams_in_large_chunks(tmp_path: Path) -> None:
    """The local streaming branch must pull large chunks per receive.

    Iterating a ByteReceiveStream directly uses anyio's 64KB default —
    one worker-thread hop per 64KB, which throttles large downloads. The
    streaming branch reads 1MB per receive, so a multi-MB stream must
    yield chunks larger than 64KB (the final chunk may be short).
    """
    payload = bytes(range(256)) * (3 * 4096)  # 3MB
    log_file = tmp_path / "log.bin"
    log_file.write_bytes(payload)

    stream = await stream_log_bytes(log_file.as_posix(), stream_threshold_bytes=16)
    assert not isinstance(stream, BytesIO)
    chunks = [chunk async for chunk in stream]
    assert b"".join(chunks) == payload
    assert any(len(chunk) > 65536 for chunk in chunks), (
        f"all {len(chunks)} chunks were <= 64KB — the stream is using "
        "anyio's default receive size (one thread hop per 64KB)"
    )


async def test_stream_log_bytes_local_does_not_restat_known_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known file size must not be re-stat'ed by the read path.

    stream_log_bytes resolves the open-ended range itself, so the
    get_log_bytes it delegates to must never call get_log_size (which is
    a synchronous fs.info on the event loop for local files — previously
    every /log-download stat'ed the file twice).
    """
    payload = b"x" * 1024
    log_file = tmp_path / "log.bin"
    log_file.write_bytes(payload)

    calls = 0
    real_get_log_size = inspect_ai._view.common.get_log_size

    async def counting_get_log_size(log_file: str) -> int:
        nonlocal calls
        calls += 1
        return await real_get_log_size(log_file)

    monkeypatch.setattr(inspect_ai._view.common, "get_log_size", counting_get_log_size)

    result = await stream_log_bytes(log_file.as_posix(), log_file_size=len(payload))
    assert isinstance(result, BytesIO)
    assert result.getvalue() == payload
    assert calls == 0, (
        f"get_log_size called {calls}x despite log_file_size being supplied"
    )


async def test_stream_log_bytes_local_stale_low_size_reads_to_eof(
    tmp_path: Path,
) -> None:
    """A stale-low log_file_size must not truncate an open-ended local read.

    In-progress .eval files grow between the caller's stat and the read;
    log_file_size may only route buffered-vs-streaming, never bound the
    bytes. Simulate the race with a log_file_size smaller than the file:
    both branches must return the full current contents.
    """
    payload = bytes(range(256)) * 16  # 4KB of non-uniform bytes
    log_file = tmp_path / "grow.bin"
    log_file.write_bytes(payload)
    path = log_file.as_posix()

    # stale size below threshold -> buffered branch
    buffered = await stream_log_bytes(path, log_file_size=len(payload) // 2)
    assert isinstance(buffered, BytesIO)
    assert buffered.getvalue() == payload

    # stale size above threshold -> streaming branch
    streamed = await stream_log_bytes(
        path, log_file_size=len(payload) // 2, stream_threshold_bytes=16
    )
    assert not isinstance(streamed, BytesIO)
    assert await _consume(streamed) == payload


def test_api_log_download_returns_full_body_when_stat_is_stale_low(
    view_client: ViewTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that grows between stat and read must download in full.

    Counterpart to the stale over-report test above: an under-reported
    size is the dangerous direction, since a truncated body ships with a
    matching framework-computed Content-Length — 200 OK, silently corrupt
    .eval, nothing for the client to detect.
    """
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    actual_size = Path(full_path).stat().st_size

    async def stale_get_log_size(log_file: str) -> int:
        return actual_size // 2

    monkeypatch.setattr(fastapi_server, "get_log_size", stale_get_log_size)

    resp = view_client.request("GET", view_client.log_url("log-download", fname))
    resp.raise_for_status()
    assert resp.content == Path(full_path).read_bytes()


class _FakeBody:
    """Stands in for the aiobotocore StreamingBody handed out by stream_log_bytes."""

    def __init__(self, chunks: int = 1, release_error: bool = False) -> None:
        self.chunks = chunks
        self.release_error = release_error
        self.started = False
        self.streamed = 0
        self.released = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started = True
        for _ in range(self.chunks):
            self.streamed += 1
            yield b"chunk"

    def release(self) -> None:
        self.released += 1
        if self.release_error:
            raise ValueError("release failed")


def _asgi_scope() -> dict[str, Any]:
    # uvicorn's h11 channel sends 2.3, which takes starlette's task-group
    # branch. It never sends 2.4 for HTTP, so only 2.3 is worth pinning.
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}}


async def _idle_receive() -> Any:
    await anyio.sleep_forever()


async def _send_failing_on_response_start(message: Any) -> None:
    assert message["type"] == "http.response.start"
    raise RuntimeError("client went away")


def _patch_stream_log_bytes(monkeypatch: pytest.MonkeyPatch) -> list[_FakeBody]:
    """Replace stream_log_bytes with a fake, returning the bodies it hands out."""
    bodies: list[_FakeBody] = []

    async def fake_stream_log_bytes(*args: Any, **kwargs: Any) -> _FakeBody:
        body = _FakeBody()
        bodies.append(body)
        return body

    monkeypatch.setattr(fastapi_server, "stream_log_bytes", fake_stream_log_bytes)
    return bodies


async def test_releasing_streaming_response_releases_unstarted_body() -> None:
    """An iterator starlette never started still gets released."""
    body = _FakeBody()

    with pytest.raises(RuntimeError, match="client went away"):
        await fastapi_server.ReleasingStreamingResponse(body)(
            _asgi_scope(), _idle_receive, _send_failing_on_response_start
        )

    assert not body.started
    assert body.released == 1


async def test_releasing_streaming_response_releases_on_disconnect() -> None:
    """A disconnect cancels the iterator mid-yield, so only the response can release."""
    body = _FakeBody(chunks=1000)
    streaming = anyio.Event()

    async def send(message: Any) -> None:
        if message["type"] == "http.response.body":
            streaming.set()
            await anyio.sleep(0)

    async def receive() -> Any:
        await streaming.wait()
        return {"type": "http.disconnect"}

    with anyio.fail_after(5):
        await fastapi_server.ReleasingStreamingResponse(body)(
            _asgi_scope(), receive, send
        )

    assert body.streamed < body.chunks
    assert body.released == 1


async def test_releasing_streaming_response_does_not_mask_request_failure() -> None:
    """A failing release() must not replace whatever ended the request."""
    body = _FakeBody(release_error=True)

    with pytest.raises(RuntimeError, match="client went away"):
        await fastapi_server.ReleasingStreamingResponse(body)(
            _asgi_scope(), _idle_receive, _send_failing_on_response_start
        )

    assert body.released == 1


@pytest.mark.parametrize("endpoint", ["log-bytes", "log-download"])
def test_api_streaming_endpoints_release_body(
    endpoint: str, view_client: ViewTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both streaming endpoints must wire up ReleasingStreamingResponse."""
    bodies = _patch_stream_log_bytes(monkeypatch)
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)

    url = view_client.log_url(endpoint, fname)
    # start/end are required on log-bytes; the fake ignores the range.
    resp = view_client.request("GET", f"{url}?start=0&end=6")

    resp.raise_for_status()
    assert resp.content == b"chunk"
    assert [body.released for body in bodies] == [1]


def test_api_log_download_encodes_non_latin1_filename(
    view_client: ViewTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A log name above U+00FF must not break (or leak) the download.

    Starlette encodes headers as latin-1, so such a name would raise in the
    response constructor, after which nothing can release an acquired body.
    """
    bodies = _patch_stream_log_bytes(monkeypatch)
    fname = "2025-01-01T00-00-00+00-00_task€_taskid.eval"
    write_eval_log(view_client.log_dir, fname)

    resp = view_client.request("GET", view_client.log_url("log-download", fname))

    resp.raise_for_status()
    assert "utf-8''" in resp.headers["content-disposition"]
    assert [body.released for body in bodies] == [1]


# ═══════════════════════════════════════════════════════════════════════════
# Resolver layer: plain-policy compatibility, resolving policies, standalone
# containment, route coverage (design/viewer-scoped-authorization.md §3, §7)
# ═══════════════════════════════════════════════════════════════════════════


class _RecordingAccessPolicy(AccessPolicy):
    """A plain policy that records every string it is asked about."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str]] = []

    async def can_read(self, request: Request, file: str) -> bool:
        self.calls.append(("read", file))
        return self.allow

    async def can_delete(self, request: Request, file: str) -> bool:
        self.calls.append(("delete", file))
        return self.allow

    async def can_list(self, request: Request, dir: str) -> bool:
        self.calls.append(("list", dir))
        return self.allow

    async def can_write(self, request: Request, file: str) -> bool:
        self.calls.append(("write", file))
        return self.allow


class _RecordingMappingPolicy(FileMappingPolicy):
    def __init__(self, prefix: str = "memory://") -> None:
        self.prefix = prefix
        self.mapped: list[str] = []

    async def map(self, request: Request, file: str) -> str:
        self.mapped.append(file)
        return f"{self.prefix}{file}"

    async def unmap(self, request: Request, file: str) -> str:
        return file.removeprefix(self.prefix)


_LOG_EDIT_BODY = {"edits": [], "provenance": {"author": "alice"}}

# (method, url, headers, json body) -> the (operation, string) pairs a plain
# AccessPolicy received on `main` at 18b1348be for that request. The strings
# are written out by hand from main's route code (normalize_uri on path
# segments and /log-headers, urllib.parse.unquote on the sample query routes,
# default_dir for an absent listing location) rather than computed, so a
# change to either the routes or the helpers shows up here.
_MAIN_POLICY_STRINGS: list[
    tuple[str, str, dict[str, str], Any, list[tuple[str, str]]]
] = [
    (
        "GET",
        "/logs/mocked_eval_set/x.eval",
        {},
        None,
        [("read", "mocked_eval_set/x.eval")],
    ),
    ("GET", "/logs/s3%3A%2F%2Fb%2Fx%20y.eval", {}, None, [("read", "s3://b/x y.eval")]),
    (
        "GET",
        "/logs/file%3A%2F%2F%2Fw%2Flogs%2Fx.eval",
        {},
        None,
        [("read", "file:///w/logs/x.eval")],
    ),
    ("GET", "/logs/a%252Fb.eval", {}, None, [("read", "a/b.eval")]),
    ("GET", "/log-size/a/b.eval", {}, None, [("read", "a/b.eval")]),
    ("GET", "/log-info/a/b.eval", {}, None, [("read", "a/b.eval")]),
    ("GET", "/log-bytes/a/b.eval?start=0&end=1", {}, None, [("read", "a/b.eval")]),
    ("GET", "/log-download/a/b.eval", {}, None, [("read", "a/b.eval")]),
    (
        "DELETE",
        "/log-delete/a/b.eval",
        FRONTEND_REQUEST_HEADERS,
        None,
        [("delete", "a/b.eval")],
    ),
    (
        "POST",
        "/log-edit/a/b.eval",
        FRONTEND_REQUEST_HEADERS,
        _LOG_EDIT_BODY,
        [("write", "a/b.eval")],
    ),
    ("GET", "/log-dir", {}, None, [("list", "default/dir")]),
    ("GET", "/log-dir?log_dir=x/y", {}, None, [("list", "x/y")]),
    ("GET", "/log-files", {}, None, [("list", "default/dir")]),
    ("GET", "/log-files?log_dir=x%2Fy", {}, None, [("list", "x/y")]),
    ("GET", "/logs", {}, None, [("list", "default/dir")]),
    ("GET", "/logs?log_dir=x/y", {}, None, [("list", "x/y")]),
    ("GET", "/eval-set", {}, None, [("list", "default/dir")]),
    ("GET", "/eval-set?dir=sub", {}, None, [("list", "default/dir/sub")]),
    ("GET", "/eval-set?log_dir=x&dir=/sub", {}, None, [("list", "x/sub")]),
    ("GET", "/eval-set?log_dir=x", {}, None, [("list", "x")]),
    ("GET", "/flow", {}, None, [("list", "default/dir")]),
    ("GET", "/flow?dir=sub", {}, None, [("list", "default/dir/sub")]),
    ("GET", "/flow?log_dir=x&dir=sub", {}, None, [("list", "x/sub")]),
    (
        "GET",
        "/log-headers?file=a%2Fb.eval&file=c%2520d.eval",
        {},
        None,
        [("read", "a/b.eval"), ("read", "c d.eval")],
    ),
    ("GET", "/pending-samples?log=a%2520b.eval", {}, None, [("read", "a b.eval")]),
    (
        "POST",
        "/log-message?log_file=a%2520b.eval&message=hi",
        FRONTEND_REQUEST_HEADERS,
        None,
        [("read", "a b.eval")],
    ),
    (
        "GET",
        "/pending-sample-data?log=a%2520b.eval&id=1&epoch=0",
        {},
        None,
        [("read", "a b.eval")],
    ),
    (
        "GET",
        "/pending-sample-data-urls?log=a%2520b.eval&id=1&epoch=0",
        {},
        None,
        [("read", "a b.eval")],
    ),
]


@pytest.mark.parametrize(
    ("method", "url", "headers", "body", "expected"),
    _MAIN_POLICY_STRINGS,
    ids=[f"{m} {u}" for m, u, _, _, _ in _MAIN_POLICY_STRINGS],
)
def test_plain_policy_receives_main_strings(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any,
    expected: list[tuple[str, str]],
) -> None:
    """A plain AccessPolicy gets byte-for-byte the strings it got before the resolver."""
    policy = _RecordingAccessPolicy(allow=False)
    app = fastapi_server.view_server_app(
        mapping_policy=_RecordingMappingPolicy(),
        access_policy=policy,
        default_dir="default/dir",
    )
    with fastapi.testclient.TestClient(app) as client:
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        response = client.request(method, url, **kwargs)
    assert response.status_code == 403
    assert sorted(policy.calls) == sorted(expected)


def test_plain_policy_io_string_is_the_caller_string(mock_s3_eval_file: str) -> None:
    """With a plain policy the mapping policy receives the once-decoded caller string."""
    policy = _RecordingAccessPolicy(allow=True)
    mapping = _RecordingMappingPolicy()
    app = fastapi_server.view_server_app(mapping_policy=mapping, access_policy=policy)
    with fastapi.testclient.TestClient(app) as client:
        encoded = urllib.parse.quote(mock_s3_eval_file, safe="")
        assert client.get(f"/logs/{encoded}").status_code == 200
        assert client.get("/logs?log_dir=mocked_eval_set").status_code == 200
        assert client.get("/eval-set?dir=mocked_eval_set").status_code == 200
    assert policy.calls == [
        ("read", mock_s3_eval_file),
        ("list", "mocked_eval_set"),
        ("list", "mocked_eval_set"),
    ]
    assert mapping.mapped == [mock_s3_eval_file, "mocked_eval_set", "mocked_eval_set"]


def test_plain_policy_eval_set_rejects_escaping_child() -> None:
    """The one tightening a plain-policy deployment observes: a `..` child is 400."""
    policy = _RecordingAccessPolicy(allow=True)
    app = fastapi_server.view_server_app(
        mapping_policy=_RecordingMappingPolicy(), access_policy=policy
    )
    with fastapi.testclient.TestClient(app) as client:
        assert client.get("/eval-set?dir=valid/../other").status_code == 400
        assert client.get("/flow?log_dir=x&dir=..").status_code == 400
        assert client.get("/eval-set?dir=a%5Cb").status_code == 400
    assert policy.calls == []


class _StateSettingMiddleware:
    """Outer pure-ASGI middleware leaving an auth context on request.state, as Hawk does."""

    def __init__(self, app: Any, auth: Any) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["auth"] = self.auth
        await self.app(scope, receive, send)


class _HawkShapedMappingPolicy(FileMappingPolicy):
    base_uri = "memory://hawk-bucket"

    async def map(self, request: Request, file: str) -> str:
        return f"{self.base_uri}/{file.lstrip('/')}"

    async def unmap(self, request: Request, file: str) -> str:
        # the memory filesystem lists names as memory:///bucket/...
        return file.removeprefix(f"{self.base_uri}/").removeprefix(
            self.base_uri.replace("://", ":///") + "/"
        )


class _HawkShapedAccessPolicy(AccessPolicy):
    """Keyed on the top-level folder, reads request.state, denies listing "" and "/"."""

    def __init__(self) -> None:
        self.folders: list[str] = []

    def _folder(self, file: str) -> str:
        import posixpath

        without_bucket = file.removeprefix(f"{_HawkShapedMappingPolicy.base_uri}/")
        return posixpath.normpath(without_bucket).strip("/").split("/", 1)[0]

    async def _check(self, request: Request, file: str) -> bool:
        folder = self._folder(file)
        self.folders.append(folder)
        return folder in request.state.auth["folders"]

    async def can_read(self, request: Request, file: str) -> bool:
        return await self._check(request, file)

    async def can_delete(self, request: Request, file: str) -> bool:
        return False

    async def can_write(self, request: Request, file: str) -> bool:
        return False

    async def can_list(self, request: Request, dir: str) -> bool:
        if not dir or dir == "/":
            return False
        return await self._check(request, dir)


def test_hawk_shaped_embedder_outcomes_unchanged() -> None:
    write_fake_eval_log("hawk-bucket/valid/2025-01-01T00-00-00+00-00_task_taskid.eval")
    write_fake_eval_log(
        "hawk-bucket/invalid/2025-01-01T00-00-00+00-00_task_taskid.eval"
    )
    policy = _HawkShapedAccessPolicy()
    api = fastapi_server.view_server_app(
        mapping_policy=_HawkShapedMappingPolicy(),
        access_policy=policy,
        recursive=False,
    )
    app = _StateSettingMiddleware(api, {"folders": {"valid"}})
    log = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    with fastapi.testclient.TestClient(app) as client:
        assert client.get(f"/logs/valid/{log}").status_code == 200
        assert client.get(f"/logs//valid/{log}").status_code == 200
        assert client.get(f"/logs/invalid/{log}").status_code == 403
        assert client.get(f"/logs/valid/../invalid/{log}").status_code == 403
        # an absent listing location binds to default_dir "", which Hawk denies
        assert client.get("/logs").status_code == 403
        assert client.get("/log-dir").status_code == 403
        assert client.get("/eval-set").status_code == 403
        listing = client.get("/logs?log_dir=valid")
        assert listing.status_code == 200
        assert [f["name"] for f in listing.json()["files"]] == [f"valid/{log}"]
        assert client.get("/logs?log_dir=invalid").status_code == 403
        assert client.get("/eval-set?dir=valid").status_code == 200
        assert client.get("/eval-set?dir=/valid").status_code == 200
        assert client.get("/eval-set?dir=invalid").status_code == 403
        assert client.get("/eval-set?dir=valid/../invalid").status_code == 400
        # (the headers reader has no memory:// path, so a permitted request 404s)
        assert client.get(f"/log-headers?file=valid/{log}").status_code != 403
        assert (
            client.get(f"/log-headers?file=valid/{log}&file=invalid/{log}").status_code
            == 403
        )
        assert (
            client.request(
                "DELETE", f"/log-delete/valid/{log}", headers=FRONTEND_REQUEST_HEADERS
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/log-edit/valid/{log}",
                headers=FRONTEND_REQUEST_HEADERS,
                json=_LOG_EDIT_BODY,
            ).status_code
            == 403
        )
        config = client.get("/app-config").json()
        assert config["scoped_authorization"] is False
        assert config["scope_claim"] is None
    # the policy saw bucket-relative folders, never the mapped storage location
    assert set(policy.folders) <= {"valid", "invalid"}


class _AliasResolvingPolicy:
    """Both protocols: the server must use resolve_* and never call can_*."""

    def __init__(self, canonical: str) -> None:
        self.canonical = canonical
        self.resolved: list[tuple[str, str | None]] = []

    async def can_read(self, request: Request, file: str) -> bool:
        raise AssertionError("can_read must not be called on a resolving policy")

    async def can_delete(self, request: Request, file: str) -> bool:
        raise AssertionError("can_delete must not be called on a resolving policy")

    async def can_list(self, request: Request, dir: str) -> bool:
        raise AssertionError("can_list must not be called on a resolving policy")

    async def can_write(self, request: Request, file: str) -> bool:
        raise AssertionError("can_write must not be called on a resolving policy")

    async def resolve_read(self, request: Request, location: str) -> str:
        self.resolved.append(("read", location))
        return self.canonical

    async def resolve_write(self, request: Request, location: str) -> str:
        self.resolved.append(("write", location))
        return self.canonical

    async def resolve_delete(self, request: Request, location: str) -> str:
        self.resolved.append(("delete", location))
        return self.canonical

    async def resolve_list(self, request: Request, location: str | None) -> str:
        self.resolved.append(("list", location))
        return self.canonical


def test_resolving_policy_is_used_directly_and_its_location_is_read() -> None:
    canonical = "memory://canonical/dir/2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_fake_eval_log(canonical.removeprefix("memory://"))
    policy = _AliasResolvingPolicy(canonical)
    assert isinstance(policy, fastapi_server.ResolvingAccessPolicy)
    app = fastapi_server.view_server_app(access_policy=policy)
    with fastapi.testclient.TestClient(app) as client:
        response = client.get("/logs/alias%2Fx.eval")
        assert response.status_code == 200
        assert response.json()["eval"]["task"] == "task"
    assert policy.resolved == [("read", "alias/x.eval")]


def test_resolving_policy_default_binding_for_absent_listing(tmp_path: Path) -> None:
    write_eval_log(tmp_path, "2025-01-01T00-00-00+00-00_task_taskid.eval")
    policy = _AliasResolvingPolicy(str(tmp_path))
    app = fastapi_server.view_server_app(access_policy=policy, default_dir="/ignored")
    with fastapi.testclient.TestClient(app) as client:
        assert client.get("/logs").status_code == 200
        assert client.get("/log-dir").status_code == 200
        # a child under an absent base joins onto the policy's default binding
        assert client.get("/eval-set?dir=sub").status_code == 200
    assert policy.resolved == [
        ("list", None),
        ("list", None),
        ("list", None),
        ("list", f"{tmp_path}/sub"),
    ]


def test_access_policy_none_still_means_no_checks(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    log = write_eval_log(elsewhere, "2025-01-01T00-00-00+00-00_task_taskid.eval")
    app = fastapi_server.view_server_app(default_dir=str(tmp_path / "default"))
    with fastapi.testclient.TestClient(app) as client:
        assert client.get(f"/logs/{log}").status_code == 200
        assert client.get(f"/logs?log_dir={elsewhere}").status_code == 200


def _standalone_layout(tmp_path: Path) -> tuple[Path, str]:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sub").mkdir()
    (tmp_path / "logs-evil").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    write_eval_log(outside, "2025-01-01T00-00-00+00-00_secret_secretid.eval")
    write_eval_log(tmp_path / "logs-evil", "2025-01-01T00-00-00+00-00_evil_evilid.eval")
    log = write_eval_log(logs, "2025-01-01T00-00-00+00-00_task_taskid.eval")
    try:
        (logs / "link-out").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not supported here")
    return logs, log


def test_standalone_only_dir_policy_contains_requests(tmp_path: Path) -> None:
    """Standalone `inspect view` keeps working inside log_dir and refuses escapes."""
    logs, log = _standalone_layout(tmp_path)
    app = fastapi_server.view_server_app(
        default_dir=str(logs),
        access_policy=fastapi_server.OnlyDirAccessPolicy(str(logs)),
    )
    secret = tmp_path / "outside" / "2025-01-01T00-00-00+00-00_secret_secretid.eval"
    evil = tmp_path / "logs-evil" / "2025-01-01T00-00-00+00-00_evil_evilid.eval"
    with fastapi.testclient.TestClient(app) as client:
        # everything the viewer does inside log_dir still works
        assert client.get(f"/logs/{log}").status_code == 200
        assert (
            client.get(
                f"/logs/{urllib.parse.quote(Path(log).as_uri(), safe='')}"
            ).status_code
            == 200
        )
        assert client.get(f"/log-size/{log}").status_code == 200
        assert client.get(f"/log-info/{log}").status_code == 200
        assert client.get(f"/log-bytes/{log}?start=0&end=10").status_code == 200
        assert client.get(f"/log-download/{log}").status_code == 200
        assert (
            client.get(
                f"/log-headers?file={urllib.parse.quote(log, safe='')}"
            ).status_code
            == 200
        )
        assert client.get("/logs").status_code == 200
        assert client.get(f"/logs?log_dir={logs}").status_code == 200
        assert client.get(f"/logs?log_dir={logs}/").status_code == 200
        single = client.get(f"/logs?log_dir={urllib.parse.quote(log, safe='')}")
        assert single.status_code == 200 and len(single.json()["files"]) == 1
        assert client.get("/log-dir").status_code == 200
        assert client.get("/log-files").status_code == 200
        assert client.get("/eval-set").status_code == 200
        assert client.get("/eval-set?dir=sub").status_code == 200
        assert client.get("/flow?dir=sub").status_code == 404
        assert (
            client.get(
                f"/pending-samples?log={urllib.parse.quote(log, safe='')}"
            ).status_code
            == 404
        )
        assert client.get(f"/logs?log_dir={logs}/not-yet-created").status_code != 403
        edited = client.post(
            f"/log-edit/{log}", headers=FRONTEND_REQUEST_HEADERS, json=_LOG_EDIT_BODY
        )
        assert edited.status_code == 200

        # escapes are refused
        assert client.get(f"/logs/{secret}").status_code == 403
        assert client.get(f"/logs/{evil}").status_code == 403
        assert client.get(f"/logs/{logs}/link-out/{secret.name}").status_code == 403
        assert client.get(f"/logs/{logs}/../outside/{secret.name}").status_code == 403
        assert client.get(f"/logs?log_dir={tmp_path / 'logs-evil'}").status_code == 403
        assert client.get(f"/logs?log_dir={logs}/link-out").status_code == 403
        assert (
            client.get(
                f"/log-headers?file={urllib.parse.quote(log, safe='')}&file={urllib.parse.quote(str(secret), safe='')}"
            ).status_code
            == 403
        )
        assert client.get("/eval-set?dir=../outside").status_code == 400
        assert client.get("/flow?dir=../outside").status_code == 400
        assert client.get(f"/eval-set?log_dir={tmp_path}").status_code == 403
        assert (
            client.request(
                "DELETE", f"/log-delete/{secret}", headers=FRONTEND_REQUEST_HEADERS
            ).status_code
            == 403
        )
        assert secret.exists()
        assert (
            client.request(
                "DELETE", f"/log-delete/{log}", headers=FRONTEND_REQUEST_HEADERS
            ).status_code
            == 200
        )
        assert not Path(log).exists()


def test_only_dir_policy_can_methods_use_the_canonicalizer(tmp_path: Path) -> None:
    logs, log = _standalone_layout(tmp_path)
    policy = fastapi_server.OnlyDirAccessPolicy(str(logs))
    request = cast(Request, None)
    assert asyncio.run(policy.can_read(request, log))
    assert asyncio.run(policy.can_list(request, str(logs)))
    assert not asyncio.run(policy.can_read(request, str(logs / "link-out" / "x.eval")))
    assert not asyncio.run(
        policy.can_read(request, str(tmp_path / "logs-evil" / "x.eval"))
    )
    assert not asyncio.run(policy.can_write(request, str(logs / ".." / "x.eval")))


def test_standalone_only_dir_policy_over_s3(mock_s3: None) -> None:
    """The canonicalizer confines an S3 log_dir; one permitted read, then denials.

    A single S3 I/O per TestClient: a second aiobotocore call in this harness
    trips over a client bound to a closed loop. Listing over a remote root is
    covered by the memory:// test below.
    """
    root = "s3://test-bucket/scoped-logs"
    inside = f"{root}/2025-01-01T00-00-00+00-00_task_taskid.eval"
    sibling = (
        "s3://test-bucket/scoped-logs-evil/2025-01-01T00-00-00+00-00_task_taskid.eval"
    )
    _write_eval_log_to_s3(inside)
    _write_eval_log_to_s3(sibling)
    app = fastapi_server.view_server_app(
        default_dir=root, access_policy=fastapi_server.OnlyDirAccessPolicy(root)
    )

    def q(location: str) -> str:
        return urllib.parse.quote(location, safe="")

    with fastapi.testclient.TestClient(app) as client:
        assert client.get(f"/logs/{q(inside)}").status_code == 200
        assert client.get(f"/logs/{q(sibling)}").status_code == 403
        assert client.get(f"/log-bytes/{q(sibling)}?start=0&end=10").status_code == 403
        assert (
            client.get(f"/logs/{q(root + '/../scoped-logs-evil/x.eval')}").status_code
            == 403
        )
        assert (
            client.get(f"/logs/{q('s3://other-bucket/scoped-logs/x.eval')}").status_code
            == 403
        )
        assert (
            client.get("/logs?log_dir=s3://test-bucket/scoped-logs-evil").status_code
            == 403
        )
        assert client.get("/logs?log_dir=s3://test-bucket").status_code == 403


def test_standalone_only_dir_policy_over_remote_listing() -> None:
    """Listing and reading a remote root go through the canonicalizer too (memory://)."""
    root = "memory://scoped/logs"
    log = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_fake_eval_log(f"scoped/logs/{log}")
    write_fake_eval_log(f"scoped/logs-evil/{log}")
    app = fastapi_server.view_server_app(
        default_dir=root, access_policy=fastapi_server.OnlyDirAccessPolicy(root)
    )

    def q(location: str) -> str:
        return urllib.parse.quote(location, safe="")

    with fastapi.testclient.TestClient(app) as client:
        listing = client.get("/logs")
        assert listing.status_code == 200
        assert len(listing.json()["files"]) == 1
        assert client.get(f"/logs?log_dir={root}").status_code == 200
        assert client.get(f"/logs?log_dir={root}/").status_code == 200
        assert client.get("/logs?log_dir=memory://SCOPED/logs//").status_code == 200
        assert client.get(f"/logs/{q(root + '/' + log)}").status_code == 200
        assert client.get(f"/logs/{q(root + '//' + log)}").status_code == 200
        assert client.get("/eval-set?dir=sub").status_code == 200
        assert client.get("/logs?log_dir=memory://scoped/logs-evil").status_code == 403
        assert client.get("/logs?log_dir=memory://scoped").status_code == 403
        assert (
            client.get(f"/logs/{q('memory://scoped/logs-evil/' + log)}").status_code
            == 403
        )
        assert (
            client.get(
                f"/logs/{q('memory://scoped/logs/../logs-evil/' + log)}"
            ).status_code
            == 403
        )
        assert client.get(f"/logs/{q(root + '/' + log + '?v=1')}").status_code == 403


class _DenyAllRecordingResolver:
    def __init__(self) -> None:
        self.calls = 0

    async def _deny(self) -> str:
        self.calls += 1
        raise fastapi.HTTPException(status_code=403)

    async def resolve_read(self, request: Request, location: str) -> str:
        return await self._deny()

    async def resolve_write(self, request: Request, location: str) -> str:
        return await self._deny()

    async def resolve_delete(self, request: Request, location: str) -> str:
        return await self._deny()

    async def resolve_list(self, request: Request, location: str | None) -> str:
        return await self._deny()


# Routes that carry no location and therefore never consult the resolver.
ROUTES_WITHOUT_LOCATION: set[tuple[str, str]] = {
    ("GET", "/user-info"),
    ("GET", "/events"),
    ("GET", "/app-config"),
    ("GET", "/scout/searches"),
}

_SOME_DIR_B64 = base64.urlsafe_b64encode(b"some/dir").decode().rstrip("=")

# How to send each location-bearing route a syntactically valid location.
_ROUTE_REQUESTS: dict[tuple[str, str], tuple[str, dict[str, str], Any]] = {
    ("GET", "/logs/{log:path}"): ("/logs/some/file.eval", {}, None),
    ("GET", "/log-size/{log:path}"): ("/log-size/some/file.eval", {}, None),
    ("GET", "/log-info/{log:path}"): ("/log-info/some/file.eval", {}, None),
    ("DELETE", "/log-delete/{log:path}"): (
        "/log-delete/some/file.eval",
        FRONTEND_REQUEST_HEADERS,
        None,
    ),
    ("POST", "/log-edit/{log:path}"): (
        "/log-edit/some/file.eval",
        FRONTEND_REQUEST_HEADERS,
        _LOG_EDIT_BODY,
    ),
    ("GET", "/log-bytes/{log:path}"): (
        "/log-bytes/some/file.eval?start=0&end=1",
        {},
        None,
    ),
    ("GET", "/log-download/{log:path}"): ("/log-download/some/file.eval", {}, None),
    ("GET", "/log-dir"): ("/log-dir?log_dir=some/dir", {}, None),
    ("GET", "/log-files"): ("/log-files?log_dir=some/dir", {}, None),
    ("GET", "/logs"): ("/logs?log_dir=some/dir", {}, None),
    ("GET", "/eval-set"): ("/eval-set?log_dir=some/dir", {}, None),
    ("GET", "/flow"): ("/flow?log_dir=some/dir", {}, None),
    ("GET", "/log-headers"): ("/log-headers?file=some/file.eval", {}, None),
    ("GET", "/pending-samples"): ("/pending-samples?log=some/file.eval", {}, None),
    ("POST", "/log-message"): (
        "/log-message?log_file=some/file.eval&message=hi",
        FRONTEND_REQUEST_HEADERS,
        None,
    ),
    ("GET", "/pending-sample-data"): (
        "/pending-sample-data?log=some/file.eval&id=1&epoch=0",
        {},
        None,
    ),
    ("GET", "/pending-sample-data-urls"): (
        "/pending-sample-data-urls?log=some/file.eval&id=1&epoch=0",
        {},
        None,
    ),
    ("POST", "/scout/transcripts/{dir}/{id}/search"): (
        f"/scout/transcripts/{_SOME_DIR_B64}/some-id/search",
        {},
        {},
    ),
    ("GET", "/scout/transcripts/{dir}/{id}/searches/{search_id}"): (
        f"/scout/transcripts/{_SOME_DIR_B64}/some-id/searches/search-1",
        {},
        None,
    ),
}


def _api_routes(app: fastapi.FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) the app serves, flattening lazily included routers."""
    found: list[tuple[str, str]] = []

    def visit(routes: list[Any], prefix: str) -> None:
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                context = getattr(route, "include_context", None)
                visit(original.routes, prefix + getattr(context, "prefix", ""))
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if (
                path is None
                or not methods
                or not isinstance(route, fastapi.routing.APIRoute)
            ):
                continue
            for method in methods:
                found.append((method, prefix + path))

    visit(list(app.routes), "")
    return sorted(found)


def test_every_route_is_classified_and_consults_the_resolver() -> None:
    """Every route either carries no location or consults the resolver.

    Adding a route forces a decision: put it in ROUTES_WITHOUT_LOCATION or
    give it a request recipe here and make it call `_resolve_*`.
    """
    resolver = _DenyAllRecordingResolver()
    app = fastapi_server.view_server_app(access_policy=resolver)
    unclassified: list[tuple[str, str]] = []
    with fastapi.testclient.TestClient(app) as client:
        for key in _api_routes(app):
            if key in ROUTES_WITHOUT_LOCATION:
                continue
            recipe = _ROUTE_REQUESTS.get(key)
            if recipe is None:
                unclassified.append(key)
                continue
            url, headers, body = recipe
            resolver.calls = 0
            kwargs: dict[str, Any] = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            response = client.request(key[0], url, **kwargs)
            assert response.status_code == 403, (key, response.status_code)
            assert resolver.calls >= 1, key
    assert not unclassified, (
        "routes carrying a location must consult the resolver and have a request "
        f"recipe in _ROUTE_REQUESTS, or be listed in ROUTES_WITHOUT_LOCATION: {unclassified}"
    )
    stale = {key for key in _ROUTE_REQUESTS if key not in set(_api_routes(app))}
    assert not stale, f"recipes for routes that no longer exist: {stale}"


def test_locations_are_decoded_only_in_the_resolver_helpers() -> None:
    """Static guard for the decode-once rule.

    `normalize_uri(` and `unquote(` may be called only inside `_decode_location`
    in fastapi_server.py; a route decoding on its own would reintroduce the
    check/use divergence the resolver layer exists to remove.
    """
    import ast

    source_path = Path(fastapi_server.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders: list[str] = []

    def callee_name(call: ast.Call) -> str | None:
        func = call.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def visit(node: ast.AST, enclosing: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = enclosing
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if isinstance(child, ast.Call) and callee_name(child) in (
                "normalize_uri",
                "unquote",
            ):
                if enclosing != "_decode_location":
                    offenders.append(f"{source_path.name}:{child.lineno}")
            visit(child, name)

    visit(tree, None)
    assert not offenders, (
        "locations must be decoded only by _decode_location (decode-once rule): "
        f"{offenders}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scoped authorization: HS256 bearer JWTs on the standalone server
# (design/viewer-scoped-authorization.md §1, §2, §5, §7)
# ═══════════════════════════════════════════════════════════════════════════

_SECRET = "d1e4c2a0-7f3b-4c9e-9a1d-2b6f8e0c5a7f"
_BASE_URL = "http://localhost:7575"


def _standalone(
    tmp_path: Path,
    *,
    secret: str | None = _SECRET,
    require_scoped: bool = False,
) -> tuple[TestClient, Path]:
    """A standalone token-mode server over tmp_path/logs, with fixture logs.

    Layout: logs/run.eval, logs/sub/inner.eval, logs/other.eval and a log
    outside the log dir at tmp_path/outside/secret.eval.
    """
    from inspect_ai._view.network import resolve_viewer_network_policy

    logs = tmp_path / "logs"
    (logs / "sub").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>viewer</html>", encoding="utf-8")
    write_eval_log(logs, "2025-01-01T00-00-00+00-00_run_runid.eval")
    write_eval_log(logs, "2025-01-01T00-00-00+00-00_other_otherid.eval")
    write_eval_log(logs / "sub", "2025-01-01T00-00-00+00-00_inner_innerid.eval")
    write_eval_log(
        tmp_path / "outside", "2025-01-01T00-00-00+00-00_secret_secretid.eval"
    )
    policy = resolve_viewer_network_policy(
        bind_host="127.0.0.1", port=7575, authorization=secret
    )
    app = fastapi_server.standalone_view_app(
        log_dir=str(logs),
        network_policy=policy,
        dist_dir=dist,
        require_scoped_authorization=require_scoped,
    )
    return TestClient(app, base_url=_BASE_URL), logs


def _mint(
    roots: list[dict[str, Any]] | None,
    *,
    secret: str = _SECRET,
    exp: int | None = int(time.time()) + 3600,
    aud: str | None = fastapi_server.VIEW_JWT_AUDIENCE,
    algorithm: str = "HS256",
    scope_override: Any = None,
    extra: dict[str, Any] | None = None,
) -> str:
    import jwt

    claims: dict[str, Any] = {"sub": "logview:test"}
    if exp is not None:
        claims["exp"] = exp
    if aud is not None:
        claims["aud"] = aud
    if scope_override is not None:
        claims["inspect_view_scope"] = scope_override
    elif roots is not None:
        claims["inspect_view_scope"] = {"v": 1, "roots": roots}
    claims.update(extra or {})
    return jwt.encode(claims, secret, algorithm=algorithm)


def _dir_root(path: Path, *permissions: str) -> dict[str, Any]:
    return {
        "uri": path.as_uri(),
        "kind": "dir",
        "permissions": list(permissions or ("read", "list")),
    }


def _file_root(path: Path, *permissions: str) -> dict[str, Any]:
    return {
        "uri": str(path),
        "kind": "file",
        "permissions": list(permissions or ("read", "list")),
    }


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _legacy() -> dict[str, str]:
    return {"Authorization": _SECRET}


def _q(location: str | Path) -> str:
    return urllib.parse.quote(str(location), safe="")


def test_scoped_legacy_credential_keeps_unscoped_behaviour(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    outside = tmp_path / "outside" / "2025-01-01T00-00-00+00-00_secret_secretid.eval"
    with client:
        assert client.get("/api/logs").status_code == 401
        assert (
            client.get("/api/logs", headers={"Authorization": "wrong"}).status_code
            == 401
        )
        assert (
            client.get(
                "/api/logs", headers={"Authorization": f"Bearer {_SECRET}"}
            ).status_code
            == 401
        )
        listing = client.get("/api/logs", headers=_legacy())
        assert listing.status_code == 200
        assert len(listing.json()["files"]) == 3
        # the legacy credential is not confined (today's token mode)
        assert (
            client.get(f"/api/logs/{_q(outside)}", headers=_legacy()).status_code == 200
        )
        assert (
            client.get(
                f"/api/logs?log_dir={_q(tmp_path / 'outside')}", headers=_legacy()
            ).status_code
            == 200
        )
        assert client.get("/api/events", headers=_legacy()).status_code == 200
        config = client.get("/api/app-config", headers=_legacy()).json()
        assert config["scoped_authorization"] is True
        assert config["scope_claim"] == "inspect_view_scope"
        assert client.get("/", headers=_legacy()).status_code == 200
        assert client.get("/").status_code == 401


def test_scoped_jwt_directory_root_confines_requests(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    token = _mint([_dir_root(logs / "sub")])
    inner = logs / "sub" / "2025-01-01T00-00-00+00-00_inner_innerid.eval"
    other = logs / "2025-01-01T00-00-00+00-00_other_otherid.eval"
    with client:
        assert (
            client.get(f"/api/logs/{_q(inner)}", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/logs/{_q(inner.as_uri())}", headers=_bearer(token)
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/log-size/{_q(inner)}", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/log-headers?file={_q(inner)}", headers=_bearer(token)
            ).status_code
            == 200
        )
        # the server's own log_dir is not the scope: an absent location binds to the root
        listing = client.get("/api/logs", headers=_bearer(token))
        assert listing.status_code == 200
        assert [Path(f["name"]).name for f in listing.json()["files"]] == [inner.name]
        assert (
            client.get("/api/log-dir", headers=_bearer(token))
            .json()["log_dir"]
            .endswith("sub")
        )
        assert client.get("/api/eval-set", headers=_bearer(token)).status_code == 200
        assert (
            client.get("/api/eval-set?dir=deeper", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/logs?log_dir={_q(logs / 'sub')}", headers=_bearer(token)
            ).status_code
            == 200
        )
        # outside the claimed root, inside the server's log_dir: refused
        assert (
            client.get(f"/api/logs/{_q(other)}", headers=_bearer(token)).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/logs?log_dir={_q(logs)}", headers=_bearer(token)
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/eval-set?log_dir={_q(logs)}", headers=_bearer(token)
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/log-headers?file={_q(inner)}&file={_q(other)}",
                headers=_bearer(token),
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/logs/{_q(logs / 'sub' / '..' / other.name)}",
                headers=_bearer(token),
            ).status_code
            == 403
        )
        # permissions not granted
        assert (
            client.post(
                f"/api/log-edit/{_q(inner)}",
                headers={**_bearer(token), **FRONTEND_REQUEST_HEADERS},
                json=_LOG_EDIT_BODY,
            ).status_code
            == 403
        )
        assert (
            client.request(
                "DELETE",
                f"/api/log-delete/{_q(inner)}",
                headers={**_bearer(token), **FRONTEND_REQUEST_HEADERS},
            ).status_code
            == 403
        )
        assert inner.exists()
        # routes without a location still need a credential but no scope
        assert client.get("/api/events", headers=_bearer(token)).status_code == 200
        assert client.get("/api/app-config", headers=_bearer(token)).status_code == 200


def test_scoped_jwt_write_and_delete_permissions(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    inner = logs / "sub" / "2025-01-01T00-00-00+00-00_inner_innerid.eval"
    writer = _mint([_dir_root(logs / "sub", "read", "list", "write")])
    deleter = _mint([_dir_root(logs / "sub", "read", "list", "delete")])
    headers = {**FRONTEND_REQUEST_HEADERS}
    with client:
        assert (
            client.post(
                f"/api/log-edit/{_q(inner)}",
                headers={**_bearer(writer), **headers},
                json=_LOG_EDIT_BODY,
            ).status_code
            == 200
        )
        assert (
            client.request(
                "DELETE",
                f"/api/log-delete/{_q(inner)}",
                headers={**_bearer(writer), **headers},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/log-edit/{_q(inner)}",
                headers={**_bearer(deleter), **headers},
                json=_LOG_EDIT_BODY,
            ).status_code
            == 403
        )
        assert (
            client.request(
                "DELETE",
                f"/api/log-delete/{_q(inner)}",
                headers={**_bearer(deleter), **headers},
            ).status_code
            == 200
        )
        assert not inner.exists()


def test_scoped_jwt_file_root(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    other = logs / "2025-01-01T00-00-00+00-00_other_otherid.eval"
    token = _mint([_file_root(run)])
    with client:
        assert (
            client.get(f"/api/logs/{_q(run)}", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/logs/{_q(run.as_uri())}", headers=_bearer(token)
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/logs/{_q(other)}", headers=_bearer(token)).status_code
            == 403
        )
        # a file root's default binding is the single-file listing the viewer probes
        listing = client.get("/api/logs", headers=_bearer(token))
        assert listing.status_code == 200
        assert [Path(f["name"]).name for f in listing.json()["files"]] == [run.name]
        assert (
            client.get(
                f"/api/logs?log_dir={_q(logs)}", headers=_bearer(token)
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/logs?log_dir={_q(run)}", headers=_bearer(token)
            ).status_code
            == 200
        )


def test_scoped_jwt_several_roots_have_no_default(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    token = _mint([_dir_root(logs / "sub"), _dir_root(tmp_path / "outside")])
    secret = tmp_path / "outside" / "2025-01-01T00-00-00+00-00_secret_secretid.eval"
    with client:
        assert client.get("/api/logs", headers=_bearer(token)).status_code == 403
        assert (
            client.get(f"/api/logs/{_q(secret)}", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/logs?log_dir={_q(logs / 'sub')}", headers=_bearer(token)
            ).status_code
            == 200
        )


def _alg_none_token(claims: dict[str, Any]) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    return (
        b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        + "."
        + b64(json.dumps(claims).encode())
        + "."
    )


def _rs256_headed_token(claims: dict[str, Any]) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    return (
        b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        + "."
        + b64(json.dumps(claims).encode())
        + "."
        + b64(b"not-a-real-signature")
    )


def _scope_claims(logs: Path) -> dict[str, Any]:
    return {
        "exp": int(time.time()) + 3600,
        "aud": fastapi_server.VIEW_JWT_AUDIENCE,
        "inspect_view_scope": {"v": 1, "roots": [_dir_root(logs)]},
    }


@pytest.mark.parametrize(
    ("name", "make_token"),
    [
        ("wrong-secret", lambda logs: _mint([_dir_root(logs)], secret="x" * 40)),
        ("alg-none", lambda logs: _alg_none_token(_scope_claims(logs))),
        ("rs256-header", lambda logs: _rs256_headed_token(_scope_claims(logs))),
        ("missing-exp", lambda logs: _mint([_dir_root(logs)], exp=None)),
        ("expired", lambda logs: _mint([_dir_root(logs)], exp=int(time.time()) - 10)),
        ("wrong-aud", lambda logs: _mint([_dir_root(logs)], aud="other-service")),
        ("missing-aud", lambda logs: _mint([_dir_root(logs)], aud=None)),
        ("missing-scope-claim", lambda logs: _mint(None)),
        ("malformed-scope-claim", lambda logs: _mint(None, scope_override="file:///w")),
        ("empty-roots", lambda logs: _mint([])),
        (
            "unknown-version",
            lambda logs: _mint(
                None, scope_override={"v": 2, "roots": [_dir_root(logs)]}
            ),
        ),
        (
            "unknown-kind",
            lambda logs: _mint(
                [{"uri": logs.as_uri(), "kind": "folder", "permissions": ["read"]}]
            ),
        ),
        (
            "http-dir-root",
            lambda logs: _mint(
                [
                    {
                        "uri": "https://example.test/logs",
                        "kind": "dir",
                        "permissions": ["read"],
                    }
                ]
            ),
        ),
        ("not-a-jwt", lambda logs: "abc"),
        ("two-segments", lambda logs: "abc.def"),
        ("garbage-segments", lambda logs: "a.b.c"),
    ],
)
def test_scoped_jwt_rejections_are_401(
    tmp_path: Path, name: str, make_token: Callable[[Path], str]
) -> None:
    client, logs = _standalone(tmp_path)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    with client:
        response = client.get(f"/api/logs/{_q(run)}", headers=_bearer(make_token(logs)))
        assert response.status_code == 401, name
        # nothing about a bad token lets a location-less route through either
        assert (
            client.get("/api/events", headers=_bearer(make_token(logs))).status_code
            == 401
        ), name


def test_scoped_jwt_duplicate_authorization_header_is_401(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    token = _mint([_dir_root(logs)])
    with client:
        response = client.get(
            "/api/events",
            headers=[("Authorization", f"Bearer {token}"), ("Authorization", _SECRET)],
        )
        assert response.status_code == 401


def test_scoped_jwt_tolerant_claim_handling(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    # unknown claim fields are ignored; unknown permissions are ignored and never grant
    token = _mint(
        None,
        scope_override={
            "v": 1,
            "roots": [
                {
                    "uri": logs.as_uri(),
                    "kind": "dir",
                    "permissions": ["read", "list", "admin"],
                }
            ],
            "future": {"x": 1},
        },
        extra={"custom": "claim", "iat": int(time.time()) - 5},
    )
    with client:
        assert (
            client.get(f"/api/logs/{_q(run)}", headers=_bearer(token)).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/log-edit/{_q(run)}",
                headers={**_bearer(token), **FRONTEND_REQUEST_HEADERS},
                json=_LOG_EDIT_BODY,
            ).status_code
            == 403
        )


def test_scoped_jwt_verified_once_then_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jwt

    client, logs = _standalone(tmp_path)
    token = _mint([_dir_root(logs)])
    calls = 0
    real_decode = jwt.decode

    def counting_decode(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_decode(*args, **kwargs)

    monkeypatch.setattr(jwt, "decode", counting_decode)
    with client:
        for _ in range(3):
            assert client.get("/api/logs", headers=_bearer(token)).status_code == 200
    assert calls == 1


def test_scoped_jwt_cache_is_bounded() -> None:
    middleware = fastapi_server.ViewAuthorizationMiddleware(
        cast(Any, None), _SECRET, cache_size=2
    )
    tokens = [
        _mint([_dir_root(Path("/w/logs"))], extra={"sub": f"panel:{i}"})
        for i in range(3)
    ]
    for token in tokens:
        assert middleware._verify(token) is not None
    assert len(middleware._cache) == 2
    assert tokens[0] not in middleware._cache


def test_scoped_jwt_expired_cache_entry_is_reverified() -> None:
    middleware = fastapi_server.ViewAuthorizationMiddleware(cast(Any, None), _SECRET)
    token = _mint([_dir_root(Path("/w/logs"))])
    assert middleware._verify(token) is not None
    exp, scope = middleware._cache[token]
    middleware._cache[token] = (time.time() - 1, scope)
    assert middleware._verify(token) is not None
    assert middleware._cache[token][0] == exp


def test_tokenless_server_rejects_jwt_and_ignores_other_headers(tmp_path: Path) -> None:
    client, logs = _standalone(tmp_path, secret=None)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    outside = tmp_path / "outside" / "2025-01-01T00-00-00+00-00_secret_secretid.eval"
    token = _mint([_dir_root(tmp_path)])
    with client:
        assert client.get(f"/api/logs/{_q(run)}").status_code == 200
        assert (
            client.get(f"/api/logs/{_q(run)}", headers=_bearer(token)).status_code
            == 401
        )
        assert (
            client.get(
                f"/api/logs/{_q(run)}", headers={"Authorization": "Basic abc"}
            ).status_code
            == 200
        )
        # token-less containment stays log_dir, JWT or not
        assert client.get(f"/api/logs/{_q(outside)}").status_code == 403
        config = client.get("/api/app-config").json()
        assert config["scoped_authorization"] is False
        assert config["scope_claim"] is None


def test_require_scoped_authorization_refuses_legacy_except_app_config(
    tmp_path: Path,
) -> None:
    client, logs = _standalone(tmp_path, require_scoped=True)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    token = _mint([_dir_root(logs)])
    with client:
        assert client.get("/api/app-config", headers=_legacy()).status_code == 200
        assert client.get("/api/logs", headers=_legacy()).status_code == 401
        assert client.get(f"/api/logs/{_q(run)}", headers=_legacy()).status_code == 401
        assert client.get("/api/events", headers=_legacy()).status_code == 401
        assert client.get("/", headers=_legacy()).status_code == 401
        assert (
            client.get(f"/api/logs/{_q(run)}", headers=_bearer(token)).status_code
            == 200
        )
        assert client.get("/api/events", headers=_bearer(token)).status_code == 200


def test_require_scoped_authorization_needs_a_secret(tmp_path: Path) -> None:
    from inspect_ai._view.network import ViewerNetworkPolicyError

    with pytest.raises(
        ViewerNetworkPolicyError, match="INSPECT_VIEW_AUTHORIZATION_TOKEN"
    ):
        _standalone(tmp_path, secret=None, require_scoped=True)


def test_token_mode_policy_without_middleware_state_is_forbidden(
    tmp_path: Path,
) -> None:
    log = write_eval_log(tmp_path, "2025-01-01T00-00-00+00-00_task_taskid.eval")
    app = fastapi_server.view_server_app(
        access_policy=fastapi_server.TokenModeAccessPolicy(str(tmp_path)),
        default_dir=str(tmp_path),
    )
    with fastapi.testclient.TestClient(app) as client:
        assert client.get(f"/logs/{_q(log)}").status_code == 403
        assert client.get("/logs").status_code == 403
        assert client.get("/app-config").json()["scoped_authorization"] is True


def test_scoped_policy_reaches_log_headers_fan_out(tmp_path: Path) -> None:
    """State set by the pure-ASGI middleware reaches tg_collect subtasks."""
    client, logs = _standalone(tmp_path)
    run = logs / "2025-01-01T00-00-00+00-00_run_runid.eval"
    other = logs / "2025-01-01T00-00-00+00-00_other_otherid.eval"
    token = _mint([_dir_root(logs)])
    with client:
        response = client.get(
            f"/api/log-headers?file={_q(run)}&file={_q(other)}", headers=_bearer(token)
        )
        assert response.status_code == 200
        assert len(response.json()) == 2


def _fake_scout_router() -> fastapi.APIRouter:
    router = fastapi.APIRouter()

    @router.get("/searches")
    async def searches() -> list[str]:
        return []

    @router.post("/transcripts/{dir}/{id}/search")
    async def search(dir: str, id: str) -> dict[str, str]:
        return {"dir": dir, "id": id}

    @router.get("/transcripts/{dir}/{id}/searches/{search_id}")
    async def search_result(dir: str, id: str, search_id: str) -> dict[str, str]:
        return {"dir": dir, "id": id, "search_id": search_id}

    return router


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_mounted_scout_routes_go_through_the_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fastapi_server, "get_scout_search_router", _fake_scout_router)
    logs = tmp_path / "logs"
    (logs / "sub").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(logs, target_is_directory=True)
    app = fastapi_server.view_server_app(
        default_dir=str(logs),
        access_policy=fastapi_server.OnlyDirAccessPolicy(str(logs)),
    )
    canonical = str(logs.resolve())
    with fastapi.testclient.TestClient(app) as client:
        # the root itself may be searched (list semantics) ...
        response = client.post(
            f"/scout/transcripts/{_b64(str(logs))}/t1/search", json={}
        )
        assert response.status_code == 200
        assert response.json() == {"dir": _b64(canonical), "id": "t1"}
        # ... and the route sees the canonical location, not the alias
        response = client.get(
            f"/scout/transcripts/{_b64(str(alias / 'sub'))}/t1/searches/s1"
        )
        assert response.status_code == 200
        assert response.json()["dir"] == _b64(f"{canonical}/sub")
        assert client.get("/scout/searches").status_code == 200
        # escapes and malformed segments
        assert (
            client.post(
                f"/scout/transcripts/{_b64(str(tmp_path))}/t1/search", json={}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/scout/transcripts/{_b64(str(logs / '..'))}/t1/search", json={}
            ).status_code
            == 403
        )
        assert (
            client.post("/scout/transcripts/not*base64/t1/search", json={}).status_code
            == 400
        )
        # non-canonical encodings (padding in the middle, stray bits) are refused
        assert (
            client.post("/scout/transcripts/YQ==YQ/t1/search", json={}).status_code
            == 400
        )
        assert (
            client.post(
                f"/scout/transcripts/{_b64(str(logs))}x/t1/search", json={}
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/scout/transcripts/{_b64(str(logs))}=/t1/search", json={}
            ).status_code
            == 200
        )


def test_mounted_scout_routes_are_confined_by_a_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fastapi_server, "get_scout_search_router", _fake_scout_router)
    client, logs = _standalone(tmp_path)
    token = _mint([_dir_root(logs / "sub")])
    with client:
        assert (
            client.post(
                f"/api/scout/transcripts/{_b64(str(logs / 'sub'))}/t/search",
                headers=_bearer(token),
                json={},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/scout/transcripts/{_b64(str(logs))}/t/search",
                headers=_bearer(token),
                json={},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/scout/transcripts/{_b64(str(logs))}/t/search",
                headers=_legacy(),
                json={},
            ).status_code
            == 200
        )
