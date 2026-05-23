"""Emit a Markdown listing of Inspect evals to stdout.

Invoked by inspect-docs post-render as the `llms-script` for
`evals/index.qmd` (see frontmatter). The script receives the page's main
HTML on stdin and ignores it — the SPA placeholder has no useful
content. We instead read the committed `evals.json` (produced by
`sync_all.py`) and emit a categorized listing.
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
    seen_traits: set[str] = set()
    for t in [r.get("kind") or "", *(r.get("modalities") or [])]:
        if t and t not in seen_traits:
            traits.append(t)
            seen_traits.add(t)
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
    # Drain stdin so the parent process doesn't block on a broken pipe.
    sys.stdin.read()

    data = json.loads((PATH / "evals.json").read_text())

    by_cat: dict[str, list[dict]] = {}
    for r in data:
        cat = (r.get("categories") or ["Other"])[0]
        by_cat.setdefault(cat, []).append(r)

    out: list[str] = ["# Evals", ""]

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

    for cat in sorted(set(by_cat) - seen_cats):
        out.append(f"## {cat}")
        out.append("")
        for r in sorted(by_cat[cat], key=lambda x: x["name"].lower()):
            out.extend(_format_record(r))
        out.append("")

    sys.stdout.write("\n".join(out).rstrip() + "\n")


main()
