"""Pre-render script for inspect-docs extension.

Generates:
- _include.yml: derived website metadata and reference sidebar
- reference/refs.json: cross-reference index for API docs
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# import shared discovery helpers from extension root (this file's directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _discover import discover_cli_name, discover_module_name  # noqa: E402

# type alias for YAML-style nested dicts
YamlDict = dict[str, Any]


class _NoAliasDumper(yaml.SafeDumper):
    """YAML dumper that never emits anchors/aliases.

    The extension's generated navigation is consumed by Quarto's schema
    validator, which cannot resolve YAML anchors/aliases. Shared dict
    references between the navbar and sidebar would otherwise be emitted
    as `&id001`/`*id001`, which Quarto treats as a schema error.
    """

    def ignore_aliases(self, data):
        return True


# matches markdown ![alt](path) and HTML <img src="path"> / src='path'
_IMG_RE = re.compile(
    r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<img[^>]*\ssrc=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


def main() -> None:
    # read project config
    with open("_quarto.yml", "r") as f:
        config: YamlDict = yaml.safe_load(f)

    opts: YamlDict = config.get("inspect-docs", {})

    # user-provided website overrides (merged with extension defaults)
    user_website: YamlDict = config.get("website") or {}
    user_navbar: YamlDict = user_website.get("navbar") or {}


    # create default .gitignore if none exists
    write_if_changed(
        Path(".gitignore"),
        "/.quarto/\n"
        "/_site/\n"
        "/_include.yml\n"
        "/reference/refs*.json\n"
        "**/*.quarto_ipynb*\n"
        "**/*.excalidraw.svg\n",
    )

    # symlink CHANGELOG.md from repo root if it exists
    changelog_src = Path("../CHANGELOG.md")
    changelog_dst = Path("CHANGELOG.md")
    if changelog_src.exists() and not changelog_dst.exists():
        changelog_dst.symlink_to(changelog_src)

    # symlink README.md from repo root as index.qmd if no index.qmd exists
    index_dst = Path("index.qmd")
    readme_src = Path("../README.md")
    if not index_dst.exists() and readme_src.exists():
        index_dst.symlink_to(readme_src)

    # symlink any images referenced by the README into cwd so the paths
    # resolve when rendering index.qmd from here
    if index_dst.is_symlink() and readme_src.exists():
        symlink_readme_images(readme_src)

    # default navigation if none defined
    has_navigation = "navigation" in opts
    navigation: list[YamlDict] | None = opts.get("navigation")
    if navigation is None:
        navigation = [{"text": "Home", "href": "index.qmd"}]
        opts["navigation"] = navigation

    # resolve title from index file if not explicitly configured
    if "title" not in opts:
        index_title = extract_h1(index_dst)
        if index_title:
            opts["title"] = index_title

    generated: YamlDict = {}

    # generate derived website metadata
    repo: str | None = opts.get("repo")
    if repo is not None:
        generated = generate_website_metadata(opts, repo, user_navbar)

    # build sidebar: user navigation + reference sidebar
    sidebars: list[YamlDict] = []
    sidebar_opt = opts.get("sidebar", has_navigation)
    show_sidebar = sidebar_opt is not False
    unified_sidebar = sidebar_opt == "unified"
    if show_sidebar:
        sidebars.append(
            {
                "title": "Main",
                "style": "docked",
                "contents": nav_to_sidebar(navigation),
            }
        )

    # resolve module name and CLI binary name (with pyproject auto-discovery)
    module_name: str | None = opts.get("module") or discover_module_name()
    cli_name: str | None = opts.get("cli") or (
        discover_cli_name(module_name) if module_name else None
    )

    if Path("reference").is_dir():
        ref_sidebar = generate_reference_artifacts(cli_name)
        if ref_sidebar is not None:
            if unified_sidebar and sidebars:
                ref_contents = ref_sidebar[0]["contents"]
                # The first entry is reference/index.qmd — pull it out
                # to use as the section href (so Quarto associates that
                # page with this sidebar) rather than showing a redundant
                # child link.
                ref_index_href: str | None = None
                if ref_contents and isinstance(ref_contents[0], str):
                    ref_index_href = ref_contents[0]
                    ref_contents = ref_contents[1:]
                # Nest reference items under an existing "Reference"
                # nav entry, or create a new section for them.
                main_contents = sidebars[0]["contents"]
                ref_entry = next(
                    (
                        item
                        for item in main_contents
                        if isinstance(item, dict)
                        and item.get("text", "").lower() == "reference"
                    ),
                    None,
                )
                if ref_entry:
                    ref_entry.pop("text", None)
                    ref_entry["section"] = "Reference"
                    ref_entry["href"] = ref_index_href or ref_entry.get("href")
                    ref_entry["contents"] = ref_contents
                else:
                    entry: YamlDict = dict(
                        section="Reference", contents=ref_contents
                    )
                    if ref_index_href:
                        entry["href"] = ref_index_href
                    main_contents.append(entry)
                sidebars[0]["collapse-level"] = 2
            else:
                sidebars.extend(ref_sidebar)

    # download external refs even when no local reference docs are generated
    ref_dir = Path("reference")
    if ref_dir.is_dir():
        download_external_refs(ref_dir, opts)

    if sidebars:
        generated.setdefault("website", {})["sidebar"] = sidebars

    # install excalidraw conversion dependencies if .excalidraw files exist
    if any(
        p
        for p in Path(".").glob("**/*.excalidraw")
        if not any(
            part.startswith((".", "_")) or part == "node_modules"
            for part in p.parts
        )
    ):
        ensure_excalidraw_deps()

    write_if_changed(
        Path("_include.yml"),
        yaml.dump(generated, sort_keys=False, Dumper=_NoAliasDumper),
    )


def symlink_readme_images(readme_src: Path) -> None:
    """Symlink README-referenced images into cwd mirroring their paths.

    Parses `readme_src` for markdown and HTML image references. For each
    relative reference, symlinks the exact file from the repo root (parent
    of cwd) into the mirrored location inside cwd, creating parent
    directories as needed. This ensures README image paths resolve when
    the README is rendered from cwd (e.g. docs/).
    """
    text = readme_src.read_text(encoding="utf-8")
    seen: set[str] = set()
    for match in _IMG_RE.finditer(text):
        path = match.group(1) or match.group(2)
        if not path or path in seen:
            continue
        seen.add(path)

        # skip absolute URLs, fragments, repo-escaping paths
        if path.startswith(("http://", "https://", "data:", "/", "#", "..")):
            continue

        dst = Path(path)
        parts = dst.parts
        if not parts or any(p in ("..", "") for p in parts):
            continue

        # source relative to repo root (parent of cwd)
        src_from_root = Path("..") / path
        if not src_from_root.exists():
            continue
        if dst.exists() or dst.is_symlink():
            continue

        # symlink target is relative to dst's parent directory:
        # one ".." per path component gets us to repo root, then the path
        target = Path(*([".."] * len(parts))) / path

        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(target)


def ensure_excalidraw_deps() -> None:
    """Install Node.js dependencies for excalidraw SVG conversion if needed."""
    ext_dir = Path(__file__).parent
    excalidraw_dir = ext_dir / "resources" / "excalidraw"
    if (excalidraw_dir / "node_modules").is_dir():
        return
    subprocess.run(
        ["npm", "install", "--prefix", str(excalidraw_dir)],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _build_footer(
    opts: YamlDict,
    repo: str,
    repo_url: str,
    title: str,
    org_name: str,
) -> YamlDict:
    """Build the website.page-footer block.

    Center links: Code, Changelog, License, Issues (all pointing at GitHub).
    Left:         optional org name with `org_url` override (falls back to
                  `https://github.com/{org}`).
    Right:        optional Twitter icon (from `twitter:` config) + GitHub icon.
    """
    footer: YamlDict = {
        "center": [
            {"text": "Code", "href": repo_url},
            {"text": "Changelog", "href": f"{repo_url}/blob/main/CHANGELOG.md"},
            {"text": "License", "href": f"{repo_url}/blob/main/LICENSE"},
            {"text": "Issues", "href": f"{repo_url}/issues"},
        ],
    }

    if org_name:
        org = repo.split("/")[0]
        org_link_url: str = opts.get("org_url") or f"https://github.com/{org}"
        footer["left"] = [{"text": org_name, "href": org_link_url}]

    right: list[YamlDict] = []
    twitter: str = opts.get("twitter", "")
    if twitter:
        right.append(
            {
                "icon": "twitter",
                "href": f"https://x.com/{twitter}",
                "aria-label": f"{title or org_name} Twitter",
            }
        )
    # Use a trailing slash so this URL differs from the center "Code"
    # text link -- Quarto's footer renderer dedupes items by href and
    # will drop the icon if both sides share the exact same URL.
    right.append(
        {
            "icon": "github",
            "href": f"{repo_url}/",
            "aria-label": f"{title} on GitHub",
        }
    )
    footer["right"] = right

    return footer


def _build_navbar(
    opts: YamlDict, repo_url: str, title: str, user_navbar: YamlDict
) -> YamlDict:
    """Build website.navbar, skipping left/right when the user provides them."""
    navbar: YamlDict = {
        "title": title,
        "background": "light",
        "search": True,
    }
    logo: str = opts.get("logo", "")
    if logo and "logo" not in user_navbar:
        navbar["logo"] = logo
    if "left" not in user_navbar:
        navbar["left"] = nav_to_navbar(opts.get("navigation", []))
    if "right" not in user_navbar:
        navbar["right"] = navbar_right(repo_url)
    return navbar


def generate_website_metadata(
    opts: YamlDict, repo: str, user_navbar: YamlDict
) -> YamlDict:
    """Generate derived website metadata from inspect-docs config.

    `user_navbar` is the user's own `website.navbar` block (if any)
    from `_quarto.yml`. When the user provides `left` or `right` keys
    directly, we skip generating those sides so the user's values are
    kept verbatim.
    """
    title: str = opts.get("title", "")
    description: str = opts.get("description", "")
    site_url: str = opts.get("url", "")
    org_name: str = opts.get("org", "")
    repo_url = f"https://github.com/{repo}"

    generated: YamlDict = {
        "website": {
            "title": title,
            "description": description,
            "site-url": site_url,
            "repo-url": repo_url,
            "navbar": _build_navbar(opts, repo_url, title, user_navbar),
            "page-footer": _build_footer(opts, repo, repo_url, title, org_name),
        }
    }

    site_image: str = opts.get("image", "")
    if title or description or site_image:
        card: YamlDict = {}
        if title:
            card["title"] = title
        if description:
            card["description"] = description
        if site_image:
            card["image"] = site_image
        generated["website"]["twitter-card"] = dict(card)
        generated["website"]["open-graph"] = dict(card)

    favicon: str = opts.get("favicon", "")
    if favicon:
        generated["website"]["favicon"] = favicon

    # add Reference navbar link if reference docs exist (only when we
    # generated the left navbar; if the user provided their own left,
    # they're responsible for including the Reference link themselves)
    if "left" not in user_navbar:
        ref_dir = Path("reference")
        if ref_dir.is_dir() and any(ref_dir.glob("*.qmd")):
            generated["website"]["navbar"]["left"].append(
                {"text": "Reference", "href": "reference/index.qmd"}
            )

    return generated


def _nested_children(item: YamlDict) -> list[YamlDict] | None:
    """Return the nested children of a navigation item, or None if it's a leaf.

    Accepts either `contents:` or `menu:` as the nesting key so users can use
    whichever they're more comfortable with.
    """
    children = item.get("contents") or item.get("menu")
    if isinstance(children, list):
        return children
    return None


def _ensure_text(leaf: YamlDict) -> YamlDict:
    """Ensure a navbar menu leaf has a `text` field (Quarto 1.9+ requirement).

    If the leaf already has `text`, return it unchanged. Otherwise try to
    read the target .qmd file's frontmatter `title` field, falling back to
    a title-cased version of the filename stem.
    """
    if "text" in leaf:
        return leaf
    href = leaf.get("href", "")
    if not isinstance(href, str) or not href:
        return leaf

    text: str | None = None
    qmd_path = Path(href.split("#", 1)[0])
    if qmd_path.suffix == ".qmd" and qmd_path.exists():
        try:
            fm = read_frontmatter(qmd_path)
            if fm and isinstance(fm.get("title"), str):
                text = fm["title"]
        except Exception:
            pass

    if text is None:
        stem = qmd_path.stem
        text = stem.replace("-", " ").replace("_", " ").title()

    return {**leaf, "text": text}


def _flatten_menu_leaves(items: list[YamlDict]) -> list[YamlDict]:
    """Recursively flatten a nested navigation tree into leaf entries only.

    Quarto navbar dropdown menus only support a flat list of `text`/`href`
    items (plus `---` separators) — no nested sub-menus. We use this to
    collapse hierarchical navigation into a single-level navbar dropdown
    while the sidebar retains the full hierarchy via `nav_to_sidebar`.

    Quarto 1.9+ requires every navbar menu item to have a `text:` field, so
    each leaf is run through `_ensure_text` to fill it in if missing.
    """
    leaves: list[YamlDict] = []
    for item in items:
        children = _nested_children(item)
        if children is None:
            # leaf entry (text/href or plain href)
            leaf = {k: v for k, v in item.items() if k not in ("contents", "menu")}
            leaves.append(_ensure_text(leaf))
        else:
            # a branch: if it has its own href, include it as a leaf before
            # recursing into its children
            if "href" in item:
                leaf = {
                    k: v for k, v in item.items() if k not in ("contents", "menu")
                }
                leaves.append(_ensure_text(leaf))
            leaves.extend(_flatten_menu_leaves(children))
    return leaves


def nav_to_navbar(items: list[YamlDict]) -> list[YamlDict]:
    """Convert docs-navigation items to navbar format.

    Simple items (text + href) pass through as navbar links.
    Items with `contents` (or `menu`) become dropdown menus. Quarto
    navbar menus are flat — so any deeper nesting is flattened into a
    single-level list of leaf entries via `_flatten_menu_leaves`.
    """
    navbar_items: list[YamlDict] = []
    for item in items:
        children = _nested_children(item)
        if children is not None:
            navbar_items.append(
                {
                    "text": item.get("text", ""),
                    "menu": _flatten_menu_leaves(children),
                }
            )
        else:
            navbar_items.append(item)
    return navbar_items


def nav_to_sidebar(items: list[YamlDict]) -> list[YamlDict]:
    """Convert docs-navigation items to sidebar format.

    Simple items (text + href) pass through as sidebar links.
    Items with `contents` (or `menu`) become collapsible sections.
    """
    sidebar_items: list[YamlDict] = []
    for item in items:
        children = _nested_children(item)
        if children is not None:
            section: YamlDict = {
                "section": item.get("text", ""),
                "contents": nav_to_sidebar(children),
            }
            if "href" in item:
                section["href"] = item["href"]
            sidebar_items.append(section)
        else:
            sidebar_items.append(item)
    return sidebar_items


def navbar_right(repo_url: str) -> list[YamlDict]:
    """Build the right-side navbar items."""
    items: list[YamlDict] = []
    if Path("CHANGELOG.md").exists():
        items.append({"text": "Changelog", "href": "CHANGELOG.md"})
    items.append({"icon": "github", "href": repo_url})
    return items


def generate_reference_artifacts(
    cli_name: str | None,
) -> list[YamlDict] | None:
    """Generate refs.json and return sidebar config from reference docs.

    Discovery is driven by each `.qmd` file's frontmatter `reference:` field;
    pages without a `reference:` field are skipped. A page is treated as a CLI
    command page when its reference equals `cli_name` or starts with
    `f"{cli_name} "`. Otherwise it is an API doc page.
    """
    ref_dir = Path("reference")
    if not ref_dir.is_dir():
        return None

    # (path, title, description, reference)
    api_docs: list[tuple[Path, str, str, str]] = []
    cli_docs: list[tuple[Path, str, str, str]] = []
    for qmd in sorted(ref_dir.glob("*.qmd")):
        if qmd.name == "index.qmd":
            continue
        frontmatter = read_frontmatter(qmd) or {}
        reference = frontmatter.get("reference")
        if not reference:
            # reference pages must declare a 'reference:' field
            continue
        reference = str(reference)
        description = str(
            frontmatter.get("description", "")
            or frontmatter.get("llms-description", "")
        )
        title = str(frontmatter.get("title") or reference)

        if cli_name and (
            reference == cli_name or reference.startswith(f"{cli_name} ")
        ):
            cli_docs.append((qmd, title, description, reference))
        else:
            api_docs.append((qmd, title, description, reference))

    if not api_docs and not cli_docs:
        return None

    # generate reference/index.qmd
    generate_reference_index(
        ref_dir,
        [(p, t, d) for p, t, d, _ in api_docs],
        [(p, t, d) for p, t, d, _ in cli_docs],
    )

    # build cross-reference index from api docs (bare H3 names → href)
    index_json: dict[str, str] = {}
    api_sidebar_entries: list[YamlDict] = []
    for doc, title, _, _ in api_docs:
        objects = parse_reference_objects(doc.read_text())
        refs: list[YamlDict] = [
            dict(text=o, href=f"{doc}#{o.lower()}") for o in objects
        ]
        for ref in refs:
            index_json[str(ref["text"])] = str(ref["href"]).removeprefix("reference/")

        api_sidebar_entries.append(dict(section=title, href=str(doc), contents=refs))

    # build sidebar contents
    sidebar_contents: list[str | YamlDict] = [str(ref_dir / "index.qmd")]

    if api_docs:
        sidebar_contents.append(
            dict(
                section="Python API",
                href=str(api_docs[0][0]),
                contents=api_sidebar_entries,
            )
        )

    if cli_docs:
        cli_entries: list[YamlDict] = [
            dict(text=title, href=str(path)) for path, title, _, _ in cli_docs
        ]
        sidebar_contents.append(
            dict(
                section="CLI Commands",
                href=str(cli_docs[0][0]),
                contents=cli_entries,
            )
        )

    # write refs.json
    write_if_changed(ref_dir / "refs.json", json.dumps(index_json, indent=2))

    return [
        {
            "title": "Reference",
            "style": "docked",
            "collapse-level": 2,
            "contents": sidebar_contents,
        }
    ]


def generate_reference_index(
    ref_dir: Path,
    api_docs: list[tuple[Path, str, str]],
    cli_docs: list[tuple[Path, str, str]],
) -> None:
    """Generate reference/index.qmd from discovered docs."""
    lines = ["---", "title: Reference", "---", ""]

    if api_docs:
        lines.append("### Python API")
        lines.append("")
        lines.append("| | |")
        lines.append("|---|---|")
        for doc, title, description in api_docs:
            lines.append(f"| [{title}]({doc.name}) | {description} |")
        lines.append(": {.borderless tbl-colwidths=[35,65]}")
        lines.append("")

    if cli_docs:
        lines.append("### CLI")
        lines.append("")
        lines.append("| | |")
        lines.append("|---|---|")
        for path, title, description in cli_docs:
            lines.append(f"| [{title}]({path.name}) | {description} |")
        lines.append(": {.borderless tbl-colwidths=[35,65]}")
        lines.append("")

    write_if_changed(ref_dir / "index.qmd", "\n".join(lines))


def write_if_changed(path: Path, content: str) -> None:
    """Write file only if content changed (prevents infinite preview render)."""
    content = content.strip()
    previous = path.read_text().strip() if path.exists() else ""
    if content != previous:
        path.write_text(content)


def read_frontmatter(path: Path) -> dict[str, str] | None:
    """Read YAML frontmatter from a .qmd file."""
    text = path.read_text()
    if not text.startswith("---"):
        return None
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end])  # type: ignore[no-any-return]


def download_external_refs(ref_dir: Path, opts: YamlDict) -> None:
    """Download external reference indices for cross-reference fallback.

    Reads `external_refs` from the inspect-docs config as a mapping of
    `pkg_name -> site_url`. For each entry, downloads `{url}/reference/refs.json`,
    transforms values from relative `file.qmd#anchor` to absolute
    `{url}/reference/file.html#anchor`, and writes to `refs-{pkg_name}.json`.

    Also writes `refs-external.json` (a manifest listing package names in
    config order) so the Lua filters know which files to load. Stale
    `refs-*.json` files for packages no longer in config are removed.
    """
    from urllib.request import urlopen

    external_refs: dict[str, str] = opts.get("external_refs") or {}

    # clean up stale refs-*.json files for packages no longer configured
    active_names = set(external_refs.keys())
    for stale in ref_dir.glob("refs-*.json"):
        name = stale.stem.removeprefix("refs-")
        if name == "external":
            continue  # manifest handled below
        if name not in active_names:
            stale.unlink()

    # if no external refs configured, remove any existing manifest and return
    manifest_path = ref_dir / "refs-external.json"
    if not external_refs:
        if manifest_path.exists():
            manifest_path.unlink()
        return

    for pkg_name, site_url in external_refs.items():
        base = site_url.rstrip("/") + "/reference/"
        dest = ref_dir / f"refs-{pkg_name}.json"
        try:
            with urlopen(base + "refs.json", timeout=5) as resp:
                raw = json.loads(resp.read())
            # transform relative .qmd paths to absolute .html URLs
            absolute: dict[str, str] = {
                key: base + value.replace(".qmd", ".html")
                for key, value in raw.items()
            }
            write_if_changed(dest, json.dumps(absolute, indent=2))
        except Exception as e:
            if dest.exists():
                pass  # use cached copy
            else:
                print(f"Warning: Could not download {pkg_name} refs: {e}")

    # write manifest listing package names in config order
    write_if_changed(manifest_path, json.dumps(list(external_refs.keys())))


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


def parse_reference_objects(markdown: str) -> list[str]:
    """Extract H3 heading names from markdown."""
    objects: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("### "):
            name = line.removeprefix("### ").removeprefix("beta.")
            objects.append(name)
    return objects


if __name__ == "__main__":
    main()
