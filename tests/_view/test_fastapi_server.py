import math
import urllib.parse
import zipfile
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
from inspect_ai._view.fastapi_server import AccessPolicy, FileMappingPolicy
from inspect_ai.model._generate_config import GenerateConfig


@pytest.fixture
def mock_s3_eval_file() -> str:
    file_path = "mocked_eval_set/2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_fake_eval_log(file_path)
    return file_path


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
            last_event_id=i,
            last_attachment_id=i,
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

    with fastapi.testclient.TestClient(
        fastapi_server.view_server_app(
            mapping_policy=mapping_policy(),
            access_policy=access_policy(),
        )
    ) as client:
        yield client


def test_api_log(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request("GET", f"/logs/{mock_s3_eval_file}")
    response.raise_for_status()
    api_log = response.json()
    assert api_log["eval"]["task"] == "task"


def test_api_log_info(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    response.raise_for_status()
    log_info = response.json()
    assert "size" in log_info
    assert log_info["size"] >= 100
    # No direct_url when generate_direct_urls is False (default)
    assert "direct_url" not in log_info


def test_api_log_info_no_direct_url_for_non_s3(mock_s3_eval_file: str):
    """generate_direct_urls=True doesn't add direct_url for non-S3 files."""

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
        log_info = response.json()
        assert "size" in log_info
        assert "direct_url" not in log_info


def test_api_log_delete(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request("GET", f"/log-delete/{mock_s3_eval_file}")
    response.raise_for_status()

    assert not inspect_ai._util.file.filesystem("memory://").exists(mock_s3_eval_file)


def test_api_log_delete_forbidden(
    test_client_with_restrictive_access: TestClient, mock_s3_eval_file: str
):
    response = test_client_with_restrictive_access.request(
        "GET", f"/log-delete/{mock_s3_eval_file}"
    )
    assert response.status_code == 403
    assert inspect_ai._util.file.filesystem("memory://").exists(mock_s3_eval_file)


def test_api_log_bytes(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request(
        "GET", f"/log-bytes/{mock_s3_eval_file}?start=0&end=99"
    )
    response.raise_for_status()
    api_log_bytes = response.content
    assert len(api_log_bytes) == 100


def test_api_log_bytes_beyond_file_size(
    test_client: TestClient, mock_s3_eval_file: str
):
    """Test that requesting bytes beyond file size returns correct Content-Length.

    This test verifies the fix for the bug where Content-Length was calculated
    from requested range (end - start + 1) rather than actual bytes returned,
    causing 'Response content shorter than Content-Length' errors.
    """
    # First, get the actual file size
    size_response = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    size_response.raise_for_status()
    file_size = size_response.json()["size"]

    requested_end = file_size + 1000
    response = test_client.request(
        "GET", f"/log-bytes/{mock_s3_eval_file}?start=0&end={requested_end}"
    )
    response.raise_for_status()

    actual_bytes = len(response.content)
    assert actual_bytes == file_size, (
        f"Should return entire file ({file_size} bytes) when end exceeds file size"
    )

    # Content-Length (if present) must match actual bytes
    if "Content-Length" in response.headers:
        content_length = int(response.headers["Content-Length"])
        assert content_length == actual_bytes


def test_api_log_bytes_start_beyond_file_size(
    test_client: TestClient, mock_s3_eval_file: str
):
    """Test that requesting bytes starting beyond file size returns 416."""
    size_response = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    size_response.raise_for_status()
    file_size = size_response.json()["size"]

    response = test_client.request(
        "GET",
        f"/log-bytes/{mock_s3_eval_file}?start={file_size + 100}&end={file_size + 200}",
    )
    assert response.status_code == 416


def test_api_log_dir(test_client: TestClient):
    response = test_client.request("GET", "/log-dir?log_dir=eval_set_dir")
    response.raise_for_status()

    api_log_dir = response.json()
    assert "log_dir" in api_log_dir
    assert api_log_dir["log_dir"] == "eval_set_dir"


def test_api_log_dir_with_non_existing_dir(test_client: TestClient):
    response = test_client.request("GET", "/log-dir?log_dir=does_not_exist")
    response.raise_for_status()

    api_logs = response.json()
    assert "log_dir" in api_logs
    assert api_logs["log_dir"] == "does_not_exist"


def test_api_logs(test_client: TestClient):
    write_fake_eval_log("eval_set_dir/2025-01-01T00-00-00+00-00_task1_taskid1.eval")
    write_fake_eval_log("eval_set_dir/2025-01-01T00-01-00+00-00_task2_taskid2.eval")
    write_fake_eval_log("eval_set_dir/2025-01-01T00-02-00+00-00_task3_taskid3.eval")

    response = test_client.request("GET", "/logs?log_dir=eval_set_dir")
    response.raise_for_status()

    api_logs = response.json()
    assert "files" in api_logs
    files = api_logs["files"]
    assert len(files) == 3
    assert {"task1", "task2", "task3"} == {file["task"] for file in files}
    assert {"taskid1", "taskid2", "taskid3"} == {
        file["task_id"] for file in api_logs["files"]
    }
    assert "log_dir" in api_logs
    assert api_logs["log_dir"] == "eval_set_dir"


def test_api_logs_with_non_existing_dir(test_client: TestClient):
    response = test_client.request("GET", "/logs?log_dir=does_not_exist")
    response.raise_for_status()

    api_logs = response.json()
    assert "files" in api_logs
    files = api_logs["files"]
    assert len(files) == 0
    assert "log_dir" in api_logs
    assert api_logs["log_dir"] == "does_not_exist"


@pytest.mark.parametrize(
    "bad_log_dir",
    [
        None,
        "",
        "/",
    ],
)
def test_api_logs_forbidden(
    test_client_with_restrictive_access: TestClient, bad_log_dir: str | None
):
    response = test_client_with_restrictive_access.request(
        "GET",
        f"/logs?log_dir={bad_log_dir}" if bad_log_dir is not None else "/logs",
    )
    assert response.status_code == 403


def test_api_log_headers(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request(
        "GET",
        f"/log-headers?file={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    response.raise_for_status()
    api_log_headers = response.json()
    assert len(api_log_headers) == 1
    assert api_log_headers[0]["status"] == "started"


@pytest.mark.parametrize(
    ["last_eval_time", "expected_events"],
    [
        pytest.param("-1", ["refresh-evals"], id="refresh"),
        pytest.param("9999999999999", [], id="no-refresh"),
    ],
)
def test_api_events_refresh(
    test_client: TestClient, last_eval_time: int, expected_events: list[str]
):
    response = test_client.request("GET", f"/events?last_eval_time={last_eval_time}")
    response.raise_for_status()
    events = response.json()
    assert events == expected_events


def test_api_pending_samples_no_pending_samples(
    test_client: TestClient, mock_s3_eval_file: str
):
    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    assert response.status_code == 404


def test_api_pending_samples(test_client: TestClient, mock_s3_eval_file: str):
    write_fake_eval_log_buffer(mock_s3_eval_file)

    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    response.raise_for_status()
    manifest = response.json()
    assert "etag" in manifest
    assert "samples" in manifest

    etag = manifest["etag"]
    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
        headers={"If-None-Match": etag},
    )
    assert response.status_code == 304


def test_api_log_message(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request(
        "GET",
        f"/log-message?log_file={urllib.parse.quote_plus(mock_s3_eval_file)}&message=hello",
    )
    assert response.status_code == 204


def test_api_sample_events(test_client: TestClient, mock_s3_eval_file: str):
    write_fake_eval_log_buffer(mock_s3_eval_file, 1)

    response = test_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(mock_s3_eval_file)}&id=id&epoch=0",
    )
    response.raise_for_status()

    sample_events_data = response.json()
    events = sample_events_data["events"]
    assert len(events) == 1


def test_api_eval_set(test_client: TestClient):
    eval_set_id = "eval_set_id"
    eval_set_dir = f"memory://{eval_set_id}"
    fs = inspect_ai._util.file.filesystem(eval_set_dir)  # pyright: ignore[reportPrivateImportUsage]
    fs.mkdir(eval_set_dir)
    inspect_ai._eval.evalset.write_eval_set_info(  # pyright: ignore[reportPrivateImportUsage]
        eval_set_id=eval_set_id,
        log_dir=eval_set_dir,
        tasks=[
            inspect_ai._eval.task.resolved.ResolvedTask(
                id="task_id",
                task=inspect_ai._eval.task.Task(  # pyright: ignore[reportPrivateImportUsage]
                    name="task-name",
                    dataset=inspect_ai.dataset.MemoryDataset(
                        samples=[
                            inspect_ai.dataset.Sample(
                                input="input",
                                target="target",
                            )
                        ],
                    ),
                ),
                sandbox=None,
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
    api_eval_set = response.json()
    assert api_eval_set["eval_set_id"] == eval_set_id
    assert api_eval_set["tasks"] == [
        {
            "name": "task-name",
            "task_id": "task_id",
            "task_file": "task_file",
            "task_args": {},
            "model": "mockllm/model",
            "model_args": {},
            "sequence": 0,
        }
    ]


def test_api_log_download_eval(test_client: TestClient):
    """Test downloading a log file in eval format."""
    eval_file = "test_dir/test_log.eval"
    write_fake_eval_log(eval_file)

    _ = inspect_ai._util.file.filesystem("memory://")
    original_eval_path = f"memory://{eval_file}"

    original_log = inspect_ai.log.read_eval_log(original_eval_path)

    response = test_client.request("GET", f"/log-download/{eval_file}")
    response.raise_for_status()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert "content-disposition" in response.headers
    assert 'attachment; filename="' in response.headers["content-disposition"]
    assert ".eval" in response.headers["content-disposition"]

    temp_path = "memory://temp_download.eval"
    with cast(
        ContextManager[IO[bytes]],
        fsspec.open(temp_path, "wb"),
    ) as f:
        f.write(response.content)

    downloaded_log = inspect_ai.log.read_eval_log(temp_path)
    assert downloaded_log.model_dump() == original_log.model_dump()


def test_api_log_download_forbidden(test_client: TestClient, mock_s3_eval_file: str):
    """Test that download respects access control."""

    class no_read_policy(AccessPolicy):
        async def can_read(self, request: Request, file: str) -> bool:
            return False

        async def can_delete(self, request: Request, file: str) -> bool:
            return False

        async def can_list(self, request: Request, dir: str) -> bool:
            return True

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


def test_api_log_download_headers(test_client: TestClient, mock_s3_eval_file: str):
    """Test that download returns correct headers."""
    response = test_client.request("GET", f"/log-download/{mock_s3_eval_file}")
    response.raise_for_status()

    assert "content-length" in response.headers
    assert int(response.headers["content-length"]) > 0
    assert int(response.headers["content-length"]) == len(response.content)

    assert "content-disposition" in response.headers
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="')
    assert ".eval" in disposition

    assert response.headers["content-type"] == "application/octet-stream"


# ── log-files ETag-based incremental listing ────────────────────────────


def test_api_log_files_full_listing(test_client: TestClient):
    """First request (no ETag) returns a full listing."""
    write_fake_eval_log("logfiles_dir/2025-01-01T00-00-00+00-00_t1_id1.eval")
    write_fake_eval_log("logfiles_dir/2025-01-01T00-01-00+00-00_t2_id2.eval")

    response = test_client.request("GET", "/log-files?log_dir=logfiles_dir")
    response.raise_for_status()

    body = response.json()
    assert body["response_type"] == "full"
    assert len(body["files"]) == 2


def test_api_log_files_incremental_listing(test_client: TestClient):
    """Same file count + old mtime → incremental with changed files only."""
    write_fake_eval_log("incr_dir/2025-01-01T00-00-00+00-00_t1_id1.eval")
    write_fake_eval_log("incr_dir/2025-01-01T00-01-00+00-00_t2_id2.eval")

    # First request to establish baseline
    resp1 = test_client.request("GET", "/log-files?log_dir=incr_dir")
    resp1.raise_for_status()
    files = resp1.json()["files"]
    assert len(files) == 2

    # Use an ETag with mtime=0 and correct file count → all files changed
    etag = f"0.0-{len(files)}"
    resp2 = test_client.request(
        "GET", "/log-files?log_dir=incr_dir", headers={"If-None-Match": etag}
    )
    resp2.raise_for_status()
    body2 = resp2.json()
    assert body2["response_type"] == "incremental"
    # All files have mtime > 0 so all should be returned
    assert len(body2["files"]) == 2


def test_api_log_files_count_change_gives_full(test_client: TestClient):
    """File count mismatch → full listing regardless of mtime."""
    write_fake_eval_log("countchg_dir/2025-01-01T00-00-00+00-00_t1_id1.eval")

    # Claim there were 5 files last time
    etag = "0.0-5"
    resp = test_client.request(
        "GET", "/log-files?log_dir=countchg_dir", headers={"If-None-Match": etag}
    )
    resp.raise_for_status()
    assert resp.json()["response_type"] == "full"


def test_api_log_files_incremental_no_changes(test_client: TestClient):
    """Same count + future mtime → incremental with zero files."""
    write_fake_eval_log("nochg_dir/2025-01-01T00-00-00+00-00_t1_id1.eval")

    # First request to get actual file count
    resp1 = test_client.request("GET", "/log-files?log_dir=nochg_dir")
    resp1.raise_for_status()
    count = len(resp1.json()["files"])

    # Use a mtime far in the future so nothing is "newer"
    etag = f"99999999999999.0-{count}"
    resp2 = test_client.request(
        "GET", "/log-files?log_dir=nochg_dir", headers={"If-None-Match": etag}
    )
    resp2.raise_for_status()
    body = resp2.json()
    assert body["response_type"] == "incremental"
    assert len(body["files"]) == 0


# ── flow endpoint ───────────────────────────────────────────────────────


def test_api_flow_returns_yaml(test_client: TestClient):
    # flow endpoint uses filesystem() directly (no mapping_policy),
    # so we must pass memory:// in the query param
    flow_dir = "memory://flow_yaml_dir"
    fs = inspect_ai._util.file.filesystem(flow_dir)
    fs.mkdir(flow_dir)
    with cast(
        ContextManager[IO[bytes]],
        fsspec.open(f"{flow_dir}/flow.yaml", "wb"),
    ) as f:
        f.write(b"steps:\n  - name: step1\n")

    response = test_client.request(
        "GET", f"/flow?log_dir={urllib.parse.quote_plus(flow_dir)}"
    )
    response.raise_for_status()
    assert response.headers["content-type"].startswith("text/yaml")
    assert "step1" in response.text


def test_api_flow_missing_returns_404(test_client: TestClient):
    response = test_client.request(
        "GET", "/flow?log_dir=memory%3A%2F%2Fnonexistent_flow_dir"
    )
    assert response.status_code == 404


# ── log_dir query param override ────────────────────────────────────────


def test_api_log_dir_override(test_client: TestClient):
    """log_dir param should be honored (no authorization gating in FastAPI)."""
    response = test_client.request("GET", "/log-dir?log_dir=custom_dir")
    response.raise_for_status()
    assert response.json()["log_dir"] == "custom_dir"


def test_api_logs_log_dir_override(test_client: TestClient):
    """Listing with log_dir override returns results from that dir."""
    write_fake_eval_log("override_dir/2025-01-01T00-00-00+00-00_t1_id1.eval")

    response = test_client.request("GET", "/logs?log_dir=override_dir")
    response.raise_for_status()
    assert response.json()["log_dir"] == "override_dir"
    assert len(response.json()["files"]) == 1


# ── authorization middleware ────────────────────────────────────────────


def test_authorization_middleware_rejects_missing_token():
    """Requests without correct Authorization header get 401."""

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
        # No auth header
        resp = client.request("GET", "/api/events")
        assert resp.status_code == 401

        # Wrong auth header
        resp = client.request(
            "GET", "/api/events", headers={"Authorization": "Bearer wrong"}
        )
        assert resp.status_code == 401

        # Correct auth header
        resp = client.request(
            "GET", "/api/events", headers={"Authorization": "Bearer secret123"}
        )
        assert resp.status_code == 200


# ── NaN / Infinity in JSON responses ────────────────────────────────────


def test_api_log_with_nan_metric(test_client: TestClient):
    """EvalLog containing NaN metric values should serialize without error."""
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

    # JSON with NaN/Inf parses fine in Python (json.loads allows them)
    data = response.json()
    scores = data["results"]["scores"]
    assert len(scores) == 1
    accuracy_val = scores[0]["metrics"]["accuracy"]["value"]
    inf_val = scores[0]["metrics"]["inf_metric"]["value"]
    assert math.isnan(accuracy_val)
    assert math.isinf(inf_val)


# ── header-only mode ────────────────────────────────────────────────────


def test_api_log_header_only_zero(test_client: TestClient, mock_s3_eval_file: str):
    """header-only=0 forces header-only read (no samples)."""
    response = test_client.request("GET", f"/logs/{mock_s3_eval_file}?header-only=0")
    response.raise_for_status()
    data = response.json()
    assert data["eval"]["task"] == "task"
    # header-only read should not include samples
    assert data.get("samples") is None


def test_api_log_header_only_large_threshold(
    test_client: TestClient, mock_s3_eval_file: str
):
    """header-only=999999 (huge MB threshold) → full read (file is small)."""
    response = test_client.request(
        "GET", f"/logs/{mock_s3_eval_file}?header-only=999999"
    )
    response.raise_for_status()
    data = response.json()
    assert data["eval"]["task"] == "task"


# ── pending-samples with actual data ────────────────────────────────────


def test_api_pending_samples_returns_data(
    test_client: TestClient, mock_s3_eval_file: str
):
    """Verify full pending-samples response structure."""
    write_fake_eval_log_buffer(mock_s3_eval_file, num_segments=1)

    response = test_client.request(
        "GET",
        f"/pending-samples?log={urllib.parse.quote_plus(mock_s3_eval_file)}",
    )
    response.raise_for_status()
    body = response.json()

    assert "etag" in body
    assert "samples" in body
    assert len(body["samples"]) == 1
    sample = body["samples"][0]
    assert sample["id"] == "id"
    assert sample["epoch"] == 0


# ── pending-sample-data incremental params ──────────────────────────────


def test_api_pending_sample_data_incremental(
    test_client: TestClient, mock_s3_eval_file: str
):
    """last-event-id and after-attachment-id params are passed through."""
    write_fake_eval_log_buffer(mock_s3_eval_file, num_segments=2)

    # Fetch all events first
    resp_all = test_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(mock_s3_eval_file)}"
        "&id=id&epoch=0",
    )
    resp_all.raise_for_status()
    all_events = resp_all.json()["events"]

    # Fetch with last-event-id=0 to skip already-seen events
    resp_incr = test_client.request(
        "GET",
        f"/pending-sample-data?log={urllib.parse.quote_plus(mock_s3_eval_file)}"
        "&id=id&epoch=0&last-event-id=0",
    )
    resp_incr.raise_for_status()
    incr_events = resp_incr.json()["events"]
    # Should have fewer or equal events (events with id > 0 only)
    assert len(incr_events) <= len(all_events)


def test_api_pending_sample_data_missing_log(test_client: TestClient):
    """Requesting sample data for nonexistent log returns 404."""
    response = test_client.request(
        "GET",
        "/pending-sample-data?log=nonexistent%2Ffile.eval&id=x&epoch=0",
    )
    assert response.status_code == 404


# ── eval-set response format ────────────────────────────────────────────


def test_api_eval_set_response_fields(test_client: TestClient):
    """Verify eval-set response includes all expected fields via Pydantic dump."""
    eval_set_id = "evalset_fields_test"
    eval_set_dir = f"memory://{eval_set_id}"
    fs = inspect_ai._util.file.filesystem(eval_set_dir)
    fs.mkdir(eval_set_dir)
    inspect_ai._eval.evalset.write_eval_set_info(
        eval_set_id=eval_set_id,
        log_dir=eval_set_dir,
        tasks=[
            inspect_ai._eval.task.resolved.ResolvedTask(
                id="tid",
                task=inspect_ai._eval.task.Task(
                    name="my-task",
                    dataset=inspect_ai.dataset.MemoryDataset(
                        samples=[inspect_ai.dataset.Sample(input="in", target="out")],
                    ),
                ),
                sandbox=None,
                task_file="tf",
                task_args={"arg1": "val1"},
                model=inspect_ai.model.get_model("mockllm/model"),
                model_roles={},
                sequence=1,
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
    assert len(data["tasks"]) == 1
    task = data["tasks"][0]
    assert task["name"] == "my-task"
    assert task["task_id"] == "tid"
    assert task["task_file"] == "tf"
    assert task["task_args"] == {"arg1": "val1"}
    assert task["model"] == "mockllm/model"
    assert task["sequence"] == 1


# ── access policy: OnlyDirAccessPolicy ──────────────────────────────────


def test_only_dir_access_policy_blocks_outside_dir():
    """OnlyDirAccessPolicy rejects files outside the configured dir."""
    policy = fastapi_server.OnlyDirAccessPolicy("/allowed/dir")

    import asyncio

    assert asyncio.run(policy.can_read(None, "/allowed/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/other/dir/file.eval"))  # type: ignore[arg-type]
    assert not asyncio.run(policy.can_read(None, "/allowed/dir/../etc/passwd"))  # type: ignore[arg-type]


def test_only_dir_access_policy_via_test_client(mock_s3_eval_file: str):
    """Integration: OnlyDirAccessPolicy blocks reads outside log_dir."""

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
        # Allowed: file is under mocked_eval_set/
        resp = client.request("GET", f"/logs/{mock_s3_eval_file}")
        assert resp.status_code == 200

        # Blocked: file is outside mocked_eval_set/
        resp = client.request("GET", "/logs/other_dir/file.eval")
        assert resp.status_code == 403


# ── log-bytes edge cases ────────────────────────────────────────────────


def test_api_log_bytes_exact_range(test_client: TestClient, mock_s3_eval_file: str):
    """Requesting exact valid range returns correct bytes."""
    size_resp = test_client.request("GET", f"/log-info/{mock_s3_eval_file}")
    size_resp.raise_for_status()
    file_size = size_resp.json()["size"]

    # Request last 10 bytes
    start = max(0, file_size - 10)
    resp = test_client.request(
        "GET", f"/log-bytes/{mock_s3_eval_file}?start={start}&end={file_size - 1}"
    )
    resp.raise_for_status()
    assert len(resp.content) == min(10, file_size)


def test_api_log_bytes_single_byte(test_client: TestClient, mock_s3_eval_file: str):
    """Requesting a single byte (start==end) works."""
    resp = test_client.request("GET", f"/log-bytes/{mock_s3_eval_file}?start=0&end=0")
    resp.raise_for_status()
    assert len(resp.content) == 1


# ── log-message ─────────────────────────────────────────────────────────


def test_api_log_message_with_special_chars(
    test_client: TestClient, mock_s3_eval_file: str
):
    """Message with URL-encoded special characters."""
    msg = "error: something & went <wrong>"
    response = test_client.request(
        "GET",
        f"/log-message?log_file={urllib.parse.quote_plus(mock_s3_eval_file)}"
        f"&message={urllib.parse.quote_plus(msg)}",
    )
    assert response.status_code == 204


# ── events endpoint ─────────────────────────────────────────────────────


def test_api_events_no_param(test_client: TestClient):
    """No last_eval_time param → empty list."""
    response = test_client.request("GET", "/events")
    response.raise_for_status()
    assert response.json() == []


# ── log-headers multiple files ──────────────────────────────────────────


def test_api_log_headers_multiple_files(test_client: TestClient):
    """Multiple file params return headers for each."""
    f1 = "headers_dir/2025-01-01T00-00-00+00-00_t1_id1.eval"
    f2 = "headers_dir/2025-01-01T00-01-00+00-00_t2_id2.eval"
    write_fake_eval_log(f1)
    write_fake_eval_log(f2)

    query = f"file={urllib.parse.quote_plus(f1)}&file={urllib.parse.quote_plus(f2)}"
    response = test_client.request("GET", f"/log-headers?{query}")
    response.raise_for_status()
    headers = response.json()
    assert len(headers) == 2
    assert headers[0]["status"] == "started"
    assert headers[1]["status"] == "started"


# ── InspectJsonResponse ─────────────────────────────────────────────────


def test_inspect_json_response_nan():
    """InspectJsonResponse.render handles NaN and Infinity."""
    resp = fastapi_server.InspectJsonResponse(
        content={"val": float("nan"), "inf": float("inf"), "neg_inf": float("-inf")}
    )
    body = resp.body.decode("utf-8")
    assert "NaN" in body
    assert "Infinity" in body
    assert "-Infinity" in body


# ══════════════════════════════════════════════════════════════════════════
# GAP TESTS — these expose aiohttp behaviors not yet matched by FastAPI.
# Each test documents the gap in its docstring. Fix the FastAPI server
# to make these pass, then remove the xfail marker.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.xfail(reason="GAP: /log-size/{log} endpoint missing in FastAPI")
def test_gap_log_size_endpoint(test_client: TestClient, mock_s3_eval_file: str):
    """Aiohttp has GET /api/log-size/{log} returning file size as a JSON int.

    FastAPI has no equivalent — size is only available via /log-info/.
    """
    response = test_client.request("GET", f"/log-size/{mock_s3_eval_file}")
    assert response.status_code == 200
    size = response.json()
    assert isinstance(size, int)
    assert size > 0


@pytest.mark.xfail(reason="GAP: /flow does not use _map_file for directory resolution")
def test_gap_flow_uses_map_file(test_client: TestClient):
    """/flow reads from the unmapped dir path instead of calling _map_file.

    This means the mapping_policy is bypassed — the endpoint calls
    filesystem(flow_dir) directly with the raw (unmapped) path.
    Compare with /eval-set which correctly calls _map_file.
    """
    flow_dir = "memory://flow_mapped_dir"
    fs = inspect_ai._util.file.filesystem(flow_dir)
    fs.mkdir(flow_dir)
    with cast(
        ContextManager[IO[bytes]],
        fsspec.open(f"{flow_dir}/flow.yaml", "wb"),
    ) as f:
        f.write(b"steps:\n  - name: mapped_step\n")

    # Use the plain dir name — mapping_policy should prepend memory://
    response = test_client.request("GET", "/flow?dir=flow_mapped_dir")
    response.raise_for_status()
    assert "mapped_step" in response.text


@pytest.mark.xfail(
    reason="GAP: view_server() does not pass generate_direct_urls to view_server_app()"
)
def test_gap_generate_direct_urls_wired():
    """The aiohttp view_server() accepts generate_direct_urls and passes it through.

    FastAPI view_server() does not accept or forward this parameter — it
    always defaults to False in view_server_app().
    """
    import inspect

    sig = inspect.signature(fastapi_server.view_server)
    assert "generate_direct_urls" in sig.parameters


@pytest.mark.xfail(
    reason="GAP: /logs/{log} does not catch exceptions — returns raw 500 instead of structured error"
)
def test_gap_log_read_error_returns_structured_500(test_client: TestClient):
    """The aiohttp server wraps log read errors in log_file_response() → 500 with reason.

    FastAPI lets exceptions propagate to uvicorn's generic 500 handler.
    A structured error response (JSON with error details) would be better
    for client-side error handling.
    """
    response = test_client.request("GET", "/logs/nonexistent/file.eval")
    assert response.status_code == 500
    # aiohttp returns reason="File not found"; FastAPI should return
    # a JSON body with error info rather than plain "Internal Server Error"
    body = response.json()
    assert "error" in body or "reason" in body
