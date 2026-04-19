"""Merge inspect_evals and inspect_harbor into a single evals.json.

The /docs/evals SPA consumes this file directly. Schema matches DESIGN_SPEC.md.

Usage:
    python docs/evals/sync_all.py [--inspect-evals PATH] [--no-fetch]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sync import CATEGORY_VOCAB, load_evals
from sync_harbor import load_harbor

HERE = Path(__file__).parent
OUTPUT_FILE = HERE / "evals.json"


def _category_index(cat: str) -> int:
    order = [
        "Coding", "Assistants", "Cybersecurity", "Safeguards", "Mathematics",
        "Reasoning", "Knowledge", "Multimodal", "Scheming", "Bias", "Behavior",
        "Personality", "Writing", "Other",
    ]
    try:
        return order.index(cat)
    except ValueError:
        return len(order)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inspect-evals", default="../inspect_evals", type=Path,
        help="Path to sibling inspect_evals checkout (default: ../inspect_evals)",
    )
    parser.add_argument(
        "--no-fetch", action="store_true",
        help="Reuse cached harbor registry.json and _tasks.py; do not hit the network.",
    )
    args = parser.parse_args()

    inspect_evals_path = args.inspect_evals.resolve()
    if not inspect_evals_path.is_dir():
        print(f"error: {inspect_evals_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    evals_records = load_evals(inspect_evals_path)
    harbor_records, missing_category = load_harbor(use_cache=args.no_fetch)

    if missing_category:
        print(
            f"\nerror: {len(missing_category)} harbor dataset(s) missing required "
            f"'category' in harbor_overrides.yml:",
            file=sys.stderr,
        )
        for name in missing_category:
            print(f"  - {name}", file=sys.stderr)
        print(
            "\nAdd a `category:` entry for each in docs/evals/harbor_overrides.yml "
            "(one of: Coding, Assistants, Cybersecurity, Safeguards, Mathematics, "
            "Reasoning, Knowledge, Multimodal, Scheming, Bias, Behavior, Writing, Other).",
            file=sys.stderr,
        )
        sys.exit(1)

    all_records = evals_records + harbor_records

    unknown = [r for r in all_records if r["category"] not in CATEGORY_VOCAB]
    if unknown:
        print(
            f"\nerror: {len(unknown)} eval(s) have categories outside the vocabulary:",
            file=sys.stderr,
        )
        for r in unknown:
            print(f"  - {r['source']}/{r['id']}: category={r['category']!r}", file=sys.stderr)
        sys.exit(1)

    all_records.sort(key=lambda r: (_category_index(r["category"]), r["name"].lower()))

    OUTPUT_FILE.write_text(json.dumps(all_records, indent=2, ensure_ascii=False) + "\n")

    print(
        f"synced {len(evals_records)} inspect_evals + {len(harbor_records)} "
        f"inspect_harbor = {len(all_records)} total → {OUTPUT_FILE.relative_to(HERE.parent.parent)}"
    )


if __name__ == "__main__":
    main()
