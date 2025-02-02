import subprocess
from typing import cast
import griffe
from griffe import Module


from parse import DocFunction, DocParseOptions, parse_docs

def render_function(function: DocFunction) -> str:

    # build param list
    params: list[str] = []
    for param in function.parameters:

        # param and type annotation
        param_fmt = f"- {param.name} ({param.type}"
        
        # default value
        if param.required:
            param_fmt = f"{param_fmt})"
        else:
            param_fmt = f"{param_fmt}, default: {param.default})" 

        # description
        param_fmt = f"{param_fmt} - {param.description}"

        params.append(param_fmt)
    params_fmt = "\n".join(params)

    return f"{function.name}\n\n{function.description}\n\n{function.source}\n\n{function.declaration}\n\n{params_fmt}"
   


    

module= cast(Module,griffe.load("inspect_ai"))
sha = subprocess.run(["git", "rev-parse", "HEAD"],capture_output=True).stdout.decode().strip()
source_url = f"https://github.com/UKGovernmentBEIS/inspect_ai/blob/{sha}/src"


options = DocParseOptions(
    module=module,
    source_url=source_url
)

doc = parse_docs("solver.basic_agent", options)
if isinstance(doc, DocFunction):
    print(render_function(doc))

    