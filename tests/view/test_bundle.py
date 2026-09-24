import json
import os
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import filesystem
from inspect_ai._view._csp import CSP_FILENAME
from inspect_ai.dataset import Sample
from inspect_ai.log._bundle import _prepare_viewer, bundle_log_dir, embed_log_dir
from inspect_ai.scorer import match


@pytest.mark.slow
@skip_if_trio
def test_s3_bundle(mock_s3) -> None:
    # run an eval to generate a log file to this directory
    s3_fs = filesystem("s3://test-bucket/")

    # target directories
    log_dir = "s3://test-bucket/test_s3_bundle/logs"
    output_dir = "s3://test-bucket/test_s3_bundle/view"

    eval(
        tasks=[
            Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
            for i in range(0, 2)
        ],
        model="mockllm/model",
        log_dir=log_dir,
    )

    # bundle to the output dir
    bundle_log_dir(log_dir, output_dir)

    # ensure files are what we expect
    expected_exact = ["index.html", "assets", "logs", "logs/listing.json"]
    for exp in expected_exact:
        assert s3_fs.exists(os.path.join(output_dir, exp))

    # asset filenames
    assets = s3_fs.ls(os.path.join(output_dir, "assets"))
    asset_names = [os.path.basename(a.name) for a in assets]
    assert "index.js" in asset_names
    assert "index.css" in asset_names


def test_bundle() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        # run an eval to generate a log file to this directory
        log_dir = os.path.join(working_dir, "logs")
        output_dir = os.path.join(working_dir, "output")

        eval(
            tasks=[
                Task(
                    dataset=[Sample(input="Say Hello", target="Hello")], scorer=match()
                )
                for i in range(0, 2)
            ],
            model="mockllm/model",
            log_dir=log_dir,
        )

        # bundle to the output dir
        bundle_log_dir(log_dir, output_dir)

        # ensure files are what we expect
        expected_exact = ["index.html", "assets", "logs", "logs/listing.json"]
        for exp in expected_exact:
            assert os.path.exists(os.path.join(output_dir, exp))

        # asset filenames
        assert os.path.exists(os.path.join(output_dir, "assets", "index.js"))
        assert os.path.exists(os.path.join(output_dir, "assets", "index.css"))

        # ensure there is a non-listing.json log file present in logs
        non_manifest_logs = [
            f
            for f in os.listdir(os.path.join(output_dir, "logs"))
            if f.endswith(".eval") and f != "logs.eval"
        ]
        assert len(non_manifest_logs) == 2


@skip_if_trio
def test_s3_embed(mock_s3) -> None:
    s3_fs = filesystem("s3://test-bucket/")

    log_dir = "s3://test-bucket/test_s3_embed/logs"

    eval(
        tasks=[
            Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
            for i in range(0, 2)
        ],
        model="mockllm/model",
        log_dir=log_dir,
    )

    # embed the viewer
    embed_log_dir(log_dir)

    # ensure viewer files are present directly in the log dir
    viewer_expected = ["index.html", "assets", "robots.txt", "listing.json"]
    for exp in viewer_expected:
        assert s3_fs.exists(os.path.join(log_dir, exp))

    # asset filenames
    assets = s3_fs.ls(os.path.join(log_dir, "assets"))
    asset_names = [os.path.basename(a.name) for a in assets]
    assert "index.js" in asset_names
    assert "index.css" in asset_names

    # ensure old viewer/ subdirectory was not created
    assert not s3_fs.exists(os.path.join(log_dir, "viewer"))


def test_embed() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        log_dir = os.path.join(working_dir, "logs")

        eval(
            tasks=[
                Task(
                    dataset=[Sample(input="Say Hello", target="Hello")], scorer=match()
                )
                for i in range(0, 2)
            ],
            model="mockllm/model",
            log_dir=log_dir,
        )

        # embed the viewer
        embed_log_dir(log_dir)

        # ensure viewer files are present directly in the log dir
        viewer_expected = ["index.html", "assets", "robots.txt", "listing.json"]
        for exp in viewer_expected:
            assert os.path.exists(os.path.join(log_dir, exp))

        # asset filenames
        assert os.path.exists(os.path.join(log_dir, "assets", "index.js"))
        assert os.path.exists(os.path.join(log_dir, "assets", "index.css"))

        # ensure old viewer/ subdirectory was not created
        assert not os.path.exists(os.path.join(log_dir, "viewer"))

        # ensure index.html has the log_dir context set to "."
        with open(os.path.join(log_dir, "index.html")) as f:
            contents = f.read()
        assert '"log_dir": "."' in contents


