# pyright: basic
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, NamedTuple, cast

from griffe import (
    Alias,
    AliasResolutionError,
    Attribute,
    Class,
    CyclicAliasError,
    Docstring,
    DocstringSection,
    DocstringSectionExamples,
    DocstringSectionParameters,
    DocstringSectionRaises,
    Expr,
    Function,
    Module,
    Object,
    ParameterKind,
)


@dataclass
class DocParseOptions:
    module: Module
    source_url: str


@dataclass
class DocParameter:
    name: str
    type: str
    required: bool
    default: Any
    description: str


@dataclass
class DocRaises:
    type: str
    description: str


@dataclass
class DocAttribute:
    name: str
    type: str
    description: str


@dataclass
class DocObject:
    name: str
    description: str
    source: str
    declaration: str
    examples: str | None
    text_sections: list[str]


@dataclass
class DocFunction(DocObject):
    parameters: list[DocParameter]
    raises: list[DocRaises]


@dataclass
class DocClass(DocObject):
    attributes: list[DocAttribute]
    methods: list[DocFunction]


def parse_docs(path: str, options: DocParseOptions) -> DocObject:
    # lookup object
    object: Object | Alias = options.module
    for segment in path.split("."):
        object = object.members[segment]

    # resolve aliases
    if isinstance(object, Alias):
        object = object.final_target

    # if we landed on a module, look for a same-named member inside it
    # (handles cases like `from ._task import audit` where _task/audit.py
    # contains a function also named `audit`)
    if isinstance(object, Module):
        leaf = path.rsplit(".", 1)[-1]
        if leaf in object.members:
            member = object.members[leaf]
            if isinstance(member, Alias):
                member = member.final_target
            object = member

    # type-specific parsing
    if isinstance(object, Function):
        return parse_function_docs(object, options)
    elif isinstance(object, Class):
        return parse_class_docs(object, options)
    elif isinstance(object, Attribute):
        return parse_attribute_docs(object, options)
    else:
        raise ValueError(
            f"Reference object type ({type(object)}) for {path} is unsupported."
        )


def parse_attribute_docs(attrib: Attribute, options: DocParseOptions) -> DocObject:
    source, declaration, docstrings = read_source(attrib, options)

    return DocObject(
        name=attrib.name,
        description=docstrings[0].value,
        source=source,
        declaration=declaration,
        examples=None,
        text_sections=[],
    )


def field_description_to_docstring(attribute: Attribute) -> None:
    """Extract description from Pydantic Field(description=...) if no docstring."""
    if attribute.docstring is not None:
        return

    if attribute.value is None:
        return

    value_str = str(attribute.value)
    if not ("Field(" in value_str and "description=" in value_str):
        return

    try:
        import ast

        value_str = value_str.strip()
        if not value_str.startswith("Field("):
            return

        tree = ast.parse(f"x = {value_str}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(
                    keyword.value, ast.Constant
                ):
                    attribute.docstring = Docstring(
                        str(keyword.value.value),
                        lineno=attribute.lineno,
                        endlineno=attribute.endlineno,
                    )
                    return
    except Exception:
        pass


