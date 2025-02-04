from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
import sys
from typing import Any
from griffe import Alias, DocstringSectionExamples, DocstringSectionParameters, Function, Module, Object, ParameterKind

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
class DocObject:
    name: str
    description: str
    source: str
    examples: str | None
    text_sections: list[str]

@dataclass
class DocFunction(DocObject):
    declaration: str
    parameters: list[DocParameter]

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
    else:
        raise ValueError(f"Reference object type ({type(object)}) for {path} is unsupported.")
  

def parse_function_docs(function: Function, options: DocParseOptions) -> DocFunction:
    
    # validate preconditions
    assert isinstance(function.filepath, Path)
    assert function.lineno is not None
    assert function.docstring is not None
    assert function.docstring.lineno is not None
    
    # parse docstrings
    doc_sections = function.docstring.parse("google")
    function_description = doc_sections[0].value

    examples: str | None = None
    text_sections: list[str] = []
    parameter_descriptions: dict[str,str] = {}
    for doc_section in doc_sections[1:]:
        if isinstance(doc_section, DocstringSectionParameters):
            for p in doc_sections[1].value:
                desc = p.description.strip()
                parameter_descriptions[p.name] = desc
        elif isinstance(doc_section, DocstringSectionExamples):
            examples = "\n\n".join(value[1] for value in doc_section.value)

    # url to code
    source = f"{options.source_url}/{function.relative_package_filepath}#L{function.lineno}"

    # read function source code
    declaration = format_declaration(read_lines(function.filepath, function.lineno, function.docstring.lineno-1))

    # extract params
    params: list[DocParameter] = []
    for p in function.parameters:
        # param name w/ varargs prefix
        name = p.name
        if p.kind == ParameterKind.var_positional:
            name = f"*{name}"
        elif p.kind == ParameterKind.var_keyword:
            name = f"**{name}"  

        params.append(
            DocParameter(
                name=name, 
                type=str(p.annotation.modernize()), 
                required=p.required,
                default=str(p.default) if p.required else "", 
                description=parameter_descriptions[name])
        )

    # return function
    return DocFunction(
        name=function.name,
        description=function_description,
        source=source,
        examples=examples,
        text_sections=text_sections,
        declaration=declaration,
        parameters=params
    )

def read_lines(filename: Path, start_line: int, end_line: int) -> list[str]:
    with open(filename, 'r') as file:
        return list(islice(file, start_line-1, end_line))

def format_declaration(lines: list[str]) -> str:
    code = "".join(lines)
    return code.removesuffix(":\n")

   