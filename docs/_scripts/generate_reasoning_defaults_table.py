"""Generate a Markdown table of reasoning_effort defaults.

Reads each `src/inspect_ai/model/_model_data/*.yml` directly (rather than via
`read_model_info()`, which expands every version/alias) so each model family
appears once. Writes `docs/_reasoning-defaults.md`, which is included by
`docs/reasoning.qmd`.

Run from repo root:

    python docs/_scripts/generate_reasoning_defaults_table.py

CI can diff the generated file against the committed copy to detect drift.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "src" / "inspect_ai" / "model" / "_model_data"
OUTPUT = REPO_ROOT / "docs" / "_reasoning-defaults.md"


def render_default(value: str) -> str:
    if value == "adaptive":
        return "adaptive"
    if value == "fixed":
        return "no effort scale"
    return value


def main() -> None:
    rows: list[tuple[str, str]] = []  # (inspect_model_name, default)

    for yml_path in sorted(DATA_DIR.glob("*.yml")):
        with open(yml_path) as f:
            data = yaml.safe_load(f) or {}
        for provider_key, provider_data in data.items():
            prefix = provider_key.lower()
            for model_name, model_def in (provider_data.get("models") or {}).items():
                if not model_def.get("reasoning"):
                    continue
                default = model_def.get("reasoning_effort_default")
                if not default:
                    continue
                rows.append((f"{prefix}/{model_name}", render_default(default)))

    rows.sort()

    lines = ["| Model | Default effort |", "|---|---|"]
    for name, default in rows:
        lines.append(f"| {name} | {default} |")
    lines.append("")

    OUTPUT.write_text("\n".join(lines))
    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
