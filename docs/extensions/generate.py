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
    "Evals",
]

SECTION_IDS = {
    "Sandboxes": "sec-sandboxes",
    "Analysis": "sec-analysis",
    "Frameworks": "sec-frameworks",
    "Tooling": "sec-tooling",
    "Evals": "sec-evals",
}

with open(PATH / "extensions.yml", "r") as f:
    records = yaml.safe_load(f)

evals_json = PATH.parent / "evals" / "evals.json"
inspect_evals_count = sum(
    1 for r in json.loads(evals_json.read_text()) if r.get("source") == "evals"
)
inspect_evals_count_floor = (inspect_evals_count // 10) * 10

groups: dict[str, list] = {cat: [] for cat in CATEGORY_ORDER}
for record in records:
    cat = record.get("categories", ["Tooling"])[0]
    if cat in groups:
        groups[cat].append(record)

lines = []
for cat, items in groups.items():
    lines.append(f"## {cat} {{#{SECTION_IDS[cat]}}}")
    lines.append("")
    for item in items:
        name = item.get("name", "").strip()
        desc = item.get("description", "").strip().replace("\n", " ")
        desc = desc.replace("{INSPECT_EVALS_COUNT}", str(inspect_evals_count_floor))
        author_raw = item.get("author", "").strip()
        # Convert markdown link to HTML <a> with no underline
        author_match = re.match(r"\[(.+?)\]\((.+?)\)", author_raw)
        if author_match:
            author = f'<a href="{author_match.group(2)}" style="text-decoration:none">{author_match.group(1)}</a>'
        else:
            author = author_raw
        lines.append(f'{name} &mdash; <small>{author}</small>\n:   {desc}')
        lines.append("")
    lines.append("")

with open(PATH / "_extensions_content.md", "w") as f:
    f.write("\n".join(lines))
