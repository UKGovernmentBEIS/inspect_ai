"""Tests for the inspect view server — both aiohttp and FastAPI implementations.

Parameterized tests run the same assertions against both servers. Tests that
are specific to FastAPI abstractions (AccessPolicy, FileMappingPolicy) or that
document gaps between the two implementations are grouped at the end.
"""

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
from inspect_ai._view.fastapi_server import AccessPolicy, FileMappingPolicy
from inspect_ai.model._generate_config import GenerateConfig

# ═══════════════════════════════════════════════════════════════════════════
# Unified test client wrapper
# ═══════════════════════════════════════════════════════════════════════════


class SimpleResponse:
    """Normalised response that works for both server implementations."""

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
    """Unified interface over FastAPI TestClient and aiohttp TestClient.

    Handles the URL-prefix and log-path-encoding differences transparently.
    """

    def __init__(self, impl: str, log_dir: Path) -> None:
        self.impl = impl
        self.log_dir = log_dir

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> SimpleResponse:
        raise NotImplementedError

    def log_path(self, filename: str) -> str:
        """Full filesystem path for a log file under log_dir."""
        return str(self.log_dir / filename)

    def log_url(self, endpoint: str, filename: str) -> str:
        """Build a URL for a log-path endpoint (e.g. ``logs``, ``log-info``)."""
        full_path = self.log_path(filename)
        return f"/{endpoint}/{self._encode_for_url(full_path)}"

    def _encode_for_url(self, file_path: str) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class FastAPIViewTestClient(ViewTestClient):
    def __init__(self, log_dir: Path) -> None:
        super().__init__("fastapi", log_dir)
        app = fastapi_server.view_server_app(default_dir=str(log_dir))
        self._tc = fastapi.testclient.TestClient(app)
        self._tc.__enter__()

    def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> SimpleResponse:
        resp = self._tc.request(method, path, headers=headers or {})
        return SimpleResponse(resp.status_code, resp.content, dict(resp.headers))

    def _encode_for_url(self, file_path: str) -> str:
        # FastAPI {log:path} captures slashes natively
        return file_path

    def close(self) -> None:
        self._tc.__exit__(None, None, None)


class AioHTTPViewTestClient(ViewTestClient):
    def __init__(self, log_dir: Path) -> None:
        super().__init__("aiohttp", log_dir)
        from inspect_ai._view.server import view_server_app

        self._loop = asyncio.new_event_loop()
        aiohttp_app = view_server_app(log_dir=str(log_dir))

        async def _start() -> None:
            from aiohttp.test_utils import TestClient as AioTestClient
            from aiohttp.test_utils import TestServer

            self._server = TestServer(aiohttp_app)
            self._client = AioTestClient(self._server)
            await self._client.start_server()

        self._loop.run_until_complete(_start())

    def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> SimpleResponse:
        # aiohttp routes are prefixed with /api
        full_path = f"/api{path}"

        async def _do() -> SimpleResponse:
            resp = await self._client.request(method, full_path, headers=headers or {})
            body = await resp.read()
            return SimpleResponse(resp.status, body, dict(resp.headers))

        return self._loop.run_until_complete(_do())

    def _encode_for_url(self, file_path: str) -> str:
        # aiohttp {log} is a single path segment — encode slashes
        return urllib.parse.quote(file_path, safe="")

    def close(self) -> None:
        self._loop.run_until_complete(self._client.close())
        self._loop.close()


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def write_eval_log(base_dir: Path, filename: str) -> str:
    """Write a minimal eval log to ``base_dir/filename``. Return full path."""
    full_path = str(base_dir / filename)
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
    inspect_ai.log.write_eval_log(eval_log, full_path, "eval")
    return full_path


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
# Parameterized fixture
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(params=["fastapi", "aiohttp"])
def view_client(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[ViewTestClient, Any, None]:
    impl = request.param
    if impl == "fastapi":
        client = FastAPIViewTestClient(tmp_path)
    else:
        client = AioHTTPViewTestClient(tmp_path)
    yield client
    client.close()


# ═══════════════════════════════════════════════════════════════════════════
# Parameterized parity tests (run against both servers)
# ═══════════════════════════════════════════════════════════════════════════


def test_api_log(view_client: ViewTestClient) -> None:
    fname = "2025-01-01T00-00-00+00-00_task_taskid.eval"
    write_eval_log(view_client.log_dir, fname)
    resp = view_client.request("GET", view_client.log_url("logs", fname))
    resp.raise_for_status()
    assert resp.json()["eval"]["task"] == "task"


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
    write_eval_log_named(view_client.log_dir, "2025-01-01T00-00-00+00-00_t1_id1.eval", "t1", "id1")
    write_eval_log_named(view_client.log_dir, "2025-01-01T00-01-00+00-00_t2_id2.eval", "t2", "id2")
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
    full_path = write_eval_log(view_client.log_dir, fname)
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


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI-specific tests (memory://, AccessPolicy, FileMappingPolicy)
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


def test_fastapi_sample_events(
    test_client: TestClient, mock_s3_eval_file: str
) -> None:
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
        assert client.request(
            "GET", "/api/events", headers={"Authorization": "Bearer wrong"}
        ).status_code == 401
        assert client.request(
            "GET", "/api/events", headers={"Authorization": "Bearer secret123"}
        ).status_code == 200


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
    assert not asyncio.run(policy.can_read(None, "/allowed/dir/../etc/passwd"))  # type: ignore[arg-type]


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
# Former gap tests — these previously documented aiohttp behaviors missing
# from FastAPI. All gaps have been fixed.
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
