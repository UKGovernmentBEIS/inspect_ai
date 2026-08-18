"""Post-render script for inspect-docs extension.

Generates per-page Markdown (.html.md) files and structured llms.txt output:
1. Converts rendered HTML pages to Markdown via pandoc
2. Generates a structured llms.txt using navigation + navbar and page descriptions
3. Generates llms-full.txt and llms-guide.txt concatenated docs
"""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

# import shared discovery helpers from extension root (this file's directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _discover import discover_module_name  # noqa: E402

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
        navbar: YamlDict = (config.get("website") or {}).get("navbar") or {}
        generate_llms_txt(output_dir, opts, navbar)
        generate_llms_full_and_guide(output_dir, opts, navbar)


def generate_html_md_files(output_dir: Path, output_files: list[Path] | None) -> None:
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

        md_path = html_path.with_name(html_path.name.removesuffix(".html") + ".html.md")
        qmd_path = Path(str(rel).removesuffix(".html") + ".qmd")
        convert_html_to_md(html_path, md_path, qmd_path)


def convert_html_to_md(
    html_path: Path, md_path: Path, qmd_path: Path | None = None
) -> None:
    """Convert a rendered HTML page to Markdown.

    By default runs pandoc with the bundled `llms.lua` filter. If the
    source `.qmd` declares an `llms-script:` frontmatter field, that
    script is invoked instead: it receives the extracted main content
    on stdin and is expected to emit the full `.html.md` body on
    stdout. The script path is resolved relative to the `.qmd` file;
    `.py` scripts run via `python`, anything else is executed directly.

    Cached: skips the subprocess when the inputs that drive it
    (extracted main content, title, filter or script mtime) are
    unchanged from the previous run, recorded in a sidecar
    `<md_path>.sha` file.
    """
    # Extract just the <main class="content"> section to avoid
    # converting navigation chrome that the Lua filter would need to strip.
    html_content = html_path.read_text(encoding="utf-8")
    main_content = extract_main_content(html_content)

    # Extract the title from the HTML
    title = extract_html_title(html_content)

    # Resolve optional user-provided llms-script (relative to the .qmd).
    llms_script: Path | None = None
    if qmd_path is not None and qmd_path.exists():
        fm = read_frontmatter(qmd_path) or {}
        script_value = fm.get("llms-script")
        if script_value:
            candidate = (qmd_path.parent / str(script_value)).resolve()
            if candidate.exists():
                llms_script = candidate
            else:
                sys.stderr.write(
                    f"llms-script {script_value!r} declared in {qmd_path} "
                    f"not found at {candidate} — falling back to pandoc.\n"
                )

    # Cache key: hash the inputs the subprocess depends on. Including
    # the filter or script mtime invalidates the cache when either
    # changes.
    digest = hashlib.sha256()
    digest.update(main_content.encode("utf-8"))
    digest.update(b"|")
    digest.update((title or "").encode("utf-8"))
    digest.update(b"|")
    if llms_script is not None:
        digest.update(b"script:")
        digest.update(str(llms_script).encode("utf-8"))
        digest.update(b"|")
        digest.update(str(llms_script.stat().st_mtime_ns).encode("ascii"))
    else:
        digest.update(b"lua:")
        digest.update(str(_LLMS_LUA.stat().st_mtime_ns).encode("ascii"))
    sha = digest.hexdigest()

    sha_path = md_path.with_suffix(md_path.suffix + ".sha")
    if md_path.exists() and sha_path.exists():
        try:
            if sha_path.read_text().strip() == sha:
                return  # cache hit
        except OSError:
            pass

    if llms_script is not None:
        md_text = run_llms_script(llms_script, main_content)
        if md_text is None:
            return
        md_path.write_text(md_text, encoding="utf-8")
        sha_path.write_text(sha)
        return

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
            sha_path.write_text(sha)
    finally:
        os.unlink(tmp_path)


def run_llms_script(script: Path, main_content: str) -> str | None:
    """Invoke a user `llms-script` with HTML on stdin, return markdown stdout.

    Returns the script's stdout on success, or `None` on failure (with
    a message written to stderr). `.py` scripts are run via `python`;
    anything else is invoked directly and must be executable.
    """
    if script.suffix == ".py":
        cmd = ["python", str(script)]
    else:
        cmd = [str(script)]
    result = subprocess.run(
        cmd,
        input=main_content,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"llms-script {script} exited with {result.returncode}\n{result.stderr}"
        )
        return None
    return result.stdout


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


def generate_llms_txt(output_dir: Path, opts: YamlDict, navbar: YamlDict) -> None:
    """Generate a structured llms.txt from inspect-docs navigation config."""
    title: str = opts.get("title", "") or extract_h1(Path("index.qmd")) or ""
    description: str = opts.get("description", "")
    base_url: str = opts.get("url", "").rstrip("/")
    module_name: str | None = opts.get("module") or discover_module_name()
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

    # navbar sections (top-level pages not under navigation or reference)
    covered_hrefs = {str(p) for p in _collect_nav_qmd_paths(navigation)}
    lines.extend(format_navbar_sections(navbar, base_url, covered_hrefs))

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


