# pyright: basic
import os
import subprocess
import sys
import warnings
from typing import Any, cast

# Suppress a noisy SyntaxWarning emitted by panflute's own io.py on Python
# 3.12+ (the warning is unrelated to our code -- panflute's docstring uses
# `\*\*kwargs`). The filter catches the warning on first compile of any
# panflute module.
warnings.filterwarnings("ignore", category=SyntaxWarning)

# ensure sibling imports (parse/render/commands) work regardless of cwd
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

# also expose the extension root so we can import shared helpers from _discover
_EXT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
sys.path.insert(0, _EXT_ROOT)

from griffe import Extensions, Module, UnpackTypedDictExtension
import griffe
import panflute as pf  # type: ignore

# Quarto serializes some metadata values (e.g. the strings under
# `categories:` in frontmatter) as pandoc RawInline elements whose format
# is `"pandoc-native"`. That format isn't in panflute 2.x's RAW_FORMATS
# set, so `pf.run_filters`'s JSON parse step raises a TypeError on any
# document that reaches pandoc's AST through that path -- a crash well
# before any of this filter's own logic runs. Widening the set at import
# time lets such documents pass through unchanged.
pf.elements.RAW_FORMATS.add("pandoc-native")  # type: ignore[attr-defined]

from rich.console import Console

from parse import DocParseOptions, MissingDocstringError, parse_docs
from render import render_docs
from commands import make_command_docs, resolve_cli_command
from _discover import discover_cli, discover_module_name  # noqa: E402

# stderr console with forced color so warnings are visible even when
# stderr is captured by Quarto (which makes isatty() return False)
_console = Console(stderr=True, force_terminal=True)


def _warn(message: str) -> None:
    """Print a yellow warning to stderr."""
    _console.print(f"[yellow][bold]WARNING:[/bold] {message}[/yellow]")


def _is_empty_section(elem: pf.Header) -> bool:
    """True when no content blocks sit between this heading and the next."""
    nxt = elem.next
    return nxt is None or (isinstance(nxt, pf.Header) and nxt.level <= elem.level)


