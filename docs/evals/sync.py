"""Sync inspect_evals eval.yaml files into listing.yml and evals.yml.

Usage:
    python docs/evals/sync.py [path/to/inspect_evals]
"""

import argparse
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent

KEEP_FIELDS = {
    "title", "description", "arxiv", "group", "contributors",
    "tasks", "tags", "metadata", "dependency", "dependency-group",
}

FIELD_ORDER = [
    "title", "description", "path", "arxiv", "group",
    "contributors", "tasks", "tags", "dependency", "dependency-group", "metadata",
]

GROUP_SORT_ORDER = (
    "Coding", "Assistants", "Cybersecurity", "Safeguards",
    "Mathematics", "Reasoning", "Knowledge",
)


class _LiteralStr(str):
    """Serialises as a YAML block scalar (style '|')."""


class _QuotedStr(str):
    """Serialises as a double-quoted YAML scalar."""


class _FlowList(list):
    """Serialises as a YAML flow sequence (["a", "b", "c"])."""


class _ListingDumper(yaml.Dumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # noqa: ARG002
        super().increase_indent(flow=flow, indentless=False)


def _literal_representer(dumper: yaml.Dumper, data: _LiteralStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


def _quoted_str_representer(dumper: yaml.Dumper, data: _QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def _flow_list_representer(dumper: yaml.Dumper, data: _FlowList) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", list(data), flow_style=True)


_ListingDumper.add_representer(_LiteralStr, _literal_representer)
_ListingDumper.add_representer(_QuotedStr, _quoted_str_representer)
_ListingDumper.add_representer(_FlowList, _flow_list_representer)


def _sort_key(record: dict) -> tuple:
    group_index = next(
        (i for i, g in enumerate(GROUP_SORT_ORDER) if g == record["group"]),
        len(GROUP_SORT_ORDER),
    )
    return (group_index, record.get("title", "").lower(), record.get("path", "").lower())


def _prepare_for_yaml(record: dict) -> dict:
    r = {}
    for key in FIELD_ORDER:
        if key not in record:
            continue
        val = record[key]
        if key == "title":
            r[key] = _QuotedStr(val)
        elif key == "description":
            r[key] = _LiteralStr(val.rstrip() + "\n")
        elif key in ("contributors", "tags"):
            r[key] = _FlowList([_QuotedStr(v) for v in val])
        elif key in ("dependency", "dependency-group"):
            r[key] = _QuotedStr(val)
        elif key == "metadata":
            r[key] = {
                mk: _FlowList([_QuotedStr(v) if isinstance(v, str) else v for v in mv])
                if isinstance(mv, list) else mv
                for mk, mv in val.items()
            }
        else:
            r[key] = val
    return r


def load_evals(inspect_evals_path: Path) -> list[dict]:
    records = []
    for yaml_path in sorted((inspect_evals_path / "src" / "inspect_evals").glob("*/eval.yaml")):
        data = yaml.safe_load(yaml_path.read_text())
        rel_path = yaml_path.parent.relative_to(inspect_evals_path)
        record = {"path": str(rel_path)}
        record.update({k: v for k, v in data.items() if k in KEEP_FIELDS})
        records.append(record)
    return sorted(records, key=_sort_key)


def write_listing(records: list[dict]) -> None:
    header = "# Groups: Assistants Bias Coding Cybersecurity Knowledge Mathematics Multimodal Personality Reasoning Safeguards Scheming Writing\n\n"
    chunks = [
        yaml.dump(
            [_prepare_for_yaml(r)],
            Dumper=_ListingDumper,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=2**31 - 1,
        ).rstrip("\n")
        for r in records
    ]
    (HERE / "listing.yml").write_text(header + "\n\n".join(chunks) + "\n")


def write_evals(records: list[dict]) -> None:
    evals = []
    for record in records:
        r = dict(record)
        r["url"] = (
            f"https://ukgovernmentbeis.github.io/inspect_evals/evals/"
            f"{r['group'].lower()}/{r['path'].split('/')[-1]}"
        )
        categories = [r["group"]]
        categories.extend(tag for tag in r.get("tags", []) if tag not in categories)
        r["categories"] = categories
        r["tasks"] = [task["name"] for task in r["tasks"]]
        evals.append(r)

    with open(HERE / "evals.yml", "w") as f:
        yaml.safe_dump(evals, f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inspect_evals_path", nargs="?", default="../inspect_evals", type=Path)
    args = parser.parse_args()

    path = args.inspect_evals_path.resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        sys.exit(1)

    records = load_evals(path)
    write_listing(records)
    write_evals(records)
    print(f"synced {len(records)} evals → listing.yml, evals.yml")


if __name__ == "__main__":
    main()
