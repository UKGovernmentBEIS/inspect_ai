"""Tests for the inspect view server."""

import asyncio
import json
import math
import urllib.parse
import zipfile
from pathlib import Path
from typing import IO, Any, ContextManager, Generator, TextIO, cast

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
from inspect_ai._view import fastapi_server
from inspect_ai._view.common import get_direct_url
from inspect_ai._view.fastapi_server import AccessPolicy, FileMappingPolicy
from inspect_ai.model._generate_config import GenerateConfig

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
        app = fastapi_server.view_server_app(default_dirs=[str(log_dir)])
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
    assert "scout_version" in config
    assert config["scout_version"] is None or isinstance(config["scout_version"], str)
    assert [d["log_dir"] for d in config["log_dirs"]] == [str(view_client.log_dir)]
    assert config["log_dirs"][0]["aliased"]


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
    resp = view_client.request("GET", view_client.log_url("log-delete", fname))
    resp.raise_for_status()
    assert not Path(full_path).exists()


def test_api_log_edit_metadata_null_value_persists(
    view_client: ViewTestClient,
) -> None:
    # End-to-end regression for the "null keys are not being saved"
    # bug. Posts a MetadataEdit with a `null` value through the live
    # log-edit endpoint, then re-reads the eval file from disk and
    # checks the key landed with value None.
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
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
    resp = view_client.request(
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
    resp = view_client.request(
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
    resp = view_client.request(
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
    resp = view_client.request(
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
    resp = view_client.request(
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

    first = view_client.request(
        "POST",
        view_client.log_url("log-edit", fname),
        json={
            "edits": [{"type": "tags", "tags_add": ["one"], "tags_remove": []}],
            "provenance": {"author": "alice"},
        },
    )
    first.raise_for_status()

    second = view_client.request(
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


def test_api_log_message(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    full_path = write_eval_log(view_client.log_dir, fname)
    resp = view_client.request(
        "GET",
        f"/log-message?log_file={urllib.parse.quote_plus(full_path)}&message=hello",
    )
    assert resp.status_code == 204


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


def test_api_eval_set_missing(view_client: ViewTestClient) -> None:
    resp = view_client.request(
        "GET",
        f"/eval-set?log_dir={urllib.parse.quote_plus(str(view_client.log_dir))}",
    )
    resp.raise_for_status()
    assert resp.json() is None


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
        "GET", f"/log-delete/{mock_s3_eval_file}"
    )
    assert response.status_code == 403
    assert inspect_ai._util.file.filesystem("memory://").exists(mock_s3_eval_file)


def test_fastapi_log_edit_forbidden(
    test_client_with_restrictive_access: TestClient, mock_s3_eval_file: str
) -> None:
    response = test_client_with_restrictive_access.request(
        "POST",
        f"/log-edit/{mock_s3_eval_file}",
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

    app = FastAPI()
    app.mount("/api", api)
    app.add_middleware(fastapi_server.authorization_middleware("Bearer secret123"))

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
    policy = fastapi_server.OnlyDirAccessPolicy(["/allowed/dir"])
    assert asyncio.run(policy.can_read(None, "/allowed/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/other/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/allowed/dir/../etc/passwd"))  # type: ignore[arg-type]


def test_only_dir_access_policy_allows_any_configured_dir() -> None:
    import anyio

    from inspect_ai._view.fastapi_server import OnlyDirAccessPolicy

    policy = OnlyDirAccessPolicy(["/logs/a", "/logs/b"])
    req = None

    async def check() -> None:
        assert await policy.can_read(req, "/logs/a/run.eval") is True
        assert await policy.can_read(req, "/logs/b/run.eval") is True
        assert await policy.can_read(req, "/logs/c/run.eval") is False
        assert await policy.can_list(req, "/logs/b") is True
        assert await policy.can_read(req, "/logs/a/../../etc/passwd") is False

    anyio.run(check)


def test_fastapi_only_dir_policy_integration(mock_s3_eval_file: str) -> None:
    class mapping_policy(FileMappingPolicy):
        async def map(self, request: Request, file: str) -> str:
            return f"memory://{file}"

        async def unmap(self, request: Request, file: str) -> str:
            return file.removeprefix("memory://")

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            access_policy=fastapi_server.OnlyDirAccessPolicy(["mocked_eval_set"]),
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


def _write_eval_log_to_s3(s3_path: str, status: str = "success") -> None:
    """Write a minimal eval log to an s3:// path. Uses the moto-mocked bucket.

    Defaults to a finished log (``status="success"``) so edit tests pass
    the in-progress gate; override for tests that need a running log.
    """
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
    inspect_ai.log.write_eval_log(eval_log, s3_path, "eval")


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
        edit_resp = client.request(
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
        first = client.request(
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
        second = client.request(
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
        resp = client.request(
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