def main() -> Any:
    # lazily initialized on first reference page
    parse_options_cache: list[DocParseOptions] = []
    module_name_cache: list[str] = []
    cli_name_cache: list[str | None] = []
    cli_entry_cache: list[str | None] = []
    initialized = [False]

    def get_parse_options(doc: pf.Doc) -> DocParseOptions | None:
        if initialized[0]:
            return parse_options_cache[0] if parse_options_cache else None

        # read configuration from document metadata, falling back to
        # auto-discovery from a parent pyproject.toml
        inspect_docs: Any = doc.metadata.get("inspect-docs", {})
        module_in_config = "module" in inspect_docs if inspect_docs else False
        if module_in_config:
            module_name = pf.stringify(inspect_docs["module"])
        else:
            discovered = discover_module_name()
            if discovered is None:
                # feature not activated -- silent no-op
                initialized[0] = True
                return None
            module_name = discovered

        # resolve cli binary name and entry point. We always look up
        # pyproject's [project.scripts] (when available) for the entry
        # point string -- the explicit `cli:` config (if present) only
        # overrides the *name* used to identify CLI pages.
        cli_info = discover_cli(module_name)
        cli_name: str | None = None
        cli_entry: str | None = None
        if inspect_docs and "cli" in inspect_docs:
            cli_name = pf.stringify(inspect_docs["cli"])
            # Take the entry point from pyproject if it matches the configured
            # name; otherwise fall back to whatever pyproject discovered.
            if cli_info is not None:
                cli_entry = cli_info[1]
        elif cli_info is not None:
            cli_name, cli_entry = cli_info

        initialized[0] = True

        try:
            module = cast(
                Module,
                griffe.load(
                    module_name,
                    extensions=Extensions(UnpackTypedDictExtension()),
                    docstring_parser="google",
                ),
            )
        except (ImportError, ModuleNotFoundError) as e:
            source = "config" if module_in_config else "pyproject.toml"
            _warn(
                f"reference: unable to load module '{module_name}' "
                f"(from {source}): {e}. Reference processing will be skipped."
            )
            return None

        repo = pf.stringify(inspect_docs["repo"]) if "repo" in inspect_docs else ""
        sha = (
            subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True)
            .stdout.decode()
            .strip()
        )
        source_url = f"https://github.com/{repo}/blob/{sha}/src"
        options = DocParseOptions(module=module, source_url=source_url)

        parse_options_cache.append(options)
        module_name_cache.append(module_name)
        cli_name_cache.append(cli_name)
        cli_entry_cache.append(cli_entry)
        return options

    def get_module_name() -> str | None:
        return module_name_cache[0] if module_name_cache else None

    def get_cli_name() -> str | None:
        return cli_name_cache[0] if cli_name_cache else None

    def get_cli_entry() -> str | None:
        return cli_entry_cache[0] if cli_entry_cache else None

    def page_reference(doc: pf.Doc) -> str | None:
        """Return the page's `reference:` field, or None if not declared."""
        if "reference" in doc.metadata:
            return pf.stringify(doc.metadata["reference"])
        return None

    def is_reference_page(doc: pf.Doc) -> bool:
        """True if the current input file lives in a `reference/` directory.

        Quarto sets `QUARTO_DOCUMENT_PATH` to the source file's directory
        when invoking filters. We treat any page whose immediate parent
        directory is named `reference` as a reference page.
        """
        doc_path = os.environ.get("QUARTO_DOCUMENT_PATH", "")
        if not doc_path:
            return False
        return os.path.basename(doc_path.rstrip("/").rstrip(os.sep)) == "reference"

    # default the page title from the `reference:` field when no title
    # is set explicitly. Runs once per document.
    def set_default_title(elem: pf.Element, doc: pf.Doc) -> None:
        if not isinstance(elem, pf.Doc):
            return
        if "title" in doc.metadata:
            return
        if "reference" not in doc.metadata:
            return
        reference = pf.stringify(doc.metadata["reference"])
        if reference:
            doc.metadata["title"] = pf.MetaInlines(pf.Str(reference))

    # python api -- convert h3 headings into rendered reference docs
    def python_api(elem: pf.Element, doc: pf.Doc) -> Any:
        if not isinstance(elem, pf.Header):
            return None
        if elem.level != 3 and "reference" not in elem.attributes:
            return None

        parse_options = get_parse_options(doc)
        if parse_options is None:
            return elem
        project_module = get_module_name()
        if project_module is None:
            return elem

        # Pages must declare their binding via a `reference:` frontmatter
        # field. No project-default fallback.
        page_ref = page_reference(doc)
        if page_ref is None:
            return elem

        # Skip CLI command pages -- they are handled by click_cli at the
        # document level, not by per-heading rewriting.
        cli_name = get_cli_name()
        if cli_name and (
            page_ref == cli_name or page_ref.startswith(f"{cli_name} ")
        ):
            return elem

        # Inline-reference flow: on article pages (outside reference/),
        # H3s with an explicit `reference="..."` attribute always become
        # symbols. Plain H3s become symbols only when their section is
        # empty (no content before the next heading), allowing reference
        # pages outside a reference/ directory to omit redundant attributes.
        has_explicit_attr = "reference" in elem.attributes
        if not has_explicit_attr and not is_reference_page(doc):
            if not _is_empty_section(elem):
                return elem

        # Symbol lookups are relative to the griffe-loaded project module,
        # so strip that prefix from `page_ref` to get the path within the
        # loaded module. e.g. page_ref="inspect_scout.aio" + target="scan_async"
        # becomes "aio.scan_async".
        if page_ref == project_module:
            relative = ""
        elif page_ref.startswith(f"{project_module}."):
            relative = page_ref.removeprefix(f"{project_module}.")
        else:
            relative = page_ref  # binding outside the project module

        target = elem.attributes.get("reference", pf.stringify(elem.content))
        object = f"{relative}.{target}" if relative else target

        # parse docs
        try:
            docs = parse_docs(object, parse_options)
        except KeyError:
            if has_explicit_attr:
                _warn(f"reference: symbol '{object}' not found (skipping)")
                return []
            return elem
        except MissingDocstringError as e:
            _warn(f"reference: {e} (skipping)")
            return []

        # render docs
        return render_docs(elem, docs)

    # click cli -- pages whose `reference:` starts with "<cli> " trigger
    # CLI doc generation; the subcommand is the suffix after the cli binary
    # name. The Click command is resolved via the pyproject entry point.
    def click_cli(elem: pf.Element, doc: pf.Doc) -> None:
        if not isinstance(elem, pf.Doc):
            return
        # ensure project options are initialized
        if get_parse_options(doc) is None:
            return
        cli_name = get_cli_name()
        cli_entry = get_cli_entry()
        if cli_name is None or cli_entry is None:
            return

        if "reference" not in doc.metadata:
            return
        page_ref = pf.stringify(doc.metadata["reference"])
        if page_ref != cli_name and not page_ref.startswith(f"{cli_name} "):
            return

        # subcommand path: everything after "<cli> " (may be a multi-token
        # path like "scout scan resume" -> ["scan", "resume"])
        if page_ref == cli_name:
            subcommand_path: list[str] = []
        else:
            subcommand_path = page_ref.removeprefix(f"{cli_name} ").split()

        try:
            command_obj = resolve_cli_command(
                cli_entry, subcommand_path, cli_name=cli_name
            )
        except RuntimeError as e:
            _warn(f"reference: {e} (skipping)")
            return

        docs = "\n".join(
            list(
                make_command_docs(
                    command=command_obj,
                    prog_name=page_ref,
                )
            )
        )
        doc.content.append(pf.RawBlock(docs, "markdown"))

    return pf.run_filters([set_default_title, python_api, click_cli])


if __name__ == "__main__":
    main()
