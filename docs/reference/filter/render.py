

import panflute as pf # type: ignore
from parse import DocFunction, DocObject

# render reference elements
def render_docs(elem: pf.Element, docs: DocObject) -> list[pf.Element]:
   
    elements: list[pf.Element] = [elem]
    elements.append(pf.RawBlock(docs.description, "markdown"))

    # type specific rendering
    if isinstance(docs, DocFunction):
        elements.append(pf.CodeBlock(docs.declaration, classes = ["python"]))
    
    # return elements
    return elements