def parse_class_docs(clz: Class, options: DocParseOptions) -> DocObject:
    # if this is a protocol then amend the declaration w/ the __call__
    is_protocol = clz.bases and str(clz.bases[0]).startswith("Protocol")
    if is_protocol and "__call__" in clz.members:
        # read from call (substituting the protocol name)
        call = cast(Function, clz.members["__call__"])
        call_docs = parse_function_docs(call, options)
        call_docs.name = clz.name
        call_docs.declaration = (
            f"class {clz.name}({str(clz.bases[0])}):\n{call_docs.declaration}"
        )
        return call_docs
    else:
        # read source
        source, declaration, docstrings = read_source(clz, options)

        # read attributes and methods
        attributes: list[DocAttribute] = []
        methods: list[DocFunction] = []

        # process inherited members first (base class fields appear first)
        for name, alias in clz.inherited_members.items():
            if name in clz.members:
                continue
            try:
                member: Object | Alias = alias.final_target
            except (AliasResolutionError, CyclicAliasError):
                continue
            if member.docstring is None:
                if isinstance(member, Attribute):
                    field_description_to_docstring(member)
                if member.docstring is None:
                    continue
            if isinstance(member, Attribute):
                if not isinstance(member.annotation, Expr):
                    continue
                if member.name.startswith("_"):
                    continue
                if "deprecated" in member.docstring.value.lower():
                    continue
                attributes.append(
                    DocAttribute(
                        name=member.name,
                        type=str(member.annotation.modernize()),
                        description=member.docstring.value,
                    )
                )
            elif isinstance(member, Function) and include_function(member):
                try:
                    methods.append(parse_function_docs(member, options))
                except MissingDocstringError:
                    # Silently skip __init__ when it has no docstring -- the
                    # constructor is often documented via the class docstring
                    # or via property accessors instead.
                    if member.name == "__init__":
                        continue
                    raise

        # then process direct (derived class) members
        for member in clz.members.values():
            if member.docstring is None:
                if isinstance(member, Attribute):
                    field_description_to_docstring(member)
                if member.docstring is None:
                    continue
            if isinstance(member, Attribute):
                if not isinstance(member.annotation, Expr):
                    continue
                if member.name.startswith("_"):
                    continue
                if "deprecated" in member.docstring.value.lower():
                    continue
                attributes.append(
                    DocAttribute(
                        name=member.name,
                        type=str(member.annotation.modernize()),
                        description=member.docstring.value,
                    )
                )
            elif isinstance(member, Function) and include_function(member):
                try:
                    methods.append(parse_function_docs(member, options))
                except MissingDocstringError:
                    # Silently skip __init__ when it has no docstring -- the
                    # constructor is often documented via the class docstring
                    # or via property accessors instead.
                    if member.name == "__init__":
                        continue
                    raise

        # return as a class
        return DocClass(
            name=clz.name,
            description=docstrings[0].value,
            source=source,
            declaration=declaration,
            examples=None,
            text_sections=[],
            attributes=attributes,
            methods=methods,
        )


def include_function(function: Function) -> bool:
    # skip private (except __init__)
    if function.name.startswith("_") and not function.name.startswith("__init__"):
        return False

    # skip pydantic model_post_init
    if function.name == "model_post_init":
        return False

    # skip pydantic validators
    if "classmethod" in function.labels:
        if any(["model_" in str(dec.value) for dec in function.decorators]):
            return False

    return True


class DocstringContent(NamedTuple):
    description: str
    parameter_descriptions: dict[str, str]
    raises: dict[str, str]
    examples: str | None
    text_sections: list[str]


def parse_function_docs(function: Function, options: DocParseOptions) -> DocFunction:
    # read source
    source, declaration, docstrings = read_source(function, options)

    # read docstring sections
    docstring_content = read_docstring_sections(docstrings)

    # extract params
    params = read_params(function, docstring_content.parameter_descriptions)

    # extract raises
    raises = [
        DocRaises(type=k, description=v) for k, v in docstring_content.raises.items()
    ]

    # return function
    return DocFunction(
        name=function.name,
        description=docstring_content.description,
        source=source,
        declaration=declaration,
        examples=docstring_content.examples,
        text_sections=docstring_content.text_sections,
        parameters=params,
        raises=raises,
    )


def read_params(
    function: Function, parameter_descriptions: dict[str, str]
) -> list[DocParameter]:
    # extract params
    params: list[DocParameter] = []
    for p in function.parameters:
        # skip self
        if p.name == "self" or p.name == "cls":
            continue

        # param name w/ varargs prefix
        name = p.name
        if p.kind == ParameterKind.var_positional:
            name = f"*{name}"
        elif p.kind == ParameterKind.var_keyword:
            name = f"**{name}"

        params.append(
            DocParameter(
                name=name,
                type=str(p.annotation.modernize())
                if isinstance(p.annotation, Expr)
                else str(p.annotation),
                required=p.required,
                default=str(p.default) if p.required else "",
                description=parameter_descriptions.get(name, "")
                or parameter_descriptions.get(name.replace("*", ""), ""),
            )
        )

    return params


