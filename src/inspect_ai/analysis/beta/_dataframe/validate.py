from __future__ import annotations

from logging import getLogger
from typing import Any, Iterator, Mapping, Type

import jsonref  # type: ignore
from jsonpath_ng import Fields, Index, JSONPath, Slice, Where, WhereNot  # type: ignore
from jsonpath_ng.ext.filter import Filter  # type: ignore
from pydantic import BaseModel

logger = getLogger(__name__)

Schema = Mapping[str, Any]


def resolved_schema(model: Type[BaseModel]) -> Schema:
    schema_dict = model.model_json_schema()
    base = "file:///memory/inspect_schema.json"
    schema: Schema = jsonref.replace_refs(
        schema_dict, base_uri=base, jsonschema=True, proxies=False
    )
    return schema


def jsonpath_in_schema(expr: JSONPath, schema: Schema) -> bool:
    # don't validate unsupported constructs
    if find_unsupported(expr):
        return True

    def descend(sch: Schema, tok: str | int | None) -> list[Schema]:
        # First, branch through anyOf/oneOf/allOf
        outs: list[Schema] = []
        for branch in _expand_union(sch):
            outs.extend(descend_concrete(branch, tok))
        return outs

    def descend_concrete(sch: Schema, tok: str | int | None) -> list[Schema]:
        # totally open object – accept any child
        if sch == {}:
            return [{}]  # stay alive, accept any key

        outs: list[Schema] = []

        def open_dict(node: Schema) -> None:
            """Append the schema that governs unknown keys.

            - None / missing  -> open object  ->   {}
            - True            -> open object  ->   {}
            - Mapping         -> that mapping (could be {} or a real subschema)
            - False           -> closed object ->   (do nothing)
            """
            if "additionalProperties" not in node:
                if not node.get("properties"):
                    outs.append({})
            else:
                ap = node["additionalProperties"]
                if ap is True:
                    outs.append({})
                elif isinstance(ap, Mapping):  # {} or {...}
                    outs.append(ap)
                # ap is False  -> closed dict  ->  ignore

        # Wildcard -----------------------------------------------------------
        if tok is None:
            if "properties" in sch:
                outs.extend(sch["properties"].values())
            if "object" in _types(sch):
                open_dict(sch)
            if "array" in _types(sch) and "items" in sch:
                outs.extend(_normalize_items(sch["items"]))
            return outs

        # Property access ----------------------------------------------------
        if isinstance(tok, str):
            if "properties" in sch and tok in sch["properties"]:
                outs.append(sch["properties"][tok])
            elif "additionalProperties" in sch:  # PRESENCE, not truthiness
                open_dict(sch)
            elif "object" in _types(sch):
                open_dict(sch)

        # Array index --------------------------------------------------------
        else:  # tok is int or None from an Index node
            if "array" in _types(sch) and "items" in sch:
                outs.extend(_normalize_items(sch["items"], index=tok))

        return outs

    def _types(sch: Schema) -> set[str]:
        t = sch.get("type")
        return set(t) if isinstance(t, list) else {t} if t else set()

    def _normalize_items(items: Any, index: int | None = None) -> list[Schema]:
        if isinstance(items, list):
            if index is None:  # wildcard/slice
                return items
            if 0 <= index < len(items):
                return [items[index]]
            return []
        if isinstance(items, Mapping):
            return [items]
        return []

    states = [schema]
    for tok in iter_tokens(expr):
        next_states: list[Schema] = []
        for st in states:
            next_states.extend(descend(st, tok))
        if not next_states:  # nothing matched this segment
            return False
        states = next_states
    return True  # every segment found at least one schema


def iter_tokens(node: JSONPath) -> Iterator[str | int | None]:
    """Linearise a jsonpath-ng AST into a stream of tokens we care about."""
    if hasattr(node, "left"):  # Child, Descendants, etc.
        yield from iter_tokens(node.left)
        yield from iter_tokens(node.right)
    elif isinstance(node, Fields):
        yield from node.fields  # e.g. ["foo"]
    elif isinstance(node, Index):
        yield node.index  # 0  /  -1  /  None for wildcard
    elif isinstance(node, Slice):
        yield None  # treat any slice as wildcard


COMBINATORS = ("anyOf", "oneOf", "allOf")


def _expand_union(sch: Schema) -> list[Schema]:
    """Return sch itself or the list of subschemas if it is a combinator."""
    for key in COMBINATORS:
        if key in sch:
            subs: list[Schema] = []
            for sub in sch[key]:
                # a sub-schema might itself be an anyOf/oneOf/allOf
                subs.extend(_expand_union(sub))
            return subs
    return [sch]


UNSUPPORTED: tuple[type[JSONPath], ...] = (
    Filter,  # [?foo > 0]
    Where,  # .foo[(@.bar < 42)]
    WhereNot,
    Slice,  # [1:5]  (wildcard “[*]” is Index/None, not Slice)
)


def find_unsupported(node: JSONPath) -> list[type[JSONPath]]:
    """Return a list of node types present in `node` that we do not validate."""
    bad: list[type[JSONPath]] = []
    stack: list[JSONPath] = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, UNSUPPORTED):
            bad.append(type(n))
        # Drill into children (jsonpath-ng uses .left / .right / .child attributes)
        for attr in ("left", "right", "child", "expression"):
            stack.extend(
                [getattr(n, attr)]
                if hasattr(n, attr) and isinstance(getattr(n, attr), JSONPath)
                else []
            )
        # handle containers like Fields(fields=[...]) and Index(index=[...])
        if hasattr(n, "__dict__"):
            for v in n.__dict__.values():
                if isinstance(v, list):
                    stack.extend(x for x in v if isinstance(x, JSONPath))
    return bad
