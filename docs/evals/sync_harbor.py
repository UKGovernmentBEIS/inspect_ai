"""Sync inspect_harbor evals into harbor.yml.

Fetches the Harbor dataset registry plus inspect_harbor's generated `_tasks.py`
(for exposed Python function names), joins with a local overlay file for fields
the registry lacks (arxiv, repo, group, tags), and writes `harbor.yml`.

Usage:
    python docs/evals/sync_harbor.py [--no-fetch]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import yaml

HERE = Path(__file__).parent
CACHE_DIR = HERE / ".cache"
OUTPUT_FILE = HERE / "harbor.yml"
OVERLAY_FILE = HERE / "harbor_overrides.yml"

REGISTRY_URL = (
    "https://raw.githubusercontent.com/laude-institute/harbor/refs/heads/main/registry.json"
)
TASKS_URL = (
    "https://raw.githubusercontent.com/meridianlabs-ai/inspect_harbor"
    "/refs/heads/main/src/inspect_harbor/_tasks.py"
)

GENERIC_IMPLEMENTATION_REPOS = {
    "https://github.com/laude-institute/harbor.git",
    "https://github.com/laude-institute/harbor-datasets.git",
    "https://huggingface.co/datasets/harborframework/harbor-datasets",
}


def derive_title(name: str) -> str:
    # Drop any owner/namespace prefix (e.g. "scale-ai/swe-atlas-qna" → "swe-atlas-qna")
    leaf = name.rsplit("/", 1)[-1]
    return leaf.replace("-", " ").replace("_", " ").strip().title()


def fetch_to_cache(url: str, dest: Path, use_cache: bool) -> str:
    if use_cache and dest.exists():
        return dest.read_text()
    print(f"fetching {url}")
    with urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return text


def extract_dataset_function_map(tasks_py_source: str) -> dict[str, str]:
    """Map dataset identifier (name or name@version) → Python function name.

    Built by parsing `_tasks.py` for `@task`-decorated functions and reading
    the `Dataset: <id>` line in each docstring. This is more robust than
    mirroring inspect_harbor's naming transform, which has exceptions
    (e.g. `scale-ai/swe-atlas-qna@1.0` → `swe_atlas_qna_1_0`).
    """
    tree = ast.parse(tasks_py_source)
    mapping: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        has_task_decorator = any(
            (isinstance(d, ast.Name) and d.id == "task")
            or (isinstance(d, ast.Attribute) and d.attr == "task")
            for d in node.decorator_list
        )
        if not has_task_decorator:
            continue
        doc = ast.get_docstring(node) or ""
        for line in doc.splitlines():
            line = line.strip()
            if line.startswith("Dataset:"):
                dataset_id = line.split(":", 1)[1].strip()
                if dataset_id:
                    mapping[dataset_id] = node.name
                break
    return mapping


def unique_task_git_url(tasks: list[dict[str, Any]]) -> str | None:
    urls = {t.get("git_url") for t in tasks if t.get("git_url")}
    if len(urls) == 1:
        (url,) = urls
        if url and url not in GENERIC_IMPLEMENTATION_REPOS:
            return url
    return None


def load_overlay() -> dict[str, dict[str, Any]]:
    if not OVERLAY_FILE.exists():
        return {}
    data = yaml.safe_load(OVERLAY_FILE.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{OVERLAY_FILE} must be a mapping keyed by dataset name")
    return data


def build_records(
    registry: list[dict[str, Any]],
    function_map: dict[str, str],
    overlay: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    sorted_registry = sorted(
        registry, key=lambda d: (d.get("name", ""), d.get("version", ""))
    )

    seen_names: set[str] = set()
    records: list[dict[str, Any]] = []
    skipped: list[str] = []

    for entry in sorted_registry:
        name = entry.get("name")
        version = entry.get("version")
        if not name or not version:
            continue

        name_version = f"{name}@{version}"
        function_name = function_map.get(name_version)

        if function_name is None:
            skipped.append(f"{name_version} (not exposed in _tasks.py)")
            continue

        is_latest = name not in seen_names
        seen_names.add(name)
        latest_alias: str | None = function_map.get(name) if is_latest else None

        ov = overlay.get(name, {})
        tasks = entry.get("tasks", []) or []
        source_repo = unique_task_git_url(tasks)

        record: dict[str, Any] = {
            "name": name,
            "version": version,
            "title": ov.get("title") or derive_title(name),
            "description": entry.get("description", ""),
            "function_name": function_name,
            "latest_alias": latest_alias,
            "sample_count": len(tasks),
            "source_repo": source_repo,
            "repo": ov.get("repo") or source_repo,
            "arxiv": ov.get("arxiv"),
            "group": ov.get("group", "Harbor"),
            "tags": ov.get("tags", []) or [],
            "registry_url": f"https://harborframework.com/registry/{name}/{version}",
            "url": f"https://harborframework.com/registry/{name}/{version}",
            "tasks": tasks,
        }
        records.append(record)

    records.sort(
        key=lambda r: (r["group"].lower(), r["title"].lower(), r["name"], r["version"])
    )

    if skipped:
        print(f"skipped {len(skipped)} registry entries not exposed by inspect_harbor:")
        for s in skipped:
            print(f"  - {s}")

    return records


def write_harbor_yaml(records: list[dict[str, Any]]) -> None:
    with OUTPUT_FILE.open("w") as f:
        yaml.safe_dump(
            records,
            f,
            sort_keys=False,
            allow_unicode=True,
            width=2**31 - 1,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Reuse cached registry.json and _tasks.py; do not hit the network.",
    )
    parser.add_argument("--registry-url", default=REGISTRY_URL)
    parser.add_argument("--tasks-url", default=TASKS_URL)
    args = parser.parse_args()

    use_cache = args.no_fetch
    try:
        registry_text = fetch_to_cache(
            args.registry_url, CACHE_DIR / "registry.json", use_cache
        )
        tasks_text = fetch_to_cache(args.tasks_url, CACHE_DIR / "_tasks.py", use_cache)
    except Exception as e:
        print(f"error fetching inputs: {e}", file=sys.stderr)
        sys.exit(1)

    registry = json.loads(registry_text)
    function_map = extract_dataset_function_map(tasks_text)
    overlay = load_overlay()

    records = build_records(registry, function_map, overlay)
    write_harbor_yaml(records)

    print(f"synced {len(records)} harbor evals → {OUTPUT_FILE.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