def read_docstring_sections(docstrings: list[DocstringSection]) -> DocstringContent:
    # main text
    description = docstrings[0].value

    examples: str | None = None
    text_sections: list[str] = []
    parameter_descriptions: dict[str, str] = {}
    raises: dict[str, str] = {}
    for doc_section in docstrings[1:]:
        if isinstance(doc_section, DocstringSectionParameters):
            for p in doc_section.value:
                desc = p.description.strip()
                parameter_descriptions[p.name] = desc
        elif isinstance(doc_section, DocstringSectionExamples):
            examples = "\n\n".join(value[1] for value in doc_section.value)
        elif isinstance(doc_section, DocstringSectionRaises):
            for r in doc_section.value:
                raises[str(r.annotation)] = r.description

    return DocstringContent(
        description=description,
        parameter_descriptions=parameter_descriptions,
        raises=raises,
        examples=examples,
        text_sections=text_sections,
    )


class MissingDocstringError(Exception):
    """Raised when a reference symbol has no docstring to render."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} has no docstring")
        self.name = name


def read_source(
    object: Object, options: DocParseOptions
) -> tuple[str, str, list[DocstringSection]]:
    # Build a qualified name (e.g. "MyClass.__init__") so warnings about
    # inherited / undocumented members point at the containing class.
    qualified = (
        f"{object.parent.name}.{object.name}"
        if object.parent is not None and getattr(object.parent, "name", None)
        else object.name
    )

    # Inherited members carry no source location (their implementation lives
    # in a parent class). Without a lineno or filepath we can't slice the
    # declaration out of the source file, so treat them the same as a missing
    # docstring -- the symbol is skipped with a warning rather than crashing
    # the build.
    if not isinstance(object.filepath, Path) or object.lineno is None:
        raise MissingDocstringError(qualified)
    if object.docstring is None:
        raise MissingDocstringError(qualified)
    if object.docstring.lineno is None:
        raise MissingDocstringError(qualified)

    # url to code
    source = f"{options.source_url}/{object.relative_package_filepath}#L{object.lineno}"

    # read function source code
    declaration = format_declaration(
        read_lines(object.filepath, object.lineno, object.docstring.lineno - 1)
    )

    # if Unpack was expanded by griffe, reconstruct the declaration
    if isinstance(object, Function) and "Unpack[" in declaration:
        declaration = reconstruct_declaration(object)

    # use pre-parsed docstrings (preserves UnpackTypedDictExtension expansion)
    docstrings = object.docstring.parsed

    # return
    return source, declaration, docstrings


def reconstruct_declaration(function: Function) -> str:
    """Reconstruct a function declaration with Unpack[TypedDict] kwargs expanded."""
    parts = [f"def {function.name}("]
    has_keyword_only_separator = False
    for p in function.parameters:
        if p.name == "self" or p.name == "cls":
            parts.append(f"    {p.name},")
            continue
        if p.kind == ParameterKind.keyword_only and not has_keyword_only_separator:
            parts.append("    *,")
            has_keyword_only_separator = True
        ann = (
            str(p.annotation.modernize())
            if isinstance(p.annotation, Expr)
            else str(p.annotation)
        )
        if p.required:
            parts.append(f"    {p.name}: {ann},")
        else:
            parts.append(f"    {p.name}: {ann} = ...,")
    ret = (
        str(function.annotation.modernize())
        if isinstance(function.annotation, Expr)
        else str(function.annotation)
    )
    parts.append(f") -> {ret}")
    return "\n".join(parts)


def read_declaration(object: Object | Alias) -> str:
    assert isinstance(object.filepath, Path)
    assert object.lineno
    assert object.endlineno
    return format_declaration(
        read_lines(object.filepath, object.lineno, object.endlineno)
    )


def read_lines(filename: Path, start_line: int, end_line: int) -> list[str]:
    with open(filename, "r") as file:
        return list(islice(file, start_line - 1, end_line))


def format_declaration(lines: list[str]) -> str:
    code = "".join(lines)
    return code.removesuffix(":\n")
