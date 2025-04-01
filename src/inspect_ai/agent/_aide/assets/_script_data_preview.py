#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

import humanize
import pandas as pd
from genson import SchemaBuilder


def get_file_len_size(f: Path) -> tuple[int, str]:
    """Calculate the size of a file (#lines for plaintext files, otherwise #bytes)"""
    if f.suffix in plaintext_files:
        num_lines = sum(1 for _ in open(f))
        return num_lines, f"{num_lines} lines"
    else:
        s = f.stat().st_size
        return s, humanize.naturalsize(s)


def file_tree(path: Path, depth=0) -> str:
    """Generate a tree structure of files in a directory"""
    result = []
    files = [p for p in Path(path).iterdir() if not p.is_dir()]
    dirs = [p for p in Path(path).iterdir() if p.is_dir()]
    max_n = 4 if len(files) > 30 else 8
    for p in sorted(files)[:max_n]:
        result.append(f"{' ' * depth * 4}{p.name} ({get_file_len_size(p)[1]})")
    if len(files) > max_n:
        result.append(f"{' ' * depth * 4}... and {len(files) - max_n} other files")

    for p in sorted(dirs):
        result.append(f"{' ' * depth * 4}{p.name}/")
        result.append(file_tree(p, depth + 1))

    return "\n".join(result)


def _walk(path: Path):
    """Recursively walk a directory"""
    for p in sorted(Path(path).iterdir()):
        if p.is_dir():
            yield from _walk(p)
            continue
        yield p


def preview_csv(p: Path, file_name: str, simple=True) -> str:
    """Generate a textual preview of a csv file"""
    df = pd.read_csv(p)
    out = []
    out.append(f"-> {file_name} has {df.shape[0]} rows and {df.shape[1]} columns.")

    if simple:
        cols = df.columns.tolist()
        sel_cols = 15
        cols_str = ", ".join(cols[:sel_cols])
        res = f"The columns are: {cols_str}"
        if len(cols) > sel_cols:
            res += f"... and {len(cols) - sel_cols} more columns"
        out.append(res)
    else:
        out.append("Here is some information about the columns:")
        for col in sorted(df.columns):
            dtype = df[col].dtype
            name = f"{col} ({dtype})"
            nan_count = df[col].isnull().sum()

            if dtype == "bool":
                v = df[col][df[col].notnull()].mean()
                out.append(f"{name} is {v * 100:.2f}% True, {100 - v * 100:.2f}% False")
            elif df[col].nunique() < 10:
                out.append(
                    f"{name} has {df[col].nunique()} unique values: {df[col].unique().tolist()}"
                )
            elif pd.api.types.is_numeric_dtype(df[col]):
                out.append(
                    f"{name} has range: {df[col].min():.2f} - {df[col].max():.2f}, {nan_count} nan values"
                )
            elif dtype == "object":
                out.append(
                    f"{name} has {df[col].nunique()} unique values. Some example values: {df[col].value_counts().head(4).index.tolist()}"
                )

    return "\n".join(out)


def preview_json(p: Path, file_name: str):
    """Generate a textual preview of a json file using a generated json schema"""
    builder = SchemaBuilder()
    with open(p) as f:
        builder.add_object(json.load(f))
    return f"-> {file_name} has auto-generated json schema:\n" + builder.to_json(
        indent=2
    )


def generate(base_path: Path, include_file_details=True, simple=False):
    """Generate a textual preview of a directory"""
    tree = f"Directory structure:\n{file_tree(base_path)}"
    out = [tree]

    if include_file_details:
        for fn in _walk(base_path):
            file_name = str(fn.relative_to(base_path))

            if fn.suffix == ".csv":
                out.append(preview_csv(fn, file_name, simple=simple))
            elif fn.suffix == ".json":
                out.append(preview_json(fn, file_name))
            elif fn.suffix in plaintext_files:
                if get_file_len_size(fn)[0] < 30:
                    with open(fn) as f:
                        content = f.read()
                        if fn.suffix in code_files:
                            stuff = content.replace("\n", "\n    ")
                            content = f"    {stuff}"
                        out.append(f"-> {file_name} has content:\n\n{content}")

    result = "\n\n".join(out)

    if len(result) > 6_000 and not simple:
        return generate(
            base_path, include_file_details=include_file_details, simple=True
        )

    return result


def main():
    # Define command line arguments
    parser = argparse.ArgumentParser(
        description="Generate a preview of files in a directory"
    )
    parser.add_argument("path", type=str, help="Path to the directory to preview")
    parser.add_argument(
        "--simple", "-s", action="store_true", help="Use simplified preview format"
    )
    parser.add_argument(
        "--no-details", "-n", action="store_true", help="Skip file details"
    )
    args = parser.parse_args()

    # Define file type sets
    global code_files, plaintext_files
    code_files = {".py", ".sh", ".yaml", ".yml", ".md", ".html", ".xml", ".log", ".rst"}
    plaintext_files = {".txt", ".csv", ".json", ".tsv"} | code_files

    # Check if path exists
    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path '{args.path}' does not exist", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"Error: Path '{args.path}' is not a directory", file=sys.stderr)
        sys.exit(1)

    try:
        # Generate and print the preview
        preview = generate(
            path, include_file_details=not args.no_details, simple=args.simple
        )
        print(preview)
    except Exception as e:
        print(f"Error generating preview: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
