"""Verify each public subpackage imports cleanly on its own.

Historically several ``__init__.py`` files eagerly imported every
implementation submodule for re-export, which created a latent
``log -> event -> scorer -> solver -> agent -> log`` cycle that only
resolved because ``inspect_ai/__init__.py`` happened to import everything
in a particular order first. These tests load each subpackage in a fresh
interpreter with a *stub* ``inspect_ai`` package (so the top-level
``__init__`` body never runs) to prove no such ordering dependency
remains.
"""

import functools
import os
import pkgutil
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(REPO_ROOT, "src", "inspect_ai")

# auto-discover every public top-level subpackage (no hand-maintained list)
PKGS = sorted(
    m.name
    for m in pkgutil.iter_modules([SRC_ROOT])
    if m.ispkg and not m.name.startswith("_")
)

STUB = textwrap.dedent(
    """
    import os, sys, types
    m = types.ModuleType("inspect_ai")
    m.__path__ = [os.path.join({root!r}, "src", "inspect_ai")]
    sys.modules["inspect_ai"] = m
    """
)


def _run(body: str) -> subprocess.CompletedProcess[str]:
    code = STUB.format(root=REPO_ROOT) + body
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT
    )


@pytest.mark.parametrize("pkg", PKGS)
def test_subpackage_imports_standalone(pkg: str) -> None:
    # each subpackage must import without ``inspect_ai/__init__`` having
    # pre-loaded its siblings (the historical circular-import mask)
    r = _run(f"import inspect_ai.{pkg}\n")
    assert r.returncode == 0, f"import inspect_ai.{pkg} failed:\n{r.stderr}"


