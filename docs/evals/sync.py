"""Load inspect_evals eval.yaml files into normalized EvalRecord dicts.

Reads `{inspect_evals}/src/inspect_evals/*/eval.yaml` and emits records matching
the design schema consumed by the /docs/evals SPA. Categories come from the
upstream `group` field plus optional additions from `evals_overrides.yml`.
Writes are handled by sync_all.py — this module only loads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).parent
OVERLAY_FILE = HERE / "evals_overrides.yml"

CATEGORY_VOCAB = {
    "Coding", "Assistants", "Cybersecurity", "Safeguards", "Mathematics",
    "Reasoning", "Knowledge", "Science", "Biology", "Chemistry", "Physics",
    "Professional", "Finance", "Medicine", "Law", "Multimodal", "Scheming",
    "Behavior",
}


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    for sep in (". ", "! ", "? "):
        idx = text.find(sep)
        if idx != -1:
            return text[: idx + 1]
    return text


def _derive_kind(tags: list[str]) -> str:
    tag_set = {t.lower() for t in tags}
    if "multimodal" in tag_set:
        return "multimodal"
    if "agent" in tag_set:
        return "agent"
    if "knowledge" in tag_set:
        return "qa"
    return "generation"


def _derive_modalities(tags: list[str], metadata: dict[str, Any]) -> list[str]:
    tag_set = {t.lower() for t in tags}
    mods: list[str] = []
    if "agent" in tag_set:
        mods.append("agent")
    if "tools" in tag_set or "tool-use" in tag_set:
        mods.append("tool-use")
    if metadata.get("sandbox"):
        mods.append("sandbox")
    if "multimodal" in tag_set:
        mods.append("vision")
    if "multi-turn" in tag_set:
        mods.append("multi-turn")
    if not mods:
        mods.append("text")
    return mods


def _derive_samples(tasks: list[dict[str, Any]]) -> int | None:
    for task in tasks or []:
        n = task.get("dataset_samples")
        if isinstance(n, int):
            return n
    return None


def _load_overlay() -> dict[str, dict[str, Any]]:
    if not OVERLAY_FILE.exists():
        return {}
    data = yaml.safe_load(OVERLAY_FILE.read_text()) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _to_record(
    yaml_path: Path,
    inspect_evals_path: Path,
    overlay: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    data = yaml.safe_load(yaml_path.read_text())
    slug = yaml_path.parent.name
    tags = data.get("tags") or []
    metadata = data.get("metadata") or {}
    ov = overlay.get(slug, {})

    group = data.get("group", "Other")
    if "categories" in ov:
        categories = list(ov["categories"])
    else:
        categories = [group]

    paper = ov.get("arxiv") or ov.get("paper") or data.get("arxiv")

    return {
        "id": slug,
        "name": data.get("title", slug),
        "source": "evals",
        "categories": categories,
        "tags": list(tags),
        "kind": _derive_kind(tags),
        "modalities": _derive_modalities(tags, metadata),
        "desc": _first_sentence((data.get("description") or "").strip()),
        "paper": paper,
        "code": f"inspect_evals/{slug}",
        "contributors": list(data.get("contributors") or []),
        "samples": _derive_samples(data.get("tasks") or []),
        "featured": False,
    }


def load_evals(inspect_evals_path: Path) -> list[dict[str, Any]]:
    overlay = _load_overlay()
    records: list[dict[str, Any]] = []
    for yaml_path in sorted((inspect_evals_path / "src" / "inspect_evals").glob("*/eval.yaml")):
        records.append(_to_record(yaml_path, inspect_evals_path, overlay))
    return records
