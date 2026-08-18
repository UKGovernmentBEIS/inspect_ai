"""Emit a Markdown listing of Inspect extensions to stdout.

Invoked by inspect-docs post-render as the `llms-script` for
`extensions/index.qmd` (see frontmatter). The script receives the page's
main HTML on stdin and ignores it — the SPA placeholder has no useful
content. We instead read the already-generated `extensions.json` (built
by `generate.py` when the page renders) and emit a categorized listing.
"""

import json
import sys
from pathlib import Path

PATH = Path(__file__).parent

CATEGORY_ORDER = [
    "Sandboxes",
    "Analysis",
    "Frameworks",
    "Tooling",
]


def _format_record(item: dict) -> list[str]:
    url = item.get("url") or ""
    name = item["name"]
    author = item.get("author") or ""
    author_url = item.get("author_url") or ""

    link = f"[{name}]({url})" if url else name
    if author and author_url:
        attribution = f"[{author}]({author_url})"
    else:
        attribution = author

    header = f"- **{link}**" + (f" — {attribution}" if attribution else "")
    desc = (item.get("desc") or "").strip()
    return [header, f"  {desc}"] if desc else [header]


def main() -> None:
    # Drain stdin so the parent process doesn't block on a broken pipe.
    sys.stdin.read()

    items = json.loads((PATH / "extensions.json").read_text())

    by_cat: dict[str, list[dict]] = {}
    for it in items:
        cat = (it.get("categories") or ["Tooling"])[0]
        by_cat.setdefault(cat, []).append(it)

    out: list[str] = ["# Inspect Extensions", ""]

    seen: set[str] = set()
    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat) or []
        if not rows:
            continue
        seen.add(cat)
        out.append(f"## {cat}")
        out.append("")
        for it in sorted(rows, key=lambda x: x["name"].lower()):
            out.extend(_format_record(it))
        out.append("")

    for cat in sorted(set(by_cat) - seen):
        out.append(f"## {cat}")
        out.append("")
        for it in sorted(by_cat[cat], key=lambda x: x["name"].lower()):
            out.extend(_format_record(it))
        out.append("")

    sys.stdout.write("\n".join(out).rstrip() + "\n")


main()
