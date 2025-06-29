import sys
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, NamedTuple, cast
from griffe import (
    Alias,
    Attribute,
    Class,
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


def parse_class_docs(clz: Class, options: DocParseOptions) -> DocObject:
    # if this is a protocol then amend the declaration w/ the __call__
    is_protocol = clz.bases and str(clz.bases[0]) == "Protocol"
    if is_protocol and "__call__" in clz.members:
        # read from call (substituting the protocol name)
        call = cast(Function, clz.members["__call__"])
        call_docs = parse_function_docs(call, options)
        call_docs.name = clz.name
        call_docs.declaration = f"class {clz.name}(Protocol):\n{call_docs.declaration}"
        return call_docs
    else:
        # read source
        source, declaration, docstrings = read_source(clz, options)

        # read attributes and methods
        attributes: list[DocAttribute] = []
        methods: list[DocFunction] = []
        for member in clz.members.values():
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
                methods.append(parse_function_docs(member, options))

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
    # skip private
    if function.name.startswith("_") and not function.name.startswith("__init__"):
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
                description=parameter_descriptions[name],
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
            for p in docstrings[1].value:
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


def read_source(
    object: Object, options: DocParseOptions
) -> tuple[str, str, list[DocstringSection]]:
    # assert preconditions
    sys.stderr.write(object.name + "\n")
    assert isinstance(object.filepath, Path)
    assert object.lineno is not None
    assert object.docstring is not None
    assert object.docstring.lineno is not None

    # url to code
    source = f"{options.source_url}/{object.relative_package_filepath}#L{object.lineno}"

    # read function source code
    declaration = format_declaration(
        read_lines(object.filepath, object.lineno, object.docstring.lineno - 1)
    )

    # read docstrings
    docstrings = object.docstring.parse("google")

    # return
    return source, declaration, docstrings


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
