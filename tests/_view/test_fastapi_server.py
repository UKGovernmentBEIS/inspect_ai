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


def test_api_log_size(test_client: TestClient, mock_s3_eval_file: str):
    response = test_client.request("GET", f"/log-size/{mock_s3_eval_file}")
    response.raise_for_status()
    api_log_size = response.text
    assert int(api_log_size) >= 100


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
        config=GenerateConfig(),
        eval_set_solver=None,
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