def _parse_lazy_init(pkg: str) -> tuple[set[str], set[str]]:
    """Return (lazy_attributes keys, TYPE_CHECKING-imported names) from a package __init__.py."""
    import ast

    path = os.path.join(SRC_ROOT, pkg, "__init__.py")
    tree = ast.parse(open(path).read(), filename=path)

    lazy_keys: set[str] = set()
    tc_names: set[str] = set()

    for node in ast.walk(tree):
        # lazy_attributes(__name__, { "foo": "...", ... })
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "lazy_attributes"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Dict)
        ):
            for k in node.args[1].keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    lazy_keys.add(k.value)
        # if TYPE_CHECKING: from ... import a, b as c, ...
        if isinstance(node, ast.If) and (
            (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
            or (
                isinstance(node.test, ast.Attribute)
                and node.test.attr == "TYPE_CHECKING"
            )
        ):
            for stmt in node.body:
                if isinstance(stmt, (ast.ImportFrom, ast.Import)):
                    for alias in stmt.names:
                        tc_names.add(alias.asname or alias.name)

    return lazy_keys, tc_names


# packages that use lazy_attributes() in their __init__.py
LAZY_PKGS = sorted(
    p
    for p in PKGS + [""]
    if "lazy_attributes("
    in open(os.path.join(SRC_ROOT, p, "__init__.py") if p else os.path.join(SRC_ROOT, "__init__.py")).read()
)


@pytest.mark.parametrize("pkg", LAZY_PKGS)
def test_lazy_attrs_have_type_checking_declarations(pkg: str) -> None:
    """Every lazy attribute has a ``TYPE_CHECKING`` import.

    Without one, mypy/pyright see the module-level ``__getattr__`` and
    silently degrade ``from inspect_ai.<pkg> import <name>`` to ``Any``
    rather than erroring. This test parses the ``__init__.py`` AST to
    enforce the invariant without running a type checker.
    """
    lazy_keys, tc_names = _parse_lazy_init(pkg)
    missing = lazy_keys - tc_names
    assert not missing, (
        f"inspect_ai{'.' + pkg if pkg else ''}/__init__.py: lazy_attributes "
        f"keys {sorted(missing)} are not imported under `if TYPE_CHECKING:`. "
        f"Static type checkers will resolve these to `Any`. Add them to the "
        f"TYPE_CHECKING block."
    )


@pytest.mark.parametrize("pkg", ["scorer", "solver", "agent", "log"])
def test_lazy_subpackage_exposes_full_api(pkg: str) -> None:
    # every name in ``__all__`` of a lazied package must resolve
    r = _run(f"import inspect_ai.{pkg} as p\nfor n in p.__all__:\n    getattr(p, n)\n")
    assert r.returncode == 0, f"inspect_ai.{pkg} __all__ incomplete:\n{r.stderr}"


@functools.cache
def _discover_builtin_registry() -> dict[str, frozenset[str]]:
    """Return every inspect_ai-shipped registry entry, grouped by kind.

    Walks and imports *every* module under ``src/inspect_ai`` so that all
    ``@scorer``/``@solver``/... decorators fire -- including ones in
    modules not reachable via any package ``__all__`` -- then snapshots
    the registry. This is ground truth derived from what actually
    registers, not a hand-maintained list.
    """
    import importlib
    import warnings

    from inspect_ai._util import registry as registry_mod

    skipped: list[tuple[str, str]] = []

    def _on_error(modname: str) -> None:
        skipped.append((modname, str(sys.exc_info()[1])))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _, modname, _ in pkgutil.walk_packages(
            [SRC_ROOT], prefix="inspect_ai.", onerror=_on_error
        ):
            try:
                importlib.import_module(modname)
            except Exception as ex:
                skipped.append((modname, f"{type(ex).__name__}: {ex}"))

    # surface modules that failed to import (optional deps etc.) so a
    # genuine ImportError in a registration module isn't silently hidden
    if skipped:
        print(f"\n[discovery] {len(skipped)} module(s) skipped:")
        for m, e in skipped[:10]:
            print(f"  {m}: {e}")

    by_kind: dict[str, set[str]] = {}
    for obj in registry_mod.registry_find(lambda _: True):
        ri = registry_mod.registry_info(obj)
        if ri.name.startswith("inspect_ai/"):
            by_kind.setdefault(ri.type, set()).add(ri.name)
    return {k: frozenset(v) for k, v in by_kind.items()}


def _builtin_pkg_map() -> dict[str, str]:
    from inspect_ai._util import registry as registry_mod

    return getattr(registry_mod, "_BUILTIN_PKG")


def test_builtin_pkg_covers_every_kind_with_builtins() -> None:
    """Catch ``_BUILTIN_PKG`` drift automatically.

    Every registry kind for which inspect_ai ships at least one built-in
    must have a ``_BUILTIN_PKG`` entry. If someone adds a new
    ``@something``-decorated built-in this fails until the map is updated --
    no test changes required.
    """
    discovered = _discover_builtin_registry()
    builtin_pkg = _builtin_pkg_map()

    missing = set(discovered) - set(builtin_pkg)
    assert not missing, (
        f"Registry kinds {sorted(missing)} have inspect_ai built-ins "
        f"(e.g. {[sorted(discovered[k])[0] for k in sorted(missing)]}) but are "
        f"not in inspect_ai._util.registry._BUILTIN_PKG, so cold "
        f"registry_lookup() will return None for them."
    )


@pytest.mark.parametrize("kind", sorted(_discover_builtin_registry()))
def test_registry_lookup_cold(kind: str) -> None:
    """Every built-in is reachable via cold ``registry_lookup``.

    For each kind, runs ``registry_lookup(kind, name)`` for *every*
    discovered inspect_ai built-in in a single fresh interpreter. This
    proves the ``_BUILTIN_PKG[kind]`` fallback (a) points at a package
    whose import registers these names, and (b) hasn't drifted. A
    registered name that lives in a different package than
    ``_BUILTIN_PKG[kind]`` will show up here as unreachable.
    """
    names = sorted(_discover_builtin_registry()[kind])
    r = _run(
        "from inspect_ai._util.registry import registry_lookup\n"
        f"missing = [n for n in {names!r} "
        f"           if registry_lookup({kind!r}, n) is None]\n"
        "assert not missing, f'unreachable: {missing}'\n"
    )
    assert r.returncode == 0, (
        f"cold registry_lookup for kind={kind!r} via "
        f"_BUILTIN_PKG[{kind!r}]={_builtin_pkg_map().get(kind)!r}:\n{r.stderr}\n"
        f"Either the package path is wrong, or these names register from a "
        f"different package than the one mapped."
    )
