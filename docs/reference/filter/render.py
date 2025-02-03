

import panflute as pf # type: ignore
from parse import DocFunction, DocObject, DocParameter

# render reference elements
def render_docs(elem: pf.Element, docs: DocObject) -> list[pf.Element]:
   
    elements: list[pf.Element] = [elem]
    elements.append(pf.RawBlock(docs.description, "markdown"))

    # type specific rendering
    if isinstance(docs, DocFunction):

        # source link
        elements.append(pf.Div(pf.Plain(pf.Link(pf.Str("Source"), url=docs.source)), classes=["source-link"]))


        # declaration
        elements.append(pf.CodeBlock(docs.declaration, classes = ["python"]))

        # parameters
        elements.append(render_params(docs.parameters))
        
    
    # return elements
    return elements


def render_params(params: list[DocParameter]) -> pf.Table:
    return pf.Table(
        pf.TableBody(*[render_param(param) for param in params]),
        head=render_params_header()      
    )

def render_params_header() -> pf.TableHead:
    return pf.TableHead(
        pf.TableRow(
            pf.TableCell(pf.Plain(pf.Str("Argument"))),
            pf.TableCell(pf.Plain(pf.Str("Type"))),
            pf.TableCell(pf.Plain(pf.Str("Description")))
        )
    )

def render_param(param: DocParameter) -> pf.TableRow:
    return pf.TableRow(
        pf.TableCell(pf.Plain(pf.Str(param.name))),
        pf.TableCell(pf.Plain(pf.Str(param.type))),
        pf.TableCell(pf.Plain(pf.RawInline(param.description, format="markdown")))
    )
