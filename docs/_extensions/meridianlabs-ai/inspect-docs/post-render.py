"""Post-render script for inspect-docs extension.

Generates per-page Markdown (.html.md) files and structured llms.txt output:
1. Converts rendered HTML pages to Markdown via pandoc
2. Generates a structured llms.txt using navigation config and page descriptions
3. Generates llms-full.txt and llms-guide.txt concatenated docs
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

YamlDict = dict[str, Any]

# Resolve path to the Lua filter bundled with this extension
_FILTER_DIR = Path(__file__).resolve().parent / "filters"
_LLMS_LUA = _FILTER_DIR / "llms.lua"

# HTML files to skip when generating .html.md
_SKIP_FILES = {"404.html", "sitemap.xml"}


def main() -> None:
    output_dir = Path(os.environ["QUARTO_PROJECT_OUTPUT_DIR"])
    render_all = os.environ.get("QUARTO_PROJECT_RENDER_ALL") == "1"

    # determine which output files were rendered
    output_files: list[Path] | None = None
    if not render_all:
        raw = os.environ.get("QUARTO_PROJECT_OUTPUT_FILES", "")
        output_files = [Path(f) for f in raw.splitlines() if f.strip()]

    # step 1: generate .html.md for rendered pages
    generate_html_md_files(output_dir, output_files)

    # step 2: generate structured llms.txt (full render only)
    if render_all:
        with open("_quarto.yml", "r") as f:
            config: YamlDict = yaml.safe_load(f)
        opts: YamlDict = config.get("inspect-docs", {})
        generate_llms_txt(output_dir, opts)
        generate_llms_full_and_guide(output_dir, opts)


def generate_html_md_files(
    output_dir: Path, output_files: list[Path] | None
) -> None:
    """Convert rendered HTML pages to Markdown using pandoc."""
    if output_files is not None:
        # incremental: only process rendered HTML files
        html_files = [f for f in output_files if f.name.endswith(".html")]
    else:
        # full render: process all HTML files
        html_files = list(output_dir.rglob("*.html"))

    for html_path in html_files:
        if html_path.name in _SKIP_FILES:
            continue
        # skip site_libs and other non-content directories
        try:
            rel = html_path.relative_to(output_dir)
        except ValueError:
            continue
        if str(rel).startswith("site_libs"):
            continue

        md_path = html_path.with_name(
            html_path.name.removesuffix(".html") + ".html.md"
        )
        convert_html_to_md(html_path, md_path)


def convert_html_to_md(html_path: Path, md_path: Path) -> None:
    """Run pandoc to convert an HTML file to GFM Markdown."""
    # Extract just the <main class="content"> section to avoid
    # converting navigation chrome that the Lua filter would need to strip.
    html_content = html_path.read_text(encoding="utf-8")
    main_content = extract_main_content(html_content)

    # Extract the title from the HTML
    title = extract_html_title(html_content)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(main_content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "quarto",
                "pandoc",
                tmp_path,
                "-f",
                "html",
                "-t",
                "gfm-raw_html",
                "--lua-filter",
                str(_LLMS_LUA),
                "--wrap=none",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            md_text = result.stdout
            # Prepend title as H1 if we extracted one
            if title:
                md_text = f"# {title}\n\n{md_text}"
            md_path.write_text(md_text, encoding="utf-8")
    finally:
        os.unlink(tmp_path)


def extract_main_content(html: str) -> str:
    """Extract content from <main class="content" ...> to </main>."""
    match = re.search(
        r'<main\s[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</main>',
        html,
        re.DOTALL,
    )
    if match:
        return match.group(1)
    # Fallback: try <main> without class
    match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL)
    if match:
        return match.group(1)
    # Last resort: return the full body
    match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
    if match:
        return match.group(1)
    return html


def extract_html_title(html: str) -> str | None:
    """Extract the <title> text from an HTML page."""
    match = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def generate_llms_txt(output_dir: Path, opts: YamlDict) -> None:
    """Generate a structured llms.txt from inspect-docs navigation config."""
    title: str = opts.get("title", "") or extract_h1(Path("index.qmd")) or ""
    description: str = opts.get("description", "")
    base_url: str = opts.get("url", "").rstrip("/")
    module_name: str | None = opts.get("module")
    navigation: list[YamlDict] = opts.get("navigation", [])

    lines: list[str] = []

    # header
    lines.append(f"# {title}")
    lines.append("")
    if description:
        lines.append(f"> {description}")
        lines.append("")

    # navigation sections
    lines.extend(format_navigation_sections(navigation, base_url))

    # reference section (auto-discovered)
    if module_name:
        lines.extend(format_reference_section(module_name, base_url))

    (output_dir / "llms.txt").write_text("\n".join(lines))


def format_navigation_sections(navigation: list[YamlDict], base_url: str) -> list[str]:
    """Format navigation items into llms.txt sections."""
    lines: list[str] = []

    for item in navigation:
        section_title = item.get("text", "")
        if section_title:
            lines.append(f"## {section_title}")
            lines.append("")

        # Accept either `contents:` or `menu:` as the nesting key
        children = item.get("contents") or item.get("menu")
        if isinstance(children, list):
            for content_item in children:
                entry = format_nav_entry(
                    content_item.get("href", ""),
                    content_item.get("text", ""),
                    base_url,
                )
                if entry:
                    lines.append(entry)
        else:
            entry = format_nav_entry(
                item.get("href", ""), item.get("text", ""), base_url
            )
            if entry:
                lines.append(entry)

        lines.append("")

    return lines


def format_nav_entry(href: str, text: str, base_url: str) -> str | None:
    """Format a single navigation entry as an llms.txt list item."""
    if not href:
        return None

    qmd_path = Path(href)
    description = ""
    if qmd_path.exists():
        frontmatter = read_frontmatter(qmd_path)
        if frontmatter:
            description = frontmatter.get(
                "description", frontmatter.get("llms-description", "")
            )
            if not text:
                text = frontmatter.get("title", qmd_path.stem)

    if not text:
        text = qmd_path.stem

    url = qmd_to_url(href, base_url)

    if description:
        return f"- [{text}]({url}): {description}"
    return f"- [{text}]({url})"


def format_reference_section(module_name: str, base_url: str) -> list[str]:
    """Format reference docs into an llms.txt section."""
    ref_dir = Path("reference")
    if not ref_dir.is_dir():
        return []

    entries: list[str] = []
    for qmd in sorted(ref_dir.glob("*.qmd")):
        if qmd.stem == "index":
            continue

        stem = qmd.stem
        is_api = stem == module_name or stem.startswith(f"{module_name}.")
        is_cli = stem.startswith(f"{module_name}_")
        if not is_api and not is_cli:
            continue

        frontmatter = read_frontmatter(qmd)
        title = frontmatter.get("title", stem) if frontmatter else stem
        description = frontmatter.get("description", "") if frontmatter else ""
        url = qmd_to_url(str(qmd), base_url)

        if description:
            entries.append(f"- [{title}]({url}): {description}")
        else:
            entries.append(f"- [{title}]({url})")

    if not entries:
        return []

    return ["## Reference", "", *entries, ""]


def generate_llms_full_and_guide(output_dir: Path, opts: YamlDict) -> None:
    """Generate `llms-full.txt` and `llms-guide.txt` at the site root.

    Both files are a concatenation of every page's rendered Markdown
    source (`.html.md`) in navigation order, prefixed with the site
    title and description:

    - `llms-full.txt`  -- every page, including reference docs.
    - `llms-guide.txt` -- every page except anything under `reference/`.
    """
    title: str = opts.get("title", "")
    description: str = opts.get("description", "")
    navigation: list[YamlDict] = opts.get("navigation", [])

    nav_paths = _collect_nav_qmd_paths(navigation)
    ref_paths = _collect_reference_qmd_paths()

    header: list[str] = []
    if title:
        header.append(f"# {title}")
        header.append("")
    if description:
        header.append(f"> {description}")
        header.append("")
    header_text = "\n".join(header)

    def read_html_md(qmd: Path) -> str:
        # .qmd -> .html.md (doesn't use with_suffix because of double suffix)
        rel = str(qmd).removesuffix(".qmd") + ".html.md"
        html_md = output_dir / rel
        return html_md.read_text() if html_md.exists() else ""

    # llms-guide.txt: navigation pages only, excluding reference/
    guide_parts: list[str] = [header_text] if header_text else []
    seen: set[str] = set()
    for qmd in nav_paths:
        if qmd.parts and qmd.parts[0] == "reference":
            continue
        key = str(qmd)
        if key in seen:
            continue
        seen.add(key)
        body = read_html_md(qmd)
        if body:
            guide_parts.append(body)
    (output_dir / "llms-guide.txt").write_text("\n\n".join(guide_parts))

    # llms-full.txt: navigation pages + all reference pages
    full_parts: list[str] = [header_text] if header_text else []
    seen = set()
    for qmd in list(nav_paths) + list(ref_paths):
        key = str(qmd)
        if key in seen:
            continue
        seen.add(key)
        body = read_html_md(qmd)
        if body:
            full_parts.append(body)
    (output_dir / "llms-full.txt").write_text("\n\n".join(full_parts))


def _collect_nav_qmd_paths(navigation: list[YamlDict]) -> list[Path]:
    """Walk the navigation tree in order and return every `href` as a Path."""
    paths: list[Path] = []

    def walk(items: list[YamlDict]) -> None:
        for item in items:
            href = item.get("href")
            if isinstance(href, str) and href.endswith(".qmd"):
                paths.append(Path(href))
            children = item.get("contents") or item.get("menu")
            if isinstance(children, list):
                walk(children)

    walk(navigation)
    return paths


def _collect_reference_qmd_paths() -> list[Path]:
    """Return all `.qmd` files under `reference/` except the auto-generated index."""
    ref_dir = Path("reference")
    if not ref_dir.is_dir():
        return []
    return [qmd for qmd in sorted(ref_dir.glob("*.qmd")) if qmd.stem != "index"]


def qmd_to_url(href: str, base_url: str) -> str:
    """Convert a .qmd path to an absolute .html.md URL."""
    html_md = href.replace(".qmd", ".html.md")
    return f"{base_url}/{html_md}"


def extract_h1(path: Path) -> str | None:
    """Extract the first H1 heading from a markdown file."""
    if not path.exists():
        return None
    target = path.resolve()
    if not target.exists():
        return None
    for line in target.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped.removeprefix("# ").strip()
    return None


def read_frontmatter(path: Path) -> dict[str, str] | None:
    """Read YAML frontmatter from a .qmd file."""
    text = path.read_text()
    if not text.startswith("---"):
        return None
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end])  # type: ignore[no-any-return]


if __name__ == "__main__":
    main()