def test_bundle_output_dir_cannot_be_subdir_of_log_dir(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    output_dir = log_dir / "output"

    log_dir.mkdir()

    with pytest.raises(PrerequisiteError, match="cannot be a subdirectory"):
        bundle_log_dir(str(log_dir), str(output_dir))


def test_bundle_hf_output_dir_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        "inspect_ai.log._bundle._check_hf_space_exists", lambda repo_id: False
    )
    monkeypatch.setattr(
        "inspect_ai.log._bundle._prepare_viewer", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "inspect_ai.log._bundle.copy_log_files", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "inspect_ai.log._bundle.write_log_listing", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "inspect_ai.log._bundle._push_bundle_to_hf", lambda *args, **kwargs: None
    )

    # Should not raise PrerequisiteError about subdirectory
    bundle_log_dir(log_dir=".", output_dir="hf/username/myspace")


_FIXTURE_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <script>document.documentElement.dataset.theme = "light";</script>
    <script type="module" src="./assets/index.js"></script>
  </head>
  <body><div id="app"></div></body>
</html>
"""


def _fixture_dist(tmp_path: Path, directives: dict[str, list[str]] | None) -> Path:
    dist_dir = tmp_path / "dist"
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "index.html").write_text(_FIXTURE_INDEX_HTML, encoding="utf-8")
    (dist_dir / "assets" / "index.js").write_text("", encoding="utf-8")
    if directives is not None:
        (dist_dir / CSP_FILENAME).write_text(
            json.dumps({"version": 1, "directives": directives}), encoding="utf-8"
        )
    return dist_dir


class _HeadChildren(HTMLParser):
    """Collect the start tags (with decoded attributes) directly inside <head>."""

    def __init__(self) -> None:
        super().__init__()
        self.children: list[tuple[str, dict[str, str | None]]] = []
        self._depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._depth = 0
        elif self._depth is not None:
            if self._depth == 0:
                self.children.append((tag, dict(attrs)))
            if tag not in ("meta", "link"):
                self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._depth = None
        elif self._depth:
            self._depth -= 1


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dist_dir: Path) -> str:
    monkeypatch.setattr("inspect_ai.log._bundle._dist_dir", lambda: dist_dir.as_posix())
    working_dir = tmp_path / "bundle"
    working_dir.mkdir()
    _prepare_viewer(str(working_dir), log_dir="logs", abs_log_dir="/abs/logs")
    return (working_dir / "index.html").read_text(encoding="utf-8")


def test_bundle_inserts_viewer_csp_meta_first_in_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_dir = _fixture_dist(
        tmp_path,
        {
            "default-src": ["'none'"],
            "script-src": ["'self'", "'sha256-abc+/='"],
            "img-src": ['https://cdn.example/a?b&c<"d">'],
        },
    )
    index_html = _prepare(tmp_path, monkeypatch, dist_dir)

    parser = _HeadChildren()
    parser.feed(index_html)
    first_tag, first_attrs = parser.children[0]
    assert first_tag == "meta"
    assert first_attrs == {
        "http-equiv": "Content-Security-Policy",
        "content": (
            "default-src 'none'; script-src 'self' 'sha256-abc+/='; "
            'img-src https://cdn.example/a?b&c<"d">'
        ),
    }
    assert "frame-ancestors" not in index_html
    assert "&amp;c&lt;&quot;d&quot;&gt;" in index_html

    # the log_dir_context data block is still injected, after the inline scripts
    tags = [tag for tag, _ in parser.children]
    assert tags == ["meta", "meta", "script", "script", "script"]
    assert parser.children[-1][1] == {
        "id": "log_dir_context",
        "type": "application/json",
    }
    assert '{"log_dir": "logs", "abs_log_dir": "/abs/logs"}' in index_html


def test_bundle_without_viewer_csp_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_html = _prepare(tmp_path, monkeypatch, _fixture_dist(tmp_path, None))

    context = '{"log_dir": "logs", "abs_log_dir": "/abs/logs"}'
    assert index_html == _FIXTURE_INDEX_HTML.replace(
        "</head>",
        f'  <script id="log_dir_context" type="application/json">{context}</script>\n  </head>',
    )


def test_bundle_viewer_csp_requires_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_dir = _fixture_dist(tmp_path, {"default-src": ["'none'"]})
    (dist_dir / "index.html").write_text("<html><body></body></html>")
    with pytest.raises(RuntimeError, match="no <head> element"):
        _prepare(tmp_path, monkeypatch, dist_dir)
