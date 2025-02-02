from itertools import islice
from pathlib import Path
from textwrap import dedent
import griffe
from griffe import Alias, Function, ParameterKind, Parser
import subprocess
inspect_ai = griffe.load("inspect_ai", docstring_parser=Parser.google)

sha = subprocess.run(["git", "rev-parse", "HEAD"],capture_output=True).stdout.decode().strip()

def read_lines(filename: Path, start_line: int, end_line: int) -> list[str]:
    with open(filename, 'r') as file:
        return list(islice(file, start_line-1, end_line))

def format_code(lines: list[str]) -> str:
    code = "".join(lines)
    return code.removesuffix(":\n")


def render_function(function: Function) -> str:
    
    # validate preconditions
    assert isinstance(function.filepath, Path)
    assert function.lineno is not None
    assert function.docstring is not None
    assert function.docstring.lineno is not None
    
    # parse docstrings
    sections = function.docstring.parse()
    function_description = sections[0].value
    parameter_descriptions: dict[str,str] = {}
    for p in  sections[1].value:
        description = p.description.strip()
        if ':' in description:
            description = description.split(':', 1)[1]
        parameter_descriptions[p.name] = description
     

    # url to code
    url = f"https://github.com/UKGovernmentBEIS/inspect_ai/blob/{sha}/src/{function.relative_package_filepath}#L{function.lineno}"

    # read function source code
    code_fmt = format_code(read_lines(function.filepath, function.lineno, function.docstring.lineno-1))

    # build param list
    params: list[str] = []
    for param in function.parameters:

        # param name w/ varargs prefix
        name = param.name

        # varargs prefix
        if param.kind == ParameterKind.var_positional:
            name = f"*{name}"
        elif param.kind == ParameterKind.var_keyword:
            name = f"**{name}"  

        # param and type annotation
        param_fmt = f"- {name} ({param.annotation.modernize()}"
        
        # default value
        if param.required:
            param_fmt = f"{param_fmt})"
        else:
            param_fmt = f"{param_fmt}, default: {param.default})" 

        # description
        param_fmt = f"{param_fmt} - {parameter_descriptions[name]}"

        params.append(param_fmt)
    params_fmt = "\n".join(params)

    return f"{function.name}\n\n{function_description}\n\n{url}\n\n{code_fmt}\n\n{params_fmt}"
   

def render_reference(path: str) -> str:
    # lookup object
    object = inspect_ai
    for segment in path.split("."):
        object = object.members[segment]

    # resolve aliases
    if isinstance(object, Alias):
        object = object.final_target
   
    # render
    if isinstance(object, Function):
        return render_function(object)
    else:
        raise ValueError(f"Reference object type ({type(object)}) for {path} is unsupported.")
    

print(render_reference("solver.basic_agent"))
   
    
       
    