"""Load inspect_harbor evals into normalized EvalRecord dicts.

Fetches inspect_harbor's ``docs/registry-listing.yml`` and joins with
``docs/overrides.yml`` for fields the listing lacks.

Writes are handled by sync_all.py.

``categories`` (array) is REQUIRED per entry in overrides.yml; entries
missing categories are reported back to the caller. inspect_harbor's CI
validates this file on every PR, so in practice reaching this code path
with a missing-category entry means the upstream validation was bypassed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.request import urlopen

import yaml

HERE = Path(__file__).parent
CACHE_DIR = HERE / ".cache"

REGISTRY_LISTING_URL = (
    "https://raw.githubusercontent.com/meridianlabs-ai/inspect_harbor"
    "/refs/heads/main/docs/registry-listing.yml"
)
OVERRIDES_URL = (
    "https://raw.githubusercontent.com/meridianlabs-ai/inspect_harbor"
    "/refs/heads/main/docs/overrides.yml"
)
INSPECT_HARBOR_DOCS_BASE = "https://meridianlabs-ai.github.io/inspect_harbor"


def _derive_title(slug: str) -> str:
    """Fallback title from an ``org/name`` slug when no ``title`` override is set."""
    return slug.rsplit("/", 1)[-1]


def _fetch_to_cache(url: str, dest: Path, use_cache: bool) -> str:
    if use_cache and dest.exists():
        return dest.read_text()
    print(f"fetching {url}")
    with urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return text


def _load_listing(use_cache: bool) -> list[dict[str, Any]]:
    text = _fetch_to_cache(
        REGISTRY_LISTING_URL, CACHE_DIR / "registry-listing.yml", use_cache
    )
    data = yaml.safe_load(text) or []
    if not isinstance(data, list):
        raise ValueError(f"{REGISTRY_LISTING_URL} must be a list of entries")
    return data


def _load_overlay(use_cache: bool) -> dict[str, dict[str, Any]]:
    """Fetch inspect_harbor's overrides.yml and return it as a mapping.

    Cached in the same ``.cache/`` directory as the listing fetch so
    ``--no-fetch`` runs offline cleanly.
    """
    text = _fetch_to_cache(OVERRIDES_URL, CACHE_DIR / "overrides.yml", use_cache)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{OVERRIDES_URL} must be a mapping keyed by org/name slug")
    return data


def load_harbor(
    *, use_cache: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (records, missing_category_slugs).

    Callers (sync_all.py) error out when missing_category_slugs is non-empty.
    """
    listing = _load_listing(use_cache)
    overlay = _load_overlay(use_cache)

    records: list[dict[str, Any]] = []
    missing_category: list[str] = []

    for entry in listing:
        slug = entry["title"]
        function_name = entry["task_function"]

        ov = overlay.get(slug, {})
        categories = ov.get("categories") or []
        if not categories:
            missing_category.append(slug)

        desc = ov.get("desc") or entry.get("desc", "")
        paper = ov.get("arxiv") or ov.get("repo")

        records.append(
            {
                "id": function_name,
                "name": ov.get("title") or _derive_title(slug),
                "source": "harbor",
                "categories": categories or ["Other"],
                "tags": list(ov.get("tags") or []),
                "kind": ov.get("kind", "agent"),
                "modalities": list(ov.get("modalities") or ["agent", "sandbox"]),
                "desc": desc,
                "paper": paper,
                "code": f"inspect_harbor/{function_name}",
                "contributors": list(ov.get("contributors") or []),
                "samples": entry.get("samples", 0),
                "featured": bool(ov.get("featured", False)),
                "url": f"{INSPECT_HARBOR_DOCS_BASE}/registry/{function_name}.html",
            }
        )

    return records, missing_category
