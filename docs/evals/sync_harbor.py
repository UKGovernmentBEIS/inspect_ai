"""Load inspect_harbor evals into normalized EvalRecord dicts.

Fetches the Harbor dataset registry plus inspect_harbor's generated `_tasks.py`
(for exposed Python function names), joins with `harbor_overrides.yml` for
fields the registry lacks, and returns records matching the design schema.

Writes are handled by sync_all.py.

`categories` (array) is REQUIRED per entry in harbor_overrides.yml; entries
missing categories are reported back to the caller.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import yaml

HERE = Path(__file__).parent
CACHE_DIR = HERE / ".cache"
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


import re


def _clean_desc(desc: str) -> str:
    """Strip 'Original benchmark: URL', 'Adapter: URL', inline URLs, etc."""
    desc = re.sub(
        r"\s*(Original benchmark|Adapter details|Adapter|Source|Website)"
        r":\s*https?://\S+\.?\s*",
        " ", desc,
    )
    desc = re.sub(r"\(https?://\S+\)", "", desc)
    desc = re.sub(r"https?://\S+", "", desc)
    desc = re.sub(r"Adapter for \S+ \.", "", desc)
    desc = re.sub(r"\s{2,}", " ", desc)
    result = desc.strip().rstrip(".")
    return (result + ".") if result else ""


def _derive_title(name: str) -> str:
    leaf = name.rsplit("/", 1)[-1]
    return leaf.replace("-", " ").replace("_", " ").strip().title()


def _fetch_to_cache(url: str, dest: Path, use_cache: bool) -> str:
    if use_cache and dest.exists():
        return dest.read_text()
    print(f"fetching {url}")
    with urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return text


def _extract_dataset_metadata(
    tasks_py_source: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Parse `_tasks.py` docstrings for per-dataset metadata.

    Returns (function_map, url_map):
      - function_map: dataset id (name or name@version) → Python function name
      - url_map:     dataset id → canonical Harbor registry URL

    Both maps are built from the `Dataset:` / `Harbor URL:` lines in each
    `@task`-decorated function's docstring. Parsing the docstring (rather
    than mirroring inspect_harbor's naming / URL-resolution logic here)
    keeps this script a pure consumer of whatever `_tasks.py` publishes.

    `url_map` may omit entries when `_tasks.py` predates the `Harbor URL:`
    line (older cached copies); the caller falls back to the site's search
    URL in that case.
    """
    tree = ast.parse(tasks_py_source)
    function_map: dict[str, str] = {}
    url_map: dict[str, str] = {}
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
        dataset_id: str | None = None
        harbor_url: str | None = None
        for line in doc.splitlines():
            line = line.strip()
            if line.startswith("Dataset:"):
                dataset_id = line.split(":", 1)[1].strip() or None
            elif line.startswith("Harbor URL:"):
                harbor_url = line.split(":", 1)[1].strip() or None
        if dataset_id is None:
            continue
        function_map[dataset_id] = node.name
        if harbor_url is not None:
            url_map[dataset_id] = harbor_url
    return function_map, url_map


def _load_overlay() -> dict[str, dict[str, Any]]:
    if not OVERLAY_FILE.exists():
        return {}
    data = yaml.safe_load(OVERLAY_FILE.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{OVERLAY_FILE} must be a mapping keyed by dataset name")
    return data


def load_harbor(
    *, use_cache: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (records, missing_category_names).

    Callers (sync_all.py) error out when missing_category_names is non-empty.
    """
    registry_text = _fetch_to_cache(REGISTRY_URL, CACHE_DIR / "registry.json", use_cache)
    tasks_text = _fetch_to_cache(TASKS_URL, CACHE_DIR / "_tasks.py", use_cache)

    registry = json.loads(registry_text)
    function_map, url_map = _extract_dataset_metadata(tasks_text)
    overlay = _load_overlay()

    sorted_registry = sorted(
        registry, key=lambda d: (d.get("name", ""), d.get("version", ""))
    )

    seen_names: set[str] = set()
    records: list[dict[str, Any]] = []
    missing_category: list[str] = []
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

        ov = overlay.get(name, {})
        categories = ov.get("categories") or []
        if not categories and is_latest:
            missing_category.append(name)

        tasks = entry.get("tasks", []) or []
        paper = ov.get("arxiv") or ov.get("repo")

        records.append({
            "id": function_name,
            "name": ov.get("title") or _derive_title(name),
            "source": "harbor",
            "categories": categories or ["Other"],
            "tags": list(ov.get("tags") or []),
            "kind": ov.get("kind", "agent"),
            "modalities": list(ov.get("modalities") or ["agent", "sandbox"]),
            "desc": ov.get("desc") or _clean_desc(entry.get("description", "")),
            "paper": paper,
            "code": f"inspect_harbor/{function_name}",
            "contributors": list(ov.get("contributors") or []),
            "samples": len(tasks),
            "featured": bool(ov.get("featured", False)),
            "url": url_map.get(name_version)
            or f"https://registry.harborframework.com/datasets?q={name}",
        })

    if skipped:
        print(f"skipped {len(skipped)} registry entries not exposed by inspect_harbor:")
        for s in skipped:
            print(f"  - {s}")

    return records, missing_category
