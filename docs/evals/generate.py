"""Emit `_evals_content.md` from the already-synced `evals.json`.

Runs as a Quarto project pre-render script (wired in `_quarto.yml`).
The generated Markdown is included by `index.qmd` and hidden via CSS;
pandoc picks it up when converting the rendered HTML to `index.html.md`,
making the page LLM-readable.
"""

import json
import sys
from pathlib import Path

PATH = Path(__file__).parent
sys.path.insert(0, str(PATH))

from sync import CATEGORY_ORDER  # noqa: E402


def _format_record(r: dict) -> list[str]:
    name = r["name"]
    url = r.get("url") or ""
    link = f"[{name}]({url})" if url else name

    facets: list[str] = []
    cats = r.get("categories") or []
    if cats:
        facets.append(", ".join(cats))

    # Merge kind + modalities, deduped while preserving order. kind often
    # repeats a modality (e.g. kind=agent, modalities=[agent, sandbox]).
    traits: list[str] = []
    seen: set[str] = set()
    for t in [r.get("kind") or "", *(r.get("modalities") or [])]:
        if t and t not in seen:
            traits.append(t)
            seen.add(t)
    if traits:
        facets.append(", ".join(traits))

    samples = r.get("samples")
    if isinstance(samples, int):
        facets.append(f"{samples} samples")
    code = r.get("code")
    if code:
        facets.append(f"`{code}`")
    paper = r.get("paper")
    if paper:
        facets.append(f"[paper]({paper})")

    header = f"- **{link}** — " + " · ".join(facets) if facets else f"- **{link}**"
    desc = r.get("desc") or ""
    return [header, f"  {desc}"] if desc else [header]


def main() -> None:
    data = json.loads((PATH / "evals.json").read_text())

    by_cat: dict[str, list[dict]] = {}
    for r in data:
        cat = (r.get("categories") or ["Other"])[0]
        by_cat.setdefault(cat, []).append(r)

    out: list[str] = []
    seen_cats: set[str] = set()
    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat) or []
        if not rows:
            continue
        seen_cats.add(cat)
        out.append(f"## {cat}")
        out.append("")
        for r in sorted(rows, key=lambda x: x["name"].lower()):
            out.extend(_format_record(r))
        out.append("")

    # Any categories outside CATEGORY_ORDER get appended after.
    extras = sorted(set(by_cat) - seen_cats)
    for cat in extras:
        out.append(f"## {cat}")
        out.append("")
        for r in sorted(by_cat[cat], key=lambda x: x["name"].lower()):
            out.extend(_format_record(r))
        out.append("")

    (PATH / "_evals_content.md").write_text("\n".join(out).rstrip() + "\n")


main()
