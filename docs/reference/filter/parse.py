from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import sys
from typing import Any, NamedTuple, cast
from griffe import Alias, Class, DocstringSection, DocstringSectionExamples, DocstringSectionParameters, Function, Module, Object, ParameterKind

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
    declaration: str
    examples: str | None
    text_sections: list[str]

@dataclass
class DocFunction(DocObject):
    parameters: list[DocParameter]

@dataclass
class DocClass(DocObject):
    pass

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
    else:
        raise ValueError(f"Reference object type ({type(object)}) for {path} is unsupported.")
  



def parse_class_docs(clz: Class, options: DocParseOptions) -> DocClass:
    
    # read source
    source, declaration, docstrings = read_source(clz, options)
    
    # if this is a protocol then ammend the declaration w/ the __call__
    examples: str | None = None
    text_sections: list[str] = []
    is_protocol = clz.bases and str(clz.bases[0]) == "Protocol"
    if is_protocol:
        # read call source code and ammend declaration
        call = clz.members["__call__"]
        call_declaration = read_declaration(call)       
        declaration = f"{declaration}\n{call_declaration}"

        # read examples and text sections
        docstring_content = read_docstring_sections(docstrings)
        examples = docstring_content.examples
        text_sections = docstring_content.text_sections

    # return class
    return DocClass(
        name=clz.name,
        description=docstrings[0].value,
        source=source,
        declaration=declaration,
        examples=examples,
        text_sections=text_sections
    )



class DocstringContent(NamedTuple):
    description: str
    parameter_descriptions: dict[str,str]
    examples: str | None
    text_sections: list[str]

def parse_function_docs(function: Function, options: DocParseOptions) -> DocFunction:
    
    # read source
    source, declaration, docstrings = read_source(function, options)
    
    # read docstring sections
    docstring_content = read_docstring_sections(docstrings)


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
                description=docstring_content.parameter_descriptions[name])
        )

    # return function
    return DocFunction(
        name=function.name,
        description=docstring_content.description,
        source=source,
        declaration=declaration,
        examples=docstring_content.examples,
        text_sections=docstring_content.text_sections,
        parameters=params
    )

def read_docstring_sections(docstrings: list[DocstringSection]) -> DocstringContent:
     # main text
    description = docstrings[0].value

    examples: str | None = None
    text_sections: list[str] = []
    parameter_descriptions: dict[str,str] = {}
    for doc_section in docstrings[1:]:
        if isinstance(doc_section, DocstringSectionParameters):
            for p in docstrings[1].value:
                desc = p.description.strip()
                parameter_descriptions[p.name] = desc
        elif isinstance(doc_section, DocstringSectionExamples):
            examples = "\n\n".join(value[1] for value in doc_section.value)


    return DocstringContent(
        description=description,
        parameter_descriptions=parameter_descriptions,
        examples=examples,
        text_sections=text_sections
    )


def read_source(object: Object, options: DocParseOptions) -> tuple[str,str,list[DocstringSection]]:
    # assert preconditions
    assert isinstance(object.filepath, Path)
    assert object.lineno is not None
    assert object.docstring is not None
    assert object.docstring.lineno is not None
    
    # url to code
    source = f"{options.source_url}/{object.relative_package_filepath}#L{object.lineno}"

    # read function source code
    declaration = format_declaration(read_lines(object.filepath, object.lineno, object.docstring.lineno-1))

    # read docstrings
    docstrings = object.docstring.parse("google")

    # return
    return source, declaration, docstrings


def read_declaration(object: Object | Alias) -> str:
    assert isinstance(object.filepath, Path)
    assert object.lineno
    assert object.endlineno
    return format_declaration(read_lines(object.filepath, object.lineno, object.endlineno))

def read_lines(filename: Path, start_line: int, end_line: int) -> list[str]:
    with open(filename, 'r') as file:
        return list(islice(file, start_line-1, end_line))

def format_declaration(lines: list[str]) -> str:
    code = "".join(lines)
    return code.removesuffix(":\n")

   