def format_navbar_sections(
    navbar: YamlDict, base_url: str, covered_hrefs: set[str]
) -> list[str]:
    """Format `website.navbar` items as llms.txt sections.

    Picks up top-level pages reachable from the navbar but not already covered
    by `inspect-docs.navigation` or `reference/`.
    """
    lines: list[str] = []
    for section_text, qmd_path in _collect_navbar_qmd_paths(navbar):
        href = str(qmd_path)
        if href in covered_hrefs:
            continue
        if qmd_path.parts and qmd_path.parts[0] == "reference":
            continue
        entry = format_nav_entry(href, "", base_url)
        if not entry:
            continue
        covered_hrefs.add(href)
        if section_text:
            lines.append(f"## {section_text}")
            lines.append("")
        lines.append(entry)
        lines.append("")
    return lines


def format_reference_section(module_name: str, base_url: str) -> list[str]:
    """Format reference docs into an llms.txt section."""
    ref_dir = Path("reference")
    if not ref_dir.is_dir():
        return []

    entries: list[str] = []
    for qmd in sorted(ref_dir.glob("*.qmd")):
        frontmatter = read_frontmatter(qmd) or {}
        is_user_index = qmd.stem == "index" and bool(frontmatter.get("reference"))

        if qmd.stem == "index" and not is_user_index:
            # Auto-generated landing page — skip.
            continue

        if not is_user_index:
            stem = qmd.stem
            is_api = stem == module_name or stem.startswith(f"{module_name}.")
            is_cli = stem.startswith(f"{module_name}_")
            if not is_api and not is_cli:
                continue

        title = frontmatter.get("title", qmd.stem)
        description = frontmatter.get("description", "")
        url = qmd_to_url(str(qmd), base_url)

        if description:
            entries.append(f"- [{title}]({url}): {description}")
        else:
            entries.append(f"- [{title}]({url})")

    if not entries:
        return []

    return ["## Reference", "", *entries, ""]


def generate_llms_full_and_guide(
    output_dir: Path, opts: YamlDict, navbar: YamlDict
) -> None:
    """Generate `llms-full.txt` and `llms-guide.txt` at the site root.

    Both files are a concatenation of every page's rendered Markdown
    source (`.html.md`) in navigation order, prefixed with the site
    title and description:

    - `llms-full.txt`  -- every page, including reference docs.
    - `llms-guide.txt` -- every page except anything under `reference/`.

    Navbar pages (`website.navbar`) that aren't already covered by
    `inspect-docs.navigation` or `reference/` are appended last.
    """
    title: str = opts.get("title", "")
    description: str = opts.get("description", "")
    navigation: list[YamlDict] = opts.get("navigation", [])

    nav_paths = _collect_nav_qmd_paths(navigation)
    ref_paths = _collect_reference_qmd_paths()

    nav_set = {str(p) for p in nav_paths}
    ref_set = {str(p) for p in ref_paths}
    navbar_extra: list[Path] = []
    for _section, qmd_path in _collect_navbar_qmd_paths(navbar):
        key = str(qmd_path)
        if key in nav_set or key in ref_set:
            continue
        if qmd_path.parts and qmd_path.parts[0] == "reference":
            continue
        navbar_extra.append(qmd_path)

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

    # llms-guide.txt: navigation + navbar pages, excluding reference/
    guide_parts: list[str] = [header_text] if header_text else []
    seen: set[str] = set()
    for qmd in list(nav_paths) + list(navbar_extra):
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

    # llms-full.txt: navigation + all reference + navbar pages
    full_parts: list[str] = [header_text] if header_text else []
    seen = set()
    for qmd in list(nav_paths) + list(ref_paths) + list(navbar_extra):
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


def _collect_navbar_qmd_paths(navbar: YamlDict) -> list[tuple[str, Path]]:
    """Walk `website.navbar` and return `(section_text, qmd_path)` pairs."""
    out: list[tuple[str, Path]] = []

    def walk(items: list[YamlDict], inherited_section: str = "") -> None:
        for item in items:
            text = item.get("text", "") or inherited_section
            href = item.get("href")
            if isinstance(href, str) and href.endswith(".qmd"):
                out.append((text, Path(href)))
            children = item.get("menu") or item.get("contents")
            if isinstance(children, list):
                walk(children, inherited_section=text)

    for side in ("left", "right"):
        items = navbar.get(side) or []
        if isinstance(items, list):
            walk(items)
    return out


def _collect_reference_qmd_paths() -> list[Path]:
    """Return all `.qmd` files under `reference/` except the auto-generated index.

    A user-authored `index.qmd` (carrying a `reference:` frontmatter field —
    single-page reference mode) is included; the auto-generated landing page
    (no such field) is excluded.
    """
    ref_dir = Path("reference")
    if not ref_dir.is_dir():
        return []
    paths: list[Path] = []
    for qmd in sorted(ref_dir.glob("*.qmd")):
        if qmd.stem == "index":
            fm = read_frontmatter(qmd) or {}
            if not fm.get("reference"):
                continue
        paths.append(qmd)
    return paths


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
