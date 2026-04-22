import json
import re
from pathlib import Path

import yaml

try:
    PATH = Path(__file__).parent
except NameError:
    PATH = Path.cwd()

CATEGORY_ORDER = [
    "Sandboxes",
    "Analysis",
    "Frameworks",
    "Tooling",
]

with open(PATH / "extensions.yml", "r") as f:
    records = yaml.safe_load(f)

# Compute count of inspect_evals (rounded down to nearest 10) to substitute
# into the Inspect Evals description.
evals_json = PATH.parent / "evals" / "evals.json"
inspect_evals_count = sum(
    1 for r in json.loads(evals_json.read_text()) if r.get("source") == "evals"
)
inspect_evals_count_floor = (inspect_evals_count // 10) * 10


def parse_md_link(s: str) -> tuple[str, str | None]:
    """Parse a [label](url) markdown link. Returns (label, url) or (s, None)."""
    m = re.match(r"\[(.+?)\]\((.+?)\)", (s or "").strip())
    if m:
        return m.group(1), m.group(2)
    return (s or "").strip(), None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


items: list[dict] = []
for record in records:
    name, url = parse_md_link(record.get("name", ""))
    author, author_url = parse_md_link(record.get("author", ""))
    desc = (record.get("description") or "").strip().replace("\n", " ")
    desc = desc.replace("{INSPECT_EVALS_COUNT}", str(inspect_evals_count_floor))
    categories = record.get("categories") or ["Tooling"]
    items.append(
        {
            "id": slugify(name),
            "name": name,
            "url": url or "",
            "desc": desc,
            "author": author,
            "author_url": author_url or "",
            "categories": categories,
        }
    )

# Sort items by category order
cat_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
items.sort(
    key=lambda x: (
        cat_rank.get((x["categories"] or ["Tooling"])[0], 99)
    )
)

with open(PATH / "extensions.json", "w") as f:
    json.dump(items, f, indent=2)
